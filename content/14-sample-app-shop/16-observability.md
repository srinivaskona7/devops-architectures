---
title: Observability - metrics, SLOs, alerts, dashboards and logs
minutes: 70
objectives:
  - Scrape the Shop with Prometheus and write recording and alert rules
  - Define a checkout SLO and derive multi-window burn-rate alerts with correct arithmetic
  - Build a Grafana dashboard outline and ship JSON logs to Loki or Elasticsearch
---
The Monitoring folder teaches Prometheus, Alertmanager and Grafana; the ELK folder teaches logging. The Shop services already expose `/metrics` and write JSON logs (see the application files). Chart versions change often; for example the kube-prometheus-stack chart was `{{v.kube_prometheus_stack_chart}}` and Prometheus `{{v.prometheus}}` when this was written. Check the current docs.

@concept What to observe - the four signals
@plain
For every service watch latency, traffic, errors and saturation. For the business also watch orders per minute and payment outcomes.
@problem
Dashboards with 80 graphs hide the one that matters. A few signals per service answer "is it broken and where".
@does
- Latency: `http_request_duration_seconds` histogram, p95 per route.
- Traffic: `rate(http_requests_total[5m])`.
- Errors: share of 5xx responses.
- Saturation: CPU versus request, memory versus limit, DB connections, Redis memory.
- Business: orders created, paid, failed; payment PENDING age (a late webhook shows as a growing pending count).
@diagram layers
caption: Signals by layer
layers:
  - {label: "Business", nodes: ["Orders per minute|rate|ok", "Payment success ratio|SUCCESS over all|ok", "Pending older than 15 min|reconcile|warn"]}
  - {label: "Service (RED)", nodes: ["Rate|requests per second|info", "Errors|5xx share|bad", "Duration|p95 and p99|info"]}
  - {label: "Resources (USE)", nodes: ["CPU and memory|vs requests|plain", "DB connections|pool use|plain", "Node pressure|disk, memory|plain"]}
@end

@concept Scraping with ServiceMonitor
@plain
A ServiceMonitor tells the Prometheus Operator which Services to scrape and on which port.
@problem
Static scrape configs in a Prometheus ConfigMap are hand-edited and forgotten when a service is added.
@does
- One ServiceMonitor selects all Services with the label `app.kubernetes.io/part-of: shop` and scrapes port `http` at `/metrics` every 30 seconds.
- Needs the CRDs from kube-prometheus-stack (Helm) or the Operator; the `monitoring` namespace is allowed in the NetworkPolicies.
- Size check: 5 services x 3 pods x about 120 series per pod = 1,800 series, which is very small for Prometheus.
- Hold cardinality down: route templates as labels, never user ids or raw paths (see the middleware).
@diagram flow
caption: Scrape path
nodes:
  - "Service pods|/metrics|app"
  - "ServiceMonitor|selects Services|info"
  - "Prometheus|30 s scrape|cp"
  - "Grafana and Alertmanager|query|ok"
@h deploy/base/servicemonitor.yaml
```yaml title="deploy/base/servicemonitor.yaml"
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: shop
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app.kubernetes.io/part-of: shop
  namespaceSelector:
    matchNames: [shop]
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```
:::note
The base kustomization adds the label `app.kubernetes.io/part-of: shop` to Services with `includeSelectors: false`. Add this file to its resource list and confirm with `kubectl get svc -n shop --show-labels`.
:::
@end

@concept Recording rules for the checkout SLI
@plain
A recording rule stores the result of a query as a new metric, so dashboards and alerts do not recompute heavy expressions.
@problem
Burn-rate alerts evaluate the same ratio over several windows every minute; computing it from raw series each time is slow and inconsistent.
@does
- The checkout SLI is the share of `POST /orders` requests that are not server errors or slow. Here: good = status not 5xx, total = all.
- Rules `shop:checkout_requests:rate5m`, `...:rate1h` and so on give the building blocks. `shop:checkout_error_ratio:rate5m` is errors over total.
- Naming convention `level:metric:operations` makes rules easy to find.
- The `path` label value is the route template `/orders` (see the middleware).
@diagram flow
caption: From raw counters to a ratio
nodes:
  - "http_requests_total|raw counter|plain"
  - "rate over window|5m, 1h, 6h|info"
  - "error ratio|5xx over all|warn"
  - "burn rate|ratio over budget|bad"
