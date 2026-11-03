---
title: DynamoDB and ElastiCache
minutes: 45
objectives:
  - Model DynamoDB tables with partition and sort keys and choose a capacity mode
  - Use indexes, TTL, streams and global tables appropriately
  - Deploy ElastiCache for Redis or Valkey with replication and failover
---
Not everything belongs in a relational database. DynamoDB and ElastiCache cover key-value storage and caching and are common neighbours of EKS workloads.

@concept DynamoDB tables and keys
@plain
DynamoDB is a fully managed key-value and document database. Each item is found by its **partition key**, and optionally a **sort key** that orders items sharing the same partition key.
@problem
Relational databases are hard to scale horizontally. DynamoDB gives predictable single-digit millisecond reads and writes at nearly any size if you design around access patterns.
@does
- The partition key is hashed to place data across partitions; a poor key (for example a date) makes a **hot partition**.
- Query by exact partition key plus an optional sort-key condition. A `Scan` reads everything and should be avoided.
- Items are up to 400 KB (check the quota); attributes are schemaless except keys.
- Design from the questions your application asks, and often put several entity types in one table.
@diagram layers
caption: Orders table with a composite key
layers:
  - {label: "Table shop-orders", nodes: ["PK customer_id|partition key|cp", "SK order_date|sort key|cp"]}
  - {label: "Items", nodes: ["C1 / 2026-10-01|total 40|app", "C1 / 2026-10-12|total 75|app", "C2 / 2026-10-03|total 12|app"]}
@h Create and use
```bash title="Create a table and query it" lab
aws dynamodb create-table --table-name shop-orders \
  --attribute-definitions AttributeName=customer_id,AttributeType=S AttributeName=order_date,AttributeType=S \
  --key-schema AttributeName=customer_id,KeyType=HASH AttributeName=order_date,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST
aws dynamodb put-item --table-name shop-orders \
  --item '{"customer_id":{"S":"C1"},"order_date":{"S":"2026-10-12"},"total":{"N":"75"}}'
aws dynamodb query --table-name shop-orders \
  --key-condition-expression "customer_id = :c AND order_date >= :d" \
  --expression-attribute-values '{":c":{"S":"C1"},":d":{"S":"2026-10-01"}}'
```
@check
Why avoid Scan? || It reads every item, consuming capacity proportional to the table size.
@end

@concept Capacity modes and throttling
@plain
You pay for reads and writes in one of two modes: on-demand (per request) or provisioned (capacity units per second, optionally with auto scaling).
@problem
Underprovisioned tables throttle with `ProvisionedThroughputExceededException`; overprovisioned ones waste money.
@does
- **On-demand** needs no planning and handles spikes; per-request price is higher.
- **Provisioned** with autoscaling is cheaper for predictable traffic; reserved capacity discounts exist.
- One RCU is one strongly consistent read per second of up to 4 KB; one WCU is one write of up to 1 KB per second. Eventually consistent reads cost half.
- Use exponential backoff and jitter; AWS SDKs retry by default.
- The **Standard-IA** table class lowers storage cost for rarely read data.
@diagram cmp
caption: Capacity mode choice
cards:
  - {h: "On-demand", kind: ok, items: ["Zero planning", "New or spiky workloads", "Higher unit price"]}
  - {h: "Provisioned plus autoscaling", kind: app, items: ["Cheaper at steady load", "Needs target utilisation tuning"]}
@h Switch mode
```bash title="Provisioned with autoscaling target" nocheck
aws dynamodb update-table --table-name shop-orders --billing-mode PROVISIONED \
  --provisioned-throughput ReadCapacityUnits=50,WriteCapacityUnits=25
aws application-autoscaling register-scalable-target --service-namespace dynamodb \
  --resource-id table/shop-orders --scalable-dimension dynamodb:table:ReadCapacityUnits \
  --min-capacity 50 --max-capacity 500
```
@check
How much does an eventually consistent 4 KB read cost compared with strongly consistent? || Half of one read capacity unit.
@end

