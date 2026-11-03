---
title: Scrum in practice
minutes: 40
objectives:
  - Describe Scrum roles, events and artifacts and the purpose of each
  - Run a sprint from planning to retrospective with a clear sprint goal
  - Recognise common Scrum anti-patterns in DevOps and platform teams
---
**Scrum** is the most used agile framework. It is deliberately small: one team, one backlog, fixed-length sprints and three accountabilities. Its value comes from the regular inspection and adaptation, not from the meetings themselves.

@concept Scrum roles
@plain
Scrum has three accountabilities: the **Product Owner** decides what is most valuable, the **Developers** (everyone needed to build and ship) decide how, and the **Scrum Master** helps the team follow the process and removes obstacles.
@problem
When nobody owns priorities, everything is urgent. When managers assign tasks, the team cannot commit to anything. Clear accountability avoids both.
@does
- The Product Owner owns and orders the **product backlog**; one person, not a committee.
- Developers include testers, operations and security skills as needed; the team is cross-functional and self-managing, typically 3 to 9 people.
- The Scrum Master coaches, protects focus and improves the process; it is not a project manager.
@diagram cmp
caption: Three accountabilities
cards:
  - {h: "Product Owner", kind: info, items: ["What and why", "Orders the backlog", "Accepts the outcome"]}
  - {h: "Developers", kind: app, items: ["How and when", "Build, test, deploy, operate", "Own the sprint plan"]}
  - {h: "Scrum Master", kind: ok, items: ["Coaches the process", "Removes impediments", "Protects team focus"]}
@h Platform team variation
```text title="Who is the product owner of a platform team?"
Customers   Internal product teams
PO          Platform product manager, prioritises by developer pain and adoption
Backlog     Items such as "self-service namespace creation" and "cluster upgrade to 1.31"
Measure     Time to first deploy for a new service, support requests per week
```
@check
Who decides how the work is done in a sprint? || The Developers, as a self-managing team.
@end

@concept The sprint and its events
@plain
A **sprint** is a fixed period, one to four weeks, that produces a usable increment. Inside it are five events: the sprint itself, planning, daily scrum, review and retrospective.
@problem
Open-ended work has no rhythm for feedback. Timeboxes force scope decisions and give regular points to inspect results and adjust.
@does
- **Sprint planning**: choose what to do and why, write a **sprint goal**, and break work into tasks.
- **Daily scrum**: 15 minutes for developers to adjust the plan for the next 24 hours.
- **Sprint review**: show the increment to stakeholders and get feedback.
- **Retrospective**: inspect how the team worked and choose one or two improvements.
- The sprint length does not change mid-sprint; scope may be renegotiated, quality may not.
@diagram flow
caption: A two week sprint
numbered: true
nodes:
  - "Planning|goal and plan|info"
  - "Daily scrum|15 minutes|app"
  - "Build and test|continuous|app"
  - "Review|demo and feedback|ok"
  - "Retrospective|improve the process|warn"
@h Timeboxes
```python title="Maximum event lengths for a 2 week sprint" lab
# Scrum Guide timeboxes: planning 8h per month of sprint, review 4h, retro 3h (all scale with sprint length)
weeks = 2
scale = weeks / 4
print("planning   <=", 8 * scale, "hours")
print("review     <=", 4 * scale, "hours")
print("retro      <=", 3 * scale, "hours")
print("daily      <= 15 minutes")
```
@check
What is a sprint goal for? || It gives the team one coherent purpose, so scope can flex without losing the point of the sprint.
@end

@concept The product backlog and refinement
@plain
The product backlog is the ordered list of everything that might be needed. Refinement is the ongoing activity of making upcoming items clear, small and estimated.
@problem
If planning starts with unclear items, the meeting turns into discovery and nothing is finished. A huge unsorted backlog hides what matters.
@does
- Items are ordered by value, risk and dependencies; the top is detailed, the bottom is rough.
- Refinement takes about 10 percent of the team's time and prepares 1 to 2 sprints of ready work.
- Items can be features, bugs, technical improvements and operational work such as upgrades.
- Items older than a few months with no plan are candidates for deletion.
@diagram layers
caption: Backlog detail decreases downward
layers:
  - {label: "Next sprint", nodes: ["Ready items|small, clear, estimated|ok"]}
  - {label: "Soon", nodes: ["Understood items|criteria drafted|app"]}
  - {label: "Later", nodes: ["Ideas and epics|large and rough|plain"]}
