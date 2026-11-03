---
title: CloudWatch metrics and alarms
minutes: 45
objectives:
  - Use namespaces, dimensions, statistics and periods to read metrics correctly
  - Build alarms including composite alarms, anomaly detection and metric math
  - Publish custom metrics and wire alarms to notifications and automation
---
CloudWatch is the default telemetry store on AWS. Metrics are cheap time series; alarms turn them into action.

@concept Metrics, namespaces and dimensions
@plain
A metric is a time series identified by a **namespace** (`AWS/RDS`), a **name** (`CPUUtilization`) and **dimensions** (key-value labels such as `DBInstanceIdentifier=shop-db`).
@problem
Hundreds of resources emit data points; you need a consistent way to pick exactly the series you mean.
@does
- AWS services publish basic metrics automatically at 1 or 5 minute resolution (some paid, finer).
- Each unique combination of dimensions is a separate metric.
- Statistics: Average, Sum, Minimum, Maximum, SampleCount and percentiles (p99).
- Period is the aggregation window (60 seconds minimum, or 1 second for high-resolution custom metrics).
- Retention: 1 minute data for 15 days, 5 minute data for 63 days, 1 hour data for 455 days (check the current retention).
@diagram layers
caption: Naming a metric
layers:
  - {label: "Namespace", nodes: ["AWS/ApplicationELB|service|cp"]}
  - {label: "Metric name", nodes: ["TargetResponseTime|what|info"]}
  - {label: "Dimensions", nodes: ["LoadBalancer app/shop/abc|which one|app", "TargetGroup targetgroup/web/def|which one|app"]}
@h Read metrics
```bash title="Query a metric with the CLI" lab
aws cloudwatch list-metrics --namespace AWS/ApplicationELB --metric-name TargetResponseTime --max-items 3
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name TargetResponseTime \
  --dimensions Name=LoadBalancer,Value=app/shop/50dc6c495c0c9188 \
  --start-time "$(date -u -v-1H +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" \
  --period 300 --extended-statistics p99
```
@check
Why are two metrics with different dimensions distinct series? || Each dimension combination defines its own time series.
@end

@concept Alarms
@plain
An alarm watches one metric (or a math expression) and changes state between OK, ALARM and INSUFFICIENT_DATA based on a threshold over several periods.
@problem
Dashboards need a human watching. Alarms notify or act when thresholds are crossed.
@does
- `EvaluationPeriods` and `DatapointsToAlarm` (M out of N) reduce flapping.
- `TreatMissingData` decides what missing data means: `notBreaching`, `breaching`, `ignore`, `missing`.
- Actions: SNS topics, Auto Scaling policies, EC2 actions, Systems Manager OpsItems, Incident Manager.
- Alarm on symptoms users feel (latency, error rate), not only causes (CPU).
@diagram flow
caption: Alarm lifecycle
nodes:
  - "Metric|data points|info"
  - "Alarm|threshold over periods|warn"
  - "SNS topic|fan-out|cp"
  - "Chat, pager, runbook|response|ok"
@h Terraform
```hcl title="5xx rate alarm on the ALB"
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "shop-alb-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 10
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions = {
    LoadBalancer = var.alb_arn_suffix
  }
  alarm_actions = [aws_sns_topic.ops.arn]
  ok_actions    = [aws_sns_topic.ops.arn]
}
```
@check
What does 3 datapoints out of 5 mean? || The alarm fires when at least 3 of the last 5 periods breach the threshold.
@end

@concept Metric math, anomaly detection and composite alarms
@plain
Metric math computes new series, such as an error rate, from other metrics. Anomaly detection learns a normal band. Composite alarms combine alarms with AND/OR.
@problem
Raw counts mislead (10 errors is fine at 1,000,000 requests and bad at 100), and many alarms firing together create noise.
@does
- Expression `100 * m1 / m2` gives error percentage from 5xx count and request count.
- Anomaly detection alarms fire when a metric leaves its expected band, which suits seasonal traffic.
- Composite: `ALARM(high-latency) AND ALARM(high-errors)` pages once, while individual alarms stay silent.
- Use `SEARCH` expressions for fleet-wide dashboards.
@diagram flow
caption: Error rate alarm
nodes:
  - "5xx count|m1|info"
  - "Request count|m2|info"
  - "Expression|100 * m1 / m2|cp"
  - "Alarm|above 1 percent|warn"
