---
title: Tracing and OpenTelemetry
minutes: 55
objectives:
  - Explain traces, spans and context propagation
  - Configure an OpenTelemetry Collector pipeline
  - Choose a sampling strategy and follow semantic conventions
---
Metrics tell you that something is slow. Traces tell you where. OpenTelemetry (OTel) is the open standard for producing and moving that data.

@concept Traces and spans
@plain
A **trace** is the story of one request. It consists of **spans**: timed operations such as an HTTP handler or a database query, linked parent to child.
@problem
In a system of 30 services, a log line from one service cannot tell you why the whole request took 4 seconds.
@does
- Each span has a name, start time, duration, attributes, events and a status.
- All spans of a request share a trace ID; each has its own span ID and a parent span ID.
- The longest chain of spans shows the critical path.
@diagram flow
caption: One request, nested spans
nodes:
  - "GET /checkout|root span 1200 ms|app"
  - "auth call|80 ms|info"
  - "inventory call|300 ms|info"
  - "payment call|700 ms, the slow one|bad"
@end

@concept Context propagation
@plain
For a trace to span services, each call must pass the trace ID along. The W3C `traceparent` HTTP header does that.
@problem
Without propagation each service starts a new unrelated trace.
@does
- Format: version, trace ID, parent span ID and flags, joined by dashes, for example `00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01`.
- SDK instrumentation for HTTP and gRPC clients and servers injects and extracts it automatically.
- Message queues need the header copied into message metadata.
- Put the trace ID into logs to link logs and traces.
@diagram seq
caption: Header passed between services
actors: ["Service A|caller|app", "Service B|callee|app"]
steps:
  - "0>1: traceparent header | req"
  - "note 1..1: child span, same trace ID"
  - "1>0: response | resp"
@end

@concept OpenTelemetry components
@plain
OpenTelemetry has a specification, language **SDKs** and **APIs**, the **OTLP** protocol and the **Collector**. It does not store data; you pick a backend.
@problem
Each vendor had its own agent and format, so switching backends meant re-instrumenting every service.
@does
- API: what your code calls. SDK: implements it, samples, batches and exports.
- OTLP over gRPC (port 4317) or HTTP (port 4318) is the standard wire format for traces, metrics and logs.
- Auto-instrumentation exists for Java, Python, Node.js, .NET and others; the OpenTelemetry Operator can inject it into Kubernetes pods by annotation.
@diagram layers
caption: OpenTelemetry stack
layers:
  - {label: "Your code", nodes: ["API calls|spans and metrics|app", "Auto-instrumentation|libraries|app"]}
  - {label: "Per process", nodes: ["SDK|sample, batch, export|env"]}
  - {label: "Pipeline", nodes: ["Collector|receive, process, export|cp"]}
  - {label: "Backends", nodes: ["Tempo, Jaeger|traces|ext", "Prometheus, Mimir|metrics|ext", "Loki, Elastic|logs|ext"]}
@end

@concept SDK setup in Python
@plain
Configure a tracer provider with a resource (who am I) and an OTLP exporter, then create spans or let auto-instrumentation do it.
@problem
Without a service name resource, backends show every service as "unknown_service".
@does
- `service.name` is the most important attribute.
- `BatchSpanProcessor` buffers spans and exports in batches, so latency is not affected.
- The standard environment variables (`OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_TRACES_SAMPLER`) configure SDKs without code.
@diagram flow
caption: In-process path
nodes:
  - "tracer.start_span|your code|app"
  - "BatchSpanProcessor|buffer|env"
  - "OTLP exporter|to Collector 4317|info"
@h Example
```python title="tracing.py"
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

resource = Resource.create({"service.name": "checkout", "deployment.environment": "prod"})
provider = TracerProvider(resource=resource)
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint="otel-collector:4317", insecure=True)))
trace.set_tracer_provider(provider)

tracer = trace.get_tracer("checkout.orders")

def place_order(order_id):
    with tracer.start_as_current_span("place_order") as span:
        span.set_attribute("order.items", 3)
        # business logic here
```
```bash title="Zero-code alternative" lab
# first install the opentelemetry-distro and opentelemetry-exporter-otlp packages
OTEL_SERVICE_NAME=checkout OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
  opentelemetry-instrument python app.py
```
@end

