---
title: Tool selection matrix
minutes: 55
objectives:
  - Build and use a weighted decision matrix for tool selection
  - Compare common DevOps tool categories with clear criteria
  - Run a proof of concept and record the decision
---
There are many tools for every job. A repeatable method beats a favourite. This page gives the method and defaults for common categories.

@concept The weighted decision matrix
@plain
List criteria, weight them, score each option, multiply and add. The result guides discussion.
@problem
Tool choices become arguments about taste without shared criteria.
@does
- Pick 5 to 8 criteria that matter: fit, operational effort, cost, skills, security, integration, exit.
- Weights add to 100. Scores 1 to 5.
- Check sensitivity: change the top weights and see if the winner changes.
- Include a must-have list that disqualifies options regardless of score.
@diagram flow
caption: Using the matrix
numbered: true
nodes:
  - "Must-haves|filter options|warn"
  - "Criteria and weights|agree first|info"
  - "Score|evidence, not opinion|app"
  - "Sensitivity|does winner change|ok"
@h Worked scoring
Weights: fit 30, effort 25, cost 20, skills 15, exit 10 = 100.

| Criterion | Weight | Tool A | Tool B |
|---|---|---|---|
| Fit | 30 | 4 (120) | 5 (150) |
| Effort | 25 | 5 (125) | 2 (50) |
| Cost | 20 | 3 (60) | 4 (80) |
| Skills | 15 | 4 (60) | 2 (30) |
| Exit | 10 | 3 (30) | 5 (50) |
| Total | 100 | 395 | 360 |

If the effort weight falls from 25 to 10 and fit rises from 30 to 45: Tool A = 4x45 + 5x10 + 60 + 60 + 30 = 380, Tool B = 5x45 + 2x10 + 80 + 30 + 50 = 405. The winner flips, so the weights deserve a real conversation.
```python title="matrix.py"
w1 = [30, 25, 20, 15, 10]
a = [4, 5, 3, 4, 3]
b = [5, 2, 4, 2, 5]
print(sum(x * y for x, y in zip(w1, a)), sum(x * y for x, y in zip(w1, b)))
w2 = [45, 10, 20, 15, 10]
print(sum(x * y for x, y in zip(w2, a)), sum(x * y for x, y in zip(w2, b)))
```
@check
Why test sensitivity? || The winner may flip when weights change, showing the choice depends on priorities.
@end

@concept Infrastructure as code
@plain
Tools that describe infrastructure in files and create it from them.
@problem
Console clicking is not repeatable, reviewable or recoverable.
@does
- Terraform or OpenTofu: all clouds and many services, large provider ecosystem, state to manage. Check the current licence position of each before adopting.
- Pulumi: real programming languages, same provider reach.
- Native: CloudFormation or CDK, Bicep, Infrastructure Manager. Day-one feature support, single cloud.
- Crossplane: manage cloud resources through Kubernetes APIs.
- Default: Terraform or OpenTofu for multi-cloud, native when single cloud and the team prefers it.
@diagram cmp
caption: IaC families
cards:
  - {h: "Declarative multi-cloud", kind: ok, items: ["Terraform, OpenTofu", "Large ecosystem", "State management"]}
  - {h: "Code-first", kind: info, items: ["Pulumi, CDK", "Loops and types", "Review generated plans"]}
  - {h: "Native", kind: app, items: ["CloudFormation, Bicep", "Fast feature support", "One cloud only"]}
@choose IaC
Terraform or OpenTofu | several clouds, big module ecosystem | you want no state file
Pulumi or CDK | developers prefer general languages | you need simple, reviewable plain files
Native cloud tool | single cloud, day-one features | you may add a second cloud
Crossplane | platform team builds self-service on Kubernetes | there is no Kubernetes platform
@check
When prefer a native IaC tool? || One cloud only and the newest features are needed immediately.
@end

@concept CI/CD and delivery
@plain
Systems that build, test and deploy changes automatically.
@problem
Manual releases are slow, error-prone and hard to audit.
@does
- GitHub Actions or GitLab CI: close to the code, large marketplace, hosted or self-hosted runners.
- Jenkins: flexible and self-run, plugin upkeep is the cost.
- Cloud-native: CodePipeline, Azure Pipelines, Cloud Build. Tight identity integration.
- GitOps (Argo CD, Flux): the cluster pulls desired state from Git. Strong audit and drift correction for Kubernetes.
- Default: one CI tool for build and test, GitOps for cluster delivery.
@diagram flow
caption: A typical split
nodes:
  - "Code|Git repository|plain"
  - "CI|build and test|app"
  - "Registry|signed images|info"
  - "GitOps|cluster pulls|cp"
  - "Cluster|running state|ok"
@choose CI tool
GitHub Actions or GitLab CI | code already hosted there | you need heavy custom orchestration
Jenkins | complex legacy pipelines | nobody can maintain plugins
Cloud-native CI | single cloud, tight IAM integration | multi-cloud portability matters
@check
What does GitOps add? || The cluster pulls desired state from Git, giving audit trail and drift correction.
@end