@h Rules file part 1
```yaml title="deploy/base/prometheusrule-recording.yaml"
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: shop-recording
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: shop.checkout.sli
      interval: 30s
      rules:
        - record: shop:checkout_error_ratio:rate5m
          expr: |
            sum(rate(http_requests_total{service="orders",path="/orders",method="POST",status=~"5.."}[5m]))
            / sum(rate(http_requests_total{service="orders",path="/orders",method="POST"}[5m]))
        - record: shop:checkout_error_ratio:rate30m
          expr: |
            sum(rate(http_requests_total{service="orders",path="/orders",method="POST",status=~"5.."}[30m]))
            / sum(rate(http_requests_total{service="orders",path="/orders",method="POST"}[30m]))
        - record: shop:checkout_error_ratio:rate1h
          expr: |
            sum(rate(http_requests_total{service="orders",path="/orders",method="POST",status=~"5.."}[1h]))
            / sum(rate(http_requests_total{service="orders",path="/orders",method="POST"}[1h]))
        - record: shop:checkout_error_ratio:rate6h
          expr: |
            sum(rate(http_requests_total{service="orders",path="/orders",method="POST",status=~"5.."}[6h]))
            / sum(rate(http_requests_total{service="orders",path="/orders",method="POST"}[6h]))
        - record: shop:checkout_error_ratio:rate3d
          expr: |
            sum(rate(http_requests_total{service="orders",path="/orders",method="POST",status=~"5.."}[3d]))
            / sum(rate(http_requests_total{service="orders",path="/orders",method="POST"}[3d]))
```
@end

@concept The checkout SLO and its error budget
@plain
An SLO is a target for a user-visible measure over a period. The error budget is the amount of failure the target still allows.
@problem
"As reliable as possible" has no end and ignores cost. A number lets the team decide between shipping features and fixing reliability.
@does
- SLO: 99.9 percent of checkout requests succeed over 30 days.
- Budget fraction: 1 - 0.999 = 0.001, which is 0.1 percent of requests.
- In time: 30 days x 24 hours x 60 minutes = 43,200 minutes; 43,200 x 0.001 = 43.2 minutes of total outage equivalent.
- In requests: at 20,000 orders a day plus retries, 600,000 order attempts a month; budget = 600 failed orders (600,000 x 0.001).
- Policy: if more than 50 percent of the budget is gone, pause risky releases; if gone, only reliability work ships.
@diagram flow
caption: From target to budget
nodes:
  - "SLO 99.9 percent|30 days|info"
  - "Budget 0.1 percent|1 minus 0.999|warn"
  - "43.2 minutes|of full outage|bad"
  - "600 failed orders|of 600,000|bad"
@h Check the arithmetic
```python title="slo_budget.py" lab
slo = 0.999
days = 30
orders_per_day = 20_000

budget_fraction = 1 - slo
minutes = days * 24 * 60
print("budget fraction:", round(budget_fraction, 6))
print("budget minutes:", round(minutes * budget_fraction, 1))
total = orders_per_day * days
print("failed orders allowed:", round(total * budget_fraction))

for burn, hours in ((14.4, 1), (6, 6), (3, 24), (1, 72)):
    pct = burn * hours / (days * 24) * 100
    print(f"burn {burn:>4} for {hours:>2} h uses {pct:.1f}% of budget, error ratio {burn * budget_fraction:.4f}")
```
@check
If checkout fails 100 percent for 10 minutes, how much of a 43.2 minute budget is used? || 10 / 43.2 = about 23 percent.
@end

@concept Multi-window burn-rate alerts
@plain
A burn rate is how fast the budget is being spent compared with the pace that would exactly use it up in 30 days. Burn rate 1 means just on target.
@problem
An alert on "error rate above 0.1 percent for 5 minutes" fires on harmless blips and misses slow leaks. Multi-window burn-rate alerts page only when a meaningful amount of budget is at stake.
@does
- Page (fast): burn rate 14.4 over 1 hour and over 5 minutes. 14.4 x 1 hour of 720 hours = 2 percent of the budget in one hour. Error ratio threshold 14.4 x 0.001 = 0.0144.
- Page (slower): burn rate 6 over 6 hours and 30 minutes: 5 percent of the budget. Threshold 0.006.
- Ticket: burn rate 3 over 24 hours (10 percent) and burn rate 1 over 3 days (10 percent). Thresholds 0.003 and 0.001.
- The short window must also exceed the threshold, so the alert resets quickly after a fix.
- This is the pattern from the Google SRE workbook; the Monitoring folder shows the general version.
@diagram cmp
caption: Four alerts for one SLO
cards:
  - {h: "Page 1 hour", kind: bad, items: ["Burn 14.4 over 1 h and 5 m", "2 percent of budget", "Ratio above 0.0144"]}
  - {h: "Page 6 hours", kind: bad, items: ["Burn 6 over 6 h and 30 m", "5 percent of budget", "Ratio above 0.006"]}
  - {h: "Ticket 1 day", kind: warn, items: ["Burn 3 over 24 h", "10 percent of budget", "Ratio above 0.003"]}
  - {h: "Ticket 3 days", kind: info, items: ["Burn 1 over 3 d", "10 percent of budget", "Ratio above 0.001"]}
