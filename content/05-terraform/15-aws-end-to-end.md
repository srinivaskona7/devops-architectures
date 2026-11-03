---
title: End-to-end AWS example with VPC, EKS and RDS
minutes: 60
objectives:
  - Lay out a repository with small modules for network, cluster and database
  - Wire the modules together and configure IRSA or Pod Identity style access
  - Plan the order of apply, outputs and a safe path to production
---
This section builds a realistic shape: a VPC, an EKS cluster and an RDS PostgreSQL database for a shop application, split into small modules and composed in an environment folder. The code is a teaching skeleton. Check the current module and provider docs for the exact inputs of the versions you use.

@concept Repository layout and plan
@plain
One `modules/` folder with three modules and one `envs/<name>` folder per environment that composes them.
@problem
A single 1000-line main.tf cannot be reused for staging, and nobody can review it.
@does
- `modules/network` creates the VPC, subnets, route tables and NAT.
- `modules/eks` creates the cluster and a managed node group from subnet IDs.
- `modules/database` creates RDS Postgres in private subnets with its security group.
- `envs/dev` and `envs/prod` call these with different sizes, each with its own state key.
@diagram layers
caption: Repository for the shop platform
layers:
  - {label: "Environments", nodes: ["envs/dev|small, one NAT|info", "envs/prod|3 AZs, multi-AZ DB|warn"]}
  - {label: "Modules", nodes: ["network|VPC and subnets|app", "eks|cluster and nodes|app", "database|RDS Postgres|app"]}
  - {label: "Foundations", nodes: ["state bucket|S3 with locking|ok", "OIDC role|CI identity|ok"]}
@h Tree
```text title="Layout" nocheck
infra/
  modules/network/   main.tf variables.tf outputs.tf versions.tf
  modules/eks/       main.tf variables.tf outputs.tf versions.tf
  modules/database/  main.tf variables.tf outputs.tf versions.tf
  envs/dev/          main.tf backend.tf versions.tf terraform.tfvars
  envs/prod/         main.tf backend.tf versions.tf terraform.tfvars
```
@end

@concept The network module
@plain
The network module creates a VPC with public subnets (load balancers, NAT) and private subnets (nodes, database) in each availability zone.
@problem
Kubernetes and databases need private address space, internet egress through NAT, and subnet tags so the AWS load balancer controller finds the right subnets.
@does
- Uses `cidrsubnet` to carve subnets from the VPC range, keyed by AZ with `for_each`.
- Tags subnets with `kubernetes.io/role/elb` (public) and `kubernetes.io/role/internal-elb` (private).
- Outputs the VPC ID and lists of subnet IDs.
- In production, prefer the community VPC module if you need VPC endpoints, flow logs and many options; the small version shows the idea.
@diagram flow
caption: Network layout
nodes:
  - "VPC|10.0.0.0/16|app"
  - "Public subnets|ALB, NAT per AZ|info"
  - "Private subnets|nodes and RDS|cp"
  - "Internet gateway and NAT|egress|ext"
@h modules/network/main.tf
```hcl title="modules/network/main.tf"
resource "aws_vpc" "this" {
  cidr_block           = var.cidr_block
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
}

resource "aws_subnet" "public" {
  for_each = { for i, az in var.azs : az => i }

  vpc_id                  = aws_vpc.this.id
  availability_zone       = each.key
  cidr_block              = cidrsubnet(var.cidr_block, 4, each.value)
  map_public_ip_on_launch = true

  tags = {
    Name                     = "${var.name}-public-${each.key}"
    "kubernetes.io/role/elb" = "1"
  }
}

resource "aws_subnet" "private" {
  for_each = { for i, az in var.azs : az => i }

  vpc_id            = aws_vpc.this.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(var.cidr_block, 4, each.value + 8)

  tags = {
    Name                              = "${var.name}-private-${each.key}"
    "kubernetes.io/role/internal-elb" = "1"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}
```
@check
Why key subnets by AZ rather than using count? || Keys are stable, so adding or removing a zone does not reshuffle the others.
@end

