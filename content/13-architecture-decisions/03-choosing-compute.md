---
title: Choosing compute - VMs, containers, serverless
minutes: 55
objectives:
  - Place a workload on the control versus convenience ladder
  - Compare VMs, Kubernetes, serverless containers and functions on cost and effort
  - Estimate break-even points with simple arithmetic
---
Compute is a ladder. Each rung removes some operations work and some control. Pick the highest rung that meets the requirements.

@concept The control versus convenience ladder
@plain
From bottom to top: physical or dedicated hosts, virtual machines, container orchestrators, serverless containers, functions. Higher rungs hide more of the machine from you.
@problem
Teams often pick the rung they know, not the one the workload needs, and either carry needless operations work or hit a platform limit.
@does
- Lower rungs: you patch the operating system, scale, and secure the host.
- Higher rungs: the provider handles hosts, but imposes limits on run time, memory, networking and start-up.
- Moving up usually shrinks cost for spiky load and grows it for steady heavy load.
@diagram layers
caption: The compute ladder
layers:
  - {label: "Less operations, more limits", nodes: ["Functions|event code|ok", "Serverless containers|image, no servers|ok"]}
  - {label: "Middle", nodes: ["Managed Kubernetes|cluster you configure|info"]}
  - {label: "More operations, more control", nodes: ["Virtual machines|you run the OS|warn", "Dedicated hosts|licensing, isolation|bad"]}
@check
What do you gain by moving up the ladder? || Less operations work, at the price of platform limits.
@end

@concept Virtual machines
@plain
A VM is a full computer in software. You choose the operating system and install anything.
@problem
Some software needs a specific kernel, licence model, GPU driver or long-lived state that higher rungs cannot offer.
@does
- Best for lift-and-shift, licensed software, agents needing root, and stateful single nodes.
- Scale with autoscaled groups, patch with images, and spread across zones.
- Cost lever: commitment discounts for steady use, spot or preemptible for tolerant work.
- Treat VMs as cattle: build from an image, never hand-edit.
@diagram flow
caption: Immutable VM rollout
nodes:
  - "Image build|patched base|app"
  - "Template|new version|info"
  - "Rolling replace|few at a time|warn"
  - "Healthy group|old removed|ok"
@choose VMs or not
Virtual machines | legacy or licensed software, special drivers | the app is already a stateless container
Autoscaled VM group | steady web tier built from an image | traffic is rare and spiky
Single VM | tools like a bastion or build agent | you need high availability and cannot tolerate reboot
@check
Why build VMs from images instead of editing them? || Rebuilds are repeatable and drift cannot accumulate.
@end

@concept Kubernetes
@plain
Kubernetes schedules containers across a pool of machines and keeps the desired number running.
@problem
Dozens of services need shared scheduling, service discovery, rolling updates and a common API.
@does
- Strong for many services, platform teams, custom controllers and portability across clouds.
- Costs: the cluster itself, node pools, upgrades every few months, and skills.
- Do not choose it for one or two simple services; the platform effort will exceed the workload.
- Managed offerings (EKS, AKS, GKE) run the control plane. You still own nodes, add-ons and workloads unless you pick an auto-managed mode.
@diagram flow
caption: What you operate on managed Kubernetes
nodes:
  - "Control plane|provider runs it|ok"
  - "Node pools|you size and upgrade|warn"
  - "Add-ons|ingress, CNI, CSI, DNS|info"
  - "Workloads|your deployments|app"
@check
When is Kubernetes the wrong choice? || When there are only one or two simple services and no platform team.
@end

@concept Serverless containers and functions
@plain
You supply an image or code. The platform runs it on demand, scales it, and bills for use.
@problem
Small teams with spiky traffic cannot justify idle servers or a cluster.
@does
- Serverless containers (Cloud Run, Container Apps, App Runner, Fargate): any language, stateless, HTTP or jobs.
- Functions (Lambda, Azure Functions, Cloud Functions): event-sized code, tiny units, strict limits.
- Watch cold starts, maximum duration, concurrency and downstream database connections.
- Check each product's current limits in its documentation.
@diagram cmp
caption: Containers versus functions
cards:
  - {h: "Serverless container", kind: info, items: ["Bring any image", "Longer requests", "Simple portability"]}
  - {h: "Function", kind: app, items: ["Tiny event handlers", "Deep event integrations", "Strict runtime limits"]}
