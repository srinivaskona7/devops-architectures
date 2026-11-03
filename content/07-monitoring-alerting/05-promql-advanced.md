---
title: PromQL in depth
minutes: 55
objectives:
  - Compute percentiles with histogram_quantile and understand its limits
  - Join series with on, ignoring and group_left
  - Forecast and detect missing data with predict_linear and absent
---
These patterns appear in nearly every real alert and dashboard.

@concept Histograms and buckets
@plain
A histogram metric exposes cumulative counters per bucket: `x_bucket{le="0.5"}` counts observations at or below 0.5 seconds. It also exposes `x_sum` and `x_count`.
@problem
Averages hide tail latency. A p99 of 3 seconds can sit beside an average of 100 ms.
@does
- Buckets are cumulative, so `le="+Inf"` equals `_count`.
- Average latency is `rate(x_sum) / rate(x_count)`.
- Percentiles are computed from bucket counts and are only as precise as bucket boundaries.
- Native histograms (newer, sparse, exponential) remove fixed buckets; check the current docs for support in your version.
@diagram layers
caption: Series produced by one histogram
layers:
  - {label: "Buckets", nodes: ["le 0.1|cumulative count|info", "le 0.5|cumulative count|info", "le 1|cumulative count|info", "le +Inf|equals count|ok"]}
  - {label: "Totals", nodes: ["_sum|sum of values|app", "_count|number of observations|app"]}
@h Average latency
```promql title="Mean latency" nocheck
sum(rate(http_request_duration_seconds_sum[5m]))
  / sum(rate(http_request_duration_seconds_count[5m]))
```
@end

@concept histogram_quantile
@plain
`histogram_quantile(0.99, ...)` estimates the 99th percentile from bucket rates, assuming values spread evenly inside a bucket.
@problem
You need fleet-wide percentiles which cannot be averaged from per-pod percentiles.
@does
- Input must be `rate()` of buckets, aggregated with `sum by (le, ...)`. Keep `le`.
- The estimate is wrong if bucket boundaries are far from your target. Put a boundary at your SLO value.
- Result is NaN if there were no observations.
@diagram flow
caption: Order of operations matters
numbered: true
nodes:
  - "rate on buckets|per series per second|info"
  - "sum by le and service|combine pods|warn"
  - "histogram_quantile|0.99|ok"
@h Examples
```promql title="p99 by service" nocheck
histogram_quantile(
  0.99,
  sum by (le, service) (rate(http_request_duration_seconds_bucket[5m]))
)
```
Share of requests faster than 300 ms, usable as an SLI.
```promql title="Latency SLI" nocheck
sum(rate(http_request_duration_seconds_bucket{le="0.3"}[5m]))
  / sum(rate(http_request_duration_seconds_count[5m]))
```
@check
Why must le stay in the by clause? || histogram_quantile needs the bucket boundaries to interpolate; without le it cannot compute the percentile.
@end

@concept Vector matching with on and ignoring
@plain
When two vectors are combined, Prometheus pairs series with exactly the same labels. `on(a,b)` pairs by only those labels, `ignoring(c)` pairs by all but those.
@problem
The numerator and denominator often have different extra labels, so a plain division returns nothing.
@does
- Use `on()` with the shared labels, such as `on(namespace, pod)`.
- One-to-one matching is default. If one side has many matches for one on the other, you must say so with `group_left` or `group_right`.
- Mismatch errors say "many-to-many matching not allowed".
@diagram flow
caption: Pairing two vectors
nodes:
  - "Left vector|labels namespace, pod, container|app"
  - "on(namespace, pod)|pairing keys|warn"
  - "Right vector|labels namespace, pod|app"
  - "Result|one per matched pair|ok"
@h Example
```promql title="Memory usage as a share of the limit" nocheck
sum by (namespace, pod) (container_memory_working_set_bytes{container!=""})
  /
sum by (namespace, pod) (kube_pod_container_resource_limits{resource="memory"})
```
@end

