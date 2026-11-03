---
title: Loki and LogQL
minutes: 55
objectives:
  - Explain how Loki indexes labels and stores log chunks
  - Write LogQL queries for filtering, parsing and metrics from logs
  - Design labels and retention to keep Loki cheap and fast
---
Loki is built like Prometheus for logs. It indexes only labels, not the log text, which makes it cheap, and it changes how you query and how you design labels.

@concept How Loki stores logs
@plain
Loki groups log lines into **streams**, one per unique set of labels. It indexes the labels and compresses the lines into chunks in object storage such as S3.
@problem
Full-text indexing of every line (as in Elasticsearch) costs a lot of CPU, memory and disk for logs that are rarely read.
@does
- Index = labels only (small). Chunks = compressed lines (large, in S3 or similar).
- A query first selects streams by labels, then scans the chunks of those streams for text matches.
- Fast when labels narrow the search; slow when you scan huge streams with a broad regex.
- Components: distributor, ingester, querier, query frontend, compactor; check the current docs for the deployment modes (monolithic, simple scalable, microservices).
@diagram flow
caption: Write and read path
nodes:
  - "Promtail or Alloy|ships lines with labels|app"
  - "Distributor and ingester|build chunks|cp"
  - "S3|chunks and index|info"
  - "Querier|select streams then scan|ok"
@check
What does Loki index? || Only the labels of each stream, not the text of the lines.
@end

@concept Labels and cardinality
@plain
A label is a key and value such as `namespace="shop"`. Every unique combination creates a new stream.
@problem
Putting high-cardinality values (user ID, request ID, pod IP) in labels creates millions of tiny streams, which makes ingestion and queries slow and costly.
@does
- Good labels: cluster, namespace, app, container, level (low and bounded).
- Bad labels: trace_id, user_id, URL path with IDs. Keep these inside the log line and filter or parse them at query time.
- Rough count: 5 clusters × 20 namespaces × 3 containers = 300 streams per level value, which is fine; adding a pod label with 50 pods each multiplies it by 50.
- Loki enforces limits such as maximum streams per tenant; check the current defaults.
@diagram cmp
caption: Label choices
cards:
  - {h: "Good labels", kind: ok, items: ["namespace, app, container", "level", "Few, bounded values"]}
  - {h: "Bad labels", kind: bad, items: ["trace_id, user_id", "Full URL path", "Millions of streams"]}
@h Alloy relabel to keep labels small
```yaml title="Promtail style pipeline" nocheck
pipeline_stages:
  - cri: {}
  - json:
      expressions:
        level: level
        trace_id: trace_id
  - labels:
      level:
```
@end

@concept Log queries, selectors and filters
@plain
A LogQL query begins with a stream selector in braces, then adds line filters.
@problem
You need to find the error lines of one service in the last 15 minutes without reading everything.
@does
- Selector: `{namespace="shop", app="api"}` uses `=`, `!=`, `=~` and `!~`. At least one non-empty matcher is required.
- Line filters: `|= "error"` contains, `!= "healthz"` excludes, `|~ "timeout|refused"` regex, `!~` negative regex.
- Put the most selective filter first, and prefer plain strings over regex.
- Order of work: selector, then filters, then parsers.
@diagram flow
caption: Narrow first
nodes:
  - "Selector|labels pick streams|cp"
  - "Line filter|contains or regex|info"
  - "Parser|json or logfmt|app"
  - "Result lines|ok|ok"
@h Examples
```text title="LogQL" nocheck
{namespace="shop", app="api"} |= "error" != "healthz"
{namespace="shop"} |~ "timeout|connection refused"
```
@end

@concept Parsers and label filters
@plain
Parsers turn a line into temporary labels at query time. Then you can filter on fields.
@problem
Structured fields live inside the line, such as `status=503` or a JSON `latency_ms`, and are not Loki labels.
@does
- `| json`, `| logfmt`, `| pattern "<ip> - <_> <method> <path>"` and `| regexp` extract fields.
- Filter extracted fields: `| status >= 500`, `| duration > 1s`, `| level = "error"`.
- `| line_format "{{.path}} {{.status}}"` rewrites the displayed line. `| drop` and `| keep` remove labels.
- Parsing costs CPU; narrow the selector first.
@diagram flow
caption: Parse then filter on fields
nodes:
  - "Raw JSON line|from the app|plain"
  - "json parser|fields become labels|app"
  - "status filter|500 and above|warn"
  - "Matching lines|ok|ok"
