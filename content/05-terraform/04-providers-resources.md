---
title: Providers, resources and data sources
minutes: 45
objectives:
  - Configure and version providers, including several regions or accounts with aliases
  - Declare resources and read existing infrastructure with data sources
  - Use the lock file and version constraints to keep runs reproducible
---
Terraform itself knows nothing about AWS or Kubernetes. Plugins called **providers** translate HCL into API calls. This section covers how they are chosen, pinned and used.

@concept What a provider is
@plain
A provider is a plugin binary that knows one API: AWS, Azure, Google Cloud, Kubernetes, Helm, GitHub, Datadog and thousands more. It defines the resource types and data sources you can write.
@problem
One tool cannot hard-code every vendor's API. Plugins let vendors ship support independently of Terraform's own release cycle.
@does
- `terraform init` downloads providers from a registry (registry.terraform.io, or registry.opentofu.org for OpenTofu).
- A source address looks like `hashicorp/aws`: namespace plus type.
- Each provider runs as a separate process and talks to Terraform over gRPC.
- Resource type names start with the provider name: `aws_`, `azurerm_`, `google_`, `kubernetes_`.
@diagram flow
caption: Terraform core delegates to providers
nodes:
  - "Terraform core|graph, plan, state|cp"
  - "Provider plugin|aws, azurerm, google|info"
  - "Cloud API|HTTPS calls|ext"
  - "Resources|real infrastructure|ok"
@h Declaring providers
```hcl title="versions.tf"
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
    }
  }
}

provider "aws" {
  region = "eu-west-1"
}
```
@end

@concept Version constraints and the lock file
@plain
`version = "~> 6.0"` allows any 6.x but not 7.0. The first `init` records the exact versions chosen, with checksums, in `.terraform.lock.hcl`.
@problem
A provider upgrade can change behaviour. Without pinning, the same code could plan differently tomorrow than today.
@does
- Operators: `=`, `!=`, `>`, `>=`, `<`, `<=` and `~>` (pessimistic: only the last digit given may rise).
- **Commit** `.terraform.lock.hcl` so everyone and CI use identical provider builds.
- `terraform init -upgrade` moves to the newest allowed versions; review that as a pull request.
- `terraform providers lock -platform=linux_amd64 -platform=darwin_arm64` adds checksums for several platforms, which avoids CI-only lock failures.
@diagram seq
caption: Lock file keeps versions stable
actors: ["Dev laptop|macOS|app", "Git|lock file committed|info", "CI|linux runner|cp"]
steps:
  - "0>0: init writes lock file | req"
  - "0>1: commit and push | req"
  - "1>2: checkout | req"
  - "2>2: init uses same version | resp"
@h Commands
```bash title="Lock file operations" lab
terraform init
terraform init -upgrade
terraform providers lock -platform=linux_amd64 -platform=darwin_arm64
git add .terraform.lock.hcl
```
@check
What does `~> 6.0` allow? || Any 6.x release at or above 6.0, but not 7.0.
@end

@concept Provider configuration and authentication
@plain
The `provider` block sets region, endpoints and credentials. Credentials should come from the environment or an assumed role, not from the code.
@problem
Access keys in `.tf` files end up in Git and in state.
@does
- AWS provider searches env vars (`AWS_ACCESS_KEY_ID`, `AWS_PROFILE`), shared config files, SSO, and instance or OIDC roles in that general order.
- `assume_role` makes Terraform call STS and work in another account.
- `default_tags` applies tags to every taggable resource automatically.
- In CI, use short-lived OIDC credentials (covered later).
@diagram layers
caption: Where credentials can come from
layers:
  - {label: "Best", nodes: ["OIDC role|CI, short lived|ok", "SSO profile|developer laptop|ok"]}
  - {label: "Acceptable", nodes: ["Instance or pod role|runs inside AWS|info"]}
  - {label: "Avoid", nodes: ["Static keys in .tf|leaks to Git and state|bad"]}
@h Example
```hcl title="provider.tf"
provider "aws" {
  region = var.region

  assume_role {
    role_arn = "arn:aws:iam::111122223333:role/terraform-deploy"
  }

  default_tags {
    tags = {
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}
```
:::danger
Never write `access_key` and `secret_key` in a provider block.
:::
@end

