---
title: Thanos and Mimir deployment guide
minutes: 55
objectives:
  - Explain why a single Prometheus stops being enough
  - Deploy Thanos with a sidecar and object storage for long retention
  - Compare Thanos and Mimir and choose for your platform
---
One Prometheus per cluster is simple and reliable. The trouble starts with many clusters, long retention and a need for one global query.

@concept Limits of a single Prometheus
@plain
Prometheus stores data on local disk in one instance. It has no built-in clustering, global view or cheap long-term storage.
@problem
Several clusters mean several Prometheus servers and no single place to ask a question. Keeping a year on local SSD is expensive, and losing the disk loses the history.
@does
- Storage cost: 2 million active series scraped every 30 s is 2 000 000 ÷ 30 ≈ 66 667 samples per second. For 15 days (1 296 000 s) that is about 86.4 billion samples; at roughly 1.5 to 2 bytes each this is about 130 to 173 GB.
- Add headroom: 173 GB × 1.25 ≈ 216 GB of disk for the larger estimate.
- High availability today means two identical replicas, with duplicates to be merged on read.
- Solutions: Thanos, Grafana Mimir, Cortex, VictoriaMetrics, or a managed service such as Amazon Managed Service for Prometheus.
@diagram cmp
caption: Single instance versus a scalable setup
cards:
  - {h: "One Prometheus", kind: warn, items: ["Local disk only", "No global view", "Two replicas for HA, duplicates"]}
  - {h: "Thanos or Mimir", kind: ok, items: ["Object storage", "Global query", "Long retention, deduplicated"]}
@check
Samples per second for 1 million series scraped every 15 s? || 1 000 000 ÷ 15 ≈ 66 667.
@end

@concept Thanos components
@plain
Thanos adds components around existing Prometheus servers. It does not replace them.
@problem
You want to keep your Prometheus and add global queries and cheap history step by step.
@does
- **Sidecar**: runs beside Prometheus, uploads each finished 2-hour block to object storage and serves recent data to the Query component.
- **Store Gateway**: serves historical blocks from object storage.
- **Query**: fans out PromQL to sidecars and store gateways, merges and deduplicates replicas by external labels.
- **Compactor**: merges blocks and creates downsampled (5 minute and 1 hour) versions; must run as a single instance per bucket.
- **Ruler** and **Query Frontend** are optional for rules and caching. Receive is an alternative ingest path using remote write.
@diagram flow
caption: Thanos read path
nodes:
  - "Prometheus + sidecar|recent data|app"
  - "Thanos Query|global PromQL|cp"
  - "Store Gateway|history from S3|info"
  - "Grafana|one data source|ok"
@end

@concept Deploying Thanos on Kubernetes
@plain
Use the kube-prometheus-stack to run Prometheus with a Thanos sidecar and an object storage secret.
@problem
Wiring the sidecar, bucket credentials and unique external labels by hand is easy to get wrong.
@does
- Every Prometheus gets unique `externalLabels` such as `cluster` and `replica`. Without them deduplication and uploads clash.
- The sidecar reads an `objstore.yml` secret describing the bucket. On AWS use an IRSA role instead of keys.
- Disable local compaction by setting equal min and max block durations only when the Thanos docs require it for sidecar mode; check the current docs.
- Keep local retention short (for example 2 days) since history is in S3.
@diagram flow
caption: What gets configured
numbered: true
nodes:
  - "Bucket and role|S3 and IRSA|cp"
  - "objstore secret|bucket config|info"
  - "Prometheus values|thanos sidecar|app"
  - "Thanos Query|add store endpoints|ok"
@h Object storage config and Prometheus values
```yaml title="objstore.yml"
type: S3
config:
  bucket: acme-thanos-metrics
  endpoint: s3.eu-west-1.amazonaws.com
  region: eu-west-1
```
```yaml title="kube-prometheus-stack values (fragment)"
prometheus:
  prometheusSpec:
    replicas: 2
    retention: 2d
    externalLabels:
      cluster: prod-eks-1
    thanos:
      objectStorageConfig:
        existingSecret:
          name: thanos-objstore
          key: objstore.yml
```
:::note
Field names in the chart change between versions. Verify them against the chart you install.
:::
@end

