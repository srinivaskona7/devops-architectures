---
title: DORA metrics and delivery performance
minutes: 40
objectives:
  - Define the DORA metrics and compute them from deployment and incident data
  - Interpret performance bands and avoid misuse of the numbers
  - Name the technical and cultural capabilities that research links to better delivery
---
The DevOps Research and Assessment (DORA) programme, now part of Google Cloud, has studied software delivery for years. Its findings, summarised in *Accelerate* and the yearly State of DevOps reports, show that speed and stability go together rather than trade off.

@concept The DORA metrics
@plain
Five measures of software delivery. Throughput: lead time for changes, deployment frequency and failed deployment recovery time. Stability: change failure rate and (in recent reports) rework rate. Older material lists four keys with "time to restore service".
@problem
Without measures, improvement is guesswork. Single numbers such as "number of releases" ignore quality.
@does
- **Lead time for changes**: from commit to running in production.
- **Deployment frequency**: how often you deploy to production.
- **Change failure rate**: share of deployments that cause a failure needing remediation.
- **Failed deployment recovery time** (formerly time to restore service): how long to recover from a failed deployment.
- Throughput and stability metrics are measured together, per application or service.
@diagram cmp
caption: Throughput and stability
cards:
  - {h: "Throughput", kind: app, items: ["Lead time for changes", "Deployment frequency"]}
  - {h: "Stability", kind: ok, items: ["Change failure rate", "Failed deployment recovery time"]}
@h Compute from data
```python title="Four keys from a deploy log" lab
from datetime import datetime as D
deploys = [  # commit time, deploy time, failed?, minutes to restore
    ("2026-10-26T09:00", "2026-10-26T11:30", False, 0),
    ("2026-10-27T10:00", "2026-10-27T10:50", True, 35),
    ("2026-10-28T08:00", "2026-10-28T09:10", False, 0),
    ("2026-10-29T13:00", "2026-10-29T15:00", False, 0),
    ("2026-10-30T09:30", "2026-10-30T10:00", False, 0),
]
lead = [(D.fromisoformat(d) - D.fromisoformat(c)).total_seconds() / 3600 for c, d, _, _ in deploys]
fails = [m for _, _, f, m in deploys if f]
print(f"deploys {len(deploys)} in 5 days, median lead time {sorted(lead)[len(lead)//2]:.1f} h")
print(f"change failure rate {len(fails) / len(deploys):.0%}, restore time {sum(fails) / len(fails):.0f} min")
```
@check
Which metrics measure stability? || Change failure rate and failed deployment recovery time.
@end

@concept Performance bands
@plain
DORA groups teams into bands such as elite, high, medium and low depending on their numbers. The bands show what is possible, not a score to chase.
@problem
Teams do not know whether their numbers are good. Bands give context for goals.
@does
- Elite teams deploy on demand (multiple times a day), have lead time under a day, change failure rate around 5 percent or lower and recover in under an hour (figures from earlier reports; thresholds shift each year, so check the latest report).
- Low performers deploy monthly or less, with lead times of weeks.
- Speed and stability correlate: high performers are better at both.
- Compare to your own past and your own context first; industry comparison second.
@diagram cmp
caption: Illustrative bands from earlier DORA reports
cards:
  - {h: "Elite", kind: ok, items: ["On-demand deploys", "Lead time under a day", "Recovery under an hour"]}
  - {h: "High", kind: app, items: ["Daily to weekly", "Lead time under a week"]}
  - {h: "Medium", kind: warn, items: ["Weekly to monthly", "Lead time up to a month"]}
  - {h: "Low", kind: bad, items: ["Monthly or rarer", "Lead time over a month"]}
@h Classify (illustrative thresholds)
```python title="Where are we?" lab
def band(lead_hours, deploys_per_week):
    if lead_hours < 24 and deploys_per_week >= 5: return "elite"
    if lead_hours < 168 and deploys_per_week >= 1: return "high"
    if lead_hours < 720: return "medium"
    return "low"
print(band(6, 12), band(80, 3), band(400, 1), band(1500, 0.2))
```
@check
Should bands be used as team targets? || No. They are for orientation; setting them as targets invites gaming.
@end

@concept Measuring in practice
@plain
Collect the metrics automatically from the systems you already have: Git, CI/CD, deployment tooling and incident records.
@problem
Manual reporting is slow and disputed. Definitions drift so numbers cannot be trusted.
@does
- Lead time: first commit (or merge) timestamp to successful production deploy.
- Deployment frequency: count of successful production deploys, per service.
- Failure: define it (rollback, hotfix, incident linked to a deploy) and tag it consistently.
- Tools: DORA four keys project, Sleuth, LinearB, Datadog or your own queries on CI and incident data.
- Review trends in retrospectives; do not report per person.
@diagram flow
caption: Data sources
nodes:
  - "Git|commit and merge times|app"
  - "CI/CD|deploy events|env"
  - "Incident tool|failures, restore times|warn"
  - "Dashboard|trends per service|ok"
