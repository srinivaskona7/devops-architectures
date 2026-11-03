---
title: Case studies and interview practice
minutes: 65
objectives:
  - Walk through a structured method for any design question
  - Work four realistic case studies with numbers and trade-offs
  - Answer common architecture interview questions clearly
---
Interviews and real design reviews reward the same skill: ask good questions, state assumptions, compute, choose, and name the trade-offs.

@concept A method for any design question
@plain
Use the same steps every time so you never freeze: clarify, estimate, design, stress, summarise.
@problem
Candidates and teams jump to a favourite tool and miss requirements.
@does
- **Clarify**: users, features, scale, uptime, data rules, budget, deadline.
- **Estimate**: requests per second, storage, bandwidth.
- **Design**: draw boxes: edge, compute, data, async, observability.
- **Stress**: what fails? Zone loss, hot key, bad deploy, secret leak.
- **Summarise**: choices, trade-offs, what you would revisit.
@diagram flow
caption: Five steps
numbered: true
nodes:
  - "Clarify|requirements and limits|plain"
  - "Estimate|load and size|info"
  - "Design|main boxes|app"
  - "Stress|failure cases|warn"
  - "Summarise|trade-offs|ok"
@h Quick estimation helpers
```python title="estimate.py"
users = 500_000
daily_active = users * 0.2
requests_per_user = 30
seconds = 24 * 3600
avg_rps = daily_active * requests_per_user / seconds
peak_rps = avg_rps * 5
print(round(avg_rps, 1), round(peak_rps, 1))
```
This gives 100,000 daily users x 30 requests / 86,400 seconds = 34.7 requests per second average, and about 173.6 at a peak factor of 5.
@check
What does the Stress step ask? || What fails and how the design survives it.
@end

@concept Case 1: A small shop on a budget
@plain
A start-up shop with 500,000 registered users, 20 percent active daily, a budget of 1,500 per month, and a team of three.
@problem
The team could overbuild with Kubernetes and a multi-region database that they cannot afford or run.
@does
- Peak load is about 174 requests per second from the estimate above: modest.
- Choose serverless containers or a small autoscaled VM group, a managed PostgreSQL with a standby in a second zone, object storage for images, a CDN in front.
- Queue for emails and invoice generation so checkout stays fast.
- Skip multi-region. Use backups and a documented restore with RTO of a few hours.
- Monitoring from the cloud's own tools to start.
@diagram flow
caption: Small shop design
nodes:
  - "CDN and WAF|static and filter|cp"
  - "Serverless container|API, scales to load|app"
  - "Managed PostgreSQL|standby in 2nd zone|ok"
  - "Queue and worker|email, invoices|info"
@h Budget check
Illustrative monthly costs: serverless containers 250, database with standby 450, CDN and egress 150, object storage 40, queue and logs 100, monitoring 60, backups 80. Total = 250 + 450 + 150 + 40 + 100 + 60 + 80 = 1,130, leaving 370 headroom under the 1,500 budget.
```python title="budget.py"
items = [250, 450, 150, 40, 100, 60, 80]
print(sum(items), 1500 - sum(items))
```
@check
Why not use multi-region here? || The cost and complexity exceed the need, and a restore with RTO of hours is acceptable.
@end

@concept Case 2: Payments with strict availability
@plain
A payments API must reach 99.95 percent monthly availability, with no more than 5 minutes of data loss and recovery within 30 minutes.
@problem
A single-region design may meet uptime but not region-loss recovery targets.
@does
- Allowed downtime at 99.95 percent: (1 - 0.9995) x 43,830 minutes in a month (365.25 x 24 x 60 / 12) = 21.9 minutes.
- Three-zone stateless tier, database with synchronous standby, idempotency keys on every payment request, retries with backoff.
- Cross-region asynchronous replica for disaster recovery, RPO a few minutes, which meets 5 minutes if replication lag alerts are tight.
- Warm standby region to hit a 30 minute RTO, with quotas pre-approved and a runbook drilled quarterly.
@diagram layers
caption: Payments reliability layers
layers:
  - {label: "Region A active", nodes: ["Three-zone API|stateless|app", "DB primary + sync standby|zones A and B|ok"]}
  - {label: "Region B warm", nodes: ["Small API fleet|scaled up on failover|info", "Async replica|lag under 5 min|warn"]}
  - {label: "Controls", nodes: ["Idempotency keys|no double charge|cp", "Quarterly drill|measure RTO|ok"]}
