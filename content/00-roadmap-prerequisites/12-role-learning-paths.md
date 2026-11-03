---
title: Learning paths by role with 30 60 90 day plans
minutes: 35
objectives:
  - Choose the role that fits your interests and see what each one emphasises
  - Follow a 30 60 90 day plan for DevOps, SRE, platform and cloud architect roles
  - Define evidence of progress for every stage
---
The roles overlap, and company titles vary. Use these plans as scaffolding, adjust to your job, and always keep a portfolio of things you built. Each plan assumes about 8 to 10 focused hours a week.

@concept Choosing a role
@plain
The four roles solve different problems. DevOps engineers speed up delivery, SREs protect reliability, platform engineers build internal products, and cloud architects design the overall system.
@problem
Learning everything at once leads to shallow knowledge. Knowing your target role tells you what to go deep on first.
@does
- **DevOps engineer**: pipelines, infrastructure as code, deployment, observability.
- **SRE**: SLOs, incident response, capacity, automation of toil.
- **Platform engineer**: self service tooling, Kubernetes platform, golden paths for developers.
- **Cloud architect**: network, identity, data, cost and resilience design across many teams.
@diagram cmp
caption: Primary focus of each role
cards:
  - {h: "DevOps", kind: app, items: ["CI/CD and IaC", "Release speed and safety"]}
  - {h: "SRE", kind: ok, items: ["SLOs and error budgets", "Incidents and postmortems"]}
  - {h: "Platform", kind: info, items: ["Internal developer platform", "Developer experience"]}
  - {h: "Cloud architect", kind: cp, items: ["Reference architectures", "Trade offs and governance"]}
@h Self assessment
```bash title="Rate yourself 0 to 3 on each skill" nocheck
cat <<'EOF' > ~/skills.csv
skill,score
linux,0
git,0
networking,0
containers,0
kubernetes,0
terraform,0
ci_cd,0
observability,0
security,0
EOF
sort -t, -k2 -n ~/skills.csv | head -4     # your weakest four are the next focus
```
@check
Which role owns the error budget policy most directly? || The SRE role, together with the product owner.
@end

@concept DevOps engineer path
@plain
Aim: take code from commit to production safely and repeatedly, and keep the pipeline and infrastructure as code.
@problem
Manual builds and hand-made servers cause slow, risky, unrepeatable releases.
@does
- **Days 1 to 30**: Linux, Git, networking essentials, Docker. Deliverable: a containerised app with a Dockerfile you can explain.
- **Days 31 to 60**: CI pipeline (build, test, scan, push), Terraform for a VPC and a VM, Kubernetes basics. Deliverable: a pipeline that deploys to a test cluster.
- **Days 61 to 90**: Helm or Kustomize, GitOps with Argo CD or Flux, monitoring with Prometheus and Grafana, secrets handling. Deliverable: a documented end to end repository with rollback.
@diagram flow
caption: DevOps plan milestones
numbered: true
nodes:
  - "Day 30|container image built|ok"
  - "Day 60|CI deploys to cluster|app"
  - "Day 90|GitOps with monitoring|cp"
@h Day 30 checkpoint
```bash title="Prove the basics" lab
git --version && docker --version
docker build -t hello:1 - <<'EOF'
FROM alpine:3.20
CMD ["echo", "hello devops"]
EOF
docker run --rm hello:1
```
@end

@concept SRE path
@plain
Aim: keep services reliable by measuring them, responding to incidents, and removing repeat work through engineering.
@problem
Without objectives, reliability is argued by opinion and every outage becomes a blame hunt.
@does
- **Days 1 to 30**: Linux performance and troubleshooting (USE method), networking, one service run locally. Deliverable: a runbook for a common failure.
- **Days 31 to 60**: define SLIs and SLOs for a service, build Prometheus metrics and alerts, learn Kubernetes failure modes. Deliverable: a dashboard and a burn rate alert.
- **Days 61 to 90**: incident roles, a blameless postmortem, load tests, capacity planning, one toil automation. Deliverable: a game day report.
- Example error budget: a 99.9 percent SLO over 30 days allows 43.2 minutes of failure.
@diagram flow
caption: SRE plan milestones
numbered: true
nodes:
  - "Day 30|runbook for a failure|ok"
  - "Day 60|SLO and burn alerts|app"
  - "Day 90|game day and postmortem|cp"
@h SLO arithmetic
```python title="Error budget in minutes" lab
slo = 0.999
days = 30
budget = (1 - slo) * days * 24 * 60
print(round(budget, 1), "minutes per", days, "days")
bad_minutes = 12
print("budget used:", round(bad_minutes / budget * 100, 1), "percent")
```
@check
How many minutes does a 99.95 percent SLO allow over 30 days? || (1 - 0.9995) x 43200 = 21.6 minutes.
@end

@concept Platform engineer path
@plain
Aim: build a product for developers: a paved road that makes the secure, reliable way the easy way.
@problem
When every team assembles its own cluster, pipeline and monitoring, effort is duplicated and quality varies.
@does
- **Days 1 to 30**: Kubernetes core objects, networking and storage, Helm. Deliverable: a cluster you can rebuild from code.
- **Days 31 to 60**: ingress or Gateway API, policy as code (Kyverno or OPA), cluster add-ons managed with GitOps, multi tenancy with namespaces and quotas. Deliverable: a namespace-per-team template.
- **Days 61 to 90**: a service template and developer portal (Backstage), golden path documentation, platform metrics such as time to first deploy. Deliverable: a new service deployed in under 30 minutes by someone else.
@diagram flow
caption: Platform plan milestones
numbered: true
nodes:
  - "Day 30|rebuildable cluster|ok"
  - "Day 60|team namespace template|app"
  - "Day 90|portal and golden path|cp"
