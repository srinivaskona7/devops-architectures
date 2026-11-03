---
title: SQS and SNS messaging
minutes: 55
objectives:
  - Choose between standard and FIFO queues and topics
  - Tune visibility timeout, long polling and dead letter queues
  - Build SNS to SQS fan-out with filtering and correct policies
---
Queues decouple speed and failure between producers and consumers. Topics broadcast one message to many subscribers. Together they form the classic fan-out.

@concept SQS basics
@plain
**SQS** is a managed queue. Producers send messages, consumers poll and delete them after processing.
@problem
If a consumer is slow or down, a direct call loses work or blocks the caller.
@does
- Messages up to 1 MiB (check the current quota), retained 60 seconds to 14 days (default 4 days).
- Pay per request, with batching of up to 10 messages.
- **Long polling** (`ReceiveMessageWaitTimeSeconds` up to 20) cuts empty responses and cost.
- No servers, scales automatically, encrypted at rest with SSE-SQS by default or a KMS key.
@diagram flow
caption: Producer and consumer
numbered: true
nodes:
  - "Producer|SendMessage|app"
  - "Queue|durable storage|cp"
  - "Consumer|ReceiveMessage|app"
  - "Delete|after success|ok"
@h Create a queue
```hcl title="queue.tf"
resource "aws_sqs_queue" "orders" {
  name                       = "orders"
  receive_wait_time_seconds  = 20
  visibility_timeout_seconds = 60
  message_retention_seconds  = 345600
  sqs_managed_sse_enabled    = true
}
```
@check
Why use long polling? || It reduces empty receives, lowering cost and latency.
@end

@concept Visibility timeout
@plain
When a consumer receives a message it becomes invisible for the **visibility timeout**. If it is not deleted in time, it becomes visible again and another consumer may get it.
@problem
Without it two consumers would process the same message at once; with a value too short you get duplicates.
@does
- Default 30 seconds, maximum 12 hours.
- Set it longer than your worst case processing time. For Lambda consumers, AWS recommends at least six times the function timeout.
- A consumer can extend it with `ChangeMessageVisibility` for long jobs.
- Delivery is at least once for standard queues, so processing must be idempotent.
@diagram seq
caption: Timeout expiry
actors: ["Consumer A|slow|app", "Queue|SQS|cp", "Consumer B|second|app"]
steps:
  - "1>0: receive message | req"
  - "note 1..1: invisible for 30 s"
  - "1>2: timeout passes message returns | warn"
  - "1>2: receive same message | req"
  - "0>1: late delete fails | bad"
@h Extend while working
```bash title="Extend visibility" nocheck
aws sqs change-message-visibility --queue-url https://sqs.eu-west-1.amazonaws.com/111122223333/orders \
  --receipt-handle "$HANDLE" --visibility-timeout 300
```
@check
Lambda timeout is 30 s. What visibility timeout does AWS recommend at least? || 180 seconds, six times 30.
@end

@concept Standard versus FIFO queues
@plain
**Standard** queues give very high throughput with at-least-once delivery and best-effort ordering. **FIFO** queues keep order per message group and support deduplication.
@problem
Some workloads, such as ledger updates, need strict order and no duplicates; others only need speed.
@does
- FIFO name must end in `.fifo`.
- `MessageGroupId` defines the ordering lane. Messages in one group are processed one at a time, in order. Different groups run in parallel.
- Deduplication by `MessageDeduplicationId` or content hash within a five minute window.
- FIFO throughput is lower by default; high throughput mode raises it per group count (check the current quotas).
@diagram cmp
caption: Queue types
cards:
  - {h: "Standard", kind: app, items: ["Nearly unlimited throughput", "At least once", "Order not guaranteed"]}
  - {h: "FIFO", kind: cp, items: ["Order per group", "Deduplication", "Lower throughput", "Name ends .fifo"]}
@choose Queue type
Standard | throughput matters and handlers are idempotent | order is a hard requirement
FIFO | order per entity such as an account | you need huge parallelism in one group
@h FIFO queue
```hcl title="fifo.tf"
resource "aws_sqs_queue" "ledger" {
  name                        = "ledger.fifo"
  fifo_queue                  = true
  content_based_deduplication = true
}
```
@end

@concept Dead letter queues and redrive
@plain
A **dead letter queue (DLQ)** is another queue that receives messages that failed too many times.
@problem
A poison message can loop forever, wasting compute and blocking the rest of a FIFO group.
@does
- Redrive policy: `maxReceiveCount` and the DLQ ARN. A DLQ for a FIFO queue must be FIFO.
- DLQ retention should be longer than the source queue because the original enqueue time is kept.
- Alarm on `ApproximateNumberOfMessagesVisible` of the DLQ.
- **Redrive to source** moves messages back after you fix the bug.
@diagram flow
caption: Poison message path
nodes:
  - "Queue|message received|cp"
  - "Fails 5 times|maxReceiveCount|warn"
  - "DLQ|parked|bad"
  - "Redrive|after the fix|ok"