@h Duplicate protection
```python title="idempotent.py"
processed = {}


def pay(key, amount):
    if key in processed:
        return processed[key]
    result = {"status": "charged", "amount": amount}
    processed[key] = result
    return result


print(pay("k1", 50), pay("k1", 50))
```
@check
What stops a retry from charging twice? || An idempotency key that returns the stored result.
@end

@concept Case 3: Global media with spiky traffic
@plain
Video clips are uploaded by users worldwide and viewed in bursts when something goes viral.
@problem
Origin servers cannot absorb viral peaks, and storing everything in hot storage is expensive.
@does
- Upload straight to object storage with pre-signed URLs, skipping app servers.
- Event triggers a transcode job on spot or preemptible capacity, queued so retries are cheap.
- CDN serves popular content, with long cache time and versioned file names.
- Lifecycle rules move clips not viewed for 90 days to a colder tier.
- Metadata in a key-value store keyed by clip ID, with sharded keys for viral items.
@diagram flow
caption: Media pipeline
nodes:
  - "Client|pre-signed upload|ext"
  - "Object storage|raw clips|info"
  - "Queue|transcode jobs|app"
  - "Workers on spot|batch|app"
  - "CDN|global delivery|cp"
@h Cache arithmetic
A clip of 50 MB viewed 1,000,000 times. With a CDN hit ratio of 95 percent, the origin serves 5 percent: 50,000 requests x 50 MB = 2,500,000 MB, about 2.38 TB. Without the CDN: 1,000,000 x 50 MB = 50,000,000 MB, about 47.7 TB.
```python title="cdn.py"
mb = 50
views = 1_000_000
print(views * 0.05 * mb / 1024 / 1024, views * mb / 1024 / 1024)
```
@check
What does the CDN save in the example? || About 45 TB of origin traffic, as 95 percent of requests hit the cache.
@end

@concept Case 4: Migrating a monolith off a data center
@plain
A 12-year-old monolith with a large SQL Server database, a data center lease ending in 9 months.
@problem
A big rewrite will not finish in time, and a naive move risks long downtime.
@does
- Phase 1: connectivity and landing zone, VPN then dedicated link, same identity provider.
- Phase 2: lift-and-shift VMs and a managed database with change data capture to keep both in sync.
- Phase 3: cutover in a weekend window with a rollback plan, DNS TTL lowered a day before.
- Phase 4 (after the lease ends): modernise piece by piece with the strangler pattern.
- Transfer arithmetic: 10 TB over a 1 Gbps link at 70 percent efficiency: 10 x 8 x 10^12 bits / (0.7 x 10^9 bits per second) = about 114,286 seconds, about 31.7 hours.
@diagram flow
caption: Migration phases
numbered: true
nodes:
  - "Landing zone|network and identity|info"
  - "Replicate|data sync|app"
  - "Cut over|DNS and rollback plan|warn"
  - "Strangle|modernise slices|ok"
@h Transfer time
```python title="transfer.py"
bits = 10 * 8 * 10**12
rate = 0.7 * 10**9
print(round(bits / rate), round(bits / rate / 3600, 1))
```
@check
Why use change data capture during the move? || It keeps the cloud copy in sync so the cutover window is short.
@end

