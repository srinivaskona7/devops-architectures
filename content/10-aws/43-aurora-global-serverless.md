---
title: Aurora Global Database and Serverless v2
minutes: 45
objectives:
  - Design a cross-Region Aurora topology and perform switchover or failover
  - Size Aurora Serverless v2 with ACU ranges
  - Pick between provisioned and Serverless v2 on cost and behaviour
---
Two Aurora features change architecture: Global Database for multi-Region reach and Serverless v2 for elastic compute.

@concept Global Database
@plain
A Global Database is one primary Aurora cluster in one Region and up to several read-only secondary clusters in other Regions. Storage-level replication copies changes between them.
@problem
Users on another continent need low-latency reads, and a regional outage needs a recovery path measured in a minute, not hours of snapshot restores.
@does
- Replication is physical at the storage layer, usually under one second lag, with no impact on writer performance.
- Secondary clusters serve reads locally; writes can be forwarded to the primary with **write forwarding** (at higher latency).
- Typical RPO is seconds and RTO about a minute for unplanned failover (check current AWS figures).
- Each secondary has its own compute instances, parameter groups and KMS key.
@diagram flow
caption: Primary Region with a secondary for reads and DR
nodes:
  - "Primary cluster|us-east-1, read and write|cp"
  - "Storage replication|sub-second lag|info"
  - "Secondary cluster|eu-west-1, read only|env"
  - "Local readers|low latency EU users|app"
@h Create
```bash title="Add a Region to an existing cluster" nocheck
aws rds create-global-cluster --global-cluster-identifier shop-global \
  --source-db-cluster-identifier arn:aws:rds:us-east-1:111122223333:cluster:shop-aurora \
  --region us-east-1
aws rds create-db-cluster --global-cluster-identifier shop-global \
  --db-cluster-identifier shop-aurora-eu --engine aurora-postgresql \
  --engine-version 16.4 --kms-key-id alias/shop-eu --region eu-west-1 \
  --db-subnet-group-name shop-private-eu
```
@check
How does Global Database replicate? || At the storage layer, not through the database engine, so the writer is not slowed.
@end

@concept Switchover versus failover
@plain
Planned switchover moves the primary role without data loss. Unplanned failover promotes a secondary after an outage and may lose a few seconds of writes.
@problem
You need one operation for maintenance and Region evacuation and another for disasters, and you must know their data guarantees.
@does
- **Switchover** (managed planned) waits for the secondary to catch up, swaps roles and keeps replication; RPO zero.
- **Failover** (`--allow-data-loss`) detaches and promotes the chosen secondary; the old primary must be rebuilt as a secondary later.
- Applications need a Region-aware endpoint. Use Route 53 failover records or the **global writer endpoint** for the write path.
- Rehearse in a game day; record the time from decision to first successful write.
@diagram seq
caption: Unplanned regional failover
actors: ["Operator|runbook|app", "Primary Region|failed|bad", "Secondary|eu-west-1|cp", "Route 53|DNS|ext"]
steps:
  - "note 1..1: region impaired"
  - "0>2: failover-global-cluster | req"
  - "2>2: promoted to writer | resp"
  - "0>3: repoint writer record | req"
  - "3>2: app writes land in EU | resp"
@h Commands
```bash title="Switchover and failover" nocheck
aws rds switchover-global-cluster --global-cluster-identifier shop-global \
  --target-db-cluster-identifier arn:aws:rds:eu-west-1:111122223333:cluster:shop-aurora-eu
aws rds failover-global-cluster --global-cluster-identifier shop-global \
  --target-db-cluster-identifier arn:aws:rds:eu-west-1:111122223333:cluster:shop-aurora-eu \
  --allow-data-loss
```
:::warn
Check `AuroraGlobalDBReplicationLag` before choosing failover; it tells you roughly how much data may be lost.
:::
@check
What distinguishes switchover from failover? || Switchover is planned with no data loss; failover is for outages and may lose the unreplicated tail.
@end

@concept Serverless v2 capacity model
@plain
Serverless v2 instances scale their CPU and memory continuously between a minimum and maximum number of **Aurora Capacity Units (ACUs)**. One ACU is about 2 GiB of memory with matching CPU and networking.
@problem
Provisioned instances are sized for peak and idle the rest of the time; spiky and dev workloads waste money.
@does
- You set `MinCapacity` and `MaxCapacity` on the cluster, for example 0.5 to 16 ACU. Scaling is in fine steps, within seconds, without dropping connections.
- Readers and writers can be Serverless v2 or provisioned in the same cluster.
- Newer versions can scale to zero ACUs and auto-pause (check availability for your engine version).
- You are billed per ACU-hour used. The minimum sets the floor and the buffer cache size.
@diagram cmp
caption: Provisioned compared with Serverless v2
cards:
  - {h: "Provisioned", kind: app, items: ["Fixed instance class", "Cheapest for steady load with reservations", "Resize needs a failover"]}
  - {h: "Serverless v2", kind: ok, items: ["ACU range scales in seconds", "Good for spiky and dev loads", "Costlier per unit at constant high use"]}
