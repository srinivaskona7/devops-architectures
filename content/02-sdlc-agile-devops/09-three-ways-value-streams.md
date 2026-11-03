---
title: The Three Ways and value streams
minutes: 40
objectives:
  - Explain flow, feedback and continual learning as the Three Ways
  - Map a value stream and compute lead time and flow efficiency
  - Apply the Theory of Constraints and small batch sizes to remove bottlenecks
---
The Three Ways, from *The Phoenix Project* and *The DevOps Handbook*, summarise why DevOps practices work. Each practice supports speeding up flow, amplifying feedback or building a learning culture.

@concept The First Way - flow
@plain
Make work move from idea to customer faster, in a smooth stream, by making it visible, limiting work in progress and reducing the size of each batch.
@problem
Large batches and long queues delay value and delay learning. Defects in a big release are hard to trace to their source.
@does
- Make work visible on a board covering the whole path to production.
- Limit WIP, shrink batch size, reduce hand-offs and automate repeated steps.
- Never pass a known defect downstream; build quality in.
- Never optimise a local step at the cost of the whole flow.
@diagram flow
caption: Flow from left to right
nodes:
  - "Dev|commit|app"
  - "Build and test|automated|warn"
  - "Deploy|automated|env"
  - "Customer|value delivered|ok"
@h Batch size effect
```python title="Smaller batches deliver sooner" lab
# 12 changes; each change needs 1 day to build and the release has a fixed 3 day overhead
changes = 12
overhead = 3
for batch in (12, 6, 3, 1):
    releases = changes // batch
    wait = (batch - 1) / 2          # average days a change waits for its batch
    print(f"batch {batch:>2}: {releases:>2} releases, avg wait before release {wait:.1f} days")
```
@check
Why does a smaller batch speed up learning? || Feedback on each change arrives sooner and problems are easier to trace to a single cause.
@end

@concept The Second Way - feedback
@plain
Create fast, constant feedback from right to left: from production and customers back to developers, so problems are found and fixed where they start.
@problem
If a defect is discovered months later, the author has forgotten the context and customers already suffered.
@does
- Fast automated tests and CI (feedback in minutes) and observability (feedback in seconds).
- Swarm on problems when they appear rather than letting them pile up.
- Push quality closer to the source: developers see production telemetry and alerts.
- Short feedback loops include pull request review times, pipeline duration and alert latency.
@diagram flow
caption: Feedback loops by speed
nodes:
  - "Editor and linter|seconds|ok"
  - "Unit tests|minutes|ok"
  - "Integration and CI|10 to 30 minutes|info"
  - "Production monitoring|real time|info"
  - "Customer feedback|days|warn"
@h Measure pipeline feedback time
```bash title="How fast is your CI feedback?" lab
echo "target: unit feedback under 10 min, full pipeline under 30 min"
git log -1 --format='last commit: %cr' 2>/dev/null || true
echo "gh run list --limit 10 --json durationMs,conclusion   # with GitHub CLI, if available"
```
@check
Give an example of production feedback reaching developers. || An alert or dashboard owned by the team, or a trace linking an error to a recent deploy.
@end

@concept The Third Way - continual learning and experimentation
@plain
Build a culture where people take calculated risks, practise failure and turn every incident into improvement. Repetition and practice build mastery.
@problem
Organisations that punish failure stop experimenting, and stagnate. Those who never practise recovery are slow when real incidents happen.
@does
- Set aside time to improve daily work; fix the process before the next feature.
- Run game days and chaos experiments to test recovery.
- Share learning: postmortems, internal talks, documentation.
- Inject faults deliberately in a controlled way to find weaknesses before customers do.
@diagram flow
caption: A learning loop
numbered: true
nodes:
  - "Hypothesis|we survive a node loss|info"
  - "Experiment|drain or kill a node|warn"
  - "Observe|alerts and recovery time|app"
  - "Improve|fix gaps found|ok"
@h A small, safe experiment
```bash title="Pod failure experiment on a test cluster" lab
kubectl create namespace chaos-demo 2>/dev/null
kubectl -n chaos-demo create deployment web --image=nginx:1.27 --replicas=3 2>/dev/null
kubectl -n chaos-demo delete pod -l app=web --wait=false 2>/dev/null   # does the Deployment self-heal?
kubectl -n chaos-demo get pods 2>/dev/null
kubectl delete namespace chaos-demo 2>/dev/null
```
@check
What is a game day? || A planned exercise in which a team practises responding to a failure scenario.
@end

