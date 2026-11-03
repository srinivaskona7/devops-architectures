---
title: Grafana as code and capacity planning with Prometheus
minutes: 55
objectives:
  - Manage dashboards and alerts as reviewed code with provisioning, Terraform and Jsonnet
  - Forecast resource needs with predict_linear and simple growth arithmetic
  - Build capacity dashboards and alerts that warn days ahead
---
Dashboards edited by hand drift and vanish. Capacity surprises come from not looking ahead. Both are fixed by putting the work in code.

@concept Why dashboards as code
@plain
Treat dashboards, data sources and alert rules like application code: stored in Git, reviewed, and deployed by a pipeline.
@problem
Hand-built dashboards are lost when Grafana is rebuilt, differ between environments, and nobody knows who changed a panel.
@does
- Source of truth in Git; Grafana is read-only for provisioned items.
- Each change is a pull request with a diff and an owner.
- The same dashboard is deployed to dev and prod with different variables.
- Options: file provisioning, the Grafana operator, the Terraform provider, or Jsonnet libraries.
@diagram flow
caption: From Git to Grafana
numbered: true
nodes:
  - "Pull request|dashboard change|app"
  - "CI|lint and render|info"
  - "Deploy|provision or Terraform|cp"
  - "Grafana|read-only copy|ok"
@end

@concept Provisioning from Kubernetes ConfigMaps
@plain
The Grafana Helm chart and kube-prometheus-stack run a sidecar that watches ConfigMaps with a label and loads their JSON as dashboards.
@problem
Teams want to ship a dashboard together with their service Helm chart without touching Grafana.
@does
- The sidecar watches for ConfigMaps labelled `grafana_dashboard: "1"` (default label; check chart values).
- A folder annotation puts the dashboard in a Grafana folder.
- Data sources can be provisioned the same way with a `datasources.yaml` file.
- Dashboard JSON should use a data source variable, not a hard-coded UID.
@diagram flow
caption: ConfigMap becomes a dashboard
nodes:
  - "Service chart|ships a ConfigMap|app"
  - "Sidecar|watches label|cp"
  - "Grafana|dashboard appears|ok"
@h Example ConfigMap
```yaml title="dashboard-configmap.yaml"
apiVersion: v1
kind: ConfigMap
metadata:
  name: shop-api-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: Shop
data:
  shop-api.json: |
    {
      "title": "Shop API",
      "uid": "shop-api",
      "schemaVersion": 39,
      "panels": []
    }
```
@end

@concept Grafana with Terraform
@plain
The `grafana/grafana` Terraform provider manages folders, data sources, dashboards, alert rules and contact points through the Grafana API.
@problem
You run several Grafana instances (or Grafana Cloud) and want the same configuration with an audit trail.
@does
- Provider needs the URL and a service account token.
- `grafana_dashboard` takes JSON from `file()`; `grafana_folder` organises.
- Alerting resources: `grafana_rule_group`, `grafana_contact_point`, `grafana_notification_policy`. Check the provider docs for current attributes.
- Keep secrets (data source passwords) in `secure_json_data_encoded` fed from a secret store.
@diagram flow
caption: Terraform manages Grafana objects
nodes:
  - "Terraform|grafana provider|cp"
  - "Grafana API|service account token|info"
  - "Folders, dashboards, alerts|created|ok"
@h Example
```hcl title="grafana.tf"
provider "grafana" {
  url  = var.grafana_url
  auth = var.grafana_token
}

resource "grafana_folder" "shop" {
  title = "Shop"
}

resource "grafana_dashboard" "api" {
  folder      = grafana_folder.shop.id
  config_json = file("${path.module}/dashboards/shop-api.json")
}
```
@end

@concept Jsonnet and Grafonnet
@plain
Jsonnet is a templating language that outputs JSON. Grafonnet is a library that builds dashboards from functions instead of 3 000 lines of JSON.
@problem
Dashboard JSON is huge and repetitive; changing the same panel across 40 dashboards by hand is error prone.
@does
- Write a helper that builds a standard row (rate, errors, duration) for any service and call it with a service name.
- Output JSON with `jsonnet`, then provision it. The `grafana-foundation-sdk` is a newer typed alternative; check the current docs for which to use.
- The kubernetes-mixin project uses Jsonnet to generate the dashboards and rules in kube-prometheus.
- Trade-off: a new language to learn; keep helpers small.
@diagram flow
caption: Function to dashboards
nodes:
  - "Helper function|standard RED row|app"
  - "Per service call|name and selectors|info"
  - "jsonnet|renders JSON|cp"
  - "Dashboards|consistent|ok"
@h Sketch
```jsonnet title="red.libsonnet" nocheck
local g = import 'github.com/grafana/grafonnet/gen/grafonnet-latest/main.libsonnet';

local redRow(service) = [
  g.panel.timeSeries.new('Request rate')
  + g.panel.timeSeries.queryOptions.withTargets([
    g.query.prometheus.new('$datasource', 'sum(rate(http_requests_total{service="%s"}[5m]))' % service),
  ]),
];

g.dashboard.new('Service ' + 'shop-api')
+ g.dashboard.withPanels(redRow('shop-api'))
```
@check
What problem does Grafonnet solve? || It removes repetition by generating dashboard JSON from reusable functions.
@end

