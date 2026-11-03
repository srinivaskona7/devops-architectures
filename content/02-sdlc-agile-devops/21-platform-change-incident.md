---
title: Platform engineering, change management and incident command
minutes: 55
objectives:
  - Explain what an internal developer platform is and design a golden path
  - Describe Backstage and its software catalog
  - Compare ITIL change management with DevOps practice and automate approvals
  - Run an incident with clear roles and communication
---
As organisations grow, the question changes from "how do we deploy" to "how do fifty teams deploy safely without each reinventing it". This page covers the answer and the process around it.

@concept Platform engineering and the internal developer platform
@plain
An **internal developer platform** (IDP) is a set of self-service tools and defaults, built by a platform team, that lets developers create, deploy and run services without being infrastructure experts.
@problem
Without a platform each team builds its own pipeline, cluster setup and monitoring. Cognitive load rises, quality varies, and security reviews multiply.
@does
- Treat the platform as a **product**: developers are customers; measure adoption and satisfaction.
- Offer capabilities through APIs, templates and a portal: create service, provision database, deploy, observe, roll back.
- The platform team owns reliability of the platform, not of every application.
- Keep an escape hatch: teams with special needs can step off the path, at their own cost.
@diagram layers
caption: Layers of an internal developer platform
layers:
  - {label: "Developer interface", nodes: ["Portal (Backstage)|catalog, templates|app", "CLI and API|automation|app"]}
  - {label: "Orchestration", nodes: ["GitOps|Argo CD or Flux|cp", "CI pipelines|build and test|cp", "Policy|Kyverno or OPA|cp"]}
  - {label: "Infrastructure", nodes: ["Kubernetes|runtime|env", "Cloud accounts|Terraform modules|env", "Observability|metrics, logs, traces|env"]}
@h Platform as a product
```yaml title="platform-product-card.yaml"
customer: application developers in 12 product teams
problem: new service takes 3 weeks to reach production
outcome: new service in production within one day
capabilities: [service template, namespace with quotas, pipeline, dashboards, secrets]
metrics:
  - time to first deploy
  - share of services on the golden path
  - developer satisfaction survey, quarterly
```
@check
What distinguishes platform engineering from a central ops ticket queue? || Self-service, treated as a product with customers and metrics.
@end

@concept Golden paths
@plain
A **golden path** is the supported, well-lit route for a common task, such as building a web service: the template, pipeline, deployment settings and monitoring already wired together.
@problem
Giving developers total freedom produces dozens of ways to deploy. Forcing one rigid way breeds resentment and shadow IT.
@does
- The path is optional but so convenient that most teams choose it. Security, compliance and observability come built in.
- Contents: repository template, Dockerfile, CI pipeline, Helm chart or Kustomize base, default alerts, runbook skeleton, docs.
- Version the path. Provide upgrade tooling when it changes.
- Success measure: how long from "I want a service" to "serving traffic".
@diagram flow
caption: One path from idea to production
numbered: true
nodes:
  - "Pick template|in the portal|app"
  - "Repo created|code, CI, chart|info"
  - "First deploy|dev namespace|cp"
  - "Promote|staging, then prod|warn"
  - "Observe|dashboards and alerts exist|ok"
@h A template skeleton
```bash title="Repository produced by the golden path" lab
mkdir -p /tmp/gp/{src,deploy,.github/workflows,docs} && cd /tmp/gp
printf 'FROM python:3.12-slim\nUSER 10001\nCOPY src /app\nCMD ["python","/app/main.py"]\n' > Dockerfile
printf 'apiVersion: v1\nkind: Service\nmetadata:\n  name: svc\nspec:\n  ports: [{port: 80}]\n' > deploy/service.yaml
printf '# Runbook\n- dashboard link\n- how to roll back\n' > docs/runbook.md
find . -type f | sort
```
@check
Is a golden path mandatory? || No; it is the easiest supported path, with an escape hatch for special needs.
@end