@h Alert rules
```yaml title="deploy/base/prometheusrule-alerts.yaml"
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: shop-alerts
  labels:
    release: kube-prometheus-stack
spec:
  groups:
    - name: shop.checkout.burn
      rules:
        - alert: CheckoutBudgetBurnFast
          expr: |
            shop:checkout_error_ratio:rate1h > (14.4 * 0.001)
            and shop:checkout_error_ratio:rate5m > (14.4 * 0.001)
          for: 2m
          labels: {severity: page, slo: checkout}
          annotations:
            summary: Checkout is burning the error budget at 14.4x
            runbook_url: https://github.com/acme/shop/blob/main/docs/runbooks/checkout-errors.md
        - alert: CheckoutBudgetBurnSlow
          expr: |
            shop:checkout_error_ratio:rate6h > (6 * 0.001)
            and shop:checkout_error_ratio:rate30m > (6 * 0.001)
          for: 15m
          labels: {severity: page, slo: checkout}
          annotations:
            summary: Checkout is burning the error budget at 6x
            runbook_url: https://github.com/acme/shop/blob/main/docs/runbooks/checkout-errors.md
        - alert: CheckoutBudgetBurnTicket
          expr: |
            shop:checkout_error_ratio:rate3d > (1 * 0.001)
            and shop:checkout_error_ratio:rate6h > (1 * 0.001)
          for: 1h
          labels: {severity: ticket, slo: checkout}
          annotations:
            summary: Checkout error budget is draining slowly
    - name: shop.service
      rules:
        - alert: ShopPodCrashLooping
          expr: increase(kube_pod_container_status_restarts_total{namespace="shop"}[15m]) > 3
          for: 5m
          labels: {severity: ticket}
          annotations:
            summary: A Shop container restarted more than 3 times in 15 minutes
        - alert: ShopLatencyHigh
          expr: |
            histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{service="orders",path="/orders"}[5m]))) > 0.8
          for: 10m
          labels: {severity: ticket}
          annotations:
            summary: Checkout p95 latency above 800 ms
        - alert: PaymentsPendingStuck
          expr: shop_payments_pending_older_than_15m > 0
          for: 10m
          labels: {severity: ticket}
          annotations:
            summary: Payments are pending for more than 15 minutes
```
:::note
`shop_payments_pending_older_than_15m` is a custom gauge. Add a small background task or CronJob in payments that counts old PENDING rows and exposes the gauge; the runbook uses the same query.
:::
@end

@concept Alertmanager routing and quality of alerts
@plain
Alertmanager groups alerts, silences duplicates and sends pages to the on-call tool and tickets to a chat channel or tracker.
@problem
Alert fatigue: 200 notifications a night teach the team to ignore all of them, including the real one.
@does
- Route by `severity`: `page` goes to the paging service; `ticket` goes to a channel with no wake-up.
- `group_by: [alertname, slo]` and `group_wait: 30s` turn a storm into one notification.
- Inhibit rules mute symptoms when a cause alert is firing (for example a node down mutes pod alerts on that node).
- Every page alert has a runbook link and is actionable within minutes; if nobody acts on an alert for two weeks, delete or downgrade it.
- Review alerts monthly: pages per on-call shift should stay low (a common target is under two per shift).
@diagram flow
caption: From rule to human
nodes:
  - "Prometheus rule|fires|cp"
  - "Alertmanager|group and route|info"
  - "Page|on-call phone|bad"
  - "Ticket|channel|warn"
@h alertmanager config (as in kube-prometheus-stack values)
```yaml title="platform/alertmanager-config.yaml"
route:
  receiver: team-channel
  group_by: [alertname, slo]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - matchers: ['severity="page"']
      receiver: oncall-pager
      repeat_interval: 1h
inhibit_rules:
  - source_matchers: ['alertname="KubeNodeNotReady"']
    target_matchers: ['alertname="ShopPodCrashLooping"']
    equal: [node]
receivers:
  - name: team-channel
    webhook_configs:
      - url: https://chat.example.com/hooks/shop-alerts
  - name: oncall-pager
    webhook_configs:
      - url: https://pager.example.com/v1/events
```
@end

