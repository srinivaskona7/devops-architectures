---
title: Scaling policies and scheduled scaling
minutes: 45
objectives:
  - Choose between target tracking, step, simple, scheduled and predictive scaling
  - Configure target tracking on CPU and on load balancer requests per target
  - Tune cooldowns, warm-up and scale-in protection to avoid flapping
---
Policies decide when the ASG changes size. Picking the right metric matters more than the policy type.

@concept Target tracking
@plain
You choose a metric and a target value, such as 50 percent average CPU. AWS creates the alarms and adjusts capacity to hold the metric near the target.
@problem
Hand-built alarms and step sizes are hard to tune and often under- or over-react.
@does
- Predefined metrics: average CPU, network in and out, and `ALBRequestCountPerTarget`.
- Custom metrics are allowed, including metrics that fall as capacity rises (queue depth per instance).
- Scales out quickly and in conservatively; it will not scale in below what keeps the metric at target.
- Use several target tracking policies together; the ASG follows the one that gives the largest capacity.
@diagram flow
caption: Target tracking loop
nodes:
  - "Metric|CPU or requests per target|info"
  - "Auto-created alarms|high and low|cp"
  - "Capacity change|proportional to the gap|app"
  - "Metric near target|ok|ok"
@h Policies
```hcl title="tracking.tf"
resource "aws_autoscaling_policy" "cpu" {
  name                   = "cpu-50"
  autoscaling_group_name = aws_autoscaling_group.web.name
  policy_type            = "TargetTrackingScaling"
  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 50
  }
}

resource "aws_autoscaling_policy" "requests" {
  name                   = "requests-per-target"
  autoscaling_group_name = aws_autoscaling_group.web.name
  policy_type            = "TargetTrackingScaling"
  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = "${aws_lb.web.arn_suffix}/${aws_lb_target_group.web.arn_suffix}"
    }
    target_value = 500
  }
}
```
@check
Why prefer requests per target over CPU for web services? || It measures load directly, so scaling reacts before CPU saturates and works for IO-bound apps.
@end

@concept Step and simple scaling
@plain
**Step scaling** adds or removes a different amount depending on how far a CloudWatch alarm is breached. **Simple scaling** does one fixed action per alarm with a cooldown.
@problem
Some metrics, such as queue depth, need an action proportional to the breach.
@does
- Step: define steps like "queue 100 to 500: add 2; above 500: add 5". Alarms you write yourself.
- Simple scaling waits for the cooldown before acting again; step scaling uses **instance warm-up** instead and can respond continuously.
- Prefer target tracking; use step policies for custom, non-proportional metrics.
@diagram cmp
caption: Policy types
cards:
  - {h: "Target tracking", kind: ok, items: ["Hold a metric at a value", "Default choice"]}
  - {h: "Step", kind: info, items: ["Action size depends on breach", "You own the alarms"]}
  - {h: "Simple", kind: warn, items: ["One action then cooldown", "Mostly legacy"]}
@h Queue-based step scaling
```bash title="Step policy" lab
aws autoscaling put-scaling-policy --auto-scaling-group-name workers --policy-name queue-steps \
  --policy-type StepScaling --adjustment-type ChangeInCapacity --metric-aggregation-type Average \
  --estimated-instance-warmup 120 \
  --step-adjustments MetricIntervalLowerBound=0,MetricIntervalUpperBound=400,ScalingAdjustment=2 MetricIntervalLowerBound=400,ScalingAdjustment=5
```
@end

@concept Scaling on queue depth
@plain
For workers that read from SQS, the useful signal is backlog per instance, not CPU.
@problem
Workers may sit idle on CPU while a large queue builds, or be CPU-heavy with an empty queue.
@does
- Compute **backlog per instance** = `ApproximateNumberOfMessagesVisible` divided by running instances, and publish as a custom metric (or use metric math in the policy).
- Set a target such as acceptable backlog per instance (messages that one instance processes within the allowed latency).
- Combine with scale-in protection so a busy worker is not terminated mid-job, or handle SIGTERM and finish the message.
- In Kubernetes, KEDA does the equivalent for pods.
@diagram flow
caption: Queue driven scaling
nodes:
  - "SQS queue|visible messages|info"
  - "Metric math|messages per instance|cp"
  - "Target tracking|hold backlog target|app"
  - "Workers scale|drain the queue|ok"
