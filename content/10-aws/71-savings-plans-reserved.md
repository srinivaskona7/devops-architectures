---
title: Savings Plans, Reserved Instances and commitment strategy
minutes: 45
objectives:
  - Compare Compute and EC2 Instance Savings Plans with Reserved Instances
  - Size commitments from stable baseline usage and monitor coverage and utilisation
  - Cover databases and other services and avoid common mistakes
---
On-demand is flexible but expensive. If you know some usage will run for a year or more, a commitment gives a discount in exchange for a promise to spend.

@concept Pricing models at a glance
@plain
You can pay on-demand, commit to a steady spend, bid for spare capacity (Spot), or reserve specific capacity.
@problem
Using only on-demand pays the highest price for predictable load; committing too much wastes money on unused hours.
@does
- **On-demand**: no commitment, highest unit price.
- **Savings Plans**: commit to a USD per hour spend for 1 or 3 years; get discounted rates on matching usage.
- **Reserved Instances (RIs)**: commit to specific instance attributes; also discount; some offer capacity reservation (zonal).
- **Spot**: spare capacity at a deep discount, interruptible.
- Typical order of operation: reduce waste, rightsize, then commit to the stable baseline, then use Spot for flexible burst.
@diagram cmp
caption: Pricing options
cards:
  - {h: "On-demand", kind: warn, items: ["Flexible", "Highest price"]}
  - {h: "Savings Plans", kind: ok, items: ["USD per hour commitment", "Flexible across usage"]}
  - {h: "Reserved Instances", kind: app, items: ["Specific attributes", "Capacity option"]}
  - {h: "Spot", kind: info, items: ["Largest discount", "Interruptible"]}
@h Look at recommendations
```bash title="Savings Plans purchase recommendations" lab
aws ce get-savings-plans-purchase-recommendation --savings-plans-type COMPUTE_SP \
  --term-in-years ONE_YEAR --payment-option NO_UPFRONT --lookback-period-in-days THIRTY_DAYS \
  --query 'SavingsPlansPurchaseRecommendation.SavingsPlansPurchaseRecommendationSummary'
```
@check
What is the usual order: commit or rightsize first? || Rightsize first, then commit to the stable baseline.
@end

@concept Savings Plan types
@plain
Compute Savings Plans apply across EC2 families, Regions, OS, tenancy, Fargate and Lambda. EC2 Instance Savings Plans give a deeper discount for a chosen family in a Region. SageMaker and database plans also exist.
@problem
Karpenter and Fargate shift instance types constantly; a commitment tied to one instance type would go unused.
@does
- **Compute SP**: most flexible; fits EKS with Karpenter, Graviton migration, Fargate. Discount is lower than instance-specific options.
- **EC2 Instance SP**: commit to a family (like `m6i`) in a Region; flexible on size, OS and tenancy. Higher discount, less flexible.
- **Database Savings Plans** (check availability) cover some RDS and Aurora usage for flexibility across engines and instance types.
- Payment: all upfront, partial upfront, no upfront; more upfront gives a bigger discount.
- Commitment is hourly: unused commitment in an hour is lost; it does not carry over.
@diagram flow
caption: How a plan is applied each hour
nodes:
  - "Hourly usage|mixed EC2 and Fargate|app"
  - "Plan covers matching usage|up to the commitment|ok"
  - "Excess|billed on-demand|warn"
  - "Shortfall|commitment wasted|bad"
@h Purchase
```bash title="Buy a one-year compute plan (example)" nocheck
aws savingsplans create-savings-plan --savings-plan-offering-id <offering-id> --commitment 4.00 \
  --client-token "$(uuidgen)"
aws savingsplans describe-savings-plans --states active
```
@check
Which plan type suits Karpenter with changing instance types? || Compute Savings Plans.
@end

@concept Reserved Instances and what is left of them
@plain
RIs reserve a specific instance type, platform and scope (Regional or zonal) for 1 or 3 years. Standard RIs give the best discount; Convertible RIs can be exchanged.
@problem
Existing estates and some services (RDS, ElastiCache, OpenSearch, Redshift) still use RIs or reserved nodes.
@does
- **Regional RIs** apply to any AZ in the Region with size flexibility within a family (for Linux), no capacity reservation.
- **Zonal RIs** reserve capacity in one AZ.
- Standard RIs can be sold on the RI Marketplace; Convertible can be exchanged for equal or greater value.
- For EC2, Savings Plans are generally simpler; use RIs for RDS, ElastiCache and OpenSearch where Savings Plans do not apply (check the current list).
- Use **On-Demand Capacity Reservations** when you need guaranteed capacity without a term.
@diagram cmp
caption: Savings Plan versus RI
cards:
  - {h: "Savings Plan", kind: ok, items: ["Dollar commitment", "Covers Fargate and Lambda", "No capacity reservation"]}
  - {h: "Reserved Instance", kind: app, items: ["Instance attributes", "Covers RDS and ElastiCache", "Zonal reserves capacity"]}
