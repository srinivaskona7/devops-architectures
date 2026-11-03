---
title: Node autoscaling with Cluster Autoscaler and Karpenter
minutes: 40
objectives:
  - Explain how node autoscalers react to Pending Pods and idle nodes
  - Compare Cluster Autoscaler and Karpenter
  - Configure a Karpenter NodePool and protect nodes from disruption
---
Pod autoscalers create Pods; something must create machines for them. Node autoscalers watch for Pods that cannot be placed and for nodes that are underused.
 
@concept What node autoscalers do
@plain
A node autoscaler adds nodes when Pods are Pending for lack of capacity and removes nodes that are empty or can be consolidated.
@problem
Fixed-size clusters are either too small at peak or too expensive off peak.
@does
- Trigger: a Pod with `Unschedulable` condition that would fit on a new node.
- Scale down: nodes below utilisation threshold (or emptied by consolidation) are drained and removed, respecting PDBs and annotations.
- Pods that block removal: no controller owner, local storage, restrictive PDBs, `safe-to-evict: false` or `karpenter.sh/do-not-disrupt`.
- On Gardener and Kyma the worker pool `minimum` and `maximum` and the Gardener-managed cluster autoscaler do this for you.
@diagram flow
caption: Scale up path
numbered: true
nodes:
  - "Pod Pending|Unschedulable|warn"
  - "Autoscaler simulates|would a new node fit|cp"
  - "Create node|cloud API|ext"
  - "Pod scheduled|node Ready|ok"
@h Is the autoscaler acting
```bash title="Autoscaler signals" lab
kubectl -n kube-system logs deploy/cluster-autoscaler --tail=30 | grep -E 'Scale-up|Scale-down|NotTriggerScaleUp'
kubectl get pods -A --field-selector=status.phase=Pending
kubectl get nodes -L topology.kubernetes.io/zone -L karpenter.sh/nodepool
```
@end

@concept Cluster Autoscaler
@plain
Cluster Autoscaler (CA) scales pre-defined node groups (AWS Auto Scaling Groups, Gardener worker pools, managed node groups) up and down.
@problem
You want elasticity but keep strict control over instance types through the groups you define.
@does
- Works per node group: it picks a group whose template node would fit the pending Pod, and raises its desired size.
- Scale-down after nodes are underused (utilisation below 50% of requests by default) for 10 minutes.
- Expanders (`random`, `least-waste`, `priority`) choose between groups.
- Each group is a single instance shape, so many shapes need many groups. This is the main weakness.
- Zone-bound volumes require one node group per zone so the CA can add a node in the right zone.
@diagram layers
caption: CA scales groups
layers:
  - {label: "Cluster Autoscaler", nodes: ["decides desired size|per node group|cp"]}
  - {label: "Node groups", nodes: ["ASG general|m6i.large|app", "ASG memory|r6i.xlarge|app", "ASG spot|mixed|warn"]}
@h Annotations that guide CA
```yaml title="ca-annotations.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: long-job
  annotations:
    cluster-autoscaler.kubernetes.io/safe-to-evict: "false"
spec:
  containers:
    - name: job
      image: busybox:1.36
      command: ["sleep", "3600"]
```
@end

@concept Karpenter
@plain
Karpenter creates nodes directly from the pending Pods' needs, choosing instance types and sizes on the fly, without pre-defined node groups.
@problem
Node groups limit instance variety and scale slowly through the ASG API, leaving capacity wasted.
@does
- Watches unschedulable Pods, batches them, and picks the cheapest instance types that satisfy requests, affinities, topology spread and taints.
- A `NodePool` sets constraints (architecture, capacity type spot or on-demand, instance families, limits, taints); an `EC2NodeClass` sets AWS specifics (AMI family, subnets, security groups, IAM role).
- **Consolidation** replaces or removes nodes to reduce cost (`WhenEmptyOrUnderutilized`), respecting PDBs and budgets.
- Disruption budgets and `expireAfter` control node rotation, which also keeps AMIs fresh.
- AWS-native (EKS) with a provider for Azure; not used by Gardener, which has its own autoscaler.
@diagram flow
caption: Provisioning with Karpenter
nodes:
  - "Pending Pods|batched|warn"
  - "NodePool rules|constraints|cp"
  - "Pick instance|cheapest fit|info"
  - "EC2 Fleet API|node joins|ext"
