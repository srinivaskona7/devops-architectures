---
title: Cluster sizing, capacity and cost
minutes: 55
objectives:
  - Estimate storage from daily ingest, replicas and retention
  - Size node counts and heap using documented rules of thumb
  - Reduce cost with mappings, compression and tiering
---
Most Elasticsearch pain comes from sizing: too little disk, too few nodes for the shard count, or logs that were never worth keeping. The arithmetic is simple when you do it before buying.

@concept Node roles in a cluster
@plain
Production clusters separate jobs. **Master-eligible** nodes manage cluster state, **data** nodes store and search, **ingest** nodes run pipelines, and **coordinating** nodes route requests.
@problem
When one node does everything, a heavy query can starve the master and the whole cluster becomes unstable.
@does
- Run exactly 3 dedicated master-eligible nodes (small, e.g. 2-4 vCPU, 8 GB RAM) so a majority survives one failure.
- Data nodes per tier carry most of the cost.
- Add dedicated coordinating or ingest nodes only when profiling shows they help.
- Never set an even number of master-eligible nodes.
@diagram layers
caption: A small production layout
layers:
  - {label: "Control", nodes: ["3 master nodes|cluster state|cp"]}
  - {label: "Data", nodes: ["Hot data nodes|recent logs|bad", "Warm data nodes|older logs|warn"]}
  - {label: "Edge", nodes: ["Coordinating or ingest|optional|info"]}
@end

@concept Heap and memory
@plain
Elasticsearch runs on the JVM. The **heap** holds caches and cluster state; the rest of RAM is used by the operating system file cache, which Lucene relies on.
@problem
Giving the JVM all the RAM starves the file cache, and too large a heap loses compressed object pointers and suffers long garbage collection.
@does
- Set heap to about half of RAM, and no more than about 30 GB (check the current docs for the compressed-pointers threshold).
- Example: a 64 GB node gets a 30 GB heap and 34 GB for the file cache.
- Set `-Xms` and `-Xmx` equal. Elasticsearch sizes the heap automatically in recent versions; override only with reason.
- On Kubernetes set container memory limit about 2x the heap.
@diagram cmp
caption: Splitting 64 GB of RAM
cards:
  - {h: "JVM heap", kind: warn, items: ["30 GB", "Caches, cluster state, aggregations"]}
  - {h: "OS file cache", kind: ok, items: ["34 GB", "Lucene segments in memory", "Search speed"]}
@end

@concept Estimating storage
@plain
Total disk = daily raw volume × index overhead × (1 + replicas) × retention days ÷ target disk fill.
@problem
Disk full is the most common production failure. Elasticsearch stops allocating at the low watermark (85 percent by default) and blocks writes at the flood stage (95 percent).
@does
- Index size relative to raw JSON varies from about 0.5 to 1.5 times; measure with your own data (a first estimate of 1.1 is common).
- Worked example: 200 GB per day raw × 1.1 = 220 GB primary data per day; with 1 replica that is 440 GB per day.
- 30 days retention: 440 × 30 = 13 200 GB. To keep disks at no more than 85 percent: 13 200 ÷ 0.85 = 15 529 GB of provisioned disk.
- Split by tier: 7 days hot = 3 080 GB; 23 days warm = 10 120 GB.
@diagram flow
caption: Storage arithmetic
numbered: true
nodes:
  - "200 GB raw per day|from log volume|plain"
  - "times 1.1|220 GB primary|info"
  - "times 2 for one replica|440 GB per day|warn"
  - "times 30 days|13200 GB|app"
  - "divide by 0.85|15529 GB provisioned|ok"
@h Check the numbers
```python title="storage.py" lab
raw_gb, overhead, replicas, days, fill = 200, 1.1, 1, 30, 0.85
per_day = raw_gb * overhead * (1 + replicas)
total = per_day * days
print("per day", round(per_day), "total", round(total), "provisioned", round(total / fill))
print("hot 7d", round(per_day * 7), "warm 23d", round(per_day * 23))
```
@check
If you drop to zero replicas on warm, what is the warm storage? || 220 GB × 23 days = 5 060 GB, but you lose redundancy; rely on snapshots.
@end

