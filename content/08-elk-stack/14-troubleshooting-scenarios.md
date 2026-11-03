---
title: Ten ELK troubleshooting scenarios
minutes: 60
objectives:
  - Diagnose ten frequent Elasticsearch, Logstash, Filebeat and Kibana failures
  - Use the right API or log to confirm each cause before changing anything
  - Apply a safe fix and a prevention step for each
---
Each scenario follows one pattern: symptom, how to confirm, fix, prevent. Confirm before you change. Most fixes below are safe settings, not deletions.

@concept Scenario 1, no logs in Kibana
@plain
Dashboards are empty, but the application is running.
@problem
The break can be anywhere on the path from pod to index to data view, so guessing wastes time.
@does
- Walk the path: pod writes stdout, Filebeat reads, Logstash or ingest processes, Elasticsearch indexes, Kibana data view matches.
- Check the shipper first: `kubectl logs ds/filebeat` for errors and the harvester count; then `GET _cat/indices/logs-*?v` for document counts rising.
- Check the data view pattern and the time picker (often the cause is a time zone or the wrong range).
- Check that the index has not been blocked as read-only.
@diagram flow
caption: Check each hop
numbered: true
nodes:
  - "Filebeat|logs and registry|app"
  - "Logstash or pipeline|errors|info"
  - "Index|doc count rising?|cp"
  - "Kibana|data view and time|ok"
@h Commands
```bash title="Where do logs stop" lab
kubectl logs -n logging ds/filebeat --tail=50
kubectl exec -n logging elasticsearch-0 -- curl -s -u "$ES_USER:$ES_PASS" "localhost:9200/_cat/indices/logs-*?v&s=index:desc" 
```
@end

@concept Scenario 2, cluster yellow after a node restart
@plain
Status is yellow, with replica shards unassigned for several minutes.
@problem
Replicas cannot be placed, which means no redundancy, but data is still available.
@does
- Confirm with `GET _cluster/allocation/explain`. Typical answers: the node is still rejoining, only one data node exists for a replica, or the disk watermark is hit.
- Delayed allocation waits one minute by default; wait and watch `_cat/recovery`.
- With a single data node, set `number_of_replicas: 0` for those indices, or add a node.
- During planned maintenance set `cluster.routing.allocation.enable: primaries` before and `null` after, to avoid needless shard movement.
@diagram flow
caption: Why replicas stay unassigned
nodes:
  - "Yellow|replicas unassigned|warn"
  - "explain|reason|info"
  - "Wait, add node or lower replicas|fix|app"
  - "Green|ok|ok"
@h Maintenance setting
```text title="Before and after restarts" nocheck
PUT _cluster/settings
{ "persistent": { "cluster.routing.allocation.enable": "primaries" } }

PUT _cluster/settings
{ "persistent": { "cluster.routing.allocation.enable": null } }
```
@end

@concept Scenario 3, disk watermark and read-only indices
@plain
Writes fail with `index read-only / allow delete (api)` or `cluster_block_exception`.
@problem
At the flood-stage watermark (95 percent disk by default) Elasticsearch blocks writes on indices that have a shard on that node.
@does
- Confirm: `GET _cat/allocation?v` for disk percent per node; watermarks are low 85, high 90, flood 95 by default.
- Free space: delete old indices through ILM or manually, expand the volume (PVC expansion on EKS with a supporting storage class), or add data nodes.
- Newer versions remove the block automatically once space is back; on older ones clear it with `index.blocks.read_only_allow_delete: null`.
- Prevent: ILM delete phase, an alert at 75 percent disk, and sizing with growth in mind.
@diagram flow
caption: Watermarks
nodes:
  - "85 percent|low, no new shards|info"
  - "90 percent|high, move shards away|warn"
  - "95 percent|flood, indices read-only|bad"
  - "Free space|block released|ok"
@h Check and clear
```text title="Disk and block" nocheck
GET _cat/allocation?v
PUT logs-*/_settings
{ "index.blocks.read_only_allow_delete": null }
```
@check
What happens at the flood-stage watermark? || Indices with shards on that node become read-only, so writes fail until space is freed.
@end

