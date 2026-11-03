---
title: Terraform foundations - state, network, ECR and GitHub OIDC
minutes: 60
objectives:
  - Lay out Terraform modules and per-environment roots with remote state
  - Create the VPC, the ECR repositories and the GitHub OIDC role
  - Explain the order of the first apply and the least privilege of the CI role
---
The Terraform folder teaches the language and state; this file applies it to the Shop on AWS in ap-south-1. The code is a teaching skeleton. Provider version is `{{v.aws_provider}}` at the time of writing; check the current provider docs for the exact arguments of the version you pin.

@concept Terraform layout for the Shop
@plain
Reusable modules in `infra/modules/`, and one small root folder per environment in `infra/envs/` that calls them.
@problem
Copying one big configuration per environment makes staging and prod drift apart.
@does
- Modules: `network`, `ecr`, `github_oidc`, `eks`, `database`, `cache`.
- Environment roots: `dev`, `staging`, `prod`, each with its own state key and `terraform.tfvars`.
- A one-time `bootstrap/` root creates the state bucket and lock table (or uses S3 native locking; check the current S3 backend docs).
- Apply order: bootstrap, network, ecr, oidc, eks, database, cache.
@diagram layers
caption: Terraform tree
layers:
  - {label: "infra/envs", nodes: ["dev|small|info", "staging|prod-like|warn", "prod|multi-AZ|ok"]}
  - {label: "infra/modules", nodes: ["network|VPC|app", "ecr|repositories|app", "github_oidc|CI role|app", "eks|cluster|app", "database|RDS|app", "cache|Redis|app"]}
  - {label: "infra/bootstrap", nodes: ["state bucket|versioned, encrypted|ok"]}
@end

@concept Remote state and providers
@plain
State is stored in a versioned, encrypted S3 bucket, with one key per environment.
@problem
State on a laptop is lost, cannot be shared and two people applying at once corrupt it.
@does
- Backend `s3` with `key = "shop/prod/terraform.tfstate"` and `encrypt = true`.
- The bucket has versioning (so a bad state can be rolled back) and blocks public access.
- Providers pin a version range; the lock file `.terraform.lock.hcl` is committed.
- Default tags (`project`, `env`, `owner`) are set once in the provider block for cost allocation.
@diagram flow
caption: Where state lives
nodes:
  - "terraform plan|CI or laptop|app"
  - "S3 backend|versioned bucket|cp"
  - "Lock|prevents concurrent apply|warn"
  - "State history|rollback possible|ok"
@h envs/prod/backend.tf and versions
```hcl title="infra/envs/prod/versions.tf"
terraform {
  required_version = ">= 1.9"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket       = "shop-tfstate-prod-123456789012"
    key          = "shop/prod/terraform.tfstate"
    region       = "ap-south-1"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project = "shop"
      env     = var.env
      owner   = "platform"
    }
  }
}
```
@end

@concept The network module
@plain
A VPC with three public and three private subnets, one NAT gateway per AZ in prod (one in dev), and tags that the AWS load balancer controller needs.
@problem
Databases and nodes belong in private subnets, but they still need outbound internet for image pulls and the payment gateway.
@does
- `cidrsubnet` carves /20 subnets from a /16: three public, three private.
- Prod uses a NAT per AZ so one AZ failure does not cut egress; dev uses a single NAT to save about 33 USD a month per NAT (cost file).
- Subnet tags `kubernetes.io/role/elb` and `kubernetes.io/role/internal-elb` let the controller place load balancers.
- Outputs: VPC ID, private subnet IDs, public subnet IDs, VPC CIDR.
@diagram layers
caption: Prod network, three AZs
layers:
  - {label: "Public subnets", nodes: ["ap-south-1a|ALB, NAT|info", "ap-south-1b|ALB, NAT|info", "ap-south-1c|ALB, NAT|info"]}
  - {label: "Private subnets", nodes: ["1a|nodes, RDS primary|cp", "1b|nodes, RDS standby|cp", "1c|nodes|cp"]}
