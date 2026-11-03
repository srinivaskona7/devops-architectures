---
title: Grafana alerting, Loki and Tempo
minutes: 45
objectives:
  - Compare Grafana-managed alerting with Prometheus alert rules
  - Link metrics, logs and traces in one workflow
  - Query Loki with LogQL and understand Tempo basics
---
Grafana does more than draw graphs. It can alert, and with Loki and Tempo it connects the three observability signals.

@concept Grafana alerting
@plain
Grafana can evaluate alert rules itself against any data source, group them in folders, and route notifications through its own built-in Alertmanager.
@problem
Prometheus rules only cover Prometheus. You may need alerts on CloudWatch, SQL or Loki data too.
@does
- Rule = query + expression (threshold, reduce, math) + `for` + labels + annotations.
- Notification policies work like Alertmanager routing trees; contact points are the receivers.
- Rules can be provisioned as YAML or Terraform.
- Grafana can also manage an external Alertmanager.
@diagram flow
caption: Grafana-managed alert flow
nodes:
  - "Data source query|any backend|ext"
  - "Rule evaluation|threshold and for|app"
  - "Notification policy|route by labels|warn"
  - "Contact point|Slack, PagerDuty|ok"
@end

@concept Prometheus rules or Grafana rules
@plain
Where should alert rules live? Prometheus-evaluated rules run next to the data. Grafana-managed rules run in Grafana and can span sources.
@problem
Two systems evaluating alerts create duplicates and confusion about where to edit.
@does
- Prefer Prometheus or Mimir ruler rules for metrics: simple, tested with promtool, survive Grafana outages.
- Use Grafana-managed rules for non-Prometheus sources or multi-source conditions.
- Pick one Alertmanager path for routing so teams know where silences go.
@diagram cmp
caption: Where rules live
cards:
  - {h: "Prometheus rules", kind: ok, items: ["promtool tested", "Stay up if Grafana is down", "PrometheusRule CRD in Kubernetes"]}
  - {h: "Grafana rules", kind: info, items: ["Any data source", "UI plus provisioning", "Multi-source conditions"]}
@end

@concept Loki and LogQL
@plain
Loki stores logs indexed only by labels (like Prometheus), keeping the text compressed in object storage. LogQL queries it.
@problem
Full-text indexing of all logs is expensive. Many questions only need "logs of this pod, containing this word".
@does
- Stream selector: `{namespace="shop", app="checkout"}`.
- Line filters: `|= "error"`, `!= "health"`, `|~ "timeout|refused"`.
- Parsers: `| json`, `| logfmt` extract fields at query time.
- Metric queries turn logs into numbers: `rate({app="checkout"} |= "error" [5m])`.
@diagram flow
caption: A LogQL query
nodes:
  - "Stream selector|labels pick streams|info"
  - "Line filter|text match|warn"
  - "Parser|json extracts fields|app"
  - "Metric or lines|count or show|ok"
@h Examples
```text title="LogQL"
{namespace="shop", app="checkout"} |= "error" | json | status >= 500
sum by (pod) (rate({namespace="shop"} |= "timeout" [5m]))
```
@end

@concept Tempo and traces in Grafana
@plain
Tempo is a trace store that needs only an object store and a trace ID lookup. Grafana shows traces as waterfalls.
@problem
Trace backends that index every attribute are costly at scale.
@does
- Ingests OTLP, Jaeger and Zipkin.
- Search uses TraceQL, for example `{ resource.service.name = "checkout" && duration > 1s }`.
- Tempo can generate RED metrics from spans (metrics-generator) and write them to Prometheus.
@diagram flow
caption: Trace storage
nodes:
  - "Apps|OpenTelemetry SDK|app"
  - "Collector|batch and sample|env"
  - "Tempo|trace storage in S3|cp"
  - "Grafana|waterfall view|info"
@end

@concept Correlating metrics, logs and traces
@plain
Correlation means one click moves between signals for the same request or time window.
@problem
During an incident, copying IDs between tools wastes minutes.
@does
- Metrics to traces: exemplars on histograms.
- Traces to logs: Tempo data source setting "trace to logs" using labels or the trace ID.
- Logs to traces: a derived field on the Loki data source that extracts `trace_id` and links to Tempo.
- Requires services to put the trace ID in each log line.
@diagram seq
caption: Following one slow request
actors: ["Metric panel|Prometheus|cp", "Trace|Tempo|app", "Logs|Loki|env"]
steps:
  - "0>1: exemplar trace_id | req"
  - "1>2: trace to logs | req"
  - "2>1: lines with trace_id | resp"
@h Datasource provisioning
```yaml title="Loki with a derived field"
apiVersion: 1
datasources:
  - name: Loki
    type: loki
    url: http://loki:3100
    jsonData:
      derivedFields:
        - name: TraceID
          matcherRegex: '"trace_id":"(\w+)"'
          url: '$${__value.raw}'
          datasourceUid: tempo
```
@end

@concept Contact points and templates
@plain
A contact point is a destination (Slack, email, PagerDuty, webhook). Message templates control the text.
@problem
Default messages are verbose and lack the runbook link.
@does
- Provision contact points in YAML so secrets are not stored in the UI.
- Include `summary`, severity and `runbook_url` in templates.
- Test each contact point before relying on it.
@diagram flow
caption: Route to a destination
nodes:
  - "Alert|labels team and severity|bad"
  - "Policy|match team=payments|warn"
  - "Contact point|pagerduty-payments|ok"
@h Provisioned contact point
```yaml title="provisioning/alerting/contact.yaml" nocheck
apiVersion: 1
contactPoints:
  - orgId: 1
    name: slack-platform
    receivers:
      - uid: slack-platform
        type: slack
        settings:
          recipient: "#platform-alerts"
          url: ${SLACK_WEBHOOK_URL}
```
:::note
Field names for alerting provisioning differ between Grafana versions. Check the current docs.
:::
@end

@concept Grafana RBAC and teams
@plain
Organizations, teams, folders and roles (Viewer, Editor, Admin) limit who can read, edit or alert.
@problem
Everyone editing everything breaks dashboards and leaks sensitive data.
@does
- Use folder permissions per team; viewers are default.
- Sign in with SSO (OIDC); map IdP groups to roles.
- Service accounts with tokens replace API keys for automation.
@diagram layers
caption: Access model
layers:
  - {label: "Identity", nodes: ["SSO or OIDC|group claims|ext"]}
  - {label: "Grants", nodes: ["Team|payments|app", "Folder|Payments dashboards|env"]}
  - {label: "Role", nodes: ["Viewer|read|ok", "Editor|change|warn", "Admin|manage|bad"]}
@end