@concept Observability stack
@plain
Tools for metrics, logs and traces.
@problem
You cannot fix what you cannot see, and costs balloon without design.
@does
- Metrics: Prometheus with Grafana, or managed Prometheus; cloud-native monitoring for cloud services.
- Logs: ELK or OpenSearch for rich search, Loki for cost-efficient logs near metrics, cloud logging for platform logs.
- Traces: OpenTelemetry instrumentation with Jaeger, Tempo or a vendor.
- SaaS platforms trade cost for speed. Always instrument with OpenTelemetry to keep the exit open.
@diagram layers
caption: Signals and sinks
layers:
  - {label: "Instrumentation", nodes: ["OpenTelemetry|portable|ok"]}
  - {label: "Collection", nodes: ["Collector or agent|route and filter|info"]}
  - {label: "Storage and view", nodes: ["Prometheus and Grafana|metrics|app", "Loki or ELK|logs|app", "Tempo or Jaeger|traces|app"]}
@choose Logs
Loki | debugging next to metrics, low cost | you need rich analytics on all fields
ELK or OpenSearch | complex search, security analytics | nobody can run stateful clusters
Cloud logging | platform logs, small volume | volume and retention are high
@check
Why instrument with OpenTelemetry? || It keeps the backend replaceable.
@end

@concept Secrets, policy and security tooling
@plain
Tools that hold secrets, enforce rules and scan for risk.
@problem
Secrets in repositories and unchecked configuration cause breaches.
@does
- Secrets: cloud secret managers for cloud workloads; Vault when you need dynamic secrets, multi-cloud or on-premises; External Secrets Operator or CSI driver to deliver into pods.
- Policy: Open Policy Agent or Kyverno for Kubernetes admission, Conftest for pipelines, cloud policy services for accounts.
- Scanning: dependency and container scanners (Trivy and similar), static analysis, infrastructure scanners. Run in CI and on a schedule.
- Supply chain: sign images (Sigstore Cosign) and keep SBOMs.
@diagram flow
caption: Shift-left checks
nodes:
  - "Commit|secret scan|plain"
  - "Build|dependency and image scan|info"
  - "Plan|policy check|warn"
  - "Deploy|admission policy|cp"
  - "Run|runtime detection|ok"
@choose Secrets store
Cloud secret manager | one cloud, simple needs | you need dynamic database credentials across clouds
Vault | multi-cloud, dynamic secrets | no one can operate it
External Secrets Operator | Kubernetes with a cloud secret store | you have no cluster
@check
What is shift-left? || Moving security checks earlier, to commit and build time.
@end

@concept Kubernetes ecosystem choices
@plain
Add-ons surround any cluster: ingress, service mesh, autoscaling, storage.
@problem
The ecosystem is large and each add-on has an upkeep cost.
@does
- Ingress or Gateway API controllers: cloud load balancer controllers or NGINX, Envoy-based gateways.
- Service mesh: only when you need mTLS everywhere, traffic shifting or rich telemetry; start without.
- Autoscaling: HPA, KEDA for events, Karpenter or cluster autoscaler for nodes.
- Packaging: Helm for third-party, Kustomize for overlays.
- Fewer add-ons means fewer upgrades to carry.
@diagram layers
caption: Add-on layers
layers:
  - {label: "Delivery", nodes: ["Helm or Kustomize|packaging|info", "Argo CD or Flux|GitOps|cp"]}
  - {label: "Traffic", nodes: ["Gateway API controller|ingress|app", "Mesh|optional|warn"]}
  - {label: "Scale", nodes: ["HPA and KEDA|pods|ok", "Node autoscaler|nodes|ok"]}
@choose Service mesh
No mesh | few services, TLS at ingress is enough | compliance demands mTLS between all services
Mesh | many services, mTLS and traffic shifting required | team has no capacity to run it
@check
When add a service mesh? || When you need mTLS everywhere, traffic shifting or rich telemetry, not by default.
@end

@concept Proof of concept and the final record
@plain
Test the two finalists on a real slice of work before committing.
@problem
Slides and demos hide integration and operations pain.
@does
- Define success criteria and a time box of one to three weeks.
- Use real data volumes and one real team.
- Measure: setup time, performance, cost estimate, failure behaviour, day-two tasks like upgrades.
- Record in an ADR with a review date and an exit note.
@diagram flow
caption: PoC to decision
numbered: true
nodes:
  - "Criteria|success measures|plain"
  - "Build|time boxed|app"
  - "Measure|cost, speed, effort|info"
  - "Decide|ADR|ok"
@h PoC plan
```yaml title="poc-plan.yaml" nocheck
question: Which log backend for 200 GB per day?
finalists: [loki, opensearch]
time_box_days: 10
success:
  - query p95 under 5 s over 24 h
  - monthly cost estimate under 3000 USD
  - upgrade rehearsed in staging
```
@check
Why time box a PoC? || Without a limit it drifts into an unplanned project.
@end
