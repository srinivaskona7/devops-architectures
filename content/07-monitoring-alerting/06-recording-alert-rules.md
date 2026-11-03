---
title: Recording rules and alert rules
minutes: 50
objectives:
  - Write recording rules with a clear naming convention
  - Write alert rules with for, labels and annotations
  - Test rules with promtool before deploying
---
Rules run inside Prometheus on a schedule. Recording rules make queries cheap; alert rules turn queries into notifications.

@concept Recording rules
@plain
A recording rule evaluates a PromQL expression on a schedule and stores the result as a new series.
@problem
Dashboards that compute a p99 over thousands of series on every refresh are slow and load Prometheus heavily.
@does
- The result is stored like any metric, so later queries read one cheap series.
- Rules are grouped; groups run on their own interval, rules in a group run in order.
- Use them for expensive aggregations, for SLI building blocks and for federation.
@diagram flow
caption: Expensive query run once, read many times
nodes:
  - "Raw series|thousands of pods|plain"
  - "Recording rule|evaluated every 30s|warn"
  - "New series|one per service|ok"
  - "Dashboards and alerts|fast reads|info"
@h Example
```yaml title="rules/recording.yml"
groups:
  - name: http_sli
    interval: 30s
    rules:
      - record: service:http_requests:rate5m
        expr: sum by (service) (rate(http_requests_total[5m]))
      - record: service:http_errors:ratio_rate5m
        expr: |
          sum by (service) (rate(http_requests_total{code=~"5.."}[5m]))
            / sum by (service) (rate(http_requests_total[5m]))
```
@end

@concept Naming recording rules
@plain
The convention is `level:metric:operations`, for example `service:http_requests:rate5m`.
@problem
When you see `job_cpu` in a graph you cannot tell if it is raw, summed or averaged.
@does
- `level` lists the labels kept (service, job, cluster).
- `metric` is the original metric name, with `_total` removed after `rate`.
- `operations` lists applied functions, newest first.
- Colons are reserved for recording rules, so exporters never use them.
@diagram layers
caption: Reading a recorded name
layers:
  - {label: "service:http_requests:rate5m", nodes: ["level|service labels kept|info", "metric|http_requests|app", "operations|rate5m|ok"]}
@check
What does the colon in a metric name tell you? || It is a recording rule output, not a raw scraped metric.
@end

@concept Alert rules
@plain
An alert rule is a PromQL expression plus a `for` duration. When the expression returns series for longer than `for`, one alert per series fires.
@problem
Alerting by eye does not scale and a single noisy sample should not wake someone.
@does
- States: **inactive**, **pending** (true but not yet for the full `for`), **firing**.
- `labels` are added to the alert and drive Alertmanager routing, such as `severity`.
- `annotations` hold human text: `summary`, `description`, `runbook_url`. Templates use `{{ $labels.x }}` and `{{ $value }}`.
- `keep_firing_for` (newer) holds an alert open to avoid flapping; check your version.
@diagram flow
caption: Alert state machine
nodes:
  - "Inactive|expression empty|plain"
  - "Pending|true, waiting for the for duration|warn"
  - "Firing|sent to Alertmanager|bad"
  - "Resolved|expression empty again|ok"
@h Example
```yaml title="rules/alerts.yml"
groups:
  - name: availability
    rules:
      - alert: HighErrorRatio
        expr: service:http_errors:ratio_rate5m > 0.05
        for: 10m
        labels:
          severity: page
          team: payments
        annotations:
          summary: "{{ $labels.service }} error ratio is {{ $value | humanizePercentage }}"
          runbook_url: https://runbooks.example.com/high-error-ratio
      - alert: TargetDown
        expr: up == 0
        for: 5m
        labels:
          severity: ticket
        annotations:
          summary: "{{ $labels.job }} on {{ $labels.instance }} is down"
```
@end

