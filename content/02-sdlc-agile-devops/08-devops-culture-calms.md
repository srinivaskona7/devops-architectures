---
title: DevOps culture and CALMS
minutes: 40
objectives:
  - Explain what DevOps is and the problem of the wall between development and operations
  - Use the CALMS model to assess a team's culture, automation, lean practice, measurement and sharing
  - Describe blameless culture, team topologies and shared ownership
---
DevOps is a way of working in which the people who build software and the people who run it share goals, tools and responsibility. It is a cultural change first. Tools such as Kubernetes, Terraform and CI servers make the change practical.

@concept The wall of confusion
@plain
Traditionally, developers were rewarded for shipping features and operations for keeping things stable. Each side handed work to the other over a "wall", and each optimised for its own measure.
@problem
Developers pushed changes that operations feared; operations added approvals that developers worked around. Releases became rare, large and risky, which proved operations right and slowed everyone.
@does
- DevOps aligns both sides on one goal: fast, safe delivery of value, measured together.
- Removes hand-offs: the same team builds, deploys, monitors and fixes.
- Replaces gatekeeping with automation and guardrails.
- Does not mean "developers do everything". Specialists remain, but they work in the same team or via clear self-service interfaces.
@diagram cmp
caption: Before and after
cards:
  - {h: "Siloed", kind: bad, items: ["Dev optimises for change", "Ops optimises for stability", "Tickets across a wall"]}
  - {h: "DevOps", kind: ok, items: ["Shared goal and metrics", "You build it, you run it", "Automation as the interface"]}
@h Spot the wall in your own process
```text title="Signs of a wall"
- A release needs a ticket to another team and a wait of days.
- Developers cannot see production logs or metrics.
- Operations learns of a change on the day it ships.
- Incidents end with "who changed what" rather than "what in the system allowed it".
```
@check
Why does the wall make releases riskier? || It discourages frequent deploys, so changes batch up and each release becomes large and hard to diagnose.
@end

@concept CALMS
@plain
CALMS is a checklist of five areas a DevOps change touches: Culture, Automation, Lean, Measurement and Sharing.
@problem
Organisations often buy tools and call it DevOps, then see no improvement. A model reminds you that people and process matter as much as pipelines.
@does
- **Culture**: collaboration, shared ownership, trust, blameless learning.
- **Automation**: build, test, deploy, infrastructure and compliance checks are scripted and repeatable.
- **Lean**: small batches, limited WIP, remove waste, improve flow.
- **Measurement**: data about delivery and reliability drives decisions (DORA metrics, SLOs).
- **Sharing**: knowledge, tools and incident learning are open across teams.
@diagram layers
caption: CALMS as five pillars
layers:
  - {label: "People", nodes: ["Culture|trust and shared ownership|info", "Sharing|docs, demos, postmortems|info"]}
  - {label: "Process", nodes: ["Lean|small batches, flow|app", "Measurement|DORA and SLOs|app"]}
  - {label: "Technology", nodes: ["Automation|pipelines, IaC, policy|ok"]}
@h Self-assessment
```python title="Score your team from 1 to 5 in each area" lab
scores = {"Culture": 3, "Automation": 4, "Lean": 2, "Measurement": 2, "Sharing": 3}
weakest = min(scores, key=scores.get)
print("average", round(sum(scores.values()) / len(scores), 1))
print("work on", weakest, "first")
```
@check
Which CALMS letter do tools mainly address? || A, Automation. The other four are about people and process.
@end

@concept You build it, you run it
@plain
The team that writes a service also carries its pager, watches its dashboards and fixes its incidents. Running software teaches design lessons that no review can.
@problem
When people who write code never feel production pain, reliability, logging and operability become somebody else's problem.
@does
- Teams own the full life cycle: design, delivery, operation, cost and security of their services.
- Requires enough support: on-call rotations of sensible size, good alerts, runbooks and a platform that removes undifferentiated work.
- Shifts incentives: a noisy alert becomes the team's own annoyance and gets fixed.
- Reserve a path for specialists (SRE, security) to advise and review.
@diagram flow
caption: Ownership loop
nodes:
  - "Design|for operability|app"
  - "Build|with tests and telemetry|app"
  - "Deploy|self-service|env"
  - "Run|on-call and SLOs|ok"
  - "Learn|fix the root cause|info"
