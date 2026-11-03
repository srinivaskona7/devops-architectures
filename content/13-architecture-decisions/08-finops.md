---
title: FinOps
minutes: 55
objectives:
  - Explain the FinOps cycle of inform, optimize and operate
  - Apply tagging, budgets, right-sizing and commitments with worked arithmetic
  - Build showback reports and unit cost metrics
---
FinOps is the practice of making cloud spend visible, owned and efficient. It is a team habit as much as a tool.

@concept The FinOps cycle
@plain
FinOps works in a loop: see what you spend, improve it, then keep it that way.
@problem
Cloud bills arrive after the money is spent and nobody feels responsible.
@does
- **Inform**: allocate costs to owners with tags or labels, show dashboards and forecasts.
- **Optimize**: remove waste, right-size, use commitments and cheaper capacity.
- **Operate**: set budgets, review monthly, build cost into design and pipelines.
- Engineering, finance and product share ownership.
@diagram flow
caption: The loop
nodes:
  - "Inform|who spends what|info"
  - "Optimize|waste and rates|app"
  - "Operate|budgets and reviews|ok"
@check
Who owns cloud cost? || Engineering, finance and product together.
@end

@concept Tagging and allocation
@plain
Tags (AWS, Azure) or labels (Google Cloud) attach owner and purpose to resources so costs can be split.
@problem
Untagged resources appear as one unexplained lump.
@does
- Minimum set: owner, team, environment, cost centre, application.
- Enforce by policy: block or flag resources missing tags. Account or project structure also gives allocation.
- Shared costs, such as networking and security tooling, are split by a rule such as proportional usage.
- Some resources and charges cannot be tagged, so measure the untagged share and drive it down.
@diagram cmp
caption: Allocated or not
cards:
  - {h: "Untagged", kind: bad, items: ["One big unknown bucket", "No owner to call", "Arguments at month end"]}
  - {h: "Tagged and enforced", kind: ok, items: ["Cost by team and app", "Clear owner", "Showback reports"]}
@h Enforce a tag in Terraform
```hcl title="tags.tf" nocheck
provider "aws" {
  region = "eu-west-1"
  default_tags {
    tags = {
      owner       = "payments-team"
      environment = "prod"
      cost_centre = "cc-1042"
    }
  }
}
```
@check
Why enforce tags by policy? || People forget, and untagged cost has no owner.
@end

@concept Budgets, alerts and anomaly detection
@plain
A budget is a spending limit with alerts. Anomaly detection flags unusual jumps.
@problem
A mistaken loop or forgotten GPU cluster can cost thousands in a weekend.
@does
- Budgets per account, project or tag. Alerts at thresholds such as 50, 80 and 100 percent, and on forecast.
- Notify the owner, not a shared mailbox nobody reads.
- Anomaly services (AWS Cost Anomaly Detection, Azure Cost Management anomaly alerts, Google Cloud budget alerts and anomaly features) catch spikes. Check current availability.
- Alerts do not stop spending by themselves. Hard stops need automation, used carefully.
@diagram flow
caption: Alert path
nodes:
  - "Spend rises|actual or forecast|warn"
  - "Threshold|80 percent|info"
  - "Notify owner|chat and email|app"
  - "Investigate|stop or accept|ok"
@h Threshold arithmetic
A monthly budget of 1,000: alerts at 50 percent = 500, 80 percent = 800, 100 percent = 1,000. A forecast alert fires when projected month-end spend exceeds 1,000. At day 10 of a 30-day month with 450 spent, the run rate gives 450 / 10 x 30 = 1,350, so a forecast alert would already fire.
```python title="forecast.py"
spent, day, days = 450, 10, 30
print(spent / day * days)
```
@check
When would a forecast alert fire in the example? || At day 10, because the projected 1,350 exceeds the 1,000 budget.
@end

@concept Right-sizing and waste removal
@plain
Right-sizing matches resource size to real use. Waste removal deletes what nobody uses.
@problem
Resources are sized for imagined peaks and never revisited.
@does
- Look at CPU, memory and network over weeks. Persistently under 20 percent peak usage suggests a smaller size.
- Find waste: unattached disks, old snapshots, idle load balancers, unused IPs, stopped instances with disks, oversized logs retention.
- Schedule non-production off outside working hours.
- Use storage lifecycle rules and cheaper tiers for cold data.
@diagram flow
caption: Right-size loop
numbered: true
nodes:
  - "Measure|weeks of usage|info"
  - "Propose|smaller or off|app"
  - "Test|staging first|warn"
  - "Apply|monitor|ok"
