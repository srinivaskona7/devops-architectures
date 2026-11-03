---
title: Cost visibility with Cost Explorer, CUR and tagging
minutes: 45
objectives:
  - Read Cost Explorer with the right cost type and grouping
  - Activate cost allocation tags and enforce a tagging standard
  - Query the Cost and Usage Report with Athena or Data Exports
---
You cannot reduce what you cannot attribute. Cost management starts with seeing who spends what, and that depends on tags and the right reports.

@concept Billing basics and cost types
@plain
AWS bills monthly per payer account, with usage priced by unit (instance-hour, GB-month, request). Different **cost types** answer different questions.
@problem
Numbers differ between reports because of amortisation, credits and refunds, and teams argue over which is right.
@does
- **Unblended**: what was charged on the day of use. **Blended**: averaged across the organisation. **Amortized**: spreads upfront Savings Plan and RI fees across the term. **Net amortized**: includes discounts.
- Use amortized or net amortized for team showback, unblended to reconcile invoices.
- Consolidated billing in an Organization shares volume discounts and commitments across accounts.
- Data in Cost Explorer lags by up to a day.
@diagram cmp
caption: Which cost type
cards:
  - {h: "Unblended", kind: info, items: ["Matches the invoice day", "Upfront fees appear once"]}
  - {h: "Amortized", kind: ok, items: ["Spreads upfront fees", "Best for showback"]}
  - {h: "Net amortized", kind: app, items: ["Also applies discounts", "Closest to true cost"]}
@h Query
```bash title="Monthly cost by service" lab
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-11-01 \
  --granularity MONTHLY --metrics AmortizedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.AmortizedCost.Amount]' --output text | sort -k2 -nr | head
```
@check
Which cost type suits team showback of Savings Plans? || Amortized (or net amortized), because upfront fees are spread across the term.
@end

@concept Cost Explorer
@plain
Cost Explorer is the console and API to explore costs and usage over time, filtered and grouped by service, account, Region, usage type, tag and more.
@problem
You need to find the biggest drivers and changes quickly without exporting data.
@does
- Group by **Service** first, then drill into **Usage type** (for example `NatGateway-Bytes`, `DataTransfer-Regional-Bytes`, `BoxUsage`).
- Compare periods and use the forecast for month end.
- Filters by linked account and tag give team views; saved reports keep them.
- Hourly and resource-level granularity are optional (extra cost) for deep dives.
- The `get-cost-and-usage` API costs a small amount per request.
@diagram flow
caption: Investigation path
numbered: true
nodes:
  - "Group by service|find top spend|info"
  - "Group by usage type|NAT, transfer, instance|app"
  - "Filter by tag or account|which team|warn"
  - "Action|fix or tune|ok"
@h Usage type breakdown
```bash title="Top usage types for EC2 and VPC" nocheck
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-11-01 --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=USAGE_TYPE \
  --filter '{"Dimensions":{"Key":"SERVICE","Values":["Amazon Elastic Compute Cloud - Compute","Amazon Virtual Private Cloud"]}}' \
  --query 'ResultsByTime[0].Groups[?Metrics.UnblendedCost.Amount>`50`].[Keys[0],Metrics.UnblendedCost.Amount]' --output table
```
@check
Which grouping reveals NAT gateway data charges? || Usage type, such as NatGateway-Bytes.
@end

@concept Tagging strategy and cost allocation tags
@plain
Tags are key-value labels on resources. **Cost allocation tags** must be activated in the Billing console before they appear in cost reports, and they apply from activation forward.
@problem
Without tags, shared accounts produce one big number with no owner.
@does
- Standard keys: `Owner`, `CostCenter`, `Environment`, `Application`, `Team`. Keep a short, documented list with fixed values.
- Enforce with **tag policies** (Organizations), SCPs requiring tags on create, Config rule `required-tags`, and Terraform `default_tags`.
- Kubernetes resources: AWS load balancers and EBS volumes inherit tags via controller flags (`--default-tags`), but pod cost needs EKS split cost allocation or a tool.
- **AWS-generated tags** (`aws:createdBy`) can also be activated.
@diagram flow
caption: From tag to report
numbered: true
nodes:
  - "Tag standard|keys and values|plain"
  - "Enforce|policy, SCP, Config|warn"
  - "Activate|cost allocation tags|info"
  - "Report|Explorer and CUR by tag|ok"