@h Splitting a large item
```text title="Epic to stories"
Epic     Customers can return an order
  Story  Request a return for a delivered item
  Story  Print a return label
  Story  Staff approve or reject a return
  Story  Refund is issued after the item arrives
```
@check
Why is the bottom of the backlog kept rough? || Details go stale and priorities change, so detailed work is done only when it is near.
@end

@concept Increment, Definition of Done and the Sprint Review
@plain
An **increment** is a usable, finished step toward the product goal. Everything in it meets the Definition of Done, and each sprint adds to earlier increments.
@problem
Showing half-done work in a demo gives false progress. Hidden unfinished work (testing, deployment) piles up and explodes near the release.
@does
- Only work meeting the Definition of Done counts; no partial credit.
- In a DevOps team, done includes automated tests, scan results and deployment through the pipeline.
- The review is a working session: stakeholders try the product, and feedback goes to the backlog.
- Release can happen any time during the sprint; it does not wait for the review.
@diagram flow
caption: Finished means shippable
nodes:
  - "Story merged|reviewed|app"
  - "Pipeline green|tests, scans|warn"
  - "Deployed|behind flag or live|env"
  - "Reviewed with users|feedback|ok"
@h Sprint burndown idea
```python title="A simple burndown check" lab
planned = 40
done_by_day = [0, 3, 6, 8, 12, 14, 18, 24, 30, 36]
ideal = [planned * d / 9 for d in range(10)]
for day, (d, i) in enumerate(zip(done_by_day, ideal), 1):
    flag = "behind" if d < i - 4 else "ok"
    print(f"day {day:>2} done {d:>2} ideal {i:5.1f} {flag}")
```
@check
Can a team release in the middle of a sprint? || Yes, Scrum does not require waiting for the review to release.
@end

@concept Retrospectives that change something
@plain
The retrospective is a regular meeting where the team looks at how it works and picks concrete improvements for the next sprint.
@problem
Without it, the same problems repeat: slow reviews, flaky tests, unclear tickets. Retros often become complaint sessions with no follow-up.
@does
- Format: look at facts (cycle time, escaped bugs, pipeline time), generate insights, choose one to three actions.
- Actions have an owner and are added to the next sprint's backlog.
- Psychological safety is a precondition: blameless, focused on systems and not on people.
- Review last retro's actions first; unfinished actions are a signal in themselves.
@diagram flow
caption: A retrospective flow
numbered: true
nodes:
  - "Check actions|last retro|info"
  - "Gather data|what happened|app"
  - "Find causes|ask why|warn"
  - "Pick actions|owner and date|ok"
@h Data to bring
```bash title="Cycle time from Git history" lab
git log --since="2 weeks ago" --merges --pretty='%h %ad %s' --date=short 2>/dev/null | head -10
echo "also bring: pipeline duration, flaky test count, reopened tickets, incidents"
```
@check
What makes a retrospective action good? || It is specific, has one owner and appears in the backlog with a date.
@end

@concept Scrum anti-patterns
@plain
Anti-patterns are practices that look like Scrum but defeat its purpose. Recognising them is half of fixing them.
@problem
Teams adopt the ceremonies and expect results, then conclude that "agile does not work".
@does
- **Scrum-but**: dropping a core part, for example no retros, or no working increment.
- **Mini-waterfall sprints**: design in week one, build in week two, test after the sprint.
- **Velocity as a target**: points become a performance measure and are inflated.
- **Daily scrum as status report** to a manager instead of a planning session for the team.
- **Constant mid-sprint changes** that destroy the sprint goal.
- On-call and interrupt-driven work does not fit sprint commitments well; many platform and SRE teams use Kanban or reserve a share of capacity for interrupts.
@diagram cmp
caption: Symptom and fix
cards:
  - {h: "Mini-waterfall", kind: bad, items: ["Testing happens after the sprint", "Fix, slice stories vertically and automate tests"]}
  - {h: "Velocity target", kind: bad, items: ["Points inflated to look good", "Fix, use velocity only for the team's own forecasting"]}
  - {h: "Status report daily", kind: warn, items: ["Talks to manager not team", "Fix, face the board and plan the day"]}
@choose Scrum or Kanban for an ops-heavy team
Scrum | planned product work with a stable team and fixed cadence | most work arrives unplanned and must start immediately
Kanban | support, on-call and platform requests that arrive continuously | you need a fixed delivery commitment to a date
Scrumban | mix of planned work and interrupts | the team wants strict sprint commitments only
@end
