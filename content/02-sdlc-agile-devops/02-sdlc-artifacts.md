---
title: SDLC artifacts and governance
minutes: 40
objectives:
  - Identify the key documents and records produced in each phase
  - Write user stories with acceptance criteria and a clear definition of done
  - Describe change management, traceability and what auditors expect from a pipeline
---
An **artifact** is anything a phase produces that someone else relies on: a requirements list, a design record, a built image, a test report, a runbook. Good teams keep artifacts few, current and close to the code.

@concept Artifacts by phase
@plain
Each phase leaves behind evidence and inputs for the next one. Knowing them tells you what "done" means for a phase.
@problem
Hand-offs fail when the receiver does not know what they should get. Missing runbooks, undocumented configuration and unknown test coverage are all missing artifacts.
@does
- Planning: business case, scope, risk register, roadmap.
- Requirements and design: backlog items, acceptance criteria, ADRs, diagrams, threat model, API contracts.
- Build and test: source, merged pull requests, build logs, test and coverage reports, container images, SBOM.
- Release and operations: release notes, change record, runbooks, dashboards, alerts, postmortems.
@diagram layers
caption: Where artifacts live
layers:
  - {label: "Plan", nodes: ["Roadmap|ticket tracker|info", "Risk register|wiki|info"]}
  - {label: "Design", nodes: ["ADRs|in Git|app", "API contract|OpenAPI in Git|app"]}
  - {label: "Build", nodes: ["Source|Git|app", "Image + SBOM|registry|env"]}
  - {label: "Run", nodes: ["Runbooks|next to the code|ok", "Dashboards|observability stack|ok"]}
@h Keep artifacts near the code
```bash title="A repository layout that carries its own artifacts" lab
mkdir -p /tmp/shop/{src,docs/adr,deploy,runbooks,.github/workflows}
touch /tmp/shop/README.md /tmp/shop/docs/adr/0001-record-decisions.md /tmp/shop/runbooks/high-latency.md
find /tmp/shop | sort
```
@check
Which artifact would you open first at 3 a.m. during an alert? || The runbook linked from that alert.
@end

@concept User stories and acceptance criteria
@plain
A **user story** states a need from the user's side: "As a customer, I want to see my order status, so that I know when it arrives." **Acceptance criteria** are the checks that prove it is done.
@problem
Long specification documents are read by nobody and go stale. One-line feature requests leave out the conditions that decide whether it works.
@does
- A story follows the INVEST ideas: independent, negotiable, valuable, estimable, small, testable.
- Acceptance criteria are often written as Given / When / Then scenarios, which map directly to automated tests.
- Stories are a conversation starter, not a contract; details are agreed when the work is picked up.
@diagram flow
caption: From need to test
numbered: true
nodes:
  - "Story|as a customer I want|app"
  - "Criteria|given, when, then|info"
  - "Automated test|Gherkin or code|warn"
  - "Done|criteria pass|ok"
@h Example
```text title="Story with acceptance criteria"
Story    As a customer I want to see my order status so that I know when it arrives.

Scenario Order shipped
  Given an order with status SHIPPED and a tracking number
  When the customer opens the order page
  Then the page shows "Shipped" and a tracking link

Scenario Unknown order
  Given an order id that does not exist
  When the customer opens the order page
  Then the response is 404 and the page shows a friendly message
```
@check
Why write criteria as Given, When, Then? || They are concrete, unambiguous and can become automated tests with little translation.
@end

@concept Definition of ready and definition of done
@plain
The **definition of ready** says when a work item is clear enough to start. The **definition of done** says what must be true before it counts as finished. Both are short team agreements.
@problem
Without them, "done" means "coded" to a developer, "tested" to QA and "live" to the product owner. Unfinished work accumulates silently.
@does
- Ready: has a clear goal, acceptance criteria, known dependencies and fits in one iteration.
- Done: code reviewed and merged, tests pass in CI, security scan clean, documentation and dashboards updated, deployed behind a flag or live.
- Raise the bar as the team matures; for DevOps teams "done" often means running in production and observed.
@diagram cmp
caption: Ready versus done
cards:
  - {h: "Definition of ready", kind: info, items: ["Clear value and criteria", "Dependencies known", "Small enough for one sprint"]}
  - {h: "Definition of done", kind: ok, items: ["Reviewed, tested, scanned", "Deployed and monitored", "Docs and runbook updated"]}
