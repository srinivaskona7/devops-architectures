---
title: Which AWS service for which job
minutes: 50
objectives:
  - Choose compute, storage, database, messaging and networking services from requirements
  - Apply a repeatable decision method instead of picking familiar services
  - Record decisions and their trade-offs
---
With hundreds of services, the skill is narrowing quickly to two or three candidates and choosing with evidence. This section gives a method and decision tables.

@concept A decision method
@plain
Ask the same questions in the same order: what is the workload shape, what are the constraints, and what is the cheapest thing that meets them.
@problem
Teams choose by habit or hype, and then redesign when scale, cost or compliance arrives.
@does
- Step 1 workload shape: request response, event driven, batch, streaming, stateful.
- Step 2 constraints: latency, throughput, data residency, compliance, team skills, budget.
- Step 3 pick the most managed option that fits; move down to lower-level services only for a stated reason.
- Step 4 record the decision, rejected options and the trigger that would change it.
@diagram flow
caption: Method
numbered: true
nodes:
  - "Workload shape|traffic and state|info"
  - "Constraints|latency, cost, compliance|warn"
  - "Candidates|two or three|app"
  - "Decision record|why and when to revisit|ok"
@h A decision record
```yaml title="adr-0007.yaml"
id: ADR-0007
decision: Use ECS on Fargate for the orders API
context: Small team, steady web traffic, no Kubernetes expertise
options:
  - EKS rejected for operational overhead
  - Lambda rejected for steady high concurrency cost
revisit_when: more than 40 services or a need for custom operators
```
@check
What should a decision record include besides the choice? || Context, rejected options and the trigger to revisit.
@end

@concept Choosing compute
@plain
Compute ranges from functions to full servers. Move toward more control only when needed.
@problem
Running everything on EC2 is costly to operate, and running everything on Lambda hits limits.
@does
- **Lambda**: short, event driven, spiky; up to 15 minutes per invocation.
- **ECS on Fargate or App Runner**: containers without servers; steady services.
- **EKS**: Kubernetes ecosystem and portability.
- **EC2**: special hardware, licensing, full OS control, or heavy steady use with commitments.
- **Batch**: queued jobs on managed compute.
@diagram cmp
caption: Compute ladder
cards:
  - {h: "More managed", kind: ok, items: ["Lambda", "App Runner", "Fargate"]}
  - {h: "Middle", kind: info, items: ["EKS", "ECS on EC2", "AWS Batch"]}
  - {h: "More control", kind: warn, items: ["EC2", "Dedicated hosts", "Bare metal"]}
@choose Compute
Lambda | event driven, spiky, short tasks | steady high load or long running
Fargate | containers with a small team | GPUs or privileged mode
EKS | Kubernetes tooling is a requirement | no one can run upgrades
EC2 | special hardware or licences | you want no patching
@check
Which compute option supports tasks longer than 15 minutes without servers? || Fargate (ECS or Batch), not Lambda.
@end

@concept Choosing data stores
@plain
Pick the data store by access pattern first, then scale and consistency.
@problem
A relational database forced into a key lookup role, or the reverse, causes cost and pain.
@does
- **DynamoDB**: key based access at any scale, single-digit millisecond latency.
- **Aurora or RDS**: relational, joins, transactions.
- **ElastiCache**: caching and sessions.
- **S3**: objects and data lakes. **EFS or FSx**: shared files.
- **OpenSearch**: search and log analytics. **Redshift**: data warehouse.
- **Neptune, Timestream, DocumentDB, MemoryDB**: specialised patterns; check current fit.
@diagram flow
caption: Access pattern to store
nodes:
  - "Key lookup at scale|DynamoDB|ok"
  - "Joins and transactions|Aurora or RDS|app"
  - "Search or logs|OpenSearch|info"
  - "Analytics|Athena or Redshift|cp"
@choose Data
DynamoDB | known access patterns and huge scale | ad hoc queries and joins
Aurora | relational integrity and moderate scale | millions of writes per second on a key
S3 plus Athena | infrequent analytical queries | low-latency transactions
@end