@concept Interview questions with worked answers
@plain
Short, structured answers beat long ones. State the trade-off and the number.
@problem
Candidates list services without reasoning.
@does
- **How do you choose between VMs, containers and serverless?** Start from requirements and team skills. Special OS or licence: VMs. Many services and a platform team: Kubernetes. Spiky stateless services with a small team: serverless containers. Event glue: functions. Check limits and break-even cost.
- **Design for 99.99 percent.** That allows 52.6 minutes a year. Multi-zone everything, remove single points of failure, automate failover and deployments, compute the chain: three parts at 99.99, 99.99 and 99.95 give about 99.93, so each part needs headroom.
- **RTO versus RPO?** RTO is time to restore service, RPO is data you can lose. RPO follows replication or backup interval, RTO follows automation and measured drills.
- **When is multi-cloud justified?** Hard requirements: regulation, customer demand, acquisition, a unique service. Not fear alone. Count egress, skills and tooling.
- **Reduce cloud cost by 30 percent?** Tag and allocate first, remove waste, right-size, schedule non-production, then commit to the baseline and use spot for tolerant jobs. Measure unit cost.
@diagram cmp
caption: Weak and strong answers
cards:
  - {h: "Weak", kind: bad, items: ["Lists products", "No numbers", "Ignores failure"]}
  - {h: "Strong", kind: ok, items: ["States requirements", "Does the arithmetic", "Names the trade-off"]}
@h Check the chain claim
```python title="chain.py"
a = 0.9999 * 0.9999 * 0.9995
print(a, round((1 - a) * 525960, 1))
```
The product is 0.9993 (99.93 percent), about 368 minutes a year, far from 52.6, which is why redundancy and shared-fate analysis matter.
@check
Why is a chain of three 99.99 percent parts not 99.99 percent overall? || Availabilities multiply, so the result is lower than any single part.
@end

@concept Behavioural and review questions
@plain
Architects are also judged on judgement and communication.
@problem
Technical depth alone does not show you can lead a decision.
@does
- **Describe a decision you reversed.** Say what new information arrived, how you recorded it, and the cost.
- **How do you handle disagreement?** Agree on criteria and weights first, run a time-boxed proof of concept, write an ADR.
- **How do you reduce risk in a risky change?** Small steps, feature flags, canaries, rollback tested, observe before and after.
- **How do you keep a design from rotting?** ADRs, fitness functions, regular reviews, cost and reliability dashboards.
- Use the situation, action, result pattern and keep to two minutes.
@diagram flow
caption: Answer pattern
nodes:
  - "Situation|context in one line|plain"
  - "Action|what you did|app"
  - "Result|measured outcome|ok"
  - "Lesson|what you changed|info"
@h Practice checklist
```yaml title="practice.yaml" nocheck
daily:
  - estimate one system from scratch (traffic, storage, cost)
  - write one ADR for a past decision
weekly:
  - draw one design and list three failure cases
  - do one recovery calculation (nines, RTO, RPO)
```
@check
What goes first when settling a team disagreement? || Agreeing the criteria and weights.
@end

@concept Final self-review checklist
@plain
Before you present or submit any design, run this list.
@problem
Missing basics such as backups, secrets and cost appear in reviews and incidents.
@does
- Requirements and quality targets written with numbers.
- Zone failure and region failure walked.
- RTO and RPO stated and tested.
- Identity, secrets, encryption and audit logs covered.
- Cost estimated, tagged, budgeted.
- Observability and runbooks present.
- Decisions recorded in ADRs with triggers.
@diagram layers
caption: Design checklist by layer
layers:
  - {label: "Foundations", nodes: ["Requirements|numbers|plain", "Accounts and network|isolated|info"]}
  - {label: "Resilience", nodes: ["Zones and regions|tested|ok", "RTO and RPO|measured|ok"]}
  - {label: "Control", nodes: ["Security|identity and keys|warn", "Cost|tagged, budgeted|warn"]}
  - {label: "Operations", nodes: ["Observability|alerts with owners|app", "ADRs|decisions recorded|app"]}
@h Checklist file
```yaml title="design-checklist.yaml" nocheck
requirements_with_numbers: true
zone_failure_walked: true
region_failure_walked: true
rto_rpo_tested: true
secrets_in_store: true
audit_logs_protected: true
cost_tagged_and_budgeted: true
alerts_have_owners: true
adrs_written: true
```
@check
Which items must be tested, not just written? || RTO and RPO through restore and failover drills.
@end