@h A done checklist as a pull request template
```markdown title=".github/pull_request_template.md" nocheck
## Definition of done
- [ ] Tests added or updated and passing in CI
- [ ] No new critical or high findings in the dependency and image scan
- [ ] Metrics, logs and alerts updated if behaviour changed
- [ ] Runbook or README updated
- [ ] Rollback plan stated for risky changes
```
@check
Who owns the definition of done? || The whole team, agreed and revisited in retrospectives.
@end

@concept Traceability from requirement to production
@plain
Traceability means you can follow a requirement to the code that implements it, the tests that check it and the release that shipped it, and back.
@problem
When an auditor or an incident asks "why does this behave like this" or "which release introduced it", missing links turn a five minute answer into days.
@does
- Reference the ticket ID in branch names and commits, for example `SHOP-142`.
- Let CI attach the commit, build and image digest to a release record.
- Use Git tags or release notes generated from merged pull requests.
- Tools: issue tracker, Git, CI, registry and deployment history together form the chain.
@diagram flow
caption: A traceable chain
nodes:
  - "Ticket|SHOP-142|info"
  - "Commit and PR|references the ticket|app"
  - "Build|image digest|env"
  - "Deploy|environment + time|ok"
@h Finding the link
```bash title="Navigate the chain with Git" lab
git log --oneline --grep 'SHOP-142' | head           # commits for a ticket
git tag --contains "$(git rev-parse HEAD)" | head -3   # releases containing a commit
git describe --tags --always                          # nearest tag for the current code
```
@check
How do you link a commit to a ticket cheaply? || Put the ticket ID in the commit message or branch name and enforce it with a hook or CI check.
@end

@concept Change management in a pipeline
@plain
Change management is how an organisation decides, records and approves changes to production. DevOps replaces slow manual boards with automated, evidence-based controls for routine changes.
@problem
A weekly approval board makes every change wait and does not actually lower risk: reviewers see a description, not the evidence. Teams then batch changes, raising risk.
@does
- **Standard changes** (pre-approved, low risk, automated) pass through the pipeline with tests, review and scans as the control.
- **Normal changes** (new, higher risk) get peer review and sometimes explicit approval.
- **Emergency changes** are fast but reviewed afterwards.
- The pipeline records who approved, what was tested and what was deployed, giving an audit trail by default.
@diagram cmp
caption: Change types
cards:
  - {h: "Standard", kind: ok, items: ["Pre-approved pattern", "Automated evidence", "Most deployments"]}
  - {h: "Normal", kind: app, items: ["Reviewed and approved", "New or riskier work", "Planned window if needed"]}
  - {h: "Emergency", kind: bad, items: ["Fix an active incident", "Fast path, review afterwards", "Keep the count low"]}
@h Protecting production with required approvals
```yaml title="Environment protection in GitHub Actions" nocheck
jobs:
  deploy-prod:
    runs-on: ubuntu-latest
    environment: production        # configured with required reviewers
    steps:
      - run: echo "deploy ${{ github.sha }}"
```
@check
Why can automated checks beat a change board? || They inspect the actual change on every deployment and leave a record, instead of relying on a description.
@end

@concept Documentation that stays alive
@plain
Documentation is useful when it is easy to find, short and updated with the change. Docs separate from the code usually rot.
@problem
Nobody trusts wiki pages that are two years old, so engineers ask people instead, and knowledge leaves with them.
@does
- Four kinds, often called Diataxis: **tutorials** (learn), **how-to guides** (solve a task), **reference** (facts) and **explanation** (why).
- Docs as code: Markdown in the repository, reviewed in the same pull request as the change.
- Generate what can be generated: API docs from OpenAPI, diagrams from text (Mermaid), CLI help.
- Test links and examples in CI.
@diagram layers
caption: Four documentation types
layers:
  - {label: "Learning", nodes: ["Tutorial|first steps|info", "Explanation|why it works this way|info"]}
  - {label: "Working", nodes: ["How-to|fix a specific problem|app", "Reference|exact facts|app"]}
@h Link checking in CI
```bash title="Find broken relative links quickly" lab
grep -rhoE '\]\((\./|\.\./)[^)]+\)' docs 2>/dev/null | head -5
echo "use a tool such as lychee or markdown-link-check in CI for the full check"
```
@check
Where should the runbook for a service live? || In the service's repository, versioned and reviewed with the code it describes.
@end