@h modules/network/main.tf
```hcl title="infra/modules/network/main.tf"
variable "name" { type = string }
variable "cidr" { type = string }
variable "azs" { type = list(string) }
variable "single_nat" {
  type    = bool
  default = false
}
variable "cluster_name" { type = string }

resource "aws_vpc" "this" {
  cidr_block           = var.cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
}

resource "aws_subnet" "public" {
  count                   = length(var.azs)
  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.azs[count.index]
  cidr_block              = cidrsubnet(var.cidr, 4, count.index)
  map_public_ip_on_launch = true
  tags = {
    Name                                        = "${var.name}-public-${count.index}"
    "kubernetes.io/role/elb"                    = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_subnet" "private" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.this.id
  availability_zone = var.azs[count.index]
  cidr_block        = cidrsubnet(var.cidr, 4, count.index + 8)
  tags = {
    Name                                        = "${var.name}-private-${count.index}"
    "kubernetes.io/role/internal-elb"           = "1"
    "kubernetes.io/cluster/${var.cluster_name}" = "shared"
  }
}

resource "aws_eip" "nat" {
  count  = var.single_nat ? 1 : length(var.azs)
  domain = "vpc"
}

resource "aws_nat_gateway" "this" {
  count         = var.single_nat ? 1 : length(var.azs)
  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id
  depends_on    = [aws_internet_gateway.this]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
}

resource "aws_route_table_association" "public" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  count  = length(var.azs)
  vpc_id = aws_vpc.this.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[var.single_nat ? 0 : count.index].id
  }
}

resource "aws_route_table_association" "private" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[count.index].id
}

output "vpc_id" { value = aws_vpc.this.id }
output "vpc_cidr" { value = aws_vpc.this.cidr_block }
output "private_subnet_ids" { value = aws_subnet.private[*].id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
```
:::tip
For a production VPC with endpoints and flow logs, most teams use the community VPC module instead of maintaining this. The skeleton shows what such a module does inside.
:::
@end

@concept ECR repositories
@plain
One private ECR repository per image, with immutable tags, scan on push and a lifecycle policy that deletes old images.
@problem
Without a lifecycle rule, repositories grow forever and cost money. Mutable tags let someone overwrite a released image.
@does
- Repositories: `shop/catalog`, `shop/cart`, `shop/orders`, `shop/payments`, `shop/web`, `shop/upi-mock`.
- `image_tag_mutability = "IMMUTABLE"` blocks tag overwrites.
- Encryption with the default AWS-managed KMS key; use a customer key if policy requires it.
- Lifecycle: keep the 30 most recent images, expire untagged images after 7 days.
@diagram flow
caption: Image lifecycle in ECR
nodes:
  - "CI push|tag sha-abc1234|app"
  - "Scan on push|findings|warn"
  - "Immutable tag|cannot be replaced|ok"
  - "Lifecycle|keeps last 30|info"
@h modules/ecr/main.tf
```hcl title="infra/modules/ecr/main.tf"
variable "names" { type = list(string) }

resource "aws_ecr_repository" "this" {
  for_each             = toset(var.names)
  name                 = "shop/${each.key}"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each   = aws_ecr_repository.this
  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "expire untagged after 7 days"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "keep last 30 tagged"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["sha-"]
          countType     = "imageCountMoreThan"
          countNumber   = 30
        }
        action = { type = "expire" }
      }
    ]
  })
}

output "repository_arns" { value = { for k, r in aws_ecr_repository.this : k => r.arn } }
output "repository_urls" { value = { for k, r in aws_ecr_repository.this : k => r.repository_url } }
```
@end

