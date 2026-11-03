---
title: Advanced scheduling
minutes: 55
objectives:
  - Use priority classes and preemption deliberately
  - Rebalance clusters with the descheduler and spread constraints
  - Queue batch work with Kueue and understand scheduler profiles
---
The default scheduler is good, but busy shared clusters need priorities, rebalancing and fair queues for batch work.
@concept The scheduling cycle and plugins
@plain
For each Pod the scheduler filters nodes that can run it, scores the rest, and binds the best. Every step is a plugin.
@problem
To tune placement you must know which extension point does what, or you change the wrong thing.
@does
- Queue: `PreEnqueue`, `QueueSort`. Scheduling cycle: `PreFilter`, `Filter`, `PostFilter` (preemption), `PreScore`, `Score`, `Reserve`, `Permit`. Binding cycle: `PreBind`, `Bind`, `PostBind`.
- Filter plugins: NodeResourcesFit, NodeAffinity, TaintToleration, PodTopologySpread, VolumeBinding.
- Score plugins prefer for example least allocated or balanced resources.
- `percentageOfNodesToScore` limits scoring in huge clusters.
@diagram flow
caption: One Pod's journey
nodes:
  - "Queue|sorted by priority|plain"
  - "Filter|feasible nodes|info"
  - "Score|rank nodes|info"
  - "Reserve and bind|write nodeName|ok"
@h Read scheduler decisions
```bash title="Why this node" lab
kubectl get events -n shop --field-selector reason=Scheduled -o custom-columns=POD:.involvedObject.name,MSG:.message | head
kubectl describe pod POD -n shop | grep -A6 Events
```
@end

@concept Scheduler profiles and configuration
@plain
A KubeSchedulerConfiguration can define several profiles in one scheduler, each with its own name and plugin set. A Pod picks one with `schedulerName`.
@problem
Different workloads want different strategies, such as bin-packing for batch and spreading for web, without running separate schedulers.
@does
- Profile `plugins` enable or disable plugins; `pluginConfig` sets args, for example NodeResourcesFit with `MostAllocated` scoring.
- Self-managed control planes pass the file through `--config`. Managed services (EKS, Gardener shoot) often expose limited settings or none, so check what your platform allows.
- A second full scheduler Deployment is possible for experiments.
@diagram cmp
caption: Two profiles in one scheduler
cards:
  - {h: "default-scheduler", kind: info, items: ["Spread (least allocated)", "For web services"]}
  - {h: "binpack-scheduler", kind: ok, items: ["MostAllocated scoring", "Fills nodes first", "Lets autoscaler remove empty nodes"]}
@h Config shape
```yaml title="Two profiles" nocheck
apiVersion: kubescheduler.config.k8s.io/v1
kind: KubeSchedulerConfiguration
profiles:
  - schedulerName: default-scheduler
  - schedulerName: binpack-scheduler
    pluginConfig:
      - name: NodeResourcesFit
        args:
          scoringStrategy:
            type: MostAllocated
            resources:
              - {name: cpu, weight: 1}
              - {name: memory, weight: 1}
```
@check
How does a Pod pick a profile? || With spec.schedulerName set to the profile name.
@end

@concept Priority and preemption
@plain
A PriorityClass gives Pods an integer priority. When a high priority Pod cannot fit, the scheduler may evict lower priority Pods to make room (preemption).
@problem
Critical services must run even when a cluster is full of batch jobs.
@does
- `PriorityClass` has `value`, `globalDefault` and `preemptionPolicy` (`PreemptLowerPriority` or `Never`).
- System classes `system-cluster-critical` and `system-node-critical` are reserved for platform Pods.
- Preemption respects PodDisruptionBudgets only on a best effort basis, and victims get their grace period.
- Priority also orders the queue and node-pressure eviction. Do not give everything high priority.
@diagram seq
caption: Preemption
actors: ["High priority Pod|pending|app", "Scheduler|PostFilter|cp", "Low priority Pod|victim|warn"]
steps:
  - "0>1: no node fits | warn"
  - "1>2: delete victim | bad"
  - "1>0: nominatedNodeName set | resp"
  - "1>0: bind after space frees | resp"
@h Classes
```yaml title="Priority classes for batch and critical"
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: business-critical
value: 100000
globalDefault: false
description: Customer facing services
---
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: batch-low
value: 1000
preemptionPolicy: Never
description: Batch jobs that wait rather than preempt
```
@end