@concept NAT and the network outputs
@plain
Private subnets need a NAT gateway to reach the internet for image pulls and updates. NAT gateways cost money per hour, so dev often uses one and prod one per AZ.
@problem
A NAT gateway per AZ costs about as much as small instances each, but a single NAT is a single AZ point of failure.
@does
- A boolean `single_nat_gateway` selects the number of gateways.
- Each private route table points to a NAT in the same AZ in production, to avoid cross-AZ traffic and failure coupling.
- VPC endpoints for S3 and ECR reduce NAT traffic cost; add them when volumes are high.
- Outputs let other modules consume the IDs.
@diagram cmp
caption: One NAT or one per AZ
cards:
  - {h: "Single NAT", kind: warn, items: ["Cheap for dev", "AZ failure cuts egress"]}
  - {h: "NAT per AZ", kind: ok, items: ["Resilient for prod", "Higher monthly cost"]}
@h NAT and outputs
```hcl title="modules/network/nat.tf"
locals {
  nat_azs = var.single_nat_gateway ? [var.azs[0]] : var.azs
}

resource "aws_eip" "nat" {
  for_each = toset(local.nat_azs)
  domain   = "vpc"
}

resource "aws_nat_gateway" "this" {
  for_each      = toset(local.nat_azs)
  allocation_id = aws_eip.nat[each.key].id
  subnet_id     = aws_subnet.public[each.key].id

  depends_on = [aws_internet_gateway.this]
}

resource "aws_route_table" "private" {
  for_each = aws_subnet.private
  vpc_id   = aws_vpc.this.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.this[var.single_nat_gateway ? var.azs[0] : each.key].id
  }
}

resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}
```
```hcl title="modules/network/outputs.tf"
output "vpc_id" {
  value = aws_vpc.this.id
}

output "private_subnet_ids" {
  value = [for az in sort(keys(aws_subnet.private)) : aws_subnet.private[az].id]
}

output "public_subnet_ids" {
  value = [for az in sort(keys(aws_subnet.public)) : aws_subnet.public[az].id]
}
```
```hcl title="modules/network/variables.tf"
variable "name" {
  type        = string
  description = "Name prefix for the VPC and its subnets"
}

variable "cidr_block" {
  type        = string
  description = "VPC range, for example 10.20.0.0/16"
}

variable "azs" {
  type        = list(string)
  description = "Availability zones to use, one public and one private subnet each"
}

variable "single_nat_gateway" {
  type        = bool
  default     = true
  description = "One shared NAT gateway (dev) or one per zone (prod)"
}
```
@end

@concept The EKS module
@plain
The EKS module creates the control plane, its IAM role, a managed node group, and an OIDC provider so pods can use IAM roles (IRSA).
@problem
EKS needs several pieces of IAM, networking and add-ons that must be wired correctly; getting them wrong yields clusters that never become ready.
@does
- Cluster role with `AmazonEKSClusterPolicy`; node role with worker node, CNI and ECR read policies.
- Control plane in the private subnets; choose public or private API endpoint access carefully.
- Managed node group scales between min and max, with Kubernetes version set explicitly.
- For many options (access entries, add-ons, Karpenter, encryption) most teams adopt the community `terraform-aws-modules/eks/aws` module instead of writing this by hand.
@diagram flow
caption: Cluster building blocks
nodes:
  - "Cluster IAM role|control plane permissions|cp"
  - "aws_eks_cluster|API server in private subnets|app"
  - "Node group|managed EC2 nodes|app"
  - "OIDC provider|IRSA for pods|info"
@h Core resources
```hcl title="modules/eks/main.tf"
data "aws_iam_policy_document" "eks_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${var.name}-cluster"
  assume_role_policy = data.aws_iam_policy_document.eks_assume.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "this" {
  name     = var.name
  version  = var.kubernetes_version
  role_arn = aws_iam_role.cluster.arn

  vpc_config {
    subnet_ids              = var.private_subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.public_endpoint
  }

  access_config {
    authentication_mode = "API"
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}
```
@check
Why does the cluster resource depend_on the policy attachment? || The role must have its permissions before EKS uses it; there is no attribute reference that expresses this order.
@end

@concept EKS node group and IRSA
@plain
Worker nodes come from a managed node group. IRSA (IAM Roles for Service Accounts) lets a Kubernetes service account assume an IAM role through the cluster's OIDC provider.
@problem
Pods that call AWS APIs should not share the node's instance role, which would give every pod the same wide permissions.
@does
- Node role needs worker node, CNI and ECR read-only policies.
- The cluster's OIDC issuer URL is registered as an IAM OIDC provider; a role's trust policy then matches the service account `sub`.
- Newer EKS Pod Identity is an alternative with simpler setup; check the current AWS docs for which fits your version and add-ons.
- The `lifecycle { ignore_changes = [scaling_config[0].desired_size] }` rule lets the autoscaler own the desired size.
@diagram flow
caption: A pod gets AWS access through IRSA
nodes:
  - "Pod|service account shop-api|app"
  - "Cluster OIDC|signs the token|cp"
  - "IAM role|trust matches the service account|info"
  - "S3 or SQS|least privilege access|ok"
