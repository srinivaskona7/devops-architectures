---
title: Amazon ECR registries and image supply chain
minutes: 45
objectives:
  - Create repositories with immutable tags, encryption and least privilege access
  - Apply lifecycle policies, image scanning and replication
  - Use pull-through cache and VPC endpoints to make pulls fast and private
---
Amazon Elastic Container Registry (ECR) stores your container images and OCI artifacts. For EKS it is the default registry because nodes authenticate with IAM and pulls stay on the AWS network.

@concept Repositories and authentication
@plain
An ECR **registry** exists per account and Region (`111122223333.dkr.ecr.us-east-1.amazonaws.com`). Inside it you create one **repository** per image name.
@problem
Public registries rate-limit pulls and offer no IAM control. You need a private store that your cluster can reach without passwords.
@does
- `aws ecr get-login-password` gives a token valid for 12 hours that `docker login` or `helm registry login` uses.
- EKS nodes pull using their node role (`AmazonEC2ContainerRegistryReadOnly` or `AmazonEC2ContainerRegistryPullOnly`); no imagePullSecret is needed in the same account.
- Cross-account pulls need a repository policy allowing the other account plus an IAM policy on the puller.
- **Immutable tags** stop `1.4.2` from being overwritten; use them for release tags.
- Encryption at rest is automatic (AES-256) or with a KMS key set at creation.
@diagram seq
caption: Pushing and pulling an image
actors: ["CI job|build|app", "ECR|registry|cp", "Node|kubelet|env"]
steps:
  - "0>1: get-login-password | req"
  - "0>1: docker push web:1.4.2 | tls"
  - "2>1: node role authenticates | req"
  - "1>2: image layers | resp"
@h Create and push
```bash title="Create a repository and push" lab
aws ecr create-repository --repository-name shop/web \
  --image-tag-mutability IMMUTABLE \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=KMS
ACCT=$(aws sts get-caller-identity --query Account --output text)
REG=$ACCT.dkr.ecr.us-east-1.amazonaws.com
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin $REG
docker tag shop-web:1.4.2 $REG/shop/web:1.4.2
docker push $REG/shop/web:1.4.2
```
```hcl title="Terraform"
resource "aws_ecr_repository" "web" {
  name                 = "shop/web"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
  }
}
```
@check
Why use immutable tags? || A released tag always points at the same image, so deployments and audits are reproducible.
@end

@concept Lifecycle policies
@plain
A lifecycle policy deletes images automatically by age or count, based on rules you write.
@problem
CI pushes an image on every commit. Without cleanup you pay for thousands of old layers, and scans get noisy.
@does
- Rules have a priority, a `tagStatus` (`tagged`, `untagged`, `any`), optional `tagPrefixList` and a `countType` (`imageCountMoreThan`, `sinceImagePushed`).
- Preview the result with `start-lifecycle-policy-preview` before applying.
- Always keep recent release tags: retain by prefix such as `v` or `release-`.
- Images in use by running pods are not protected, so keep enough history to roll back.
@diagram flow
caption: Cleanup order
nodes:
  - "Rule 1|keep last 20 release tags|ok"
  - "Rule 2|expire untagged after 7 days|warn"
  - "Rule 3|expire CI tags after 30 days|bad"
@h Policy
```json title="lifecycle.json"
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Keep 20 release images",
      "selection": {"tagStatus": "tagged", "tagPrefixList": ["v"], "countType": "imageCountMoreThan", "countNumber": 20},
      "action": {"type": "expire"}
    },
    {
      "rulePriority": 2,
      "description": "Expire untagged after 7 days",
      "selection": {"tagStatus": "untagged", "countType": "sinceImagePushed", "countUnit": "days", "countNumber": 7},
      "action": {"type": "expire"}
    }
  ]
}
```
```bash title="Apply" nocheck
aws ecr put-lifecycle-policy --repository-name shop/web --lifecycle-policy-text file://lifecycle.json
```
@check
Why preview a lifecycle policy? || A wrong rule can delete images that are still deployed or needed for rollback.
@end

@concept Image scanning
@plain
ECR checks images for known vulnerabilities (CVEs). **Basic** scanning uses the open source Clair-based database; **enhanced** scanning uses Amazon Inspector for continuous scanning of OS and language packages.
@problem
Images age: a clean image today has a known CVE next month, so a one-off scan at build time is not enough.
@does
- Basic: scan on push or manually; results per tag.
- Enhanced: Inspector rescans when new CVEs appear and when the image is pulled recently (configurable duration); findings flow to Security Hub and EventBridge.
- Gate pipelines: fail the build for critical findings in your own scanner (Trivy, Grype) and use ECR for continuous monitoring.
- Pair with minimal base images (distroless, Alpine, Chainguard) to reduce findings.
@diagram flow
caption: Scanning in the pipeline
nodes:
  - "Build|image|app"
  - "Scan in CI|Trivy or Grype|warn"
  - "Push to ECR|scan on push|info"
  - "Inspector|continuous rescans|ok"
  - "Security Hub|findings|ext"
