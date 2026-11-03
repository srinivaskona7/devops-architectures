---
title: Kanban and Extreme Programming
minutes: 40
objectives:
  - Build a Kanban board with explicit policies and work in progress limits
  - Read cumulative flow, cycle time and throughput to find bottlenecks
  - Apply XP practices such as test driven development, pairing and continuous integration
---
Kanban manages **flow**; XP improves **engineering**. Both fit DevOps well because they favour small batches, fast feedback and sustainable pace.

@concept Kanban boards and WIP limits
@plain
A Kanban board shows each work item as a card moving through columns such as To do, In progress, Review, Done. A **WIP limit** caps how many cards a column may hold.
@problem
When everything is started and little is finished, work waits everywhere and delivery slows. Starting is easy; finishing is the real goal.
@does
- Visualise the whole workflow, including waiting and review columns.
- Limit work in progress; when a column is full, help finish something rather than start more ("stop starting, start finishing").
- Make policies explicit: what "ready for review" means, how to treat urgent items.
- Pull work when there is capacity instead of pushing work onto people.
@diagram rows
caption: A board with WIP limits
rows:
  - arrows: true
    items: ["Backlog|unlimited|plain", "In progress|WIP limit 3|app", "Review|WIP limit 2|warn", "Deploy|WIP limit 1|env", "Done|finished|ok"]
@h Policy as text
```text title="Board policies"
Ready to start   Has acceptance criteria and an owner.
In review        PR open, CI green, reviewer assigned. Review within 4 working hours.
Expedite lane    Only one card at a time; production outage or security fix.
Blocked          Card gets a red flag and a note naming what is needed and from whom.
```
@check
What should you do when the Review column is at its WIP limit? || Review something to unblock the flow rather than starting new work.
@end

@concept Flow metrics
@plain
Flow metrics describe how work moves: how long it takes, how much finishes, how much is in progress and how old items are. They come from the board and need no estimates.
@problem
Story points and opinions give little evidence about delivery speed. Teams need numbers that predict when work will finish.
@does
- **Cycle time**: from work started to done. **Lead time**: from request to done.
- **Throughput**: items finished per week. **WIP**: items currently in progress. **Work item age**: how long an open item has been in progress.
- Little's Law: average cycle time = average WIP divided by average throughput.
- Use percentiles, for example "85 percent of items finish within 6 days", rather than averages, because cycle time distributions have long tails.
@diagram flow
caption: Metrics from a card's life
nodes:
  - "Requested|lead time starts|info"
  - "Started|cycle time starts|app"
  - "Done|both stop|ok"
@h Percentile forecast
```python title="85th percentile cycle time" lab
import statistics
cycle_days = [1, 2, 2, 3, 3, 3, 4, 4, 5, 6, 6, 8, 12, 15]
q = statistics.quantiles(cycle_days, n=20)
print("median", statistics.median(cycle_days), "days")
print("85th percentile", round(q[16], 1), "days")      # q[16] is the 85th percentile cut point
print("mean", round(statistics.mean(cycle_days), 1), "days (pulled up by the long tail)")
```
@check
Why prefer the 85th percentile to the mean? || It gives a promise you can keep most of the time and is not distorted by a few very slow items.
@end

@concept Cumulative flow and bottlenecks
@plain
A cumulative flow diagram (CFD) stacks the count of items in each state over time. The vertical thickness of a band is the WIP in that state; the horizontal distance is the delay.
@problem
A team feels slow but cannot say where the time goes. The CFD shows which stage is a queue.
@does
- Parallel, evenly rising bands mean a healthy, stable flow.
- A band that widens over time shows a growing queue, for example Review or QA.
- A flat Done line shows nothing is being finished.
- Fix by moving capacity to the bottleneck, reducing batch size or lowering upstream WIP.
@diagram cmp
caption: Reading a cumulative flow diagram
cards:
  - {h: "Even bands", kind: ok, items: ["Stable WIP", "Predictable delivery"]}
  - {h: "Widening band", kind: warn, items: ["Queue grows in that state", "Bottleneck found"]}
  - {h: "Flat Done line", kind: bad, items: ["Nothing finished", "Check blockers and WIP"]}