@h Node group and OIDC provider
```hcl title="modules/eks/nodes.tf"
data "aws_iam_policy_document" "node_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "node" {
  name               = "${var.name}-node"
  assume_role_policy = data.aws_iam_policy_document.node_assume.json
}

resource "aws_iam_role_policy_attachment" "node" {
  for_each = toset([
    "arn:aws:iam::aws:policy/AmazonEKSWorkerNodePolicy",
    "arn:aws:iam::aws:policy/AmazonEKS_CNI_Policy",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.node.name
  policy_arn = each.value
}

resource "aws_eks_node_group" "default" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "default"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  instance_types  = var.instance_types

  scaling_config {
    min_size     = var.min_size
    max_size     = var.max_size
    desired_size = var.min_size
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}

data "tls_certificate" "oidc" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "cluster" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.oidc.certificates[0].sha1_fingerprint]
}
```
```hcl title="modules/eks/outputs.tf"
output "cluster_name" {
  value = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  value = aws_eks_cluster.this.endpoint
}

output "oidc_provider_arn" {
  value = aws_iam_openid_connect_provider.cluster.arn
}
```

```hcl title="modules/eks/outputs.tf (addition)"
output "node_security_group_id" {
  description = "Security group attached to managed node group instances"
  value       = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id
}
```
```hcl title="modules/eks/variables.tf"
variable "name" {
  type = string
}

variable "kubernetes_version" {
  type        = string
  description = "EKS version, check which versions EKS currently supports"
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "instance_types" {
  type    = list(string)
  default = ["m6i.large"]
}

variable "min_size" {
  type    = number
  default = 2
}

variable "max_size" {
  type    = number
  default = 6
}

variable "public_endpoint" {
  type        = bool
  default     = false
  description = "Expose the Kubernetes API publicly"
}
```
:::note
Without a custom launch template, managed node group instances use the cluster security group that EKS creates, so that is what the output exposes. If you add a launch template with its own security group, output that one instead.
:::
@end

@concept The RDS database module
@plain
The database module creates a PostgreSQL instance in private subnets, reachable only from the cluster's nodes, with the master password managed by AWS Secrets Manager.
@problem
Databases hold the data. They need encryption, backups, no public access, and a password that never appears in Terraform code or state.
@does
- A DB subnet group in the private subnets and a security group that allows port 5432 only from a given source security group.
- `manage_master_user_password = true` makes RDS create and rotate the secret in Secrets Manager; Terraform never sees the value.
- `storage_encrypted`, `backup_retention_period`, `deletion_protection` and `multi_az` are inputs with safe defaults.
- `lifecycle { prevent_destroy = true }` blocks accidental deletion; remove it deliberately when decommissioning.
@diagram flow
caption: Private database with managed secret
nodes:
  - "EKS nodes|source security group|app"
  - "Security group|allows 5432 from nodes|cp"
  - "RDS Postgres|private subnets, encrypted|ok"
  - "Secrets Manager|managed master password|info"
@h modules/database/main.tf
```hcl title="modules/database/main.tf"
resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "db" {
  name   = "${var.name}-db"
  vpc_id = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "from_app" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = var.app_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_instance" "this" {
  identifier        = var.name
  engine            = "postgres"
  engine_version    = var.engine_version
  instance_class    = var.instance_class
  allocated_storage = var.allocated_storage
  storage_encrypted = true
  multi_az          = var.multi_az

  db_name                     = "shop"
  username                    = "shopadmin"
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]

  backup_retention_period   = var.backup_days
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"

  lifecycle {
    prevent_destroy = true
  }
}
```
```hcl title="modules/database/variables.tf"
variable "name" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "app_security_group_id" {
  type        = string
  description = "Source security group allowed to reach port 5432"
}

variable "engine_version" {
  type    = string
  default = "16"
}

variable "instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "allocated_storage" {
  type    = number
  default = 50
}

variable "multi_az" {
  type    = bool
  default = false
}

variable "backup_days" {
  type    = number
  default = 7
}

variable "deletion_protection" {
  type    = bool
  default = true
}
```
```hcl title="modules/database/outputs.tf"
output "endpoint" {
  value = aws_db_instance.this.endpoint
}

output "secret_arn" {
  description = "Secrets Manager secret holding the managed master password"
  value       = aws_db_instance.this.master_user_secret[0].secret_arn
}
```
@check
How does the password avoid appearing in state? || RDS manages it in Secrets Manager (manage_master_user_password), so Terraform only stores the secret ARN.
@end