@concept GitHub OIDC provider and CI role
@plain
AWS trusts GitHub's token issuer. A role trusts only tokens that come from our repository and branch or environment, and can only push to our ECR repositories.
@problem
Storing AWS access keys in GitHub secrets means long-lived credentials that leak and are never rotated. See the CI security chapter of the CI/CD folder for the full threat model.
@does
- One `aws_iam_openid_connect_provider` for `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`).
- The role's trust policy checks the `sub` claim, for example `repo:acme/shop:ref:refs/heads/main`. A wildcard on the whole organisation would let any repository assume the role.
- Permission policy: ECR login (`ecr:GetAuthorizationToken` on `*`, it cannot be scoped) plus push actions on the six repositories only.
- Cluster deploy is not allowed: Argo CD deploys (ADR 3).
@diagram seq
caption: Keyless push from GitHub
actors: ["Workflow|GitHub Actions|app", "GitHub OIDC|token issuer|cp", "AWS STS|trust check|ext", "ECR|registry|ext"]
steps:
  - "0>1: request ID token | req"
  - "1>0: JWT with sub | resp"
  - "0>2: AssumeRoleWithWebIdentity | tls"
  - "note 2..2: match sub and aud"
  - "2>0: temporary credentials | resp"
  - "0>3: push image | tls"
@h modules/github_oidc/main.tf
```hcl title="infra/modules/github_oidc/main.tf"
variable "repo" {
  type        = string
  description = "GitHub org/repo, for example acme/shop"
}
variable "ref" {
  type        = string
  description = "Allowed subject suffix, for example ref:refs/heads/main"
}
variable "ecr_repository_arns" { type = list(string) }
variable "create_provider" {
  type    = bool
  default = true
}

resource "aws_iam_openid_connect_provider" "github" {
  count          = var.create_provider ? 1 : 0
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_caller_identity" "me" {}

locals {
  provider_arn = "arn:aws:iam::${data.aws_caller_identity.me.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [local.provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repo}:${var.ref}"]
    }
  }
}

resource "aws_iam_role" "ci" {
  name               = "shop-ci-ecr-push"
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

data "aws_iam_policy_document" "push" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:InitiateLayerUpload",
      "ecr:UploadLayerPart",
      "ecr:CompleteLayerUpload",
      "ecr:PutImage",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = var.ecr_repository_arns
  }
}

resource "aws_iam_role_policy" "push" {
  role   = aws_iam_role.ci.id
  policy = data.aws_iam_policy_document.push.json
}

output "role_arn" { value = aws_iam_role.ci.arn }
```
:::warn
Use `StringEquals` on the exact subject. `StringLike` with `repo:acme/*` would allow every repository in the organisation, including a forked or new one, to push your images.
:::
@check
Why can `ecr:GetAuthorizationToken` not be scoped to one repository? || It is an account-level action, so AWS requires resource "*". Push rights are limited by the other statement.
@end

@concept A prod environment root
@plain
The root file wires the modules together and passes sizes from variables.
@problem
Without a single place that composes the modules, nobody knows what exists in prod.
@does
- Network and ECR are created first; their outputs feed EKS and the database in the next file.
- Different `terraform.tfvars` per environment change sizes only.
- Run `terraform fmt -check`, `validate` and `plan` in CI on every pull request; `apply` only from the protected branch with approval. The CI/CD folder covers the Terraform pipeline.
@diagram flow
caption: Module wiring
nodes:
  - "network|VPC and subnets|app"
  - "ecr|six repositories|app"
  - "github_oidc|push role|app"
  - "eks and database|next file|cp"
@h envs/prod/main.tf (first part)
```hcl title="infra/envs/prod/main.tf"
variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "env" {
  type    = string
  default = "prod"
}

locals {
  cluster_name = "shop-${var.env}"
  azs          = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
}

module "network" {
  source       = "../../modules/network"
  name         = local.cluster_name
  cidr         = "10.20.0.0/16"
  azs          = local.azs
  single_nat   = false
  cluster_name = local.cluster_name
}

module "ecr" {
  source = "../../modules/ecr"
  names  = ["catalog", "cart", "orders", "payments", "web", "upi-mock"]
}

module "github_oidc" {
  source              = "../../modules/github_oidc"
  repo                = "acme/shop"
  ref                 = "ref:refs/heads/main"
  ecr_repository_arns = values(module.ecr.repository_arns)
}
```
```bash title="First apply" lab
cd infra/envs/prod
terraform init
terraform fmt -check -recursive ../..
terraform validate
terraform plan -out=tfplan
```
@end
