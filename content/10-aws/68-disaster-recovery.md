---
title: Disaster recovery patterns
minutes: 55
objectives:
  - Define RTO and RPO and choose among backup and restore, pilot light, warm standby and active-active
  - Design DR for the EKS shop including data replication and traffic failover
  - Rehearse failover with a runbook and know the failback steps
---
Multi-AZ covers a data centre failure. Disaster recovery covers losing a Region, an account compromise, ransomware or a bad deployment that corrupts data.
@concept RTO, RPO and the DR spectrum
@plain
**RPO** (recovery point objective) is how much data you can lose, measured in time. **RTO** (recovery time objective) is how long recovery may take. Lower targets cost more.
@problem
Without numbers, teams overbuild everything or discover too late that recovery takes days.
@does
- Get the targets from the business for each service tier, then pick the cheapest pattern that meets them.
- AWS describes four strategies in increasing cost and speed: **backup and restore**, **pilot light**, **warm standby**, **multi-site active-active**.
- Include dependencies: DNS, identity, secrets, container images, certificates, CI/CD, and people.
- Also plan for non-regional disasters: account takeover, deletion, corrupted data. These need immutable backups in another account.
@diagram cmp
caption: Four strategies
cards:
  - {h: "Backup and restore", kind: info, items: ["RPO hours, RTO hours or more", "Lowest cost"]}
  - {h: "Pilot light", kind: app, items: ["Core data replicated", "Compute off until needed"]}
  - {h: "Warm standby", kind: warn, items: ["Scaled-down full copy", "RTO minutes"]}
  - {h: "Active-active", kind: ok, items: ["Both Regions serve", "RTO near zero, highest cost"]}
@h Record targets
```yaml title="Service tier targets (example)"
tiers:
  tier0:
    services: [checkout, login]
    rpo: 1 minute
    rto: 15 minutes
    strategy: warm-standby
  tier1:
    services: [catalog, search]
    rpo: 15 minutes
    rto: 2 hours
    strategy: pilot-light
  tier2:
    services: [reports]
    rpo: 24 hours
    rto: 24 hours
    strategy: backup-restore
```
@check
What does RPO measure? || The maximum acceptable amount of data loss, expressed as time.
@end

@concept Backup and restore
@plain
Take regular backups, copy them to another Region and account, and rebuild the environment from infrastructure as code when needed.
@problem
Cheap protection against Region loss and against deletion or ransomware.
@does
- **AWS Backup** plans centralise schedules, retention, cross-Region and cross-account copy, and **Vault Lock** for immutability. It covers RDS, Aurora, DynamoDB, EBS, EFS, S3, EKS (cluster state) and more.
- Recreate the VPC, EKS and add-ons from Terraform and GitOps in the DR Region; restore data from backups.
- RTO is dominated by rebuild time plus restore time; rehearse it.
- ECR replication and Route 53 failover records are prerequisites.
@diagram flow
caption: Backup and restore flow
numbered: true
nodes:
  - "AWS Backup plan|daily, 35 days|info"
  - "Copy to DR Region|and backup account|app"
  - "Disaster|primary lost|bad"
  - "Terraform apply|rebuild platform|warn"
  - "Restore data|then switch DNS|ok"
@h Backup plan
```hcl title="AWS Backup plan with cross-Region copy"
resource "aws_backup_vault" "primary" {
  name = "shop-primary"
}

resource "aws_backup_plan" "shop" {
  name = "shop-daily"

  rule {
    rule_name         = "daily"
    target_vault_name = aws_backup_vault.primary.name
    schedule          = "cron(0 3 * * ? *)"

    lifecycle {
      delete_after = 35
    }

    copy_action {
      destination_vault_arn = var.dr_vault_arn
      lifecycle {
        delete_after = 35
      }
    }
  }
}

resource "aws_backup_selection" "tagged" {
  plan_id      = aws_backup_plan.shop.id
  name         = "tagged-resources"
  iam_role_arn = var.backup_role_arn

  selection_tag {
    type  = "STRINGEQUALS"
    key   = "backup"
    value = "daily"
  }
}
```
@check
Why copy backups to another account as well as another Region? || It protects against account compromise and deletion, not only a Region outage.
@end

@concept Pilot light
@plain
Keep the data replicated and the core infrastructure defined in the DR Region, but keep compute switched off or at minimum size. On disaster, scale up.
@problem
Backup and restore is too slow, but a full standby is too expensive.
@does
- Aurora Global Database secondary cluster (readers off or one small instance), DynamoDB global tables, S3 cross-Region replication, ECR replication.
- A minimal EKS control plane exists (cluster fee) with zero or few nodes; manifests are synced by GitOps.
- Failover steps: promote database, scale node pools and deployments, switch DNS.
- RTO tens of minutes to hours; RPO seconds to minutes depending on replication.
@diagram flow
caption: Pilot light in the DR Region
nodes:
  - "Primary Region|full stack|cp"
  - "Replicated data|Aurora secondary, S3 CRR|info"
  - "DR EKS|minimal nodes|warn"
  - "Scale up on failover|promote and scale|ok"
@h Failover commands
```bash title="Pilot light activation (outline)" nocheck
aws rds failover-global-cluster --global-cluster-identifier shop-global \
  --target-db-cluster-identifier arn:aws:rds:eu-west-1:111122223333:cluster:shop-aurora-eu --allow-data-loss
kubectl --context shop-dr scale deployment --all --replicas=3 -n shop
kubectl --context shop-dr patch nodepool general --type merge -p '{"spec":{"limits":{"cpu":"200"}}}'
aws route53 change-resource-record-sets --hosted-zone-id Z0123456789ABCDEFGHIJ --change-batch file://failover.json
```
@check
What stays off in a pilot light? || Most compute; data replication and core definitions stay on.
@end