@h Enable and read
```bash title="Enhanced scanning and findings" nocheck
aws ecr put-registry-scanning-configuration --scan-type ENHANCED \
  --rules '[{"scanFrequency":"CONTINUOUS_SCAN","repositoryFilters":[{"filter":"shop/*","filterType":"WILDCARD"}]}]'
aws ecr describe-image-scan-findings --repository-name shop/web --image-id imageTag=1.4.2 \
  --query 'imageScanFindings.findingSeverityCounts'
```
@check
What does enhanced scanning add over basic? || Continuous rescans through Inspector, including language packages, with events and Security Hub integration.
@end

@concept Replication and cross-Region DR
@plain
ECR replicates images automatically to other Regions or accounts when they are pushed.
@problem
A regional outage must not stop you from pulling images in the DR Region, and cross-Region pulls are slow and cost data transfer.
@does
- Configured at the registry level with rules and optional repository filters.
- Only images pushed after the rule exists are replicated; use a script to copy older images.
- Pods in the DR cluster pull from the local replica registry hostname.
- Replication of repository policies, lifecycle policies and tags is separate: manage those in code in each Region.
@diagram flow
caption: Push once, pull anywhere
nodes:
  - "CI pushes|us-east-1|app"
  - "ECR primary|source repo|cp"
  - "Replication rule|eu-west-1|info"
  - "ECR replica|local pulls|ok"
@h Rule
```bash title="Cross-Region replication" nocheck
aws ecr put-replication-configuration --replication-configuration '{
  "rules":[{"destinations":[{"region":"eu-west-1","registryId":"111122223333"}],
            "repositoryFilters":[{"filter":"shop/","filterType":"PREFIX_MATCH"}]}]}'
```
@check
Are images pushed before the rule existed replicated? || No; only new pushes are replicated.
@end

@concept Pull-through cache
@plain
A pull-through cache rule makes ECR fetch and store images from an upstream registry (Docker Hub, Quay, GitHub Container Registry, registry.k8s.io, Amazon ECR Public, and others) on first pull.
@problem
Docker Hub rate limits break node scale-outs, and arbitrary public images carry supply-chain risk.
@does
- Create a rule with a repository prefix such as `docker-hub` and the upstream URL; some upstreams need credentials stored in Secrets Manager.
- Pull `ACCT.dkr.ecr.REGION.amazonaws.com/docker-hub/library/nginx:1.27` and ECR caches it.
- Cached images are rescanned and periodically refreshed from upstream.
- Combine with an admission policy that allows only your registry domain.
@diagram flow
caption: First pull populates the cache
nodes:
  - "Node pulls|ECR prefix docker-hub|app"
  - "ECR|cache miss|cp"
  - "Docker Hub|upstream|ext"
  - "ECR cache|next pulls are local|ok"
@h Create
```bash title="Rule for Docker Hub" nocheck
aws secretsmanager create-secret --name ecr-pullthroughcache/docker-hub \
  --secret-string '{"username":"myuser","accessToken":"REPLACE_ME"}'
aws ecr create-pull-through-cache-rule --ecr-repository-prefix docker-hub \
  --upstream-registry-url registry-1.docker.io \
  --credential-arn arn:aws:secretsmanager:us-east-1:111122223333:secret:ecr-pullthroughcache/docker-hub-AbCdEf
```
@check
Why use a cache for public images? || It avoids rate limits and outages of the upstream registry and lets you scan the images.
@end

@concept Private access and permissions
@plain
Nodes in private subnets reach ECR either through a NAT gateway or through VPC endpoints. Endpoints avoid NAT data processing charges and keep image traffic private.
@problem
Pulling large images through NAT is expensive and sends AWS-internal traffic along an internet-bound path.
@does
- Create interface endpoints `com.amazonaws.<region>.ecr.api` and `ecr.dkr`, plus an S3 **gateway** endpoint, because image layers are served from S3.
- Allow HTTPS (443) from the node security groups to the endpoints.
- Use repository policies with conditions (`aws:PrincipalOrgID`) to share images inside an organisation.
- CI roles need push permissions only on their repositories, never `ecr:*` on all resources.
@diagram layers
caption: Private image pulls
layers:
  - {label: "Private subnet", nodes: ["Node|kubelet|app"]}
  - {label: "VPC endpoints", nodes: ["ecr.api|auth and manifests|info", "ecr.dkr|registry|info", "S3 gateway|layers|info"]}
  - {label: "AWS", nodes: ["ECR|images|cp"]}
@h Least privilege for CI
```json title="CI push policy"
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "ecr:GetAuthorizationToken", "Resource": "*"},
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability", "ecr:InitiateLayerUpload", "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload", "ecr:PutImage", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"
      ],
      "Resource": "arn:aws:ecr:us-east-1:111122223333:repository/shop/*"
    }
  ]
}
```
@check
Why is an S3 gateway endpoint part of private ECR access? || ECR serves image layers from S3, so layer downloads need an S3 path.
@end