@h Example
```text title="JSON logs" nocheck
{namespace="shop", app="api"} | json | status >= 500 | line_format "{{.method}} {{.path}} {{.status}} {{.trace_id}}"
```
@check
Why not make status a Loki label? || It is dynamic per line; parse it at query time to avoid more streams, unless the values are few and stable.
@end

@concept Metric queries from logs
@plain
LogQL can turn log lines into numbers using `rate`, `count_over_time` and `sum by`, like PromQL.
@problem
You need error rates, or a quick metric for an app that does not export one.
@does
- `rate({app="api"} |= "error" [5m])` gives lines per second.
- `sum by (namespace) (count_over_time({app="api"} | json | status >= 500 [1m]))` counts errors per minute per namespace.
- `quantile_over_time(0.95, {app="api"} | json | unwrap duration_ms [5m]) by (path)` computes percentiles from a numeric field.
- Use metrics for alerts through the Loki ruler or recording rules, but for stable alerting prefer real Prometheus metrics.
@diagram flow
caption: Lines to numbers
nodes:
  - "Log stream|json lines|plain"
  - "Range function|count_over_time|app"
  - "Aggregation|sum by namespace|cp"
  - "Graph or alert|ok|ok"
@h Examples
```text title="LogQL metrics" nocheck
sum by (namespace) (rate({app="api"} |= "error" [5m]))
quantile_over_time(0.95, {app="api"} | json | unwrap duration_ms [5m]) by (path)
```
@end

@concept Deploying Loki and collecting logs on Kubernetes
@plain
Install Loki with Helm and run a collector as a DaemonSet that reads container log files and pushes them to Loki.
@problem
Applications write to stdout; something must read node log files, attach Kubernetes labels and ship them.
@does
- The Grafana Helm chart `grafana/loki` supports modes; start with the simple scalable or monolithic mode for small clusters. Check the current docs, since chart values change between versions.
- Collector: Grafana Alloy is the current agent; Promtail is in maintenance mode, so check the current docs before choosing.
- Use S3 for chunks and index with an IRSA or Pod Identity role; avoid filesystem storage in production.
- Multi-tenancy uses the `X-Scope-OrgID` header.
@diagram flow
caption: Logs from pod to query
nodes:
  - "Pod stdout|container logs on node|plain"
  - "Alloy DaemonSet|adds k8s labels|app"
  - "Loki|ingest and index|cp"
  - "Grafana|Explore and dashboards|ok"
@h Storage configuration sketch
```yaml title="loki values (sketch)" nocheck
loki:
  storage:
    type: s3
    bucketNames:
      chunks: acme-loki-chunks
    s3:
      region: eu-west-1
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: s3
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
```
@end

@concept Retention, limits and cost
@plain
Logs grow without end unless you set retention and per-tenant limits.
@problem
A single noisy debug-logging service can fill storage and slow queries for everyone.
@does
- Retention is applied by the compactor (`retention_enabled`), globally or per stream selector via limits.
- Limits per tenant: ingestion rate, burst, streams, query range and line length.
- Estimate cost: 200 GB per day raw, compression often 5 to 10 times, 30 days: 200 × 30 ÷ 7 ≈ 857 GB stored at 7 times compression. Compute it with your own ratio.
- Drop noise at the agent (health checks, debug level in production) instead of paying to store it.
@diagram layers
caption: Cost controls
layers:
  - {label: "At source", nodes: ["Log levels|info in prod|ok", "Drop health checks|at the agent|ok"]}
  - {label: "In Loki", nodes: ["Per tenant limits|rate and streams|cp", "Retention|compactor deletes|cp"]}
  - {label: "Storage", nodes: ["S3 lifecycle|cheaper tiers|info"]}
@check
200 GB per day for 30 days at 7 times compression stores about how much? || 200 × 30 ÷ 7 ≈ 857 GB.
@end

@concept Loki, correlating with metrics and traces
@plain
Grafana links the three signals: from a metric spike to the logs of the same labels, from a log line to its trace.
@problem
Switching tools and retyping filters during an incident costs minutes.
@does
- Use the same label names (`namespace`, `app`) in Prometheus and Loki so a dashboard can jump with one click.
- A Loki data source **derived field** turns `trace_id=(\w+)` in a log line into a link to Tempo.
- Log the trace ID in every structured log line; OpenTelemetry SDKs can inject it.
- Explore split view shows metrics and logs side by side for one time range.
@diagram flow
caption: From symptom to cause
nodes:
  - "Metric spike|Prometheus panel|warn"
  - "Logs same labels|Loki|info"
  - "trace_id link|derived field|cp"
  - "Trace|Tempo|ok"
@end