@h NodePool and EC2NodeClass
```yaml title="karpenter.yaml"
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: general
spec:
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
        - {key: karpenter.sh/capacity-type, operator: In, values: [spot, on-demand]}
        - {key: kubernetes.io/arch, operator: In, values: [amd64, arm64]}
        - {key: karpenter.k8s.aws/instance-category, operator: In, values: [c, m, r]}
      expireAfter: 720h
  limits:
    cpu: "500"
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
    budgets:
      - nodes: "10%"
---
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  amiFamily: AL2023
  amiSelectorTerms:
    - alias: al2023@latest
  role: KarpenterNodeRole-prod
  subnetSelectorTerms:
    - tags: {karpenter.sh/discovery: prod}
  securityGroupSelectorTerms:
    - tags: {karpenter.sh/discovery: prod}
```
:::note
`al2023@latest` follows new AMIs automatically. Pin an AMI alias version in production and promote it through environments.
:::
@check
How does Karpenter differ from CA? || It selects instance types from Pod requirements and creates nodes directly, rather than resizing fixed node groups.
@end

@concept Consolidation and disruption safety
@plain
Cost optimisation means moving Pods. Make that safe with PDBs, budgets and do-not-disrupt markers.
@problem
Aggressive consolidation during business hours can restart critical workloads.
@does
- Each voluntary node removal drains with the Eviction API, so PDBs apply.
- Budgets can restrict disruptions by count and by schedule (for example none during weekdays 9 to 17).
- `karpenter.sh/do-not-disrupt: "true"` on a Pod or node blocks voluntary removal.
- Spot interruptions give a 2 minute warning; handle SIGTERM fast and use `terminationGracePeriodSeconds` below that.
- Keep critical system Pods on a small on-demand pool with a taint.
@diagram flow
caption: Consolidation guard rails
nodes:
  - "Candidate node|underused|info"
  - "Budget allows|time window|warn"
  - "PDB allows|evictions OK|warn"
  - "Drain and replace|cheaper node|ok"
@h Scheduled budget
```yaml title="disruption-budget.yaml"
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: business-hours-safe
spec:
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
        - {key: karpenter.sh/capacity-type, operator: In, values: [on-demand]}
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    budgets:
      - nodes: "0"
        schedule: "0 8 * * mon-fri"
        duration: 10h
      - nodes: "20%"
```
@end

@concept Capacity planning and cost
@plain
Autoscaling finds machines; you still decide the shape of the fleet, how much headroom to hold and where the money goes.
@problem
Clusters often run at 20 to 30 percent real utilisation because requests are inflated.
@does
- Compare requested versus used CPU and memory; the gap is waste.
- Use spot instances for stateless and batch work with PDBs and multiple instance types; keep a baseline on-demand.
- Overprovision with low-priority pause Pods so burst traffic lands on ready nodes; they are preempted at once.
- Show cost per namespace or label with OpenCost or Kubecost.
- Right-size first, then consolidate, then buy commitments.
@diagram flow
caption: Savings order
numbered: true
nodes:
  - "Right-size requests|remove waste|ok"
  - "Autoscale nodes|match demand|ok"
  - "Use spot for tolerant work|discount|ok"
  - "Commit savings plans|stable base|ok"
@h Headroom placeholder
```yaml title="overprovision.yaml"
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: overprovision
value: -10
globalDefault: false
description: Placeholder Pods that yield to real workloads
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: overprovision
spec:
  replicas: 2
  selector:
    matchLabels:
      app: overprovision
  template:
    metadata:
      labels:
        app: overprovision
    spec:
      priorityClassName: overprovision
      containers:
        - name: pause
          image: registry.k8s.io/pause:3.10
          resources:
            requests: {cpu: "1", memory: 2Gi}
```
@end
