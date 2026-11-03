---
title: SRE principles, SLIs and SLOs
minutes: 45
objectives:
  - Explain how site reliability engineering treats operations as a software problem
  - Choose SLIs, set SLOs and compute an error budget
  - Use burn rate alerts instead of raw threshold alerts
---
**Site Reliability Engineering (SRE)** began at Google as a way to run large systems with software engineers. Its central idea is that reliability is a feature with a measurable target, and that the target is not 100 percent.

@concept SRE and DevOps
@plain
DevOps is a set of cultural ideas; SRE is a concrete way to apply them to reliability, with specific practices such as SLOs, error budgets and toil limits. Google describes it as "class SRE implements interface DevOps".
@problem
"Make it reliable" is vague. Without a target, teams either over-invest in reliability that users do not notice, or ship fast and break trust.
@does
- Engineers spend at most about 50 percent of time on operational work; the rest goes to automation and engineering that reduce future toil.
- Reliability is defined from the user's point of view and measured.
- A shared **error budget** settles the argument between feature speed and stability.
- Postmortems are blameless; incidents are managed by clear roles.
@diagram cmp
caption: DevOps and SRE
cards:
  - {h: "DevOps", kind: info, items: ["Culture and principles", "Break silos, automate delivery", "Flexible about how"]}
  - {h: "SRE", kind: ok, items: ["Specific practices", "SLOs, error budgets, toil caps", "Engineering applied to operations"]}
