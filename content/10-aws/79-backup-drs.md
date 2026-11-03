---
title: AWS Backup and Elastic Disaster Recovery
minutes: 50
objectives:
  - Build centralised backup plans with vaults, lifecycle, copies and Vault Lock
  - Choose between backup restore, pilot light, warm standby and Elastic Disaster Recovery
  - Test restores and measure RPO and RTO
---
Backups protect against deletion and corruption. Disaster recovery protects against the loss of a site or Region. This section covers the AWS services for both.

@concept AWS Backup plans and vaults
@plain
**AWS Backup** is one service to schedule, retain and monitor backups for EBS, RDS, Aurora, DynamoDB, EFS, FSx, S3, EC2 and more.
@problem
Each service has its own backup settings, so coverage is inconsistent and nobody can prove it.
@does
- A **backup plan** has rules for schedule, window, lifecycle (cold storage, expiry) and copy actions.
- A **vault** stores recovery points and is encrypted with a KMS key.
- Resources are chosen by tag such as `backup=daily`, so new resources are covered automatically.
- Continuous backup with point-in-time recovery exists for some services; check the supported list.
@diagram flow
caption: Plan to recovery point
nodes:
  - "Backup plan|schedule and lifecycle|cp"
  - "Resource selection|by tag|info"
  - "Vault|encrypted recovery points|ok"
@h Plan in Terraform
```hcl title="backup.tf"
resource "aws_backup_vault" "main" {
  name        = "main"
  kms_key_arn = aws_kms_key.backup.arn
}

resource "aws_backup_plan" "daily" {
  name = "daily"
  rule {
    rule_name         = "daily-35d"
    target_vault_name = aws_backup_vault.main.name
    schedule          = "cron(0 3 * * ? *)"
    lifecycle {
      delete_after = 35
    }
  }
}

resource "aws_backup_selection" "tagged" {
  name         = "tagged"
  plan_id      = aws_backup_plan.daily.id
  iam_role_arn = aws_iam_role.backup.arn
  selection_tag {
    type  = "STRINGEQUALS"
    key   = "backup"
    value = "daily"
  }
}
```
@check
How do new resources get included automatically? || A tag based selection in the backup plan.
@end

@concept Cross-account copies and Vault Lock
@plain
Copy recovery points to another account and Region, and lock the vault so even administrators cannot delete them early.
@problem
Ransomware or a compromised admin can delete backups that live beside the data.
@does
- A copy rule sends recovery points to a vault in a separate **backup account** and a second Region.
- **Vault Lock** in compliance mode enforces minimum and maximum retention; after the grace period it cannot be removed.
- Organization backup policies apply plans across accounts.
- Logically air-gapped vaults are an additional option; check current documentation.
@diagram flow
caption: Isolated copies
nodes:
  - "Workload vault|primary|app"
  - "Copy|other account and Region|info"
  - "Backup account vault|Vault Lock|ok"
@h Vault Lock
```bash title="Lock a vault" nocheck
aws backup put-backup-vault-lock-configuration --backup-vault-name main \
  --min-retention-days 7 --max-retention-days 365 --changeable-for-days 3
```
:::danger
After the changeable period ends, compliance mode cannot be undone. Test in a non production vault first.
:::
@check
What is the benefit of a separate backup account? || A compromise of a workload account cannot delete its own backups.
@end

@concept RPO, RTO and restore time
@plain
**RPO** is how much data you can lose, measured in time. **RTO** is how long you can be down. They drive the design and its cost.
@problem
Without numbers, teams buy too little protection or an expensive design they do not need.
@does
- Daily backup gives RPO up to 24 hours; hourly up to 1 hour; continuous backup seconds to minutes.
- RTO includes detection, decision, restore time and validation.
- Worked estimate: a 2 TB restore at an effective 100 MB per second is 2,000,000 MB / 100 = 20,000 s, about 5.6 hours.
- Test restores to measure real RTO.
@diagram cmp
caption: Targets
cards:
  - {h: "RPO", kind: info, items: ["Data loss window", "Set by backup frequency or replication"]}
  - {h: "RTO", kind: warn, items: ["Time to recover", "Set by automation and restore speed"]}
@h Estimate in Python
```python title="rto.py"
size_mb = 2 * 1000 * 1000
rate_mb_s = 100
seconds = size_mb / rate_mb_s
print(seconds, seconds / 3600)
```
@check
Daily backups give what worst case RPO? || Up to 24 hours.
@end

