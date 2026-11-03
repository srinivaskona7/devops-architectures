---
title: FinOps, developer experience, careers and case studies
minutes: 55
objectives:
  - Apply the FinOps cycle of inform, optimise and operate to a Kubernetes bill
  - Measure developer experience with the SPACE framework and avoid vanity metrics
  - Read a DevOps career ladder and plan growth
  - Extract lessons from three realistic case studies
---
Cost, productivity and people are the long-term constraints on every engineering organisation. Figures in the examples are illustrative; check your own provider pricing and data.

@concept The FinOps cycle
@plain
**FinOps** is a culture and practice of making cloud spending a shared engineering concern. Engineers, finance and product work from the same data and make trade offs between speed, quality and cost.
@problem
Cloud billing is variable and arrives after the spend. Finance cannot judge technical need, and engineers rarely see the cost of their choices, so waste grows quietly.
@does
- Three phases that repeat: **Inform** (visibility, allocation, forecasting), **Optimise** (rightsizing, commitments, removing waste), **Operate** (governance, automation, continuous review). See the FinOps Foundation for the current framework wording.
- Cost is a metric like latency: owned by the team that controls it.
- The aim is value per dollar, not the smallest bill.
@diagram flow
caption: The FinOps loop
nodes:
  - "Inform|who spends what and why|info"
  - "Optimise|rightsize, commit, delete waste|app"
  - "Operate|budgets, policy, reviews|cp"
  - "Repeat|every month|ok"
@h First look at spend
```bash title="Cost by service with the AWS CLI" nocheck
aws ce get-cost-and-usage \
  --time-period Start=2026-10-01,End=2026-11-01 \
  --granularity MONTHLY --metrics UnblendedCost \
  --group-by Type=DIMENSION,Key=SERVICE \
  --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]' --output text | sort -k2 -nr | head
```
@check
Which phase includes buying commitments? || Optimise.
@end

@concept Cost allocation: tags, accounts and Kubernetes labels
@plain
Allocation assigns each dollar to a team, product or environment. Without it, the bill is one big number nobody owns.
@problem
"The EKS bill went up 30 percent" cannot be acted on until you know which namespace or team caused it.
@does
- Mandatory tags: `team`, `service`, `environment`, `cost-center`. Activate them as cost allocation tags in billing. Enforce with policy at creation time.
- Separate AWS accounts per environment give hard boundaries.
- In Kubernetes, nodes are shared, so allocate by namespace and labels using requests (and usage) with tools such as OpenCost or Kubecost.
- Shared costs (control plane, NAT, observability) are split by an agreed rule, for example proportional to usage.
@diagram flow
caption: From invoice to owner
nodes:
  - "Cloud bill|accounts and tags|ext"
  - "Allocation tool|OpenCost, cost reports|cp"
  - "Namespace and label|team, service|app"
  - "Team report|monthly, per service|ok"
@h Label and enforce
```yaml title="Deployment with allocation labels"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders-api
  namespace: team-orders
  labels:
    team: orders
    service: orders-api
    cost-center: "cc-4821"
spec:
  replicas: 3
  selector:
    matchLabels: {app: orders-api}
  template:
    metadata:
      labels: {app: orders-api, team: orders, service: orders-api}
    spec:
      containers:
        - name: api
          image: registry.example.com/orders-api:2.3.1
          resources:
            requests: {cpu: 500m, memory: 512Mi}
            limits: {memory: 512Mi}
```
```bash title="Find untagged resources" nocheck
aws resourcegroupstaggingapi get-resources --tag-filters Key=team --query 'ResourceTagMappingList[].ResourceARN' --output text | wc -w
kubectl get ns -L team | awk '$NF=="" || $NF=="<none>"'
```
@check
Why is Kubernetes allocation harder than per-VM allocation? || Pods from many teams share nodes, so cost must be split by requests or usage.
@end

@concept Rightsizing Kubernetes workloads
@plain
**Rightsizing** adjusts CPU and memory requests to what workloads actually need. Over-requesting reserves capacity you pay for but do not use.
@problem
Developers copy generous requests "to be safe". Nodes then show 20 percent real utilisation while the scheduler considers them full.
@does
- Compare requests to usage percentiles over weeks (p95 for CPU, near max for memory). The Vertical Pod Autoscaler in recommendation mode, or Goldilocks, suggests values.
- Memory: set requests close to usage and limit equal to request to avoid OOM surprises. CPU: requests matter for scheduling; limits can cause throttling.
- Bin pack with the cluster autoscaler or Karpenter, which can consolidate under-used nodes. Pod disruption budgets protect availability during consolidation.
- Example: 20 nodes at 22 percent average utilisation, target 60 percent, need ceil(20 x 0.22 / 0.60) = 8 nodes, a 60 percent reduction in nodes.
@diagram cmp
caption: Before and after
cards:
  - {h: "Before", kind: bad, items: ["20 nodes, 22 percent used", "Requests 4x usage"]}
  - {h: "After", kind: ok, items: ["8 nodes, about 55 to 60 percent used", "Requests near p95 usage", "Autoscaling for peaks"]}
