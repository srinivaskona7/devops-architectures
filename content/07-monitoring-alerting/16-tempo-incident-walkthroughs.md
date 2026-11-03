---
title: Tempo, trace-based debugging and incident walk-throughs
minutes: 60
objectives:
  - Store and query traces with Tempo and TraceQL
  - Connect metrics, logs and traces with exemplars and trace IDs
  - Follow three realistic incidents from alert to cause
---
Traces show the path of one request through many services. Together with metrics and logs they shorten the time from alert to cause.

@concept Tempo architecture
@plain
Tempo stores traces in object storage and indexes almost nothing. You find traces by ID, or by searching attributes with TraceQL over recent blocks.
@problem
Indexing every span attribute is expensive. Most teams only need to open a few traces linked from a log, metric or alert.
@does
- Receives OTLP, Jaeger and Zipkin formats; the OpenTelemetry Collector usually sends OTLP.
- Ingesters write blocks to S3; a compactor merges them; queriers read them.
- Tempo can generate metrics from spans (the metrics-generator) such as request rate, errors and latency per service, written to Prometheus remote write.
- Check the current docs for the deployment modes and the block format version.
@diagram flow
caption: Trace pipeline
nodes:
  - "App with OTel SDK|spans|app"
  - "OTel Collector|batch, sample|cp"
  - "Tempo|blocks in S3|info"
  - "Grafana|trace view|ok"
@end

@concept Sampling strategies
@plain
Sampling keeps a subset of traces. **Head sampling** decides at the start of the request; **tail sampling** decides after seeing the whole trace.
@problem
Storing every trace at high traffic is costly, but random sampling can drop the rare slow or failed requests you need most.
@does
- Head: simple, cheap, for example keep 5 percent. Cannot know yet if the request will fail.
- Tail (OpenTelemetry Collector `tail_sampling` processor): keep all errors, all slow traces, plus 5 percent of the rest. Needs all spans of a trace on the same collector, so route by trace ID.
- Arithmetic: 2 000 requests per second × 86 400 s = 172.8 million traces a day. At 5 percent that is 8.64 million.
- Always keep metrics for 100 percent of traffic; sampling affects only traces.
@diagram cmp
caption: Head versus tail sampling
cards:
  - {h: "Head sampling", kind: warn, items: ["Decided at start", "Cheap and simple", "May drop the error trace"]}
  - {h: "Tail sampling", kind: ok, items: ["Decided after completion", "Keeps errors and slow", "Needs routing by trace ID"]}
@h Tail sampling policy
```yaml title="otel collector processor"
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: errors
        type: status_code
        status_code:
          status_codes: [ERROR]
      - name: slow
        type: latency
        latency:
          threshold_ms: 1000
      - name: baseline
        type: probabilistic
        probabilistic:
          sampling_percentage: 5
```
@check
Why does tail sampling need all spans of a trace on one collector? || The decision looks at the complete trace, so spans split across collectors would be judged incorrectly.
@end

@concept TraceQL basics
@plain
TraceQL selects traces by span attributes, durations and structure.
@problem
You need all slow checkout traces from the last hour, not just one known trace ID.
@does
- `{ resource.service.name = "api" && duration > 500ms }` finds traces with such a span.
- `{ span.http.status_code >= 500 }` finds failing HTTP spans.
- Structural operators such as `>>` (descendant) find a span under another.
- `| count() > 3` and `| avg(duration)` aggregate per trace.
- Search relies on recent data and block scans, so keep time ranges tight.
@diagram flow
caption: Search to trace
nodes:
  - "TraceQL query|attributes and duration|app"
  - "Matching traces|list by duration|info"
  - "Open one|waterfall|cp"
  - "Slow span|cause|ok"
@h Examples
```text title="TraceQL" nocheck
{ resource.service.name = "checkout" && duration > 500ms }
{ span.http.status_code >= 500 } | count() > 1
{ resource.service.name = "api" } >> { span.db.system = "postgresql" && duration > 200ms }
```
@end

