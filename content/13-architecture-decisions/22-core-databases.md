---
title: Core services 11 to 15, databases
minutes: 60
objectives:
  - Compare relational, cloud-native, key-value, cache and global databases
  - State when to choose each service
  - List the limits to verify in the current docs
---
Databases are chosen by data shape, scale and consistency need, not by brand. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
From familiar engines to globally distributed stores. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Database spectrum
layers:
  - {label: "Services on this page", nodes: ["Managed relational database|RDS|app", "Cloud-native relational database|Aurora|info", "Key-value and document database|DynamoDB|env", "In-memory cache|ElastiCache|ok", "Global relational database|Aurora DSQL or Aurora Global Database|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 11 | Managed relational database | RDS | Azure SQL or Flexible Server | Cloud SQL |
| 12 | Cloud-native relational database | Aurora | Azure SQL Hyperscale | AlloyDB |
| 13 | Key-value and document database | DynamoDB | Cosmos DB | Firestore or Bigtable |
| 14 | In-memory cache | ElastiCache | Azure Cache for Redis | Memorystore |
| 15 | Global relational database | Aurora DSQL or Aurora Global Database | Cosmos DB or SQL Hyperscale geo-replicas | Spanner |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 11. Managed relational database
@plain
A managed MySQL, PostgreSQL, SQL Server or similar database where the cloud handles patching, backups and failover.
@problem
Running your own database means owning backups, replication, patching and failover drills.
@does
- **Names**: AWS RDS; Azure Azure SQL or Flexible Server; GCP Cloud SQL.
- **What it is**: Provisions engine instances with automated backups, point-in-time recovery, read replicas and a standby in another zone.
- **Choose it when**: Standard OLTP apps with moderate scale; Teams wanting familiar engines; Lift-and-shift of existing databases.
- **Check in the current docs**: Engine versions and extensions available differ, so check the current docs; Storage and instance size limits cap vertical scale; Failover takes tens of seconds to minutes, and clients must retry.
@diagram cmp
caption: Managed relational database on the three clouds
cards:
  - {h: "RDS", kind: warn, items: ["Multi-AZ, read replicas, parameter groups"]}
  - {h: "Azure SQL or Flexible Server", kind: info, items: ["Flexible Server zone-redundant HA, Azure SQL Database"]}
  - {h: "Cloud SQL", kind: ok, items: ["High availability option, read replicas"]}
@h Example
A PostgreSQL database runs with a standby in a second zone, seven-day point-in-time recovery and one read replica for reports.
@h CLI on each cloud
```bash title="AWS CLI, Managed relational database" nocheck
aws rds create-db-instance --db-instance-identifier demo-pg --engine postgres --db-instance-class db.t3.micro --allocated-storage 20 --master-username dbadmin --manage-master-user-password --multi-az
```
```bash title="Azure CLI, Managed relational database" nocheck
az postgres flexible-server create --resource-group rg-demo --name demo-pg-123 --tier Burstable --sku-name Standard_B1ms --admin-user dbadmin --high-availability ZoneRedundant
```
```bash title="gcloud, Managed relational database" nocheck
gcloud sql instances create demo-pg --database-version=POSTGRES_16 --tier=db-custom-2-7680 --region=europe-west1 --availability-type=REGIONAL
```
@check
What must a client do during a failover? || Reconnect and retry, because connections drop.
@end

@concept 12. Cloud-native relational database
@plain
A relational database whose storage layer is redesigned for the cloud, so it scales storage and reads faster than the classic engine.
@problem
Classic managed databases couple compute to a single disk, which limits recovery time, replicas and storage growth.
@does
- **Names**: AWS Aurora; Azure Azure SQL Hyperscale; GCP AlloyDB.
- **What it is**: Separates compute from distributed storage, offers many fast read replicas and quick failover, while keeping MySQL, PostgreSQL or SQL Server compatibility.
- **Choose it when**: Heavy read workloads that outgrow one instance; Large databases needing fast snapshots and recovery; Teams wanting PostgreSQL or MySQL compatibility.
- **Check in the current docs**: Compatibility is high but not total, so test extensions and versions; Pricing includes I/O or storage models that differ, so check the current docs; Hyperscale is a tier of Azure SQL, while Aurora and AlloyDB are separate products.
@diagram cmp
caption: Cloud-native relational database on the three clouds
cards:
  - {h: "Aurora", kind: warn, items: ["Aurora clusters, Serverless v2, Global Database"]}
  - {h: "Azure SQL Hyperscale", kind: info, items: ["Hyperscale service tier, named replicas"]}
  - {h: "AlloyDB", kind: ok, items: ["Clusters, primary and read pool instances"]}
@h Example
A reporting-heavy PostgreSQL workload moves to a cloud-native engine and adds read replicas instead of resizing one big instance.
@h CLI on each cloud
```bash title="AWS CLI, Cloud-native relational database" nocheck
aws rds create-db-cluster --db-cluster-identifier demo-aurora --engine aurora-postgresql --master-username dbadmin --manage-master-user-password
```
```bash title="Azure CLI, Cloud-native relational database" nocheck
az sql db create --resource-group rg-demo --server demo-sql-123 --name appdb --edition Hyperscale --family Gen5 --capacity 2
```
```bash title="gcloud, Cloud-native relational database" nocheck
gcloud alloydb clusters create demo-cluster --region=europe-west1 --password=CHANGE_ME --network=default
```
@check
What is the key design idea? || Compute is separated from a shared distributed storage layer.
@end

@concept 13. Key-value and document database
@plain
A database that stores items by key with predictable speed at any scale, without joins or a fixed schema.
@problem
Relational databases struggle at very high request rates and global distribution with single-digit-millisecond targets.
@does
- **Names**: AWS DynamoDB; Azure Cosmos DB; GCP Firestore or Bigtable.
- **What it is**: Offers partitioned tables, automatic scaling, optional global replication and pay per request or provisioned throughput.
- **Choose it when**: Known access patterns by key; Very high scale session, cart or profile data; Serverless backends.
- **Check in the current docs**: Design starts from queries, and changing access patterns later is costly; Hot partitions throttle requests; Item size and throughput limits apply, so check the current docs.
@diagram cmp
caption: Key-value and document database on the three clouds
cards:
  - {h: "DynamoDB", kind: warn, items: ["Partition and sort keys, on-demand mode, global tables"]}
  - {h: "Cosmos DB", kind: info, items: ["Multiple APIs, partition keys, request units"]}
  - {h: "Firestore or Bigtable", kind: ok, items: ["Firestore for documents, Bigtable for wide-column scale"]}
@h Example
A shopping cart is stored by user ID and read in a few milliseconds regardless of user count.
@h CLI on each cloud
```bash title="AWS CLI, Key-value and document database" nocheck
aws dynamodb create-table --table-name carts --attribute-definitions AttributeName=userId,AttributeType=S --key-schema AttributeName=userId,KeyType=HASH --billing-mode PAY_PER_REQUEST
```
```bash title="Azure CLI, Key-value and document database" nocheck
az cosmosdb create --resource-group rg-demo --name demo-cosmos-123 --kind GlobalDocumentDB
az cosmosdb sql database create --resource-group rg-demo --account-name demo-cosmos-123 --name shop
```
```bash title="gcloud, Key-value and document database" nocheck
gcloud firestore databases create --location=europe-west1 --type=firestore-native
gcloud bigtable instances create demo-bt --display-name=demo --cluster-config=id=c1,zone=europe-west1-b,nodes=1
```
@check
What is the first design step for these stores? || List the access patterns and choose keys to serve them.
@end

@concept 14. In-memory cache
@plain
A very fast store that keeps data in memory, usually Redis or Memcached compatible.
@problem
Repeating the same database query on every request is slow and overloads the database.
@does
- **Names**: AWS ElastiCache; Azure Azure Cache for Redis; GCP Memorystore.
- **What it is**: Holds hot data, sessions, counters and queues with optional replicas and failover.
- **Choose it when**: Read-heavy lookups and sessions; Rate limiting and leaderboards; Reducing load on a relational database.
- **Check in the current docs**: Cache data can be lost, so the source of truth must live elsewhere; Product lines and engine choices change, so check the current docs for Redis and Valkey support; Eviction policy and memory sizing decide hit rate.
@diagram cmp
caption: In-memory cache on the three clouds
cards:
  - {h: "ElastiCache", kind: warn, items: ["Redis OSS and Valkey, Memcached, replication groups"]}
  - {h: "Azure Cache for Redis", kind: info, items: ["Redis tiers with clustering and persistence"]}
  - {h: "Memorystore", kind: ok, items: ["Redis and Valkey instances with HA tiers"]}
@h Example
Product pages are cached for five minutes so the database sees one query per product rather than one per visitor.
@h CLI on each cloud
```bash title="AWS CLI, In-memory cache" nocheck
aws elasticache create-replication-group --replication-group-id demo-cache --replication-group-description demo --engine redis --cache-node-type cache.t4g.micro --num-cache-clusters 2 --automatic-failover-enabled
```
```bash title="Azure CLI, In-memory cache" nocheck
az redis create --resource-group rg-demo --name demo-redis-123 --location westeurope --sku Standard --vm-size c1
```
```bash title="gcloud, In-memory cache" nocheck
gcloud redis instances create demo-redis --region=europe-west1 --tier=standard --size=1
```
@check
Can a cache be the only copy of data? || No, it can lose data, so keep a durable source of truth.
@end

@concept 15. Global relational database
@plain
A relational database that keeps copies in several regions so users worldwide read locally and a region loss does not lose the service.
@problem
A single-region database cannot give low latency to distant users or survive a regional outage with near-zero data loss.
@does
- **Names**: AWS Aurora DSQL or Aurora Global Database; Azure Cosmos DB or SQL Hyperscale geo-replicas; GCP Spanner.
- **What it is**: Replicates data across regions, with either one writer plus fast replicas or multi-region strongly consistent writes, depending on the product.
- **Choose it when**: Global users needing local reads; Regional-outage tolerance with tight RPO; Financial or inventory data needing strong consistency.
- **Check in the current docs**: Write latency rises with distance because commits need cross-region agreement on strongly consistent designs; Products differ widely in consistency and compatibility, so check the current docs; Cost is much higher than a single-region database.
@diagram cmp
caption: Global relational database on the three clouds
cards:
  - {h: "Aurora DSQL or Aurora Global Database", kind: warn, items: ["Aurora Global Database with a primary region, Aurora DSQL"]}
  - {h: "Cosmos DB or SQL Hyperscale geo-replicas", kind: info, items: ["Cosmos DB multi-region writes, geo-replicas"]}
  - {h: "Spanner", kind: ok, items: ["Spanner multi-region configurations"]}
@h Example
An inventory system uses Spanner with three regions so any region can serve reads and a region loss keeps writes available.
@h CLI on each cloud
```bash title="AWS CLI, Global relational database" nocheck
aws rds create-global-cluster --global-cluster-identifier demo-global --source-db-cluster-identifier arn:aws:rds:eu-west-1:111122223333:cluster:demo-aurora
```
```bash title="Azure CLI, Global relational database" nocheck
az cosmosdb update --resource-group rg-demo --name demo-cosmos-123 --locations regionName=westeurope failoverPriority=0 --locations regionName=northeurope failoverPriority=1
```
```bash title="gcloud, Global relational database" nocheck
gcloud spanner instances create demo --config=nam3 --description=demo --processing-units=100
```
@check
Why can global strong consistency raise write latency? || Commits must be acknowledged across regions, so distance adds time.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Choosing a NoSQL store without listing access patterns.
- Treating a cache as durable.
- Paying for global consistency nobody needs.
- Always confirm limits, prices and regional availability in the current documentation before committing.
@diagram flow
caption: A safe habit before adopting any service
nodes:
  - "Define need|workload, size, latency|plain"
  - "Map services|three cloud names|info"
  - "Check docs|limits, price, regions|warn"
  - "Prototype|measure on real data|app"
  - "Decide|record in an ADR|ok"
@h Habit as a checklist
```yaml title="service-evaluation.yaml" nocheck
service: Managed relational database
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

