---
title: Requirements, user stories and architecture documentation
minutes: 50
objectives:
  - Write user stories with testable acceptance criteria
  - Turn vague quality wishes into measurable non functional requirements
  - Draw the four C4 levels for a system
  - Record decisions as short ADRs and keep documentation next to code
---
Most expensive mistakes are made before any code is written: building the wrong thing, or building it in a way nobody can later explain. This page covers the writing that prevents both.

@concept Functional and non functional requirements
@plain
A **functional** requirement says what the system does ("a customer can reset a password"). A **non functional** requirement says how well it does it: speed, availability, security, cost.
@problem
Teams agree on features and discover in production that nobody defined how fast, how available or how secure it had to be.
@does
- Functional requirements become stories and tests.
- Non functional requirements shape architecture: a 99.99 percent target leads to multi zone design and costs far more than 99.9 percent.
- Constraints (budget, region, existing tools) also count as requirements.
@diagram cmp
caption: Two kinds of requirement
cards:
  - {h: "Functional", kind: app, items: ["What the system does", "Customer can reset password", "Verified by feature tests"]}
  - {h: "Non functional", kind: cp, items: ["How well it does it", "Login under 300 ms for 95 percent", "Verified by load and chaos tests"]}
  - {h: "Constraints", kind: warn, items: ["Data stays in the EU", "Must run on Kubernetes"]}
@h Capture them
```yaml title="requirements.yaml"
service: checkout
functional:
  - id: F1
    text: A customer can pay by card and receives an order confirmation email
non_functional:
  - {id: N1, quality: latency, target: "p95 under 400 ms at 200 requests per second"}
  - {id: N2, quality: availability, target: "99.9 percent per 30 days, 43.2 minutes of budget"}
constraints:
  - Card data never stored outside the payment provider
```
@check
Which kind of requirement drives the choice of multi zone deployment? || Non functional, specifically the availability target.
@end

@concept User stories and the INVEST checklist
@plain
A **user story** states a need from the user's point of view: "As a role, I want a goal, so that a benefit". It starts a conversation instead of replacing it.
@problem
Long specification documents are out of date as soon as they are written and hide the reason behind each feature.
@does
- Template: As a (who), I want (what), so that (why). The "so that" is the part people skip and the part that allows better solutions.
- **INVEST**: Independent, Negotiable, Valuable, Estimable, Small, Testable.
- Slice vertically (a thin end to end feature) rather than horizontally (all database work first).
- Larger work is an **epic**; split it until a story fits in a few days.
@diagram flow
caption: From need to sprint backlog
numbered: true
nodes:
  - "Epic|customers manage payments|plain"
  - "Story|save a card for later|app"
  - "Acceptance criteria|how we know it works|info"
  - "Tasks|code, tests, deploy|ok"
@h A good story
```yaml title="story.yaml"
id: SHOP-142
title: Save a card for faster checkout
story: >
  As a returning customer, I want to save my card,
  so that I can pay in one click next time.
invest_check:
  small: yes, about 3 days
  testable: yes, see criteria
```
@check
Which INVEST letter does "split it until it fits in a few days" serve? || Small.
@end

@concept Acceptance criteria and Given When Then
@plain
**Acceptance criteria** are concrete examples that must pass for the story to be done. **Given When Then** (Gherkin) is a readable format: the starting state, the action, the expected result.
@problem
"It works" means different things to the developer, tester and product owner, so work returns for rework late.
@does
- Each criterion is a testable example with specific numbers, not a goal.
- Gherkin scenarios can be automated with Cucumber, Behave or pytest-bdd, so documentation and tests are the same file.
- Include the unhappy paths: errors, limits, permissions.
@diagram seq
caption: One scenario
actors: ["Customer|has a saved card|app", "Checkout|the system|cp"]
steps:
  - "0>1: pay with saved card | req"
  - "1>0: confirmation shown | resp"
  - "0>1: card expired | bad"
  - "1>0: ask for a new card | resp"
