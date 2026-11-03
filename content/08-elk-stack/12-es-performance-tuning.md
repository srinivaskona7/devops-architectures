---
title: Elasticsearch performance tuning and recovery
minutes: 60
objectives:
  - Find and fix hot shards and uneven load
  - Understand circuit breakers and heap pressure
  - Recover a red or yellow cluster step by step
---
Most Elasticsearch trouble comes from a few causes: too many shards, uneven shards, heap pressure and slow disks. This section shows how to see each one and what to do.

@concept Reading cluster health and allocation
@plain
Cluster health is green (all shards assigned), yellow (primaries assigned, some replicas not) or red (some primary shard is not assigned, so data is unavailable).
@problem
A yellow or red status tells you something is wrong but not what. The allocation explain API tells you why.
@does
- `GET _cluster/health` shows status and counts of unassigned shards.
- `GET _cat/shards?v&h=index,shard,prirep,state,unassigned.reason` lists problem shards.
- `GET _cluster/allocation/explain` explains why a shard is not assigned: disk watermark, no matching node, allocation filter, too many shards per node, or a failed allocation count.
- Always start here before changing settings.
@diagram flow
caption: From symptom to reason
nodes:
  - "Health yellow or red|status|warn"
  - "_cat/shards|find unassigned|info"
  - "allocation/explain|says why|cp"
  - "Targeted fix|ok|ok"
@h Requests
```text title="Kibana Dev Tools" nocheck
GET _cluster/health
GET _cat/shards?v&h=index,shard,prirep,state,unassigned.reason&s=state
GET _cluster/allocation/explain
```
@check
What does red mean? || At least one primary shard is unassigned, so some data cannot be read or written.
@end

@concept Hot shards and uneven load
@plain
A **hot node** does more work than its peers, usually because it holds more shards of busy indices or because the busiest data stream writes to few shards.
@problem
One node at 95 percent CPU while the others idle makes indexing slow and queries time out, even though total capacity is plentiful.
@does
- Check `GET _cat/nodes?v&h=name,cpu,heap.percent,load_1m,disk.used_percent` and `GET _cat/allocation?v` for imbalance.
- Cause 1: a write index with 1 primary shard receives all writes on one node. Use more primaries (sized for the write rate) or more rollover shards.
- Cause 2: routing or a custom `_routing` value sends most documents to one shard.
- Cause 3: a few nodes hold the big, frequently searched indices. Use shard allocation awareness and `index.routing.allocation.total_shards_per_node` to spread them.
- Note: replicas also do searches, so more replicas spread read load, not write load.
@diagram cmp
caption: Even versus hot
cards:
  - {h: "Hot shards", kind: bad, items: ["1 primary for the write index", "One node saturated", "Others idle"]}
  - {h: "Spread load", kind: ok, items: ["Primaries match write rate", "total_shards_per_node limit", "Even CPU and heap"]}
@h Spread shards of one index
```text title="Index setting" nocheck
PUT logs-app-000042/_settings
{
  "index.routing.allocation.total_shards_per_node": 2
}
```
@end

@concept Shard sizing and count arithmetic
@plain
Each shard is a Lucene index with memory and file overhead. Too many small shards waste heap; a few huge shards recover and move slowly.
@problem
Oversharding is the most common cause of unstable clusters: thousands of tiny shards and a heap full of overhead.
@does
- Target shard size: roughly 10 to 50 GB for most time series use; check the current Elastic sizing guidance.
- Rule of thumb: keep the shard count per node within about 20 shards per GB of heap, so a 30 GB heap suits up to about 600 shards.
- Example: 120 GB a day, 30 GB target, gives 4 primary shards a day; 30 days gives 120 primaries, or 240 shards with one replica.
- Daily indices of 1 GB each with 5 shards waste the budget; use ILM rollover by size (for example `max_primary_shard_size: 30gb`) rather than by day.
@diagram flow
caption: Shard budget
nodes:
  - "Data per day|120 GB|info"
  - "Target shard size|30 GB|app"
  - "Primaries per day|4|cp"
  - "30 days with 1 replica|240 shards|warn"
@check
How many shards for 30 days if each day has 4 primaries and 1 replica? || 4 × 30 = 120 primaries, doubled by replicas is 240 shards.
@end

@concept Circuit breakers and heap pressure
@plain
Circuit breakers stop a request that would use too much memory, returning an error instead of letting the node run out of heap.
@problem
Without breakers one heavy aggregation could trigger an OutOfMemoryError and take the node down, causing shard movement for everyone.
@does
- Breakers: parent (total), request, fielddata, in-flight requests and accounting. The parent defaults to about 95 percent of heap with real memory tracking (check current defaults for your version).
- Symptom: `circuit_breaking_exception ... Data too large`. See `GET _nodes/stats/breaker`.
- Heap should be at most half of RAM and under about 31 GB so compressed object pointers stay enabled.
- Causes: huge aggregations over high cardinality fields, large `size` values, bulk requests too big, fielddata on text fields.
- Fixes: reduce request size, use `composite` aggregation paging, add nodes, fix mappings (use keyword plus doc values instead of fielddata).
@diagram flow
caption: Request meets breaker
nodes:
  - "Heavy aggregation|many buckets|warn"
  - "Breaker estimates memory|request or parent|cp"
  - "Rejected|circuit_breaking_exception|bad"
  - "Node stays alive|ok|ok"
