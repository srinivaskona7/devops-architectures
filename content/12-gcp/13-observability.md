---
title: Cloud Logging, Monitoring, Prometheus, Error Reporting and Trace
minutes: 60
objectives:
  - Route and query logs with Cloud Logging sinks and the Logging query language
  - Build alerting policies, uptime checks and SLOs in Cloud Monitoring
  - Use Managed Service for Prometheus, Error Reporting and Cloud Trace for Kubernetes workloads
---
Google Cloud Observability is on by default for most services. The work for an engineer is routing, retention, alert design and keeping Prometheus-style tooling that you already know.

@concept Cloud Logging basics
@plain
**Cloud Logging** collects logs from Google services, GKE, VMs (through the Ops Agent) and your applications into log buckets, where you query them with the Logging query language.
@problem
Logs spread over nodes and services are unusable during an incident.
@does
- Log entries have a `logName`, `resource.type`, `severity`, a payload (text, JSON or protobuf) and labels.
- GKE writes container stdout and stderr automatically. JSON lines on stdout become structured `jsonPayload`; set `severity` in the JSON to map levels.
- Buckets: `_Required` (audit, 400 days), `_Default` (30 days default retention), and user-defined buckets with your own retention and location.
- **AWS equivalent**: CloudWatch Logs. Main difference: logs are routed through a central Log Router with sinks and exclusions, and queries use a filter language rather than Logs Insights syntax.
@diagram flow
caption: Log path
nodes:
  - "Container stdout|JSON lines|app"
  - "Log Router|sinks and exclusions|cp"
  - "Log bucket|retention|db"
  - "Logs Explorer|query|info"
@h Read logs
```bash title="Query logs" lab
gcloud logging read 'resource.type="k8s_container" AND resource.labels.namespace_name="shop" AND severity>=ERROR' \
  --project=shop-dev-123456 --freshness=1h --limit=20 --format="table(timestamp,resource.labels.pod_name,jsonPayload.message)"
gcloud logging buckets update _Default --location=global --retention-days=14
```
@check
Where does a JSON line on stdout end up in the log entry? || In jsonPayload, with severity taken from the severity field if present.
@end

@concept Log Router, sinks and exclusions
@plain
The **Log Router** evaluates every entry against sinks. A **sink** sends matching entries to a destination: a log bucket, BigQuery, Cloud Storage, Pub/Sub or another project.
@problem
You need long-term archives, analytics, SIEM export and a way to drop noisy logs to save cost.
@does
- Aggregated sinks at folder or organization level collect from all children.
- Exclusion filters stop matching entries from being stored in a bucket (they still go to other sinks).
- Each sink has a writer identity service account that needs permission on the destination.
- Log-based metrics count entries or extract values and appear in Monitoring.
- **AWS equivalent**: CloudWatch subscription filters and Firehose to S3. Main difference: the Router is a single place, and sinks are free (you pay for the destination).
@diagram flow
caption: Routing
nodes:
  - "All entries|every service|app"
  - "Router|filters|cp"
  - "BigQuery|analytics|db"
  - "Cloud Storage|archive|db"
  - "Pub/Sub|SIEM feed|ext"
@h Sinks
```bash title="Create sinks" lab
gcloud logging sinks create audit-to-bq bigquery.googleapis.com/projects/shop-dev-123456/datasets/audit \
  --log-filter='logName:"cloudaudit.googleapis.com"' --use-partitioned-tables
gcloud logging sinks describe audit-to-bq --format="value(writerIdentity)"
gcloud logging metrics create shop-5xx --description="HTTP 5xx from the API" \
  --log-filter='resource.type="k8s_container" AND jsonPayload.status>=500'
```
@end

@concept Cloud Monitoring metrics and dashboards
@plain
**Cloud Monitoring** stores time series from Google services, agents, custom metrics and Prometheus. Metrics have a type, resource and labels.
@problem
You need dashboards and queries across infrastructure and application behaviour.
@does
- System metrics need no setup: `compute.googleapis.com/instance/cpu/utilization`, `kubernetes.io/container/memory/used_bytes`, load balancer request counts.
- Query in the Metrics Explorer with MQL (older) or PromQL (recommended); dashboards can be defined as JSON and deployed with `gcloud monitoring dashboards create`.
- A **metrics scope** lets one project view metrics from many projects.
- **AWS equivalent**: CloudWatch Metrics. Main difference: PromQL is supported directly, with labels on every series.
@diagram layers
caption: Metric sources
layers:
  - {label: "Sources", nodes: ["Google services|automatic|ok", "Ops Agent|VM metrics|info", "Managed Prometheus|your /metrics|app", "Custom metrics|API|warn"]}
  - {label: "Store", nodes: ["Cloud Monitoring|time series|db"]}
  - {label: "Use", nodes: ["Dashboards|charts|app", "Alerts|policies|bad", "SLOs|objectives|cp"]}
