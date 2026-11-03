---
title: Security analytics, detection rules and Elastic APM
minutes: 55
objectives:
  - Write detection rules over logs with ES and KQL concepts
  - Understand how Elastic Security and Fleet fit together
  - Instrument an application for Elastic APM and read traces
---
The same Elastic data that serves logs can detect threats and show application performance. This section covers both, as used on a Kubernetes and AWS platform.

@concept Elastic Security overview
@plain
Elastic Security is a set of Kibana apps and rules on top of Elasticsearch for SIEM (finding threats in logs) and endpoint protection.
@problem
Logs from CloudTrail, VPC flow, Kubernetes audit and hosts are useless for security if nobody searches them continuously.
@does
- Data arrives through Elastic Agent integrations (AWS CloudTrail, GuardDuty, Kubernetes audit, system logs) mapped to the Elastic Common Schema (ECS).
- Detection rules run on a schedule and create **alerts** in a `.alerts-security.alerts-*` index.
- Cases track investigations; timelines let analysts pivot across events.
- Some features need a paid licence tier; check the current subscription page.
@diagram flow
caption: From log to alert
nodes:
  - "Elastic Agent|AWS and k8s integrations|app"
  - "ECS fields|common names|info"
  - "Detection rule|runs on schedule|cp"
  - "Alert and case|analyst triage|ok"
@end

@concept ECS: the common schema
@plain
The Elastic Common Schema defines standard field names such as `source.ip`, `user.name`, `event.action` and `event.outcome`.
@problem
Each log source names the same thing differently. Without a common schema a rule must be rewritten per source.
@does
- Map your data to ECS in ingest pipelines or by using the integration packages.
- `event.category`, `event.type` and `event.outcome` classify what happened (for example `authentication`, `start`, `failure`).
- Rules written against ECS apply to any data that is mapped.
- Keep original values in `event.original` for forensics.
@diagram cmp
caption: Before and after ECS
cards:
  - {h: "Raw fields", kind: warn, items: ["clientIp, src_ip, remote", "One rule per source"]}
  - {h: "ECS fields", kind: ok, items: ["source.ip everywhere", "One rule fits many sources"]}
@h Rename in an ingest pipeline
```json title="pipeline body"
{
  "processors": [
    { "rename": { "field": "clientIp", "target_field": "source.ip", "ignore_missing": true } },
    { "set": { "field": "event.category", "value": "authentication" } }
  ]
}
```
@end

@concept Writing detection rules
@plain
A rule is a query plus a schedule, severity and actions. Rule types include query (KQL or Lucene), threshold, event correlation (EQL), indicator match and machine learning.
@problem
You want to know about repeated failed logins, a new admin role in AWS, or a shell in a container, within minutes.
@does
- **Query rule**: matches events, for example CloudTrail `event.action: "DeleteTrail"`.
- **Threshold rule**: more than N events grouped by a field, for example 10 failed logins from one `source.ip` in 5 minutes.
- **EQL rule**: ordered sequences such as a process start followed by a network connection.
- Set the run interval and look-back with a small overlap so events at the boundary are not missed.
- Tune with exceptions rather than disabling a noisy rule.
@diagram flow
caption: Rule types
nodes:
  - "Query|single event|app"
  - "Threshold|count over time|info"
  - "EQL sequence|ordered events|cp"
  - "ML|anomaly|warn"
@h Examples
```text title="Rule queries" nocheck
KQL:  event.dataset : "aws.cloudtrail" and event.action : "StopLogging" and event.outcome : "success"
EQL:  sequence by host.id with maxspan=2m
        [process where process.name == "curl"]
        [network where destination.port == 4444]
```
@check
Which rule type fits "10 failed logins from one IP in 5 minutes"? || A threshold rule grouped by source.ip.
@end

@concept Detection rules as code and tuning
@plain
Rules can be managed through the Kibana Detection Engine API and kept in Git.
@problem
Hand edited rules differ between clusters and nobody knows why a rule was changed.
@does
- Export rules as NDJSON, store in Git, and import with the API from CI; or use the community `detection-rules` project from Elastic.
- Tune: add exceptions for known good actors, raise thresholds, and measure alert-to-incident ratio per rule.
- Track MITRE ATT&CK mapping for coverage.
- Review the rule list quarterly and disable rules whose data source no longer exists.
@diagram flow
caption: Rule lifecycle
numbered: true
nodes:
  - "Rule in Git|NDJSON|app"
  - "Review|pull request|info"
  - "Import to Kibana|API call|cp"
  - "Tune|exceptions|ok"
@h Export and import
```bash title="Kibana API (check current docs)" nocheck
curl -s -u "$USER:$PASS" -H 'kbn-xsrf: true' -X POST \
  "$KIBANA/api/detection_engine/rules/_export" -o rules.ndjson
```
@end

