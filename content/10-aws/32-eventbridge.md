---
title: Amazon EventBridge
minutes: 50
objectives:
  - Route events with buses and rules using event patterns
  - Use Pipes and Scheduler for point to point integration and timed jobs
  - Add archive, replay, retries and dead letter queues for reliable delivery
---
EventBridge is the serverless event router of AWS. Producers emit events, rules match them, and targets react, without producers knowing who listens.

@concept Events, buses and rules
@plain
An **event** is a JSON record of something that happened. An **event bus** receives events. A **rule** matches events by pattern and sends them to **targets**.
@problem
Direct calls between services couple them tightly; adding a new consumer means changing the producer.
@does
- The **default bus** receives events from AWS services. **Custom buses** carry your application events. **Partner buses** receive SaaS events.
- A rule has an event pattern (or a schedule) and up to five targets (check the current quota).
- Targets include Lambda, SQS, SNS, Step Functions, ECS tasks, API destinations, another bus, Kinesis and many more.
- Delivery is at least once; consumers must be idempotent.
@diagram flow
caption: Event routing
nodes:
  - "Producer|app or AWS service|app"
  - "Event bus|custom or default|cp"
  - "Rule|pattern match|info"
  - "Targets|Lambda, SQS, Step Functions|ok"
@h A custom bus and rule
```hcl title="bus.tf"
resource "aws_cloudwatch_event_bus" "shop" {
  name = "shop"
}

resource "aws_cloudwatch_event_rule" "order_created" {
  name           = "order-created"
  event_bus_name = aws_cloudwatch_event_bus.shop.name
  event_pattern = jsonencode({
    source        = ["shop.orders"]
    "detail-type" = ["OrderCreated"]
  })
}

resource "aws_cloudwatch_event_target" "to_queue" {
  rule           = aws_cloudwatch_event_rule.order_created.name
  event_bus_name = aws_cloudwatch_event_bus.shop.name
  arn            = aws_sqs_queue.fulfilment.arn
}
```
@check
Does the producer need to know the consumers? || No. It only publishes to the bus.
@end

@concept Event patterns
@plain
An **event pattern** is a JSON document that lists the fields and values an event must have to match.
@problem
Targets should receive only the events they care about, filtered before invocation so you do not pay to discard them.
@does
- Match on exact values, arrays (any of), `prefix`, `suffix`, `anything-but`, `numeric`, `exists`, `cidr` and `wildcard`.
- All named fields must match (AND); values inside an array are OR.
- Test patterns with the console sandbox or `aws events test-event-pattern`.
- Content filtering at the rule saves downstream cost compared with filtering in code.
@diagram flow
caption: Pattern evaluation
nodes:
  - "Event|JSON document|plain"
  - "Pattern|fields and operators|info"
  - "Match|yes goes to targets|ok"
  - "No match|dropped|warn"
@h Pattern with numeric filter
```json title="pattern.json"
{
  "source": ["shop.orders"],
  "detail-type": ["OrderCreated"],
  "detail": {
    "total": [{"numeric": [">=", 100]}],
    "country": [{"anything-but": ["XX"]}]
  }
}
```
```bash title="Test a pattern" nocheck
aws events test-event-pattern --event-pattern file://pattern.json --event file://event.json
```
@check
Within one field, are listed values AND or OR? || OR. Different fields are combined with AND.
@end

@concept Targets, input transformation and retries
@plain
Each target can reshape the event with an **input transformer**, and EventBridge retries failed deliveries before giving up.
@problem
Targets need a specific payload, and temporary failures should not lose events.
@does
- Input transformer picks fields with JSON paths and builds a template.
- Retry policy: maximum event age (up to 24 hours) and attempts (up to 185). Check the current limits.
- Attach a **dead letter queue** (SQS) per target to capture undeliverable events.
- Targets need an IAM role (for Step Functions, ECS, Kinesis) or a resource policy (Lambda, SQS, SNS).
@diagram flow
caption: Delivery with retry
nodes:
  - "Rule matches|event|info"
  - "Deliver|to target|app"
  - "Retry|backoff up to max age|warn"
  - "DLQ|SQS for failed events|bad"
@h Target with DLQ
```hcl title="target-dlq.tf"
resource "aws_cloudwatch_event_target" "fn" {
  rule           = aws_cloudwatch_event_rule.order_created.name
  event_bus_name = aws_cloudwatch_event_bus.shop.name
  arn            = aws_lambda_function.fulfil.arn
  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 5
  }
  dead_letter_config {
    arn = aws_sqs_queue.eventbridge_dlq.arn
  }
}
```
:::warn
The DLQ queue policy must allow events.amazonaws.com to send messages or failures are lost silently.
:::
@end

@concept Cross-account and cross-Region buses
@plain
A bus can receive events from other accounts and Regions and forward events to another bus.
@problem
Central teams want a single place for audit or integration events, and multi-account organisations need controlled sharing.
@does
- A **resource policy** on the receiving bus allows specific accounts or an Organization (`aws:PrincipalOrgID`).
- A rule with a bus target forwards matching events; the sender needs a role to put events.
- Global endpoints with Route 53 health checks provide failover of event ingestion between two Regions.
- Keep the pattern narrow at the sender to limit cross-account volume.
@diagram flow
caption: Central bus
nodes:
  - "Workload account|rule forwards|app"
  - "Central bus|resource policy by org|cp"
  - "Security account|rules and targets|ok"