@h Deploy events from Kubernetes
```bash title="Rollout history as a data source" lab
kubectl rollout history deployment/api -n shop 2>/dev/null | tail -5
kubectl get deploy api -n shop -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}{"\n"}' 2>/dev/null
echo "better: have the pipeline POST an event (service, sha, time, status) to your metrics store"
```
@check
What needs a clear definition before measuring change failure rate? || What counts as a failure, such as a rollback, a hotfix or a linked incident.
@end

@concept Misuse and Goodhart's law
@plain
When a measure becomes a target, it stops being a good measure. DORA metrics are diagnostic indicators for teams, not performance reviews.
@problem
Targets on deploy count lead to empty deploys; targets on failure rate lead to hiding failures.
@does
- Use as conversation starters: "why did lead time rise last month?"
- Never compare teams with different contexts, or use them to rank individuals.
- Look at all four together, plus qualitative information.
- Pair with outcome measures such as customer satisfaction and business results.
@diagram cmp
caption: Gaming and its antidote
cards:
  - {h: "Gaming", kind: bad, items: ["Split deploys to inflate frequency", "Reclassify failures as non-incidents"]}
  - {h: "Healthy use", kind: ok, items: ["Trend per team over time", "Discuss causes in retros"]}
@h Safe dashboard rules
```text title="Rules for the dashboard"
Show trends per service, not leaderboards.
Show all four keys together on one page.
Keep the definition of "failure" written next to the chart.
Never link metrics to individual bonuses.
```
@check
Why show all four metrics together? || Optimising one alone, such as speed, can hide a drop in stability.
@end

@concept Capabilities that drive performance
@plain
DORA also identifies practices that cause better performance. They fall into technical, process and cultural capabilities.
@problem
Knowing your numbers is not enough; you need to know what to change.
@does
- Technical: version control, trunk-based development, continuous integration, test automation, deployment automation, loosely coupled architecture, monitoring, shifting left on security.
- Process: working in small batches, limiting WIP, streamlined change approval (lightweight peer review beats external boards), customer feedback.
- Culture: generative organisational culture (high cooperation, learning from failure), job satisfaction, supportive leadership, documentation quality.
- Platform engineering and good developer experience are also linked to higher productivity in recent reports.
@diagram layers
caption: Capability groups
layers:
  - {label: "Technical", nodes: ["CI and test automation|fast feedback|app", "Trunk-based development|small merges|app", "Loose coupling|independent deploys|app"]}
  - {label: "Process", nodes: ["Small batches|less risk|env", "Lightweight approval|peer review|env"]}
  - {label: "Culture", nodes: ["Generative culture|learn from failure|ok"]}
@h Pick the next capability
```python title="Choose by lowest score" lab
caps = {"CI": 4, "test automation": 2, "trunk-based": 3, "monitoring": 3, "loose coupling": 2}
print("focus next on:", sorted(caps, key=caps.get)[:2])
```
@check
Which is linked to better outcomes, an external change board or peer review inside the team? || Peer review with automated checks; external boards correlate with slower delivery and no stability benefit.
@end

@concept Improving lead time step by step
@plain
Break lead time into phases, find the largest waiting segment, remove it and measure again.
@problem
Ambitious "go faster" programmes fail without a concrete next step.
@does
- Typical gains: faster CI (parallelise, cache), smaller pull requests, review SLAs, automated deploys, removing manual approvals.
- Measure each segment: coding, waiting for review, CI, waiting for release, deploy.
- Change one thing, measure for a few weeks, then continue.
- Celebrate reduced waiting, not heroics.
@diagram flow
caption: Typical lead time segments
nodes:
  - "Coding|2 h|app"
  - "Waiting for review|9 h|bad"
  - "CI|25 min|warn"
  - "Waiting for release|20 h|bad"
  - "Deploy|10 min|ok"
@h Find the biggest segment
```python title="Where does lead time go?" lab
segments = {"coding": 2, "wait review": 9, "ci": 0.4, "wait release": 20, "deploy": 0.2}
total = sum(segments.values())
for k, v in sorted(segments.items(), key=lambda kv: -kv[1]):
    print(f"{k:<13}{v:>5.1f} h {v / total:.0%}")
```
@check
What is the usual first fix when most of lead time is waiting for release? || Automate the release and deploy continuously instead of batching.
@end
