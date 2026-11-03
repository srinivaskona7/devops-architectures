---
title: Aurora architecture, storage and failover
minutes: 45
objectives:
  - Explain how Aurora separates compute from a shared distributed storage volume
  - Use cluster, reader and custom endpoints correctly
  - Predict failover behaviour and tune it with priorities and RDS Proxy
---
Aurora is AWS's cloud-built MySQL and PostgreSQL compatible engine. The big difference from RDS is not the SQL layer but the storage layer, which changes how replicas, backups and failover behave.

@concept Aurora compared with RDS
@plain
In RDS each instance owns its own EBS volume. In Aurora, all instances in a cluster share one distributed storage volume that spans three AZs. Instances only do compute.
@problem
Classic replication copies data to every replica's own disk, so replicas lag, storage is paid per copy, and promoting a replica takes time.
@does
- Compute instances (one writer, up to 15 readers) read and write the same volume.
- Storage grows automatically in 10 GiB steps up to the documented maximum (check the current quota).
- Replica lag is typically milliseconds because readers read the shared volume, not a stream of redo.
- Aurora only replicates **redo log records** to storage, which cuts write amplification.
@diagram layers
caption: Aurora cluster layout
layers:
  - {label: "Compute", nodes: ["Writer|AZ a|cp", "Reader 1|AZ b|app", "Reader 2|AZ c|app"]}
  - {label: "Shared storage volume", nodes: ["Segment copies|6 copies of each 10 GiB segment|ok", "Spread over 3 AZs|2 copies per AZ|ok"]}
  - {label: "Continuous backup", nodes: ["S3|log and snapshot data|ext"]}
@h Create a cluster
```bash title="Aurora PostgreSQL cluster with a writer" nocheck
aws rds create-db-cluster --db-cluster-identifier shop-aurora \
  --engine aurora-postgresql --engine-version 16.4 \
  --master-username shopadmin --manage-master-user-password \
  --db-subnet-group-name shop-private --storage-encrypted \
  --backup-retention-period 14 --vpc-security-group-ids sg-0123456789abcdef0
aws rds create-db-instance --db-cluster-identifier shop-aurora \
  --db-instance-identifier shop-aurora-1 --engine aurora-postgresql \
  --db-instance-class db.r6g.large
```
@check
Why is Aurora replica lag small? || Readers read the same shared storage volume instead of applying a replicated log to their own disks.
@end

@concept Quorum storage and self-healing
@plain
Every 10 GiB chunk of data is stored six times, two in each of three AZs. A write succeeds when four of six copies confirm; a read needs three.
@problem
Losing a disk or a whole AZ must not lose data or block writes, and repairs must not need a human.
@does
- Losing a whole AZ removes two copies, leaving four, so writes (which need four) continue.
- Reads survive an AZ plus one more copy lost.
- A failed segment is rebuilt in the background from healthy copies because segments are small, so repair is quick.
- Backups are continuous to S3 and do not impact the writer; restores create a new cluster.
@diagram cmp
caption: Quorum rules for six copies
cards:
  - {h: "Write quorum", kind: ok, items: ["4 of 6 acknowledgements", "Survives loss of one AZ"]}
  - {h: "Read quorum", kind: info, items: ["3 of 6 copies", "Survives AZ plus one more"]}
  - {h: "Repair", kind: app, items: ["10 GiB segments", "Rebuilt from peers automatically"]}
@h Observe
```bash title="Cluster members and volume use" lab
aws rds describe-db-clusters --db-cluster-identifier shop-aurora \
  --query 'DBClusters[0].DBClusterMembers[].[DBInstanceIdentifier,IsClusterWriter,PromotionTier]'
aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name VolumeBytesUsed \
  --dimensions Name=DBClusterIdentifier,Value=shop-aurora \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" \
  --period 300 --statistics Maximum
```
@check
How many copies of data does Aurora keep and in how many AZs? || Six copies across three AZs.
@end

@concept Endpoints
@plain
An Aurora cluster publishes several DNS names. Use the right one so writes reach the writer and reads spread over readers.
@problem
After failover the writer moves to a different instance. Hard-coded instance names break; stable names do not.
@does
- **Cluster endpoint** always points to the current writer. Use it for writes.
- **Reader endpoint** load-balances connections across readers (per connection, not per query), so a long-lived pool can become uneven.
- **Custom endpoints** group chosen instances, for example big readers for analytics.
- **Instance endpoints** point to one instance; use only for diagnostics.
@diagram flow
caption: Which endpoint serves which traffic
nodes:
  - "App writes|cluster endpoint|app"
  - "Writer|current primary|cp"
  - "App reads|reader endpoint|app"
  - "Readers|round robin by connection|env"
@h Custom endpoint
```bash title="Analytics endpoint on selected readers" nocheck
aws rds create-db-cluster-endpoint --db-cluster-identifier shop-aurora \
  --db-cluster-endpoint-identifier analytics --endpoint-type READER \
  --static-members shop-aurora-3 shop-aurora-4
```
:::tip
JDBC and psycopg pools cache DNS. Set a low DNS TTL in the JVM (`networkaddress.cache.ttl`) so the pool follows the writer after failover.
:::
@check
Should an application connect to an instance endpoint for writes? || No; the writer role moves on failover, so use the cluster endpoint.
@end