@concept Topology spread and affinity at scale
@plain
`topologySpreadConstraints` keep replicas balanced across zones or nodes. Affinity and anti-affinity attract or repel Pods.
@problem
All replicas on one node or zone defeat redundancy.
@does
- `maxSkew`, `topologyKey`, `whenUnsatisfiable` (`DoNotSchedule` or `ScheduleAnyway`) and `labelSelector` define the rule.
- `minDomains` and `matchLabelKeys` (for per-revision spreading in rollouts) refine it; check availability in your version.
- Required pod anti-affinity is expensive in large clusters; prefer spread constraints.
- Spread is evaluated only at scheduling time, so later imbalance needs the descheduler.
@diagram layers
caption: Spread across zones then nodes
layers:
  - {label: "Zone a", nodes: ["node a1|api-1|app", "node a2|api-2|app"]}
  - {label: "Zone b", nodes: ["node b1|api-3|app", "node b2|api-4|app"]}
@h Example
```yaml title="Spread over zone and node"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 4
  selector:
    matchLabels: {app: api}
  template:
    metadata:
      labels: {app: api}
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels: {app: api}
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: {app: api}
      containers:
        - name: api
          image: registry.example.com/shop/api:1.8.3
```
@check
Why does imbalance appear after node failures even with spread rules? || Constraints are checked only when a Pod is scheduled. Existing Pods are not moved afterwards.
@end

@concept The descheduler
@plain
The descheduler is a separate component that evicts Pods that are badly placed now, so the scheduler can place them again.
@problem
Clusters drift: new nodes join empty, taints change, spread skews, and long-lived Pods stay where they were first put.
@does
- Strategies (plugins): `LowNodeUtilization`, `HighNodeUtilization`, `RemoveDuplicates`, `RemovePodsViolatingTopologySpreadConstraint`, `RemovePodsViolatingNodeAffinity`, `RemovePodsHavingTooManyRestarts`, `PodLifeTime`.
- Runs as Job, CronJob or Deployment. Respects PDBs and does not evict static or DaemonSet Pods by default.
- Evictions use the eviction API, so graceful shutdown applies. Always set PDBs and test in dry-run (`dryRun: true`).
@diagram flow
caption: Descheduler loop
nodes:
  - "Scan cluster|policy strategies|info"
  - "Evict Pod|eviction API with PDB|warn"
  - "Controller recreates|new Pod|app"
  - "Scheduler places|better node|ok"
@h Policy (shape)
```yaml title="Descheduler policy" nocheck
apiVersion: descheduler/v1alpha2
kind: DeschedulerPolicy
profiles:
  - name: rebalance
    pluginConfig:
      - name: DefaultEvictor
        args:
          nodeFit: true
      - name: RemovePodsViolatingTopologySpreadConstraint
      - name: LowNodeUtilization
        args:
          thresholds: {cpu: 20, memory: 20, pods: 20}
          targetThresholds: {cpu: 50, memory: 50, pods: 50}
    plugins:
      balance:
        enabled:
          - RemovePodsViolatingTopologySpreadConstraint
          - LowNodeUtilization
```
:::warn
The policy API version changes between releases. Copy the example from the release you deploy.
:::
@end

@concept Kueue and job queueing
@plain
Kueue is a Kubernetes SIG project that adds quotas and queues for batch workloads. Jobs are suspended until their quota is admitted.
@problem
Without admission control, many Jobs create Pods at once, fill the cluster and leave important work Pending in a partial state.
@does
- `ClusterQueue` holds quotas per resource flavor (for example on-demand versus spot, or GPU types) and can borrow unused quota between queues in a cohort.
- `LocalQueue` in a namespace points to a ClusterQueue. Jobs opt in with the label `kueue.x-k8s.io/queue-name`.
- Works with Job, JobSet, Kubeflow and Ray types. Supports priority, preemption and fair sharing.
- Admission is all or nothing for the whole workload (with optional partial admission).
@diagram flow
caption: Admission path
nodes:
  - "Job suspended|queue label|app"
  - "LocalQueue|team namespace|info"
  - "ClusterQueue|quota and flavors|cp"
  - "Admitted|unsuspended, Pods created|ok"
@h Queue and Job
```yaml title="Queue objects and a queued Job" nocheck
apiVersion: kueue.x-k8s.io/v1beta1
kind: ResourceFlavor
metadata:
  name: default
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata:
  name: team-a
spec:
  namespaceSelector: {}
  resourceGroups:
    - coveredResources: [cpu, memory]
      flavors:
        - name: default
          resources:
            - {name: cpu, nominalQuota: 40}
            - {name: memory, nominalQuota: 160Gi}
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: main
  namespace: batch
spec:
  clusterQueue: team-a
---
apiVersion: batch/v1
kind: Job
metadata:
  name: report
  namespace: batch
  labels:
    kueue.x-k8s.io/queue-name: main
spec:
  suspend: true
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: r
          image: busybox:1.36
          command: ["sleep", "30"]
          resources:
            requests: {cpu: "2", memory: 4Gi}
```
@check
Why is a Kueue Job created suspended? || Kueue unsuspends it only when quota is available, so Pods are not created before admission.
@end