@h Counting items per state
```python title="Daily snapshot to CFD data" lab
from collections import Counter
cards = ["done", "review", "review", "review", "doing", "doing", "todo", "todo", "todo", "todo"]
print(dict(Counter(cards)))
print("review holds", Counter(cards)["review"] / len(cards), "of all items; this is the queue to attack")
```
@check
What does a widening band in a CFD tell you? || Work is entering that state faster than it leaves, so it is a bottleneck.
@end

@concept Extreme Programming practices
@plain
Extreme Programming (XP) is a set of engineering practices that keep code easy to change: test first, integrate continuously, refactor, pair and keep designs simple.
@problem
Frequent change breaks code that is untested and tangled, so speed drops over time. Quality practices let teams keep going fast.
@does
- **Test driven development (TDD)**: write a failing test, make it pass, then refactor.
- **Continuous integration**: merge to main at least daily, with automated tests.
- **Pair or mob programming**: two people on one task for review in real time and knowledge sharing.
- **Refactoring** and **simple design**; **collective code ownership**; **small releases**; **sustainable pace**.
- Many DevOps practices (CI, trunk-based development, automated tests) come directly from XP.
@diagram flow
caption: The TDD cycle
numbered: true
nodes:
  - "Red|write a failing test|bad"
  - "Green|simplest code to pass|ok"
  - "Refactor|clean up, tests stay green|info"
@h A red-green example
```python title="TDD in miniature" lab
def apply_discount(price, percent):
    if not 0 <= percent <= 100:
        raise ValueError("percent must be 0 to 100")
    return round(price * (100 - percent) / 100, 2)

assert apply_discount(200, 25) == 150.0       # the test written first
assert apply_discount(19.99, 0) == 19.99
try:
    apply_discount(10, 120)
except ValueError:
    print("invalid percent rejected")
print("all tests passed")
```
@check
Why refactor only when tests are green? || Passing tests tell you quickly if the cleanup changed behaviour.
@end

@concept Trunk-based development and pairing
@plain
Trunk-based development means everyone commits small changes to one main branch at least daily, using flags to hide unfinished features. Pairing and mobbing are ways to review and share knowledge as the code is written.
@problem
Long-lived branches collect conflicts and hide integration problems until a painful merge. Late code review makes feedback expensive.
@does
- Short-lived branches (under a day or two) or direct commits to main with CI as a guard.
- Feature flags decouple deploying code from releasing features.
- DORA research links trunk-based practices with higher delivery performance.
- Pairing replaces some review time, especially for risky or unfamiliar work.
@diagram cmp
caption: Branching styles compared
cards:
  - {h: "Long-lived branches", kind: bad, items: ["Merge pain, hidden conflicts", "Large batches of change"]}
  - {h: "Trunk-based", kind: ok, items: ["Small, daily merges", "Flags hide unfinished work"]}
@h Keep branches short
```bash title="How old is each branch?" lab
git for-each-ref --sort=committerdate --format='%(committerdate:short) %(refname:short)' refs/heads 2>/dev/null | head
echo "anything older than a few days deserves a merge, a split or a delete"
```
@check
How can unfinished code live safely on main? || Behind a feature flag that is off by default.
@end

@concept Technical debt
@plain
Technical debt is the extra future cost created by shortcuts in code, tests, infrastructure or documentation. Like financial debt, it accrues interest: every change becomes slower.
@problem
Ignored debt makes each feature take longer, increases defects and eventually forces a rewrite. Hiding it from planning makes things worse.
@does
- Prudent debt is taken deliberately for a deadline and repaid soon; accidental debt comes from lack of skill or knowledge.
- Make it visible: backlog items, code analysis, DORA lead time trends.
- Reserve capacity (for example 15 to 20 percent) to repay it continuously, or refactor as you touch code ("boy scout rule").
- Infrastructure debt includes old Kubernetes versions, unpatched images and manual steps.
@diagram flow
caption: Debt slows delivery over time
nodes:
  - "Shortcut|ship quickly|warn"
  - "Interest|slower changes|bad"
  - "Refactor|pay down|app"
  - "Faster delivery|recovered|ok"
@h Spotting infrastructure debt
```bash title="Versions that are falling behind" lab
kubectl version 2>/dev/null | head -3 || echo "no cluster reachable"
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion 2>/dev/null | head
```
@check
Name one way to keep technical debt visible. || Track it as backlog items with cost estimates and review the trend regularly.
@end
