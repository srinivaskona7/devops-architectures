---
title: CloudWatch Logs, Logs Insights and Container Insights
minutes: 50
objectives:
  - Ship container logs to CloudWatch Logs and control retention and cost
  - Query logs with Logs Insights and turn patterns into metrics
  - Enable Container Insights and know when to choose Prometheus and Grafana instead
---
Logs answer why. On EKS the usual path is stdout, to a node agent, to CloudWatch Logs, with queries and metric filters on top.
@concept Log groups, streams and retention
@plain
Logs are stored in **log groups** (one per application or source) that contain **log streams** (one per source instance). Retention and encryption are set on the group.
@problem
Default retention is never expire, which silently builds large bills.
@does
- Set a retention period on every group (1 day to 10 years).
- Encrypt with a KMS key when required.
- Log classes: **Standard** (full features) and **Infrequent Access** (cheaper ingestion, fewer features).
- Ingestion is the main cost, followed by storage; reduce noise with log levels and sampling.
- Subscription filters stream logs to Kinesis, Firehose or Lambda; export to S3 for long-term archive.
@diagram layers
caption: Hierarchy
layers:
  - {label: "Log group", nodes: ["/aws/containerinsights/shop-prod/application|retention 30 days|cp"]}
  - {label: "Log streams", nodes: ["web-7d9c.web|pod and container|app", "orders-5b8f.orders|pod and container|app"]}
  - {label: "Events", nodes: ["Timestamped messages|JSON preferred|info"]}
@h Set retention everywhere
```bash title="Find groups with no retention and fix them" lab
aws logs describe-log-groups --query 'logGroups[?retentionInDays==`null`].logGroupName' --output text
aws logs put-retention-policy --log-group-name /aws/eks/shop-prod/cluster --retention-in-days 30
```
@check
What is the usual hidden cost of CloudWatch Logs? || Log groups with no retention accumulate storage forever, and high-volume ingestion is billed per GB.
@end

@concept Shipping container logs from EKS
@plain
Pods write to stdout. A DaemonSet agent (Fluent Bit, or the CloudWatch agent from the Observability add-on) reads node log files and ships them with Kubernetes metadata.
@problem
Without an agent, logs vanish when pods are rescheduled.
@does
- The `amazon-cloudwatch-observability` add-on installs the CloudWatch agent and Fluent Bit and creates groups under `/aws/containerinsights/<cluster>/`.
- Agents need an IAM role (`CloudWatchAgentServerPolicy`) via Pod Identity or IRSA.
- Write structured JSON logs with level, trace ID and request ID.
- Fargate uses the built-in log router configured via a ConfigMap.
- Alternatives: ship to OpenSearch, Grafana Loki or a third party using Fluent Bit outputs.
@diagram flow
caption: Log path
nodes:
  - "Container stdout|JSON lines|app"
  - "Node log file|/var/log/containers|env"
  - "Fluent Bit|DaemonSet|cp"
  - "CloudWatch Logs|searchable|ok"
@h Install
```bash title="Observability add-on" nocheck
aws eks create-addon --cluster-name shop-prod --addon-name amazon-cloudwatch-observability \
  --pod-identity-associations serviceAccount=cloudwatch-agent,roleArn=arn:aws:iam::111122223333:role/cloudwatch-agent
kubectl -n amazon-cloudwatch get pods
```
@check
Why log JSON? || Logs Insights and other tools can then filter by fields without brittle text parsing.
@end

@concept Logs Insights queries
@plain
Logs Insights is an interactive query language for log groups: filter, parse, aggregate, sort.
@problem
Grepping across many pods and streams is slow and misses context.
@does
- Commands: `fields`, `filter`, `parse`, `stats`, `sort`, `limit`, `dedup`, `pattern`.
- Auto-discovers JSON fields in the log message (`@message`) so you can filter on `level` directly.
- You pay per GB scanned, so narrow the time range and the group list.
- Save queries and add them to dashboards; use `anomaly` or `pattern` to find new error shapes.
@diagram flow
caption: Query pipeline
nodes:
  - "Select groups and time|narrow scan|info"
  - "filter|rows|app"
  - "stats|aggregate|cp"
  - "sort and limit|answer|ok"