@concept Provider aliases and multiple regions
@plain
An **alias** gives a second configuration of the same provider, for example another region or account. A resource picks one with `provider = aws.other`.
@problem
Some designs span regions (a CloudFront certificate must be in us-east-1) or accounts (a central logging account).
@does
- The default provider has no alias; extra ones are named: `provider "aws" { alias = "use1" ... }`.
- Resources opt in using `provider = aws.use1`.
- Modules receive providers explicitly through the `providers = { aws = aws.use1 }` argument.
- Dynamic region lists cannot be looped: each alias is static code. Newer provider versions add per-resource `region` arguments; check the current provider docs.
@diagram flow
caption: Two provider configurations, two regions
nodes:
  - "aws (default)|eu-west-1|app"
  - "aws.use1|us-east-1|info"
  - "Load balancer|uses default|ok"
  - "ACM certificate|uses aws.use1|ok"
@h Example
```hcl title="aliases"
provider "aws" {
  region = "eu-west-1"
}

provider "aws" {
  alias  = "use1"
  region = "us-east-1"
}

resource "aws_acm_certificate" "cdn" {
  provider          = aws.use1
  domain_name       = "shop.example.com"
  validation_method = "DNS"
}
```
@end

@concept Resources
@plain
A `resource` block declares one infrastructure object you want Terraform to create and manage. The type decides the arguments; the name is for referencing.
@problem
You need a stable handle on each object so Terraform can compare desired and actual state.
@does
- Arguments are inputs; **attributes** are values you can read, including ones set by the cloud (`id`, `arn`).
- Nested blocks configure sub-settings.
- Meta-arguments available on every resource: `count`, `for_each`, `depends_on`, `provider`, `lifecycle`.
- Changing some arguments forces replacement. The docs mark them as "Forces new resource".
@diagram cmp
caption: Parts of a resource
cards:
  - {h: "Arguments", kind: app, items: ["What you set", "cidr_block, tags"]}
  - {h: "Attributes", kind: info, items: ["What you can read", "id, arn, endpoint"]}
  - {h: "Meta-arguments", kind: cp, items: ["count, for_each", "depends_on, lifecycle"]}
  - {h: "Nested blocks", kind: ok, items: ["Sub-configuration", "ingress, versioning"]}
@h Example
```hcl title="ecr.tf"
resource "aws_ecr_repository" "shop" {
  name                 = "shop/api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

output "ecr_url" {
  value = aws_ecr_repository.shop.repository_url
}
```
@check
Where do you find which arguments force replacement? || In the provider documentation for that resource type, and in the plan output next to the changing attribute.
@end

@concept Implicit and explicit dependencies
@plain
When one resource references another, Terraform infers the order. When no reference exists but order matters, `depends_on` states it.
@problem
Sometimes a hidden relationship exists, such as an IAM policy that must be attached before a workload starts.
@does
- Prefer references. They are precise and show intent.
- `depends_on = [aws_iam_role_policy_attachment.x]` forces ordering without a data link.
- Heavy use of `depends_on` on modules or data sources can delay reads until apply and cause bigger plans; use it narrowly.
@diagram flow
caption: Hidden dependency made explicit
nodes:
  - "Role policy attachment|permission granted|app"
  - "depends_on|ordering only|cp"
  - "Lambda function|starts after|ok"
@h Example
```hcl title="depends_on"
resource "aws_lambda_function" "worker" {
  function_name = "shop-worker"
  role          = aws_iam_role.worker.arn
  runtime       = "python3.12"
  handler       = "app.handler"
  filename      = "worker.zip"

  depends_on = [aws_iam_role_policy_attachment.worker_logs]
}
```
@end

@concept The Kubernetes and Helm providers
@plain
Terraform can also create objects inside a cluster using the `kubernetes` and `helm` providers. They authenticate against the cluster's API.
@problem
Cluster add-ons (ingress controller, cert-manager) are needed straight after the cluster exists, and teams want one pipeline for both.
@does
- On EKS, fetch a short-lived token using `aws_eks_cluster_auth` or the `exec` block with `aws eks get-token`.
- `helm_release` installs a chart with values.
- Mixing cluster creation and in-cluster resources in the same state is fragile because the provider needs cluster details that do not exist yet. Split into two root modules, or hand over to Argo CD or Flux after bootstrap.
@diagram flow
caption: Two states avoid a chicken and egg problem
nodes:
  - "Stack 1|VPC and EKS|app"
  - "Outputs|endpoint and CA|info"
  - "Stack 2|Helm add-ons|cp"
  - "GitOps|apps via Argo CD|ok"
@h Provider configuration using exec
```hcl title="k8s provider"
provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", var.cluster_name]
    }
  }
}
```
:::tip
Check the current Helm provider documentation: the `kubernetes` block syntax changed between major versions.
:::
@end
