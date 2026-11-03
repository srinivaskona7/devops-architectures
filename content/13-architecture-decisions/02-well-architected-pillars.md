---
title: Well-Architected pillars across clouds
minutes: 55
objectives:
  - Name the pillars of the AWS, Azure and Google Cloud architecture frameworks
  - Apply each pillar as a set of review questions to a real design
  - Run a lightweight review and record the risks found
---
All three major clouds publish an architecture framework. The wording differs, but they ask the same questions. Use them as checklists, not as rules to follow blindly.

@concept Why frameworks exist
@plain
A framework is a distilled list of good practice and review questions based on many customer designs.
@problem
Every team repeats the same avoidable mistakes: single points of failure, wide permissions, no cost visibility.
@does
- Gives a shared vocabulary for reviews.
- Turns "is this good?" into specific questions.
- Provides tools: AWS Well-Architected Tool, Azure Well-Architected Review, Google Cloud Architecture Framework. Check each vendor's site for the current pillar list, because it is revised from time to time.
@diagram flow
caption: Frameworks in the lifecycle
nodes:
  - "Design|apply questions|plain"
  - "Build|use guardrails|app"
  - "Review|score and list risks|warn"
  - "Improve|plan fixes|ok"
@check
Are the frameworks laws? || No, they are review aids, and you may accept a risk knowingly if you record it.
@end

@concept The pillars side by side
@plain
The three frameworks overlap strongly. AWS lists six pillars, Azure five, and Google Cloud a similar set under slightly different names.
@problem
When a team uses two clouds, they need to map the vocabulary so reviews are consistent.
@does
- AWS pillars (current as of writing): operational excellence, security, reliability, performance efficiency, cost optimization, sustainability.
- Azure pillars: reliability, security, cost optimization, operational excellence, performance efficiency.
- Google Cloud: operational excellence, security and compliance, reliability, cost optimization, performance optimization. Sustainability and AI topics also appear. Verify the current lists.
@diagram cmp
caption: Pillar names
cards:
  - {h: "AWS", kind: warn, items: ["Operational excellence", "Security", "Reliability", "Performance efficiency", "Cost optimization", "Sustainability"]}
  - {h: "Azure", kind: info, items: ["Reliability", "Security", "Cost optimization", "Operational excellence", "Performance efficiency"]}
  - {h: "Google Cloud", kind: ok, items: ["Operational excellence", "Security and compliance", "Reliability", "Cost optimization", "Performance optimization"]}
@h Mapping table
| Theme | AWS | Azure | Google Cloud |
|---|---|---|---|
| Run and improve | Operational excellence | Operational excellence | Operational excellence |
| Protect | Security | Security | Security and compliance |
| Stay up | Reliability | Reliability | Reliability |
| Speed | Performance efficiency | Performance efficiency | Performance optimization |
| Money | Cost optimization | Cost optimization | Cost optimization |
| Footprint | Sustainability | Part of other pillars, check docs | Check docs |
@check
Which theme appears in all three frameworks? || Reliability, security, cost, operations and performance.
@end

@concept Operational excellence
@plain
Operational excellence means you can run the system, see what it is doing, change it safely and learn from failures.
@problem
Without it, deployments are scary, incidents repeat, and knowledge sits in one person's head.
@does
- Everything as code: infrastructure, configuration, dashboards.
- Small, frequent, reversible changes through a pipeline.
- Observability: metrics, logs, traces and alerts tied to service goals.
- Runbooks and game days. Blameless post-incident reviews with tracked actions.
@diagram flow
caption: The operations loop
numbered: true
nodes:
  - "Prepare|code, tests, runbooks|plain"
  - "Deploy|small and reversible|app"
  - "Observe|metrics, logs, traces|info"
  - "Respond|runbook and on-call|warn"
  - "Learn|review and improve|ok"
@h Review questions
```yaml title="ops-questions.yaml" nocheck
- Can we rebuild the environment from code?
- Can we roll back a release in minutes?
- Which alert wakes someone and what do they do?
- When did we last practise an incident?
```
@check
What makes a change safe? || It is small, tested, reversible and observed after release.
@end

@concept Security
@plain
Security protects data and systems through identity, least privilege, encryption, detection and response.
@problem
One leaked key or open storage bucket can expose all customer data.
@does
- Strong identity: single sign-on, MFA, short-lived credentials, no shared accounts.
- Least privilege and separation of duties across accounts.
- Encrypt in transit and at rest, with managed keys.
- Network layers: private subnets, restricted ingress, private endpoints.
- Detect and respond: audit logs, threat detection, tested incident process.
@diagram layers
caption: Defence in depth
layers:
  - {label: "People and workloads", nodes: ["SSO and MFA|human access|ok", "Workload identity|no stored keys|ok"]}
  - {label: "Network", nodes: ["Private subnets|no public data stores|info", "WAF|filter web traffic|info"]}
  - {label: "Data", nodes: ["Encryption|keys under control|app", "Backups|immutable copies|app"]}
  - {label: "Detection", nodes: ["Audit logs|who did what|warn", "Threat findings|owned and triaged|warn"]}