@concept Composing the environment
@plain
The environment folder is the only place that knows about all modules. It passes outputs of one module as inputs of the next.
@problem
Hidden coupling between modules makes changes unpredictable. The root should show the whole picture on one screen.
@does
- Calls network, eks, database in that order of dependency (Terraform infers it from references).
- Differences between dev and prod are values: AZ count, instance size, Multi-AZ, deletion protection.
- Outputs the cluster name, so a follow-up `aws eks update-kubeconfig` works.
- Backend key is unique per environment.
@diagram flow
caption: Outputs feed inputs
nodes:
  - "network|vpc_id, subnet ids|app"
  - "eks|cluster, node SG|app"
  - "database|endpoint, secret ARN|app"
  - "Root env|wires everything|cp"
@h envs/prod/main.tf
```hcl title="envs/prod/main.tf"
module "network" {
  source = "../../modules/network"

  name               = "shop-prod"
  cidr_block         = "10.20.0.0/16"
  azs                = ["eu-west-1a", "eu-west-1b", "eu-west-1c"]
  single_nat_gateway = false
}

module "eks" {
  source = "../../modules/eks"

  name               = "shop-prod"
  kubernetes_version = "{{v.eks_to}}"
  private_subnet_ids = module.network.private_subnet_ids
  instance_types     = ["m6i.large"]
  min_size           = 3
  max_size           = 9
  public_endpoint    = false
}

module "database" {
  source = "../../modules/database"

  name                  = "shop-prod"
  vpc_id                = module.network.vpc_id
  private_subnet_ids    = module.network.private_subnet_ids
  app_security_group_id = module.eks.node_security_group_id
  engine_version        = "16"
  instance_class        = "db.m6g.large"
  allocated_storage     = 100
  multi_az              = true
  backup_days           = 14
  deletion_protection   = true
}

output "cluster_name" {
  value = module.eks.cluster_name
}

output "db_endpoint" {
  value = module.database.endpoint
}
```
:::note
Kubernetes versions move fast. Use a version that EKS currently supports; check the EKS documentation.
:::
@end

@concept Apply order, kubeconfig and handing over to GitOps
@plain
First apply creates the network, cluster and database. Afterwards you connect with kubectl and let GitOps (Argo CD or Flux) manage workloads inside the cluster.
@problem
Mixing cluster creation and application deployments in one Terraform state creates provider ordering problems and slow plans.
@does
- First apply: `terraform apply` takes around 15 to 25 minutes, mostly EKS and RDS.
- Connect: `aws eks update-kubeconfig --name shop-prod --region eu-west-1`.
- Terraform stops at the platform boundary (cluster, add-on IAM roles, database). Argo CD or Flux bootstraps once and deploys everything else from Git.
- Store DB endpoint and secret ARN as outputs; the app reads the secret through External Secrets or the CSI driver.
@diagram flow
caption: Terraform builds the platform, GitOps runs the workloads
numbered: true
nodes:
  - "terraform apply|VPC, EKS, RDS|cp"
  - "update-kubeconfig|kubectl access|info"
  - "Bootstrap Argo CD|one-time|app"
  - "Git is source of truth|apps deployed from manifests|ok"
@h Commands
```bash title="After the first apply" lab
terraform output
aws eks update-kubeconfig --name shop-prod --region eu-west-1
kubectl get nodes
aws secretsmanager list-secrets --query 'SecretList[?starts_with(Name, `rds!`)].Name'
```
:::tip
Destroying the stack is the reverse: remove `prevent_destroy` and `deletion_protection` in a reviewed commit, apply, and only then destroy. Delete Kubernetes load balancers and volumes first or the VPC deletion will hang.
:::
@check
Why delete Kubernetes load balancers before destroying the VPC? || The controller created ENIs and load balancers outside Terraform; they block subnet and VPC deletion.
@end
