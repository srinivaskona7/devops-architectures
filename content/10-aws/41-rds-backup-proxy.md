---
title: RDS backups, PITR, upgrades and RDS Proxy
minutes: 50
objectives:
  - Configure automated backups and restore to a point in time
  - Manage snapshots across accounts and Regions
  - Upgrade engines with low downtime and pool connections with RDS Proxy
---
Failover protects you from hardware. Backups protect you from people, bugs and bad deployments. This section covers the recovery tools and the operational features around them.

@concept Automated backups and retention
@plain
RDS takes a daily storage snapshot during your backup window and continuously uploads transaction logs to S3. Together they allow recovery to any second in the retention period.
@problem
You need recovery without scripting dumps, and without stopping writes while the backup runs.
@does
- Retention is 0 to 35 days; 0 disables automated backups (and also disables replicas for some engines). Default is 7 for console creations.
- The backup is a storage-level snapshot, so there is a brief I/O pause on Single-AZ; on Multi-AZ instances it is taken from the standby.
- Automated backups are deleted with the instance unless you choose to retain them, so take a final snapshot.
- Backups live in RDS-managed S3; you cannot browse them, only restore from them.
@diagram flow
caption: What makes a point in time restore possible
nodes:
  - "Daily snapshot|backup window|info"
  - "Transaction logs|uploaded about every 5 minutes|app"
  - "Restore|snapshot plus log replay|ok"
@h Settings
```bash title="Set retention and window" lab
aws rds modify-db-instance --db-instance-identifier shop-db \
  --backup-retention-period 14 \
  --preferred-backup-window 02:00-03:00 \
  --copy-tags-to-snapshot --apply-immediately
aws rds describe-db-instance-automated-backups \
  --db-instance-identifier shop-db \
  --query 'DBInstanceAutomatedBackups[].[Status,RestoreWindow]'
```
@check
What happens to automated backups when you delete the instance? || They are removed after deletion unless you retain them; take a final or manual snapshot first.
@end

@concept Point-in-time recovery
@plain
PITR rebuilds your database as it was at a chosen second. It always creates a **new instance**; it never rewinds the existing one.
@problem
Someone ran an `UPDATE` without a `WHERE` clause at 14:07. You need the data as of 14:06 without losing everything since last night.
@does
- `LatestRestorableTime` is usually within the last five minutes.
- The restored instance has a new endpoint, default parameter and security groups unless you specify them, and cold caches.
- Standard recovery pattern is restore beside production, copy back the affected rows or switch the application, then delete the extra instance.
- Restore time depends on the size of the logs to replay, so rehearse and record it for your RTO.
@diagram seq
caption: Recovering from a bad update
actors: ["Operator|you|app", "RDS|control plane|cp", "Restored copy|new endpoint|env", "Production|original|ext"]
steps:
  - "0>1: restore to 14:06 | req"
  - "1>2: snapshot plus log replay | tls"
  - "0>2: extract good rows | req"
  - "0>3: repair data | resp"
  - "0>1: delete restored copy | req"
@h Restore
```bash title="PITR to a new instance" lab
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier shop-db \
  --target-db-instance-identifier shop-db-restore \
  --restore-time 2026-10-30T08:36:00Z \
  --db-subnet-group-name shop-private \
  --vpc-security-group-ids sg-0123456789abcdef0
aws rds wait db-instance-available --db-instance-identifier shop-db-restore
```
:::danger
A restore does not copy tags, option settings or IAM database authentication in every case; verify the restored instance's security settings before you connect applications to it.
:::
@check
Does PITR overwrite the original instance? || No, it creates a new instance with a new endpoint.
@end