@h Dashboard from JSON
```json title="dashboard.json"
{
  "displayName": "Shop API",
  "gridLayout": {
    "columns": 2,
    "widgets": [
      {
        "title": "Request rate",
        "xyChart": {
          "dataSets": [
            {"timeSeriesQuery": {"prometheusQuery": "sum(rate(http_requests_total{job=\"shop-api\"}[5m]))"}}
          ]
        }
      }
    ]
  }
}
```
```bash title="Create it" lab
gcloud monitoring dashboards create --config-from-file=dashboard.json
```
@check
Which query language does Google recommend for new Monitoring queries? || PromQL.
@end

@concept Alerting policies and notification channels
@plain
An **alerting policy** has conditions on metrics or logs, and notification channels (email, Slack, PagerDuty, Pub/Sub, webhook).
@problem
Nobody watches dashboards all day. Alerts must be actionable and not noisy.
@does
- Condition types: metric threshold, metric absence, PromQL condition, log match, and uptime check failure.
- Set duration (alignment and `duration`) to avoid flapping, and use documentation fields with runbook links.
- Incidents open and close automatically. Alert on symptoms (errors, latency) rather than causes (CPU) where possible.
- Define policies as code with YAML and `gcloud alpha monitoring policies create --policy-from-file` or Terraform `google_monitoring_alert_policy`.
- **AWS equivalent**: CloudWatch Alarms with SNS. Main difference: policies can combine multiple conditions and use PromQL.
@diagram flow
caption: Alert flow
nodes:
  - "Condition|error ratio above 2 percent|warn"
  - "Policy|duration 5 minutes|cp"
  - "Incident|opened|bad"
  - "Channel|Slack or pager|ext"
@h Alert policy
```hcl title="alert.tf"
resource "google_monitoring_alert_policy" "api_5xx" {
  display_name = "Shop API 5xx ratio"
  combiner     = "OR"
  conditions {
    display_name = "5xx ratio over 2 percent"
    condition_prometheus_query_language {
      query    = "sum(rate(http_requests_total{job=\"shop-api\",code=~\"5..\"}[5m])) / sum(rate(http_requests_total{job=\"shop-api\"}[5m])) > 0.02"
      duration = "300s"
    }
  }
  notification_channels = [google_monitoring_notification_channel.oncall.id]
  documentation {
    content   = "Runbook: https://wiki.example.com/runbooks/shop-api-5xx"
    mime_type = "text/markdown"
  }
}
```
@end

@concept Uptime checks and SLOs
@plain
**Uptime checks** probe public or private endpoints from several regions. **Service Level Objectives** track reliability goals and error budget.
@problem
You need an outside-in view of availability and a way to decide when to slow feature work.
@does
- HTTP, HTTPS and TCP checks from global locations; private checks use a private-network probe through the Service Directory.
- SLOs on request-based or window-based SLIs; burn-rate alerting policies warn about fast and slow budget consumption.
- Services in GKE with Cloud Service Mesh and Istio, App Engine, and Cloud Run are detected automatically; custom services define SLIs by metrics.
- **AWS equivalent**: CloudWatch Synthetics and Application Signals SLOs. Main difference: uptime checks are lightweight config, not scripted canaries.
@diagram flow
caption: Error budget
nodes:
  - "SLI|good requests over total|info"
  - "SLO|99.9 percent in 30 days|cp"
  - "Error budget|0.1 percent|warn"
  - "Burn rate alert|fast or slow|bad"
@h Uptime check
```bash title="Create an uptime check" lab
gcloud monitoring uptime create shop-home --resource-type=uptime-url \
  --resource-labels=host=shop.example.com,project_id=shop-dev-123456 \
  --protocol=https --path=/healthz --period=1
gcloud monitoring uptime list-configs --format="table(displayName,period)"
```
:::note
Check the latest `gcloud monitoring uptime` flags; the command group is newer than some tutorials.
:::
@check
What does a burn-rate alert tell you? || How fast the error budget is being used compared with the allowed rate.
@end