@h Metric math target tracking
```json title="queue-target-tracking.json"
{
  "TargetValue": 20.0,
  "CustomizedMetricSpecification": {
    "Metrics": [
      {"Id": "m1", "Label": "visible", "ReturnData": false, "MetricStat": {"Metric": {"Namespace": "AWS/SQS", "MetricName": "ApproximateNumberOfMessagesVisible", "Dimensions": [{"Name": "QueueName", "Value": "jobs"}]}, "Stat": "Average"}},
      {"Id": "m2", "Label": "instances", "ReturnData": false, "MetricStat": {"Metric": {"Namespace": "AWS/AutoScaling", "MetricName": "GroupInServiceInstances", "Dimensions": [{"Name": "AutoScalingGroupName", "Value": "workers"}]}, "Stat": "Average"}},
      {"Id": "e1", "Label": "backlog per instance", "ReturnData": true, "Expression": "m1 / m2"}
    ]
  }
}
```
```bash title="Apply" lab
aws autoscaling put-scaling-policy --auto-scaling-group-name workers --policy-name backlog \
  --policy-type TargetTrackingScaling --target-tracking-configuration file://queue-target-tracking.json
```
:::note
`GroupInServiceInstances` requires group metrics collection to be enabled with `enable-metrics-collection`.
:::
@check
Which metric would you scale SQS workers on? || Backlog per instance (queue depth divided by instances), not CPU.
@end

@concept Scheduled and predictive scaling
@plain
**Scheduled actions** change capacity at set times. **Predictive scaling** learns daily and weekly patterns and scales ahead of load.
@problem
Reactive scaling lags behind a sudden known peak, such as a nine o'clock login surge.
@does
- Scheduled actions set min, max or desired using cron (UTC unless a time zone is given); use for known events and for turning off dev at night.
- Predictive scaling forecasts from at least a day of history (best with two weeks), and can run in forecast-only mode first.
- Combine: predictive sets a floor, target tracking handles surprises.
@diagram flow
caption: Layered scaling
nodes:
  - "Scheduled|known events|plain"
  - "Predictive|learned pattern|info"
  - "Target tracking|real time|app"
  - "Capacity|within min and max|ok"
@h Examples
```bash title="Scheduled actions" lab
aws autoscaling put-scheduled-update-group-action --auto-scaling-group-name web --scheduled-action-name weekday-up \
  --recurrence "0 7 * * 1-5" --time-zone "Europe/Dublin" --min-size 4 --desired-capacity 6
aws autoscaling put-scheduled-update-group-action --auto-scaling-group-name web --scheduled-action-name night-down \
  --recurrence "0 20 * * *" --time-zone "Europe/Dublin" --min-size 1 --desired-capacity 1
aws autoscaling describe-scheduled-actions --auto-scaling-group-name web --query 'ScheduledUpdateGroupActions[].[ScheduledActionName,Recurrence]'
```
@end

@concept Warm-up, cooldown and scale-in
@plain
Scaling decisions need time to take effect. Warm-up and cooldown stop the ASG from reacting twice to the same load.
@problem
New instances take minutes to boot. If the policy keeps counting their idle CPU, it concludes there is spare capacity and scales in too early (flapping).
@does
- **Default instance warmup** excludes new instances from metrics for a period; set it to your real time-to-serve.
- **Cooldown** pauses simple scaling after an action.
- **Scale-in protection** on instances and **termination policies** (`OldestLaunchTemplate`, `OldestInstance`, `Default`) shape who is removed.
- Scale in slowly, scale out fast. Alarm on `GroupInServiceInstances` and on scaling failures.
@diagram flow
caption: Avoiding flapping
numbered: true
nodes:
  - "Load rises|metric above target|warn"
  - "Scale out|instances launched|app"
  - "Warm-up|ignored by metrics|info"
  - "In service|counted|ok"
@h Settings
```bash title="Warm-up and termination policy" lab
aws autoscaling update-auto-scaling-group --auto-scaling-group-name web \
  --default-instance-warmup 180 --termination-policies OldestLaunchTemplate Default
aws autoscaling enable-metrics-collection --auto-scaling-group-name web --granularity 1Minute
```
@check
What happens if warm-up is shorter than boot time? || New instances report low load too early, so the ASG thinks it has surplus capacity and may scale in again.
@end