@concept Manual snapshots, copies and sharing
@plain
A manual snapshot is a backup you create and keep until you delete it. You can copy it to another Region or share it with another account.
@problem
Automated backups expire and stay in one Region. DR and account-isolation strategies need copies elsewhere that you control.
@does
- Take snapshots before risky changes, major upgrades or deletions.
- `copy-db-snapshot --source-region` makes a cross-Region copy; encrypted snapshots need a KMS key in the destination Region.
- Share to another account with `modify-db-snapshot-attribute`; snapshots encrypted with the default AWS-managed key cannot be shared, use a customer managed key and grant the other account access.
- **AWS Backup** can schedule and copy RDS and Aurora snapshots centrally with vault lock for immutability.
@diagram flow
caption: Keeping a recoverable copy outside the failure domain
nodes:
  - "Source account|Region a|app"
  - "Snapshot|encrypted with CMK|info"
  - "Copy|Region b|env"
  - "Backup account|vault lock|ok"
@h Commands
```bash title="Snapshot, copy, share" nocheck
aws rds create-db-snapshot --db-instance-identifier shop-db --db-snapshot-identifier shop-pre-upgrade
aws rds copy-db-snapshot --region eu-west-1 \
  --source-region us-east-1 \
  --source-db-snapshot-identifier arn:aws:rds:us-east-1:111122223333:snapshot:shop-pre-upgrade \
  --target-db-snapshot-identifier shop-pre-upgrade-eu \
  --kms-key-id alias/shop-eu
aws rds modify-db-snapshot-attribute --db-snapshot-identifier shop-pre-upgrade \
  --attribute-name restore --values-to-add 444455556666
```
@check
Why can a snapshot encrypted with the default aws/rds key not be shared? || The AWS-managed key policy cannot be edited to grant another account; use a customer managed key.
@end

@concept Maintenance, minor upgrades and blue/green deployments
@plain
RDS patches in a weekly maintenance window. For major upgrades or risky changes, a **blue/green deployment** builds a synchronized copy (green), lets you change and test it, and then switches over.
@problem
In-place major upgrades mean an outage you cannot roll back easily.
@does
- Enable `auto-minor-version-upgrade` for minor patches; schedule the window outside peak hours.
- A blue/green deployment creates a staging environment with logical replication from production. You upgrade or tune green, test, then switch over, usually in under a minute for supported engines.
- Switchover renames endpoints so the application needs no change; blue remains until you delete it.
- Major engine upgrades require a compatible parameter group family and extension compatibility; test on a restored copy first.
@diagram flow
caption: Blue/green switchover
numbered: true
nodes:
  - "Blue|production|cp"
  - "Create green|replica with new version|info"
  - "Test green|queries, extensions|app"
  - "Switch over|endpoints swapped|warn"
  - "Delete blue|after validation|ok"
@h CLI
```bash title="Blue/green upgrade" nocheck
aws rds create-blue-green-deployment \
  --blue-green-deployment-name shop-pg17 \
  --source arn:aws:rds:us-east-1:111122223333:db:shop-db \
  --target-engine-version 17.2 \
  --target-db-parameter-group-name shop-pg17
aws rds switchover-blue-green-deployment \
  --blue-green-deployment-identifier bgd-0123456789abcdef \
  --switchover-timeout 300
```
:::tip
Always take a manual snapshot first and check the current list of engines and versions that support blue/green in the RDS documentation.
:::
@check
How does blue/green avoid application changes? || Switchover swaps the endpoint names so the same hostnames point at the new environment.
@end

@concept RDS Proxy
@plain
RDS Proxy is a managed connection pool that sits between your application and the database. Applications connect to the proxy; the proxy keeps a small set of warm connections to the database.
@problem
Hundreds of pods or Lambda functions each opening connections exhaust `max_connections`, and every failover forces slow reconnect storms.
@does
- **Multiplexing**: many client connections share fewer database connections between transactions.
- **Pinning** happens when session state (temporary tables, `SET` statements, prepared statements on some engines) ties a client to one connection, which reduces pooling. Watch the `DatabaseConnectionsCurrentlyBorrowed` and pinning metrics.
- During failover the proxy holds client connections and reconnects to the new writer, cutting visible failover time.
- Credentials come from Secrets Manager; clients may authenticate to the proxy with IAM.
- The proxy endpoint is reachable only from inside the VPC. Aurora also gets optional read-only endpoints.
@diagram flow
caption: Pooling between pods and the database
nodes:
  - "Many pods|hundreds of connections|app"
  - "RDS Proxy|pool and IAM auth|cp"
  - "Secrets Manager|DB credentials|ext"
  - "Database|few connections|ok"
