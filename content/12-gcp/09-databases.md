---
title: Databases on Google Cloud
minutes: 65
objectives:
  - Choose the right managed database for a workload
  - Run Cloud SQL for PostgreSQL with high availability, replicas and private networking
  - Explain how AlloyDB, Spanner, Firestore, Bigtable and Memorystore differ from RDS, Aurora, DynamoDB and ElastiCache
---
Google Cloud has more distinct database products than a typical AWS design uses. Picking the right one early matters because moving later is costly.

@concept Choosing a database
@plain
The choice depends on the data model (relational, document, wide column, key-value), scale, consistency and region needs.
@problem
Using one engine for everything either costs too much or hits scaling limits.
@does
- **Cloud SQL**: managed MySQL, PostgreSQL, SQL Server. **AlloyDB**: PostgreSQL-compatible with higher performance. **Spanner**: global relational with strong consistency.
- **Firestore**: serverless document database. **Bigtable**: wide column for huge throughput. **Memorystore**: Redis or Valkey and Memcached.
- **BigQuery**: analytics, not transactions.
- **AWS equivalent**: RDS, Aurora, DynamoDB, ElastiCache; Spanner has no direct match. Main difference: Spanner combines horizontal scale with SQL and external consistency.
@diagram layers
caption: Pick by model
layers:
  - {label: "Relational", nodes: ["Cloud SQL|RDS|app", "AlloyDB|Aurora PostgreSQL|app", "Spanner|global scale|cp"]}
  - {label: "NoSQL", nodes: ["Firestore|DynamoDB documents|info", "Bigtable|wide column|info"]}
  - {label: "Cache and analytics", nodes: ["Memorystore|ElastiCache|warn", "BigQuery|Redshift|env"]}
@choose Which one for the Shop
Cloud SQL for PostgreSQL | orders and catalog at modest scale | you need multi-region writes
AlloyDB | heavy PostgreSQL with analytics queries | you want the lowest cost for a small database
Spanner | global writes with strong consistency | a single regional PostgreSQL meets the need
Memorystore | sessions and caches | you need durable primary storage
@end

@concept Cloud SQL
@plain
**Cloud SQL** is a managed PostgreSQL, MySQL or SQL Server service with backups, patching, replicas and failover.
@problem
Running a database yourself costs on-call time for backups, upgrades and failover.
@does
- Editions: Enterprise and Enterprise Plus (check current features like near-zero downtime maintenance).
- **High availability** uses a standby in another zone of the same region with synchronous replication and automatic failover.
- Automated backups and point-in-time recovery, maintenance windows, flags and storage auto-increase.
- Connect with **private IP** (private services access or PSC), the Cloud SQL Auth Proxy, or language connectors with IAM database authentication.
- **AWS equivalent**: RDS. Main difference: the Auth Proxy handles TLS and IAM login without opening IP allow lists.
@diagram flow
caption: Cloud SQL HA
nodes:
  - "App|Auth Proxy|app"
  - "Primary|zone b|db"
  - "Standby|zone c|db"
  - "Backups and PITR|retained|ok"
@h Create a private HA instance
```bash title="Cloud SQL PostgreSQL" lab
gcloud sql instances create shop-pg --database-version=POSTGRES_16 --edition=ENTERPRISE \
  --tier=db-custom-2-7680 --region=europe-west1 --availability-type=REGIONAL \
  --network=projects/shop-dev-123456/global/networks/shop-net --no-assign-ip \
  --backup-start-time=02:00 --enable-point-in-time-recovery
gcloud sql databases create shop --instance=shop-pg
gcloud sql users create shop_app --instance=shop-pg --type=CLOUD_IAM_SERVICE_ACCOUNT
```
:::note
The `--network` option needs private services access set up first. Verify tier names and edition options in the current docs.
:::
@check
Where is the HA standby placed? || In another zone of the same region.
@end

@concept Cloud SQL replicas and migration
@plain
**Read replicas** serve read traffic and can be promoted. **Database Migration Service (DMS)** moves data from other databases with little downtime.
@problem
Reads overload the primary, and moving from on-premises or RDS needs continuous replication.
@does
- Replicas can be in another region (cross-region disaster recovery) and cascade in some versions.
- Replicas are asynchronous, so there is lag. Promotion is manual and breaks the link.
- DMS supports continuous migrations for PostgreSQL and MySQL, from RDS, on-premises, and others; it needs network connectivity and logical replication settings.
- **AWS equivalent**: RDS read replicas and AWS DMS. Main difference: DMS is a separate Google service with migration jobs and connection profiles.
@diagram flow
caption: Replica topology
nodes:
  - "Primary|europe-west1|db"
  - "Replica|europe-west1|db"
  - "DR replica|us-central1|db"
  - "Promote|manual on disaster|warn"
@h Create a replica
```bash title="Replica" lab
gcloud sql instances create shop-pg-r1 --master-instance-name=shop-pg --region=europe-west1
gcloud sql instances create shop-pg-dr --master-instance-name=shop-pg --region=us-central1
gcloud sql instances promote-replica shop-pg-dr
```
@end

