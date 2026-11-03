---
title: Agile, Lean and DevOps as SDLC models
minutes: 40
objectives:
  - State the Agile Manifesto values and how they differ from plan-driven thinking
  - Explain Lean ideas such as waste, flow and limiting work in progress
  - Show how DevOps extends agile through delivery and operations and how DevSecOps and platform teams build on it
---
Agile, Lean and DevOps are not three competing models. They stack. Lean provides the thinking about flow, Agile organises the team around short feedback loops, and DevOps extends those loops all the way to production and back.

@concept The Agile Manifesto
@plain
In 2001 a group of practitioners wrote four value statements and twelve principles for software work. The key idea is to deliver working software in small steps and adjust based on feedback.
@problem
Heavy upfront planning and documentation could not keep up with changing needs. Projects delivered what was specified two years earlier, not what was needed now.
@does
- The four values prefer: individuals and interactions over processes and tools; working software over comprehensive documentation; customer collaboration over contract negotiation; responding to change over following a plan.
- The items on the right still matter. The statement says the left side matters more.
- Principles include frequent delivery (weeks, not months), sustainable pace, technical excellence and regular reflection.
@diagram cmp
caption: The four Agile values
cards:
  - {h: "People over process", kind: app, items: ["Talk instead of hand off", "Tools support the team"]}
  - {h: "Working software", kind: ok, items: ["Progress measured by running code", "Documentation stays useful"]}
  - {h: "Collaboration", kind: info, items: ["Customer is part of the team", "Contracts allow change"]}
  - {h: "Respond to change", kind: env, items: ["Plan is a guide", "Replan every iteration"]}
@h Misreading to avoid
```text title="Common misreadings"
"Agile means no documentation"     No. It means only the documentation that has a reader.
"Agile means no planning"          No. It plans continuously in small horizons.
"Agile means fast"                 It means short feedback loops, with sustainable pace.
"We do Scrum so we are agile"      Ceremonies without delivery and learning are not agile.
```
@check
Does the Manifesto reject documentation? || No, it values working software more than comprehensive documentation.
@end

@concept Lean thinking and waste
@plain
Lean comes from manufacturing (Toyota). It asks you to deliver value to the customer as fast as possible by finding and removing waste, and by making work flow smoothly.
@problem
Teams can be busy and still slow because work sits in queues, waits for approvals or is redone. Busy does not mean productive.
@does
- Software forms of waste: partially done work, extra features nobody uses, relearning, hand-offs, task switching, delays and defects.
- **Flow efficiency** is the share of lead time in which work is actively being done. Many organisations find it is 10 percent or less.
- **Work in progress (WIP)** limits reduce multitasking and show bottlenecks.
- Little's Law links the numbers: average lead time = work in progress divided by throughput.
@diagram flow
caption: Value stream with waiting highlighted
nodes:
  - "Idea|0 days|info"
  - "Waiting for review|4 days|warn"
  - "Coding|1 day|app"
  - "Waiting for QA|5 days|warn"
  - "Release|0.5 day|ok"
@h Flow efficiency calculation
```python title="Active time versus lead time" lab
steps = [("coding", 1.0, True), ("review wait", 4.0, False), ("test", 0.5, True), ("qa queue", 5.0, False), ("release", 0.5, True)]
lead = sum(d for _, d, _ in steps)
active = sum(d for _, d, a in steps if a)
print(f"lead time {lead} days, active {active} days, flow efficiency {active / lead:.0%}")
wip, throughput = 12, 3          # items in progress, finished per week
print(f"Little's Law lead time: {wip / throughput} weeks")
```
@check
Name two ways to improve flow without working harder. || Limit work in progress and shrink waiting times such as review and approval queues.
@end

@concept Agile delivery frameworks at a glance
@plain
Agile is a set of values. Frameworks are concrete ways to apply them. The common ones are Scrum, Kanban, Extreme Programming (XP) and scaling approaches such as SAFe.
@problem
Teams need practical rhythms for planning and working, but copying a framework blindly without understanding the purpose creates ritual.
@does
- **Scrum** adds fixed-length sprints and roles; **Kanban** visualises flow with WIP limits; **XP** adds engineering practices such as TDD and pair programming.
- Most teams blend them: Scrum events with Kanban boards and XP practices (this is often called Scrumban).
- Scaling frameworks coordinate many teams; many organisations prefer lighter coordination through shared goals and platform teams.
- Details of each appear in the next section.
@diagram layers
caption: How the pieces stack
layers:
  - {label: "Thinking", nodes: ["Lean|flow and waste|info", "Agile values|feedback and change|info"]}
  - {label: "Team method", nodes: ["Scrum|sprints|app", "Kanban|continuous flow|app"]}
  - {label: "Engineering", nodes: ["XP practices|TDD, CI, pairing|env", "DevOps|automation to production|ok"]}