@concept DR strategies
@plain
Four classic strategies trade cost against recovery speed: **backup and restore**, **pilot light**, **warm standby** and **multi-site active-active**.
@problem
Choosing the same DR level for every workload either wastes money or leaves critical systems exposed.
@does
- **Backup and restore**: cheapest, RTO hours to a day.
- **Pilot light**: data replicated and core services such as the database running; scale out on disaster.
- **Warm standby**: a scaled-down full copy running; scale up on failover.
- **Active-active**: every Region serves traffic; lowest RTO, highest cost and complexity.
@diagram layers
caption: Cost rises as RTO falls
layers:
  - {label: "Hours", nodes: ["Backup and restore|cheapest|ok"]}
  - {label: "Tens of minutes", nodes: ["Pilot light|data plus core|info"]}
  - {label: "Minutes", nodes: ["Warm standby|scaled down copy|warn"]}
  - {label: "Seconds", nodes: ["Active-active|all Regions serve|bad"]}
@choose DR level
Backup and restore | internal systems with hours of tolerance | revenue systems with minutes of tolerance
Pilot light | important systems | strict minutes-level RTO
Warm standby | customer facing with minutes of tolerance | budget cannot carry a second stack
Active-active | near zero downtime is a requirement | data model cannot handle multi-writer conflicts
@check
Which strategy keeps a scaled-down full environment running? || Warm standby.
@end

@concept AWS Elastic Disaster Recovery
@plain
**AWS Elastic Disaster Recovery (DRS)** continuously replicates servers at block level into a low-cost staging area in AWS and launches recovery instances on demand.
@problem
Running a second copy of every server is costly, but restoring from nightly backups is too slow.
@does
- An agent on the source server replicates disks to replication servers and EBS volumes in a staging subnet. Typical RPO is seconds and RTO minutes.
- Launch templates define instance type, subnet and security groups for recovery.
- Point-in-time snapshots allow recovery to before corruption.
- Drills launch recovery instances without interrupting replication; failback returns data to the source.
@diagram flow
caption: DRS replication and recovery
numbered: true
nodes:
  - "Source server|agent installed|app"
  - "Staging area|replication servers and EBS|info"
  - "Launch|recovery instances|warn"
  - "Failback|return to source|ok"
@h Start a drill
```bash title="DRS commands" nocheck
aws drs initialize-service
aws drs describe-source-servers --query 'items[].[sourceServerID,dataReplicationInfo.dataReplicationState]'
aws drs start-recovery --is-drill --source-servers sourceServerID=s-1234567890abcdef0
```
@check
Does DRS need a full duplicate fleet running? || No. Only low-cost staging resources run until recovery.
@end

@concept Testing recovery
@plain
A recovery plan is real only after it has been exercised with measured results.
@problem
Teams discover broken runbooks, missing permissions and expired keys during the real outage.
@does
- AWS Backup restore testing plans restore and validate automatically on a schedule.
- Script failover with Step Functions or Systems Manager Automation.
- Use Route 53 health checks and Application Recovery Controller routing controls for deliberate DNS switching.
- Record actual RPO and RTO, fix gaps, retest.
@diagram flow
caption: DR test loop
nodes:
  - "Plan|targets and steps|info"
  - "Exercise|restore or fail over|app"
  - "Measure|RPO and RTO|warn"
  - "Improve|fix gaps|ok"
@h Restore test plan
```hcl title="restore-test.tf"
resource "aws_backup_restore_testing_plan" "weekly" {
  name                = "weekly"
  schedule_expression = "cron(0 5 ? * SUN *)"
  start_window_hours  = 4
  recovery_point_selection {
    algorithm            = "LATEST_WITHIN_WINDOW"
    include_vaults       = ["*"]
    recovery_point_types = ["SNAPSHOT"]
    lookback_window_days = 7
  }
}
```
@end

@concept Backup monitoring and cost
@plain
Monitor job success, alarm on failures and watch storage growth, because backup storage accumulates silently.
@problem
A backup that failed three weeks ago is discovered only when needed.
@does
- EventBridge emits job state events; alarm on failed jobs.
- Backup Audit Manager checks coverage and retention against policy.
- Cost drivers: warm storage per GB-month, cold storage with a minimum retention, cross-Region transfer and restore charges.
- Incremental estimate: 5 TB, 2 percent daily change, 35 days gives about 5 + 0.02 x 5 x 35 = 8.5 TB.
@diagram flow
caption: Observe
nodes:
  - "Backup jobs|events|cp"
  - "Alarm on failures|SNS|warn"
  - "Audit Manager|compliance report|ok"
@h Failed jobs
```bash title="Failed backup jobs" lab
aws backup list-backup-jobs --by-state FAILED --query 'BackupJobs[].[ResourceArn,StatusMessage]' --output table
```
@check
Compute the estimate for 5 TB, 2 percent daily change, 35 days. || 5 + 0.02 x 5 x 35 = 8.5 TB.
@end
