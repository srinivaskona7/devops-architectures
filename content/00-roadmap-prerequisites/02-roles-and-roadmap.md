---
title: Roles and the roadmap
minutes: 15
objectives:
  - Tell DevOps, SRE, cloud and architect roles apart
  - See the order topics are learned in and why
  - Know what "architect level" means in practice
---
Job titles overlap, but the work differs. Knowing the difference helps you decide which topics to emphasise.

@concept The four roles
@plain
A **DevOps engineer** builds the pipeline from code to production. An **SRE** keeps production reliable using engineering and measurable targets. A **cloud engineer** designs and runs the cloud platform itself. An **architect** decides how all of it fits together and defends the trade-offs.
@problem
Learners often study tools in random order and cannot tell which skills their target role needs. Employers then see a list of tools but no depth in any area.
@does
- Gives each role a primary question it answers.
- Shows where the roles share skills, so one path serves all four.
- Makes the architect role concrete: choices, cost, risk and communication, not just more tools.
@diagram cmp
caption: The question each role answers
cards:
  - {h: "DevOps engineer", kind: app, items: ["How do changes reach users quickly and safely?", "Pipelines, automation, environments"]}
  - {h: "Site reliability engineer", kind: ok, items: ["How reliable is it, and how do we know?", "SLOs, alerts, incidents, capacity"]}
  - {h: "Cloud engineer", kind: env, items: ["How is the platform built and secured?", "Networks, identity, compute, cost"]}
  - {h: "Architect", kind: cp, items: ["Which option is right, and why?", "Trade-offs, risk, cost, decisions"]}
@choose Where to focus first
DevOps engineer | you enjoy automation, pipelines and shortening release time | you want to avoid on-call and deployment ownership
SRE | you like measuring, debugging and designing for failure | you want purely feature development
Cloud engineer | you like networks, identity and infrastructure design | you dislike cost and security detail
Architect | you can already build and run systems and want to guide others | you are brand new, because judgement needs experience first
@check
Which role owns the sentence "we will accept 0.1 percent errors"? || The SRE, who turns it into an SLO and an error budget.
@end

@concept The learning order
@plain
Topics build on each other. Linux comes first because containers, Kubernetes nodes and CI runners are all Linux. Containers come before Kubernetes because Kubernetes runs containers. Cloud comes after the tools so you recognise what each cloud service replaces.
@problem
Starting with Kubernetes or a cloud console without the foundations leads to copy-paste work that breaks as soon as something differs from the tutorial.
@does
- Puts foundations (Linux, networking, Git) before tooling.
- Teaches tools (containers, Kubernetes, Terraform, CI/CD) before platforms (AWS, Azure, GCP).
- Finishes with decision-making and one complete application that uses everything.
@diagram flow
caption: The path from foundations to architecture
dir: col
nodes:
  - "Foundations|Linux, networking, Git, SDLC|info"
  - "Packaging and running|Docker, Kubernetes|app"
  - "Infrastructure and delivery|Terraform, CI/CD|env"
  - "Operations|monitoring, alerting, logs, Python|ok"
  - "Platforms|AWS, then Azure and GCP|vm"
  - "Judgement|architecture decisions and the Shop app|cp"
@end

@concept What architect-level means
@plain
An architect is not the person who knows the most commands. They choose between options, explain why, estimate cost and risk, and write the decision down so others can follow it.
@problem
Without recorded reasons, teams repeat debates, new members cannot tell why a system looks the way it does, and nobody notices when the original reasons stop being true.
@does
- Frames every choice as options, criteria and trade-offs.
- Uses a short decision record: context, decision, alternatives, consequences.
- Checks designs against reliability, security, cost, operations and performance.
@diagram flow
caption: A decision record in four parts
numbered: true
nodes:
  - "Context|what forces the decision|info"
  - "Options|at least two real choices|app"
  - "Decision|what we chose and why|ok"
  - "Consequences|what gets harder|warn"
@end