@h Bus policy by organization
```json title="bus-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "AllowOrg",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "events:PutEvents",
    "Resource": "arn:aws:events:eu-west-1:111122223333:event-bus/central",
    "Condition": {"StringEquals": {"aws:PrincipalOrgID": "o-exampleorgid"}}
  }]
}
```
@check
How do you let every account in your organization send to a bus? || A bus resource policy with an aws:PrincipalOrgID condition.
@end

@concept Archive and replay, schema registry
@plain
An **archive** stores events from a bus so you can **replay** them later. The **schema registry** discovers and stores event shapes.
@problem
After a bug or when adding a new consumer, you need to reprocess past events, and developers need to know the event structure.
@does
- Archives filter by pattern and have a retention period.
- Replay sends archived events in a time window to chosen rules; replayed events carry a replay marker, so make consumers idempotent.
- Schema discovery records event schemas and can generate code bindings.
- Use versioned `detail-type` values such as `OrderCreated.v2` for evolution.
@diagram flow
caption: Replay flow
nodes:
  - "Bus|live events|cp"
  - "Archive|stored with retention|info"
  - "Replay|time window|warn"
  - "Rule|reprocess|ok"
@h Create an archive
```bash title="Archive" nocheck
aws events create-archive --archive-name shop-all --event-source-arn arn:aws:events:eu-west-1:111122223333:event-bus/shop --retention-days 30
```
@end

@concept EventBridge Pipes
@plain
A **pipe** connects one source to one target, with optional filtering, enrichment and transformation in between.
@problem
Gluing a queue or stream to a target with a Lambda function adds code to maintain.
@does
- Sources: SQS, Kinesis, DynamoDB Streams, MSK, self-managed Kafka, MQ.
- Optional filter, then optional enrichment (Lambda, API Gateway, Step Functions or API destination), then the target.
- Handles batching, polling and partial failures for you.
- Use Pipes for point to point and buses for many to many.
@diagram flow
caption: A pipe
numbered: true
nodes:
  - "Source|SQS or stream|info"
  - "Filter|drop unwanted|warn"
  - "Enrich|Lambda call|app"
  - "Target|Step Functions or bus|ok"
@h Pipe from SQS to Step Functions
```hcl title="pipe.tf"
resource "aws_pipes_pipe" "orders" {
  name     = "orders-to-workflow"
  role_arn = aws_iam_role.pipe.arn
  source   = aws_sqs_queue.orders.arn
  target   = aws_sfn_state_machine.orders.arn
  source_parameters {
    sqs_queue_parameters {
      batch_size = 1
    }
  }
}
```
@check
Bus or pipe for one queue feeding one workflow? || A pipe.
@end

@concept EventBridge Scheduler
@plain
**Scheduler** runs one-time or recurring schedules using cron, rate or `at()` expressions and calls over 270 services directly.
@problem
Cron on a server is a single point of failure and old EventBridge scheduled rules do not scale to millions of per-customer timers.
@does
- Time zones and flexible time windows are supported.
- Schedules live in **schedule groups**. Each has a target, role, retry policy and optional DLQ.
- One-time schedules can auto-delete after running.
- Replaces ad-hoc scheduled rules for new work; check the current quota on schedules per account.
@diagram flow
caption: Timed work
nodes:
  - "Schedule|cron or at|info"
  - "Scheduler|retries and DLQ|cp"
  - "Target|Lambda, ECS, SQS, API|app"
@h Nightly Lambda
```hcl title="schedule.tf"
resource "aws_scheduler_schedule" "nightly" {
  name                         = "nightly-report"
  schedule_expression          = "cron(0 2 * * ? *)"
  schedule_expression_timezone = "Europe/London"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.report.arn
    role_arn = aws_iam_role.scheduler.arn
  }
}
```
@end

@concept API destinations and operations
@plain
**API destinations** let a rule call any HTTPS endpoint with managed authentication and rate limiting.
@problem
You want to push events to a SaaS webhook without writing and hosting a forwarding function.
@does
- A **connection** stores credentials (basic, API key, OAuth) in Secrets Manager managed by EventBridge.
- The destination sets the endpoint, method and an invocation rate limit.
- Monitor `FailedInvocations`, `ThrottledRules`, `InvocationsFailedToBeSentToDlq` and target DLQ depth.
- CloudTrail data events can audit PutEvents if needed.
@diagram flow
caption: Webhook delivery
nodes:
  - "Rule|matches event|info"
  - "API destination|rate limited|cp"
  - "Connection|auth in Secrets Manager|env"
  - "SaaS endpoint|HTTPS|ext"
@h Alarm on failures
```hcl title="alarm.tf"
resource "aws_cloudwatch_metric_alarm" "eb_failed" {
  alarm_name          = "eventbridge-failed-invocations"
  namespace           = "AWS/Events"
  metric_name         = "FailedInvocations"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
}
```
@check
Where are OAuth secrets for an API destination kept? || In a connection, stored by EventBridge in Secrets Manager.
@end
