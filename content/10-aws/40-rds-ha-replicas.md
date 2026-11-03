---
title: RDS high availability and replicas
minutes: 50
objectives:
  - Choose between Single-AZ, Multi-AZ instance and Multi-AZ DB cluster deployments
  - Use read replicas for scale and cross-Region copies and know what they do not protect
  - Tune engines safely with parameter groups and subnet groups
---
Amazon RDS runs MySQL, PostgreSQL, MariaDB, Oracle, SQL Server and Db2 as a managed service. AWS patches the host, takes backups and replaces failed hardware; you still own schema, queries, sizing and the recovery plan.

@concept What RDS manages and what you still own
@plain
RDS gives you a database endpoint without giving you the operating system. You choose the engine, version, instance class and storage; AWS runs the host, the install, backups and failover automation.
@problem
Running your own database on EC2 means you patch the OS, script backups, build replication and rehearse failover. Most teams do this badly under pressure.
@does
- RDS handles provisioning, minor-version patching in a maintenance window, automated backups, monitoring hooks and Multi-AZ failover.
- You cannot SSH to the host. You tune through parameter groups and observe with CloudWatch, Enhanced Monitoring and Performance Insights.
- You remain responsible for schema design, indexes, connection handling in the app, security groups, encryption choices and tested restores.
- RDS Custom (Oracle, SQL Server) is a variant that allows OS access when a packaged application demands it.
@diagram layers
caption: The shared responsibility split for RDS
layers:
  - {label: "You", nodes: ["Schema and queries|indexes, migrations|app", "Sizing and cost|class, storage, IOPS|app", "Access|SG, IAM, secrets|app"]}
  - {label: "AWS RDS service", nodes: ["Backups and PITR|automated|ok", "Patching|minor versions in window|ok", "Failover|Multi-AZ automation|ok"]}
  - {label: "AWS infrastructure", nodes: ["EC2 host and EBS|replaced on failure|cp", "Network and power|per AZ|cp"]}
@h Create a small instance
```bash title="Create a PostgreSQL instance" lab
aws rds create-db-instance \
  --db-instance-identifier shop-db \
  --engine postgres --engine-version 16.4 \
  --db-instance-class db.m6g.large \
  --allocated-storage 100 --storage-type gp3 \
  --master-username shopadmin --manage-master-user-password \
  --db-subnet-group-name shop-private \
  --vpc-security-group-ids sg-0123456789abcdef0 \
  --multi-az --storage-encrypted \
  --backup-retention-period 7 \
  --no-publicly-accessible
aws rds describe-db-instances --db-instance-identifier shop-db \
  --query 'DBInstances[0].[DBInstanceStatus,Endpoint.Address]'
```
:::tip
`--manage-master-user-password` makes RDS keep the master password in Secrets Manager and rotate it, so no password ever appears in your shell history or Terraform state. Check the engine versions currently offered with `aws rds describe-db-engine-versions`.
:::
@check
Which part of the database can you not reach on RDS? || The operating system of the host; you use parameter groups and the service APIs instead.
@end

@concept Multi-AZ instance deployment
@plain
RDS keeps a second, hidden copy of your database in another Availability Zone. Every write is copied to it synchronously. If the primary fails, RDS points the same DNS name at the copy.
@problem
A single instance dies with its host or its AZ. You want an automatic recovery with no data loss and no application change.
@does
- The standby is **not readable**; it exists only for failover and for taking backups without load on the primary.
- Storage is replicated synchronously at the storage level (or via engine mirroring for SQL Server), so committed data is not lost.
- Failover is triggered by host failure, AZ outage, instance class change, patching or a manual reboot with failover. It usually takes one to two minutes because DNS changes and the engine must recover.
- Clients keep the same endpoint; they must reconnect, so use short DNS caching and retry logic.
@diagram seq
caption: Failover in a Multi-AZ instance deployment
actors: ["App|reconnects|app", "Endpoint|DNS CNAME|ext", "Primary|AZ a|cp", "Standby|AZ b|env"]
steps:
  - "0>2: writes via endpoint | req"
  - "2>3: synchronous copy | tls"
  - "note 2..2: host fails"
  - "1>3: DNS now points to standby | resp"
  - "0>1: resolve again | req"
  - "0>3: writes continue | resp"