@concept Warm standby and active-active
@plain
Warm standby runs a smaller but complete copy that can serve traffic at once and be scaled up. Active-active serves users from both Regions simultaneously.
@problem
Tier 0 services cannot wait for scale-up and promotion steps.
@does
- Warm standby: DR cluster runs at 20 to 30 percent of production; Route 53 health checks fail over; scale with HPA and Karpenter.
- Active-active: requires data layers that accept writes in both Regions (DynamoDB global tables, Aurora with write forwarding or sharded ownership, conflict handling) and idempotent business logic.
- Global traffic: Route 53 latency or weighted records, Global Accelerator, CloudFront origin groups.
- Most complex part is data consistency, not compute. Prefer active-passive unless you truly need active-active.
@diagram flow
caption: Global traffic management
nodes:
  - "Users|worldwide|ext"
  - "Route 53 or Global Accelerator|health checks|cp"
  - "Region A cluster|serving|app"
  - "Region B cluster|serving or standby|env"
@h Route 53 failover records
```hcl title="Primary and secondary failover records"
resource "aws_route53_health_check" "primary" {
  fqdn              = "origin-a.shop.example.com"
  port              = 443
  type              = "HTTPS"
  resource_path     = "/healthz"
  failure_threshold = 3
  request_interval  = 10
}

resource "aws_route53_record" "primary" {
  zone_id         = var.zone_id
  name            = "shop.example.com"
  type            = "CNAME"
  ttl             = 60
  set_identifier  = "primary"
  records         = ["origin-a.shop.example.com"]
  health_check_id = aws_route53_health_check.primary.id

  failover_routing_policy {
    type = "PRIMARY"
  }
}

resource "aws_route53_record" "secondary" {
  zone_id        = var.zone_id
  name           = "shop.example.com"
  type           = "CNAME"
  ttl            = 60
  set_identifier = "secondary"
  records        = ["origin-b.shop.example.com"]

  failover_routing_policy {
    type = "SECONDARY"
  }
}
```
@check
What is the hardest part of active-active? || Data consistency across Regions, including write conflicts.
@end

@concept DR for the EKS control plane and cluster state
@plain
A second cluster is rebuilt from code. Application state lives in databases and object stores, not in the cluster.
@problem
Teams back up etcd out of habit, but EKS does not expose etcd; the right approach is to treat clusters as disposable.
@does
- Keep cluster definition in Terraform and workloads in Git (Argo CD or Flux); a DR cluster syncs the same repository with region-specific overlays.
- Stateful data: use managed databases; for PVs use EBS snapshots (via VolumeSnapshot or AWS Backup) copied to the DR Region; EFS replication; Velero for namespace-level backup of Kubernetes resources and volumes.
- Secrets: Secrets Manager replication to the DR Region; External Secrets Operator in the DR cluster reads local replicas.
- Certificates: cert-manager reissues; ACM certificates must exist in the DR Region.
- Images: ECR replication.
@diagram layers
caption: DR dependencies
layers:
  - {label: "Code", nodes: ["Terraform|cluster and network|cp", "Git|manifests|cp"]}
  - {label: "Data", nodes: ["Aurora and DynamoDB|replicated|ok", "EBS snapshots and Velero|copied|ok"]}
  - {label: "Supply", nodes: ["ECR replication|images|info", "Secrets replication|credentials|info", "ACM and DNS|certs and routing|info"]}
@h Replicate secrets
```bash title="Replicate a secret to the DR Region" nocheck
aws secretsmanager replicate-secret-to-regions --secret-id shop/db \
  --add-replica-regions Region=eu-west-1,KmsKeyId=alias/shop-eu
```
```bash title="Velero backup with schedule" nocheck
velero schedule create shop-daily --schedule "0 2 * * *" --include-namespaces shop --ttl 720h
```
@check
Why not rely on backing up etcd for DR? || EKS does not expose etcd; rebuild clusters from code and keep state in data stores.
@end

@concept Runbooks, rehearsals and failback
@plain
A DR plan that was never exercised does not work. Write a runbook, run it, and record the actual times.
@problem
Real disasters expose missing permissions, stale AMIs, expired certificates and forgotten dependencies.
@does
- Runbook: decision criteria and who decides, step by step commands, verification checks, communication plan, and rollback.
- Rehearse at least twice a year in a game day; measure RTO and RPO against targets.
- **Failback**: re-establish replication to the original Region, sync data, switch traffic during a quiet window. It is often harder than failover.
- Keep DR credentials, break-glass access and the runbook available outside the failing Region and tooling.
- AWS Elastic Disaster Recovery covers VM-based workloads; Resilience Hub validates the design.
@diagram flow
caption: Failover and failback
numbered: true
nodes:
  - "Declare disaster|criteria met|bad"
  - "Fail over|promote, scale, DNS|warn"
  - "Operate in DR|monitor and communicate|info"
  - "Rebuild primary|reverse replication|app"
  - "Fail back|planned window|ok"
@h Runbook skeleton
```yaml title="DR runbook outline" nocheck
name: shop-regional-failover
preconditions:
  - Incident commander approved
  - Replication lag below 60s or data loss accepted
steps:
  - promote Aurora secondary in eu-west-1
  - scale Karpenter NodePool limits in DR cluster
  - scale deployments to production counts
  - verify smoke tests against dr.shop.example.com
  - switch Route 53 failover record
verify:
  - checkout success rate above 99 percent
rollback:
  - restore record to primary if primary recovers within 15 minutes
```
@check
Why is failback often harder than failover? || Data has changed in the DR Region and must be synchronised back before traffic can return safely.
@end