@concept AlloyDB for PostgreSQL
@plain
**AlloyDB** is a PostgreSQL-compatible database with a separate, log-based storage layer and read pools.
@problem
Cloud SQL scaling and analytics performance can be limiting for heavy PostgreSQL workloads.
@does
- A **cluster** has a primary instance and optional **read pool** instances sharing storage. Storage scales automatically.
- A columnar engine speeds up analytical queries on the same data.
- Regional availability with automatic failover. Connect with private IP or the AlloyDB Auth Proxy.
- Cross-region replicas exist as secondary clusters.
- **AWS equivalent**: Aurora PostgreSQL. Main difference: the same design idea; priced and sized differently, so compare costs with current price lists.
@diagram layers
caption: AlloyDB layout
layers:
  - {label: "Compute", nodes: ["Primary instance|reads and writes|app", "Read pool|scale out reads|app"]}
  - {label: "Storage", nodes: ["Shared distributed storage|replicated across zones|db"]}
@h Create
```bash title="AlloyDB" lab
gcloud alloydb clusters create shop-alloy --region=europe-west1 --password="$ALLOY_PASS" \
  --network=projects/shop-dev-123456/global/networks/shop-net
gcloud alloydb instances create shop-primary --cluster=shop-alloy --region=europe-west1 \
  --instance-type=PRIMARY --cpu-count=4
```
@check
What do read pool instances share with the primary? || The same storage layer.
@end

@concept Spanner
@plain
**Spanner** is a horizontally scalable relational database with strong consistency, SQL, and multi-region replication.
@problem
Traditional relational databases cannot scale writes across regions without sharding.
@does
- Capacity is **processing units** (1000 = 1 node) or autoscaling. Instances are regional or multi-region configurations.
- Schema design matters: avoid monotonically increasing primary keys that create hotspots; use UUIDs or bit-reversed keys.
- Interleaved tables and foreign keys co-locate data; PostgreSQL interface is available.
- Strong external consistency and a published 99.999 percent SLA for multi-region configs.
- **AWS equivalent**: no direct match (check the status of Aurora DSQL as the nearest offering). Main difference: global writes with consistency is its core.
@diagram flow
caption: Spanner replicas
nodes:
  - "Client|any region|ext"
  - "Leader replica|writes|cp"
  - "Read-write replicas|synchronous quorum|db"
  - "Witness|tie breaker|info"
@h Create
```bash title="Spanner" lab
gcloud spanner instances create shop-spanner --config=regional-europe-west1 \
  --description="Shop" --processing-units=100
gcloud spanner databases create shop --instance=shop-spanner \
  --database-dialect=POSTGRESQL
```
@end

@concept Firestore and Bigtable
@plain
**Firestore** is a serverless document database with real-time sync. **Bigtable** is a wide-column store for very large, low-latency key-based workloads.
@problem
Some data (profiles, sessions, time series, IoT telemetry) does not need a relational engine and needs massive scale.
@does
- Firestore Native mode: documents in collections, indexes automatic, strong consistency, offline sync for mobile, multi-region options. A Datastore mode and a MongoDB compatible edition exist too; check current docs.
- Bigtable: tables with a row key; design the key for even distribution; scale by adding nodes. It has an HBase API.
- Neither supports joins. Pick keys for the access pattern.
- **AWS equivalent**: DynamoDB (for both). Main difference: DynamoDB is one product; Google splits document and wide column use.
@diagram cmp
caption: Two NoSQL options
cards:
  - {h: "Firestore", kind: app, items: ["Documents and collections", "Serverless, pay per operation", "Real-time listeners"]}
  - {h: "Bigtable", kind: info, items: ["Row key and column families", "Provisioned nodes", "Time series, analytics feeds"]}
@h Bigtable quick start
```bash title="cbt and gcloud" lab
gcloud bigtable instances create shop-bt --display-name="Shop" --cluster-config=id=c1,zone=europe-west1-b,nodes=1
cbt -instance=shop-bt createtable events "families=cf1"
cbt -instance=shop-bt set events user1#20261101 cf1:type=view
```
@check
What decides Bigtable performance more than node count? || The row key design.
@end

@concept Memorystore
@plain
**Memorystore** is managed in-memory data: Memorystore for Redis, Redis Cluster, Valkey and Memcached.
@problem
Caches, sessions and rate counters need sub-millisecond reads without running Redis yourself.
@does
- Basic tier has no replication; Standard tier has a replica and automatic failover. Redis Cluster shards across nodes.
- Instances are reachable by private IP in your VPC (private services access or PSC); authentication and in-transit encryption are options.
- Sizes are in GB; eviction policy is a configuration flag.
- **AWS equivalent**: ElastiCache and MemoryDB. Main difference: it is only accessible from the VPC. Check current docs for Valkey support and product naming.
@diagram flow
caption: Cache aside
nodes:
  - "API pod|checks cache|app"
  - "Memorystore|Redis|warn"
  - "Cloud SQL|on miss|db"
@h Create
```bash title="Memorystore Redis" lab
gcloud redis instances create shop-cache --region=europe-west1 --tier=STANDARD --size=2 \
  --redis-version=redis_7_2 --network=shop-net --connect-mode=PRIVATE_SERVICE_ACCESS --transit-encryption-mode=SERVER_AUTHENTICATION
gcloud redis instances describe shop-cache --region=europe-west1 --format="value(host,port)"
```
@end
