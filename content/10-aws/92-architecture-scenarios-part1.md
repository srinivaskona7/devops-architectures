---
title: Architecture scenarios part one
minutes: 60
objectives:
  - Design a static site, a three-tier web app, an event-driven pipeline and a batch system
  - Justify each service choice and estimate capacity with explicit arithmetic
  - Identify failure modes and cost drivers per scenario
---
Four worked scenarios applying the decision method. Each lists requirements, a design, a diagram, numbers and trade-offs. Prices are deliberately left symbolic; use the current price pages.

@concept How to read the scenarios
@plain
Each scenario starts with requirements, then picks services by the rules from the previous section, then checks failure and cost.
@problem
Memorising architectures does not transfer. Reasoning does.
@does
- Requirements: traffic, latency, availability, data, security.
- Design: smallest set of managed services.
- Numbers: estimate capacity with arithmetic, not guesses.
- Failure: what breaks first and how it recovers.
- Cost drivers: the two or three line items that dominate.
@diagram flow
caption: Template
numbered: true
nodes:
  - "Requirements|traffic and SLO|info"
  - "Design|managed first|app"
  - "Numbers|capacity and cost|warn"
  - "Failure review|what breaks|bad"
@h Quick capacity helper
```python title="capacity.py"
def concurrency(rps, avg_seconds):
    return rps * avg_seconds

print(concurrency(200, 0.25))
```
@check
200 requests per second at 250 ms average needs how much concurrency? || 200 x 0.25 = 50.
@end

@concept Scenario 1 Static website
@plain
A marketing site with global visitors, a few deployments per day and no server logic.
@problem
Servers for static files add patching, scaling and cost with no benefit.
@does
- S3 private bucket for files, CloudFront in front with Origin Access Control, ACM certificate in us-east-1, Route 53 alias.
- WAF only if abuse is a risk. CloudFront Function for redirects and SPA routing.
- Deploy by syncing to S3 and invalidating only unhashed files.
- Availability follows S3 and CloudFront; no AZ design needed.
- Cost drivers: data transfer out and requests. If 1 TB leaves per month, multiply 1,000 GB by the current per-GB rate.
@diagram flow
caption: Static site
nodes:
  - "Visitor|browser|ext"
  - "CloudFront|cache and TLS|cp"
  - "S3 bucket|private origin|ok"
  - "CI pipeline|sync on merge|app"
@h Deploy
```bash title="Publish" nocheck
aws s3 sync ./dist s3://example-site --delete --cache-control "public,max-age=31536000,immutable" --exclude index.html
aws s3 cp ./dist/index.html s3://example-site/index.html --cache-control "no-cache"
aws cloudfront create-invalidation --distribution-id E1ABCDEF12345 --paths "/index.html"
```
@check
Why give index.html a different cache header from hashed assets? || It must always revalidate, while hashed assets never change.
@end

@concept Scenario 2 Three-tier web application
@plain
A customer-facing web app: presentation, application and database tiers with 99.9 percent availability.
@problem
Single instances and public databases fail and get breached.
@does
- Edge: CloudFront and WAF. Entry: ALB in public subnets across 3 AZs.
- App: ECS on Fargate in private subnets, 3 tasks minimum, target tracking on CPU 60 percent.
- Data: Aurora PostgreSQL Multi-AZ with a reader, in isolated subnets; ElastiCache for sessions.
- Secrets in Secrets Manager; one NAT gateway per AZ or VPC endpoints for AWS services.
- Capacity: 600 requests per second peak at 100 ms average gives 60 concurrent requests. If a task handles 20 concurrent, you need 3 tasks, plus one extra for AZ loss = 4.
@diagram layers
caption: Three tier
layers:
  - {label: "Public", nodes: ["CloudFront and WAF|edge|ext", "ALB|3 AZs|cp"]}
  - {label: "Private", nodes: ["Fargate tasks|min 4|app", "ElastiCache|sessions|info"]}
  - {label: "Isolated", nodes: ["Aurora writer|AZ a|ok", "Aurora reader|AZ b|ok"]}
