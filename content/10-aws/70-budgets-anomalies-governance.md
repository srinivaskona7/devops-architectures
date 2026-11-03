---
title: Budgets, anomaly detection and cost governance
minutes: 40
objectives:
  - Create budgets with alerts and actions per account, tag and service
  - Detect unusual spend with Cost Anomaly Detection
  - Set up guardrails and a monthly FinOps routine
---
Bills should never surprise anyone. Budgets set expectations, anomaly detection finds surprises early, and guardrails stop expensive mistakes.

@concept AWS Budgets
@plain
A budget tracks cost, usage, Savings Plans coverage or utilisation against a target and sends alerts when actual or forecast spend crosses thresholds.
@problem
You only discover overspend when the invoice arrives.
@does
- Types: cost, usage, RI utilisation and coverage, Savings Plans utilisation and coverage.
- Filter by linked account, service, tag, Region.
- Alerts at actual 80 and 100 percent and forecasted 100 percent, via email, SNS or Chatbot.
- **Budget actions** can apply an IAM policy or SCP, or stop EC2/RDS instances when a threshold is crossed (with approval or automatically).
- The first two budgets are free; more cost per day (check current pricing).
@diagram flow
caption: Alert path
nodes:
  - "Budget 5000 USD|per month|info"
  - "Threshold|80 percent actual|warn"
  - "SNS and email|team notified|cp"
  - "Action|apply restricting policy|bad"
@h Create
```json title="budget.json"
{
  "BudgetName": "shop-monthly",
  "BudgetLimit": {"Amount": "5000", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST",
  "CostFilters": {"TagKeyValue": ["user:Application$shop"]}
}
```
```json title="notifications.json"
[
  {
    "Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN", "Threshold": 80, "ThresholdType": "PERCENTAGE"},
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "finops@example.com"}]
  },
  {
    "Notification": {"NotificationType": "FORECASTED", "ComparisonOperator": "GREATER_THAN", "Threshold": 100, "ThresholdType": "PERCENTAGE"},
    "Subscribers": [{"SubscriptionType": "EMAIL", "Address": "finops@example.com"}]
  }
]
```
```bash title="Apply" nocheck
aws budgets create-budget --account-id 111122223333 --budget file://budget.json --notifications-with-subscribers file://notifications.json
```
@check
What is the benefit of a forecasted alert? || It warns before the limit is actually reached.
@end

@concept Cost Anomaly Detection
@plain
Cost Anomaly Detection uses machine learning to flag unexpected spend by service, account, tag or cost category and ranks the likely root cause.
@problem
A misconfigured autoscaler or a data transfer storm can cost thousands in a day, long before month end.
@does
- **Monitors** define the scope (AWS services, linked accounts, cost allocation tag, cost category).
- **Subscriptions** send alerts above an absolute or percentage impact threshold, individually or as daily/weekly summaries.
- Each anomaly shows impact and root causes (service, account, Region, usage type).
- Free to use; pair with chat delivery for quick response.
@diagram flow
caption: From anomaly to fix
numbered: true
nodes:
  - "Monitor|services and accounts|info"
  - "Anomaly|spend spike detected|warn"
  - "Alert|SNS or Chatbot|cp"
  - "Investigate|usage type and resource|app"
  - "Fix|and add guardrail|ok"
@h Create
```bash title="Monitor by service with an alert subscription" nocheck
aws ce create-anomaly-monitor --anomaly-monitor '{"MonitorName":"services","MonitorType":"DIMENSIONAL","MonitorDimension":"SERVICE"}'
aws ce create-anomaly-subscription --anomaly-subscription '{
  "SubscriptionName":"finops-daily","Frequency":"DAILY",
  "MonitorArnList":["arn:aws:ce::111122223333:anomalymonitor/abcd"],
  "Subscribers":[{"Type":"EMAIL","Address":"finops@example.com"}],
  "ThresholdExpression":{"Dimensions":{"Key":"ANOMALY_TOTAL_IMPACT_ABSOLUTE","MatchOptions":["GREATER_THAN_OR_EQUAL"],"Values":["100"]}}}'
```
@check
What does a monitor define? || The scope of spend the anomaly detection model watches.
@end

@concept Guardrails against expensive mistakes
@plain
Prevention beats detection. Limit what can be created, where and how big.
@problem
One engineer launching a large GPU instance or an unrestricted autoscaling group can cost more than a month of normal spend.
@does
- SCP denying expensive instance families or Regions in sandbox accounts.
- Service Quotas as natural limits; keep them just above need.
- Karpenter NodePool `limits` and EKS node group max sizes.
- Auto-delete or shut down sandboxes on a schedule (AWS Instance Scheduler, Lambda, or `aws-nuke` style tools in sandbox only).
- S3 lifecycle rules, log retention and ECR lifecycle by default through modules.
- Review newly created resources with Config and tagging checks.
@diagram layers
caption: Preventive controls
layers:
  - {label: "Org", nodes: ["SCP|limit instance types and Regions|warn"]}
  - {label: "Platform", nodes: ["NodePool limits|cap cluster growth|warn", "Quotas|natural ceiling|warn"]}
  - {label: "Hygiene", nodes: ["Lifecycle rules|S3, logs, images|ok", "Scheduler|stop non-prod|ok"]}
@h SCP for sandbox
```json title="Deny large instance types in sandbox accounts"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyLargeInstances",
      "Effect": "Deny",
      "Action": "ec2:RunInstances",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {
        "StringNotLike": {"ec2:InstanceType": ["t3.*", "t4g.*", "m6i.large", "m6i.xlarge"]}
      }
    }
  ]
}
```
@check
Why use preventive controls as well as budgets? || Budgets alert after spend occurs; guardrails stop the expensive action first.
@end

@concept A monthly FinOps routine
@plain
FinOps is a habit: inform, optimise, operate. A short monthly review keeps spend aligned with value.
@problem
Cost work done once decays; usage and prices change.
@does
- Review top 10 cost drivers and change from last month; ask the owner for each increase.
- Track unit economics: cost per order, per request, per tenant, not only total.
- Check commitment coverage and utilisation, idle resources (unattached EBS, idle load balancers, old snapshots) and rightsizing recommendations.
- Record decisions and savings; set targets per team.
- Share dashboards with engineering so cost is a design input, not a finance surprise.
@diagram flow
caption: Cycle
numbered: true
nodes:
  - "Inform|reports and allocation|info"
  - "Optimise|rightsize, commit, Spot|app"
  - "Operate|budgets and reviews|warn"
  - "Repeat|monthly|ok"
@h Find idle resources
```bash title="Unattached EBS volumes and idle Elastic IPs" lab
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].[VolumeId,Size,CreateTime]' --output table
aws ec2 describe-addresses --query 'Addresses[?AssociationId==`null`].[PublicIp,AllocationId]' --output table
```
@check
What is a useful unit cost metric? || Cost per order, request or tenant, which ties spend to business value.
@end