@h Review questions
```yaml title="security-questions.yaml" nocheck
- Are there any long-lived access keys?
- Can any data store be reached from the internet?
- Who can read production data and why?
- Where are audit logs stored and who can change them?
```
@check
Why prefer workload identity to stored keys? || Credentials are short-lived and cannot leak from files.
@end

@concept Reliability
@plain
Reliability is the ability to keep working correctly and to recover quickly when parts fail.
@problem
Hardware, networks, deployments and people fail. A design that assumes otherwise fails in production.
@does
- Remove single points of failure: multiple zones, health checks, autoscaling.
- Limit blast radius with cells, separate accounts and gradual rollouts.
- Retries with backoff and jitter, timeouts, circuit breakers, idempotent operations.
- Backups, tested restores, and defined recovery objectives.
- Quotas checked in advance, including in the recovery region.
@diagram flow
caption: Request path with failure handling
nodes:
  - "Client|retries with backoff|ext"
  - "Load balancer|health checks|cp"
  - "App in 3 zones|stateless|app"
  - "Database|standby and backups|ok"
@h Retry with backoff and jitter
```python title="retry.py"
import random
import time


def call_with_retry(fn, attempts=5, base=0.2, cap=5.0):
    for i in range(attempts):
        try:
            return fn()
        except Exception:
            if i == attempts - 1:
                raise
            delay = min(cap, base * (2 ** i))
            time.sleep(random.uniform(0, delay))
```
@check
Why add jitter to retries? || It spreads retries in time so many clients do not hammer a recovering service together.
@end

@concept Performance efficiency
@plain
Performance efficiency means using resources well to meet latency and throughput goals, and keeping that true as demand changes.
@problem
Over-sized systems waste money, and under-sized ones frustrate users.
@does
- Pick resource types that fit the workload: memory, CPU, GPU, storage class.
- Measure with load tests against targets such as p95 latency.
- Cache, use CDNs, and place data near users.
- Scale horizontally with autoscaling. Remove bottlenecks one at a time, starting with the biggest.
@diagram flow
caption: Tuning loop
numbered: true
nodes:
  - "Target|p95 under 300 ms|plain"
  - "Measure|load test and profile|info"
  - "Find bottleneck|largest first|warn"
  - "Change one thing|then re-measure|app"
@h Arithmetic of capacity
At peak, 9000 requests per second. One node serves 1500 requests per second. Nodes needed: 9000 / 1500 = 6. To survive losing one of three zones with two thirds of capacity remaining, run 6 x 3 / 2 = 9 nodes, three per zone. The cost of zone tolerance here is 3 extra nodes, which is 50 percent more.
@check
Why change one thing at a time? || Otherwise you cannot tell which change improved or hurt performance.
@end

@concept Cost optimization and sustainability
@plain
Cost optimization means paying only for value you use. Sustainability means doing the same work with less energy and fewer resources, which usually also lowers cost.
@problem
Cloud makes it easy to start resources and forget them, so costs creep up.
@does
- Visibility: tags or labels, budgets and alerts per team.
- Right-size and schedule non-production off outside working hours.
- Use commitment discounts for steady load and spot or preemptible capacity for tolerant work.
- Choose efficient hardware, regions with cleaner energy where policy allows, and delete unused data.
@diagram cmp
caption: Spend now and later
cards:
  - {h: "Without discipline", kind: bad, items: ["Untagged resources", "Always-on dev environments", "No budgets"]}
  - {h: "With discipline", kind: ok, items: ["Owner tags enforced", "Scheduled shutdown", "Budget alerts at 80 percent"]}
@h Working example, scheduling
A test VM costs 0.10 per hour in an example price. Always on for 730 hours per month is 0.10 x 730 = 73.00. Running 10 hours on 22 working days is 220 hours, which is 0.10 x 220 = 22.00. The saving is 73.00 minus 22.00 = 51.00, about 70 percent. Prices are examples; check current rates.
@check
Which non-production saving needs no code change? || Scheduling the environment off outside working hours.
@end

@concept Running a lightweight review
@plain
A review is a short workshop that walks the pillars, records risks, and agrees actions.
@problem
Full formal reviews are skipped because they feel heavy, so risks go unseen.
@does
- Choose one workload and invite the people who run it.
- Spend about ten minutes per pillar, using the vendor question lists.
- Classify findings as high, medium or low risk, with an owner and date.
- Repeat when the design changes or every six to twelve months.
@diagram seq
caption: A two-hour review
actors: ["Facilitator|keeps time|info", "Team|knows the system|app", "Risk log|findings|ok"]
steps:
  - "0>1: walk a pillar question | req"
  - "1>0: describe current state | resp"
  - "0>2: record risk and rating | req"
  - "2>1: owner and due date | resp"
@h Risk log
```csv title="risks.csv" nocheck
id,pillar,finding,risk,owner,due
1,reliability,single zone database,high,db-team,2026-12-01
2,security,long-lived CI key,high,platform,2026-11-15
3,cost,dev cluster runs 24x7,medium,platform,2026-12-15
```
@check
What turns a finding into progress? || An owner and a due date.
@end