@h Check breaker state
```text title="Breakers and JVM" nocheck
GET _nodes/stats/breaker?filter_path=nodes.*.breakers
GET _cat/nodes?v&h=name,heap.percent,heap.max,ram.percent
```
@check
Why keep heap under about 31 GB? || Above that the JVM stops using compressed object pointers, so more heap can hold fewer objects.
@end

@concept Thread pools and rejected requests
@plain
Elasticsearch handles work in thread pools with bounded queues. When a queue is full the request is rejected with HTTP 429.
@problem
A 429 on bulk indexing or searches means the node is saturated. Retrying immediately makes it worse.
@does
- `GET _cat/thread_pool/write,search?v&h=node_name,name,active,queue,rejected` shows pressure.
- Write rejections: reduce bulk concurrency, increase bulk size moderately (5 to 15 MB per request is common), or add data nodes.
- Search rejections: expensive queries, too many concurrent users, or slow disks.
- Clients must back off exponentially on 429; Filebeat and Logstash do this automatically.
- Do not just raise queue sizes; it hides the problem and uses more heap.
@diagram flow
caption: Back-pressure path
nodes:
  - "Shipper|bulk requests|app"
  - "Write queue full|node saturated|warn"
  - "429 rejected|client retries with backoff|bad"
  - "Fix|more nodes or smaller load|ok"
@end

@concept Indexing performance
@plain
Indexing speed depends on bulk size, refresh interval, replicas during load, mappings and storage speed.
@problem
Ingest cannot keep up, and lag grows in Kafka or Filebeat.
@does
- Use the bulk API with several parallel workers.
- `refresh_interval` of 30s or more instead of 1s for log data reduces segment churn.
- For a large initial load set `number_of_replicas: 0`, then restore it after.
- Disable dynamic mapping explosion: use explicit templates, set `index.mapping.total_fields.limit` sensibly and `dynamic: strict` or `runtime` where suitable.
- Use SSD or NVMe on hot nodes, and keep the translog on the same fast disk.
@diagram layers
caption: Where indexing time goes
layers:
  - {label: "Client", nodes: ["Bulk size and workers|5 to 15 MB|app"]}
  - {label: "Index settings", nodes: ["refresh_interval|30s|cp", "replicas|0 during bulk load|cp"]}
  - {label: "Hardware", nodes: ["NVMe disks|fast segments|ok", "CPU|analysis and merge|ok"]}
@h Template with tuned settings
```json title="index template body"
{
  "index_patterns": ["logs-app-*"],
  "template": {
    "settings": {
      "number_of_shards": 2,
      "number_of_replicas": 1,
      "refresh_interval": "30s"
    }
  }
}
```
@end

@concept Search performance
@plain
Slow searches come from scanning too much data, heavy aggregations, wildcard queries and cold caches.
@problem
A dashboard that takes 40 seconds to load makes the cluster look broken even though the cause is one expression.
@does
- Use filters (`filter` context) for exact conditions and time ranges; they are cached and do not score.
- Avoid leading wildcards and regexes on large text fields. Use `keyword` mappings and `match` queries.
- Limit the indices touched: the time range on a data stream selects only the needed backing indices.
- Use the slow log: `index.search.slowlog.threshold.query.warn: 5s` to find the offenders.
- Pre-aggregate with transforms or rollups for dashboards that scan months.
- `force merge` only on read-only indices that will not be written again.
@diagram cmp
caption: Query styles
cards:
  - {h: "Slow", kind: bad, items: ["Leading wildcard", "Huge terms aggregation", "All indices"]}
  - {h: "Fast", kind: ok, items: ["Filter by time and keyword", "Composite paging", "Only needed indices"]}
@h Slow log setting
```text title="Enable search slowlog" nocheck
PUT logs-app-*/_settings
{
  "index.search.slowlog.threshold.query.warn": "5s",
  "index.search.slowlog.threshold.fetch.warn": "1s"
}
```
@end

@concept Recovering a red cluster
@plain
Recovery means finding why primaries are unassigned and fixing that cause, in a safe order.
@problem
Panic actions such as deleting indices or forcing allocation can destroy the only copy of data.
@does
- Step 1: `GET _cluster/allocation/explain` for a red primary. Common reasons below.
- Node left or crashed: restart it; shards recover from local disk. Wait for the delayed allocation timer (default 1 minute) and recovery to finish.
- Disk watermark: free disk or add nodes. Flood stage (95 percent) makes indices read-only; after freeing space clear the block (newer versions release it automatically; check current behaviour).
- Allocation filter or wrong node attributes: fix the setting.
- Corrupt or missing primary with no copy: restore from a snapshot. Only as a last resort use `_cluster/reroute` with `allocate_stale_primary` or `allocate_empty_primary`, accepting data loss.
- Always keep regular snapshots to S3 (SLM) so this path exists.
@diagram flow
caption: Red cluster recovery order
numbered: true
nodes:
  - "Explain|why unassigned|info"
  - "Fix cause|node, disk, settings|cp"
  - "Wait for recovery|watch _cat/recovery|app"
  - "Snapshot restore|if copy lost|warn"
@h Commands
```text title="Recovery checks" nocheck
GET _cat/recovery?v&active_only=true
GET _cluster/settings?include_defaults=false
PUT _snapshot/s3_repo/_restore
{ "indices": "logs-app-000041", "include_global_state": false }
```
:::danger
`allocate_stale_primary` and `allocate_empty_primary` can lose data. Use them only when no good copy exists and with the owner's agreement.
:::
@check
What should you try before forcing a primary allocation? || Restart the lost node, fix the disk or allocation setting, or restore the index from a snapshot.
@end
