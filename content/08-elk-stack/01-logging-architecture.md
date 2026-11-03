---
title: Logging architecture and structured logs
minutes: 45
objectives:
  - Describe the stages of a centralised logging pipeline
  - Write structured JSON logs with consistent fields
  - Decide where to collect logs on Kubernetes and AWS
---
Logs are the detailed record of what happened. Once you run more than a few servers or pods, reading files on each machine stops working, so you ship them to one searchable place.

@concept Why centralise logs
@plain
Centralised logging copies the logs of every host, pod and service into one system where you can search, filter and graph them together.
@problem
Pods are deleted and replaced, taking their local logs with them. Debugging one request that crossed six services would need six shell sessions.
@does
- Logs survive the death of the pod or node that wrote them.
- One query can follow a request ID across services.
- Access control, retention and alerting can be applied in one place.
@diagram flow
caption: The stages of a logging pipeline
nodes:
  - "Apps|write to stdout or files|app"
  - "Collector|Filebeat, Fluent Bit, Agent|env"
  - "Processor|parse, enrich, route|warn"
  - "Store|Elasticsearch|cp"
  - "UI|Kibana|info"
@end

@concept The ELK stack and the Elastic Stack
@plain
**ELK** means Elasticsearch (store and search), Logstash (process) and Kibana (view). Beats and Elastic Agent were added to collect data, so the whole family is now called the Elastic Stack.
@problem
Each job in the pipeline is different. Searching terabytes needs a distributed engine, parsing needs a flexible processor, and collection needs a very light agent.
@does
- **Elasticsearch**: distributed search and analytics engine built on Apache Lucene.
- **Logstash**: server-side pipeline for heavy parsing and routing.
- **Kibana**: web interface for search, dashboards and alerts.
- **Beats / Elastic Agent**: lightweight shippers running on each host.
@diagram layers
caption: Roles in the Elastic Stack
layers:
  - {label: "Collect", nodes: ["Filebeat|log files|env", "Elastic Agent|managed by Fleet|env"]}
  - {label: "Process", nodes: ["Logstash|pipelines|warn", "Ingest pipelines|inside Elasticsearch|warn"]}
  - {label: "Store and search", nodes: ["Elasticsearch|indices, shards|cp"]}
  - {label: "Visualise", nodes: ["Kibana|Discover, Lens, alerts|info"]}
@end

@concept Structured logging
@plain
A structured log line is data, not prose: usually one JSON object per line with named fields such as `level`, `service`, `trace_id` and `message`.
@problem
Free text such as `User bob failed login from 10.1.2.3 after 3 tries` must be parsed with fragile regular expressions, and any wording change breaks the parser.
@does
- JSON lines can be indexed field by field with no parsing step.
- Fields enable exact filters (`level: error`, `http.status >= 500`) and aggregations.
- Use the same names in every service. Elastic Common Schema (ECS) is a ready-made naming standard.
@diagram cmp
caption: Same event, two styles
cards:
  - {h: "Unstructured", kind: bad, items: ["Failed login for bob from 10.1.2.3", "Needs regex or grok", "Breaks on rewording"]}
  - {h: "Structured JSON", kind: ok, items: ["Fields: user, client.ip, outcome", "Index directly", "Stable for queries"]}
@h Python example
```python title="structured_logging.py" lab
import json, logging, sys, time

class JsonFormatter(logging.Formatter):
    def format(self, record):
        doc = {
            "@timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "log.level": record.levelname.lower(),
            "message": record.getMessage(),
            "service.name": "checkout",
        }
        doc.update(getattr(record, "fields", {}))
        return json.dumps(doc)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger("checkout")
log.addHandler(handler)
log.setLevel(logging.INFO)
log.info("login failed", extra={"fields": {"user.name": "bob", "client.ip": "10.1.2.3", "event.outcome": "failure"}})
```
@end

@concept Elastic Common Schema
@plain
ECS is a published list of standard field names, such as `@timestamp`, `log.level`, `host.name`, `http.response.status_code`, `trace.id` and `kubernetes.pod.name`.
@problem
If one team logs `status` and another `httpCode`, a single dashboard cannot cover both.
@does
- Field names use dotted paths, which Elasticsearch treats as nested objects.
- Beats, Elastic Agent integrations and ingest pipelines emit ECS fields.
- OpenTelemetry semantic conventions are being aligned with ECS; check the current docs for details.
@diagram flow
caption: Normalising to one schema
nodes:
  - "Nginx log|status, remote_addr|plain"
  - "Parser|maps to ECS|warn"
  - "ECS fields|http.response.status_code, source.ip|ok"
