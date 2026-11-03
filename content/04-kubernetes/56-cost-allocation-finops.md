---
title: Cost allocation and FinOps on Kubernetes
minutes: 40
objectives:
  - Explain why Kubernetes cost is hard to attribute and how requests drive it
  - Measure cost per namespace and team with OpenCost or Kubecost
  - Reduce waste with right-sizing, autoscaling, spot and scheduling
---
A node bill does not say which team spent what. Cost allocation maps cloud spend onto namespaces, labels and workloads so teams can see and own their costs.
@concept Why cost is hard to attribute
@plain
You pay for nodes, disks, load balancers and network traffic. Pods share those. Allocation rules decide how a node's price is split among the Pods that ran on it.
@problem
Finance sees a single EC2 and EBS bill, teams see none, and idle capacity is nobody's fault. Without visibility nobody reduces waste.
@does
- A common model: a Pod's cost is the greater of its CPU/memory **request** and its actual usage, priced by the node's hourly rate. Idle node capacity is shown separately.
- Shared costs (control plane fee, monitoring, ingress, system namespaces) are split by a rule: evenly or proportional to usage.
- Costs outside nodes: persistent volumes, load balancers, NAT gateway and cross-AZ traffic, managed services.
- Requests are the lever: oversized requests reserve capacity you pay for even if unused.
@diagram flow
caption: From bill to team
nodes:
  - "Cloud bill|nodes, disks, network|ext"
  - "Pod resource share|requests and usage|info"
  - "Allocation|by namespace, label, team|app"
  - "Showback or chargeback|per team report|ok"
@h Quick estimate by hand
```bash title="Where requests are high" lab
kubectl get pods -A -o custom-columns=NS:.metadata.namespace,CPU:.spec.containers[*].resources.requests.cpu,MEM:.spec.containers[*].resources.requests.memory | head -20
kubectl top pods -A --sort-by=cpu | head -10
kubectl describe nodes | grep -A8 'Allocated resources' | head -30
```
@end

@concept Labels and tagging for cost
@plain
Consistent labels on namespaces and workloads (and tags on cloud resources) are what let tools attribute cost to a team.
@problem
Without ownership labels, 30 percent of spend ends up in "unallocated" and nobody acts on it.
@does
- Standardise a small set: `team`, `cost-center`, `app`, `env`. Enforce with admission policy (Kyverno or ValidatingAdmissionPolicy) so objects without them are rejected.
- Label **namespaces** (inherit at tenant level) and **workloads** (for shared namespaces).
- On EKS, activate cost allocation tags in AWS Billing, and use split cost allocation data to see Pod-level cost in the Cost and Usage Report.
- Apply the same tags to volumes and load balancers through StorageClass parameters or controller annotations.
@diagram layers
caption: Where ownership metadata lives
layers:
  - {label: "Kubernetes", nodes: ["Namespace labels|team, cost-center|info", "Pod labels|app, env|info"]}
  - {label: "Cloud", nodes: ["Resource tags|nodes, volumes, LBs|ext", "Cost report|grouped by tag|ok"]}
@h Enforce labels
```yaml title="require-labels.yaml"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: require-team-label
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments"]
  validations:
    - expression: "has(object.metadata.labels) && 'team' in object.metadata.labels"
      message: "Deployments must have a team label"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: require-team-label
spec:
  policyName: require-team-label
  validationActions: ["Deny"]
```
@end

@concept OpenCost and Kubecost
@plain
**OpenCost** is the open source CNCF project that calculates Kubernetes cost from Prometheus metrics and cloud price lists. **Kubecost** is a commercial product built on the same engine, adding history, alerts and multi-cluster views.
@problem
You need numbers per namespace, label and workload without building a data pipeline of your own.
@does
- Installs in a cluster, reads node, Pod and PV metrics from Prometheus, and prices them with provider APIs or custom prices (useful on-prem).
- API and UI show allocation by namespace, controller, label, Pod, with idle and shared cost separated.
- The allocation API: `/allocation/compute?window=7d&aggregate=namespace`.
- Check the current Helm chart and licence terms of each project before choosing; capabilities of the free tier change over time.
@diagram flow
caption: OpenCost data flow
nodes:
  - "Prometheus|usage metrics|db"
  - "OpenCost|joins with prices|app"
  - "Price data|cloud API or custom|ext"
  - "Reports|namespace, team, label|ok"
