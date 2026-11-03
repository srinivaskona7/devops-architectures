---
title: Prometheus architecture and data model
minutes: 50
objectives:
  - Describe the Prometheus pull model and its components
  - Read a time series with its labels and understand staleness
  - Write a scrape configuration and check target health
---
Prometheus is a time series database with a pull-based collector and a query language. It is the default metrics system on Kubernetes.
@concept Prometheus architecture
@plain
Prometheus is one server that **scrapes** HTTP endpoints on a schedule, stores the numbers in a local database, evaluates rules, and answers queries. Alerts are sent to a separate **Alertmanager**.
@problem
Push-based systems need every app to know where to send data and can hide dead apps. A central collector that pulls knows exactly what it expects to see.
@does
- Targets expose plain text at `/metrics`.
- The server stores samples in its own TSDB on local disk.
- Rules produce new series or alerts, Grafana and API clients run PromQL.
- Short-lived jobs use the Pushgateway, which Prometheus then scrapes.
@diagram flow
caption: Components around the Prometheus server
nodes:
  - "Targets|apps and exporters expose metrics|app"
  - "Prometheus|scrape, store, evaluate rules|cp"
  - "Alertmanager|route and notify|warn"
  - "Grafana|query and display|info"
  - "Receivers|Slack, PagerDuty, email|ext"
@end

@concept The data model
@plain
Everything is a **time series**: a metric name plus a set of key-value **labels**, holding a stream of timestamped numbers called samples.
@problem
You need to slice one measurement by many dimensions, such as per pod or per status code, without inventing a new name for each.
@does
- `http_requests_total{job="api",code="500"}` is one series. Change one label and it is a different series.
- Samples are a 64-bit float and a millisecond timestamp.
- The name is itself the hidden label `__name__`.
- Labels beginning with `__` are internal and removed before storage.
@diagram layers
caption: Anatomy of one series
layers:
  - {label: "Identity", nodes: ["Metric name|http_requests_total|info", "Labels|job, instance, code|env"]}
  - {label: "Data", nodes: ["Timestamp|milliseconds|plain", "Value|float64|ok"]}
@h Exposition format
```text title="What /metrics looks like"
# HELP http_requests_total Total HTTP requests.
# TYPE http_requests_total counter
http_requests_total{method="GET",code="200"} 10234
http_requests_total{method="GET",code="500"} 17
```
@end

@concept Scraping and scrape configuration
@plain
Every `scrape_interval` Prometheus makes an HTTP GET to each target and stores what it returns. A **job** is a group of targets with the same purpose.
@problem
You need predictable, central control of how often and where data is collected.
@does
- `scrape_interval` is commonly 15s to 60s, and `scrape_timeout` must be shorter.
- Prometheus adds `job` and `instance` labels to every series.
- Each scrape also writes `up` (1 or 0) and `scrape_duration_seconds`.
@diagram seq
caption: One scrape cycle
actors: ["Prometheus|server|cp", "Target|app /metrics|app", "TSDB|local storage|env"]
steps:
  - "0>1: GET /metrics | req"
  - "1>0: text samples | resp"
  - "0>2: append samples and up=1 | req"
  - "note 0..1: timeout means up=0"
@h A minimal prometheus.yml
```yaml title="prometheus.yml"
global:
  scrape_interval: 30s
  scrape_timeout: 10s
  evaluation_interval: 30s
rule_files:
  - /etc/prometheus/rules/*.yml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
scrape_configs:
  - job_name: prometheus
    static_configs:
      - targets: ["localhost:9090"]
  - job_name: node
    static_configs:
      - targets: ["10.0.1.11:9100", "10.0.1.12:9100"]
```
```bash title="Validate before reload" lab
promtool check config prometheus.yml
curl -s localhost:9090/api/v1/targets | head -c 400
curl -X POST localhost:9090/-/reload   # needs --web.enable-lifecycle
```
@end