@concept Choosing messaging and integration
@plain
Use queues for work, topics for fan-out, event buses for routing, streams for replay, and workflows for orchestration.
@problem
Using a stream where a queue is enough costs money, and using a queue where replay is needed loses data.
@does
- **SQS** buffer; **SNS** fan-out; **EventBridge** routing and SaaS events; **Kinesis or MSK** ordered replay; **Step Functions** orchestration; **API Gateway or AppSync** synchronous APIs.
- Keep each message small and idempotent; add DLQs everywhere.
@diagram cmp
caption: Integration
cards:
  - {h: "Work", kind: app, items: ["SQS", "Pull and retry", "DLQ"]}
  - {h: "Broadcast", kind: info, items: ["SNS or EventBridge", "Filters", "Many targets"]}
  - {h: "Replay", kind: cp, items: ["Kinesis or MSK", "Ordered", "Many readers"]}
  - {h: "Orchestrate", kind: ok, items: ["Step Functions", "Retries", "Human steps"]}
@check
Which service orchestrates multi-step workflows with retries and approvals? || Step Functions.
@end

@concept Choosing networking and edge
@plain
Pick network services by scope: inside a VPC, between VPCs, to on-premises, and to the internet.
@problem
Peering meshes and public endpoints for private traffic add risk and cost.
@does
- Same VPC: security groups, subnets. Service access: VPC endpoints.
- Between VPCs: peering for two, Transit Gateway for many, Lattice for application services, PrivateLink for one provider service.
- On-premises: VPN quick start, Direct Connect for steady bandwidth.
- Internet edge: CloudFront for HTTP, Global Accelerator for TCP or UDP and fixed IPs, Route 53 for DNS, WAF and Shield for protection.
@diagram layers
caption: Network scope
layers:
  - {label: "Edge", nodes: ["CloudFront|HTTP|ext", "Global Accelerator|TCP and UDP|ext"]}
  - {label: "Between networks", nodes: ["Transit Gateway|hub|cp", "Lattice|apps|cp", "PrivateLink|one service|cp"]}
  - {label: "Inside", nodes: ["VPC endpoints|AWS services|ok"]}
@choose Between VPCs
Peering | two VPCs, simple | many VPCs
Transit Gateway | many VPCs and on-premises | per-service authorisation
Lattice | app-level routing and IAM auth | raw network transit
@end

@concept Choosing security and governance services
@plain
Layer prevention, detection and response: SCPs and IAM prevent, Config and GuardDuty detect, Security Hub and automation respond.
@problem
Enabling tools without a model leaves gaps and alert fatigue.
@does
- Prevent: SCPs, IAM boundaries, VPC endpoints policies, Control Tower controls.
- Detect: CloudTrail, Config, GuardDuty, Inspector, Macie.
- Respond: Security Hub, EventBridge, Systems Manager Automation, Lambda.
- Protect data: KMS, Secrets Manager, S3 Block Public Access, backups with Vault Lock.
@diagram flow
caption: Control loop
nodes:
  - "Prevent|SCP and IAM|cp"
  - "Detect|Config and GuardDuty|info"
  - "Respond|Security Hub and Automation|warn"
  - "Learn|post incident|ok"
@h Org policy example
```json title="deny-regions.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Deny",
    "NotAction": ["iam:*", "organizations:*", "support:*", "cloudfront:*", "route53:*"],
    "Resource": "*",
    "Condition": {"StringNotEquals": {"aws:RequestedRegion": ["eu-west-1", "eu-central-1"]}}
  }]
}
```
@end

@concept Choosing observability and operations
@plain
Start with the managed tooling, then add third-party tooling where it fills a gap.
@problem
Teams pay for several overlapping monitoring tools while still missing key signals.
@does
- CloudWatch metrics, logs, alarms, Synthetics canaries and Application Signals for SLOs.
- X-Ray or OpenTelemetry for traces.
- Systems Manager for fleet operations; CloudTrail for API audit; Config for configuration history.
- Managed Prometheus and Grafana if you run Kubernetes and want the open source stack.
@diagram flow
caption: Signals
nodes:
  - "Metrics|CloudWatch or Prometheus|info"
  - "Logs|CloudWatch Logs|info"
  - "Traces|X-Ray or OTel|info"
  - "Alerts|alarms and on-call|warn"
@h Alarm to SNS
```hcl title="sns-alarm.tf"
resource "aws_cloudwatch_metric_alarm" "latency" {
  alarm_name          = "api-p99-latency"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p99"
  period              = 60
  evaluation_periods  = 5
  threshold           = 1
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.oncall.arn]
}
```
@check
Which services provide traces on AWS? || X-Ray, or OpenTelemetry through a collector.
@end