@h Compute the saving
```python title="Node count and monthly cost" lab
import math
nodes, util, target = 20, 0.22, 0.60
needed = math.ceil(nodes * util / target)
rate, hours = 0.192, 730             # example hourly price, check current pricing
print("nodes needed:", needed)
print("before $", round(nodes * rate * hours, 2), "after $", round(needed * rate * hours, 2))
print("saving $", round((nodes - needed) * rate * hours, 2), "per month")
```
Expected: 8 nodes, $2803.20 before, $1121.28 after, saving $1681.92 a month. Leave headroom for zone failure and spikes in practice.
```bash title="Requests versus usage" nocheck
kubectl top pods -n team-orders
kubectl get pods -n team-orders -o custom-columns=NAME:.metadata.name,CPUREQ:.spec.containers[*].resources.requests.cpu,MEMREQ:.spec.containers[*].resources.requests.memory
```
@check
Why not rightsize to exactly the average usage? || Peaks, zone failures and growth need headroom; use a high percentile plus margin.
@end

@concept Commitments, spot and unit economics
@plain
After removing waste, reduce the price per unit with commitments and cheaper capacity, and track **unit economics**: cost per order, per active user or per request.
@problem
Total spend rising can be healthy (more customers) or unhealthy (waste). Only a unit metric tells them apart.
@does
- Cover the stable baseline with savings plans or reserved capacity; run fault tolerant work on spot with diversified instance types and graceful termination handling.
- Unit cost = total cost divided by a business measure. If cost rose 20 percent while orders rose 50 percent, cost per order fell by 20 percent (1.20 / 1.50 = 0.80).
- Review commitment coverage and utilisation monthly; unused commitments are waste.
@diagram flow
caption: Layered capacity strategy
nodes:
  - "Baseline|always on|ok"
  - "Savings plan|commitment for baseline|info"
  - "Variable load|on demand and autoscaling|app"
  - "Batch and CI|spot|warn"
@h Unit cost
```python title="Cost per order" lab
cost_before, orders_before = 100_000, 1_000_000
cost_after, orders_after = 120_000, 1_500_000
b = cost_before / orders_before
a = cost_after / orders_after
print(f"before ${b:.3f} per order, after ${a:.3f}, change {100*(a/b-1):.0f} percent")
```
@check
Spend rose 20 percent and orders rose 50 percent. Is efficiency better or worse? || Better: cost per order fell 20 percent.
@end

@concept Measuring developer experience with SPACE
@plain
**Developer experience (DevEx)** is how it feels to build and ship software here: fast feedback, low friction, clear goals. The **SPACE** framework (Forsgren and colleagues, 2021) says productivity has five dimensions and no single metric captures it.
@problem
Counting lines of code, commits or tickets rewards the wrong behaviour and can be gamed. Leaders still need evidence to prioritise platform work.
@does
- **S**atisfaction and well-being: survey results, burnout risk.
- **P**erformance: outcomes such as quality and customer impact.
- **A**ctivity: counts of actions such as deploys or pull requests (use carefully, never alone).
- **C**ommunication and collaboration: review turnaround, onboarding time, quality of documentation.
- **E**fficiency and flow: waiting time, handoffs, interruptions, time in flow.
- Use metrics from at least three dimensions, include at least one perceptual measure from surveys, and track teams, not individuals.
@diagram cmp
caption: The five dimensions with example signals
cards:
  - {h: "Satisfaction", kind: ok, items: ["Quarterly survey", "Would recommend the stack"]}
  - {h: "Performance", kind: app, items: ["Change failure rate", "Customer impact"]}
  - {h: "Activity", kind: info, items: ["Deployment frequency", "Use with care"]}
  - {h: "Communication", kind: cp, items: ["PR review time", "Onboarding to first deploy"]}
  - {h: "Efficiency", kind: warn, items: ["CI wait time", "Context switches"]}