@h Configure
```bash title="Set the ACU range and add a serverless instance" lab
aws rds modify-db-cluster --db-cluster-identifier shop-aurora \
  --serverless-v2-scaling-configuration MinCapacity=0.5,MaxCapacity=16
aws rds create-db-instance --db-cluster-identifier shop-aurora \
  --db-instance-identifier shop-aurora-sv2 --engine aurora-postgresql \
  --db-instance-class db.serverless
```
```hcl title="Terraform"
resource "aws_rds_cluster" "shop" {
  cluster_identifier = "shop-aurora"
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  database_name      = "shop"
  master_username    = "shopadmin"
  manage_master_user_password = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5
    max_capacity = 16
  }
}

resource "aws_rds_cluster_instance" "shop" {
  cluster_identifier = aws_rds_cluster.shop.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.shop.engine
}
```
@check
What does the minimum ACU influence besides cost? || The buffer cache size and how quickly the database can absorb a sudden burst.
@end

@concept Choosing capacity and avoiding surprises
@plain
Serverless v2 is flexible, but a badly chosen range gives either high bills or throttled performance.
@problem
A maximum that is too low causes slow queries; a minimum that is too high removes savings; max_connections is derived from the maximum ACU.
@does
- Watch `ServerlessDatabaseCapacity` and `ACUUtilization` in CloudWatch.
- `max_connections` depends on the **maximum** capacity, so a tiny max with many pods causes "too many connections". Use RDS Proxy.
- Mix a provisioned writer with Serverless v2 readers to absorb read spikes, or the reverse for dev stacks.
- Compare cost using the AWS Pricing Calculator with your measured average ACU, not the maximum.
@diagram flow
caption: Tuning loop
numbered: true
nodes:
  - "Start 0.5 to 8 ACU|small range|plain"
  - "Observe|ACUUtilization, latency|info"
  - "Raise max if pinned|performance|warn"
  - "Raise min if cold|cache misses|app"
  - "Compare to provisioned|savings check|ok"
@h Alarm
```bash title="Alarm when the max is almost reached" nocheck
aws cloudwatch put-metric-alarm --alarm-name shop-acu-high \
  --namespace AWS/RDS --metric-name ACUUtilization \
  --dimensions Name=DBClusterIdentifier,Value=shop-aurora \
  --statistic Average --period 300 --evaluation-periods 3 \
  --threshold 90 --comparison-operator GreaterThanThreshold \
  --alarm-actions arn:aws:sns:us-east-1:111122223333:ops-alerts
```
@check
Why can Serverless v2 produce "too many connections" at a low maximum? || The default connection limit scales with the maximum ACU setting.
@end

@concept Choosing between RDS, Aurora and the rest
@plain
Pick the database by access pattern, scale and cost, not by habit.
@problem
Using Aurora where plain RDS suffices doubles cost; using RDS where you need multi-Region or many readers hits a wall.
@does
- RDS PostgreSQL or MySQL Multi-AZ: simple, cheaper, any version lag acceptable.
- Aurora: more readers, fast failover, Global Database, cloning, large storage.
- Aurora Serverless v2: variable load and many small environments.
- DynamoDB: key-value and document access at any scale with single-digit millisecond latency.
- ElastiCache: caching and session data, never the system of record.
@choose Pick a datastore
RDS Multi-AZ | a standard relational app of moderate size | you need more than five readers or multi-Region writes
Aurora provisioned | steady heavy OLTP with many readers | the workload is tiny and cost-sensitive
Aurora Serverless v2 | spiky, unpredictable, or many dev databases | constant 24/7 high load where reservations win
DynamoDB | key-based access, huge scale, no joins | you need ad hoc SQL analytics
@diagram flow
caption: Decision shortcut
nodes:
  - "Relational needed?|joins, transactions|plain"
  - "Scale and HA needs|readers, regions|info"
  - "Load shape|steady or spiky|warn"
  - "Choice|RDS, Aurora or v2|ok"
@end