@h Alarm JSON
```json title="Error percentage alarm input (put-metric-alarm --cli-input-json)"
{
  "AlarmName": "shop-error-rate",
  "ComparisonOperator": "GreaterThanThreshold",
  "Threshold": 1.0,
  "EvaluationPeriods": 5,
  "DatapointsToAlarm": 3,
  "TreatMissingData": "notBreaching",
  "Metrics": [
    {"Id": "e1", "Expression": "100 * m1 / m2", "Label": "ErrorRate", "ReturnData": true},
    {"Id": "m1", "ReturnData": false, "MetricStat": {"Metric": {"Namespace": "AWS/ApplicationELB", "MetricName": "HTTPCode_Target_5XX_Count", "Dimensions": [{"Name": "LoadBalancer", "Value": "app/shop/50dc6c495c0c9188"}]}, "Period": 60, "Stat": "Sum"}},
    {"Id": "m2", "ReturnData": false, "MetricStat": {"Metric": {"Namespace": "AWS/ApplicationELB", "MetricName": "RequestCount", "Dimensions": [{"Name": "LoadBalancer", "Value": "app/shop/50dc6c495c0c9188"}]}, "Period": 60, "Stat": "Sum"}}
  ]
}
```
@check
Why prefer a rate alarm over a raw count? || A rate stays meaningful as traffic changes, avoiding false alarms at peaks and missed ones at quiet times.
@end

@concept Custom metrics and the embedded metric format
@plain
Applications can publish their own metrics with `PutMetricData` or by writing JSON logs in the **Embedded Metric Format (EMF)**, which CloudWatch turns into metrics.
@problem
Business signals such as orders per minute or queue depth are not in AWS metrics.
@does
- `put-metric-data` takes namespace, name, dimensions, value and unit; each unique dimension set is billed as a metric, so avoid high-cardinality dimensions like user ID.
- EMF lines printed to stdout (picked up by the CloudWatch agent or Lambda) generate metrics without extra API calls.
- Prometheus metrics can be scraped by the CloudWatch agent or sent to Amazon Managed Service for Prometheus.
- Keep a small, reviewed set of SLO metrics: request rate, errors, latency, saturation.
@diagram flow
caption: App to metric
nodes:
  - "App|orders placed|app"
  - "EMF log line or PutMetricData|publish|info"
  - "CloudWatch metric|Shop/Orders|cp"
  - "Alarm and dashboard|use it|ok"
@h Publish
```bash title="Publish a custom metric" lab
aws cloudwatch put-metric-data --namespace Shop --metric-name OrdersPlaced \
  --dimensions Environment=prod --value 12 --unit Count
```
```json title="EMF log line"
{
  "_aws": {
    "Timestamp": 1761826800000,
    "CloudWatchMetrics": [
      {"Namespace": "Shop", "Dimensions": [["Environment"]], "Metrics": [{"Name": "OrdersPlaced", "Unit": "Count"}]}
    ]
  },
  "Environment": "prod",
  "OrdersPlaced": 12
}
```
@check
Why avoid user IDs as dimensions? || Each unique dimension value creates a new billable metric, causing huge cost and unusable dashboards.
@end

@concept Dashboards and notification routing
@plain
Dashboards show golden signals across services; SNS and AWS Chatbot route alarms to people.
@problem
During an incident people need one place to see health and the right channel to learn about failures.
@does
- Build a dashboard per service: traffic, errors, latency (p50 and p99), saturation, plus dependencies (RDS, Redis).
- SNS topics fan out to email, SMS, HTTPS, Lambda, and AWS Chatbot for Slack or Teams.
- Separate topics by severity: page for customer impact, ticket for the rest.
- Cross-account observability links monitoring and workload accounts into one view.
- Define dashboards as code (JSON or Terraform) so they are reviewed and recreated.
@diagram layers
caption: Alerting tiers
layers:
  - {label: "Page", nodes: ["Composite alarm|user impact|bad", "SNS to pager|immediate|bad"]}
  - {label: "Ticket", nodes: ["Capacity warnings|disk, quotas|warn", "SNS to ticketing|business hours|warn"]}
  - {label: "Info", nodes: ["Dashboards|trend review|info"]}
@h Topic
```bash title="SNS topic with email subscription" nocheck
aws sns create-topic --name ops-alerts
aws sns subscribe --topic-arn arn:aws:sns:us-east-1:111122223333:ops-alerts --protocol email --notification-endpoint oncall@example.com
aws cloudwatch put-dashboard --dashboard-name shop --dashboard-body file://dashboard.json
```
@check
What should page a human? || Customer-impacting symptoms such as error rate or latency SLO breaches, not every resource warning.
@end