@concept Scenario 4, mapping conflict and field explosion
@plain
Documents are rejected with `mapper_parsing_exception`, or an index has thousands of fields and Kibana is slow.
@problem
A field arrives as a number in one document and text in another, or an app logs dynamic keys like user IDs as field names.
@does
- Confirm: the bulk response error shows the field and the types; `GET index/_mapping` shows the existing type.
- Fix a conflict: send the correct type, add an ingest pipeline that converts or renames, or put the odd value in a different field. Existing mapping cannot be changed; reindex if needed.
- Field explosion: dynamic keys. Use `flattened` type for free-form objects, set `dynamic: false` or `strict`, and keep `index.mapping.total_fields.limit` (default 1000) as a guard.
- Prevent: templates with explicit mappings and a log schema agreed with developers.
@diagram cmp
caption: Dynamic keys
cards:
  - {h: "Fields per user", kind: bad, items: ["labels.user_123 ...", "Thousands of fields", "Mapping bloat"]}
  - {h: "Flattened object", kind: ok, items: ["One flattened field", "Keys searchable", "Small mapping"]}
@h Mapping
```json title="mapping fragment"
{
  "mappings": {
    "properties": {
      "labels": { "type": "flattened" },
      "latency_ms": { "type": "float" }
    }
  }
}
```
@end

@concept Scenario 5, Logstash pipeline backlog
@plain
Logs arrive in Kibana minutes or hours late. Logstash CPU is high or its queue is full.
@problem
Logstash cannot process events as fast as they arrive, usually due to slow filters, a slow output or too few workers.
@does
- Confirm with the monitoring API: `curl localhost:9600/_node/stats/pipelines` shows events in and out and time per plugin.
- Grok with heavy regex is a common cost; use `dissect`, anchor patterns, or parse JSON logs with the `json` filter.
- Increase `pipeline.workers` (default is the number of CPU cores) and `pipeline.batch.size`; check output bulk latency to Elasticsearch.
- Add a persistent queue or Kafka buffer so spikes do not drop events.
- Scale out: more Logstash pods, or move simple parsing to ingest pipelines in Elasticsearch.
@diagram flow
caption: Find the slow stage
nodes:
  - "Input|events in|app"
  - "Filters|grok cost|warn"
  - "Output|bulk to ES|info"
  - "Queue grows|backlog|bad"
@h Per-plugin timings
```bash title="Logstash API" lab
curl -s localhost:9600/_node/stats/pipelines?pretty | grep -E 'duration_in_millis|events|name'
```
@end

@concept Scenario 6, Filebeat not shipping or duplicating logs
@plain
Pods log but nothing arrives, or every line appears twice.
@problem
Filebeat tracks file offsets in a registry. Wrong paths, permissions, or a lost registry cause gaps or duplicates.
@does
- Confirm paths: on Kubernetes container logs are under `/var/log/containers/*.log` (symlinks into `/var/log/pods`); mount both host paths read-only into the DaemonSet.
- Look for `harvester` and permission errors in Filebeat logs.
- Duplicates: the registry must persist on the host (`hostPath` for `/usr/share/filebeat/data`); without it a pod restart re-reads files. Set a document ID fingerprint if you need idempotent writes.
- Enable autodiscover or the Kubernetes provider to add metadata.
- Use `filebeat test output` to check connectivity and TLS.
@diagram flow
caption: Filebeat checks
nodes:
  - "Paths mounted|containers and pods|app"
  - "Registry persisted|hostPath|cp"
  - "Output test|filebeat test output|info"
  - "Logs flowing|ok|ok"
@h Test commands
```bash title="Inside the Filebeat pod" lab
filebeat test config
filebeat test output
```
@check
Why do duplicates appear after Filebeat pod restarts? || The registry with file offsets was not kept on persistent host storage, so files are read again from the start.
@end

@concept Scenario 7, JVM heap pressure and long garbage collection
@plain
Nodes drop out of the cluster, queries stall and logs show `[gc][young][...] overhead`.
@problem
Heap above about 85 percent triggers constant garbage collection; the node becomes unresponsive and may be removed by the master.
@does
- Confirm: `GET _cat/nodes?v&h=name,heap.percent,cpu` and the GC logs.
- Causes: too many shards, large fielddata, huge aggregations, big bulk requests, undersized heap.
- Fix: reduce shard count (shrink or merge indices), add nodes, set heap to half the RAM but under 31 GB, fix mappings.
- On ECK set resource requests equal to limits and JVM options through the Elasticsearch resource; avoid swap.
- Prevent: alert at 75 percent heap and watch shard count per node.
@diagram flow
caption: Heap pressure cycle
nodes:
  - "Too many shards|heap overhead|warn"
  - "GC thrashing|node pauses|bad"
  - "Node leaves|rebalancing|bad"
  - "Fewer shards|stable|ok"
