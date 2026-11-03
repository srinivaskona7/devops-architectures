---
title: Data streams, ILM, tiers and snapshots
minutes: 55
objectives:
  - Use data streams with rollover for append-only logs
  - Write an ILM policy with hot, warm, cold and delete phases
  - Back up with snapshots to S3 and restore them
---
Logs arrive forever and become less valuable with age. Lifecycle management moves data to cheaper storage and finally deletes it, automatically.

@concept Data streams
@plain
A **data stream** is a single name you write to and search, backed by hidden time-ordered indices. New documents always go to the newest backing index.
@problem
Hand-managing daily indices and aliases is error-prone, and old indices need to be handled one by one.
@does
- Works for append-only data with an `@timestamp` field; documents cannot be updated in place through the stream.
- Needs an index template with `data_stream: {}`.
- Naming convention: `logs-<dataset>-<namespace>`, such as `logs-checkout-prod`. Beats and Elastic Agent use this.
- Backing indices are named like `.ds-logs-checkout-prod-2026.10.31-000001`.
@diagram flow
caption: One name, many backing indices
nodes:
  - "Writers|logs-checkout-prod|app"
  - "Data stream|search and write name|cp"
  - "Backing index 000002|current write index|ok"
  - "Backing index 000001|older, read only|info"
@h Create and use
```text title="Dev Tools" nocheck
PUT _index_template/logs-checkout
{ "index_patterns": ["logs-checkout-*"], "data_stream": {}, "priority": 300,
  "template": { "settings": { "index.lifecycle.name": "logs-30d" } } }

POST logs-checkout-prod/_doc
{ "@timestamp": "2026-10-31T12:00:00Z", "message": "hello" }

GET _data_stream/logs-checkout-prod
```
@end

@concept Index Lifecycle Management
@plain
ILM is a policy that moves an index through **phases** (hot, warm, cold, frozen, delete) using conditions on age and size, and runs actions at each step.
@problem
Without lifecycle rules, storage grows until the cluster is full, and queries slow down over ever bigger data.
@does
- **Hot**: actively written. Action `rollover` creates a new backing index when it reaches a size, document count or age.
- **Warm**: no longer written but still searched; shrink, force-merge, move to cheaper nodes.
- **Cold / frozen**: rarely searched; may use searchable snapshots.
- **Delete**: remove the index.
- `min_age` counts from rollover, not from creation.
@diagram flow
caption: Phases of the lifecycle
nodes:
  - "Hot|write and search, rollover|bad"
  - "Warm|search, force merge|warn"
  - "Cold|rare search, cheaper disks|info"
  - "Delete|remove data|plain"
@end

@concept Writing an ILM policy
@plain
A policy is JSON listing phases, when each starts (`min_age`), and the actions to perform.
@problem
You need a repeatable retention rule, reviewed in Git, matching a business requirement such as "30 days searchable".
@does
- Rollover at `50gb` primary shard size or `1d`, whichever comes first, keeps shards in the target size range.
- Warm phase after 2 days; set replicas or force-merge to 1 segment to save space.
- Delete after 30 days.
- Attach with `index.lifecycle.name` in the index template.
@diagram cmp
caption: A 30 day policy
cards:
  - {h: "Day 0 to 2", kind: bad, items: ["Hot nodes", "Rollover at 50 GB or 1 day"]}
  - {h: "Day 2 to 30", kind: warn, items: ["Warm nodes", "Force merge, read only"]}
  - {h: "Day 30", kind: info, items: ["Delete", "Snapshot kept in S3"]}
@h Policy
```json
{
  "policy": {
    "phases": {
      "hot": {
        "actions": {
          "rollover": { "max_primary_shard_size": "50gb", "max_age": "1d" },
          "set_priority": { "priority": 100 }
        }
      },
      "warm": {
        "min_age": "2d",
        "actions": {
          "forcemerge": { "max_num_segments": 1 },
          "set_priority": { "priority": 50 }
        }
      },
      "delete": {
        "min_age": "30d",
        "actions": { "delete": {} }
      }
    }
  }
}
```
:::note
Send this with `PUT _ilm/policy/logs-30d`. On Elastic Cloud or Kubernetes with ECK, tier migration is automatic through node roles.
:::
@end