@choose What to buy
Compute Savings Plan | EKS and EC2 with changing families, Fargate | you need guaranteed capacity in a zone
EC2 Instance Savings Plan | stable family and Region | you plan to migrate families soon
Reserved nodes for RDS or ElastiCache | stable database sizes | you may move to Aurora Serverless
Capacity Reservation | scheduled events needing capacity | you want a discount alone
@h RDS reservation
```bash title="Find reserved DB instance offerings" nocheck
aws rds describe-reserved-db-instances-offerings --db-instance-class db.r6g.large \
  --product-description postgresql --duration 31536000 --offering-type "No Upfront" \
  --query 'ReservedDBInstancesOfferings[].[ReservedDBInstancesOfferingId,FixedPrice,RecurringCharges[0].RecurringChargeAmount]'
```
@check
Which services still rely on reserved nodes rather than Savings Plans? || Typically RDS, ElastiCache and OpenSearch (check current coverage).
@end

@concept Sizing a commitment
@plain
Commit to the level of usage you are certain to have, not the average and certainly not the peak.
@problem
Overcommitting locks in waste for years; undercommitting leaves savings on the table.
@does
- Look at the **minimum hourly usage** over 30 to 90 days after rightsizing; commit up to about 70 to 80 percent of that baseline at first.
- Stagger purchases (for example quarterly) to spread expiry and adapt to change.
- Choose 1 year for uncertain workloads, 3 years for stable platforms.
- Account for planned migrations (Graviton, Aurora Serverless, Fargate) and shutdowns.
- Commitments are shared across the Organization by default; the management account can disable sharing for specific accounts.
@diagram layers
caption: Layering usage
layers:
  - {label: "Burst", nodes: ["Spot and on-demand|variable|warn"]}
  - {label: "Predictable", nodes: ["Savings Plan layer|committed baseline|ok"]}
  - {label: "Floor", nodes: ["Always-on minimum|first commitments|cp"]}
@h Check utilisation and coverage
```bash title="Savings Plans utilisation and coverage" nocheck
aws ce get-savings-plans-utilization --time-period Start=2026-10-01,End=2026-10-31 \
  --query 'Total.Utilization.UtilizationPercentage'
aws ce get-savings-plans-coverage --time-period Start=2026-10-01,End=2026-10-31 \
  --query 'SavingsPlansCoverages[].Coverage.CoveragePercentage' --output text
```
@check
What number should a first commitment be sized from? || The stable minimum hourly usage after rightsizing, not the average or the peak.
@end

@concept Monitoring and avoiding mistakes
@plain
Commitments need ongoing care: watch **utilisation** (are we using what we bought) and **coverage** (how much eligible usage is covered).
@problem
Team changes quietly drop usage and the commitment is wasted for months.
@does
- Alert when utilisation falls below about 95 percent or coverage below target using Budgets.
- Review expirations 60 days ahead; renew with fresh data.
- Common mistakes: buying before rightsizing, tying to one family before a Graviton move, forgetting non-production shutdown, ignoring Fargate/Lambda eligibility, committing in a member account that leaves the Organization.
- Understand that Savings Plans apply first to the usage with the highest discount.
- Consider third-party or AWS automation for rolling purchases, but keep human approval.
@diagram flow
caption: Control loop
nodes:
  - "Measure|coverage and utilisation|info"
  - "Alert|below target|warn"
  - "Adjust|buy or change usage|app"
  - "Review|quarterly|ok"
@h Budget for utilisation
```bash title="Savings Plans utilisation budget" nocheck
aws budgets create-budget --account-id 111122223333 --budget '{
  "BudgetName":"sp-utilization","BudgetType":"SAVINGS_PLANS_UTILIZATION","TimeUnit":"MONTHLY",
  "BudgetLimit":{"Amount":"95","Unit":"PERCENTAGE"}}' \
  --notifications-with-subscribers '[{"Notification":{"NotificationType":"ACTUAL","ComparisonOperator":"LESS_THAN","Threshold":95,"ThresholdType":"PERCENTAGE"},"Subscribers":[{"SubscriptionType":"EMAIL","Address":"finops@example.com"}]}]'
```
@check
What does low utilisation mean? || You are paying for commitment you are not using.
@end
