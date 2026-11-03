---
title: Lambda packaging, event sources and operations
minutes: 55
objectives:
  - Package functions as zip, layers or container images and choose between them
  - Match event sources to synchronous, asynchronous and polling invocation
  - Observe and cost-control Lambda in production including SnapStart
---
Once a function runs, the next questions are how to package it, what triggers it, and how to operate it safely.

@concept Zip packages and layers
@plain
A zip package holds your code and dependencies. A **layer** is a separate zip that is mounted under `/opt` and shared between functions.
@problem
Copying the same large library into every function makes deployments slow and hard to patch.
@does
- Zip limit is 50 MB zipped direct upload and 250 MB unzipped including layers (check the current quota).
- Up to five layers per function. Layers are versioned and immutable.
- Good for shared SDKs, extensions and binaries. Poor for fast-changing business code.
- A layer update does not change existing functions until they are updated to the new layer version.
@diagram layers
caption: What is inside an environment
layers:
  - {label: "Your code", nodes: ["Function zip|handler and app logic|app"]}
  - {label: "Layers under /opt", nodes: ["Shared library|versioned|info", "Extension|telemetry agent|info"]}
  - {label: "Managed", nodes: ["Runtime|Python, Node.js, Java and others|cp"]}
@h Publish a layer
```bash title="Publish and attach" nocheck
aws lambda publish-layer-version --layer-name common-utils \
  --zip-file fileb://layer.zip --compatible-runtimes python3.12
aws lambda update-function-configuration --function-name orders \
  --layers arn:aws:lambda:eu-west-1:111122223333:layer:common-utils:4
```
@check
Does publishing a new layer version update the functions that use it? || No. Each function must be updated to reference the new version.
@end

@concept Container image functions
@plain
Lambda can run a container image up to 10 GB stored in Amazon ECR instead of a zip.
@problem
Large machine learning libraries, custom OS packages or existing container build pipelines do not fit the zip limits or workflow.
@does
- Base on an AWS provided Lambda base image or add the Runtime Interface Client to your own image.
- Same execution model as zip: still one request at a time, still a cold start, but images are cached lazily so large images start reasonably.
- Scan in ECR and sign images like any other container.
- Not the same as running a long-lived container. Use ECS or Fargate for that.
@diagram flow
caption: Image to function
nodes:
  - "Dockerfile|Lambda base image|app"
  - "ECR|private repository|info"
  - "Function|PackageType Image|cp"
@h Example Dockerfile
```dockerfile title="Dockerfile" nocheck
FROM public.ecr.aws/lambda/python:3.12
COPY requirements.txt ${LAMBDA_TASK_ROOT}
RUN pip install -r requirements.txt
COPY app.py ${LAMBDA_TASK_ROOT}
CMD ["app.handler"]
```
@end

@concept Synchronous, asynchronous and polling invocation
@plain
There are three ways Lambda is invoked, and each has different retry behaviour.
@problem
Wrong assumptions about retries cause duplicate processing or lost events.
@does
- **Synchronous** (API Gateway, ALB, function URL, SDK `RequestResponse`): caller waits and handles errors itself.
- **Asynchronous** (S3, SNS, EventBridge): Lambda queues the event, retries failed runs twice by default, and can send failures to a destination or DLQ.
- **Polling** (SQS, Kinesis, DynamoDB Streams, Kafka): the Lambda service polls and invokes with batches; retries follow the source semantics.
- Assume at-least-once delivery. Make handlers idempotent.
@diagram cmp
caption: Invocation types
cards:
  - {h: "Synchronous", kind: app, items: ["Caller waits", "Caller retries", "API Gateway, ALB"]}
  - {h: "Asynchronous", kind: info, items: ["Internal queue", "Two retries by default", "Destinations on failure"]}
  - {h: "Polling", kind: cp, items: ["Lambda reads source", "Batches", "SQS, Kinesis, streams"]}
@h Async failure destination
```bash title="Send failures to SQS" nocheck
aws lambda put-function-event-invoke-config --function-name orders \
  --maximum-retry-attempts 1 --maximum-event-age-in-seconds 3600 \
  --destination-config '{"OnFailure":{"Destination":"arn:aws:sqs:eu-west-1:111122223333:orders-failed"}}'
```
@check
Which invocation types retry automatically inside the Lambda service? || Asynchronous and polling. Synchronous callers must retry themselves.
@end