@choose Which framework to start with
Scrum | cross-functional team with a product owner and planned increments | work is mostly unplanned interrupts like support
Kanban | continuous flow, operations or platform work | you need fixed commitments for a date
XP practices | any team that wants better code quality | no one can commit time to automated testing
@end

@concept DevOps as an extension of agile
@plain
Agile helped teams build software in short cycles, but the finished work often waited weeks for operations to release it. DevOps removes that wall by sharing responsibility from commit to production.
@problem
Development wanted change, operations wanted stability, and each was measured against the other. The result was slow, fearful releases.
@does
- Automates build, test, deploy and infrastructure so releases are routine.
- Makes teams own what they run ("you build it, you run it") with shared on-call.
- Uses monitoring and production data as feedback for the next iteration.
- Culture and measurement come first; tools alone are not DevOps.
@diagram flow
caption: The DevOps infinity loop in words
nodes:
  - "Plan|backlog|info"
  - "Code|branch, review|app"
  - "Build and test|CI|warn"
  - "Release and deploy|CD|env"
  - "Operate|run|ok"
  - "Monitor|feedback|info"
@h The loop as pipeline stages
```yaml title="Minimal pipeline covering the loop" nocheck
stages: [build, test, scan, deploy, verify]
build:  { script: ["docker build -t $IMAGE:$CI_COMMIT_SHA ."] }
test:   { script: ["make test"] }
scan:   { script: ["trivy image --exit-code 1 --severity HIGH,CRITICAL $IMAGE:$CI_COMMIT_SHA"] }
deploy: { script: ["kubectl set image deploy/api api=$IMAGE:$CI_COMMIT_SHA"] }
verify: { script: ["curl -fsS https://api.example.com/healthz"] }
```
@check
What does DevOps add to agile? || Automation and shared ownership across build, release and operation, so feedback comes from production.
@end

@concept Shift left and continuous everything
@plain
Shift left means moving checks such as testing, security and operability review earlier, to where they are cheaper. "Continuous" practices run those checks on every change.
@problem
Finding problems at the end of the process is slow and demoralising. Security review a week before a release usually ends in delay or risk acceptance.
@does
- **Continuous integration**: merge and test often. **Continuous delivery**: every change is releasable. **Continuous deployment**: every passing change ships automatically.
- Shift left examples: linting in the editor, unit tests on commit, policy checks on pull requests, image scans in the build.
- Shift right adds testing in production: canaries, synthetic checks, chaos experiments.
- Both are needed; neither replaces the other.
@diagram flow
caption: Checks move earlier and later
nodes:
  - "Editor|lint, secrets scan|ok"
  - "Pull request|tests, policy|ok"
  - "Pipeline|scan, integration tests|ok"
  - "Production|canary, SLO monitoring|ok"
@h Quick local shift-left hooks
```bash title="A Git pre-commit hook" lab
mkdir -p /tmp/hookdemo && cd /tmp/hookdemo && git init -q .
cat > .git/hooks/pre-commit <<'HOOK'
#!/usr/bin/env bash
if git diff --cached | grep -E 'AKIA[0-9A-Z]{16}'; then echo "possible AWS key, commit blocked" >&2; exit 1; fi
HOOK
chmod +x .git/hooks/pre-commit
echo "key=AKIAABCDEFGHIJKLMNOP" > leak.txt && git add leak.txt && git commit -qm test || echo "blocked as expected"
```
@check
Difference between continuous delivery and continuous deployment? || Delivery keeps every change releasable with a manual release decision; deployment releases automatically.
@end

@concept DevSecOps and platform engineering
@plain
**DevSecOps** builds security checks into the pipeline instead of reviewing at the end. **Platform engineering** gives product teams a ready-made, self-service path to build, deploy and run, so each team does not rebuild the same tooling.
@problem
As systems grew, every team needed expertise in Kubernetes, cloud, security and observability, which is too much cognitive load. Inconsistent setups became security and cost problems.
@does
- DevSecOps: automated scans (code, dependencies, images, infrastructure as code), secrets detection, signed artifacts and policy as code.
- A platform team offers an **internal developer platform** with golden paths: templates, shared pipelines, standard clusters and dashboards.
- The platform is treated as a product with users, a roadmap and feedback.
- Teams stay free to deviate, but the paved path is the easiest.
@diagram layers
caption: A platform between teams and infrastructure
layers:
  - {label: "Product teams", nodes: ["Shop team|owns services|app", "Payments team|owns services|app"]}
  - {label: "Internal platform", nodes: ["Templates|golden paths|cp", "Shared CI/CD|pipelines|cp", "Observability|dashboards, alerts|cp"]}
  - {label: "Infrastructure", nodes: ["Kubernetes|clusters|env", "AWS|accounts, networking|env"]}
@h Golden path example
```bash title="One command to a new service" lab
echo "platformctl new service --name orders --language go --team shop"
echo "creates repo, pipeline, Helm chart, dashboard, alerts and an SLO file from templates"
```
@check
What problem does platform engineering solve? || It reduces the cognitive load and duplication of every team assembling its own delivery tooling.
@end
