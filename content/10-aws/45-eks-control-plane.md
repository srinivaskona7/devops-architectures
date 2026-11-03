---
title: EKS control plane and cluster creation
minutes: 45
objectives:
  - Describe what AWS runs in the EKS control plane and what you run
  - Create a cluster with eksctl and Terraform
  - Control endpoint access and enable control plane logging
---
Amazon EKS is managed Kubernetes. AWS runs the API server and etcd; you run the nodes and everything on them. If you operate Kyma, you already know the Kubernetes layer; this section shows what is specific to AWS.

@concept What EKS manages
@plain
EKS runs the Kubernetes **control plane** (API servers, etcd, controller manager, scheduler) in an AWS-managed account, spread over multiple AZs. You pay a fixed hourly fee per cluster and manage worker capacity separately.
@problem
Running a highly available etcd and API server yourself means certificates, backups, upgrades and 3 AM incidents.
@does
- The API server runs as at least two instances across AZs behind a load balancer; etcd runs across three AZs. AWS scales and patches them.
- Worker nodes join through ENIs that EKS places in your subnets (the **cross-account ENIs**), which carry kubelet-to-API traffic.
- You choose the Kubernetes minor version; each version has a standard support period, then paid extended support (check the current EKS version calendar).
- Provisioned control plane tiers can raise API capacity for very large clusters (check current offerings).
@diagram layers
caption: Who owns which layer
layers:
  - {label: "AWS managed account", nodes: ["API server x2+|multi AZ|cp", "etcd x3|multi AZ|cp", "Scheduler and controllers|managed|cp"]}
  - {label: "Your VPC", nodes: ["Cross-account ENIs|in your subnets|info", "Managed node groups|EC2|app", "Fargate pods|serverless|app", "Karpenter nodes|EC2|app"]}
  - {label: "You operate", nodes: ["Add-ons|CoreDNS, CNI, CSI|env", "Workloads|your apps|env"]}
@h See it
```bash title="Describe a cluster" lab
aws eks describe-cluster --name shop-prod \
  --query 'cluster.{version:version,endpoint:endpoint,private:resourcesVpcConfig.endpointPrivateAccess,public:resourcesVpcConfig.endpointPublicAccess,platform:platformVersion}'
aws eks update-kubeconfig --name shop-prod --alias shop-prod
kubectl get nodes -o wide
```
@check
Where do you find etcd on an EKS cluster? || You do not; it runs in the AWS managed account and is not accessible to you.
@end

@concept Creating a cluster with eksctl
@plain
`eksctl` reads a YAML file and creates the cluster, its IAM roles, node groups and optional VPC through CloudFormation.
@problem
A cluster needs a VPC with tagged subnets, IAM roles, security groups, an OIDC provider and node groups. Doing it by hand through the console is slow and not repeatable.
@does
- Config files are declarative: `eksctl create cluster -f cluster.yaml`.
- It can reuse an existing VPC (`vpc.subnets`) or create a new one with public and private subnets across AZs.
- It creates the OIDC provider (`iam.withOIDC`) required for IRSA.
- Prefer a Terraform or CloudFormation pipeline for long-lived environments, and eksctl for labs and quick starts.
@diagram flow
caption: What eksctl creates
numbered: true
nodes:
  - "cluster.yaml|desired state|plain"
  - "CloudFormation stack|VPC, roles, control plane|info"
  - "Node group stack|ASG or managed group|app"
  - "kubeconfig|context added|ok"
@h Cluster file
```yaml title="cluster.yaml"
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: shop-prod
  region: us-east-1
  version: "{{v.eks_to}}"
iam:
  withOIDC: true
vpc:
  cidr: 10.20.0.0/16
  nat:
    gateway: HighlyAvailable
availabilityZones: ["us-east-1a", "us-east-1b", "us-east-1c"]
managedNodeGroups:
  - name: system
    instanceType: m6i.large
    minSize: 2
    maxSize: 4
    desiredCapacity: 2
    privateNetworking: true
    labels: {role: system}
cloudWatch:
  clusterLogging:
    enableTypes: ["api", "audit", "authenticator"]
```
```bash title="Create and check" nocheck
eksctl create cluster -f cluster.yaml
eksctl get cluster --region us-east-1
```
:::tip
Pick the Kubernetes version from `eksctl version` support or `aws eks describe-cluster-versions`; versions in examples age quickly.
:::
@check
Why does the config enable OIDC? || IRSA needs an IAM OIDC identity provider for the cluster so pods can assume roles.
@end

@concept Creating a cluster with Terraform
@plain
The community module `terraform-aws-modules/eks/aws` creates the cluster, IAM, security groups and node groups from variables.
@problem
Cluster creation must live in version control, be reviewed, and be reproducible for each environment.
@does
- The module takes `vpc_id`, `subnet_ids` (private subnets for nodes) and `control_plane_subnet_ids`.
- Access entries and add-ons are modelled as inputs so the whole platform stays declarative.
- State holds the cluster; protect it in an S3 bucket with locking.
@diagram flow
caption: Pipeline for cluster changes
nodes:
  - "Pull request|terraform plan|plain"
  - "Review|plan output|info"
  - "Apply|pipeline role|app"
  - "Cluster|updated|ok"
