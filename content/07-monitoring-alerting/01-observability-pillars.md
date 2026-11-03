---
title: Observability pillars and what to measure
minutes: 45
objectives:
  - Tell monitoring from observability and pick the right signal for a question
  - Apply the four golden signals and the RED and USE methods
  - Choose metric types and decide what is worth measuring
---
You cannot fix what you cannot see. This section gives you the vocabulary and the three or four checklists that decide what to measure before you touch any tool.

@concept Monitoring versus observability
@plain
**Monitoring** watches things you already know can go wrong and tells you when they do. **Observability** is how well you can ask new questions of a running system, using the data it emits, without shipping new code.
@problem
Dashboards built for yesterday's failures stay green while a new kind of failure hurts users. In a microservice system most incidents are unknown unknowns.
@does
- Monitoring answers "is it broken" with known checks and alerts.
- Observability answers "why is it broken, for whom, since when" using high-detail telemetry you can slice by any attribute.
- Both rely on the same raw material: metrics, logs and traces.
@diagram cmp
caption: Two questions, two styles of data
cards:
  - {h: "Monitoring", kind: info, items: ["Known failure modes", "Thresholds and alerts", "Is it up and fast"]}
  - {h: "Observability", kind: ok, items: ["Unknown failure modes", "Explore by any label", "Why is it slow for this tenant"]}
@check
Which one lets you investigate a failure nobody predicted? || Observability, because rich telemetry can be sliced in new ways after the fact.
@end

@concept The three pillars
@plain
**Metrics** are numbers over time. **Logs** are timestamped event records. **Traces** follow one request across services. Each is good at a different job.
@problem
Using only one signal forces awkward answers: counting errors from logs is expensive, and reading one log line cannot show which of eight services was slow.
@does
- Metrics are cheap, compact and ideal for alerting and trends. They lose per-request detail.
- Logs carry full detail for one event but cost more to store and search.
- Traces show the path and timing of one request, linking services together.
- The usual workflow is metric alert, then trace to find the service, then logs to find the line.
@diagram flow
caption: A typical investigation walks through all three signals
numbered: true
nodes:
  - "Alert fires|error rate metric is high|bad"
  - "Dashboard|which service and endpoint|info"
  - "Trace|which hop is slow|app"
  - "Logs|the exact error message|env"
  - "Fix and verify|metric returns to normal|ok"
@end

@concept The four golden signals
@plain
Google's SRE book names four signals that describe the health of almost any user-facing service: **latency**, **traffic**, **errors** and **saturation**.
@problem
Teams drown in hundreds of graphs. You need a short list that will catch most user-visible problems.
@does
- **Latency**: how long requests take. Track successes and failures separately, because a fast error hides slow successes.
- **Traffic**: demand on the service, such as requests per second.
- **Errors**: rate of failed requests, including wrong content or slow responses counted as failures.
- **Saturation**: how full the most constrained resource is, such as CPU, memory, queue depth or connections.
@diagram layers
caption: Golden signals map to user pain and to capacity
layers:
  - {label: "User facing", nodes: ["Latency|how slow|warn", "Errors|how often wrong|bad", "Traffic|how much demand|info"]}
  - {label: "Capacity", nodes: ["Saturation|how full|env"]}
@check
Why measure latency of errors separately? || A quick failure lowers average latency and can hide a real slowdown in successful requests.
@end

@concept The RED method
@plain
For every request-driven service, graph three things: **Rate**, **Errors** and **Duration**. It is the golden signals trimmed for microservices.
@problem
With dozens of services you need one identical dashboard layout per service so that anyone on call can read any of them.
@does
- Rate is requests per second, errors is failed requests per second (or a ratio), duration is a latency distribution such as p50 and p99.
- Works for HTTP, gRPC and queue consumers.
- Saturation is deliberately left to the USE method.
@diagram flow
caption: One RED row per service
nodes:
  - "Rate|requests per second|info"
  - "Errors|failed per second|bad"
  - "Duration|p50 and p99|warn"