@h Install and query
```bash title="OpenCost" lab
helm repo add opencost https://opencost.github.io/opencost-helm-chart
helm upgrade --install opencost opencost/opencost -n opencost --create-namespace
kubectl port-forward -n opencost svc/opencost 9003:9003 &
curl -s "http://localhost:9003/allocation/compute?window=7d&aggregate=namespace" | python3 -m json.tool | head -40
```
@end

@concept Showback and chargeback
@plain
**Showback** reports cost to teams for awareness. **Chargeback** actually bills their budget. Start with showback.
@problem
Teams do not change behaviour until they see their own numbers regularly and in terms they understand.
@does
- Publish a monthly and weekly report per team: total, trend, efficiency (usage versus request), and top workloads.
- Define an **efficiency** metric: used divided by requested. A team at 20 percent is paying for four times what it uses.
- Treat shared costs transparently; explain the rule once.
- Set budgets and alerts (AWS Budgets by tag, Kubecost alerts) rather than surprise end-of-month reviews.
@diagram cmp
caption: Two stages of maturity
cards:
  - {h: "Showback", kind: info, items: ["Visibility only", "Weekly team reports", "Builds trust in the numbers"]}
  - {h: "Chargeback", kind: warn, items: ["Costs hit team budgets", "Needs accurate allocation", "Disputes on shared cost"]}
@h Efficiency from Prometheus
```promql title="CPU request efficiency per namespace" nocheck
sum by (namespace) (rate(container_cpu_usage_seconds_total{container!=""}[7d]))
  /
sum by (namespace) (kube_pod_container_resource_requests{resource="cpu"})
```
@end

@concept Reducing cost safely
@plain
After you can see cost, reduce it in order of safety: remove waste, right-size, then change purchasing and scheduling.
@problem
Cutting blindly causes outages. Waste removal first gives the largest savings with least risk.
@does
- **Remove**: unused namespaces, orphaned PVCs and load balancers, idle dev clusters (hibernate Gardener shoots, scale node groups to zero at night).
- **Right-size**: use VPA recommendations, `kubectl top`, and efficiency reports to lower requests; keep memory limit equal to request.
- **Autoscale**: HPA/KEDA for Pods and Karpenter or Cluster Autoscaler for nodes with consolidation of underused nodes.
- **Purchase**: spot instances for fault tolerant workloads with PDBs and graceful shutdown; Savings Plans for the stable baseline.
- **Bin-pack**: fewer larger nodes pack better but reduce failure isolation; balance with topology spread.
@diagram flow
caption: Order of savings work
numbered: true
nodes:
  - "Remove waste|orphans, idle env|ok"
  - "Right-size requests|VPA, reports|info"
  - "Autoscale Pods and nodes|follow demand|app"
  - "Buy smarter|spot, savings plans|warn"
@h Orphans and idle objects
```bash title="Find waste" lab
kubectl get pvc -A --no-headers | awk '{print $1, $2, $3}' | head
kubectl get pv -o custom-columns=NAME:.metadata.name,STATUS:.status.phase,CLAIM:.spec.claimRef.name | grep Released
kubectl get svc -A --field-selector spec.type=LoadBalancer
kubectl get deploy -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,REPL:.spec.replicas | awk '$3==0'
```
@check
Why can a Pod with low CPU usage still cost a lot? || Cost is based on reserved requests, so an oversized request holds node capacity whether or not the Pod uses it.
@end