@h Terraform default tags
```hcl title="Provider-wide tags"
provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Application = "shop"
      Environment = "prod"
      CostCenter  = "cc-1234"
      Owner       = "platform-team"
    }
  }
}
```
```bash title="Activate tags" nocheck
aws ce update-cost-allocation-tags-status --cost-allocation-tags-status \
  TagKey=Application,Status=Active TagKey=CostCenter,Status=Active TagKey=Environment,Status=Active
aws ce list-cost-allocation-tags --status Active
```
@check
Do cost allocation tags apply to past costs? || No, only to usage after they are activated (backfill is a separate request).
@end

@concept Cost and Usage Report and Data Exports
@plain
The Cost and Usage Report (CUR) is the most detailed dataset: one row per resource per line item per hour or day, delivered to S3 as Parquet or CSV. **Data Exports** is the newer interface that also offers CUR 2.0 and FOCUS formats.
@problem
Cost Explorer cannot answer custom questions such as cost per pod label or per resource ID with joins to your CMDB.
@does
- Enable with resource IDs and hourly granularity for FinOps analysis.
- Query with Athena; a Glue crawler or the provided CloudFormation creates tables.
- Use columns `line_item_unblended_cost`, `line_item_usage_type`, `line_item_resource_id`, `resource_tags_user_*`, `savings_plan_savings_plan_effective_cost`.
- Dashboards: QuickSight (CUDOS, CID dashboards) or Grafana.
@diagram flow
caption: CUR pipeline
nodes:
  - "AWS billing|line items|ext"
  - "S3 bucket|Parquet files|cp"
  - "Athena and Glue|SQL|info"
  - "QuickSight or Grafana|dashboards|ok"
@h Athena query
```sql title="Cost by tag Application and service, last month" nocheck
SELECT resource_tags_user_application AS application,
       line_item_product_code AS service,
       ROUND(SUM(line_item_unblended_cost), 2) AS cost
FROM cur_database.cur_table
WHERE year = '2026' AND month = '10'
  AND line_item_line_item_type = 'Usage'
GROUP BY 1, 2
ORDER BY cost DESC
LIMIT 25;
```
@check
What does CUR give that Cost Explorer does not? || Line-item detail per resource and tag that you can join and query with SQL.
@end

@concept Kubernetes cost allocation
@plain
EKS bills for nodes and volumes, not pods. To attribute spend to teams you need to divide node cost by pod resource use.
@problem
Ten teams share a cluster; the bill shows EC2 and EBS only.
@does
- **Split cost allocation data for Amazon EKS** (enabled in Cost Management preferences) adds pod and namespace-level usage to CUR with Kubernetes labels as dimensions.
- Open source **OpenCost** or **Kubecost** compute per namespace, label and workload costs using Prometheus and AWS pricing.
- Allocate shared costs (control plane, system pods, idle) by an agreed rule: proportional to usage or even split.
- Requests (not usage) are the fair basis for reserved capacity; track idle as a metric.
- Label namespaces consistently: `team`, `cost-center`, `app`.
@diagram layers
caption: Allocation layers
layers:
  - {label: "Billed", nodes: ["EC2 nodes|per instance-hour|cp", "EBS and NAT|per GB and hour|cp"]}
  - {label: "Allocated", nodes: ["Namespace cost|by requests and usage|app", "Idle cost|unused capacity|warn", "Shared cost|control plane, add-ons|info"]}
  - {label: "Report", nodes: ["Showback by team|monthly|ok"]}
@h Install OpenCost
```bash title="Install OpenCost with Helm" nocheck
helm repo add opencost https://opencost.github.io/opencost-helm-chart
helm upgrade --install opencost opencost/opencost -n opencost --create-namespace
kubectl -n opencost port-forward svc/opencost 9090:9090
```
@check
Why can EC2 cost not be assigned to a team directly in a shared cluster? || Nodes run pods from many teams, so cost must be divided by pod resource use.
@end
