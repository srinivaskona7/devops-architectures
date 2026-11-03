---
title: SDLC phases
minutes: 40
objectives:
  - Name the phases of the software development life cycle and what each one produces
  - Explain why cost of change rises the later a defect is found
  - Map each phase to the DevOps practices and tools that support it
---
The **software development life cycle (SDLC)** is the set of stages every piece of software passes through, from an idea to retirement. Every team has one, written down or not. DevOps does not remove these stages. It shortens the loops between them and automates the hand-offs.

@concept Why a life cycle exists
@plain
Building software without stages means building before you know what is wanted, testing after it is too late, and releasing without a plan. A life cycle gives work a shape: decide, build, check, release, run.
@problem
Unstructured work leads to rework. Studies and experience agree that fixing a defect found in production costs many times more than fixing the same defect when it was a line in a requirement.
@does
- Breaks a large uncertain job into smaller steps with clear outputs.
- Creates points where someone can say stop, change or go.
- Gives managers, engineers and auditors a shared vocabulary.
- Applies at any size: a one-line fix and a new platform both pass through the same stages, only the duration differs.
@diagram flow
caption: The classic SDLC loop
numbered: true
nodes:
  - "Plan|why and what|info"
  - "Design|how|app"
  - "Build|code and review|app"
  - "Test|prove it works|warn"
  - "Release|deploy|env"
  - "Operate|run and learn|ok"
@h Cost of change
```python title="Illustrative relative cost of fixing one defect" lab
# Commonly cited orders of magnitude, not exact measurements
stages = {"requirements": 1, "design": 5, "coding": 10, "testing": 20, "production": 100}
for name, cost in stages.items():
    print(f"{name:<13}{'#' * (cost // 5 or 1):<22}x{cost}")
```
@check
Why is a defect cheaper to fix early? || Fewer people, artifacts and customers depend on the wrong decision, so less has to be undone.
@end

@concept Planning and requirements
@plain
Planning decides whether to do the work and what the outcome should be. Requirements describe what the software must do (functional) and how well it must do it (non-functional).
@problem
Teams often build the wrong thing very well. Vague requests like "make it faster" cannot be tested or estimated.
@does
- Captures **functional** needs (a user can pay by card) and **non-functional** needs (99.9 percent availability, p95 latency under 300 ms, data stays in the EU).
- Identifies stakeholders: users, owners, security, operations, compliance.
- Produces a scope, success measures, risks and a rough budget.
- Operations requirements, such as monitoring and recovery time, belong here too. Raising them late is a classic source of friction.
@diagram cmp
caption: Two kinds of requirements
cards:
  - {h: "Functional", kind: app, items: ["What the system does", "A customer can reset a password", "Testable as pass or fail"]}
  - {h: "Non-functional", kind: cp, items: ["How well it does it", "Availability, latency, security, cost", "Needs a number to be testable"]}
@h Turning a vague wish into a testable requirement
```text title="Vague versus testable"
Vague      The checkout should be fast and reliable.
Testable   95 percent of checkout requests finish in under 400 ms over a 30 day window.
Testable   The checkout service is available 99.9 percent of minutes per month.
Testable   Card numbers are never written to logs. A CI check scans for 16 digit patterns.
```
@check
Give a non-functional requirement for a login API. || For example, p99 latency under 500 ms and 99.95 percent availability, measured monthly.
@end

@concept Design and architecture
@plain
Design decides how the system will meet the requirements: components, data, interfaces, hosting and security. Architecture is the set of design decisions that are expensive to change later.
@problem
Without a design, each developer makes private decisions and the pieces do not fit. Without recorded reasons, nobody remembers why a database or cloud region was chosen.
@does
- High level design sets components and boundaries; low level design details each API, table and algorithm.
- Considers constraints: team skills, budget, compliance, existing platforms such as Kubernetes or AWS.
- Records big decisions as **Architecture Decision Records (ADRs)**: context, decision, consequences.
- Includes threat modelling and capacity estimates before code exists.
@diagram layers
caption: Levels of design
layers:
  - {label: "Context", nodes: ["Users and systems|who talks to whom|ext"]}
  - {label: "Containers", nodes: ["Web app|UI|app", "API|business logic|app", "Database|state|env"]}
  - {label: "Platform", nodes: ["Kubernetes|runs the services|cp", "AWS|managed services|cp"]}
  - {label: "Decisions", nodes: ["ADRs|why we chose this|info"]}
@h A short ADR
```text title="docs/adr/0007-use-postgres.md"
# 7. Use PostgreSQL for orders
Status   Accepted, 2026-10-12
Context  Orders need transactions and reporting joins. The team knows SQL.
Decision Use Amazon RDS for PostgreSQL 16, Multi-AZ.
Consequences Strong consistency. Higher cost than DynamoDB at low volume. Schema migrations needed in CI.
```
@check
What goes into an ADR besides the decision? || The context that forced the choice and the consequences, good and bad.
@end