@concept The for clause and flapping
@plain
`for: 10m` means the condition must hold on every evaluation for ten minutes before the alert fires.
@problem
Brief spikes cause pages that nobody can act on.
@does
- Choose `for` from the cost of a delay: pages for severe user impact use 2 to 5 minutes, capacity warnings use 30 minutes or more.
- Too long a `for` delays real incidents. Too short creates noise.
- If the series vanishes for one evaluation, pending resets.
@diagram seq
caption: Pending then firing
actors: ["Rule group|evaluates every 30s|cp", "Alertmanager|receives alerts|warn"]
steps:
  - "note 0..0: expr true, pending"
  - "note 0..0: still true after 10m"
  - "0>1: POST alert firing | req"
  - "0>1: refresh every interval | req"
  - "0>1: resolved | resp"
@choose Choosing for
for 0 | very rare, e.g. data loss detected | anything that can spike
for 5m | page for user-visible errors | slow-moving trends
for 1h | capacity and trend tickets | urgent faults
@end

@concept Good alert expressions
@plain
Good alerts are about user pain, carry enough labels to route, and have an action the responder can take.
@problem
Alerts such as "CPU above 90 percent" teach people to ignore the pager.
@does
- Use ratios and rates, not raw counts.
- Add a minimum traffic guard so low traffic does not cause false ratios.
- Include a `runbook_url` and a clear `summary`.
- Group related alerts under the same labels, `team` and `severity`.
@diagram cmp
caption: Same intent, better rule
cards:
  - {h: "Weak", kind: bad, items: ["CPU above 90", "Single instance", "No runbook"]}
  - {h: "Strong", kind: ok, items: ["Error ratio above 5 percent", "Traffic above 1 request per second", "Runbook linked"]}
@h Traffic guard
```promql title="Ratio with a guard" nocheck
(
  service:http_errors:ratio_rate5m > 0.05
)
and on (service)
(
  service:http_requests:rate5m > 1
)
```
@end

@concept Testing rules with promtool
@plain
`promtool check rules` validates syntax. `promtool test rules` runs rules against fake input series and asserts alerts.
@problem
A typo in an alert is only discovered when the incident happens and nothing fires.
@does
- Unit tests define `input_series` using a compact notation and `alert_rule_test` expectations.
- Run them in CI before any change merges.
- Tests prove both the firing and not-firing cases.
@diagram flow
caption: CI for alerts
numbered: true
nodes:
  - "Edit rule|in git|plain"
  - "promtool check rules|syntax|info"
  - "promtool test rules|behaviour|app"
  - "Merge and deploy|reload Prometheus|ok"
@h Unit test
```yaml title="tests/alerts_test.yml"
rule_files:
  - ../rules/alerts.yml
evaluation_interval: 1m
tests:
  - interval: 1m
    input_series:
      - series: 'up{job="node", instance="a"}'
        values: '1 1 0 0 0 0 0 0'
    alert_rule_test:
      - eval_time: 8m
        alertname: TargetDown
        exp_alerts:
          - exp_labels:
              severity: ticket
              job: node
              instance: a
            exp_annotations:
              summary: "node on a is down"
```
```bash title="Run the checks" lab
promtool check rules rules/*.yml
promtool test rules tests/alerts_test.yml
```
@end

@concept Common rule mistakes
@plain
Most broken rules fall into a handful of patterns: wrong label match, missing `for`, stale series and rule groups that take longer than their interval.
@problem
Silent failures in monitoring are worse than loud ones.
@does
- Alert on a counter's raw value instead of `rate`.
- Use `==` on floats (compare with a range instead).
- Forget that `absent()` returns a series with labels only from equality matchers.
- Watch `prometheus_rule_group_last_duration_seconds`; if it exceeds the interval, evaluations are skipped.
@diagram flow
caption: Watch the watchers
nodes:
  - "Rule group duration|prometheus_rule_group_last_duration_seconds|info"
  - "Compare to interval|longer means missed evaluations|warn"
  - "Fix|record sub-expressions|ok"
@h Meta alerts
```yaml title="rules/meta.yml"
groups:
  - name: meta
    rules:
      - alert: Watchdog
        expr: vector(1)
        labels:
          severity: none
        annotations:
          summary: Always firing. If this stops arriving, the alerting pipeline is broken.
      - alert: RuleGroupSlow
        expr: prometheus_rule_group_last_duration_seconds > prometheus_rule_group_interval_seconds
        for: 10m
        labels:
          severity: ticket
```
:::tip
The Watchdog pattern is a dead man's switch: send it to an external service that pages you when it stops arriving.
:::
@end