@h Create with Terraform
```hcl title="RDS Proxy for the shop database"
resource "aws_db_proxy" "shop" {
  name                   = "shop-proxy"
  engine_family          = "POSTGRESQL"
  role_arn               = aws_iam_role.proxy.arn
  vpc_subnet_ids         = var.private_subnet_ids
  vpc_security_group_ids = [aws_security_group.proxy.id]
  require_tls            = true
  idle_client_timeout    = 1800

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "REQUIRED"
    secret_arn  = aws_secretsmanager_secret.db.arn
  }
}

resource "aws_db_proxy_default_target_group" "shop" {
  db_proxy_name = aws_db_proxy.shop.name
  connection_pool_config {
    max_connections_percent      = 80
    max_idle_connections_percent = 40
  }
}

resource "aws_db_proxy_target" "shop" {
  db_proxy_name          = aws_db_proxy.shop.name
  target_group_name      = aws_db_proxy_default_target_group.shop.name
  db_instance_identifier = aws_db_instance.shop.identifier
}
```
:::note
RDS Proxy has an hourly cost per vCPU of the database. Use it when connection counts or failover time hurt, not by default.
:::
@check
What is connection pinning? || A client is locked to one database connection because of session state, so the proxy cannot share that connection with others.
@end

@concept Monitoring RDS
@plain
Three layers show database health: CloudWatch metrics from the hypervisor, Enhanced Monitoring from an OS agent, and Performance Insights which shows which SQL consumes time.
@problem
"The database is slow" is not actionable. You need to tell CPU saturation from lock waits, storage IOPS limits and bad queries.
@does
- CloudWatch: `CPUUtilization`, `FreeableMemory`, `DatabaseConnections`, `ReadIOPS`/`WriteIOPS`, `DiskQueueDepth`, `FreeStorageSpace`, `ReplicaLag`.
- Enhanced Monitoring (1 to 60 second granularity) shows per-process OS metrics.
- Performance Insights reports **DB Load** in average active sessions by wait event, SQL, user and host.
- Export engine logs (error, slow query, postgresql) to CloudWatch Logs with `--cloudwatch-logs-export-configuration`.
- Enable storage autoscaling (`--max-allocated-storage`) to avoid running out of space.
@diagram cmp
caption: Which tool answers which question
cards:
  - {h: "CloudWatch", kind: info, items: ["Is it CPU, memory, IOPS?", "Alarm targets"]}
  - {h: "Enhanced Monitoring", kind: app, items: ["Which OS process?", "Swap and file system"]}
  - {h: "Performance Insights", kind: ok, items: ["Which SQL and wait event?", "Load by user and host"]}
  - {h: "Logs", kind: env, items: ["Slow queries", "Errors and deadlocks"]}
@h Alarm on storage and CPU
```bash title="Free storage alarm" nocheck
aws cloudwatch put-metric-alarm --alarm-name shop-db-low-storage \
  --namespace AWS/RDS --metric-name FreeStorageSpace \
  --dimensions Name=DBInstanceIdentifier,Value=shop-db \
  --statistic Minimum --period 300 --evaluation-periods 3 \
  --threshold 10737418240 --comparison-operator LessThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:111122223333:ops-alerts
```
@check
What does DB Load in Performance Insights measure? || The average number of active sessions, broken down by wait event, SQL statement, user or host.
@end