@concept Grafana dashboard outline
@plain
One dashboard per audience: an overview for everyone, a checkout SLO dashboard for the team, a service detail dashboard for debugging.
@problem
Click-built dashboards are lost with the Grafana database and differ between environments.
@does
- Store dashboards as JSON in Git, loaded by a sidecar from ConfigMaps labelled `grafana_dashboard: "1"` (kube-prometheus-stack does this).
- Top row: SLO status stat panels (budget left, current burn rate), then request rate, error ratio, p95 per service, then saturation, then logs panel from Loki.
- Use template variables for `env` and `service`, so one dashboard works everywhere.
- The JSON below is an outline: two panels and one variable. Export your real dashboard from Grafana and commit it.
@diagram layers
caption: Overview dashboard rows
layers:
  - {label: "Row 1 SLO", nodes: ["Budget left %|stat|ok", "Burn rate 1h|stat|warn", "Checkout success|stat|ok"]}
  - {label: "Row 2 RED", nodes: ["Requests per second|timeseries|info", "Error ratio|timeseries|bad", "p95 latency|timeseries|info"]}
  - {label: "Row 3 resources", nodes: ["CPU vs request|timeseries|plain", "Memory vs limit|timeseries|plain", "Pods ready|stat|plain"]}
@h dashboards/shop-overview.json
```json title="dashboards/shop-overview.json"
{
  "title": "Shop overview",
  "uid": "shop-overview",
  "schemaVersion": 39,
  "refresh": "30s",
  "templating": {
    "list": [
      {"name": "service", "type": "query", "query": "label_values(http_requests_total, service)", "includeAll": true}
    ]
  },
  "panels": [
    {
      "id": 1,
      "type": "stat",
      "title": "Checkout 30 day error budget left",
      "gridPos": {"h": 4, "w": 6, "x": 0, "y": 0},
      "targets": [
        {"expr": "1 - (shop:checkout_error_ratio:rate3d / 0.001)", "legendFormat": "budget left"}
      ],
      "fieldConfig": {"defaults": {"unit": "percentunit", "min": 0, "max": 1}}
    },
    {
      "id": 2,
      "type": "timeseries",
      "title": "p95 latency by service",
      "gridPos": {"h": 8, "w": 12, "x": 6, "y": 0},
      "targets": [
        {
          "expr": "histogram_quantile(0.95, sum by (le, service) (rate(http_request_duration_seconds_bucket{service=~\"$service\"}[5m])))",
          "legendFormat": "{{service}}"
        }
      ],
      "fieldConfig": {"defaults": {"unit": "s"}}
    }
  ]
}
```
:::note
The budget-left panel uses the 3 day ratio as an approximation. For an exact 30 day figure add a 30 day recording rule (it needs 30 days of retention in Prometheus or a long-term store such as Thanos or Mimir).
:::
@end

@concept Logs - Loki or Elasticsearch
@plain
Collect each container's stdout JSON and make it searchable by field. Loki is cheap and good next to metrics; Elasticsearch is stronger for analytics.
@problem
`kubectl logs` only shows live pods. After a pod is replaced or a node is drained, the evidence is gone.
@does
- A DaemonSet agent (Promtail, Grafana Alloy or Fluent Bit; check the current Loki docs for which is recommended) reads `/var/log/pods`, adds labels `namespace`, `app`, `pod`, and ships to Loki.
- Index only low-cardinality labels (`app`, `namespace`); keep `order_id` and `status` inside the JSON line and filter with LogQL `| json | status >= 500`.
- Retention 14 days in dev and 30 days in prod. Volume estimate: 5 services x 3 pods x about 2 MB per hour x 24 hours = 720 MB per day, so even 30 days is about 21.6 GB, which is small.
- The ELK folder shows the Elasticsearch route with Filebeat; the same JSON fields work for both.
@diagram flow
caption: Log pipeline
nodes:
  - "App stdout JSON|per request|app"
  - "Node agent|labels and ships|info"
  - "Loki|object storage|cp"
  - "Grafana Explore|LogQL|ok"
@h Useful queries
```text title="LogQL examples" nocheck
{namespace="shop", app="orders"} | json | status >= 500
{namespace="shop", app="payments"} |= "collect" | json | line_format "{{.msg}} order={{.order_id}}"
sum by (app) (rate({namespace="shop"} | json | status >= 500 [5m]))
```
```bash title="Estimate daily log volume" lab
python3 - <<'PY'
services, pods, mb_per_hour = 5, 3, 2
daily_mb = services * pods * mb_per_hour * 24
print("daily MB:", daily_mb, "= GB:", round(daily_mb / 1000, 2))
PY
```
@end
