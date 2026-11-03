---
title: Amazon OpenSearch Service
minutes: 45
objectives:
  - Describe domains, nodes, shards and replicas
  - Size a domain and secure it inside a VPC
  - Manage index lifecycle, snapshots and the serverless option
---
OpenSearch Service runs search and log analytics clusters. It is powerful but needs careful sizing and index management.

@concept When to use OpenSearch
@plain
OpenSearch indexes JSON documents so you can run full-text search, filters, aggregations and vector search quickly.
@problem
Databases are poor at free-text search, relevance ranking and fast aggregations over logs.
@does
- Use cases: application search, log analytics, observability, security analytics, vector search for AI retrieval.
- It is not a primary database; keep the source of truth elsewhere and index copies.
- Ingest from Firehose, Logstash, Fluent Bit, DynamoDB streams or OpenSearch Ingestion.
- Managed domains or OpenSearch Serverless collections.
@diagram flow
caption: Search pipeline
nodes:
  - "Source of truth|database or logs|ok"
  - "Ingest|Firehose or Ingestion pipeline|info"
  - "OpenSearch|index|cp"
  - "App or Dashboards|query|app"
@h Check cluster health
```bash title="Health" nocheck
curl -s -u "$USER:$PASS" "https://$DOMAIN/_cluster/health?pretty"
```
@check
Is OpenSearch a good system of record? || No. Keep the source of truth in a database and treat the index as a derived copy.
@end

@concept Domains, nodes, shards and replicas
@plain
A **domain** is a cluster. Indexes are split into **primary shards**, each with **replica** copies on other nodes.
@problem
One node is a single point of failure, and one huge shard cannot be spread out for speed.
@does
- Production: three dedicated master nodes and data nodes across three AZs (Multi-AZ with standby is an option; check the current options).
- Primary shard count is fixed at index creation; replicas can change at any time.
- Aim for shard sizes of roughly 10 to 50 GB (guideline, depending on use) and avoid thousands of tiny shards.
- Example: 300 GB of data per day index with 30 GB shards needs 10 primaries; with 1 replica that is 20 shards total and 600 GB of storage before overhead.
@diagram layers
caption: Domain layout
layers:
  - {label: "Control", nodes: ["Master node 1|AZ a|cp", "Master node 2|AZ b|cp", "Master node 3|AZ c|cp"]}
  - {label: "Data", nodes: ["Data node|primaries and replicas|app", "Data node|primaries and replicas|app", "Data node|primaries and replicas|app"]}
@h Index settings
```json title="index-settings.json"
{
  "settings": {
    "index": {
      "number_of_shards": 10,
      "number_of_replicas": 1
    }
  }
}
```
@check
Can you change primary shard count of an existing index freely? || No. It is fixed at creation; reindex, split or shrink to change it.
@end

@concept Sizing storage and instances
@plain
Size by raw data per day, retention, replicas and overhead, then choose instance types for memory and IOPS.
@problem
Undersized domains go red under load; oversized ones are very expensive.
@does
- Storage estimate = source data x (1 + replicas) x indexing overhead (often around 1.1 to 1.45 depending on mappings, check by testing) x days retained.
- Example: 100 GB per day, 1 replica, overhead 1.25, 14 days gives 100 x 2 x 1.25 x 14 = 3,500 GB, plus free space headroom of about 25 percent so provision about 4,375 GB.
- Memory-optimised (R family) or Graviton nodes for search; **UltraWarm** and cold tiers store older data cheaply.
- Keep JVM heap pressure under control; alarm on it.
@diagram cmp
caption: Hot warm cold
cards:
  - {h: "Hot", kind: warn, items: ["Recent data", "Fast instance storage", "Highest cost"]}
  - {h: "UltraWarm", kind: info, items: ["Older read mostly", "Backed by S3", "Cheaper"]}
  - {h: "Cold", kind: ok, items: ["Rarely read", "Attach on demand", "Lowest cost"]}