@h A function handler
```python title="handler.py"
import json


def handler(event, context):
    name = (event.get("queryStringParameters") or {}).get("name", "world")
    return {"statusCode": 200, "body": json.dumps({"hello": name})}
```
@check
Which limit must you check before choosing functions? || Maximum run time and memory or payload size.
@end

@concept Cost break-even arithmetic
@plain
Serverless charges per use, VMs per hour. There is a utilisation level where they cost the same.
@problem
Choosing serverless for a steady heavy load, or a VM for a nearly idle one, wastes money.
@does
- Compute the monthly VM cost, then the per-request cost, and find the request volume where they meet.
- All numbers below are illustrative, check current prices.
- Include operations time, which is real money.
@diagram flow
caption: Finding the break-even
numbered: true
nodes:
  - "VM monthly|price x hours|info"
  - "Per request cost|duration x memory|info"
  - "Break-even|VM / per request|warn"
  - "Compare to load|choose side|ok"
@h Worked example
Assume a VM at 0.10 per hour, 730 hours per month: 0.10 x 730 = 73.00. Assume a function request costs 0.0000009 including duration (an invented figure for the example). Break-even requests per month = 73.00 / 0.0000009 = 81,111,111, about 81 million, roughly 31 requests per second on average (81,111,111 / 2,592,000 seconds in 30 days). Below that average the function is cheaper before operations time; above it the VM wins. A real comparison must add the VM's headroom for peaks and the function's other charges.
```python title="breakeven.py"
vm = 0.10 * 730
per_req = 0.0000009
n = vm / per_req
print(round(vm, 2), round(n), round(n / (30 * 24 * 3600), 1))
```
@check
What else belongs in the comparison besides price per hour? || Operations time, headroom for peaks and other service charges.
@end

@concept Operational fit and team skills
@plain
The best technical choice fails if the team cannot run it at 3 a.m.
@problem
Choices made on features alone ignore who carries the pager.
@does
- Count who can debug the platform. One Kubernetes expert is a risk.
- Count the upgrade burden: Kubernetes minor versions arrive several times a year, VM images need regular rebuilds, functions need runtime updates.
- Prefer one or two compute models per organisation to keep tooling and training manageable.
@diagram cmp
caption: Questions per model
cards:
  - {h: "VMs", kind: warn, items: ["Who patches the OS?", "Who rebuilds images?"]}
  - {h: "Kubernetes", kind: info, items: ["Who upgrades the cluster?", "Who owns add-ons?"]}
  - {h: "Serverless", kind: ok, items: ["Who tracks runtime deprecations?", "Who watches cold starts?"]}
@check
Why limit the number of compute models? || Fewer models mean simpler tooling, training and on-call.
@end

@concept A decision tree
@plain
A short sequence of questions that lands on a sensible default.
@problem
Open-ended debates stall. A tree gives a starting point to argue from.
@does
- Needs special OS, licence or GPU driver control: VMs.
- Many services and a platform team: Kubernetes.
- Stateless HTTP or jobs, small team: serverless containers.
- Event glue and small handlers: functions.
- Always challenge the default with the workload's limits.
@diagram flow
caption: Default decision path
nodes:
  - "Special OS or licence?|yes means VM|warn"
  - "Many services and platform team?|yes means Kubernetes|info"
  - "Stateless HTTP or jobs?|yes means serverless container|ok"
  - "Small event handler?|yes means function|app"
@choose Defaults
Functions | event glue, rare triggers | steady heavy compute
Serverless containers | stateless APIs, small team | you need daemonsets or custom networking
Managed Kubernetes | many services, shared platform | two services, no platform skills
VMs | special requirements, lift-and-shift | you want zero patching
@check
What is the default for a small team with a stateless API? || A serverless container service.
@end