@h Capacity arithmetic
```python title="tiers.py"
import math
rps, seconds, per_task = 600, 0.1, 20
concurrent = rps * seconds
tasks = math.ceil(concurrent / per_task)
print(concurrent, tasks, tasks + 1)
```
@check
Why add one task beyond the computed count? || To keep capacity if one AZ is lost.
@end

@concept Scenario 3 Event-driven pipeline
@plain
Uploaded files trigger validation, enrichment and storage, with bursts of 10,000 files in minutes.
@problem
Synchronous processing times out and loses files under bursts.
@does
- S3 event to EventBridge, then SQS queue with a DLQ, then Lambda with reserved concurrency 50.
- Step Functions Express for multi-step enrichment or Standard if a human review is involved.
- Results in DynamoDB; failures to the DLQ with an alarm.
- Visibility timeout at least six times the function timeout; partial batch responses enabled.
- Throughput: 10,000 files, 2 seconds each, concurrency 50 gives 10,000 x 2 / 50 = 400 seconds, about 6.7 minutes.
@diagram flow
caption: Pipeline
nodes:
  - "S3 upload|object created|ext"
  - "EventBridge and SQS|buffer|cp"
  - "Lambda|50 concurrent|app"
  - "DynamoDB|results|ok"
  - "DLQ|failures|bad"
@h Verify
```python title="burst.py"
files, seconds, concurrency = 10000, 2, 50
total = files * seconds / concurrency
print(total, total / 60)
```
@check
What protects the database from the burst? || Reserved concurrency on the function plus the queue buffer.
@end

@concept Scenario 4 Batch processing
@plain
A nightly job processes 2 TB of data in under 3 hours using many short tasks.
@problem
A fixed fleet sits idle most of the day, and one big server is a single point of failure.
@does
- EventBridge Scheduler starts a Step Functions workflow; Distributed Map or AWS Batch fans out tasks on Fargate or EC2 Spot.
- Input and output in S3; checkpoints so Spot interruptions only repeat small chunks.
- Capacity: 2 TB in 200 chunks of 10 GB; each chunk takes 30 minutes on one vCPU task. With 40 parallel tasks, 200 / 40 = 5 waves x 30 minutes = 2.5 hours, within the 3 hour limit.
- Cost drivers: vCPU-hours (200 x 0.5 h = 100 vCPU-hours) times the Spot or on-demand rate.
@diagram flow
caption: Nightly batch
numbered: true
nodes:
  - "Scheduler|02 00 UTC|info"
  - "Step Functions|fan out chunks|cp"
  - "Spot tasks|40 parallel|app"
  - "S3 output|results|ok"
@h Arithmetic
```python title="batch.py"
chunks, parallel, minutes = 200, 40, 30
waves = chunks / parallel
print(waves, waves * minutes / 60, chunks * minutes / 60)
```
@check
How many vCPU-hours does the job use? || 200 chunks x 0.5 hour = 100 vCPU-hours.
@end

@concept Failure review and cost drivers
@plain
After the design, ask what breaks first, how you know, and what each costs.
@problem
Designs that look fine on paper hide single points of failure and surprise bills.
@does
- Static site: origin bucket deletion is the main risk, so enable versioning and replication.
- Three-tier: database failover time and connection storms; use RDS Proxy if connections spike.
- Pipeline: poison messages and throttling; DLQ and alarms.
- Batch: Spot interruptions; checkpoints and retries.
- Largest cost lines usually: data transfer, NAT gateways, always-on databases, and logs.
@diagram cmp
caption: First failures
cards:
  - {h: "Static", kind: info, items: ["Bucket deletion", "Stale cache"]}
  - {h: "Three tier", kind: warn, items: ["DB failover", "Connection storm"]}
  - {h: "Pipeline", kind: bad, items: ["Poison message", "Throttling"]}
  - {h: "Batch", kind: info, items: ["Spot interruption", "Straggler tasks"]}
@h Alarm on DLQ depth
```hcl title="dlq-alarm.tf"
resource "aws_cloudwatch_metric_alarm" "dlq" {
  alarm_name          = "orders-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = "orders-dlq" }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
}
```
@end