@concept Data tiers
@plain
Nodes can have **roles**: `data_hot`, `data_warm`, `data_cold`, `data_frozen`. ILM moves indices between tiers by changing their allocation.
@problem
Fast NVMe disks for everything is expensive, yet old data rarely needs that speed.
@does
- Hot: newest data, fast disks, most CPU. Warm: larger, cheaper disks (gp3 on AWS). Cold: even cheaper, or searchable snapshots with a local cache. Frozen: data kept only in object storage (S3) and cached on demand.
- Example ratios (disk to RAM): hot about 1:30, warm 1:80 and up; check Elastic's sizing guidance for your version.
- Content tier holds non-time-series data.
@diagram layers
caption: Tiers from fast to cheap
layers:
  - {label: "Hot", nodes: ["NVMe or gp3 high IOPS|recent, writes|bad"]}
  - {label: "Warm", nodes: ["gp3 larger disks|weeks, searches|warn"]}
  - {label: "Cold and frozen", nodes: ["S3 searchable snapshots|months or years|info"]}
@end

@concept Rollover and shrink in practice
@plain
Rollover starts a new write index; shrink reduces the number of primary shards of an old index; force merge reduces segments.
@problem
Even with good planning, quiet indices end up with too many tiny shards.
@does
- Rollover conditions are evaluated periodically (default every 10 minutes), so indices may slightly pass the limit.
- Shrink needs all shards on one node and a target shard count that is a factor of the original.
- Force merge is heavy; run it only on indices no longer written.
- Check ILM progress with `GET <index>/_ilm/explain`.
@diagram flow
caption: Tidying an aging index
nodes:
  - "Rolled over|no more writes|info"
  - "Shrink|fewer primaries|warn"
  - "Force merge|one segment per shard|app"
  - "Smaller, faster to search|ok|ok"
@h Check ILM
```bash title="Explain lifecycle state" lab
curl -s -u elastic:$ES_PASSWORD "$ES_URL/logs-checkout-prod/_ilm/explain?human" | head -c 600
curl -s -u elastic:$ES_PASSWORD "$ES_URL/_cat/indices/.ds-logs-*?v&s=index"
```
@end

@concept Snapshots and repositories
@plain
A **snapshot** is a backup of indices stored in a **repository**: S3, GCS, Azure Blob or a shared file system. Snapshots are incremental: only new segments are copied.
@problem
Replicas protect against node loss but not against deleting an index, a bad upgrade or losing the whole cluster.
@does
- On AWS use the S3 repository with an IAM role (IRSA on EKS) and a bucket with versioning off and lifecycle rules for old snapshots.
- Snapshot Lifecycle Management (SLM) schedules and expires snapshots.
- Restore selected indices, even into another cluster.
- Never copy data directories as a backup.
@diagram flow
caption: Backup path to S3
nodes:
  - "Elasticsearch cluster|data nodes|cp"
  - "Snapshot repository|S3 bucket|ext"
  - "SLM policy|nightly, keep 14|warn"
  - "Restore|selected indices|ok"
@h SLM policy and repository
```json
{
  "schedule": "0 30 1 * * ?",
  "name": "<nightly-{now/d}>",
  "repository": "s3-backups",
  "config": { "indices": ["logs-*"], "include_global_state": false },
  "retention": { "expire_after": "14d", "min_count": 5, "max_count": 30 }
}
```
```text title="Register the repository" nocheck
PUT _snapshot/s3-backups
{ "type": "s3", "settings": { "bucket": "my-es-snapshots", "base_path": "prod" } }
PUT _slm/policy/nightly
POST _snapshot/s3-backups/_verify
```
@end

@concept Searchable snapshots
@plain
A searchable snapshot lets you search an index whose data lives only in the snapshot repository (S3). Elasticsearch caches the parts it needs locally.
@problem
Keeping 90 days of logs on replicated SSD costs several times more than S3.
@does
- Cold phase: `searchable_snapshot` with a fully mounted index (full local copy, no replica needed because S3 is the copy).
- Frozen phase: partially mounted, small local cache, slower first queries.
- Requires an appropriate Elastic licence level; check current licensing.
- Arithmetic: 220 GB/day for 90 days is 19 800 GB. With 1 replica on SSD that is 39 600 GB of disk; as a snapshot in S3 it is 19 800 GB of object storage.
@diagram cmp
caption: Replicas on SSD or snapshot in S3
cards:
  - {h: "Regular warm", kind: warn, items: ["Primary and replica on disk", "2 copies of 19.8 TB", "Fast queries"]}
  - {h: "Searchable snapshot", kind: ok, items: ["One copy in S3", "Local cache only", "Slower cold queries"]}
@end
