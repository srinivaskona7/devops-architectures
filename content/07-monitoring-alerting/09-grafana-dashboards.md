---
title: Grafana dashboards that answer questions
minutes: 50
objectives:
  - Design dashboards around a question instead of a data dump
  - Use variables and templating to make one dashboard serve many services
  - Provision data sources and dashboards as code
---
Grafana draws what your data sources store. A good dashboard answers one question in under ten seconds.

@concept What Grafana is
@plain
Grafana is a web application that queries data sources (Prometheus, Loki, Tempo, CloudWatch, Elasticsearch, SQL) and shows the results in panels on dashboards.
@problem
Raw query output is hard to read. Teams need shared, versioned views of system health.
@does
- Grafana stores no metrics itself; it forwards queries to each data source.
- One dashboard can mix data sources, for example Prometheus latency next to CloudWatch RDS CPU.
- Folders, teams and permissions control who sees what.
@diagram flow
caption: Grafana sits in front of your data
nodes:
  - "Prometheus|metrics|cp"
  - "Loki|logs|cp"
  - "Tempo|traces|cp"
  - "Grafana|dashboards and alerts|app"
  - "Engineer|browser|ext"
@end

@concept Dashboard design principles
@plain
Start with the question, then the layout. Put the most important signal at the top left and detail below.
@problem
Dashboards with 60 panels hide the one that matters during an incident.
@does
- Top row: SLO status and the RED or golden signals for the service.
- Next rows: dependencies, then resources (USE), then detail.
- Show units and thresholds. Use the same colours for the same meaning everywhere.
- Link to runbooks and to related dashboards.
@diagram layers
caption: A service dashboard from top to bottom
layers:
  - {label: "Row 1", nodes: ["SLO and error budget|am I ok|ok", "Request rate|traffic|info"]}
  - {label: "Row 2", nodes: ["Error ratio|errors|bad", "p50 and p99 latency|duration|warn"]}
  - {label: "Row 3", nodes: ["Dependencies|DB, cache, queues|app", "Saturation|CPU, memory, pool|env"]}
@end

@concept Panels and PromQL in Grafana
@plain
A panel has a query, a visualization (time series, stat, gauge, table, heatmap) and display options such as units and thresholds.
@problem
The same data can mislead if shown with the wrong visualization.
@does
- Use `$__rate_interval` instead of a fixed window in `rate()`; Grafana picks a safe value from the scrape interval and graph step.
- Heatmaps suit histogram buckets. Stat panels suit current SLO values.
- Legend format `{{pod}}` names series by a label.
- Set the correct unit (seconds, bytes, percent 0.0-1.0) so axes are readable.
@diagram cmp
caption: Visualization choice
cards:
  - {h: "Time series", kind: info, items: ["Trends and spikes", "Rates, latency"]}
  - {h: "Stat or gauge", kind: ok, items: ["One current number", "SLO, uptime"]}
  - {h: "Heatmap", kind: app, items: ["Latency distribution", "Histogram buckets"]}
  - {h: "Table", kind: warn, items: ["Top offenders", "Instant query"]}
@h Query examples
```promql title="Panel queries" nocheck
sum by (service) (rate(http_requests_total[$__rate_interval]))
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{service="$service"}[$__rate_interval])))
```
@end

@concept Variables and templating
@plain
Dashboard variables are drop-downs (`$cluster`, `$namespace`, `$service`) that change queries without editing the dashboard.
@problem
Copying one dashboard for each of 40 services makes maintenance impossible.
@does
- Query variables fill from label values: `label_values(kube_pod_info, namespace)`.
- Chained variables: `label_values(kube_pod_info{namespace="$namespace"}, pod)`.
- Multi-value and "All" options need regex matchers in queries: `namespace=~"$namespace"`.
- Add `$datasource` to switch between clusters or tenants.
@diagram flow
caption: Variables narrow the query
numbered: true
nodes:
  - "Pick cluster|datasource variable|info"
  - "Pick namespace|label_values query|app"
  - "Pick service|depends on namespace|warn"
  - "Panels re-query|filtered|ok"
@h Example
```promql title="Query using variables" nocheck
sum by (pod) (rate(container_cpu_usage_seconds_total{namespace=~"$namespace", pod=~"$service-.*", container!=""}[$__rate_interval]))
```
@end