@h Scheduling saving
A dev cluster of 6 nodes at an example 0.20 per node-hour. Always on: 6 x 0.20 x 730 = 876.00 a month. Weekdays 10 hours x 22 days = 220 hours: 6 x 0.20 x 220 = 264.00. Saving 612.00 a month, 69.9 percent.
```python title="schedule.py"
always = 6 * 0.20 * 730
sched = 6 * 0.20 * 220
print(round(always, 2), round(sched, 2), round(always - sched, 2), round((always - sched) / always * 100, 1))
```
@check
How much of the 876.00 does scheduling save? || 612.00, which is 69.9 percent.
@end

@concept Commitments and discount models
@plain
You can lower the unit price by committing to steady usage, or by accepting interruption.
@problem
On-demand price is the highest. Steady workloads pay a premium for flexibility they do not need.
@does
- Commitments: AWS Savings Plans and Reserved Instances, Azure Reservations and Savings Plans, Google Cloud committed use discounts. Terms and flexibility change, so check current rules.
- Spot, preemptible or low-priority capacity: large discounts, can be reclaimed at short notice. Use for batch, CI, stateless workers.
- Commit only to the steady baseline, not the peak. Over-commitment wastes money.
- Review utilisation of commitments monthly.
@diagram layers
caption: Layers of demand
layers:
  - {label: "Peaks", nodes: ["On-demand|flexible, highest price|bad"]}
  - {label: "Variable", nodes: ["Spot or preemptible|cheap, interruptible|warn"]}
  - {label: "Baseline", nodes: ["Commitment|steady use, lower price|ok"]}
@h Commitment arithmetic
Steady baseline 40 instances, on-demand 0.10 per hour; a commitment gives an example 30 percent discount. Baseline on-demand: 40 x 0.10 x 730 = 2,920. Committed: 2,920 x 0.70 = 2,044. Saving 876 a month, 10,512 a year. If you committed to 60 instead and use only 40, you pay for 20 unused: 20 x 0.07 x 730 = 1,022 wasted monthly, which cancels the savings.
```python title="commit.py"
od = 40 * 0.10 * 730
print(od, od * 0.7, od * 0.3, od * 0.3 * 12)
print(20 * 0.07 * 730)
```
@choose Capacity type
On-demand | spiky or new workloads | usage is steady for a year
Commitment | steady baseline | the workload may disappear or move
Spot or preemptible | batch, CI, stateless workers | the job cannot restart
@check
What should you commit to? || The steady baseline, not the peak.
@end

@concept Unit economics and showback
@plain
Total spend alone says little. Cost per order, per user or per request shows whether spending is efficient.
@problem
Spend rises when business grows, and teams cannot tell good growth from waste.
@does
- Pick a unit: cost per thousand requests, per order, per active user.
- Divide allocated cost by units from the business data.
- Showback: report each team's cost to them. Chargeback: actually bill them. Start with showback.
- Track the trend in a dashboard reviewed monthly.
@diagram flow
caption: From bill to unit cost
nodes:
  - "Billing export|detailed line items|info"
  - "Allocation|tags and rules|app"
  - "Business metric|orders or users|app"
  - "Unit cost|cost per order|ok"
@h Worked example
Month one: cost 12,000 for 400,000 orders = 0.030 per order. Month two: cost 15,000 for 600,000 orders = 0.025 per order. Spend rose 25 percent, but unit cost fell 16.7 percent, which is healthy growth.
```python title="unit.py"
m1 = 12000 / 400000
m2 = 15000 / 600000
print(m1, m2, round((m2 - m1) / m1 * 100, 1))
```
@check
Did unit cost rise or fall in the example? || It fell about 16.7 percent, from 0.030 to 0.025 per order.
@end

@concept Cost in the delivery pipeline
@plain
Check cost before deploying, not after the bill.
@problem
A pull request can add an expensive resource and nobody notices.
@does
- Show estimated monthly change on pull requests (tools such as Infracost for Terraform).
- Policy: block resources above a size without approval.
- Sandbox accounts with hard budgets and automatic cleanup.
- Review the top ten cost drivers monthly and assign actions.
@diagram flow
caption: Cost check on a pull request
nodes:
  - "Pull request|infrastructure change|plain"
  - "Plan|resource list|info"
  - "Cost estimate|monthly difference|warn"
  - "Approval|if above limit|ok"
@h Pipeline step
```yaml title="cost-check.yml" nocheck
name: cost
on: pull_request
jobs:
  estimate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: infracost/actions/setup@v3
        with:
          api-key: ${{ secrets.INFRACOST_API_KEY }}
      - run: infracost breakdown --path . --format table
```
@check
Why estimate cost on the pull request? || It is cheapest to change a design before it is deployed.
@end
