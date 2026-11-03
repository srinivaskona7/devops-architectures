---
title: Trusted Advisor and Compute Optimizer
minutes: 40
objectives:
  - Use Trusted Advisor checks for cost, security, fault tolerance, performance and service limits
  - Read Compute Optimizer recommendations for EC2, EBS, Lambda, ECS on Fargate and Auto Scaling
  - Turn recommendations into automated, tracked improvements
---
AWS offers built-in advice. Trusted Advisor looks across the account for risks and waste. Compute Optimizer uses utilisation metrics to suggest better sizes.

@concept What Trusted Advisor checks
@plain
**Trusted Advisor** inspects your account against best practice checks in categories: cost optimization, performance, security, fault tolerance, service limits and operational excellence.
@problem
Teams do not know which of thousands of settings matter most.
@does
- Core checks are available to all accounts (for example S3 bucket permissions, security groups with unrestricted access, MFA on root, service quotas).
- The full check set requires a Business, Enterprise On-Ramp or Enterprise support plan (check the current plans).
- Findings show status (OK, warning, action needed), affected resources and recommended actions.
- Organizational view aggregates all accounts from the management or delegated administrator account.
@diagram cmp
caption: Check categories
cards:
  - {h: "Cost", kind: warn, items: ["Idle load balancers", "Unattached volumes", "Underused instances"]}
  - {h: "Security", kind: bad, items: ["Open security groups", "Root MFA", "Public snapshots"]}
  - {h: "Fault tolerance", kind: info, items: ["Backups", "Multi-AZ", "Health checks"]}
  - {h: "Service limits", kind: ok, items: ["Quota use over 80 percent", "Warnings before throttling"]}
@h Read checks
```bash title="Trusted Advisor via API" lab
aws support describe-trusted-advisor-checks --language en --region us-east-1 \
  --query 'checks[?category==`cost_optimizing`].[id,name]' --output table
```
@check
Which Trusted Advisor check category warns before you hit quotas? || Service limits.
@end

@concept Automating Trusted Advisor
@plain
Trusted Advisor publishes status changes to EventBridge, so findings can raise tickets or trigger remediation.
@problem
A dashboard nobody opens does not reduce risk.
@does
- The EventBridge event `Trusted Advisor Check Item Refresh Notification` carries the check and status.
- Route to SNS, chat or a ticket system, or invoke Lambda or SSM Automation to remediate.
- Weekly email summary and organizational reports to S3.
- Prioritise by severity and cost saving; track with an owner and a due date.
- Combine with Security Hub and Config for findings with automated fixes.
@diagram flow
caption: Alert path
nodes:
  - "Trusted Advisor|check changes|cp"
  - "EventBridge|rule on ERROR|info"
  - "SNS or ticket|notify owner|ok"
@h Rule
```hcl title="ta-rule.tf"
resource "aws_cloudwatch_event_rule" "ta" {
  name = "trusted-advisor-red"
  event_pattern = jsonencode({
    source        = ["aws.trustedadvisor"]
    "detail-type" = ["Trusted Advisor Check Item Refresh Notification"]
    detail        = { status = ["ERROR"] }
  })
}
```
:::note
Trusted Advisor events are delivered in us-east-1, so create this rule in that Region.
:::
@end

@concept How Compute Optimizer works
@plain
**Compute Optimizer** analyses CloudWatch utilisation history with machine learning and recommends better configurations.
@problem
Right-sizing by guesswork either wastes money or risks performance.
@does
- Covers EC2 instances, Auto Scaling groups, EBS volumes, Lambda functions, ECS services on Fargate, commercial software licences and RDS (check the current resource list).
- Needs opt-in, either per account or for the whole Organization.
- Default look-back is 14 days; enhanced infrastructure metrics extend to 93 days (paid) and memory metrics need the CloudWatch agent for EC2.
- Each finding is Under-provisioned, Over-provisioned or Optimized, with up to three options, expected savings and a performance risk score.
@diagram flow
caption: Recommendation flow
nodes:
  - "CloudWatch metrics|CPU, memory, I/O|info"
  - "Compute Optimizer|ML analysis|cp"
  - "Findings|over, under, optimized|warn"
  - "Change|resize with tests|ok"
