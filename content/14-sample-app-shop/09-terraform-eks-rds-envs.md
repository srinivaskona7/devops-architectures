---
title: Terraform - EKS, RDS, Redis and environment sizing
minutes: 60
objectives:
  - Create an EKS cluster with managed node groups and IRSA or Pod Identity roles
  - Create a private multi-AZ RDS PostgreSQL and an ElastiCache Redis
  - Size dev, staging and prod and run a safe plan and apply workflow
---
This continues the Terraform files: the network, ECR and OIDC exist. Now the compute and data layers. Module inputs shown are a teaching subset; check the current AWS provider docs for the version you pin.

@concept EKS cluster module
@plain
An EKS control plane, the IAM role it needs, an OIDC issuer for pod identities, and the control plane log types turned on.
@problem
Clusters created by hand cannot be reproduced for staging or recovered after an incident.
@does
- Private subnets for the control plane network interfaces; the API endpoint is public but restricted by CIDR in dev and private-only in prod behind VPN.
- Enabled log types: `api`, `audit`, `authenticator` (they go to CloudWatch, which costs money; see the cost file).
- Version is a variable (`{{v.eks_from}}` in the upgrade chapter changes to `{{v.eks_to}}`). Check the current EKS version calendar for support windows.
- Output the OIDC issuer URL for IRSA roles.
@diagram flow
caption: Cluster pieces
nodes:
  - "Cluster IAM role|EKS service|ext"
  - "EKS control plane|managed by AWS|cp"
  - "OIDC issuer|for pod roles|info"
  - "Node groups|worker nodes|app"
@h modules/eks/main.tf
```hcl title="infra/modules/eks/main.tf"
variable "name" { type = string }
variable "kubernetes_version" { type = string }
variable "subnet_ids" { type = list(string) }
variable "public_access_cidrs" {
  type    = list(string)
  default = []
}
variable "endpoint_public" {
  type    = bool
  default = false
}

data "aws_iam_policy_document" "cluster_trust" {
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
  assume_role_policy = data.aws_iam_policy_document.cluster_trust.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEKSClusterPolicy"
}

resource "aws_eks_cluster" "this" {
  name     = var.name
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = var.subnet_ids
    endpoint_private_access = true
    endpoint_public_access  = var.endpoint_public
    public_access_cidrs     = var.endpoint_public ? var.public_access_cidrs : null
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator"]

  access_config {
    authentication_mode = "API"
  }

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

data "tls_certificate" "oidc" {
  url = aws_eks_cluster.this.identity[0].oidc[0].issuer
}

resource "aws_iam_openid_connect_provider" "cluster" {
  url             = aws_eks_cluster.this.identity[0].oidc[0].issuer
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.oidc.certificates[0].sha1_fingerprint]
}

output "name" { value = aws_eks_cluster.this.name }
output "endpoint" { value = aws_eks_cluster.this.endpoint }
output "oidc_provider_arn" { value = aws_iam_openid_connect_provider.cluster.arn }
output "oidc_issuer" { value = aws_eks_cluster.this.identity[0].oidc[0].issuer }
output "security_group_id" { value = aws_eks_cluster.this.vpc_config[0].cluster_security_group_id }
```
@end

@concept Managed node groups
@plain
A node group is a set of EC2 instances that EKS creates, patches and replaces for you.
@problem
Hand-built nodes drift, lack the right IAM policies and are painful to upgrade.
@does
- One node group per environment with `min`, `desired` and `max` sizes; the Cluster Autoscaler or Karpenter changes the desired size (check which one your platform team runs).
- Instance type `m6i.large` (2 vCPU, 8 GiB) in prod; `t3.medium` in dev.
- Update config `max_unavailable = 1` makes node upgrades roll one node at a time.
- Node role policies: worker node, CNI and ECR read-only.
@diagram layers
caption: Prod nodes across AZs
layers:
  - {label: "Managed node group shop-prod-default", nodes: ["node 1a|m6i.large|app", "node 1b|m6i.large|app", "node 1c|m6i.large|app"]}
  - {label: "Scaling bounds", nodes: ["min 3|one per AZ|ok", "max 6|cost cap|warn"]}
@h modules/eks/nodes.tf
```hcl title="infra/modules/eks/nodes.tf"
variable "node_instance_types" {
  type    = list(string)
  default = ["m6i.large"]
}
variable "node_min" {
  type    = number
  default = 3
}
variable "node_desired" {
  type    = number
  default = 3
}
variable "node_max" {
  type    = number
  default = 6
}

data "aws_iam_policy_document" "node_trust" {
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
  assume_role_policy = data.aws_iam_policy_document.node_trust.json
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
  subnet_ids      = var.subnet_ids
  instance_types  = var.node_instance_types

  scaling_config {
    min_size     = var.node_min
    desired_size = var.node_desired
    max_size     = var.node_max
  }

  update_config {
    max_unavailable = 1
  }

  lifecycle {
    ignore_changes = [scaling_config[0].desired_size]
  }

  depends_on = [aws_iam_role_policy_attachment.node]
}
```
:::note
`ignore_changes` on `desired_size` stops Terraform from fighting the autoscaler on every plan.
:::
@end