@h Namespace per team
```yaml title="Team namespace with quota"
apiVersion: v1
kind: Namespace
metadata:
  name: team-orders
  labels:
    owner: orders
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: compute
  namespace: team-orders
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    pods: "50"
```
@end

@concept Cloud architect path
@plain
Aim: design systems that meet business needs across availability, security, cost and operability, and explain the trade offs.
@problem
Designs made without constraints are either fragile or wasteful, and are hard to change later.
@does
- **Days 1 to 30**: cloud fundamentals, VPC and IAM design, one provider certification study (for example AWS Solutions Architect Associate). Deliverable: a landing zone sketch.
- **Days 31 to 60**: multi account strategy, data stores, resilience patterns, cost modelling. Deliverable: a three tier design with availability math and a cost estimate.
- **Days 61 to 90**: architecture decision records, C4 diagrams, disaster recovery design with RPO and RTO, a review of a real system. Deliverable: a design document reviewed by peers.
@diagram flow
caption: Architect plan milestones
numbered: true
nodes:
  - "Day 30|landing zone sketch|ok"
  - "Day 60|3 tier design with cost|app"
  - "Day 90|reviewed design document|cp"
@h Cost and availability check
```python title="Design numbers" lab
nodes, hourly, hours = 6, 0.096, 730          # example rate, check current pricing
print("compute per month", round(nodes * hourly * hours, 2))
a_db, a_app = 0.9995, 0.9995
print("series availability", round(a_db * a_app, 6))
```
@check
What two artefacts show an architect's reasoning? || Architecture decision records and diagrams such as C4.
@end

@concept A weekly rhythm that works
@plain
Consistency beats intensity. A fixed weekly shape keeps progress steady and builds evidence.
@problem
Studying without building leaves knowledge that disappears under interview or on-call pressure.
@does
- Two sessions of learning (reading and video), two of hands-on labs, one of review and writing notes, and one hour for a small public artefact (a README, a diagram, a blog post).
- Keep a learning log with commands that surprised you. Review it weekly.
- Rebuild each lab from scratch after a week without notes; that is the test of retention.
@diagram flow
caption: A weekly cycle
nodes:
  - "Learn|2 sessions|plain"
  - "Build|2 labs|app"
  - "Review|notes and flashcards|info"
  - "Ship|one small artefact|ok"
@h Weekly plan template
```yaml title="week-plan.yaml"
week: 3
goal: deploy an app with a Helm chart
sessions:
  - {day: Mon, type: learn, topic: Helm charts and values}
  - {day: Wed, type: build, topic: chart for the shop api}
  - {day: Fri, type: build, topic: upgrade and rollback drill}
  - {day: Sun, type: review, topic: write notes and a README}
evidence: charts/shop pushed with a README
```
@end

@concept Building evidence and a portfolio
@plain
Employers trust things they can see. A portfolio is a small set of repositories that show your work.
@problem
A list of tools on a CV does not distinguish you from many other applicants.
@does
- Three projects are enough: an infrastructure as code repository, a CI/CD pipeline with a deploy, and an operations project with monitoring and a postmortem.
- Each repository has a README with an architecture diagram, how to run it, costs and cleanup, and what you would do next.
- Never include secrets or personal cloud account identifiers.
@diagram layers
caption: A balanced portfolio
layers:
  - {label: "Build", nodes: ["IaC repo|Terraform VPC and cluster|app"]}
  - {label: "Deliver", nodes: ["Pipeline repo|test, scan, deploy, rollback|env"]}
  - {label: "Operate", nodes: ["Observability repo|SLOs, alerts, runbook, postmortem|ok"]}
@h README skeleton
```bash title="Create a project skeleton" lab
mkdir -p ~/portfolio/shop-platform/{docs,infra,app,.github/workflows} && cd ~/portfolio/shop-platform
cat > README.md <<'EOF'
# Shop platform
## Architecture
(diagram here)
## Run it
## Cost and cleanup
## What I would improve
EOF
git init -q && git add -A && git commit -qm "Project skeleton" && git log --oneline
```
@check
Why include a cleanup section? || It shows cost awareness and prevents forgotten resources.
@end

@concept Choosing next steps after day 90
@plain
After 90 days you can choose depth or breadth. Pick one specialty and keep one adjacent skill growing.
@problem
Staying a generalist forever makes senior growth slow; specialising too early limits options.
@does
- Pick a certification only if it matches the role: CKA or CKAD for Kubernetes, a cloud associate certificate, Terraform Associate. Check current exam details on the vendor site.
- Contribute to an open source project, or take an on-call shadow rotation.
- Teach: a talk or a document forces precision.
@diagram flow
caption: Depth and breadth after day 90
nodes:
  - "Day 90 done|portfolio and basics|ok"
  - "Choose a specialty|k8s, cloud, reliability, platform|info"
  - "Add an adjacent skill|security or data|app"
  - "Teach and mentor|compounds learning|cp"
@h Review prompts
```yaml title="day-90-review.yaml"
what_i_can_do_alone: [build an image, write a pipeline, deploy to a cluster]
what_i_cannot_yet: [design multi region, tune a database]
next_specialty: kubernetes platform
next_90_days_goal: pass CKA and run a game day
```
@end