@concept Alert rules as code
@plain
Prometheus alert rules live in `PrometheusRule` objects, and Grafana alerts can be provisioned. Both belong in Git with tests.
@problem
Alert edits made in a UI are not reviewed, and a typo in an expression can silently disable paging.
@does
- Test Prometheus rules with `promtool test rules` using synthetic series.
- Lint expressions in CI with `promtool check rules`.
- One owner label per alert and a runbook URL annotation.
- Keep the alert near the service code so it ships with the feature.
@diagram flow
caption: Alert pipeline
numbered: true
nodes:
  - "Rule file|in service repo|app"
  - "promtool test|synthetic series|info"
  - "Merge|deployed by GitOps|cp"
  - "Fires correctly|verified|ok"
@h A tested rule
```yaml title="rules.yaml"
groups:
  - name: capacity
    rules:
      - alert: DiskWillFillIn4Days
        expr: predict_linear(node_filesystem_avail_bytes{fstype!="tmpfs"}[6h], 4 * 24 * 3600) < 0
        for: 1h
        labels:
          severity: ticket
        annotations:
          summary: Disk on {{ $labels.instance }} is predicted to fill within 4 days
```
@end

@concept Capacity planning method
@plain
Capacity planning answers: when will we run out of CPU, memory, disk or IP addresses, and what do we add by then?
@problem
Running out is a surprise page. Overbuying is a silent cost.
@does
- Pick the scarce resources: node CPU and memory requests, disk, PVC size, pod IPs per subnet, Prometheus series, database connections.
- Measure current use and the trend over 4 to 12 weeks, plus peak versus average.
- Growth arithmetic: 8 percent monthly growth starting from 100 units reaches 100 × 1.08 to the power 6 ≈ 158.7 after six months and ≈ 251.8 after twelve.
- Add lead time: if procuring or approving takes 4 weeks, alert when the forecast shows exhaustion within 6 weeks.
- Keep headroom (often 20 to 30 percent) for failures and spikes.
@diagram flow
caption: Plan loop
numbered: true
nodes:
  - "Measure|use and trend|info"
  - "Forecast|growth and seasonality|app"
  - "Add lead time|buy before it is needed|warn"
  - "Review monthly|adjust|ok"
@check
Units after 6 months at 8 percent monthly growth from 100? || 100 × 1.08^6 ≈ 158.7.
@end

@concept predict_linear and Kubernetes capacity queries
@plain
`predict_linear(v[range], seconds)` fits a straight line to recent data and projects it forward.
@problem
A threshold such as "disk above 80 percent" gives no time to react on a fast-filling disk and fires early on a slow one.
@does
- Use a range long enough to smooth noise (6 hours for disks) and not so long that it ignores a new trend.
- Linear forecasts fail for daily cycles or step changes; combine with `deriv` and dashboards.
- Kubernetes allocation: requested CPU as a share of allocatable CPU shows scheduling headroom, which differs from actual usage.
- Pod IP exhaustion (AWS VPC CNI) is a common cap: check subnet free IPs and the per-node ENI limit.
@diagram cmp
caption: Static threshold versus forecast
cards:
  - {h: "Static 80 percent", kind: warn, items: ["No time estimate", "Late for fast growth", "Noisy for slow"]}
  - {h: "predict_linear", kind: ok, items: ["Time to full", "Alert days ahead", "Wrong for cycles"]}
@h Queries
```text title="PromQL capacity" nocheck
# CPU requests as a fraction of allocatable CPU
sum(kube_pod_container_resource_requests{resource="cpu"}) / sum(kube_node_status_allocatable{resource="cpu"})

# Memory headroom per node
1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)

# Hours until a PVC is full
(kubelet_volume_stats_available_bytes / (-deriv(kubelet_volume_stats_available_bytes[6h]))) / 3600
```
@end

@concept Prometheus capacity and the capacity dashboard
@plain
Monitor the monitoring: Prometheus itself needs disk, memory and a limit on series.
@problem
A cardinality explosion makes Prometheus run out of memory and lose the very data you need during an incident.
@does
- Memory rule of thumb is a few kilobytes per active series (about 3 to 8 KB, depends on labels); 2 million series therefore needs roughly 6 to 16 GB. Measure your own with `process_resident_memory_bytes` divided by `prometheus_tsdb_head_series`.
- Alert on `prometheus_tsdb_head_series` growth, scrape sample limits, and `prometheus_tsdb_storage_blocks_bytes` against disk.
- One dashboard: nodes (CPU, memory), requests versus allocatable, PVC fill forecast, series count, top 10 metrics by series.
- Review monthly and record the forecast against the outcome to improve it.
@diagram layers
caption: Capacity dashboard rows
layers:
  - {label: "Cluster", nodes: ["CPU and memory requests|vs allocatable|app", "Pod IPs|subnet free addresses|app"]}
  - {label: "Storage", nodes: ["PVC forecast|days to full|warn", "Prometheus disk|TSDB size|warn"]}
  - {label: "Monitoring", nodes: ["Head series|growth|info", "Top metrics|by series|info"]}
@h Series by metric name
```text title="Top 10 metrics by series" nocheck
topk(10, count by (__name__) ({__name__=~".+"}))
```
:::warn
That query is expensive on large servers. Run it on demand, or use the TSDB status page in the Prometheus UI.
:::
@end