@concept group_left and info metrics
@plain
`group_left` lets the many side keep labels copied from the one side. It is used with "info" metrics such as `kube_pod_info` or `kube_node_labels` whose value is always 1 and whose labels carry metadata.
@problem
CPU metrics have a pod name but not the owning team or the node's instance type. You need to attach that information.
@does
- Multiply by an info metric (value 1) so values do not change.
- `group_left(label)` copies named labels to the result.
- Common pattern: attach `team` from a pod label metric.
@diagram flow
caption: Enriching a metric with metadata
nodes:
  - "container CPU|has pod only|app"
  - "x on(pod) group_left(team)|multiply by 1|warn"
  - "kube_pod_labels|has team label, value 1|env"
  - "CPU with team|ready for grouping|ok"
@h Example
```promql title="CPU by team" nocheck
sum by (team) (
  sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{container!=""}[5m]))
  * on (namespace, pod) group_left (label_team)
  kube_pod_labels
)
```
:::note
`kube_pod_labels` carries pod labels only when allowed in the kube-state-metrics settings (`--metric-labels-allowlist`). Check the current docs for your version.
:::
@end

@concept Forecasting and missing data
@plain
`predict_linear(x[6h], 4*3600)` extrapolates a gauge four hours ahead. `absent()` returns 1 when a selector matches nothing. `absent_over_time` does the same across a window.
@problem
A full disk can be predicted and a vanished metric is a silent failure.
@does
- Disk-full prediction alerts give time to react before an outage.
- Use gauges only. A window of 6h smooths daily cycles.
- `absent()` only works for selectors with equality matchers.
@diagram flow
caption: Predict the future from the slope
nodes:
  - "Free bytes now|20 GB|info"
  - "Slope over 6h|minus 6 GB per hour|warn"
  - "In 4 hours|about minus 4 GB, negative means full|bad"
@h Example
```promql title="Disk full within four hours" nocheck
predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}[6h], 4*3600) < 0
```
@check
With 20 GB free and a fall of 6 GB per hour, when does the disk fill? || In about 3.3 hours (20 divided by 6), inside the four hour horizon, so the alert fires.
@end

@concept Subqueries and the resolution of time
@plain
A subquery `expr[1h:1m]` runs an instant expression every minute over one hour, producing a range vector that range functions can use.
@problem
You cannot apply `max_over_time` to the result of `rate()` directly, because `rate()` returns an instant vector.
@does
- Syntax is `[range:step]`; omit step for the global evaluation interval.
- Heavy: every step recalculates the inner query. Prefer a recording rule for repeated use.
- Typical use: peak rate over the last day.
@diagram flow
caption: Subquery turns an instant result into a range
nodes:
  - "rate over 5m|instant vector|info"
  - "[1d:5m]|evaluate every 5 minutes|warn"
  - "max_over_time|peak of the day|ok"
@h Example
```promql title="Peak request rate in 24h" nocheck
max_over_time(sum(rate(http_requests_total[5m]))[1d:5m])
```
@end

@concept Useful query patterns
@plain
A short list of queries you will write again and again: restarts, CPU throttling, pod readiness and percent of nodes ready.
@problem
Knowing the syntax is not the same as knowing which question to ask.
@does
- Restarts in the last hour from kube-state-metrics.
- CPU throttling ratio from cAdvisor.
- Pods not ready by namespace.
- Each can be turned into an alert after a sensible `for`.
@diagram cmp
caption: Query to symptom
cards:
  - {h: "Crash loops", kind: bad, items: ["increase(kube_pod_container_status_restarts_total[1h])"]}
  - {h: "Throttling", kind: warn, items: ["Throttled periods divided by periods"]}
  - {h: "Readiness", kind: info, items: ["kube_pod_status_ready condition false"]}
@h Queries
```promql title="Kubernetes patterns" nocheck
increase(kube_pod_container_status_restarts_total[1h]) > 3

sum by (namespace, pod) (rate(container_cpu_cfs_throttled_periods_total[5m]))
  / sum by (namespace, pod) (rate(container_cpu_cfs_periods_total[5m])) > 0.25

sum by (namespace) (kube_pod_status_ready{condition="false"}) > 0
```
@end