@concept Annotations, links and exemplars
@plain
Annotations mark events (deploys, alerts) on graphs. Data links and exemplars jump from a panel to logs, traces or runbooks.
@problem
A latency spike means little until you can see it started at the moment of a deploy, or click through to the slow request.
@does
- Annotation queries can read alert state or a deploy metric.
- Data links build URLs with variables such as `${__field.labels.pod}`.
- Exemplars attach a trace ID to a histogram bucket so a dot on the graph opens the trace in Tempo.
@diagram flow
caption: From a spike to the cause
nodes:
  - "Latency spike|time series panel|warn"
  - "Deploy annotation|started at the same time|info"
  - "Exemplar|click to open trace|app"
  - "Trace in Tempo|slow span|ok"
@end

@concept Provisioning as code
@plain
Grafana reads YAML files at startup to create data sources and to load dashboards from JSON files on disk. Everything is then in Git.
@problem
Click-built dashboards disappear when someone edits them, cannot be reviewed, and are lost when Grafana is rebuilt.
@does
- `provisioning/datasources/*.yaml` define data sources.
- `provisioning/dashboards/*.yaml` define providers that point at folders of JSON.
- Dashboards come from Git, usually a ConfigMap with the sidecar loader in Kubernetes, or the Grafana Operator.
- Set `allowUiUpdates: false` so Git stays the source of truth.
@diagram flow
caption: Dashboards from Git to Grafana
nodes:
  - "Git repo|dashboard JSON, YAML|ext"
  - "CI|lint and render|info"
  - "ConfigMap|mounted into Grafana|env"
  - "Grafana|loads provisioning|app"
@h Provisioning files
```yaml title="provisioning/datasources/prometheus.yaml"
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus-operated.monitoring:9090
    isDefault: true
    jsonData:
      timeInterval: 30s
```
```yaml title="provisioning/dashboards/default.yaml"
apiVersion: 1
providers:
  - name: platform
    folder: Platform
    type: file
    allowUiUpdates: false
    options:
      path: /var/lib/grafana/dashboards
```
@end

@concept Dashboards as code with a tiny generator
@plain
You can generate dashboard JSON from Python, Jsonnet (Grafonnet) or Terraform instead of hand editing.
@problem
Fifty near-identical service dashboards drift apart.
@does
- Write one template function that takes a service name and emits JSON.
- Review the JSON diff in a pull request.
- The same file can be pushed with the Grafana HTTP API or mounted via provisioning.
@diagram flow
caption: Template to dashboard
nodes:
  - "Template|python or jsonnet|app"
  - "Dashboard JSON|one per service|info"
  - "Grafana|provisioned|ok"
@h Minimal Python generator
```python title="make_dashboard.py"
import json

def panel(pid, title, expr, x, y):
    return {"id": pid, "type": "timeseries", "title": title,
            "gridPos": {"h": 8, "w": 12, "x": x, "y": y},
            "targets": [{"expr": expr, "refId": "A"}]}

def dashboard(service):
    rate = f'sum(rate(http_requests_total{{service="{service}"}}[$__rate_interval]))'
    err = (f'sum(rate(http_requests_total{{service="{service}",code=~"5.."}}[$__rate_interval]))'
           f' / {rate}')
    return {"title": f"{service} RED", "uid": f"red-{service}", "schemaVersion": 39,
            "panels": [panel(1, "Rate", rate, 0, 0), panel(2, "Error ratio", err, 12, 0)]}

print(json.dumps(dashboard("checkout"), indent=2))
```
:::note
Dashboard `schemaVersion` changes with Grafana releases. Export a dashboard from your version to see the current value.
:::
@end

@concept Dashboard review checklist
@plain
Before sharing a dashboard, run through a short checklist.
@problem
Unreviewed dashboards mislead during incidents.
@does
- Does the title say what question it answers?
- Are units, thresholds and time ranges correct?
- Do variables work with All selected?
- Is every expensive query using a recording rule?
- Is there a runbook link?
@diagram flow
caption: Review steps
numbered: true
nodes:
  - "Question|stated in title|info"
  - "Queries|use rate_interval and recording rules|app"
  - "Variables|test All|warn"
  - "Links|runbook and traces|ok"
@check
Why use $__rate_interval over [5m]? || It adapts to scrape interval and zoom level so rate always has enough samples.
@end
