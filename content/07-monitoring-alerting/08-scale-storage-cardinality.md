---
title: Scale, long-term storage and cardinality
minutes: 55
objectives:
  - Understand TSDB storage and size it with arithmetic
  - Pick between federation, remote write, Thanos, Mimir and VictoriaMetrics
  - Find and control high cardinality
---
One Prometheus is simple and fast. This section covers what to do when you need more history, more clusters or lower cost.

@concept How the TSDB stores data
@plain
Prometheus writes new samples to memory and a write-ahead log (WAL), then every two hours compacts them into immutable blocks on disk. Old blocks are deleted when they exceed retention.
@problem
You need fast writes and compact storage without an external database.
@does
- Samples cost about 1 to 2 bytes each after compression.
- Default retention is 15 days; set `--storage.tsdb.retention.time` and `--storage.tsdb.retention.size`.
- Memory is dominated by the number of active series (several KB per series).
- Local storage is not replicated; for durability use remote write or Thanos.
@diagram flow
caption: Life of a sample
nodes:
  - "Scrape|new sample|app"
  - "Head and WAL|memory plus log|warn"
  - "2h block|compacted on disk|info"
  - "Retention|old blocks deleted|bad"
@end

@concept Sizing storage
@plain
Disk needed = samples per second × bytes per sample × retention seconds.
@problem
Guessing disk size leads to full disks or waste.
@does
- Samples per second = active series ÷ scrape interval.
- Worked example: 100 000 series scraped every 15 s gives 100 000 ÷ 15 = 6 667 samples per second.
- One day is 6 667 × 86 400 = 576 000 000 samples. For 15 days that is 8.64 billion samples.
- At 1.5 bytes per sample this is 12.96 GB; at 2 bytes it is 17.28 GB. Add 20 to 30 percent headroom for the WAL and compaction.
- So plan roughly 20 GB for 100 000 series at 15 s for 15 days.
@diagram flow
caption: Sizing arithmetic
numbered: true
nodes:
  - "100000 series|active in head|plain"
  - "divide by 15 s|6667 samples per second|info"
  - "times 86400 times 15|8.64 billion samples|warn"
  - "times 1.5 to 2 bytes|13 to 17 GB|ok"
@h Check your own server
```promql title="Measure rather than guess" nocheck
prometheus_tsdb_head_series
rate(prometheus_tsdb_head_samples_appended_total[5m])
rate(prometheus_tsdb_compaction_chunk_size_bytes_sum[6h]) / rate(prometheus_tsdb_compaction_chunk_samples_sum[6h])
```
@check
Series doubles to 200 000 at the same interval. What happens to disk? || It doubles, since samples per second doubles.
@end

@concept Cardinality
@plain
**Cardinality** is the number of distinct series. Every unique combination of label values is a new series.
@problem
A label such as `user_id` or `request_path` with unbounded values creates millions of series, exhausting memory and crashing Prometheus.
@does
- Series count = product of label value counts. 5 services × 200 pods × 10 endpoints × 8 status codes × 12 buckets = 960 000 series from one histogram.
- Avoid IDs, emails, full URLs, timestamps in labels.
- Find offenders with the TSDB status page or `topk(10, count by (__name__)({__name__=~".+"}))`.
- Set `sample_limit` and `label_limit` per job to protect the server.
@diagram flow
caption: A label explosion
nodes:
  - "Metric|requests_total|plain"
  - "Add user_id label|1 million users|bad"
  - "1 million series|memory and query cost explode|bad"
@h Guard rails
```yaml title="Per-job limits"
scrape_configs:
  - job_name: apps
    sample_limit: 50000
    label_limit: 30
    label_value_length_limit: 200
    kubernetes_sd_configs:
      - role: pod
```
```bash title="Find the heavy hitters" lab
curl -s localhost:9090/api/v1/status/tsdb | head -c 800
promtool tsdb analyze /prometheus | head -40
```
@end

@concept Federation
@plain
A federation setup has a global Prometheus that scrapes the `/federate` endpoint of other Prometheus servers to pull selected series.
@problem
You want one place showing key numbers from several clusters.
@does
- Use `match[]` selectors to pull only aggregated recording rules, never everything.
- Works for a small number of clusters and summaries.
- Limits: no deduplication, scrape gaps, load grows with series, no long-term storage.
@diagram flow
caption: Hierarchical federation
nodes:
  - "Cluster A Prometheus|local detail|cp"
  - "Cluster B Prometheus|local detail|cp"
  - "Global Prometheus|selected aggregates only|info"
@h Example
```yaml title="Global Prometheus scrape of /federate"
scrape_configs:
  - job_name: federate
    honor_labels: true
    metrics_path: /federate
    params:
      "match[]":
        - '{__name__=~"service:.*"}'
    static_configs:
      - targets: ["prom-a.example.com:9090", "prom-b.example.com:9090"]
```
@end

