---
title: Postmortems, capacity and reliability practice
minutes: 40
objectives:
  - Write a blameless postmortem with a timeline, contributing factors and tracked actions
  - Plan capacity and test reliability with load tests and game days
  - Design for graceful degradation and measure improvement over time
---
Incidents are expensive lessons. The postmortem is how the organisation collects the value from that expense. Capacity planning and reliability testing reduce the number of lessons you need.

@concept Blameless postmortems
@plain
A postmortem is a written review after an incident: what happened, why, how we responded and what we will change. It is blameless, so people can describe facts honestly.
@problem
Without a review the same incident repeats with a different person on call. With blame, people hide facts.
@does
- Written within a few days for incidents above an agreed severity; reviewed in a meeting with all involved.
- Sections: summary, impact, timeline, root causes and contributing factors, what went well, what went badly, where we got lucky, action items.
- Focus on how the system and process allowed the failure, not on individual errors.
- Publish internally so other teams learn.
@diagram flow
caption: Postmortem process
numbered: true
nodes:
  - "Collect data|timeline, graphs, chat|info"
  - "Draft|facts and causes|app"
  - "Review meeting|blameless|warn"
  - "Actions|owners and dates|ok"
  - "Share|internal library|env"
@h Template
```text title="postmortem.md"
Title        Checkout 502s after config rollout
Date         2026-10-31   Duration 47 minutes   Severity SEV2
Impact       About 20 percent of card payments failed; est. 1 340 orders delayed
Summary      A config change reduced the payment client timeout from 10 s to 1 s...
Timeline     10:42 deploy  10:49 alert  10:55 IC assigned  11:07 rollback  11:29 recovered
Causes       1. Timeout value not validated.  2. Staging payment mock is always fast.
Went well    Alert fired within 7 minutes; rollback took 3 minutes.
Went badly   No canary for config changes.
Lucky        Occurred outside the peak sale hour.
Actions      [P1] Add config validation (sam, 2026-11-14)  [P2] Canary config rollout (priya, 2026-11-28)
```
@check
Why record where we got lucky? || Luck hides risks that could have made the incident worse next time.
@end

@concept Root cause and contributing factors
@plain
Incidents rarely have a single cause. Several small weaknesses line up. Analysis looks for all of them rather than stopping at the first "human error".
@problem
Stopping at "someone made a typo" leads to "be more careful", which never works. The next typo has the same effect.
@does
- **Five whys**: keep asking why until you reach a process or design gap.
- Look at detection, mitigation and prevention separately: why did we not notice sooner, why did recovery take this long, why was it possible.
- Use categories: change, capacity, dependency, monitoring, process, human factors.
- Prefer fixes that make the right thing easy and the wrong thing hard (validation, automation, guardrails) over training and warnings.
@diagram flow
caption: Five whys example
nodes:
  - "Payments failed|timeout too low|bad"
  - "Why|config changed by hand|warn"
  - "Why|no validation in pipeline|warn"
  - "Why|config not treated as code|info"
  - "Fix|config in Git with checks|ok"
@h Rank actions
```python title="Prefer strong fixes" lab
actions = [("send reminder email", 1), ("update runbook", 2), ("add alert", 3), ("automate with validation", 4), ("remove the failure mode", 5)]
for a, strength in sorted(actions, key=lambda x: -x[1]):
    print(f"strength {strength}: {a}")
```
@check
Why is "be more careful" a poor action item? || It relies on human memory and attention; stronger fixes remove the chance of the error.
@end

@concept Tracking actions and learning across incidents
@plain
A postmortem only helps if its action items are done. Track them like any other work and look for patterns across incidents.
@problem
Actions get forgotten, and the same causes recur in different forms.
@does
- Each action has an owner, a due date and a priority in the normal backlog.
- Review open actions in a regular reliability meeting; close or consciously drop them.
- Tag incidents by cause category and analyse quarterly, for example "5 of 9 incidents involved config changes".
- Share summaries; a monthly "incident review" reading group builds shared understanding.
@diagram cmp
caption: Healthy and unhealthy follow-up
cards:
  - {h: "Unhealthy", kind: bad, items: ["Actions in a document nobody reads", "No owners or dates", "Repeat incidents"]}
  - {h: "Healthy", kind: ok, items: ["Actions in the backlog", "Reviewed monthly", "Patterns drive investment"]}
@h Pattern query
```python title="Count causes across incidents" lab
from collections import Counter
incidents = ["config", "capacity", "config", "dependency", "config", "deploy", "capacity", "config"]
for cause, n in Counter(incidents).most_common():
    print(f"{cause:<11}{'#' * n} {n}")
```
@check
Where should postmortem actions be tracked? || In the same backlog and process as other engineering work, with owners and dates.
@end