@concept Exemplars and linking signals
@plain
An **exemplar** is a trace ID attached to a metric sample. On a latency graph you click a dot to open a trace from the slow time bucket.
@problem
A p99 graph tells you something is slow but not which request.
@does
- The application client library attaches the trace ID to a histogram observation; Prometheus stores exemplars when started with exemplar storage enabled (check the current flag in the docs) and the scrape uses OpenMetrics format.
- Grafana shows exemplars as points; the data source setting maps the label (often `trace_id`) to the Tempo data source.
- Logs carry the same `trace_id`; Loki derived fields link to Tempo; Tempo can link back to logs by service and time.
- Result: metric to trace to log, each with one click.
@diagram flow
caption: Three signals joined by trace ID
nodes:
  - "Metric with exemplar|p99 dot|warn"
  - "Trace in Tempo|waterfall|info"
  - "Logs in Loki|by trace_id|app"
@end

@concept Incident 1, latency after a deploy
@plain
Alert: checkout p99 above 2 seconds for 10 minutes, started at 14:02.
@problem
Without a method the team guesses (database? network? the new release?).
@does
- Metrics: p99 rose only for route `/checkout`; error rate flat; CPU normal. Deploy annotation at 14:01 on the Grafana graph.
- Trace via exemplar: one slow trace shows a 1.8 s span `SELECT ... FROM orders` in service `checkout`.
- Logs filtered by that `trace_id`: the new release logs `seq scan on orders`.
- Cause: a migration dropped an index. Fix: recreate the index concurrently; confirm p99 recovers.
- Lesson: deploy annotations and trace-linked logs cut diagnosis to minutes.
@diagram seq
caption: Metrics to trace to log
actors: ["Alert|p99 high|warn", "Metrics|route panel|info", "Trace|Tempo|app", "Logs|Loki|app"]
steps:
  - "0>1: open dashboard | req"
  - "1>2: click exemplar | req"
  - "2>3: jump with trace_id | req"
  - "3>3: seq scan found | bad"
@end

@concept Incident 2, error spike from a dependency
@plain
Alert: 5xx ratio on `api` above 5 percent.
@problem
The error is in the API, but the cause may be downstream.
@does
- Metrics: errors only on `/search`; latency also rising.
- TraceQL `{ resource.service.name = "api" && span.http.status_code >= 500 }` shows the failing spans all have a child span to `search-svc` ending with a timeout after 5 s.
- Metrics for `search-svc`: pods restarting, memory near limit; `kubectl get pods` shows OOMKilled.
- Cause: a larger index loaded into memory. Action: raise the memory limit, add a timeout and circuit breaker in `api` so failures are fast, then fix the memory growth.
- Lesson: look at the child spans, not just the entry service.
@diagram flow
caption: Follow the failing child span
numbered: true
nodes:
  - "5xx on api|alert|bad"
  - "Trace child span|search-svc timeout|warn"
  - "OOMKilled|pod restarts|bad"
  - "Raise limit and add timeout|fix|ok"
@h Commands
```bash title="Confirm the restart reason" lab
kubectl get pods -n shop -l app=search-svc
kubectl describe pod -n shop -l app=search-svc | grep -A3 "Last State"
```
@end

@concept Incident 3, a slow burn that metrics hide
@plain
No alert fires, but customers report occasional slow orders.
@problem
Averages and even p95 look fine because only 0.5 percent of requests are slow.
@does
- Metrics: p99.9 is not tracked. The SLO burn alert is quiet because slow requests are under the threshold budget.
- Traces: TraceQL `{ resource.service.name = "checkout" && duration > 3s }` finds a pattern: all use a retry to the payment provider, with exponential delay.
- Logs: the provider returns 429 at peak times.
- Cause: rate limiting by a third party. Actions: add a client side limiter with queueing, raise the quota, and add a latency SLO at p99 and an alert on retry count.
- Lesson: tail latency is invisible in averages; tail-sampled traces keep the evidence.
@diagram cmp
caption: What each signal showed
cards:
  - {h: "Metrics", kind: warn, items: ["Average and p95 fine", "No burn alert"]}
  - {h: "Traces", kind: ok, items: ["Slow ones share retry spans", "Pattern visible"]}
  - {h: "Logs", kind: ok, items: ["429 from provider", "Root cause confirmed"]}
@check
Why did averages hide the problem? || Only about 0.5 percent of requests were slow, which barely moves the average or p95; tail percentiles and traces expose them.
@end