@h Enable and read
```bash title="Compute Optimizer" lab
aws compute-optimizer update-enrollment-status --status Active
aws compute-optimizer get-ec2-instance-recommendations \
  --query 'instanceRecommendations[].[instanceArn,finding,recommendationOptions[0].instanceType]' --output table
```
@check
Which metric needs the CloudWatch agent for EC2 recommendations? || Memory utilisation.
@end

@concept Acting on recommendations safely
@plain
A recommendation is a hypothesis. Test it on a copy or in a canary before you change production.
@problem
Blindly applying a smaller size can break a latency-sensitive workload or one with spiky memory.
@does
- Check the performance risk score and the peak, not only the average.
- Change one tier of size at a time, watch p99 latency and error rates.
- For Auto Scaling groups change the launch template and use instance refresh.
- Lambda: use the recommended memory then confirm duration and cost with real traffic.
- Worked example: moving from `m5.2xlarge` to `m5.xlarge` halves vCPU and memory, so the hourly price is about half; for 20 instances at 730 hours check the saving as 20 x 730 x (old rate minus new rate) with current prices.
@diagram flow
caption: Safe right-sizing
numbered: true
nodes:
  - "Review finding|risk score|info"
  - "Test or canary|one instance|app"
  - "Watch p99 and errors|24 to 48 hours|warn"
  - "Roll out|instance refresh|ok"
@h Refresh after template change
```bash title="Instance refresh" nocheck
aws autoscaling start-instance-refresh --auto-scaling-group-name web \
  --preferences '{"MinHealthyPercentage":90,"InstanceWarmup":120}'
```
@end

@concept Cost Optimization Hub and Savings Plans
@plain
**Cost Optimization Hub** consolidates savings opportunities from many sources, including Compute Optimizer, idle resources and commitment recommendations.
@problem
Savings ideas are scattered across several consoles.
@does
- One list across accounts and Regions with estimated monthly savings and effort level.
- Includes rightsizing, idle resource deletion, Graviton migration, Savings Plans and Reserved Instance recommendations.
- Filter by account, tag or action type; export to S3 via Data Exports.
- Review commitment purchases together with rightsizing: rightsize first, then commit.
@diagram layers
caption: Where savings come from
layers:
  - {label: "Eliminate", nodes: ["Idle resources|delete|ok"]}
  - {label: "Right-size", nodes: ["Compute Optimizer|resize|info"]}
  - {label: "Commit", nodes: ["Savings Plans|after sizing|cp"]}
@choose Order of work
Delete idle first | resources have no traffic | they are quiet DR standbys
Right-size second | utilisation is consistently low | spiky workloads need headroom
Commit last | the baseline is stable | architecture changes are planned soon
@h Query recommendations
```bash title="Hub" lab
aws cost-optimization-hub list-recommendations --max-results 5
```
@check
Why rightsize before buying Savings Plans? || A commitment sized to wasteful usage locks in the waste.
@end

@concept Governance and reporting
@plain
Put recommendations into a regular review with owners, so improvements actually happen.
@problem
Recommendations pile up without accountability.
@does
- Assign each finding to the owning team by tag.
- Monthly review: top savings, security risks, quota warnings.
- Track realised savings versus estimated; keep an exceptions list with expiry.
- Feed into Well-Architected reviews and FinOps reporting.
- Use Organizations delegated administrators for Trusted Advisor, Compute Optimizer and Cost Optimization Hub so central teams see all accounts.
@diagram flow
caption: Review cycle
nodes:
  - "Collect|findings by account|cp"
  - "Assign|owner tags|info"
  - "Fix or accept|with expiry|app"
  - "Report|realised savings|ok"
@h Delegate administration
```bash title="Delegated admin" nocheck
aws organizations register-delegated-administrator --account-id 444455556666 \
  --service-principal compute-optimizer.amazonaws.com
```
@end