@concept Downsampling and retention
@plain
Thanos keeps raw data for recent periods and coarser summaries for old periods.
@problem
Queries over a year of raw 30 second data are slow and load far more bytes than a graph needs.
@does
- Compactor creates 5 minute resolution after 40 hours and 1 hour resolution after 10 days.
- Retention is set per resolution: for example raw 30 days, 5m 180 days, 1h 2 years.
- The query frontend or querier picks the resolution automatically with `max_source_resolution` auto behaviour.
- Downsampling does not reduce storage by itself; it speeds up long-range queries. It stores extra blocks.
@diagram layers
caption: Resolutions over time
layers:
  - {label: "Raw", nodes: ["30 s samples|30 days|ok"]}
  - {label: "5 minutes", nodes: ["Downsampled|180 days|info"]}
  - {label: "1 hour", nodes: ["Downsampled|2 years|info"]}
@h Compactor flags
```bash title="compactor retention" nocheck
thanos compact \
  --objstore.config-file=/etc/thanos/objstore.yml \
  --retention.resolution-raw=30d \
  --retention.resolution-5m=180d \
  --retention.resolution-1h=730d \
  --wait
```
@end

@concept Grafana Mimir
@plain
Mimir is a horizontally scalable, multi-tenant metrics backend. Prometheus servers send data to it with remote write, and Grafana queries it as a Prometheus data source.
@problem
Sidecars tie you to long-lived Prometheus servers. For many tenants and very large series counts, a central, scalable store is easier to run.
@does
- Components: distributor, ingester, querier, query-frontend, store-gateway, compactor, ruler, alertmanager.
- Ingest by remote write; each tenant is identified by the `X-Scope-OrgID` header.
- Blocks live in object storage; ingesters keep recent data in memory with a write-ahead log, with replication factor 3 by default.
- Sizing arithmetic: 1 million series with replication 3 means ingesters hold 3 million series in memory in total.
- Deployment is by the `mimir-distributed` Helm chart; check the current docs for modes and chart values.
@diagram flow
caption: Remote write into Mimir
nodes:
  - "Prometheus or Agent|remote write|app"
  - "Distributor|hash by series|cp"
  - "Ingesters x3|replicated|info"
  - "Object storage|blocks|ok"
@h Prometheus remote write
```yaml title="prometheus remote_write"
remote_write:
  - url: http://mimir-gateway.mimir.svc/api/v1/push
    headers:
      X-Scope-OrgID: team-shop
    queue_config:
      max_samples_per_send: 2000
```
@check
Why does replication 3 triple ingester memory demand? || Each series is written to three ingesters, so three copies are held.
@end

@concept Thanos or Mimir
@plain
Both give global queries and long retention. They differ in how data gets to object storage and how much you operate.
@problem
Choosing wrongly means migrating metrics history later.
@does
- Thanos: incremental, keeps Prometheus as the main store, sidecar upload, fewer moving parts to start. Good for a handful of clusters.
- Mimir: central scalable store, strong multi-tenancy, higher operating complexity, uses remote write. Good for many clusters or tenants.
- Both need object storage lifecycle rules, caching (memcached) at scale and good label hygiene.
- Managed options (Amazon Managed Prometheus, Grafana Cloud) remove operations; compare cost per series.
@diagram cmp
caption: Trade-offs
cards:
  - {h: "Thanos", kind: ok, items: ["Sidecar on existing Prometheus", "Incremental adoption", "Fewer tenants"]}
  - {h: "Mimir", kind: info, items: ["Central scalable store", "Multi-tenant by design", "More to operate"]}
  - {h: "Managed service", kind: ok, items: ["No operations", "Pay per series or sample", "Vendor limits"]}
@choose Which to start with
Thanos sidecar | Few clusters, existing Prometheus, want low change | Hundreds of tenants with isolation needs
Mimir | Many clusters or tenants, central platform team | Small setup with no one to operate it
Managed service | Little operations capacity | Strict data location rules
@end

@concept Operating the long-term store
@plain
Once metrics live in S3, the main risks are query cost, compaction health and cardinality.
@problem
A single heavy query over a year can time out or cost real money in S3 requests.
@does
- Alert on compactor halted, blocks not uploading (sidecar upload failures) and store gateway load errors.
- Cache index and chunks with memcached and use the query frontend to split and cache long queries.
- Keep an S3 lifecycle policy for incomplete multipart uploads.
- Fix cardinality at the source; it multiplies every cost above. Use recording rules for dashboards that look at long ranges.
@diagram flow
caption: Health signals
nodes:
  - "Upload|sidecar to S3|app"
  - "Compaction|single compactor|cp"
  - "Query cache|frontend and memcached|info"
  - "Alerts|on each stage|warn"
@h Example alert
```yaml title="thanos alert"
groups:
  - name: thanos
    rules:
      - alert: ThanosCompactHalted
        expr: thanos_compact_halted == 1
        for: 5m
        labels:
          severity: page
        annotations:
          summary: Thanos compactor has halted
```
@end
