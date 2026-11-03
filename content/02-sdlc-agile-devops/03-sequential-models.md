---
title: Plan-driven SDLC models
minutes: 40
objectives:
  - Describe waterfall, V-model, incremental, iterative and spiral models and their trade-offs
  - Explain why long feedback loops cause late surprises
  - Pick a plan-driven model for the situations where it still fits
---
A **model** is a pattern for ordering the SDLC phases. Early models assume requirements can be known upfront. Newer models accept that learning happens during the work. Knowing the older ones helps you recognise them inside large organisations and regulated projects.

@concept Waterfall
@plain
Waterfall runs the phases once, in order: requirements, design, build, test, deploy, maintain. Each phase finishes and is signed off before the next begins.
@problem
Large engineering projects, such as bridges or hardware, needed order and predictable budgets. Changing a design after concrete is poured is expensive, so planning everything first made sense.
@does
- Strong documentation and clear milestones; easy to contract and to report progress.
- Feedback from real users arrives only at the end, often after months or years.
- Changing requirements mid-way is hard and expensive.
- Fits well when requirements are stable and well understood, for example some embedded, safety critical or fixed-scope regulatory work.
@diagram flow
caption: Waterfall moves one way
numbered: true
nodes:
  - "Requirements|signed off|info"
  - "Design|frozen|app"
  - "Build|months|app"
  - "Test|late|warn"
  - "Deploy|big bang|bad"
@h Where the risk hides
```python title="When does the first user feedback arrive?" lab
projects = {"waterfall": 12, "iterative (3 month cycles)": 3, "agile (2 week sprints)": 0.5, "DevOps (daily deploys)": 0.03}
for name, months in projects.items():
    print(f"{name:<28} first feedback after about {months} months")
```
@check
What is the main weakness of waterfall for software? || User feedback and testing come late, when changes are most costly.
@end

@concept V-model
@plain
The V-model is waterfall with testing planned in parallel. Every design phase on the left of the V has a matching test phase on the right.
@problem
Plain waterfall leaves test design to the end. In safety or regulated systems you must show that every requirement was verified.
@does
- Requirements pair with acceptance tests, architecture with system tests, detailed design with integration tests, code with unit tests.
- Test plans are written while the matching phase is being specified, which finds ambiguity early.
- Produces strong traceability, common in automotive, medical and aerospace software.
- Still sequential, so late change is still costly.
@diagram cmp
caption: Each design level has a test level
cards:
  - {h: "Requirements", kind: info, items: ["Paired with acceptance testing", "Does it meet the business need"]}
  - {h: "Architecture", kind: app, items: ["Paired with system testing", "Does the whole behave"]}
  - {h: "Detailed design", kind: env, items: ["Paired with integration testing", "Do modules work together"]}
  - {h: "Code", kind: ok, items: ["Paired with unit testing", "Does each unit work"]}
@h Traceability matrix
```text title="Requirement to test mapping"
REQ-12  Brake signal latency under 20 ms   ->  SYS-TEST-4  (bench), UNIT-TEST-31
REQ-13  Fault logged within 1 s            ->  INT-TEST-9,  UNIT-TEST-40
REQ-14  Firmware update is signed          ->  SYS-TEST-7   (security)
```
@check
What does the V-model add to waterfall? || Test activities defined alongside each design phase, with traceability.
@end

@concept Incremental and iterative development
@plain
**Incremental**: build the product in slices, each slice working and releasable. **Iterative**: build a rough version, then refine it repeatedly. Most modern methods do both.
@problem
Delivering everything at once hides risk. Users cannot describe what they want until they see something.
@does
- Incremental delivery gets the first usable slice out early and adds capability each cycle.
- Iteration lets design improve using feedback from the previous cycle.
- Each cycle repeats mini versions of the full SDLC.
- Needs a modular design so slices can be added without rework.
@diagram flow
caption: Cycles instead of a single pass
nodes:
  - "Cycle 1|core checkout|app"
  - "Cycle 2|discounts|app"
  - "Cycle 3|returns|app"
  - "Cycle 4|reports|app"