@h Scenarios
```gherkin title="saved_card.feature" nocheck
Feature: Saved card
  Scenario: Pay with a valid saved card
    Given a customer with a saved card expiring in 2028
    When they confirm an order of 49.90
    Then the payment is accepted
    And a confirmation email is sent

  Scenario: Saved card has expired
    Given a customer with a saved card expiring in 2024
    When they confirm an order of 49.90
    Then the payment is declined with "Card expired"
    And they are asked to add a new card
```
@check
Why include unhappy paths in acceptance criteria? || Because most defects and production incidents arise from errors and edge cases.
@end

@concept Turning quality into numbers
@plain
Words like "fast", "reliable" and "secure" cannot be tested. A measurable target names the metric, the level, the load and the time window.
@problem
Without numbers, disagreements about quality are opinions, and nobody knows when the work is finished.
@does
- Latency: a percentile (p95 or p99), not an average, under a stated load.
- Availability: a percentage over a window, which converts to minutes: 99.9 percent over 30 days is 43.2 minutes.
- Capacity: 1 million orders per day is about 11.6 per second on average (1000000 divided by 86400); peaks are a multiple, for example 5 times is about 58 per second.
- These become SLOs and load test pass criteria.
@diagram flow
caption: From a wish to a gate
nodes:
  - "Wish|the site must be fast|warn"
  - "Metric|p95 latency|info"
  - "Target|under 400 ms at 200 rps|app"
  - "Test gate|fails the pipeline if missed|ok"
@h Compute the numbers
```python title="Requirement arithmetic" lab
per_day = 1_000_000
avg = per_day / 86400
print("average per second", round(avg, 1), "peak x5", round(avg * 5, 1))
for slo in (0.99, 0.999, 0.9999):
    print(slo, "allows", round((1 - slo) * 30 * 24 * 60, 1), "minutes down per 30 days")
```
@check
Why use p95 instead of the average? || Averages hide the slow tail that real users experience.
@end

@concept The C4 model: context and containers
@plain
**C4** describes software at four zoom levels: Context, Containers, Components, Code. Each diagram answers one question for one audience.
@problem
Architecture diagrams mix users, servers, classes and cloud icons in one picture, so nobody can read them.
@does
- **Level 1 System Context**: your system as one box, with the people and other systems around it. Audience: everyone.
- **Level 2 Containers**: the separately runnable parts (web app, API, database, queue). "Container" here means a deployable unit, not necessarily Docker.
- Keep every box labelled with name, type and a short description; every arrow with purpose and protocol.
@diagram flow
caption: Level 1 context for an online shop
nodes:
  - "Customer|person|ext"
  - "Shop system|sells products online|app"
  - "Payment provider|external system|ext"
  - "Email service|external system|ext"
@diagram flow
caption: Level 2 containers inside the shop system
nodes:
  - "Web app|React, served by CDN|app"
  - "Orders API|Go on Kubernetes|app"
  - "PostgreSQL|orders data|db"
  - "Queue|order events|info"
@h Plain text sources
```text title="docs/context.md body, a Mermaid C4 block that GitHub renders"
C4Context
  Person(customer, "Customer")
  System(shop, "Shop system", "Sells products online")
  System_Ext(pay, "Payment provider")
  Rel(customer, shop, "Orders via HTTPS")
  Rel(shop, pay, "Charges cards", "HTTPS")
```
Place those lines inside a fenced block marked `mermaid` in your markdown file.
@check
At which C4 level do you show the database? || Level 2, containers.
@end