@h Queries
```text title="Top errors by service in the last hour" nocheck
fields @timestamp, kubernetes.labels.app as app, level, msg
| filter level = "error"
| stats count(*) as errors by app, msg
| sort errors desc
| limit 20
```
```text title="p99 latency from request logs" nocheck
fields @timestamp, duration_ms
| filter ispresent(duration_ms)
| stats pct(duration_ms, 99) as p99, avg(duration_ms) as avg by bin(5m)
```
```bash title="Run a query from the CLI" nocheck
aws logs start-query --log-group-name /aws/containerinsights/shop-prod/application \
  --start-time $(date -u -v-1H +%s) --end-time $(date -u +%s) \
  --query-string 'fields @timestamp, @message | filter @message like /error/ | limit 20'
```
@check
What drives Logs Insights cost? || The amount of log data scanned by each query.
@end

@concept Metric filters and subscription filters
@plain
A **metric filter** turns matching log lines into a CloudWatch metric. A **subscription filter** streams logs in near real time to another service.
@problem
Applications log errors but do not publish metrics, so you cannot alarm on them.
@does
- Pattern like `{ $.level = "error" }` increments a metric `AppErrors`; then alarm on it.
- Metric filters apply to new events only, with values from JSON fields if needed.
- Subscription filters (up to two per group) send to Firehose for S3/OpenSearch or Lambda for processing; use cross-account destinations to centralise logs.
- Data protection policies can mask sensitive data patterns automatically.
@diagram flow
caption: Logs to alarms and archives
nodes:
  - "Log group|JSON events|info"
  - "Metric filter|count errors|cp"
  - "Alarm|too many|warn"
  - "Firehose to S3|archive|ok"
@h Create
```bash title="Metric filter for errors" nocheck
aws logs put-metric-filter --log-group-name /aws/containerinsights/shop-prod/application \
  --filter-name app-errors --filter-pattern '{ $.level = "error" }' \
  --metric-transformations metricName=AppErrors,metricNamespace=Shop,metricValue=1,defaultValue=0
```
@check
Do metric filters process historical logs? || No, only events ingested after the filter exists.
@end

@concept Container Insights
@plain
Container Insights collects cluster, node, pod and container metrics (CPU, memory, network, restarts) and presents them in prebuilt dashboards, with optional enhanced observability for EKS.
@problem
`kubectl top` shows only current values and no history; you need trends and per-namespace views.
@does
- Metrics land in the `ContainerInsights` namespace with dimensions `ClusterName`, `Namespace`, `PodName`, `NodeName`.
- Enhanced observability adds more detail (per-container, control plane metrics, performance dashboards) at higher metric cost.
- Cost control: metrics per pod multiply with churn; for large clusters consider Amazon Managed Service for Prometheus plus Managed Grafana, or a self-hosted stack.
- Pair with Application Signals or OpenTelemetry (ADOT) for traces and service maps; X-Ray for tracing.
@diagram cmp
caption: Native versus Prometheus stack
cards:
  - {h: "Container Insights", kind: ok, items: ["Add-on, no servers", "Prebuilt dashboards", "Cost grows with pod count"]}
  - {h: "AMP and Managed Grafana", kind: app, items: ["PromQL and ecosystem", "Remote write from Prometheus", "More setup"]}
@choose Observability stack
Container Insights | quick start, AWS native alarms | very high pod churn and cardinality
Prometheus with AMP | PromQL, SLOs, portable across clouds | you want zero setup
OpenTelemetry (ADOT) | traces and metrics from apps | you only need node metrics
@h Alarm on pod restarts
```bash title="Alarm on container restarts" nocheck
aws cloudwatch put-metric-alarm --alarm-name shop-pod-restarts \
  --namespace ContainerInsights --metric-name pod_number_of_container_restarts \
  --dimensions Name=ClusterName,Value=shop-prod Name=Namespace,Value=shop \
  --statistic Maximum --period 300 --evaluation-periods 1 --threshold 3 \
  --comparison-operator GreaterThanThreshold --alarm-actions arn:aws:sns:us-east-1:111122223333:ops-alerts
```
@check
Why can Container Insights get expensive? || Metrics are produced per pod and per container, so churn and cardinality increase the metric count.
@end