@concept Backstage and the software catalog
@plain
**Backstage** is an open source developer portal. Its core is a **software catalog**: a searchable inventory of services, owners, APIs, docs and dependencies, described by YAML files in each repository.
@problem
Nobody can answer "who owns this service, where is its runbook, what depends on it" quickly, especially during an incident.
@does
- Each repository holds a `catalog-info.yaml`; Backstage reads it and builds the catalog.
- **Software templates** (scaffolder) create new repositories from the golden path.
- **TechDocs** renders markdown docs from the repo; plugins show Kubernetes status, CI runs and on-call.
- It is a framework you operate yourself; there are hosted offerings. Check the current Backstage documentation for setup.
@diagram flow
caption: Catalog data flow
nodes:
  - "catalog-info.yaml|in each repository|app"
  - "Backstage|ingests and indexes|cp"
  - "Catalog|owner, docs, dependencies|ok"
  - "Developers and on-call|find answers fast|ext"
@h Describe a service
```yaml title="catalog-info.yaml"
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: orders-api
  description: Order service for the shop
  annotations:
    github.com/project-slug: myorg/orders-api
    backstage.io/techdocs-ref: dir:.
spec:
  type: service
  lifecycle: production
  owner: team-orders
  system: shop
  dependsOn:
    - resource:default/orders-db
```
:::note
Validate the structure against the current Backstage descriptor format before relying on it; fields and API versions evolve.
:::
@end

@concept Change management: ITIL versus DevOps
@plain
**Change management** controls how changes reach production to limit risk. Traditional ITIL processes use a Change Advisory Board (CAB) that reviews requests. DevOps replaces most manual approval with automated evidence and small, frequent changes.
@problem
Heavy approval processes slow delivery but the research shows they do not reduce failure rates. No process at all causes outages from risky changes.
@does
- ITIL 4 classifies changes: **standard** (pre-approved, low risk), **normal** (assessed and authorised), **emergency**. Check the current ITIL guidance for definitions.
- DevOps approach: make most changes standard by proving safety automatically: tests, canary, automatic rollback, small batch size. Reserve human review for high-risk changes.
- The DORA research found external change approval boards correlate with slower delivery and no better stability; peer review in the pull request is more effective. Check the current DORA reports.
@diagram cmp
caption: Two approaches to the same goal
cards:
  - {h: "CAB driven", kind: warn, items: ["Weekly meeting", "Large batched releases", "Slow feedback"]}
  - {h: "Pipeline driven", kind: ok, items: ["Peer review and automated gates", "Small, frequent changes", "Audit trail from Git"]}
@choose Approval route
Pre-approved standard change | routine, well-tested, reversible, automated deploys | schema changes without rollback
Peer review plus automated gates | most application changes | regulated change requiring segregation of duties
Human CAB or risk review | high blast radius, novel, irreversible changes | frequent routine releases
@h Automated evidence for audits
```yaml title="Deployment gate as policy"
# conceptual pipeline stage, adapt to your CI system
stages:
  - name: gate
    requires:
      - tests_passed
      - image_scanned_no_critical
      - approved_by_second_person
      - change_window_open_or_standard_change
    on_success: deploy_canary_10_percent
    on_failure: block_and_notify
```
@check
How does DevOps keep an audit trail without a CAB? || Git history, pull request approvals and pipeline logs record who changed what and what checks passed.
@end

@concept Incident command: roles and structure
@plain
For a serious incident, a small set of defined roles replaces chaos: one person leads, one communicates, others investigate. The model comes from emergency services (Incident Command System).
@problem
Without roles, ten engineers debug the same thing, nobody updates stakeholders, and decisions are made by the loudest voice.
@does
- **Incident Commander (IC)**: coordinates, decides, delegates; does not debug. **Operations lead**: runs the investigation and changes. **Communications lead**: updates stakeholders and the status page. **Scribe**: keeps the timeline.
- Declare early; severity levels (for example SEV1 to SEV4) define who joins and how often updates go out.
- Hand off explicitly after about 2 hours or when tired.
- Mitigate first: rollback, failover, disable a feature flag, scale up.
@diagram layers
caption: Roles in a SEV1
layers:
  - {label: "Command", nodes: ["Incident commander|decides and delegates|cp"]}
  - {label: "Work streams", nodes: ["Operations lead|investigate and fix|app", "Communications lead|status page, executives|info", "Scribe|timeline and decisions|plain"]}
  - {label: "Support", nodes: ["Subject experts|called in as needed|env"]}