@concept Implementation
@plain
Implementation is writing, reviewing and integrating code. In a modern flow it includes the build, tests and review as part of the same activity.
@problem
Large changes written alone for weeks collide with everyone else's work and hide defects until the end.
@does
- Small changes in short-lived branches, reviewed by another person.
- Coding standards, linters and formatters enforced by tools rather than by arguing in reviews.
- Infrastructure is code too: Terraform, Helm and Kubernetes manifests are versioned, reviewed and tested.
- Continuous integration builds and tests every push, so a broken change shows within minutes.
@diagram flow
caption: Inner loop of implementation
numbered: true
nodes:
  - "Branch|small and short lived|app"
  - "Commit|with tests|app"
  - "Pull request|peer review|info"
  - "CI|build, lint, test|warn"
  - "Merge|to main|ok"
@h Local checks before pushing
```bash title="A repeatable pre-push routine" lab
git switch -c feature/order-status          # one small purpose per branch
git add -p                                  # review your own diff in pieces
git commit -m "Add order status endpoint"
git diff --stat origin/main...HEAD          # how big is this change?
```
@check
Why keep pull requests small? || They are reviewed faster and more carefully, merge with fewer conflicts and are easy to roll back.
@end

@concept Testing and verification
@plain
Testing checks that the software meets the requirements and does not break what already worked. It happens at several levels and, ideally, on every change.
@problem
Manual testing at the end is slow, inconsistent and the first thing cut when time is short. Releases then carry unknown risk.
@does
- **Unit** tests check one function; **integration** tests check parts together; **end-to-end** tests check a user journey; **non-functional** tests check load, security and resilience.
- **Verification** asks "did we build it right" (against the spec). **Validation** asks "did we build the right thing" (for the user).
- Automated tests run in the pipeline; exploratory testing by people finds what scripts do not expect.
- Test environments should resemble production in versions and configuration.
@diagram cmp
caption: Verification versus validation
cards:
  - {h: "Verification", kind: app, items: ["Built right", "Code meets the specification", "Unit and integration tests"]}
  - {h: "Validation", kind: ok, items: ["Right thing built", "Meets the user's real need", "Demos, UAT, usage data"]}
@h A test as a gate
```bash title="Fail the build when tests fail" lab
set -e
echo "running unit tests"; true       # replace with: pytest -q   or   go test ./...
echo "running linter"; true           # replace with: ruff check .
echo "gate passed"
```
@check
Which is validation, a unit test or a user acceptance session? || The user acceptance session, because it checks the product against the real need.
@end

@concept Deployment and release
@plain
Deployment puts a build into an environment. Release makes its features available to users. They can happen at different times.
@problem
Manual releases at midnight with a long checklist are error prone and stressful, so teams release rarely, making each release bigger and riskier.
@does
- Automated pipelines build one artifact, once, and promote the same artifact through environments.
- Strategies such as rolling, blue-green and canary reduce risk; feature flags separate deploy from release.
- Every release has a rollback or roll-forward path and a way to tell if it worked (health checks, metrics).
- Changes are recorded for audit: who deployed what, when, from which commit.
@diagram flow
caption: Build once, promote through environments
nodes:
  - "Artifact|image with digest|app"
  - "Dev|automatic|env"
  - "Staging|automatic + checks|env"
  - "Production|approved or automatic|ok"
@h Promotion by digest
```bash title="Deploy the exact tested image" lab
IMAGE=registry.example.com/shop/api
DIGEST=sha256:3f1c0e9d5a7b            # shortened example; use the full digest in real use
echo "kubectl set image deployment/api api=${IMAGE}@${DIGEST} -n staging"
echo "kubectl rollout status deployment/api -n staging --timeout=120s"
```
@check
Why promote the same artifact instead of rebuilding per environment? || A rebuild can produce different bytes, so what you tested is no longer what you ship.
@end

@concept Operations, maintenance and retirement
@plain
After release the software runs, is monitored, patched, extended and eventually retired. This is usually the longest and most expensive phase.
@problem
Treating release as the finish line leaves no one owning reliability, security patches or the cost of keeping old systems alive.
@does
- **Corrective** maintenance fixes bugs; **adaptive** keeps pace with platform changes; **perfective** improves features; **preventive** reduces future risk.
- Monitoring, alerting and on-call turn production behaviour into input for the next planning round.
- Dependencies and base images need regular updates; unmaintained ones become security debt.
- Retirement means migrating users, archiving data per policy and removing infrastructure so it stops costing money.
@diagram flow
caption: Operations feeds planning
nodes:
  - "Run|monitor and respond|ok"
  - "Learn|incidents and metrics|info"
  - "Plan|next improvements|app"
  - "Change|small releases|env"
  - "Retire|when value ends|warn"
@h Maintenance chores to automate
```bash title="Spot stale dependencies and images" lab
kubectl get pods -A -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}' 2>/dev/null | sort | uniq -c | sort -rn | head
echo "then compare tags against the latest supported versions and schedule updates"
```
@check
Name the four kinds of maintenance. || Corrective, adaptive, perfective and preventive.
@end