@concept The C4 model: components and code
@plain
**Level 3** zooms into one container and shows its components (controllers, services, repositories). **Level 4** is the code itself, usually generated from source, and rarely drawn by hand.
@problem
New engineers cannot find where a change belongs, and reviewers cannot see whether a change breaks the intended structure.
@does
- Draw level 3 only for the containers that are complex or contested.
- Add supplementary diagrams when needed: deployment (which container runs on which node or zone) and dynamic (sequence of a key flow).
- Generate diagrams from a model (Structurizr DSL) so they stay consistent.
@diagram layers
caption: Level 3 components inside the Orders API
layers:
  - {label: "Interface", nodes: ["REST controller|HTTP handlers|app"]}
  - {label: "Domain", nodes: ["Order service|business rules|cp", "Pricing|discounts and tax|cp"]}
  - {label: "Infrastructure", nodes: ["Repository|SQL access|env", "Event publisher|queue client|env"]}
@h A model in code
```text title="workspace.dsl for Structurizr" nocheck
workspace {
  model {
    customer = person "Customer"
    shop = softwareSystem "Shop" {
      api = container "Orders API" "Go" "REST"
      db  = container "PostgreSQL" "Orders data" "Database"
    }
    customer -> api "Places orders" "HTTPS"
    api -> db "Reads and writes" "SQL"
  }
  views {
    container shop { include * autolayout lr }
  }
}
```
@check
Who is the audience of level 1? || Everyone, including non technical stakeholders.
@end

@concept Architecture Decision Records
@plain
An **ADR** is a short document recording one significant decision: the context, the options considered, the choice and its consequences.
@problem
Six months later nobody remembers why the team picked a queue over direct calls, so people either keep it blindly or repeat the debate.
@does
- One decision per file, numbered, stored in the repository (`docs/adr/0007-use-postgresql.md`).
- Statuses: proposed, accepted, superseded by ADR n. Never edit history; add a new ADR that supersedes the old one.
- Keep it to one page. Write it when a decision is expensive to reverse or affects several teams.
@diagram flow
caption: Life of an ADR
numbered: true
nodes:
  - "Proposed|opened in a pull request|info"
  - "Discussed|reviewed by the team|app"
  - "Accepted|merged to main|ok"
  - "Superseded|replaced by a newer ADR|warn"
@h Template
```markdown title="docs/adr/0007-use-postgresql.md" nocheck
# 7. Use PostgreSQL for the orders service
Status: Accepted (2026-10-31)

## Context
Orders need transactions and reporting joins. The team operates PostgreSQL already.

## Options
1. PostgreSQL on RDS  2. DynamoDB  3. MongoDB

## Decision
Use PostgreSQL on RDS, Multi-AZ, with point in time recovery.

## Consequences
+ Familiar tooling, strong consistency.
- Vertical scaling limits; read replicas needed beyond about 5000 writes per second (to be measured).
```
:::tip
A good ADR lists the options that were rejected and why. That is the part future readers value most.
:::
@end

@concept Documentation as code
@plain
Keep documentation in the same repository and review process as the code, in plain text formats, built and published by the pipeline.
@problem
Wikis rot because updating them is a separate step nobody owns, and a stale diagram is worse than none.
@does
- Markdown plus Mermaid or PlantUML diagrams, checked in next to the service; a `docs/` folder and a README per service.
- CI checks: markdown lint, broken link check, diagram render, and a rule that a pull request touching an API also touches its docs.
- Documentation types (Diataxis): tutorials, how to guides, reference, explanation. Do not mix them in one page.
- Publish with MkDocs or Docusaurus, and surface in the developer portal.
@diagram flow
caption: Docs travel with the code
nodes:
  - "Pull request|code and docs together|app"
  - "CI|lint, links, diagrams|cp"
  - "Build site|MkDocs or Docusaurus|info"
  - "Portal|always current|ok"
@h CI check
```yaml title=".github/workflows/docs.yml"
name: docs
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Lint markdown
        run: npx --yes markdownlint-cli2 "docs/**/*.md" "README.md"
      - name: Check links
        run: npx --yes markdown-link-check README.md
```
@check
Why keep docs in the code repository? || They are reviewed and versioned with the change, so they stay accurate.
@end