@concept Cluster add-ons and access
@plain
Add-ons such as the VPC CNI, CoreDNS, kube-proxy and the EBS CSI driver are managed as `aws_eks_addon`. People get access through EKS access entries.
@problem
Unmanaged add-ons fall behind on versions and block cluster upgrades. A shared admin kubeconfig has no audit trail.
@does
- Core add-ons are pinned by the platform team and bumped during the upgrade runbook.
- Access entries map an IAM role (SSO role for engineers) to a cluster access policy (view, edit, admin) per namespace.
- CI has no cluster access; Argo CD runs inside and applies manifests.
- The AWS Load Balancer Controller and External Secrets operator are installed by Argo CD from the platform repository (see the Kustomize files); chart versions such as the load balancer controller `{{v.aws_lb_controller_chart}}` change often, so check the current docs.
@diagram flow
caption: Who can reach the API
nodes:
  - "Engineer SSO role|access entry|ext"
  - "EKS API|authz by policy|cp"
  - "Namespace shop|edit or view|app"
  - "Audit log|CloudWatch|ok"
@h Add-ons and access entries
```hcl title="infra/modules/eks/addons.tf"
variable "addons" {
  type    = list(string)
  default = ["vpc-cni", "coredns", "kube-proxy", "aws-ebs-csi-driver"]
}
variable "admin_role_arns" {
  type    = list(string)
  default = []
}

resource "aws_eks_addon" "this" {
  for_each                    = toset(var.addons)
  cluster_name                = aws_eks_cluster.this.name
  addon_name                  = each.key
  resolve_conflicts_on_update = "OVERWRITE"
  depends_on                  = [aws_eks_node_group.default]
}

resource "aws_eks_access_entry" "admin" {
  for_each      = toset(var.admin_role_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
}

resource "aws_eks_access_policy_association" "admin" {
  for_each      = toset(var.admin_role_arns)
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = each.value
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"

  access_scope {
    type = "cluster"
  }

  depends_on = [aws_eks_access_entry.admin]
}
```
@end

@concept IRSA role for External Secrets
@plain
IAM Roles for Service Accounts lets one Kubernetes service account assume one AWS role through the cluster's OIDC issuer. EKS Pod Identity is the newer alternative; check the current docs for which your platform standardises on.
@problem
Pods that use the node's IAM role give every pod on the node the same AWS permissions.
@does
- The role trusts the cluster OIDC provider, restricted to the subject `system:serviceaccount:external-secrets:external-secrets`.
- Policy: read only `shop/*` secrets in Secrets Manager, nothing else.
- The service account gets the annotation `eks.amazonaws.com/role-arn`.
- The same pattern gives the AWS Load Balancer Controller its own role.
@diagram seq
caption: Pod to Secrets Manager without keys
actors: ["Pod|external-secrets|app", "EKS OIDC|projected token|cp", "AWS STS|trust check|ext", "Secrets Manager|shop secrets|ext"]
steps:
  - "0>1: projected service account token | req"
  - "0>2: AssumeRoleWithWebIdentity | tls"
  - "note 2..2: match issuer and subject"
  - "2>0: temporary credentials | resp"
  - "0>3: GetSecretValue shop/prod/* | tls"
@h modules/irsa/main.tf
```hcl title="infra/modules/irsa/main.tf"
variable "name" { type = string }
variable "oidc_provider_arn" { type = string }
variable "oidc_issuer" { type = string }
variable "namespace" { type = string }
variable "service_account" { type = string }
variable "policy_json" { type = string }

locals {
  issuer = replace(var.oidc_issuer, "https://", "")
}

data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]
    principals {
      type        = "Federated"
      identifiers = [var.oidc_provider_arn]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.issuer}:sub"
      values   = ["system:serviceaccount:${var.namespace}:${var.service_account}"]
    }
    condition {
      test     = "StringEquals"
      variable = "${local.issuer}:aud"
      values   = ["sts.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = var.name
  assume_role_policy = data.aws_iam_policy_document.trust.json
}

resource "aws_iam_role_policy" "this" {
  role   = aws_iam_role.this.id
  policy = var.policy_json
}

output "role_arn" { value = aws_iam_role.this.arn }
```
@end