@h Gather a few signals
```python title="Median PR review time from sample data" lab
from statistics import median
review_hours = [2, 5, 1, 30, 4, 3, 26, 2]       # hours from open to first review
print("median", median(review_hours), "h; slowest", max(review_hours), "h")
survey = {"build speed": 3.1, "docs": 2.6, "on-call load": 3.8}    # scale 1 to 5
print("lowest satisfaction:", min(survey, key=survey.get))
```
:::warn
Never use these metrics to rank individuals. Metrics used as targets get gamed (Goodhart's law).
:::
@check
Why combine survey data with system data? || Systems show what happens, surveys show how it feels and why; both are needed.
@end

@concept DevEx drivers and relation to DORA
@plain
Research on developer experience (Noda, Storey, Forsgren, Greiler) groups the main drivers into three: **feedback loops**, **cognitive load** and **flow state**. DORA's four key metrics measure delivery outcomes; SPACE and DevEx explain what helps or hinders the people producing them.
@problem
Improving a delivery metric without understanding friction leads to pressure instead of fixes.
@does
- Feedback loops: how long builds, tests, reviews and deploys take. Shorter loops give faster learning. Example: cutting a 20 minute CI to 8 minutes saves 12 minutes on each of 10 runs a day per developer.
- Cognitive load: how much a developer must hold in mind; reduce with golden paths, good docs and simple abstractions.
- Flow: protected focus time, fewer interruptions, clear goals.
- DORA: deployment frequency, lead time for changes, change failure rate, time to restore. Check the current DORA report for the exact definitions and any added metrics.
@diagram layers
caption: How the frameworks fit
layers:
  - {label: "Outcomes", nodes: ["DORA metrics|delivery speed and stability|ok"]}
  - {label: "Experience", nodes: ["Feedback loops|build, test, review|app", "Cognitive load|complexity to hold|app", "Flow state|focus time|app"]}
  - {label: "Levers", nodes: ["Platform and golden paths|env", "Docs and tooling|env", "Process and meetings|env"]}
@h Value of faster builds
```python title="Time saved per week" lab
devs, runs_per_day, old_min, new_min = 40, 10, 20, 8
saved_hours_week = devs * runs_per_day * (old_min - new_min) * 5 / 60
print(round(saved_hours_week), "developer hours per week")   # 400
```
@check
Which driver does a golden path mainly reduce? || Cognitive load.
@end

@concept Career ladders for DevOps and platform engineers
@plain
A **career ladder** describes what is expected at each level: scope, autonomy and impact. Titles differ by company, but the pattern is similar.
@problem
Without a ladder people guess what promotion requires, and managers apply it inconsistently.
@does
- **Junior or associate**: completes well-defined tasks with guidance, learns the stack, follows runbooks, asks good questions.
- **Engineer**: owns a component end to end, handles on-call, improves reliability and automation, reviews others' work.
- **Senior**: owns a system or cross-team area, designs solutions with trade offs, mentors, leads incidents, reduces toil at scale.
- **Staff and principal**: shapes technical direction across teams, sets standards, resolves ambiguous organisation-wide problems, multiplies others.
- **Manager track** branches from senior: people, hiring, delivery. Both tracks are valued.
- Impact grows from tasks, to projects, to systems, to organisation.
@diagram flow
caption: Growth of scope
numbered: true
nodes:
  - "Junior|tasks with guidance|plain"
  - "Engineer|owns a component|app"
  - "Senior|owns a system, mentors|info"
  - "Staff and principal|org wide direction|cp"
@h Self assessment
```yaml title="growth-plan.yaml"
current_level: engineer
target_level: senior
gaps:
  - {area: design, evidence_needed: led one cross-team design with an ADR}
  - {area: operations, evidence_needed: reduced pages for my service by 50 percent}
  - {area: mentoring, evidence_needed: onboarded two engineers}
next_quarter:
  - run the postmortem for the last SEV2 and finish its action items
  - present the Terraform module design in the guild
```
@check
What changes most between engineer and senior? || Scope: from a component to a system and other people's growth.
@end

@concept Case studies and lessons
@plain
Real incidents and migrations teach more than theory. These three composite scenarios are modelled on common public postmortems and are not about any specific company.
@problem
Teams repeat each other's mistakes because the lessons stay inside the organisations that paid for them.
@does
- **Case 1, the expired certificate**: a wildcard certificate for internal APIs expired on a Saturday. Renewal was manual and owned by someone who left. Lessons: inventory, automation, alert at 21 days, ownership in the catalog.
- **Case 2, the config push**: a global configuration change was deployed to every region at once and made all instances reject requests. Lessons: progressive rollout with canaries, config validated like code, fast rollback, and out-of-band access to fix the system that deploys.
- **Case 3, the cost spike**: a debug log level left on and a cross-zone chatty service raised the monthly bill by 40 percent before anyone noticed. Lessons: budget alerts, unit cost dashboards, allocation labels, cost in the postmortem template.
- Common thread: small, frequent, observable changes with automatic rollback beat heroics.
@diagram cmp
caption: Three cases, three controls
cards:
  - {h: "Expired certificate", kind: warn, items: ["Control: automation and inventory", "Alert 21 days ahead"]}
  - {h: "Global config push", kind: bad, items: ["Control: staged rollout", "Validation and quick rollback"]}
  - {h: "Cost spike", kind: info, items: ["Control: budgets and unit cost", "Labels and review"]}
@h Turn lessons into checks
```yaml title="lessons-to-actions.yaml"
- case: expired certificate
  action: cert-manager everywhere, alert on days left, owner in catalog-info.yaml
  owner: platform
  due: 2026-12-01
- case: global config push
  action: deploy config in waves (1 percent, 10 percent, 100 percent) with auto rollback on error rate
  owner: release engineering
  due: 2027-01-15
- case: cost spike
  action: weekly budget alert per team, cost per order on the service dashboard
  owner: finops
  due: 2026-12-15
```
:::tip
When reading any public postmortem, ask three questions: what changed, why was detection slow, and what made recovery hard? The answers are usually the same few themes.
:::
@check
What was common to all three cases? || The failure was predictable and preventable with automation, staged change and observability.
@end