@h Reliability is not 100 percent
```python title="Why 100 percent is the wrong target" lab
for target in (0.99, 0.999, 0.9999, 0.99999):
    minutes = (1 - target) * 30 * 24 * 60
    print(f"{target * 100:g}% -> {minutes:8.1f} minutes of allowed downtime per 30 days")
```
@check
Why not aim for 100 percent availability? || It is unreachable (users' own networks fail first), and each extra nine costs far more while slowing feature delivery.
@end

@concept SLIs - what to measure
@plain
A **service level indicator (SLI)** is a measurement of one aspect of service quality, expressed as the proportion of good events out of valid events.
@problem
CPU and memory graphs show machine health, not whether users are happy. A server can be healthy and the checkout broken.
@does
- Form: `good events / valid events`, over a time window, giving a number from 0 to 100 percent.
- Common SLIs: **availability** (non-5xx responses), **latency** (requests faster than a threshold), **correctness**, **freshness** (data updated recently), **throughput** for pipelines.
- Measure close to the user: load balancer or ingress metrics, or synthetic checks.
- Pick few SLIs per user journey (checkout, search), not hundreds.
@diagram flow
caption: From request to SLI
nodes:
  - "Request|user action|ext"
  - "Good or bad|status and latency|info"
  - "Ratio|good / valid|app"
  - "SLI|99.93 percent over 30 days|ok"
@h Prometheus queries
```text title="Availability and latency SLIs in PromQL"
# availability: share of non-5xx requests over 30 days
sum(rate(http_requests_total{job="api",code!~"5.."}[30d]))
/ sum(rate(http_requests_total{job="api"}[30d]))

# latency: share of requests faster than 400 ms
sum(rate(http_request_duration_seconds_bucket{job="api",le="0.4"}[30d]))
/ sum(rate(http_request_duration_seconds_count{job="api"}[30d]))
```
@check
Why is a ratio of good to valid events preferred? || It is easy to read, ranges from 0 to 100 percent and works for any kind of event.
@end

@concept SLOs and SLAs
@plain
A **service level objective (SLO)** is the target for an SLI over a window, for example 99.9 percent of requests succeed over 30 days. An **SLA** is a contract with penalties, usually looser than the internal SLO.
@problem
Without an agreed target nobody knows when reliability is good enough, so every outage becomes a debate.
@does
- Set SLOs from user needs and current performance, then tighten gradually. A good SLO is one that users start to notice when missed.
- The SLO should be stricter than the SLA so you get a warning before paying penalties.
- Use rolling windows (28 or 30 days) so one bad day fades.
- Review quarterly; share on a dashboard that product and engineering both read.
@diagram layers
caption: Relationship of terms
layers:
  - {label: "Contract", nodes: ["SLA|99.5 percent, refunds if missed|bad"]}
  - {label: "Internal goal", nodes: ["SLO|99.9 percent|warn"]}
  - {label: "Measurement", nodes: ["SLI|good / valid events|ok"]}
@h Example SLO file
```yaml title="slo.yaml"
service: checkout-api
slos:
  - name: availability
    sli: non-5xx responses / all responses
    objective: 99.9
    window: 30d
  - name: latency
    sli: responses under 400ms / all responses
    objective: 95
    window: 30d
```
@check
Why should the SLO be stricter than the SLA? || It triggers action before the contractual penalty is reached.
@end

@concept Error budgets
@plain
The **error budget** is the allowed amount of unreliability: 100 percent minus the SLO. A 99.9 percent SLO gives a 0.1 percent budget, about 43 minutes in 30 days.
@problem
Product wants to ship fast, operations wants stability. With no shared number, the loudest voice wins.
@does
- While budget remains, ship features and take risks. When it is spent, slow down and prioritise reliability work.
- Convert to events: with 10 million requests per month a 99.9 percent SLO allows 10 000 failures.
- Agree the policy in advance with product leadership: for example freeze non-urgent releases when the budget is exhausted.
- Budget also funds experiments such as chaos tests and risky migrations.
@diagram flow
caption: Using the budget
nodes:
  - "SLO 99.9 percent|budget 0.1 percent|info"
  - "Budget left|ship features|ok"
  - "Budget low|slow down, reduce risk|warn"
  - "Budget spent|freeze, fix reliability|bad"
@h Compute the budget
```python title="Error budget in minutes and requests" lab
slo = 0.999
window_min = 30 * 24 * 60
budget_min = (1 - slo) * window_min
requests = 10_000_000
print(f"budget {budget_min:.1f} minutes, or {int(requests * (1 - slo))} failed requests")
used = 12_500
print(f"used {used / (requests * (1 - slo)):.0%} of the budget")
```
@check
How many minutes of full outage does 99.9 percent allow in 30 days? || About 43.2 minutes.
@end

@concept Burn rate alerting
@plain
Burn rate says how fast you are consuming the error budget. A burn rate of 1 uses the whole budget exactly at the end of the window; 10 uses it ten times faster.
@problem
Alerting on "error rate above 1 percent for 5 minutes" is noisy for small blips and slow for long, slow burns. Neither tells you how much it matters to the SLO.
@does
- Alert on fast burn (page) and slow burn (ticket) using multiple windows.
- The Google SRE workbook suggests, for a 30 day window: burn rate 14.4 over 1 hour (and 5 minutes) pages, because it spends 2 percent of the budget; burn rate 6 over 6 hours pages; burn rate 1 over 3 days opens a ticket.
- Two windows (long and short) reduce false alarms and make alerts reset quickly.
- Each page must be actionable and linked to a runbook.
@diagram cmp
caption: Multi-window burn rate alerts for a 30 day SLO
cards:
  - {h: "Page fast burn", kind: bad, items: ["Rate 14.4 over 1h and 5m", "2 percent of budget in 1 hour"]}
  - {h: "Page slower burn", kind: warn, items: ["Rate 6 over 6h and 30m", "5 percent of budget in 6 hours"]}
  - {h: "Ticket", kind: info, items: ["Rate 1 over 3d and 6h", "10 percent of budget in 3 days"]}
@h Compute and alert
```python title="Burn rate arithmetic" lab
slo = 0.999
budget = 1 - slo
observed_error_rate = 0.0144
burn = observed_error_rate / budget
print(f"burn rate {burn:.1f}x; a 30 day budget is gone in {30 / burn:.1f} days")
print("fraction of 30d budget used in 1h at rate 14.4:", round(14.4 * 1 / (30 * 24), 3))
```
```yaml title="Prometheus alert rule" nocheck
groups:
  - name: checkout-slo
    rules:
      - alert: CheckoutFastBurn
        expr: |
          (sum(rate(http_requests_total{job="checkout",code=~"5.."}[1h])) / sum(rate(http_requests_total{job="checkout"}[1h])) > 14.4 * 0.001)
          and
          (sum(rate(http_requests_total{job="checkout",code=~"5.."}[5m])) / sum(rate(http_requests_total{job="checkout"}[5m])) > 14.4 * 0.001)
        labels: {severity: page}
        annotations: {runbook: "https://runbooks.example.com/checkout-fast-burn"}
```
@check
What does burn rate 1 mean? || Errors are using the budget at exactly the pace that exhausts it at the end of the window.
@end

@concept Choosing good SLOs
@plain
SLOs should reflect what users care about, be achievable and be few. Starting rough and improving beats waiting for the perfect SLO.
@problem
Teams pick SLOs that are copied, never reviewed, or so tight that the budget is always empty and they are ignored.
@does
- Start from user journeys; ask "what makes the user unhappy".
- Look at the past 4 to 12 weeks of data to set a realistic first target, then adjust.
- Dependencies cap you: a service cannot be more available than the product of the services it hard-depends on.
- Different tiers for different services: critical (99.95 percent), standard (99.9 percent), best effort.
@diagram flow
caption: Setting an SLO
numbered: true
nodes:
  - "User journey|what hurts users|info"
  - "Pick SLI|measurable proxy|app"
  - "Check history|what is realistic|warn"
  - "Set and review|quarterly|ok"
@h Composite availability
```python title="Serial dependencies multiply" lab
deps = {"api": 0.9995, "database": 0.9995, "payments": 0.999, "auth": 0.9995}
total = 1.0
for v in deps.values():
    total *= v
print(f"best possible availability {total:.4%}")
print("so a 99.99% SLO is impossible with these dependencies unless you add redundancy or degrade gracefully")
```
@check
Why can a service not exceed the availability of its hard dependencies? || If any hard dependency fails the service fails too, so availabilities multiply.
@end

@concept Observability that supports SLOs
@plain
Metrics, logs and traces let you measure SLIs and diagnose why they drop. Observability is the ability to ask new questions of a running system without deploying new code.
@problem
Dashboards of CPU do not explain why users see errors. Missing traces make cross-service problems slow to find.
@does
- Metrics for SLIs and alerts (RED: rate, errors, duration; USE for resources).
- Logs for details of individual events; traces for request paths across services.
- OpenTelemetry is the vendor-neutral standard for emitting all three.
- Link alerts to dashboards and runbooks; keep cardinality of labels under control.
@diagram layers
caption: Three signals
layers:
  - {label: "Signals", nodes: ["Metrics|numbers over time|app", "Logs|events with detail|app", "Traces|path of a request|app"]}
  - {label: "Collection", nodes: ["OpenTelemetry Collector|vendor-neutral|cp"]}
  - {label: "Use", nodes: ["SLO dashboards|ok", "Alerts|ok", "Debugging|ok"]}
@h Instrumentation sketch
```python title="Counting good and total events" lab
from collections import Counter
requests = Counter()
def handle(status, ms):
    requests["total"] += 1
    if status < 500 and ms < 400:
        requests["good"] += 1
for s, m in [(200, 120), (200, 380), (500, 90), (200, 900), (201, 150)]:
    handle(s, m)
print(f"SLI {requests['good'] / requests['total']:.0%} good of {requests['total']}")
```
@check
Which signal shows the path of one request through many services? || Traces.
@end