@concept The Collector and pipelines
@plain
The OpenTelemetry Collector is a standalone process that **receives** telemetry, **processes** it and **exports** it. A pipeline connects receivers, processors and exporters for one signal.
@problem
Sending directly from every app to a backend couples apps to vendors and cannot add retry, filtering or sampling centrally.
@does
- Receivers: `otlp`, `prometheus`, `filelog`, `hostmetrics`, `k8s_cluster`.
- Processors: `memory_limiter` (first), `k8sattributes`, `batch` (last), `attributes`, `tail_sampling`.
- Exporters: `otlp` to Tempo, `prometheusremotewrite`, `loki`, `elasticsearch`, `awsxray`, and others (check the contrib distribution for availability).
- Deploy as agent (DaemonSet) near apps and as a gateway (Deployment) for central processing.
@diagram flow
caption: Pipeline anatomy
nodes:
  - "Receivers|otlp, prometheus, filelog|ext"
  - "Processors|memory_limiter, k8sattributes, batch|warn"
  - "Exporters|otlp, remote write, loki|ok"
@h Collector configuration
```yaml title="otel-collector.yaml"
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
processors:
  memory_limiter:
    check_interval: 1s
    limit_mib: 400
  k8sattributes: {}
  batch:
    timeout: 5s
    send_batch_size: 8192
exporters:
  otlp/tempo:
    endpoint: tempo.monitoring:4317
    tls:
      insecure: true
  prometheusremotewrite:
    endpoint: http://mimir.monitoring/api/v1/push
service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, k8sattributes, batch]
      exporters: [otlp/tempo]
    metrics:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [prometheusremotewrite]
```
@end

@concept Sampling
@plain
Sampling keeps a fraction of traces. **Head sampling** decides when the trace starts. **Tail sampling** decides after the trace completes, so it can keep all errors and slow traces.
@problem
Storing 100 percent of traces from a busy system is costly, and most traces are boring.
@does
- Head: simple, cheap, random (for example 10 percent), but may drop the one failing trace.
- Tail: needs all spans of a trace in one Collector instance (use a load-balancing exporter keyed by trace ID) and memory to buffer them.
- Example policy: keep 100 percent of errors, 100 percent over 2 seconds, 5 percent of the rest.
- Arithmetic: 2 000 traces per second × 86 400 = 172.8 million traces per day. At 5 percent kept that is 8.64 million; at 10 KB per trace about 86 GB per day instead of 1.7 TB.
@diagram cmp
caption: Head versus tail
cards:
  - {h: "Head sampling", kind: info, items: ["Decide at the start", "Cheap, no buffering", "Can miss errors"]}
  - {h: "Tail sampling", kind: ok, items: ["Decide at the end", "Keeps errors and slow traces", "Needs memory and routing"]}
@h Tail sampling policy
```yaml title="Tail sampling processor"
processors:
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: errors
        type: status_code
        status_code: {status_codes: [ERROR]}
      - name: slow
        type: latency
        latency: {threshold_ms: 2000}
      - name: baseline
        type: probabilistic
        probabilistic: {sampling_percentage: 5}
```
@end

@concept Semantic conventions
@plain
Semantic conventions are agreed attribute names, such as `http.request.method`, `service.name`, `db.system` and `k8s.pod.name`.
@problem
If every team names the same thing differently, backends and dashboards cannot work across services.
@does
- Use standard names for resources (who produced it) and span attributes (what happened).
- Some HTTP and database attribute names changed in recent versions (for example `http.method` became `http.request.method`); check the current spec for your SDK.
- Keep attribute values low in cardinality when they become metric labels.
- Add business attributes under your own prefix, such as `shop.order_id`.
@diagram cmp
caption: Resource versus span attributes
cards:
  - {h: "Resource", kind: info, items: ["service.name", "deployment.environment", "k8s.namespace.name"]}
  - {h: "Span", kind: app, items: ["http.request.method", "http.response.status_code", "db.system"]}
@end

@concept Synthetic monitoring in practice
@plain
Synthetic monitoring runs scripted checks against your service on a schedule, from outside, as a fake user.
@problem
Real users only reveal outages after they happen, and idle systems at night have no traffic to measure.
@does
- Layers: simple probes (blackbox), multi-step browser journeys (login then checkout), and API contract checks.
- Tools: blackbox exporter, Grafana Synthetic Monitoring (k6 based), CloudWatch Synthetics canaries on AWS.
- Run from at least two locations, alert on consecutive failures, and attach the trace or screenshot to the alert.
- Keep test accounts and clearly mark synthetic traffic so it is excluded from business metrics.
@diagram flow
caption: Synthetic check lifecycle
nodes:
  - "Scheduler|every minute from 2 regions|cp"
  - "Scripted journey|login and checkout|app"
  - "Result metrics|success and duration|info"
  - "Alert|two failures in a row|bad"
@choose Which synthetic tool
Blackbox exporter | simple HTTP, TCP, DNS, TLS checks | you need a multi-step browser flow
CloudWatch Synthetics canary | you are all-in on AWS and want screenshots | you want PromQL based alerts only
Grafana k6 or browser checks | scripted API or browser journeys | a plain ping is enough
@end
