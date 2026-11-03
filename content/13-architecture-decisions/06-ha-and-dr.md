---
title: High availability and disaster recovery
minutes: 60
objectives:
  - Convert availability percentages into allowed downtime with correct arithmetic
  - Define RTO and RPO and choose a recovery strategy to meet them
  - Plan and test failover with quotas, data replication and runbooks
---
High availability keeps service running through small failures. Disaster recovery restores service after a large one. They use different tools and different budgets.

@concept Availability and the nines
@plain
Availability is the share of time a service works. It is quoted as a percentage, often called nines.
@problem
Saying "highly available" means nothing without a number everyone can check.
@does
- Allowed downtime = (1 - availability) x time in the period.
- A year has 365.25 x 24 x 60 = 525,960 minutes.
- Targets are a business decision, with cost rising steeply per extra nine.
@diagram cmp
caption: Allowed downtime
cards:
  - {h: "99.9 percent", kind: warn, items: ["525.96 minutes a year", "about 8.77 hours", "43.83 minutes a month"]}
  - {h: "99.99 percent", kind: info, items: ["52.60 minutes a year", "4.38 minutes a month"]}
  - {h: "99.999 percent", kind: ok, items: ["5.26 minutes a year", "0.44 minutes a month"]}
@h Calculate it
```python title="nines.py"
year = 365.25 * 24 * 60
for a in (99.0, 99.9, 99.95, 99.99, 99.999):
    down = (1 - a / 100) * year
    print(a, round(down, 2), "min per year", round(down / 12, 2), "min per month")
```
Result: 99 percent gives 5259.6 minutes (87.66 hours) a year, 99.9 percent 525.96, 99.95 percent 262.98, 99.99 percent 52.6, 99.999 percent 5.26.
@check
How many minutes of downtime a year does 99.99 percent allow? || About 52.6 minutes.
@end

@concept Composite availability
@plain
A system with several parts in a chain is only as available as the product of the parts. Redundant parts in parallel improve it.
@problem
Teams assume a 99.99 percent load balancer gives a 99.99 percent application.
@does
- In series: multiply. 0.9999 x 0.999 x 0.9995 = 0.99840065, so 99.84 percent, which is (1 - 0.99840065) x 525,960 = about 841 minutes a year, 14 hours.
- In parallel with independent failures: 1 - (1 - a)^n. Two copies at 99.9 percent give 1 - 0.001 x 0.001 = 0.999999, which is 99.9999 percent in theory.
- Real failures are not fully independent: shared deployments, shared configuration and shared dependencies cap the gain.
@diagram flow
caption: Chain and redundancy
nodes:
  - "Load balancer|99.99 percent|info"
  - "App tier|99.9 percent|app"
  - "Database|99.95 percent|app"
  - "Whole chain|99.84 percent|warn"
@h Compute it
```python title="composite.py"
chain = 0.9999 * 0.999 * 0.9995
print(chain, (1 - chain) * 525960)
pair = 1 - (1 - 0.999) ** 2
print(pair)
```
@check
Why is the chain less available than its weakest part? || Each part adds its own chance of failure, and they multiply.
@end

@concept RTO and RPO
@plain
RTO is how long you can be down. RPO is how much data you can afford to lose, measured in time.
@problem
Without these two numbers nobody can choose a backup schedule or a recovery design.
@does
- RTO (recovery time objective): maximum acceptable time from failure to service restored.
- RPO (recovery point objective): maximum acceptable age of the last recoverable data.
- RPO is driven by backup or replication interval. RTO is driven by how much must be rebuilt and how well it is automated.
- Actual recovery time must be measured by drills.
@diagram flow
caption: Timeline of an incident
nodes:
  - "Last good copy|T minus 15 min|info"
  - "Failure|T|bad"
  - "Detect and decide|T plus 10 min|warn"
  - "Restore and switch|T plus 55 min|app"
  - "Service back|RTO measured|ok"
@h Worked example
Backups every 15 minutes with log shipping every 5 minutes: worst-case data loss is 5 minutes, so RPO = 5 minutes. Recovery steps: detect and decide 10 minutes, restore database 30 minutes, redeploy and verify app 15 minutes. RTO = 10 + 30 + 15 = 55 minutes. If the business requires RTO of 30 minutes, 55 does not meet it, and the restore step must shrink, for example with a warm standby.
```python title="rto.py"
steps = {"detect": 10, "restore db": 30, "redeploy": 15}
print(sum(steps.values()), "minutes")
```
@check
What decides RPO? || The interval between backups or replication of data.
@end