@concept SQS and stream event source mappings
@plain
An **event source mapping** is a Lambda-managed poller that reads a queue or stream and invokes your function with batches.
@problem
Writing your own consumer loop needs scaling, checkpointing and retry code.
@does
- SQS: configure `BatchSize`, `MaximumBatchingWindowInSeconds` and **partial batch response** so one bad message does not retry the whole batch.
- Set the queue visibility timeout to at least six times the function timeout, as AWS recommends.
- Kinesis and DynamoDB Streams: ordered per shard, with `BisectBatchOnFunctionError`, retry limits and an on-failure destination.
- Use `ScalingConfig.MaximumConcurrency` for SQS to protect a database.
@diagram flow
caption: Queue consumer
nodes:
  - "SQS queue|messages|info"
  - "Event source mapping|managed poller|cp"
  - "Function|batch of up to N|app"
  - "DLQ|after max receives|bad"
@h Mapping with partial batch
```hcl title="mapping.tf"
resource "aws_lambda_event_source_mapping" "orders" {
  event_source_arn        = aws_sqs_queue.orders.arn
  function_name           = aws_lambda_function.orders.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 20
  }
}
```
@end

@concept Function URLs and Lambda in a VPC
@plain
A **function URL** is a built-in HTTPS endpoint. A function can also attach to your VPC to reach private resources.
@problem
Simple webhooks do not need API Gateway, and some functions must reach a private database.
@does
- Function URL auth: `AWS_IAM` (SigV4) or `NONE` (public). It has no throttling, WAF or custom domain features of API Gateway; front with CloudFront if needed.
- VPC attachment creates network interfaces in your subnets using shared Hyperplane ENIs. Give at least two subnets in different AZs.
- A VPC function has no internet unless the subnet routes to a NAT gateway; use VPC endpoints for AWS services.
- Use RDS Proxy for relational databases to avoid connection storms.
@diagram flow
caption: Private data access
nodes:
  - "Function|attached to private subnets|app"
  - "RDS Proxy|pooled connections|cp"
  - "Database|private subnet|info"
  - "VPC endpoint|S3 or DynamoDB|ok"
@h Create a URL
```bash title="Function URL" nocheck
aws lambda create-function-url-config --function-name hook --auth-type AWS_IAM
```
@end

@concept SnapStart and runtime choices
@plain
**SnapStart** takes a snapshot of an initialised environment after the init phase and restores it for new environments, cutting cold start time.
@problem
Java and similar runtimes with long init are too slow on cold start for interactive APIs.
@does
- Enabled on published versions, for supported runtimes (check the current supported runtimes and regions).
- Code must be snapshot safe: do not cache unique values, network connections or random seeds created during init. Use runtime hooks to refresh.
- Alternative: provisioned concurrency, or a faster-starting runtime.
- Arm64 (Graviton) functions are usually cheaper per GB-second; check the current price and test your dependencies.
@diagram flow
caption: SnapStart idea
nodes:
  - "Publish version|run init once|app"
  - "Snapshot|memory and disk state|info"
  - "New environment|restore snapshot|ok"
@h Enable
```bash title="SnapStart" nocheck
aws lambda update-function-configuration --function-name orders-java \
  --snap-start ApplyOn=PublishedVersions
aws lambda publish-version --function-name orders-java
```
@check
Why must uniqueness-sensitive values be created after restore? || The snapshot is copied to many environments, so values made during init would be shared.
@end

@concept Observability and cost control
@plain
Lambda writes logs to CloudWatch Logs automatically, emits metrics, and supports X-Ray and OpenTelemetry tracing.
@problem
Short-lived functions leave nothing to log into after they are gone, and costs grow silently with invocations.
@does
- Key metrics: `Invocations`, `Errors`, `Throttles`, `Duration`, `ConcurrentExecutions`, `IteratorAge` for streams.
- Use structured JSON logging and set log retention; log groups never expire by default.
- Active tracing gives a service map through downstream calls.
- Cost levers: right-size memory, Arm64, shorter timeouts, batching, filter events at the source, avoid polling loops, and set log retention.
- Alarm on `Errors`, `Throttles` and p99 `Duration`.
@diagram flow
caption: Signals from a function
nodes:
  - "Function|runs|app"
  - "Logs|CloudWatch Logs|info"
  - "Metrics|errors and duration|info"
  - "Traces|X-Ray or OpenTelemetry|info"
  - "Alarm|page the team|warn"
@h Log retention and alarm
```hcl title="observability.tf"
resource "aws_cloudwatch_log_group" "orders" {
  name              = "/aws/lambda/orders"
  retention_in_days = 30
}

resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "orders-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = "orders" }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
}
```
@check
What two default behaviours of Lambda logs can quietly raise cost? || Log groups keep data forever and verbose logging per invocation adds ingestion charges.
@end