@concept Capacity planning
@plain
Capacity planning makes sure there are enough resources for expected load plus headroom, without paying for large idle surplus.
@problem
Too little capacity causes outages in peaks; too much wastes money. Growth, seasonal events and launches change demand.
@does
- Know your limits via load testing: requests per second per pod, database connections, queue throughput.
- Forecast growth from traffic history and business plans (sales, campaigns).
- Keep headroom: for example plan so that peak load uses at most 60 to 70 percent of capacity, and so that the loss of one zone is survivable (N+1).
- Autoscale (HPA, Karpenter, Cluster Autoscaler) handles variance; it does not replace planning for limits such as quotas, IP addresses and database size.
@diagram flow
caption: Capacity loop
numbered: true
nodes:
  - "Measure|load and limits|info"
  - "Forecast|growth + events|app"
  - "Provision|with headroom|env"
  - "Review|actual versus plan|ok"
@h Pods required
```python title="Size a deployment for a peak" lab
import math
peak_rps = 1800
rps_per_pod = 150          # measured in a load test at the SLO latency
target_util = 0.65         # leave headroom
zones = 3
pods = math.ceil(peak_rps / (rps_per_pod * target_util))
# survive losing one zone: remaining zones must carry the peak
pods_n1 = math.ceil(pods * zones / (zones - 1))
print(f"pods needed {pods}, with one zone failure tolerance {pods_n1}")
```
@check
What does N+1 capacity protect against? || The loss of one unit (a node or zone) while still carrying the peak load.
@end

@concept Graceful degradation and resilience patterns
@plain
When part of the system fails or load is too high, a resilient service keeps its core function working and sheds or simplifies the rest.
@problem
A failure in a minor dependency, such as recommendations, should not take down checkout. Retry storms can turn a small failure into a large outage.
@does
- **Timeouts** on every remote call; **retries** with exponential backoff, jitter and a retry budget.
- **Circuit breakers** stop calling a failing dependency; **bulkheads** isolate resources per dependency.
- **Load shedding** and rate limits protect the core; **fallbacks** return cached or default data.
- **Idempotency keys** make retries safe for operations like payments.
@diagram flow
caption: Protecting the core path
nodes:
  - "Request|checkout|ext"
  - "Timeout and retry|with jitter|app"
  - "Circuit breaker|stop calling failing service|warn"
  - "Fallback|cached recommendations|ok"
@h Backoff with jitter
```python title="Exponential backoff with full jitter" lab
import random
random.seed(1)
base, cap = 0.2, 10
for attempt in range(1, 7):
    delay = random.uniform(0, min(cap, base * 2 ** attempt))
    print(f"attempt {attempt}: wait up to {min(cap, base * 2 ** attempt):5.1f}s, chosen {delay:5.2f}s")
```
:::warn
Retrying without limits multiplies load on a struggling service. Combine retries with a budget (for example at most 10 percent extra requests) and circuit breakers.
:::
@check
Why add jitter to retries? || It spreads retries over time, so many clients do not hit the recovering service at the same instant.
@end

@concept Game days, chaos engineering and disaster recovery
@plain
Practise failure on purpose, in a controlled way, so recovery steps work when you need them. Disaster recovery (DR) covers losing a whole region or data store.
@problem
Untested failover plans fail. Backups never restored may be corrupt. The first time you try recovery should not be during a real disaster.
@does
- **Game day**: scheduled exercise where a team simulates a failure and follows the runbook.
- **Chaos experiments**: hypothesis, small blast radius, abort condition, then observe; tools include Chaos Mesh, Litmus and AWS Fault Injection Service.
- Define **RTO** and **RPO** per service and test them. DR patterns on AWS: backup and restore, pilot light, warm standby, multi-site active-active, each trading cost for recovery speed.
- Fix what you find, and repeat on a schedule.
@diagram cmp
caption: AWS disaster recovery strategies
cards:
  - {h: "Backup and restore", kind: plain, items: ["Lowest cost", "RTO hours, RPO hours"]}
  - {h: "Pilot light", kind: info, items: ["Core data replicated, compute off", "RTO tens of minutes"]}
  - {h: "Warm standby", kind: warn, items: ["Scaled-down copy running", "RTO minutes"]}
  - {h: "Active-active", kind: ok, items: ["Full capacity in two regions", "Near-zero RTO, highest cost"]}
@h Experiment plan
```yaml title="chaos-experiment.yaml" nocheck
hypothesis: Checkout stays above 99.9 percent success when one API pod is killed every minute for 10 minutes.
blast_radius: namespace shop-staging
abort_if: error_rate > 2 percent for 2 minutes
steps:
  - kill one pod labelled app=api each minute
observe: [error rate, p95 latency, pod restarts, alert firing]
```
```bash title="Zone failure drill on a test cluster" lab
kubectl get nodes -L topology.kubernetes.io/zone 2>/dev/null
kubectl cordon NODE_NAME 2>/dev/null; kubectl drain NODE_NAME --ignore-daemonsets --delete-emptydir-data --timeout=120s 2>/dev/null
kubectl uncordon NODE_NAME 2>/dev/null     # always restore the node afterwards
```
:::warn
After any drain-based drill, confirm that the node is uncordoned again and that workloads rebalanced. Managed platforms may also reconcile node state on their own.
:::
@check
What belongs in a chaos experiment before it starts? || A hypothesis, a limited blast radius and an abort condition.
@end
