---
title: Estimation, planning and agile metrics
minutes: 35
objectives:
  - Estimate with relative sizing and use throughput data to forecast
  - Plan releases and roadmaps without false precision
  - Use metrics that guide teams and avoid metrics that distort behaviour
---
Estimates are forecasts under uncertainty, not promises. Good teams use cheap relative sizing for conversation and real delivery data for dates.

@concept Relative estimation and story points
@plain
Instead of guessing hours, teams compare items: "this story is about twice as hard as that one". The unit is a **story point**, a made-up number that only means something inside one team.
@problem
People are poor at estimating absolute time, and hours get treated as commitments. Relative size is faster and discussion exposes hidden complexity.
@does
- Use a scale such as Fibonacci 1, 2, 3, 5, 8, 13; the gaps reflect growing uncertainty.
- **Planning poker**: everyone reveals an estimate at once; big differences trigger a conversation, then re-vote.
- Points combine effort, complexity and risk. Anything above 8 or 13 should be split.
- Velocity (points per sprint) is a planning input for that team only; it must not be compared between teams.
@diagram flow
caption: Planning poker round
numbered: true
nodes:
  - "Read the story|clarify questions|info"
  - "Reveal cards together|avoid anchoring|app"
  - "Discuss outliers|why 2 versus 13|warn"
  - "Agree|or split the story|ok"
@h Velocity forecast
```python title="Forecast sprints from past velocity" lab
import math, statistics
velocities = [21, 18, 24, 20, 19, 23]
remaining = 140
avg = statistics.mean(velocities)
low = min(velocities)
print(f"average {avg:.1f}, sprints needed {math.ceil(remaining / avg)}")
print(f"pessimistic (lowest velocity {low}) sprints needed {math.ceil(remaining / low)}")
```
@check
Why compare velocity only within a team? || Points are relative to each team's own scale, so cross-team comparison is meaningless.
@end

@concept Forecasting with throughput
@plain
Throughput forecasting uses the count of finished items per week from history and runs many simulated futures (Monte Carlo) to give a range of dates with probabilities.
@problem
Estimation meetings cost time and still give single-number answers that are usually wrong. Historical data is free and more reliable.
@does
- Needs only a count of items done per period and an item count remaining; slice items to roughly similar size.
- Produces statements like "85 percent likely to finish by 18 December".
- Works for Kanban and Scrum teams alike and improves as data accumulates.
- Re-run it weekly as scope changes.
@diagram flow
caption: Monte Carlo forecast
nodes:
  - "History|items done per week|info"
  - "Simulate|thousands of random futures|app"
  - "Distribution|dates and likelihood|warn"
  - "Commit to the 85th percentile|not the average|ok"
@h Run the simulation
```python title="Monte Carlo delivery forecast" lab
import random
weekly = [3, 5, 2, 4, 6, 3, 4, 2]       # items finished in past weeks
remaining = 40
results = []
random.seed(7)
for _ in range(10000):
    left, weeks = remaining, 0
    while left > 0:
        left -= random.choice(weekly)
        weeks += 1
    results.append(weeks)
results.sort()
for p in (50, 85, 95):
    print(f"{p}th percentile: {results[int(len(results) * p / 100) - 1]} weeks")
```
@check
What is the benefit of quoting the 85th percentile? || It states a date you are likely to hit, rather than a date you hit half the time.
@end

@concept Roadmaps and release planning
@plain
A roadmap shows direction over months: outcomes the product aims at, not a list of dated features. Release planning turns the next slice of that direction into scheduled increments.
@problem
Fixed-date feature lists set false expectations because discovery changes scope. No roadmap leaves stakeholders guessing and teams without direction.
@does
- Use **Now / Next / Later** horizons: Now is committed, Next is likely, Later is exploration.
- Frame items as outcomes ("reduce checkout drop-off by 10 percent") with measures.
- Review each quarter; share it openly and treat dates beyond the next horizon as intentions.
- Include enablers: platform upgrades, security and reliability work with their own value statement.
@diagram cmp
caption: Now Next Later roadmap
cards:
  - {h: "Now", kind: ok, items: ["In progress this quarter", "Dates are firm"]}
  - {h: "Next", kind: app, items: ["Planned, shaped", "Dates are estimates"]}
  - {h: "Later", kind: plain, items: ["Ideas under discovery", "No dates promised"]}
