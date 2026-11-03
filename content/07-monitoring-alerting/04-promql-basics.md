---
title: PromQL fundamentals
minutes: 55
objectives:
  - Select series with label matchers and range vectors
  - Use rate and increase correctly on counters
  - Aggregate with sum, avg, topk and by or without
---
PromQL is the query language for Prometheus. Alerts, dashboards and recording rules are all PromQL expressions.

@concept Instant and range vectors
@plain
A selector such as `http_requests_total{job="api"}` returns an **instant vector**: the latest value of every matching series. Adding `[5m]` returns a **range vector**: all samples in the last five minutes per series.
@problem
You need a way to ask both "what is the value now" and "how did it change over a window".
@does
- Instant vector: one sample per series at one time. Graphs and alerts use this.
- Range vector: a list of samples per series. Only functions like `rate()` can consume it.
- A scalar is a single number; a string is rarely used.
@diagram cmp
caption: The data types of PromQL
cards:
  - {h: "Instant vector", kind: ok, items: ["metric{label=x}", "One value per series"]}
  - {h: "Range vector", kind: info, items: ["metric[5m]", "Needs rate or similar"]}
  - {h: "Scalar", kind: app, items: ["A plain number", "Used in arithmetic"]}
@end

@concept Label matchers
@plain
Inside braces you filter by labels with four operators: `=`, `!=`, `=~` (regex match) and `!~` (regex not match).
@problem
A metric name alone returns series from every service and environment.
@does
- Regexes are fully anchored: `code=~"5.."` matches 500 to 599 only.
- A selector must have at least one matcher that does not match the empty string.
- Matching on `__name__` selects across metrics, which is expensive.
@diagram flow
caption: Narrowing a selector
nodes:
  - "Name only|every series|warn"
  - "job and env|one service|info"
  - "code regex|only server errors|ok"
@h Examples
```promql title="Selectors" nocheck
http_requests_total
http_requests_total{job="api", env="prod"}
http_requests_total{code=~"5.."}
http_requests_total{namespace!~"kube-.*|monitoring"}
```
@end

@concept rate, irate and increase
@plain
Counters only go up, so their raw value is useless. `rate(x[5m])` gives the per-second average increase over the window. `increase(x[5m])` gives the total increase. `irate` uses only the last two samples.
@problem
You need requests per second, not "10 billion requests since the server first started". Counters also reset to zero on restart, which `rate` handles.
@does
- `rate` handles counter resets and extrapolates to window edges.
- Window must hold at least two samples: use at least 4 times the scrape interval (with 30s scrape use 2m or more).
- `irate` is jumpy and suits only fast-moving graphs. Never use it in alerts.
- `increase(x[1h])` equals `rate(x[1h]) * 3600`.
@diagram flow
caption: Counter to rate
numbered: true
nodes:
  - "Raw counter|1000, 1060, 1120|plain"
  - "Window 2m|samples inside the window|info"
  - "Rate|60 per 60 s = 1 per second|ok"
@h Examples
```promql title="Counter functions" nocheck
rate(http_requests_total{job="api"}[5m])
increase(http_requests_total{job="api"}[1h])
sum(rate(http_requests_total[5m])) by (job)
```
:::warn
Do not apply `rate` to a gauge, and do not apply `avg` before `rate`. Always rate first, then aggregate.
:::
@check
Rate window with a 15s scrape interval, minimum sensible value? || About 1m (four samples). Many teams use 5m for stability.
@end

@concept Aggregation operators
@plain
`sum`, `avg`, `min`, `max`, `count`, `topk`, `bottomk`, `quantile` and a few more combine many series into fewer.
@problem
One pod's metric tells little. You want per service, per namespace, or the five worst offenders.
@does
- `by (label)` keeps only the listed labels. `without (label)` removes the listed labels and keeps the rest.
- `count by (job) (up == 1)` counts healthy targets per job.
- `topk(5, expr)` returns the 5 largest series.
@diagram flow
caption: Many series become few
nodes:
  - "50 pod series|one per pod|plain"
  - "sum by (service)|drop pod label|warn"
  - "6 service series|ready to graph|ok"
@h Examples
```promql title="Aggregations" nocheck
sum by (namespace) (rate(container_cpu_usage_seconds_total[5m]))
avg without (instance) (node_load1)
topk(5, sum by (pod) (rate(container_network_receive_bytes_total[5m])))
count by (job) (up == 0)
```
@end

@concept Arithmetic and comparison
@plain
You can add, divide and compare vectors. Operators match series on identical label sets unless you tell them otherwise. Comparison without `bool` filters; with `bool` returns 0 or 1.
@problem
Ratios such as error percentage need two queries combined into one.
@does
- Arithmetic: `+ - * / % ^`.
- Comparison `> < == != >= <=` keeps only series that satisfy it. This is how alerts work.
- Use `ignoring(label)` or `on(label)` when label sets differ.
@diagram flow
caption: Error percentage
nodes:
  - "5xx rate|sum by service|bad"
  - "Total rate|sum by service|info"
  - "Divide|ratio 0 to 1|app"
  - "Greater than 0.05|only breaching services remain|warn"
@h Example
```promql title="Error ratio per service" nocheck
sum by (service) (rate(http_requests_total{code=~"5.."}[5m]))
  /
sum by (service) (rate(http_requests_total[5m]))
  > 0.05
```
@check
What does a comparison like x > 5 return? || Only the series of x whose value is above 5; the others disappear.
@end

@concept Gauges, delta and deriv
@plain
For gauges use direct values or `avg_over_time`, `max_over_time`, `delta` and `deriv`.
@problem
Gauges such as memory can spike. A raw point may miss the peak.
@does
- `max_over_time(x[1h])` is the peak in the last hour.
- `delta(x[1h])` is the change of a gauge across the window.
- `deriv(x[1h])` is the per-second slope using regression.
- `*_over_time` functions also include `min`, `sum`, `count`, `quantile`.
@diagram cmp
caption: Counters and gauges use different functions
cards:
  - {h: "Counter", kind: info, items: ["rate", "increase", "irate"]}
  - {h: "Gauge", kind: ok, items: ["avg_over_time", "max_over_time", "delta, deriv"]}
@h Examples
```promql title="Gauge queries" nocheck
max_over_time(container_memory_working_set_bytes{pod=~"api-.*"}[1h])
avg_over_time(node_load1[10m])
delta(node_filesystem_free_bytes{mountpoint="/"}[6h])
```
@end

@concept Time offsets, @ modifier and the Prometheus HTTP API
@plain
`offset 1d` looks one day back. The `@` modifier pins evaluation to an exact timestamp. The HTTP API lets scripts run any PromQL.
@problem
"Is traffic lower than the same time yesterday" needs two time points in one expression, and automation needs a machine interface.
@does
- `rate(x[5m] offset 1w)` is last week's rate.
- `/api/v1/query` evaluates at one instant; `/api/v1/query_range` returns a graph with `start`, `end`, `step`.
- Results are JSON with `data.result`.
@diagram seq
caption: Calling the API
actors: ["Script|curl or Python|app", "Prometheus|HTTP API|cp"]
steps:
  - "0>1: query=up | req"
  - "1>0: JSON vector | resp"
@h Example
```bash title="Query by API" lab
curl -sG localhost:9090/api/v1/query --data-urlencode 'query=sum(rate(http_requests_total[5m]))'
curl -sG localhost:9090/api/v1/query --data-urlencode 'query=sum(rate(http_requests_total[5m])) / sum(rate(http_requests_total[5m] offset 1d))'
```
@end