@concept Sizing the node count
@plain
Work out nodes from disk per node and the shard budget, then check indexing throughput.
@problem
Buying disk without checking RAM and shard limits gives a cluster that has space but is slow or unstable.
@does
- Memory-to-disk ratios (rule of thumb): hot about 1:30, warm about 1:160. Check Elastic's current guidance.
- Hot example: 3 080 GB ÷ 0.85 = 3 624 GB provisioned. At a 1:30 ratio a 64 GB node serves 64 × 30 = 1 920 GB, so 3 624 ÷ 1 920 = 1.9, which rounds up to 2; use 3 nodes for resilience.
- Warm example: 10 120 GB ÷ 0.85 = 11 906 GB. At 1:160 a 64 GB node serves 10 240 GB, so you need 2 nodes minimum; use 3.
- Shard check: 7 days × 5 primary shards × 2 (replica) = 70 hot shards; far below 600 per 30 GB heap.
- Always load test with your real queries.
@diagram flow
caption: From volume to node count
nodes:
  - "Provisioned disk|per tier|info"
  - "Disk per node|RAM times ratio|warn"
  - "Divide and round up|add one for failure|app"
  - "Shard budget check|under 20 per GB heap|ok"
@end

@concept Reducing cost
@plain
Most savings come from storing less, not from cheaper disks: remove unused fields, shorten retention for noisy logs and move data to cheaper tiers sooner.
@problem
Log volume grows faster than budget. Debug logs from a chatty service can double the bill.
@does
- Drop health-check and debug logs at the agent before they leave the node.
- Disable indexing for fields you never search (`"index": false`) and avoid duplicate `text` plus `keyword` mapping where not needed.
- Use `best_compression` codec on warm indices and force-merge to one segment.
- Use zero replicas on cold data backed by snapshots, searchable snapshots for long retention, and sample verbose logs.
- Separate retention by data type: security audit 1 year, app info 14 days, debug 3 days.
@diagram cmp
caption: Where the savings are
cards:
  - {h: "Send less", kind: ok, items: ["Drop noise at the agent", "Sample debug logs", "Remove duplicate fields"]}
  - {h: "Store smaller", kind: info, items: ["best_compression", "Index false for unused fields", "Force merge"]}
  - {h: "Store cheaper", kind: warn, items: ["Warm and cold tiers", "Searchable snapshots", "Short debug retention"]}
@h Index setting example
```json
{
  "settings": {
    "index.codec": "best_compression",
    "index.refresh_interval": "30s"
  },
  "mappings": {
    "properties": {
      "debug_blob": { "type": "keyword", "index": false, "doc_values": false }
    }
  }
}
```
@end

@concept Monitoring the cluster
@plain
Monitor Elasticsearch itself: cluster health, disk, heap, indexing rejections and shard counts.
@problem
A full disk or a growing queue shows up in logs only when it is already an incident.
@does
- `GET _cluster/health`: green (all shards allocated), yellow (replicas missing), red (a primary missing).
- Watch disk watermarks, JVM heap above 85 percent for long periods, `write` thread pool rejections and pending tasks.
- Use Elastic's Stack Monitoring or the Prometheus `elasticsearch_exporter`.
- Alert on yellow for more than 15 minutes and red immediately.
@diagram flow
caption: Health colours
nodes:
  - "Green|all shards allocated|ok"
  - "Yellow|replicas missing|warn"
  - "Red|primary missing, data unavailable|bad"
@h Quick checks
```bash title="First look at a sick cluster" lab
curl -s -u elastic:$ES_PASSWORD "$ES_URL/_cluster/health?pretty"
curl -s -u elastic:$ES_PASSWORD "$ES_URL/_cat/allocation?v"
curl -s -u elastic:$ES_PASSWORD "$ES_URL/_cat/thread_pool/write?v&h=node_name,active,queue,rejected"
curl -s -u elastic:$ES_PASSWORD "$ES_URL/_cluster/allocation/explain?pretty"
```
@end

@concept Retention policy as a business decision
@plain
Retention is how long each kind of log stays searchable. It is a trade between cost, legal duty and usefulness.
@problem
"Keep everything forever" is the default when nobody decides, and it is the most expensive choice.
@does
- Ask: how far back do incidents get investigated (usually 7 to 30 days)? What do audits or regulations require (often 90 days to 7 years for security and finance)?
- Keep cheap copies (S3 snapshots, Glacier) for compliance, not hot data.
- Document retention per data stream and implement it with ILM.
- Review quarterly against actual query patterns.
@diagram layers
caption: Retention by value
layers:
  - {label: "Short", nodes: ["Debug logs|3 days|plain"]}
  - {label: "Medium", nodes: ["Application logs|14 to 30 days|info"]}
  - {label: "Long", nodes: ["Audit and security|90 days hot or cold, years in S3|warn"]}
@end