@h Operate failover
```bash title="Test a failover on a non-production instance" lab
aws rds reboot-db-instance --db-instance-identifier shop-db --force-failover
aws rds describe-events --source-type db-instance --source-identifier shop-db --duration 30
```
:::warn
The standby costs the same as the primary, so Multi-AZ doubles instance cost. It protects against infrastructure failure, not against a bad `DELETE`; that needs backups and PITR.
:::
@check
Can you send read queries to the standby of a Multi-AZ instance? || No. Use a read replica or a Multi-AZ DB cluster for readable standbys.
@end

@concept Multi-AZ DB cluster deployment
@plain
A newer RDS layout for MySQL and PostgreSQL with one writer and two **readable** standbys in three AZs. Commits are acknowledged when at least one standby has the data.
@problem
The classic Multi-AZ standby sits idle and failover is slow. Teams wanted readable standbys and faster recovery without moving to Aurora.
@does
- One writer instance and two reader instances in different AZs, each with local storage; replication is semi-synchronous.
- A cluster endpoint always points to the writer, a reader endpoint load-balances across readers.
- Failover is typically much faster than the instance model (the RDS user guide says typically under 35 seconds; it depends on replica lag, so check the guide for your engine).
- Write latency is lower than the instance model because storage is local NVMe-backed on supported classes.
@diagram cmp
caption: Three RDS deployment shapes
cards:
  - {h: "Single-AZ", kind: warn, items: ["One instance", "Restore from backup on failure", "Dev and test only"]}
  - {h: "Multi-AZ instance", kind: app, items: ["Hidden synchronous standby", "Failover typically 60 to 120 seconds", "Standby not readable"]}
  - {h: "Multi-AZ DB cluster", kind: ok, items: ["Writer plus two readable standbys", "Faster failover", "MySQL and PostgreSQL only"]}
@choose Which Multi-AZ shape
Multi-AZ instance | any engine, simple HA, cost matters | you need to read from the standby
Multi-AZ DB cluster | MySQL or PostgreSQL with read scaling and quick failover | you need Oracle or SQL Server
Aurora | storage-level replication, up to 15 readers, fastest failover | you need an engine Aurora does not offer
@h Create a cluster
```bash title="Multi-AZ DB cluster" nocheck
aws rds create-db-cluster \
  --db-cluster-identifier shop-cluster \
  --engine postgres --engine-version 16.4 \
  --db-cluster-instance-class db.m6gd.large \
  --storage-type io1 --allocated-storage 100 --iops 3000 \
  --master-username shopadmin --manage-master-user-password \
  --db-subnet-group-name shop-private
```
@end

@concept Read replicas
@plain
A read replica is another database instance that continuously receives changes from a source instance asynchronously. You send reporting and read-heavy queries to it.
@problem
One primary cannot serve all reads and writes, and analytics queries slow down the transactional workload.
@does
- Replication is **asynchronous**, so replicas can lag. Always watch the `ReplicaLag` CloudWatch metric.
- MySQL, MariaDB and PostgreSQL support up to 15 replicas per source (check the current quota); replicas can live in another Region.
- A replica can be **promoted** to a standalone database, which is the basis of a manual cross-Region DR plan.
- Replicas can be Multi-AZ themselves and can use a different instance class.
- A read replica is not a backup: a destructive statement on the primary replicates too.
@diagram flow
caption: Application split between writer and readers
nodes:
  - "App|writes to primary, reports to replica|app"
  - "Primary|shop-db|cp"
  - "Replica in region|async, lag possible|env"
  - "Replica in other Region|DR and local reads|ext"