@concept Managed Service for Prometheus
@plain
**Google Cloud Managed Service for Prometheus** collects Prometheus metrics with managed collectors and stores them in Monarch (the Cloud Monitoring backend), queried with PromQL.
@problem
Running Prometheus servers, storage and federation is operational work, and long retention costs effort.
@does
- Managed collection is enabled by default on new GKE Autopilot clusters; for Standard use `--enable-managed-prometheus`.
- You declare scraping with `PodMonitoring` (namespaced) or `ClusterPodMonitoring` custom resources. Rules and alerting rules use `Rules` and `ClusterRules` resources; Alertmanager can be run for notification.
- Retention is 24 months for metrics by default; check pricing, which is per sample ingested.
- Grafana connects through the Prometheus data source UI proxy or a frontend.
- **AWS equivalent**: Amazon Managed Service for Prometheus. Main difference: the same data is available to Cloud Monitoring alerts and dashboards.
@diagram flow
caption: Managed collection
nodes:
  - "App /metrics|port 8080|app"
  - "PodMonitoring|scrape config|info"
  - "Managed collector|DaemonSet|cp"
  - "Monarch store|PromQL|db"
@h PodMonitoring
```yaml title="podmonitoring.yaml"
apiVersion: monitoring.googleapis.com/v1
kind: PodMonitoring
metadata:
  name: shop-api
  namespace: shop
spec:
  selector:
    matchLabels:
      app: shop-api
  endpoints:
    - port: metrics
      interval: 30s
      path: /metrics
```
```bash title="Enable on Standard" lab
gcloud container clusters update shop-std --region=europe-west1 --enable-managed-prometheus
kubectl apply -f podmonitoring.yaml
```
@end

@concept Error Reporting
@plain
**Error Reporting** groups application exceptions found in logs into distinct errors with counts, first and last seen and stack traces.
@problem
Hundreds of repeated stack traces hide the one new error.
@does
- Automatically reads logs containing stack traces or entries sent through its API in supported languages; log entries must be in a recognised format (for example a JSON payload with `stack_trace` or the `@type` field of `ReportedErrorEvent`).
- Groups similar errors, allows resolving or muting, and sends notifications for new errors.
- Works with GKE, Cloud Run, Compute Engine and Cloud Run functions.
- **AWS equivalent**: CloudWatch Application Signals or Sentry-like features; no direct match. Main difference: it needs no SDK for standard runtimes.
@diagram flow
caption: From exception to group
nodes:
  - "Exception|stack trace in log|bad"
  - "Error Reporting|groups by signature|cp"
  - "New error|notification|warn"
  - "Engineer|investigates|ext"
@h Structured error log
```json title="Error log entry"
{
  "severity": "ERROR",
  "message": "OrderError: payment declined\n  at charge (/app/payments.js:42:11)\n  at process (/app/orders.js:17:5)",
  "serviceContext": {"service": "shop-api", "version": "1.4.2"}
}
```
@check
What does Error Reporting group by? || The stack trace signature of an error.
@end

@concept Cloud Trace and Cloud Profiler
@plain
**Cloud Trace** collects distributed traces for latency analysis. **Cloud Profiler** records continuous CPU and heap profiles.
@problem
A slow request crosses many services, and averages hide where the time is spent.
@does
- Instrument with OpenTelemetry and export through the Google Cloud exporter or an OpenTelemetry Collector; Cloud Run and App Engine add some traces automatically.
- Propagate the W3C `traceparent` header (Google's `X-Cloud-Trace-Context` is also accepted).
- Trace shows a waterfall of spans with latency distributions; logs carry a `trace` field so you can jump from a trace to its logs.
- Profiler has a low overhead agent for Go, Java, Node.js and Python.
- **AWS equivalent**: X-Ray and CodeGuru Profiler. Main difference: OpenTelemetry is the primary path.
@diagram seq
caption: Trace across services
actors: ["Browser|client|ext", "Web|span 1|app", "API|span 2|app", "Cloud Trace|collector|cp"]
steps:
  - "0>1: request with traceparent | req"
  - "1>2: call API, pass header | req"
  - "2>3: export spans | tele"
  - "1>3: export spans | tele"
@h OpenTelemetry Collector exporter
```yaml title="otel-collector.yaml"
receivers:
  otlp:
    protocols:
      grpc: {}
processors:
  batch: {}
exporters:
  googlecloud:
    project: shop-dev-123456
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch]
      exporters: [googlecloud]
```
@end