@h Redrive policy
```hcl title="dlq.tf"
resource "aws_sqs_queue" "orders_dlq" {
  name                      = "orders-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue_redrive_policy" "orders" {
  queue_url = aws_sqs_queue.orders.id
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = 5
  })
}
```
```bash title="Redrive" nocheck
aws sqs start-message-move-task --source-arn arn:aws:sqs:eu-west-1:111122223333:orders-dlq
```
@check
Why give the DLQ longer retention? || The message age counts from first enqueue, so a short DLQ retention could expire messages immediately.
@end

@concept SNS topics and subscriptions
@plain
**SNS** publishes a message to a topic, and every subscriber receives a copy.
@problem
One event often needs several reactions, such as email, queue and function, and the publisher should not loop over them.
@does
- Subscribers: SQS, Lambda, HTTPS, email, SMS, mobile push, Firehose.
- **FIFO topics** pair with FIFO queues for ordered fan-out.
- **Filter policies** on subscriptions send only matching messages, on attributes or body.
- Delivery retries and a subscription DLQ handle failures.
@diagram flow
caption: Fan-out
nodes:
  - "Publisher|one publish|app"
  - "SNS topic|copies to all|cp"
  - "SQS billing|filtered|ok"
  - "SQS shipping|filtered|ok"
  - "Lambda audit|all messages|info"
@h Topic with filtered subscription
```hcl title="sns.tf"
resource "aws_sns_topic" "orders" {
  name = "orders"
}

resource "aws_sns_topic_subscription" "billing" {
  topic_arn            = aws_sns_topic.orders.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.billing.arn
  raw_message_delivery = true
  filter_policy        = jsonencode({ type = ["paid"] })
}
```
@check
Which feature stops a subscriber receiving irrelevant messages? || A subscription filter policy.
@end

@concept Fan-out policy and permissions
@plain
SNS needs permission to send to a queue, and the queue policy is where most fan-out setups fail.
@problem
Messages published but never arriving is almost always a missing or too broad queue policy.
@does
- The queue policy allows `sns.amazonaws.com` to `sqs:SendMessage` with condition `aws:SourceArn` equal to the topic.
- Encrypted topics and queues need KMS key policy access for the service.
- Cross-account subscriptions need permission on both sides.
- Use raw message delivery to skip the SNS JSON envelope.
@diagram layers
caption: What must allow what
layers:
  - {label: "Topic side", nodes: ["Publish permission|publisher role|info"]}
  - {label: "Queue side", nodes: ["Queue policy|SNS may send from this topic|cp"]}
  - {label: "KMS if used", nodes: ["Key policy|sns and sqs usage|warn"]}
@h Queue policy
```json title="queue-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "sns.amazonaws.com"},
    "Action": "sqs:SendMessage",
    "Resource": "arn:aws:sqs:eu-west-1:111122223333:billing",
    "Condition": {"ArnEquals": {"aws:SourceArn": "arn:aws:sns:eu-west-1:111122223333:orders"}}
  }]
}
```
@end

@concept Choosing SQS, SNS, EventBridge and Kinesis
@plain
All four move data between components, but with different delivery models.
@problem
Picking the wrong one leads to lost ordering, missed replays or unnecessary cost.
@does
- **SQS**: one consumer group pulls work; buffering and retries.
- **SNS**: push fan-out to many subscribers, simple filtering.
- **EventBridge**: rich pattern routing, SaaS and AWS service events, schedules, archive and replay.
- **Kinesis or MSK**: ordered replayable streams read by many consumers at their own pace.
- Common combo: EventBridge or SNS to SQS per consumer, then Lambda.
@diagram cmp
caption: Messaging services
cards:
  - {h: "SQS", kind: app, items: ["Work queue", "Pull", "DLQ"]}
  - {h: "SNS", kind: info, items: ["Push fan-out", "Filter policy", "Many protocols"]}
  - {h: "EventBridge", kind: cp, items: ["Pattern routing", "Archive and replay", "SaaS events"]}
  - {h: "Kinesis", kind: ok, items: ["Ordered stream", "Replay window", "Many readers"]}
@choose Pick one
SQS | you need a buffer and retries for one worker pool | many independent subscribers need copies
SNS | simple push to several endpoints | you need replay or complex routing
EventBridge | routing across services and accounts | you need very high throughput of ordered records
Kinesis | ordered high volume records and several readers | a simple task queue is enough
@check
Which service retains a stream so a new consumer can read from the past? || Kinesis (or MSK). EventBridge offers archive and replay of events.
@end