@h Create and promote
```bash title="Replica lifecycle" lab
aws rds create-db-instance-read-replica \
  --db-instance-identifier shop-db-ro1 \
  --source-db-instance-identifier shop-db \
  --db-instance-class db.m6g.large
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name ReplicaLag \
  --dimensions Name=DBInstanceIdentifier,Value=shop-db-ro1 \
  --start-time "$(date -u -v-30M +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" \
  --period 60 --statistics Maximum
aws rds promote-read-replica --db-instance-identifier shop-db-ro1
```
:::warn
Promotion breaks replication permanently. Plan how applications and DNS move to the promoted database before you need it.
:::
@check
Why is a read replica not a substitute for backups? || Replication is continuous, so a bad write or drop is copied to the replica within seconds.
@end

@concept Parameter groups and option groups
@plain
A parameter group is a named set of engine settings such as `max_connections` or `innodb_buffer_pool_size`. You attach it to an instance because you cannot edit config files on the host.
@problem
Default engine settings are generic. Production needs tuned memory, logging and connection limits that are repeatable across environments.
@does
- Default parameter groups are read-only. Create a custom group, modify it, and attach it.
- Parameters are **dynamic** (applied immediately) or **static** (applied at reboot). The instance shows `pending-reboot` until you reboot.
- Aurora has two levels: a DB cluster parameter group for cluster-wide settings and a DB parameter group per instance.
- Many values use formulas such as `{DBInstanceClassMemory/32768}`, so they scale with the class.
- Option groups add engine features (Oracle, SQL Server, MySQL plugins) and are separate from parameters.
@diagram flow
caption: From a custom parameter group to a running setting
numbered: true
nodes:
  - "Create group|family postgres16|info"
  - "Modify values|dynamic or static|app"
  - "Attach to instance|modify-db-instance|env"
  - "Reboot if pending|static changes|warn"
  - "Verify|SHOW parameter|ok"
@h Create and attach
```bash title="Custom PostgreSQL parameters" lab
aws rds create-db-parameter-group --db-parameter-group-name shop-pg16 \
  --db-parameter-group-family postgres16 --description "Shop tuning"
aws rds modify-db-parameter-group --db-parameter-group-name shop-pg16 --parameters \
  "ParameterName=log_min_duration_statement,ParameterValue=500,ApplyMethod=immediate" \
  "ParameterName=shared_preload_libraries,ParameterValue=pg_stat_statements,ApplyMethod=pending-reboot"
aws rds modify-db-instance --db-instance-identifier shop-db \
  --db-parameter-group-name shop-pg16 --apply-immediately
aws rds describe-db-instances --db-instance-identifier shop-db \
  --query 'DBInstances[0].DBParameterGroups'
```
```hcl title="The same in Terraform"
resource "aws_db_parameter_group" "shop" {
  name   = "shop-pg16"
  family = "postgres16"

  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
}
```
@check
What does a status of pending-reboot mean? || A static parameter was changed and takes effect only after the instance reboots.
@end

@concept Subnet groups, security groups and encryption
@plain
A DB subnet group tells RDS which private subnets (at least two AZs) it may place instances in. Security groups decide who can connect. Encryption at rest uses KMS and is chosen when you create the database.
@problem
A database reachable from the internet or stored unencrypted fails every audit and widens the blast radius of any mistake.
@does
- Put RDS in **private subnets** and set `PubliclyAccessible=false`.
- Allow port 5432 or 3306 only from the application security group, not from CIDR ranges.
- Encryption at rest cannot be turned on later in place; you copy an unencrypted snapshot to an encrypted one and restore. Replicas and snapshots inherit it.
- Force TLS with `rds.force_ssl=1` (PostgreSQL) or `require_secure_transport=ON` (MySQL) in the parameter group.
@diagram flow
caption: Network path from a pod to the database
nodes:
  - "Pod|SG for pods or node SG|app"
  - "Node subnet|private, AZ a or b|env"
  - "DB security group|allows 5432 from app SG|warn"
  - "RDS in DB subnet group|private subnets, 2+ AZs|cp"
@h Terraform
```hcl title="Subnet group and security group"
resource "aws_db_subnet_group" "shop" {
  name       = "shop-private"
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "db" {
  name   = "shop-db"
  vpc_id = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "from_app" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = var.app_sg_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
```
@check
How do you encrypt an existing unencrypted RDS database? || Copy a snapshot with a KMS key, then restore a new instance from the encrypted copy and cut over.
@end