@h Module call
```hcl title="main.tf"
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = "shop-prod"
  cluster_version = "{{v.eks_to}}"
  vpc_id          = module.vpc.vpc_id
  subnet_ids      = module.vpc.private_subnets

  cluster_endpoint_public_access  = false
  cluster_endpoint_private_access = true
  enable_irsa                     = true

  cluster_enabled_log_types = ["api", "audit", "authenticator"]

  eks_managed_node_groups = {
    system = {
      instance_types = ["m6i.large"]
      min_size       = 2
      max_size       = 4
      desired_size   = 2
    }
  }
}
```
@check
Which subnets should nodes use? || Private subnets, with egress through NAT gateways or VPC endpoints.
@end

@concept API endpoint access
@plain
The Kubernetes API endpoint can be public, private or both. Private means it resolves to the ENIs in your VPC and is reachable only from the VPC or connected networks.
@problem
A public API endpoint exposed to 0.0.0.0/0 is attack surface. But a fully private one is unreachable from CI runners and laptops unless you plan connectivity.
@does
- **Public only** (default for new clusters): reachable from the internet, restrict with `publicAccessCidrs`.
- **Public and private**: nodes use the private path; admins use the public path from allowed CIDRs.
- **Private only**: reach it via VPN, Direct Connect, a bastion, or SSM port forwarding.
- Authentication still uses IAM; authorisation uses Kubernetes RBAC or access entries.
@diagram cmp
caption: Endpoint modes
cards:
  - {h: "Public", kind: warn, items: ["Easy for CI and laptops", "Restrict with CIDR list"]}
  - {h: "Public and private", kind: info, items: ["Nodes stay inside VPC", "Admins from allowed CIDRs"]}
  - {h: "Private", kind: ok, items: ["Smallest exposure", "Needs VPN or bastion"]}
@h Restrict it
```bash title="Lock down the endpoint" nocheck
aws eks update-cluster-config --name shop-prod \
  --resources-vpc-config endpointPublicAccess=true,publicAccessCidrs=203.0.113.0/24,endpointPrivateAccess=true
aws eks wait cluster-active --name shop-prod
```
@check
Do nodes need the public endpoint to join? || No; with private access enabled they reach the API through the VPC.
@end

@concept Control plane logging and audit
@plain
EKS can send five log types to CloudWatch Logs: api, audit, authenticator, controllerManager and scheduler.
@problem
When someone deletes a deployment or a role mapping breaks authentication, you need evidence of who did what.
@does
- Logs go to `/aws/eks/<cluster>/cluster`. They cost ingestion and storage, so set retention.
- **audit** records every API call with user and verb; **authenticator** shows IAM identity mapping failures.
- Query them with CloudWatch Logs Insights.
@diagram flow
caption: Audit log path
nodes:
  - "kubectl delete|IAM identity|app"
  - "API server|audit event|cp"
  - "CloudWatch Logs|/aws/eks/shop-prod/cluster|info"
  - "Logs Insights|who did it|ok"
@h Enable and query
```bash title="Enable audit logs and set retention" nocheck
aws eks update-cluster-config --name shop-prod \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator"],"enabled":true}]}'
aws logs put-retention-policy --log-group-name /aws/eks/shop-prod/cluster --retention-in-days 30
aws logs start-query --log-group-name /aws/eks/shop-prod/cluster \
  --start-time $(date -u -v-1H +%s) --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, user.username, verb, objectRef.resource, objectRef.name | filter verb = "delete" | sort @timestamp desc | limit 20'
```
@check
Which log type helps debug IAM identity to Kubernetes user mapping? || The authenticator log.
@end

@concept Cluster tags, networking requirements and sizing
@plain
EKS and its controllers find subnets through tags, and the cluster needs enough free IP addresses.
@problem
Missing subnet tags make load balancers fail to place, and small subnets run out of IPs when pods get VPC addresses.
@does
- Tag public subnets `kubernetes.io/role/elb=1` and private subnets `kubernetes.io/role/internal-elb=1`.
- Karpenter and the AWS Load Balancer Controller also use `karpenter.sh/discovery` or `kubernetes.io/cluster/<name>` tags.
- Because pods use VPC IPs, size subnets generously (for example /19 or larger for nodes) or add a secondary CIDR for pods.
- Use at least two AZs, preferably three, with one NAT gateway per AZ for production.
@diagram layers
caption: Subnet roles
layers:
  - {label: "Public subnets", nodes: ["ALB, NAT|tag elb=1|ext"]}
  - {label: "Private subnets", nodes: ["Nodes and pods|tag internal-elb=1|app", "Internal NLB|private services|env"]}
  - {label: "Data subnets", nodes: ["RDS, ElastiCache|no route to internet|cp"]}
@h Tag with CLI
```bash title="Tag a private subnet" nocheck
aws ec2 create-tags --resources subnet-0aaa subnet-0bbb subnet-0ccc \
  --tags Key=kubernetes.io/role/internal-elb,Value=1 Key=karpenter.sh/discovery,Value=shop-prod
```
@check
What happens if subnets lack the elb tags? || The Load Balancer Controller cannot auto-discover subnets and provisioning fails unless you list subnets explicitly.
@end