@concept RDS PostgreSQL module
@plain
A private, encrypted, multi-AZ PostgreSQL with automated backups and a security group that allows only the nodes.
@problem
A database in a public subnet, without backups or with open security groups is the classic data breach.
@does
- DB subnet group on private subnets; `publicly_accessible = false`.
- Security group ingress on 5432 from the cluster security group only.
- `multi_az = true` in staging and prod; backup retention 7 days enables point-in-time restore with RPO of about 5 minutes (continuous log shipping; check current RDS docs).
- `manage_master_user_password = true` stores the master password in Secrets Manager and rotates it; per-service passwords are created by a bootstrap Job.
- `deletion_protection = true` and `skip_final_snapshot = false` in prod.
@diagram flow
caption: Data path
nodes:
  - "Pods in private subnets|5432|app"
  - "Security group|source is cluster SG|warn"
  - "RDS primary|AZ a|cp"
  - "RDS standby|AZ b, sync copy|ok"
@h modules/database/main.tf
```hcl title="infra/modules/database/main.tf"
variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_security_group_id" { type = string }
variable "instance_class" { type = string }
variable "multi_az" { type = bool }
variable "allocated_storage" {
  type    = number
  default = 50
}
variable "protect" {
  type    = bool
  default = true
}

resource "aws_db_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "db" {
  name   = "${var.name}-db"
  vpc_id = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "from_cluster" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = var.allowed_security_group_id
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
}

resource "aws_db_instance" "this" {
  identifier                  = var.name
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.instance_class
  allocated_storage           = var.allocated_storage
  storage_type                = "gp3"
  storage_encrypted           = true
  multi_az                    = var.multi_az
  db_subnet_group_name        = aws_db_subnet_group.this.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  publicly_accessible         = false
  username                    = "shopadmin"
  manage_master_user_password = true
  backup_retention_period     = 7
  deletion_protection         = var.protect
  skip_final_snapshot         = !var.protect
  final_snapshot_identifier   = var.protect ? "${var.name}-final" : null
  performance_insights_enabled = true
}

output "endpoint" { value = aws_db_instance.this.address }
output "master_secret_arn" { value = aws_db_instance.this.master_user_secret[0].secret_arn }
```
@end

@concept ElastiCache Redis and the environment sizes
@plain
A small replicated Redis for carts, and a table of sizes for each environment.
@problem
Redis with no replica loses carts on a node failure; Redis in prod sized like dev falls over on sale day.
@does
- Replication group with automatic failover in staging and prod, one node in dev; encryption in transit and at rest; the security group allows 6379 from the cluster only.
- Carts are small: 20,000 orders per day x maybe 5 carts per order x 1 KB = about 100 MB, so a `cache.t4g.small` (about 1.37 GiB) has ample room.
- Sizes: dev `t3.medium` x2 nodes, `db.t4g.micro` single-AZ; staging `m6i.large` x2, `db.t4g.medium` multi-AZ; prod `m6i.large` x3, `db.t4g.medium` multi-AZ.
- Run `plan` on pull requests, show the plan as a comment, `apply` after approval. Never `apply` from a laptop to prod.
@diagram cmp
caption: Sizes by environment
cards:
  - {h: "dev", kind: info, items: ["2 x t3.medium", "db.t4g.micro single-AZ", "Redis 1 node", "1 NAT"]}
  - {h: "staging", kind: warn, items: ["2 x m6i.large", "db.t4g.medium multi-AZ", "Redis 2 nodes", "1 NAT"]}
  - {h: "prod", kind: ok, items: ["3 x m6i.large", "db.t4g.medium multi-AZ", "Redis 2 nodes failover", "3 NAT"]}
@h modules/cache/main.tf
```hcl title="infra/modules/cache/main.tf"
variable "name" { type = string }
variable "vpc_id" { type = string }
variable "subnet_ids" { type = list(string) }
variable "allowed_security_group_id" { type = string }
variable "node_type" {
  type    = string
  default = "cache.t4g.small"
}
variable "nodes" {
  type    = number
  default = 2
}

resource "aws_elasticache_subnet_group" "this" {
  name       = var.name
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "cache" {
  name   = "${var.name}-cache"
  vpc_id = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "from_cluster" {
  security_group_id            = aws_security_group.cache.id
  referenced_security_group_id = var.allowed_security_group_id
  from_port                    = 6379
  to_port                      = 6379
  ip_protocol                  = "tcp"
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id       = var.name
  description                = "Shop carts"
  engine                     = "redis"
  node_type                  = var.node_type
  num_cache_clusters         = var.nodes
  automatic_failover_enabled = var.nodes > 1
  multi_az_enabled           = var.nodes > 1
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.this.name
  security_group_ids         = [aws_security_group.cache.id]
}

output "primary_endpoint" { value = aws_elasticache_replication_group.this.primary_endpoint_address }
```
```bash title="Check the sizing arithmetic" lab
python3 - <<'PY'
orders = 20000
carts_per_order = 5
kb_per_cart = 1
mb = orders * carts_per_order * kb_per_cart / 1000
print(f"cart memory about {mb:.0f} MB of 1370 MB = {mb / 1370:.0%}")
PY
```
@end