@h RED in PromQL
```promql title="RED for an http_server service" nocheck
# Rate
sum(rate(http_requests_total{job="checkout"}[5m]))
# Errors as a ratio
sum(rate(http_requests_total{job="checkout",code=~"5.."}[5m]))
  / sum(rate(http_requests_total{job="checkout"}[5m]))
# Duration p99
histogram_quantile(0.99, sum by (le) (rate(http_request_duration_seconds_bucket{job="checkout"}[5m])))
```
@end

@concept The USE method
@plain
For every **resource** such as a CPU, disk or network link, check **Utilization**, **Saturation** and **Errors**. Brendan Gregg created it for hunting bottlenecks.
@problem
When a host is slow, guessing at causes wastes time. USE gives a systematic checklist across all resources.
@does
- Utilization is the fraction of time the resource is busy.
- Saturation is extra work waiting, such as run queue length or disk queue.
- Errors are error counts, such as network drops or disk errors.
- RED is for services, USE is for infrastructure. Use both.
@diagram cmp
caption: RED looks at requests, USE looks at resources
cards:
  - {h: "RED (services)", kind: app, items: ["Rate", "Errors", "Duration"]}
  - {h: "USE (resources)", kind: env, items: ["Utilization", "Saturation", "Errors"]}
@h USE for a Linux node
```promql title="USE with node_exporter" nocheck
# CPU utilization
1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))
# CPU saturation, load per core
node_load1 / count(count by (cpu) (node_cpu_seconds_total))
# Memory utilization
1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes
# Network errors
rate(node_network_receive_errs_total[5m])
```
@end

@concept SLIs, what to measure
@plain
A **service level indicator (SLI)** is a measurement of how well the service serves users, written as a ratio of good events to all events.
@problem
CPU graphs do not tell you whether users are happy. You need numbers that track user experience.
@does
- Good SLIs: availability (non-5xx over all requests), latency (requests faster than 300 ms over all requests), freshness and correctness for data pipelines.
- Measure close to the user: load balancer or client, not just inside the pod.
- Keep a short list per service, two to four.
@diagram flow
caption: From user journey to SLI
nodes:
  - "User journey|checkout|info"
  - "Good event|200 under 300 ms|ok"
  - "SLI ratio|good divided by total|app"
  - "SLO target|99.9 percent|cp"
@end

@concept Metric types
@plain
Prometheus metrics come in four types: **counter**, **gauge**, **histogram** and **summary**.
@problem
Using the wrong type gives wrong answers, such as averaging a percentile or graphing a raw counter that only goes up.
@does
- Counter only increases (resets on restart). Always use `rate()` on it.
- Gauge goes up and down, such as memory in use or queue size.
- Histogram counts observations into buckets, so percentiles can be computed on the server and across instances.
- Summary computes quantiles in the client and cannot be aggregated across instances.
@diagram cmp
caption: Pick the type from the question
cards:
  - {h: "Counter", kind: info, items: ["requests_total", "Use rate or increase"]}
  - {h: "Gauge", kind: ok, items: ["memory bytes", "Read directly"]}
  - {h: "Histogram", kind: app, items: ["latency buckets", "histogram_quantile"]}
  - {h: "Summary", kind: warn, items: ["Client quantiles", "Cannot aggregate"]}
@check
Why prefer histograms over summaries for latency in Kubernetes? || Bucket counters from many pods add up, so you can compute a fleet-wide percentile.
@end

@concept Symptoms versus causes
@plain
Alert on **symptoms** users feel (errors, slowness). Use causes (CPU, disk) for dashboards and diagnosis.
@problem
Alerting on every high CPU wakes people for harmless spikes while real outages from other causes go unnoticed.
@does
- A symptom alert catches every cause, including ones you never thought of.
- A cause alert is justified only when it predicts a future symptom, for example a disk that will fill in four hours.
- Fewer, symptom-based pages reduce alert fatigue.
@diagram flow
caption: Page on the symptom, diagnose with the causes
nodes:
  - "Symptom alert|error ratio above SLO burn|bad"
  - "Dashboard|CPU, memory, disk, dependencies|info"
  - "Root cause|found by the responder|ok"
@choose What to alert on
Error ratio or latency SLO burn | users are affected now | it only measures an internal resource
Disk will fill in 4 hours | prediction gives time to act | the disk is large and growth is flat
CPU above 80 percent | rarely, as a ticket for capacity | you would page a human for it
@end