@h Operability checklist
```text title="Before a service goes live"
[ ] Health endpoints and readiness probes
[ ] Structured logs with request IDs
[ ] RED metrics (rate, errors, duration) and dashboards
[ ] Alerts tied to an SLO, each linked to a runbook
[ ] Tested rollback, documented dependencies
```
@check
What support must exist for you-build-it-you-run-it to work? || A good platform, sensible on-call, useful alerting and time to fix operability problems.
@end

@concept Blameless culture and psychological safety
@plain
When something fails, a blameless culture asks how the system allowed a mistake, not who made it. People report problems early when they are not punished for them.
@problem
In a blame culture people hide errors and near misses, so the organisation never learns, and the same failure repeats.
@does
- Assumes people acted sensibly with the information they had; looks at missing safeguards, confusing tooling and pressure.
- Uses "what" and "how" questions, not "who" and "why did you".
- Rewards raising issues; leaders model it by admitting their own mistakes.
- Psychological safety is a top predictor of team performance in Google's Project Aristotle research.
@diagram cmp
caption: Two reactions to an outage
cards:
  - {h: "Blame", kind: bad, items: ["Who pushed the change", "People hide mistakes", "Same failure returns"]}
  - {h: "Blameless", kind: ok, items: ["What let this reach production", "Near misses reported", "Safeguards added"]}
@h Question wording
```text title="Better questions in a review"
Instead of    Why did you run that command on prod?
Ask           What made that command look safe, and why could it reach prod?

Instead of    Who approved this?
Ask           What did the review see, and what evidence was missing?
```
@check
Does blameless mean no accountability? || No. Accountability moves to fixing the system and following through on actions.
@end

@concept Team topologies and collaboration modes
@plain
Team Topologies describes four team types and three ways teams interact so that work flows with minimal hand-offs.
@problem
Many teams depending on one central ops or platform group create queues. Too much cognitive load on stream teams slows them down.
@does
- **Stream-aligned** teams deliver a flow of work for a product or user journey. **Platform** teams provide self-service capabilities. **Enabling** teams coach others for a time. **Complicated subsystem** teams own hard specialist components.
- Interaction modes: **collaboration** (work closely for a while), **X-as-a-Service** (use via a clear interface), **facilitating** (coach).
- Aim to keep each team's cognitive load within what it can handle.
@diagram layers
caption: Team types
layers:
  - {label: "Delivers value", nodes: ["Stream-aligned|product teams|app"]}
  - {label: "Supports", nodes: ["Platform|self-service paved paths|cp", "Enabling|coaching, security, SRE|info", "Subsystem|specialist components|env"]}
@h Interaction modes
```text title="Choosing a mode"
New Kubernetes platform capability   -> collaboration for 6 weeks, then X-as-a-Service
Teams unfamiliar with SLOs           -> facilitating by an SRE enabling team
Stable CI service                    -> X-as-a-Service with docs and an SLA
```
@check
What reduces queues between product teams and infrastructure? || A platform team offering self-service capabilities instead of ticket-based requests.
@end

@concept DevOps adoption anti-patterns
@plain
Patterns that look like DevOps but keep the old problems.
@problem
A rename of the operations team to "DevOps team" with no other change reproduces the wall under a new name.
@does
- **DevOps team as a silo**: a new group between dev and ops that owns every pipeline.
- **Tool-first adoption**: buying a CI platform without changing ownership.
- **DevOps as job title for sysadmin work**.
- **Ignoring security and compliance**, which then blocks late.
- **No measurement**, so improvement cannot be shown.
- Fix: start with one value stream, measure lead time and failures, and expand.
@diagram cmp
caption: Common failures
cards:
  - {h: "Silo team", kind: bad, items: ["Another hand-off", "Fix, embed skills in teams"]}
  - {h: "Tool first", kind: bad, items: ["Same process, new tool", "Fix, change workflow and ownership"]}
  - {h: "Start small", kind: ok, items: ["One service, measured", "Expand with evidence"]}
@h Pilot selection
```text title="A good first value stream"
- Visible and important enough to matter, but not mission critical
- A team willing to change
- Measurable lead time and failure rate before and after
```
@check
Why start with one value stream? || You learn cheaply, show measured results and build credibility for wider change.
@end