@concept Failover mechanics
@plain
If the writer fails, Aurora promotes a reader to be the new writer. No data copy is needed because storage is shared, so it is much faster than RDS.
@problem
Database downtime during an AZ failure directly costs revenue, and slow DNS or pool behaviour can extend it.
@does
- Promotion order follows **promotion tier** (0 to 15, lowest first); within a tier the largest instance wins, then arbitrary.
- With at least one reader, service is typically restored in less than 60 seconds, and often in less than 30 seconds (AWS Aurora user guide, high availability page). Treat 60 seconds as the planning figure. With no reader, Aurora creates a new instance, which takes longer.
- The cluster endpoint DNS is updated; applications must reconnect.
- Aurora PostgreSQL supports **cluster cache management**, keeping the buffer cache of a priority-0 replica warm.
@diagram seq
caption: Writer failure and promotion
actors: ["App|pool|app", "Cluster endpoint|DNS|ext", "Old writer|AZ a|bad", "Reader tier 0|AZ b|cp"]
steps:
  - "0>2: writes | req"
  - "note 2..2: instance or AZ fails"
  - "3>3: promoted to writer | resp"
  - "1>3: DNS updated | resp"
  - "0>1: reconnect and retry | req"
  - "0>3: writes resume | resp"
@h Practise
```bash title="Planned failover test" lab
aws rds failover-db-cluster --db-cluster-identifier shop-aurora
aws rds describe-events --source-type db-cluster --source-identifier shop-aurora --duration 15
aws rds modify-db-instance --db-instance-identifier shop-aurora-2 --promotion-tier 0
```
@check
Which reader is promoted first? || The one with the lowest promotion tier; ties go to the largest instance.
@end

@concept Aurora features worth knowing
@plain
Aurora adds operations features that RDS lacks: fast cloning, backtrack (MySQL), parallel query, and the I/O-Optimized storage configuration.
@problem
Creating a test copy of a 2 TB database or undoing a bad deploy should take minutes, not hours.
@does
- **Cloning** uses copy-on-write; a clone is created in minutes and only diverging pages are paid for. Great for test data and migration rehearsals.
- **Backtrack** (Aurora MySQL) rewinds the same cluster to a time in place; not available for PostgreSQL.
- **Storage configurations**: Standard (pay per I/O) or I/O-Optimized (no per-I/O charge, higher instance and storage price). Compare using Cost Explorer once I/O is above roughly a quarter of your Aurora spend; check current pricing.
- **Data API** and `aws_s3` import/export extend integration options.
@diagram flow
caption: Clone for a safe rehearsal
numbered: true
nodes:
  - "Production cluster|shared pages|cp"
  - "Create clone|copy on write|info"
  - "Run migration|on the clone|app"
  - "Discard or promote|delete the clone|ok"
@h Clone
```bash title="Clone via point in time" nocheck
aws rds restore-db-cluster-to-point-in-time --db-cluster-identifier shop-aurora-clone \
  --source-db-cluster-identifier shop-aurora --restore-type copy-on-write \
  --use-latest-restorable-time
aws rds create-db-instance --db-cluster-identifier shop-aurora-clone \
  --db-instance-identifier shop-aurora-clone-1 --engine aurora-postgresql \
  --db-instance-class db.r6g.large
```
@check
What does a clone cost initially? || Almost nothing for storage; you pay for changed pages and the clone's instances.
@end

@concept Aurora with RDS Proxy and connection strategy
@plain
Aurora failover is fast, but clients are not. Pools must detect the change, reconnect and retry.
@problem
Applications that keep dead TCP connections open turn a failover of under a minute into minutes of errors.
@does
- Use RDS Proxy to hold connections while the writer changes.
- Set connection validation, `tcpKeepAlive` and short max connection lifetime in the pool.
- Retry idempotent operations with backoff; transactions in flight at failover are lost and must be retried.
- The AWS Advanced JDBC Wrapper understands Aurora topology and fails over faster than DNS alone.
@diagram cmp
caption: Three ways to survive failover
cards:
  - {h: "Short DNS TTL and pool validation", kind: info, items: ["No extra service", "Recovery bounded by DNS and timeouts"]}
  - {h: "RDS Proxy", kind: ok, items: ["Managed hold and reconnect", "Extra hourly cost"]}
  - {h: "AWS JDBC wrapper", kind: app, items: ["Reads cluster topology", "Java only"]}
@h Pool settings (HikariCP example)
```yaml title="application.yaml"
spring:
  datasource:
    url: jdbc:postgresql://shop-aurora.cluster-abc123.us-east-1.rds.amazonaws.com:5432/shop
    hikari:
      maximum-pool-size: 20
      max-lifetime: 600000
      connection-timeout: 5000
      keepalive-time: 60000
```
@check
Why set a max connection lifetime? || So pooled connections are recycled and eventually follow DNS to the new writer after failover.
@end