@concept The up metric and staleness
@plain
`up` is a series Prometheus creates for each target: 1 if the last scrape worked, 0 if not. When a series stops appearing, Prometheus marks it **stale** instead of showing the old value for five minutes.
@problem
You must know when a target disappears. And queries should not show data from a pod that was deleted a minute ago.
@does
- `up == 0` is the base alert for a broken scrape.
- A target that vanishes from service discovery produces no `up` series at all, so use `absent()` for "should exist but does not".
- Stale markers end a series cleanly; the default lookback for instant queries is 5 minutes.
@diagram flow
caption: Three ways a target can fail
nodes:
  - "Scrape works|up is 1|ok"
  - "Scrape fails|up is 0|warn"
  - "Target removed|no up series, use absent|bad"
@h Alerts for missing targets
```promql title="Down and missing" nocheck
up{job="node"} == 0
absent(up{job="node"})
count(up{job="node"} == 1) / count(up{job="node"}) < 0.9
```
@check
Why is up == 0 not enough? || If discovery drops the target there is no up series, so the expression returns nothing; absent() catches that.
@end

@concept Choosing a metric type for instrumentation
@plain
When you write your own code, the client library gives you counter, gauge, histogram and summary objects. The name and unit conventions matter as much as the type.
@problem
Inconsistent names and units make dashboards impossible to reuse and queries wrong.
@does
- Use base units: seconds, bytes, ratios 0 to 1. Put the unit in the name: `_seconds`, `_bytes`.
- Counters end with `_total`.
- Never put unbounded values such as user IDs or URLs with IDs into labels.
- Name format: `application_what_unit`, for example `checkout_orders_total`.
@diagram cmp
caption: Good and bad metric names
cards:
  - {h: "Good", kind: ok, items: ["http_request_duration_seconds", "queue_length", "backup_last_success_timestamp_seconds"]}
  - {h: "Bad", kind: bad, items: ["request_time_ms", "requests_per_sec", "path label with user ids"]}
@h Python client example
```python title="Instrumenting a service"
from prometheus_client import Counter, Histogram, start_http_server

REQS = Counter("checkout_orders_total", "Orders placed", ["status"])
LAT = Histogram("checkout_request_duration_seconds", "Request latency",
                buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5))

def handle():
    with LAT.time():
        REQS.labels(status="ok").inc()

start_http_server(8000)   # serves /metrics
```
@end

@concept Push versus pull and the Pushgateway
@plain
Prometheus pulls from long-lived services. For batch jobs that finish before a scrape, the **Pushgateway** holds the last pushed values so Prometheus can still collect them.
@problem
A nightly backup job lives for 90 seconds. It cannot be scraped reliably.
@does
- The job pushes its metrics to the gateway at the end.
- The gateway keeps them until deleted, so stale values can mislead. Add a timestamp metric and alert if it is old.
- Do not use it as a general push proxy for services; you lose `up` health checking.
@diagram flow
caption: Batch job metrics through the Pushgateway
nodes:
  - "Batch job|runs 90 seconds|app"
  - "Pushgateway|holds last values|env"
  - "Prometheus|scrapes the gateway|cp"
@h Example
```bash title="Push a success timestamp" lab
cat <<EOM | curl --data-binary @- http://pushgateway:9091/metrics/job/nightly_backup
# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds $(date +%s)
EOM
```
```promql title="Alert if no success for 26 hours" nocheck
time() - backup_last_success_timestamp_seconds{job="nightly_backup"} > 26*3600
```
@end

@concept Prometheus on a laptop in one minute
@plain
You can run Prometheus and node_exporter locally with Docker to try every query in this section.
@problem
Learning from slides is slower than typing a query and seeing a graph.
@does
- One compose file starts both services and a Grafana.
- Open `http://localhost:9090/graph` for the expression browser.
- The `Status > Targets` page shows scrape health.
@diagram flow
caption: A local lab
nodes:
  - "node_exporter|port 9100|app"
  - "Prometheus|port 9090|cp"
  - "Grafana|port 3000|info"
@h Compose file
```yaml title="compose.yaml" lab
services:
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports: ["9090:9090"]
  node:
    image: prom/node-exporter:latest
    ports: ["9100:9100"]
  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
```
:::tip
Pin image tags in anything beyond a lab. `latest` changes under you.
:::
@end