@concept Kubernetes and AWS security data sources
@plain
Two high value sources for a Kubernetes on AWS platform are the Kubernetes audit log and AWS CloudTrail.
@problem
Cluster compromise often shows up as unusual API calls or IAM activity, which only these logs record.
@does
- EKS control plane logging can send `audit`, `authenticator` and `api` logs to CloudWatch; ship them to Elastic with the AWS integration.
- Rule ideas: `kubectl exec` into a pod in production, creation of a ClusterRoleBinding to `cluster-admin`, privileged pod creation, anonymous requests.
- CloudTrail: root account use, `CreateAccessKey`, security group opened to 0.0.0.0/0, disabling logging.
- Cost: audit logs are large; filter by verbs and resources in the audit policy if you control it (on EKS you receive what AWS provides).
@diagram layers
caption: Security data sources
layers:
  - {label: "Kubernetes", nodes: ["Audit log|exec, RBAC changes|app"]}
  - {label: "AWS", nodes: ["CloudTrail|IAM and network changes|app", "GuardDuty|threat findings|app"]}
  - {label: "Hosts", nodes: ["Agent events|process and network|info"]}
@end

@concept Elastic APM architecture
@plain
Elastic APM collects traces, spans, errors and metrics from applications and shows them in Kibana with service maps and latency charts.
@problem
Logs alone do not show where time goes inside a request across several services.
@does
- Applications use an Elastic APM agent (Java, Node.js, Python, Go, .NET and others) or OpenTelemetry SDKs that send OTLP.
- Data goes to APM Server (or the Elastic Agent integration) and is stored in data streams like `traces-apm-*`, `metrics-apm.*`, `logs-apm.*`.
- Kibana's Observability apps show services, transactions, dependencies and error groups.
- A **transaction** is a top-level operation (an HTTP request); a **span** is a step inside it (a SQL query).
@diagram flow
caption: APM data path
nodes:
  - "App with APM agent|spans|app"
  - "APM Server|validates and enriches|cp"
  - "Elasticsearch|traces-apm data streams|info"
  - "Kibana APM|service map and traces|ok"
@end

@concept Instrumenting a Kubernetes workload
@plain
The simplest set-up gives each pod environment variables that point the agent at the APM server.
@problem
Hard-coded endpoints and secret tokens in images make it impossible to move between environments.
@does
- Set `ELASTIC_APM_SERVER_URL`, `ELASTIC_APM_SERVICE_NAME`, `ELASTIC_APM_ENVIRONMENT` and a secret token from a Kubernetes Secret.
- Use a sampling rate (`ELASTIC_APM_TRANSACTION_SAMPLE_RATE`) such as 0.1 for busy services; error data is still captured.
- Add the trace ID to log lines (ECS logging libraries do this) so Kibana can link logs to the trace.
- On ECK, APM Server can be deployed as the `ApmServer` custom resource or through Fleet; check the current ECK docs.
@diagram flow
caption: Configuration reaches the agent
nodes:
  - "Secret|APM token|cp"
  - "Deployment env|URL, name, sample rate|app"
  - "Agent|sends data|info"
@h Deployment fragment
```yaml title="deployment env"
env:
  - name: ELASTIC_APM_SERVER_URL
    value: https://apm.observability.svc:8200
  - name: ELASTIC_APM_SERVICE_NAME
    value: shop-api
  - name: ELASTIC_APM_ENVIRONMENT
    value: prod
  - name: ELASTIC_APM_TRANSACTION_SAMPLE_RATE
    value: "0.1"
  - name: ELASTIC_APM_SECRET_TOKEN
    valueFrom:
      secretKeyRef:
        name: apm-token
        key: token
```
@check
Does sampling at 0.1 hide errors? || No; errors are still captured, while only about one in ten transactions keeps full trace detail.
@end

@concept Using APM to find a problem
@plain
Start at the service list, find the slow or failing service, then drill into transactions, spans and linked logs.
@problem
Looking at logs first for a latency complaint is slow; APM shows which span costs the time.
@does
- Services view: latency, throughput and error rate. Sort by impact.
- Transaction view: latency distribution and the slowest samples; a waterfall shows spans.
- Dependencies: the service map and external calls (database, HTTP).
- Errors: grouped by stack trace, with the trace of the failing request.
- Alert on latency and error rate with APM rules in Kibana; tie them to an SLO.
@diagram flow
caption: Drill-down path
numbered: true
nodes:
  - "Service list|find the outlier|info"
  - "Transaction|slow sample|app"
  - "Span waterfall|longest span|warn"
  - "Linked logs|cause|ok"
@end