@concept Value streams and value stream mapping
@plain
A **value stream** is the sequence of steps from a request to the customer receiving value. A value stream map shows each step with its active time and waiting time.
@problem
Teams optimise the part they see, such as coding speed, while most elapsed time is spent in queues elsewhere.
@does
- For each step record process time (hands-on), wait time (queue) and percent complete and accurate (%C/A).
- **Lead time** is the total elapsed time; **flow efficiency** equals process time divided by lead time.
- The biggest wait is the first place to improve.
- Include the non-technical steps: approvals, procurement, change boards.
@diagram flow
caption: Value stream for a small change
nodes:
  - "Request approved|wait 2 d|warn"
  - "Code and review|work 1 d, wait 2 d|app"
  - "QA|work 0.5 d, wait 3 d|warn"
  - "Change board|wait 5 d|bad"
  - "Deploy|work 0.1 d|ok"
@h Compute lead time
```python title="Value stream numbers" lab
steps = [("approval", 0, 2), ("code and review", 1, 2), ("QA", 0.5, 3), ("change board", 0, 5), ("deploy", 0.1, 0)]
work = sum(w for _, w, _ in steps); wait = sum(q for _, _, q in steps)
print(f"lead time {work + wait:.1f} d, work {work:.1f} d, flow efficiency {work / (work + wait):.0%}")
worst = max(steps, key=lambda s: s[2])
print("largest queue:", worst[0], worst[2], "days")
```
@check
What is flow efficiency? || The share of total lead time spent actively working rather than waiting.
@end

@concept Theory of Constraints
@plain
Every system has one bottleneck that limits its output. Improving anything else does not increase throughput; improving the bottleneck does.
@problem
Teams spend effort speeding up steps that are not the limiting one, so nothing improves at the end of the line.
@does
- Five focusing steps: identify the constraint, exploit it (never starve it), subordinate other steps to it, elevate it (add capacity), then repeat because a new constraint appears.
- In software the constraint is often not coding but review, environments, testing, security approval or deployment.
- Starting more work upstream of a constraint only builds a queue.
@diagram flow
caption: The five focusing steps
numbered: true
nodes:
  - "Identify|find the bottleneck|info"
  - "Exploit|keep it busy on the right work|app"
  - "Subordinate|others pace to it|warn"
  - "Elevate|add capacity|env"
  - "Repeat|constraint moves|ok"
@h Find the constraint
```python title="Stage capacities per week" lab
capacity = {"code": 20, "review": 12, "test": 9, "deploy": 40}
bottleneck = min(capacity, key=capacity.get)
print("system throughput =", capacity[bottleneck], "items per week, limited by", bottleneck)
```
@check
Why not add developers when review is the bottleneck? || More code only lengthens the review queue; throughput stays at the review capacity.
@end

@concept Unplanned work and the four types of work
@plain
*The Phoenix Project* names four kinds of work: business projects, internal IT projects, changes, and unplanned work (firefighting). Unplanned work steals time from everything else.
@problem
Teams that spend most of their time firefighting never fix the causes, and so keep firefighting.
@does
- Track how much capacity goes to each type.
- Treat recurring incidents as projects: fix the cause and automate the fix.
- Reduce change failures (they create more unplanned work).
- Limit WIP; context switching during incidents is expensive.
@diagram cmp
caption: Four types of work
cards:
  - {h: "Business projects", kind: app, items: ["New features and products"]}
  - {h: "Internal projects", kind: info, items: ["Platform, tooling, upgrades"]}
  - {h: "Changes", kind: env, items: ["Releases and operational changes"]}
  - {h: "Unplanned work", kind: bad, items: ["Incidents and rework", "Reduce it, do not normalise it"]}
@h Capacity split
```python title="Where did the week go?" lab
week = {"projects": 14, "internal": 4, "changes": 6, "unplanned": 16}
total = sum(week.values())
for k, v in week.items():
    print(f"{k:<10} {v:>2} h {v / total:.0%}")
```
@check
Why track unplanned work? || It is invisible demand that crowds out improvement; knowing its size justifies investing in prevention.
@end