@h A short outcome based roadmap
```text title="Roadmap excerpt"
Now    Cut p95 checkout latency from 900 ms to 400 ms.   Upgrade EKS to a supported version.
Next   Self-service returns.                              SLOs and alerts for all tier 1 services.
Later  Multi-region failover investigation.
```
@check
Why should the Later column carry no dates? || The work is not yet understood, so dates would be guesses that become expectations.
@end

@concept OKRs and outcome measures
@plain
Objectives and Key Results (OKRs) set an ambitious qualitative goal and a few measurable results to show progress. They link team work to outcomes.
@problem
Teams that measure only output (tickets closed, story points) can be busy without helping anyone.
@does
- An objective is inspiring and short; 2 to 4 key results are numbers with a baseline and target.
- Outcomes (customer behaviour, reliability, cost) matter more than outputs (features shipped).
- Typical engineering key results are DORA metrics, SLO attainment and cloud cost per transaction.
- Scored quarterly; 0.7 achievement on a stretch goal is considered good.
@diagram layers
caption: Linking goals to measures
layers:
  - {label: "Objective", nodes: ["Make releases boring|safe and frequent|info"]}
  - {label: "Key results", nodes: ["Deploy frequency daily|from weekly|app", "Change failure rate under 10 percent|from 22 percent|app", "Lead time under 1 day|from 5 days|app"]}
  - {label: "Initiatives", nodes: ["Trunk-based development|app", "Pipeline caching|app", "Canary releases|app"]}
@h Tracking progress
```python title="Progress toward a key result" lab
baseline, target, current = 22, 10, 15       # change failure rate percent
progress = (baseline - current) / (baseline - target)
print(f"progress {progress:.0%}")
```
@check
Which is the outcome, deploys per week or customers completing checkout faster? || Customers completing checkout faster; deploys are an output.
@end

@concept Metrics that help and metrics that hurt
@plain
A metric used as a target stops being a good metric (Goodhart's law). Pick measures that guide improvement and cannot be gamed cheaply.
@problem
Measuring individuals by lines of code, tickets closed or hours worked encourages bloated code, ticket splitting and burnout.
@does
- Good: DORA four keys, cycle time, escaped defects, SLO attainment, customer outcomes.
- Risky as targets: velocity, utilisation, code coverage percent, number of commits.
- Measure systems and teams, not individuals; discuss trends, not single values.
- Pair every speed metric with a stability metric.
@diagram cmp
caption: Helpful and harmful measures
cards:
  - {h: "Useful", kind: ok, items: ["Lead time for changes", "Change failure rate", "Time to restore", "SLO attainment"]}
  - {h: "Gameable", kind: bad, items: ["Lines of code", "Story points per person", "Hours logged", "Coverage as a target"]}
@h Coverage can lie
```python title="100 percent coverage with no real test" lab
def withdraw(balance, amount):
    return balance - amount            # missing overdraft check

def test_withdraw():
    withdraw(100, 30)                  # executes the line, asserts nothing

test_withdraw()
print("covered, yet withdraw(10, 50) silently returns", withdraw(10, 50))
```
@check
Why pair a speed metric with a stability metric? || Otherwise teams can look fast by shipping broken changes.
@end

@concept Capacity, interrupts and sustainable pace
@plain
Teams have limited focused time. Support requests, meetings and on-call reduce it. Planning must include them or commitments fail.
@problem
Planning at 100 percent capacity leaves nothing for incidents, review or learning. Overload causes burnout, quality drops and attrition.
@does
- Plan at roughly 70 to 80 percent, keeping a buffer for unplanned work.
- Track the interrupt rate; if it is half the week, make it visible work (support lane) with its own policy.
- Rotate support and on-call duties so the whole team shares the load and learns.
- Protect focus: batch meetings, set no-meeting blocks, use written updates.
@diagram flow
caption: A weekly capacity budget
nodes:
  - "Total hours|5 days x 6 focus hours|info"
  - "Minus support and on-call|expected interrupts|warn"
  - "Minus meetings|ceremonies|warn"
  - "Planned work|about 70 percent|ok"
@h Compute a budget
```python title="Capacity per person per week" lab
focus_hours = 5 * 6
support = 5
meetings = 4
available = focus_hours - support - meetings
print(f"{available} hours available out of {focus_hours} ({available / focus_hours:.0%})")
print("plan about", round(available * 0.85), "hours of committed work")
```
@check
Why not plan to 100 percent capacity? || Unplanned work always arrives, and a plan with no slack fails the moment it does.
@end