@h Heap and shard count
```text title="Checks" nocheck
GET _cat/nodes?v&h=name,heap.percent,heap.max,cpu
GET _cluster/stats?filter_path=indices.shards.total
```
@end

@concept Scenario 8, ILM stuck or not rolling over
@plain
An index grows far past its target size, or old indices are never deleted.
@problem
ILM runs in steps; one failed step stops the index until you fix the cause.
@does
- Confirm: `GET logs-*/_ilm/explain` shows the phase, action, step and a failure reason.
- Common causes: the write alias is missing (for non data-stream setups), `index.lifecycle.rollover_alias` not set, a shrink step blocked by too few nodes, or poll interval (default 10 minutes) not yet elapsed.
- Fix the cause then `POST <index>/_ilm/retry`.
- Use data streams, which handle the write alias automatically.
- Prevent: alert on indices with ILM `failed_step`.
@diagram flow
caption: ILM debugging
numbered: true
nodes:
  - "ilm/explain|phase and step|info"
  - "Read failed_step|reason|warn"
  - "Fix cause|alias, nodes, policy|cp"
  - "_ilm/retry|continues|ok"
@h Commands
```text title="ILM" nocheck
GET logs-app-*/_ilm/explain?only_errors=true
POST logs-app-000042/_ilm/retry
```
@end

@concept Scenario 9, slow Kibana dashboards and timeouts
@plain
A dashboard takes a minute to load or shows a timeout.
@problem
Panels run heavy aggregations over wide time ranges and many indices.
@does
- Confirm with the search slow log and Kibana's Inspect view to see the request and the time taken.
- Shorten the default time range, reduce panel count, and replace `terms` on high cardinality fields with `top N` on keyword fields.
- Pre-aggregate: transforms to a summary index for dashboards over months.
- Set a sensible `search.max_buckets` and make sure the data view uses the proper time field.
- Make sure frozen or cold data is not queried by default; scope dashboards to hot data.
@diagram flow
caption: Reduce work per panel
nodes:
  - "Dashboard|20 panels, 90 days|bad"
  - "Inspect|find slow request|info"
  - "Transform|daily summary|cp"
  - "Fast dashboard|ok|ok"
@end

@concept Scenario 10, certificates, TLS and authentication failures
@plain
Kibana cannot reach Elasticsearch, Beats get `x509: certificate signed by unknown authority`, or users see 401 and 403.
@problem
Security is on by default in recent versions, so a wrong CA, expired certificate or role causes access errors that look like outages.
@does
- Check certificate expiry: `openssl s_client -connect es:9200 </dev/null | openssl x509 -noout -dates`.
- On ECK, the operator creates the CA and certs and stores the CA in a secret named `<cluster>-es-http-certs-public`; mount that CA into clients (Filebeat `ssl.certificate_authorities`).
- 401 means bad credentials; 403 means the role lacks a privilege. Use `GET _security/_authenticate` and the role mappings.
- Rotate service account tokens or API keys and update the secrets; expired API keys are a frequent cause after a long time.
- Prevent: alert on certificate expiry and keep API keys in External Secrets.
@diagram seq
caption: TLS trust path
actors: ["Filebeat|client|app", "Elasticsearch|HTTPS 9200|cp", "CA secret|cluster CA|info"]
steps:
  - "0>1: connect | req"
  - "1>0: server certificate | tls"
  - "0>2: verify with CA | req"
  - "2>0: unknown CA | bad"
@h Get the ECK CA
```bash title="Read the CA from the secret" lab
kubectl get secret quickstart-es-http-certs-public -n logging -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt
openssl x509 -in ca.crt -noout -dates
```
@check
What is the difference between 401 and 403? || 401 means authentication failed; 403 means the user is known but lacks the privilege.
@end