@concept Remote write
@plain
`remote_write` streams every sample (or a filtered subset) to a remote backend over HTTP as soon as it is scraped.
@problem
Local disk is limited and single-server; you want durable, queryable storage across clusters.
@does
- Targets include Mimir, Cortex, Thanos Receive, VictoriaMetrics, Grafana Cloud, Amazon Managed Service for Prometheus.
- Uses a WAL-backed queue; tune `queue_config` for throughput.
- `write_relabel_configs` drop series you do not want to pay for.
- Monitor `prometheus_remote_storage_samples_pending` and failed totals.
@diagram flow
caption: Sending data out
nodes:
  - "Prometheus per cluster|scrape and rules|cp"
  - "remote_write|HTTP protobuf|info"
  - "Central store|Mimir, VictoriaMetrics, AMP|ext"
  - "Grafana|queries central store|app"
@h Example
```yaml title="remote_write to a central store"
remote_write:
  - url: https://metrics.example.com/api/v1/push
    basic_auth:
      username: tenant-a
      password_file: /etc/prometheus/secrets/pw
    write_relabel_configs:
      - source_labels: [__name__]
        regex: "go_.*|process_.*"
        action: drop
    queue_config:
      max_samples_per_send: 2000
      capacity: 10000
```
@end

@concept Thanos
@plain
Thanos adds global query and cheap long retention on top of existing Prometheus servers by shipping their blocks to object storage such as S3.
@problem
You want unlimited history, one query across clusters, and HA Prometheus pairs without duplicate data.
@does
- **Sidecar** next to Prometheus uploads 2-hour blocks to S3 and serves recent data.
- **Store Gateway** serves old blocks from S3. **Querier** fans out queries and deduplicates replicas using the `replica` label.
- **Compactor** merges and **downsamples** blocks (5-minute and 1-hour resolutions).
- **Ruler** evaluates rules globally. Alternative ingestion path: **Receive** for remote write.
@diagram layers
caption: Thanos components
layers:
  - {label: "Query", nodes: ["Querier|global PromQL, dedup|app", "Query Frontend|split and cache|info"]}
  - {label: "Data", nodes: ["Sidecar|next to Prometheus|env", "Store Gateway|reads S3 blocks|env", "Receive|remote write ingest|env"]}
  - {label: "Storage", nodes: ["S3 bucket|blocks, long retention|ext", "Compactor|merge and downsample|ok"]}
@end

@concept Mimir and VictoriaMetrics
@plain
**Grafana Mimir** (successor of Cortex) is a horizontally scalable, multi-tenant, remote-write backend with object storage. **VictoriaMetrics** is a PromQL-compatible (MetricsQL) database, available as a single binary or a cluster, known for low resource use.
@problem
Millions to billions of series do not fit one Prometheus, and building HA yourself is hard.
@does
- Both accept remote write and serve PromQL-style queries to Grafana.
- Mimir splits into distributors, ingesters, store-gateways, queriers and compactors, and enforces per-tenant limits.
- VictoriaMetrics single node handles large loads with simple operation; `vmagent` can replace Prometheus scraping.
- Managed options: Amazon Managed Service for Prometheus, Grafana Cloud.
@diagram cmp
caption: Choosing a long-term backend
cards:
  - {h: "Thanos", kind: info, items: ["Keeps Prometheus as is", "Object storage blocks", "Good for few clusters"]}
  - {h: "Mimir", kind: app, items: ["Multi-tenant", "Remote write native", "Larger operations burden"]}
  - {h: "VictoriaMetrics", kind: ok, items: ["Very efficient", "Simple single binary", "MetricsQL extensions"]}
  - {h: "Managed (AMP)", kind: warn, items: ["No servers to run", "Pay per sample and query"]}
@choose Pick a backend
Plain Prometheus | one cluster, 15-30 days is enough | you need global view or years of data
Thanos | existing Prometheus, S3 available | you want one remote-write ingestion path
Mimir or VictoriaMetrics | many clusters, central platform team | team is tiny and load is small
Managed service | you want zero operations | cost per sample is a concern
@end

@concept CloudWatch versus Prometheus
@plain
CloudWatch is AWS's built-in metric and alarm service. Prometheus is open-source, label-based and runs anywhere. They are not exclusive.
@problem
Teams on AWS ask whether to use only the managed service or run their own.
@does
- CloudWatch: automatic for AWS services, no servers, alarms and dashboards built in; custom metrics and high-resolution metrics cost money, dimensions are limited and queries are less expressive.
- Prometheus: rich PromQL, label model, Kubernetes native, portable across clouds; you operate storage and HA (or buy a managed service).
- Common pattern: CloudWatch for AWS-managed resources (ALB, RDS, SQS) plus Prometheus for Kubernetes and applications, joined in Grafana.
@diagram cmp
caption: Strengths side by side
cards:
  - {h: "CloudWatch", kind: warn, items: ["Zero setup for AWS services", "Pay per metric, alarm, API call", "Weaker query language"]}
  - {h: "Prometheus", kind: ok, items: ["Rich labels and PromQL", "Kubernetes ecosystem", "You run it, or use AMP"]}
@choose Which to use
CloudWatch alarms | an EC2 or RDS metric alone drives an action such as Auto Scaling | you need joins across metrics
Prometheus | Kubernetes workloads and app metrics | you only run three managed AWS services
Both in Grafana | mixed estate | you cannot afford two alert systems; pick one place to alert
@end