@concept Recovery strategies
@plain
Four classic patterns trade cost for speed: backup and restore, pilot light, warm standby, active-active.
@problem
Paying for active-active everywhere is wasteful, but backup-only is too slow for critical systems.
@does
- **Backup and restore**: cheapest, hours of RTO, RPO equal to backup interval.
- **Pilot light**: data replicated, minimal core running, scale up on disaster. RTO tens of minutes to hours.
- **Warm standby**: a scaled-down full copy running. RTO minutes.
- **Active-active**: all regions serve traffic. RTO near zero, highest cost and complexity.
@diagram cmp
caption: Cost versus recovery speed
cards:
  - {h: "Backup and restore", kind: ok, items: ["Lowest cost", "Slowest recovery"]}
  - {h: "Pilot light", kind: info, items: ["Data always replicated", "Compute started on demand"]}
  - {h: "Warm standby", kind: warn, items: ["Small copy running", "Scale up on failover"]}
  - {h: "Active-active", kind: bad, items: ["All regions serve", "Highest cost and complexity"]}
@choose Pick a strategy
Backup and restore | RTO of hours, low-value system | RPO under minutes
Pilot light | RTO under a couple of hours | you need instant failover
Warm standby | RTO of minutes, important system | budget is very tight
Active-active | near zero RTO, revenue critical | your data model cannot handle multi-writer conflicts
@h Cost sketch
If production costs 100 units per month, warm standby at 25 percent of capacity costs 25 more, so total 125, while active-active costs about 100 more, total about 200. Use real numbers from your estimate.
@check
Which strategy keeps data replicated but compute off? || Pilot light.
@end

@concept Designing for high availability
@plain
Spread across zones, remove single points of failure, and make failures cheap to survive.
@problem
Single-zone designs go down for a rack, power or network fault that the cloud considers normal.
@does
- Run at least two zones, preferably three, for stateless tiers behind a load balancer.
- Databases: synchronous standby in another zone. Expect a failover of tens of seconds to a few minutes and make clients retry.
- Keep stateless apps so any instance can serve any request.
- Capacity: after losing one of n zones, remaining zones must carry full load, so provision n / (n - 1) times the per-zone need. For 3 zones this is 1.5 times.
@diagram layers
caption: Three-zone service
layers:
  - {label: "Zone A", nodes: ["App|stateless|app", "DB primary|writes|ok"]}
  - {label: "Zone B", nodes: ["App|stateless|app", "DB standby|synchronous|info"]}
  - {label: "Zone C", nodes: ["App|stateless|app"]}
@h Capacity rule
If peak needs 6 units: with 3 zones, each zone runs 6 / 2 = 3 units so losing a zone leaves 2 x 3 = 6. Total 9 units in normal times, which is 50 percent more than 6.
@check
How much extra capacity does a three-zone design need to survive losing a zone? || 50 percent over peak, as each zone must hold half the load.
@end

@concept Multi-region disaster recovery
@plain
A region can fail, or a mistake can destroy data in one. A second region or a separate account protects against both.
@problem
Zone redundancy does not help against region-wide events, bad deployments to all zones, or deleted data.
@does
- Replicate data: asynchronous database replicas, object storage replication, cross-region backup copies in a separate account.
- Keep infrastructure as code so the second region can be built or scaled quickly.
- Use DNS or a global load balancer for traffic switch, with health checks and low TTL.
- Check quotas and capacity in the recovery region ahead of time.
- Replicated mistakes are still mistakes, so keep point-in-time backups and immutable copies.
@diagram flow
caption: Failover to a second region
numbered: true
nodes:
  - "Detect|health checks fail|warn"
  - "Decide|runbook, human or automatic|info"
  - "Promote|replica becomes writer|app"
  - "Scale|bring compute up|app"
  - "Switch|DNS or global LB|cp"
  - "Verify|smoke tests|ok"
@h Region failover check
```bash title="failover-checklist.sh" nocheck
# 1. confirm primary region is unhealthy
# 2. promote the replica database in the recovery region
# 3. scale the application group to the production size
# 4. lower DNS TTL earlier, then switch the record
# 5. run smoke tests
# 6. record times to update the measured RTO
```
@check
Why keep backups even with cross-region replication? || A replica copies mistakes and deletions as well.
@end

@concept Testing recovery
@plain
An untested plan is a guess. Drills turn it into a known number.
@problem
Plans fail because credentials expired, quotas were short, or steps were out of date.
@does
- Restore tests on a schedule, timed and recorded.
- Game days: simulate zone loss and region loss in a safe environment, then in production with care.
- Chaos experiments on non-critical parts, using tools such as AWS Fault Injection Service, Azure Chaos Studio or open-source Litmus. Check the current docs.
- Update runbooks after each drill, and track the measured RTO and RPO against targets.
@diagram flow
caption: Drill loop
nodes:
  - "Plan|scope and rollback|plain"
  - "Run|inject failure|warn"
  - "Measure|time to recover|info"
  - "Fix|update runbook|ok"
@h Drill record
```yaml title="drill-2026-10.yaml" nocheck
date: 2026-10-20
scenario: loss of primary zone
target_rto_min: 30
measured_rto_min: 42
target_rpo_min: 5
measured_rpo_min: 0
findings:
  - standby promotion step was manual
  - dashboard missing for replica lag
actions:
  - automate promotion, owner platform, due 2026-11-30
```
@check
What does a failed drill give you? || A concrete list of fixes before a real incident.
@end