@h Slicing vertically
```text title="Slice through all layers, not one layer at a time"
Bad slicing    Month 1 database, month 2 API, month 3 UI   (nothing usable until month 3)
Good slicing   Week 1  one product listing: DB table, API call, simple page
               Week 2  add search to the same path
               Week 3  add filters
```
@check
What is a vertical slice? || A thin feature that cuts through every layer, from UI to data, and works end to end.
@end

@concept Spiral model
@plain
The spiral model repeats four steps in loops: set objectives, analyse risks, build and test, and plan the next loop. Each loop starts with the biggest risk.
@problem
Some projects fail from a specific unknown, such as unproven technology or a hard integration. Waterfall postpones tackling it until it is too late.
@does
- Each loop produces a prototype or increment that addresses the highest risk first.
- A formal risk analysis step decides whether to continue, change or stop.
- Useful for large, expensive, high uncertainty projects; heavy for small teams.
- Its core idea, "attack the riskiest thing first", lives on in modern spikes and proofs of concept.
@diagram flow
caption: One loop of the spiral
numbered: true
nodes:
  - "Objectives|what this loop should achieve|info"
  - "Risk analysis|biggest unknown first|warn"
  - "Build and test|prototype or increment|app"
  - "Review and plan|continue or stop|ok"
@h A spike for risk
```text title="Spike ticket"
Spike     Can we stream 20 000 events per second from Kafka into our reporting store?
Time box  3 days
Output    Measured throughput, a recommendation, and a go or no-go
```
@check
What does the spiral model do first in each loop? || Look at objectives and then the riskiest unknown, so risk drives the plan.
@end

@concept Prototyping and RAD
@plain
Prototyping builds a quick, throwaway or evolving model to show users and learn what is really needed. Rapid Application Development (RAD) combines that with short builds and heavy user involvement.
@problem
Written requirements are interpreted differently by each reader. People recognise what they want when they see it.
@does
- Low-fidelity prototypes (sketches, clickable mock-ups) test ideas cheaply before engineering effort.
- Throwaway prototypes are discarded; evolutionary ones grow into the product, with the risk that quick code becomes permanent.
- Today this appears as design sprints, A/B tests and MVP releases.
@diagram cmp
caption: Two prototype styles
cards:
  - {h: "Throwaway", kind: warn, items: ["Answers a question fast", "Never goes to production", "Must be actually discarded"]}
  - {h: "Evolutionary", kind: ok, items: ["Grows into the product", "Needs tests and design early", "Faster to first release"]}
@h A cheap experiment
```bash title="A fake API for the front-end team to try" lab
mkdir -p /tmp/mock && echo '{"id":42,"status":"SHIPPED"}' > /tmp/mock/order.json
(cd /tmp/mock && timeout 2 python3 -m http.server 8099 >/dev/null 2>&1 &) ; sleep 1
curl -s localhost:8099/order.json
```
@check
Why is a throwaway prototype risky? || Management may ask to ship it, carrying untested shortcuts into production.
@end

@concept Choosing a plan-driven model
@plain
No model is best. The right one depends on how well requirements are known, how costly change is and what rules apply.
@problem
Picking a process because it is fashionable, or applying one blindly, produces ceremony without benefit.
@does
- Stable requirements, high cost of failure, contractual fixed scope: more plan-driven (waterfall, V-model).
- Unclear requirements, need for fast learning: iterative and agile.
- Large uncertain technical risk: spiral style risk-first loops.
- Many organisations mix: a regulated plan-driven outer layer with agile delivery inside.
@diagram cmp
caption: Rule of thumb for model choice
cards:
  - {h: "Requirements clear, change costly", kind: info, items: ["Waterfall or V-model", "Example: avionics firmware"]}
  - {h: "Requirements unclear", kind: ok, items: ["Iterative and agile", "Example: consumer web app"]}
  - {h: "High technical risk", kind: warn, items: ["Spiral or spikes first", "Example: new data platform"]}
@choose Plan-driven or adaptive
Waterfall or V-model | scope fixed by contract or regulation and well understood | users still discovering what they need
Spiral or risk-first | large, costly project with major unknowns | small, familiar changes
Agile or DevOps | product evolves with feedback and can release often | physical product cannot be changed after shipping
@end