@concept Indexes, TTL and streams
@plain
Secondary indexes give alternative query keys. TTL deletes expired items for free. Streams emit a change record for each write.
@problem
A key design serves one access pattern; other queries need alternative keys, and applications need to react to changes or expire data without cron jobs.
@does
- **Global secondary index (GSI)**: different partition and sort key, its own capacity, eventually consistent.
- **Local secondary index (LSI)**: same partition key, alternative sort key; must be created with the table.
- **TTL**: an attribute holding a Unix epoch time; DynamoDB deletes items some time after expiry (usually within days, so filter in queries).
- **Streams** feed Lambda or Kinesis for events, search sync and audit.
- **PITR** continuous backups restore to any second in the last 35 days; enable it on every important table.
@diagram flow
caption: A write fans out
nodes:
  - "Write item|PutItem|app"
  - "Table|base keys|cp"
  - "GSI|alternate query|info"
  - "Stream|change event|env"
  - "Lambda or consumer|react|ok"
@h Enable features
```bash title="TTL, PITR and a GSI" nocheck
aws dynamodb update-time-to-live --table-name shop-orders \
  --time-to-live-specification Enabled=true,AttributeName=expires_at
aws dynamodb update-continuous-backups --table-name shop-orders \
  --point-in-time-recovery-specification PointInTimeRecoveryEnabled=true
```
:::tip
Choose a GSI key with high cardinality; a status field with three values creates a hot partition.
:::
@check
Can you add an LSI to an existing table? || No; LSIs must be defined at table creation.
@end

@concept Global tables and access from EKS
@plain
A global table replicates a DynamoDB table across Regions with multi-writer semantics. Pods access DynamoDB through IAM roles.
@problem
Multi-Region active-active applications need local low-latency writes, and pods must reach the table without static credentials.
@does
- Global tables (version 2019.11.21) replicate asynchronously, usually within a second; conflicts resolve **last writer wins** by timestamp.
- Use a VPC **gateway endpoint** for DynamoDB so traffic stays on the AWS network and avoids NAT charges.
- Grant the pod an IAM role via IRSA or Pod Identity with least privilege on the table ARN.
@diagram flow
caption: Active-active with global tables
nodes:
  - "App us-east-1|local reads and writes|app"
  - "Table replica|us-east-1|cp"
  - "Replication|async, last writer wins|info"
  - "Table replica|eu-west-1|cp"
@h Least privilege policy
```json title="Pod role policy for shop-orders"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query", "dynamodb:UpdateItem"],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:111122223333:table/shop-orders",
        "arn:aws:dynamodb:us-east-1:111122223333:table/shop-orders/index/*"
      ]
    }
  ]
}
```
```bash title="Gateway endpoint to avoid NAT cost" nocheck
aws ec2 create-vpc-endpoint --vpc-id vpc-0abc --service-name com.amazonaws.us-east-1.dynamodb \
  --route-table-ids rtb-0111 rtb-0222
```
@check
How are write conflicts resolved in global tables? || Last writer wins, based on timestamps.
@end

@concept ElastiCache for Redis and Valkey
@plain
ElastiCache runs in-memory stores (Valkey, Redis OSS, Memcached) as a managed service. Applications use them to hold hot data and sessions with sub-millisecond reads.
@problem
Repeated database reads for the same product or session data waste capacity and add latency.
@does
- A **replication group** has one primary and up to five replicas across AZs; with Multi-AZ and automatic failover, a replica is promoted on failure.
- **Cluster mode enabled** shards data over several node groups for more memory and throughput.
- Use TLS in transit (`--transit-encryption-enabled`), at-rest encryption and AUTH or IAM authentication.
- Eviction policy (`maxmemory-policy`, often `allkeys-lru`) decides what happens when memory fills.
- Cache is not the system of record: design for cold starts and use TTLs.
- **ElastiCache Serverless** removes node sizing; you pay for data stored and compute used (check current pricing).
@diagram flow
caption: Cache-aside pattern
numbered: true
nodes:
  - "App|needs product 42|app"
  - "Cache|hit returns at once|ok"
  - "Miss|read database|warn"
  - "Database|source of truth|cp"
  - "Fill cache|set with TTL|info"
@h Create
```hcl title="Valkey replication group with Multi-AZ"
resource "aws_elasticache_replication_group" "shop" {
  replication_group_id       = "shop-cache"
  description                = "Shop sessions and catalog cache"
  engine                     = "valkey"
  node_type                  = "cache.r7g.large"
  num_cache_clusters         = 3
  automatic_failover_enabled = true
  multi_az_enabled           = true
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.shop.name
  security_group_ids         = [aws_security_group.cache.id]
  parameter_group_name       = "default.valkey7"
}
```
@check
What happens to the data if the cache cluster is lost? || Nothing authoritative is lost, since the database is the source of truth; the cache is rebuilt on demand.
@end