@check
Why use ECS names even for your own services? || Dashboards, alerts and detection rules written once work for every source that follows the schema.
@end

@concept What to log, and what not to
@plain
Log events that explain behaviour: requests, errors, state changes, security decisions. Do not log secrets or personal data.
@problem
Too little logging leaves incidents unexplained; too much costs money and hides the signal. Leaked tokens in logs become a security incident.
@does
- Levels: `error` for failures needing attention, `warn` for recoverable problems, `info` for normal milestones, `debug` only when needed.
- Always include timestamp, service, version, environment, request or trace ID.
- Never log passwords, tokens, full card numbers or personal data. Mask them in the application or in the pipeline.
- One event per line. Multi-line stack traces should go inside a single JSON field.
@diagram layers
caption: Fields every log line needs
layers:
  - {label: "When and where", nodes: ["@timestamp|UTC ISO 8601|info", "service.name|which app|app", "service.version|which build|app"]}
  - {label: "What", nodes: ["log.level|severity|warn", "message|human text|plain"]}
  - {label: "Correlation", nodes: ["trace.id|link to traces|ok", "request id|follow one request|ok"]}
@end

@concept Container logging on Kubernetes
@plain
Containers should write logs to **stdout and stderr**. The container runtime saves them as files on the node, and a collector reads those files.
@problem
Writing log files inside a container fills its writable layer and the files vanish when the pod does.
@does
- On the node, files appear under `/var/log/pods/<namespace>_<pod>_<uid>/<container>/` with symlinks in `/var/log/containers/`.
- The kubelet rotates them (`containerLogMaxSize`, default 10Mi, and `containerLogMaxFiles`, default 5).
- A DaemonSet collector tails these files and adds pod metadata (namespace, labels).
- `kubectl logs` reads the same files, so it only shows recent data.
@diagram flow
caption: From container to Elasticsearch
nodes:
  - "App stdout|JSON line|app"
  - "Node file|/var/log/containers|env"
  - "DaemonSet collector|adds pod metadata|warn"
  - "Elasticsearch|searchable|cp"
@h Look at the node files
```bash title="Where the logs live" lab
kubectl get pods -n shop -o wide
kubectl logs deploy/checkout -n shop --tail=5
# on a node (via SSH or a debug pod)
ls /var/log/containers | head
tail -n 2 /var/log/containers/checkout-*.log
```
@end

@concept Collection patterns on Kubernetes and AWS
@plain
There are four common ways to get logs out: a node-level agent, a sidecar, direct push from the app, and a cloud service such as CloudWatch Logs.
@problem
The right pattern depends on cost, isolation and how much control you need.
@does
- **Node agent (DaemonSet)**: one collector per node. Cheapest and the default.
- **Sidecar**: a collector per pod. Needed when the app writes files you cannot change, at the price of more resources.
- **Direct push**: the app sends to Logstash or Elasticsearch. Couples the app to the logging backend; avoid unless required.
- **AWS**: EKS can send control plane logs to CloudWatch Logs; Fluent Bit or Firehose can forward CloudWatch to Elasticsearch or OpenSearch.
@diagram cmp
caption: Collection patterns
cards:
  - {h: "DaemonSet agent", kind: ok, items: ["One per node", "Default choice", "Reads node files"]}
  - {h: "Sidecar", kind: info, items: ["One per pod", "For app-written files", "More resource use"]}
  - {h: "Direct push", kind: warn, items: ["App knows the backend", "Loses logs on outage", "Rarely best"]}
  - {h: "CloudWatch Logs", kind: app, items: ["Managed AWS source", "Pay per GB ingested", "Forward when needed"]}
@choose Pick a pattern
DaemonSet agent | stdout logging, standard clusters | the app only writes a file inside the container
Sidecar | legacy apps that write log files | you have thousands of small pods
CloudWatch Logs first | Lambda, RDS and EKS control plane logs | you need low-cost, full-text search on high volume
@end