@h Severity table
```yaml title="severity-levels.yaml"
SEV1:
  meaning: major outage or data loss affecting most customers
  response: page everyone needed now, update every 15 minutes
SEV2:
  meaning: significant degradation or one major feature down
  response: on-call plus owning team, update every 30 minutes
SEV3:
  meaning: minor impact, workaround exists
  response: handle in working hours
```
@check
Should the incident commander debug? || No; the IC coordinates so someone keeps the whole picture.
@end

@concept Incident communication
@plain
Good communication is part of the fix. Stakeholders, customers and teammates need regular, honest, plain-language updates, even when the update is "no change".
@problem
Silence breeds duplicate pings, panic and speculation. Technical jargon in customer messages causes confusion.
@does
- Single channel: a dedicated chat room and a video bridge; pin the current summary.
- Update on a fixed cadence that matches severity. Use the template: what we know, impact, what we are doing, next update time.
- External status page: acknowledge, investigate, identify, monitor, resolve. Do not promise a fix time you cannot guarantee.
- After resolution send a summary and schedule the blameless postmortem within about five working days.
@diagram seq
caption: Update cadence
actors: ["IC|coordinates|cp", "Comms lead|writes updates|info", "Customers|status page|ext"]
steps:
  - "0>1: facts and next step | req"
  - "1>2: investigating, next update 15 min | resp"
  - "0>1: mitigated, monitoring | req"
  - "1>2: resolved, summary follows | resp"
@h Update template
```text title="Stakeholder update"
[SEV2] Checkout errors - update 3, 14:35 UTC
What we know: 8 percent of card payments fail since 14:05.
Impact: customers in EU see "payment failed", retry usually works.
Actions: rolled back release 4.12 at 14:28; error rate falling.
Next update: 14:50 UTC or sooner if status changes.
```
```bash title="Post a status update from the CLI" nocheck
curl -sS -X POST "$STATUSPAGE_API/incidents" -H "Authorization: OAuth $TOKEN" \
  -d 'incident[name]=Checkout errors' -d 'incident[status]=investigating' \
  -d 'incident[body]=We are investigating failed card payments. Next update in 15 minutes.'
```
:::warn
Never paste secrets, customer data or unverified root cause claims into public updates.
:::
@check
What should every update contain, even with no news? || The next update time.
@end

@concept On call health and learning from incidents
@plain
Reliable systems depend on rested people. A sustainable on-call rotation, strong handoffs and a blameless review process turn incidents into improvement.
@problem
Burnt-out responders make worse decisions and leave. Blame teaches people to hide mistakes.
@does
- Rotation: at least 6 to 8 people for a primary rotation, follow-the-sun where possible; compensation or time off; shadow shifts for new members.
- Track pages per shift. Aim for a small number of actionable pages (many teams target under 2 per 12 hour shift; adjust to your context). Remove or tune noisy alerts.
- Postmortem: timeline, contributing factors, what went well, what went poorly, action items with owners and dates. Focus on systems and processes.
- Review action item completion monthly; an unfinished action is a future outage.
@diagram flow
caption: Learning loop
numbered: true
nodes:
  - "Incident|resolved|bad"
  - "Postmortem|blameless, within 5 days|app"
  - "Action items|owners and dates|warn"
  - "Follow up|tracked to done|cp"
  - "Fewer repeat incidents|measured|ok"
@h Metrics from pages
```python title="Pages per shift" lab
pages = [3, 0, 1, 5, 2, 0, 1]      # actionable pages in 7 shifts
print("mean per shift:", round(sum(pages) / len(pages), 2))
print("shifts over 2 pages:", sum(1 for p in pages if p > 2))
```
@check
Why is a blameless postmortem more effective? || People share honest detail, which reveals system causes that can be fixed.
@end