@h Sizing in Python
```python title="size.py"
daily_gb, replicas, overhead, days = 100, 1, 1.25, 14
data = daily_gb * (1 + replicas) * overhead * days
print(data, data / 0.8)
```
@end

@concept Network and access security
@plain
Put the domain in a VPC, use fine-grained access control and a resource policy, and encrypt everything.
@problem
Public domains with weak policies are a common source of data leaks.
@does
- VPC domains have no public endpoint; reach them through the VPC, VPN or a proxy.
- Fine-grained access control maps IAM or internal users to roles for index, document and field level security.
- Enable node-to-node encryption, encryption at rest with KMS, enforce HTTPS and TLS 1.2 or later.
- Sign requests with SigV4 for IAM access.
@diagram layers
caption: Security layers
layers:
  - {label: "Network", nodes: ["VPC subnets|private only|info", "Security group|443 from apps|info"]}
  - {label: "Identity", nodes: ["Resource policy|who can call|cp", "Fine-grained roles|index and field|cp"]}
  - {label: "Data", nodes: ["KMS at rest|encryption|ok", "TLS in transit|node to node|ok"]}
@h Domain policy
```json title="domain-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::111122223333:role/search-app"},
    "Action": "es:ESHttp*",
    "Resource": "arn:aws:es:eu-west-1:111122223333:domain/logs/*"
  }]
}
```
@check
Why prefer a VPC domain? || It has no public endpoint, reducing exposure.
@end

@concept Index lifecycle and snapshots
@plain
Use **Index State Management** policies to roll over, move, and delete indexes on a schedule. Snapshots protect against loss.
@problem
Time-series indexes grow forever and a failed cluster can lose data.
@does
- Rollover by size or age; transition to UltraWarm; delete after retention.
- Automated hourly snapshots are kept by the service for a limited time; for long-term backups register a manual snapshot repository in S3.
- Rebuild from the source of truth when possible; snapshots speed recovery.
- Use index templates so every new index gets the right mappings and settings.
@diagram flow
caption: Lifecycle
numbered: true
nodes:
  - "Write index|hot|warn"
  - "Rollover|50 GB or 1 day|info"
  - "Warm|read mostly|info"
  - "Delete|after 30 days|bad"
@h ISM policy
```json title="ism-policy.json"
{
  "policy": {
    "description": "hot to delete",
    "default_state": "hot",
    "states": [
      {"name": "hot", "actions": [{"rollover": {"min_size": "50gb", "min_index_age": "1d"}}],
       "transitions": [{"state_name": "delete", "conditions": {"min_index_age": "30d"}}]},
      {"name": "delete", "actions": [{"delete": {}}], "transitions": []}
    ]
  }
}
```
@end

@concept OpenSearch Serverless and operations
@plain
**OpenSearch Serverless** removes node and shard management: you create a collection and pay for compute (OCUs) and storage.
@problem
Capacity planning and cluster upgrades consume time for teams with variable search needs.
@does
- Collection types: search, time series, vector search.
- Security through encryption, network and data access policies instead of node roles.
- Billed in OpenSearch Compute Units with a minimum; for small steady workloads a managed domain can be cheaper. Check the current minimums and price.
- For managed domains monitor `ClusterStatus.red`, `FreeStorageSpace`, `JVMMemoryPressure`, `CPUUtilization`.
@diagram cmp
caption: Domain or serverless
cards:
  - {h: "Managed domain", kind: cp, items: ["Choose nodes", "Full tuning", "Predictable cost at steady load"]}
  - {h: "Serverless collection", kind: ok, items: ["No nodes", "Scales with OCUs", "Fewer tuning options"]}
@choose Pick
Managed domain | steady load and you need tuning control | nobody can size and patch clusters
Serverless | variable load and a small team | you need features not yet supported there
@h Alarm
```hcl title="os-alarm.tf"
resource "aws_cloudwatch_metric_alarm" "red" {
  alarm_name          = "opensearch-red"
  namespace           = "AWS/ES"
  metric_name         = "ClusterStatus.red"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
}
```
@check
Which status means some primary shard is unassigned? || Red.
@end
