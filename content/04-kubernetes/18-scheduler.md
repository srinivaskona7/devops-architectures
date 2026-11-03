---
title: The scheduler in depth
minutes: 45
objectives:
  - Explain the scheduling cycle and its plugin extension points
  - Use nodeSelector, node affinity and Pod affinity correctly
  - Use taints, tolerations and priority to place and protect workloads
---
The scheduler is a pipeline of plugins. Knowing the stages lets you read FailedScheduling messages and pick the right constraint for each job.

@concept Scheduling cycle and plugins
@plain
For each Pod the scheduler runs a queue, a filter phase, a score phase and a bind phase. Each phase is made of plugins you can enable, disable or weight.
@problem
Fixed placement logic cannot suit batch, GPU, stateful and multi-tenant clusters all at once.
@does
- Extension points: `PreFilter`, `Filter`, `PostFilter` (preemption), `PreScore`, `Score`, `Reserve`, `Permit`, `Bind`.
- Built-in plugins include `NodeResourcesFit`, `NodeAffinity`, `TaintToleration`, `PodTopologySpread`, `InterPodAffinity`, `VolumeBinding`, `ImageLocality`.
- Profiles in `KubeSchedulerConfiguration` allow several schedulers behaviours; Pods choose with `schedulerName`.
- On managed control planes you cannot change the default scheduler config, but you can run a second scheduler (for example Volcano, Kueue's integration or a bin-packing one).
@diagram flow
caption: One Pod through the scheduler
numbered: true
nodes:
  - "Queue|priority order|plain"
  - "Filter|drop unfit nodes|cp"
  - "Score|rank the rest|cp"
  - "Reserve and bind|write nodeName|ok"
@h Read a scheduling failure
```bash title="Typical message" lab
kubectl describe pod api-7d9 | grep -A3 FailedScheduling
# 0/6 nodes are available: 2 Insufficient cpu, 3 node(s) had untolerated taint {dedicated: gpu},
# 1 node(s) didn't match Pod's node affinity/selector.
kubectl get events -A --field-selector reason=FailedScheduling | tail
```
@check
What does a message listing counts per reason tell you? || Every node was rejected by one of those filters, so the Pod stays Pending until one reason is resolved.
@end

@concept nodeSelector and node affinity
@plain
nodeSelector picks nodes by exact labels. Node affinity adds operators, required versus preferred rules and weights.
@problem
Workloads need particular hardware or location: GPU nodes, a zone, an architecture, a spot pool.
@does
- `nodeSelector`: simple AND of key=value.
- `requiredDuringSchedulingIgnoredDuringExecution`: hard rule; Pod stays Pending if no node matches.
- `preferredDuringSchedulingIgnoredDuringExecution`: soft rule with weight 1 to 100.
- Operators: `In`, `NotIn`, `Exists`, `DoesNotExist`, `Gt`, `Lt`.
- "IgnoredDuringExecution" means running Pods are not moved if labels later change.
- Well-known labels: `topology.kubernetes.io/zone`, `kubernetes.io/arch`, `node.kubernetes.io/instance-type`, `karpenter.sh/capacity-type`.
@diagram cmp
caption: Hard versus soft
cards:
  - {h: "required", kind: bad, items: ["Pod waits if nothing fits", "Use for real constraints"]}
  - {h: "preferred", kind: ok, items: ["Best effort with weight", "Use for preferences"]}
@h Arm64 on-demand preference
```yaml title="node-affinity.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: batch-arm
spec:
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
          - matchExpressions:
              - {key: kubernetes.io/arch, operator: In, values: [arm64]}
      preferredDuringSchedulingIgnoredDuringExecution:
        - weight: 80
          preference:
            matchExpressions:
              - {key: karpenter.sh/capacity-type, operator: In, values: [spot]}
  containers:
    - name: job
      image: busybox:1.36
      command: ["sleep", "60"]
```
@end

@concept Pod affinity and anti-affinity
@plain
Pod affinity attracts a Pod toward nodes (or zones) that already run certain other Pods. Anti-affinity repels it.
@problem
You may want a cache beside its app, or want replicas of one service on different nodes for failure isolation.
@does
- Uses a `labelSelector` plus a `topologyKey` (`kubernetes.io/hostname` for node, `topology.kubernetes.io/zone` for zone).
- Required anti-affinity across hostnames means at most one replica per node; scaling beyond node count leaves Pods Pending.
- Evaluation cost grows with cluster size; prefer **topology spread constraints** for even spreading at scale.
- `matchLabelKeys` (stable in recent releases) ties the rule to a rollout's `pod-template-hash`, so old and new ReplicaSets do not block each other.
@diagram layers
caption: Anti-affinity by hostname
layers:
  - {label: "node-a", nodes: ["api replica 1|app=api|app"]}
  - {label: "node-b", nodes: ["api replica 2|app=api|app"]}
  - {label: "node-c", nodes: ["api replica 3|app=api|app"]}
@h Spread replicas across nodes
```yaml title="anti-affinity.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      affinity:
        podAntiAffinity:
          preferredDuringSchedulingIgnoredDuringExecution:
            - weight: 100
              podAffinityTerm:
                topologyKey: kubernetes.io/hostname
                labelSelector:
                  matchLabels:
                    app: api
      containers:
        - name: api
          image: ghcr.io/example/api:1.4.2
```
@end

@concept Taints and tolerations
@plain
A taint on a node repels Pods. A toleration on a Pod lets it ignore a matching taint. Taints keep unwanted Pods out; they do not attract.
@problem
Special nodes (GPU, spot, control plane) should not receive ordinary Pods, and a failing node should shed its workloads.
@does
- Effects: `NoSchedule` (new Pods blocked), `PreferNoSchedule` (soft) and `NoExecute` (also evicts running Pods, optionally after `tolerationSeconds`).
- Taint a node: `kubectl taint nodes n1 dedicated=gpu:NoSchedule`; remove with a trailing `-`.
- Control plane nodes carry `node-role.kubernetes.io/control-plane:NoSchedule`.
- The node lifecycle controller adds `node.kubernetes.io/not-ready` and `unreachable` taints.
- For dedicated pools combine a taint (keep others out) with node affinity (pull yours in).
@diagram flow
caption: Dedicated GPU pool
nodes:
  - "GPU node|taint dedicated=gpu|warn"
  - "Normal Pod|no toleration, rejected|bad"
  - "GPU Pod|toleration plus affinity|ok"
@h GPU Pod
```yaml title="toleration.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: trainer
spec:
  tolerations:
    - {key: dedicated, operator: Equal, value: gpu, effect: NoSchedule}
    - {key: node.kubernetes.io/unreachable, operator: Exists, effect: NoExecute, tolerationSeconds: 60}
  nodeSelector:
    pool: gpu
  containers:
    - name: train
      image: ghcr.io/example/trainer:2.0
      resources:
        limits:
          nvidia.com/gpu: 1
```
@check
Does a toleration make a Pod go to the tainted node? || No. It only permits it. Add node affinity or a selector to attract it.
@end

@concept Topology spread constraints
@plain
Topology spread constraints keep Pods evenly distributed across zones, nodes or any label domain, within an allowed difference called `maxSkew`.
@problem
Without spreading, the scheduler may put all replicas in one zone, and a zone outage takes the service down.
@does
- `topologyKey` names the domain, `maxSkew` the largest allowed difference between the fullest and emptiest domain.
- `whenUnsatisfiable: DoNotSchedule` is hard; `ScheduleAnyway` is soft.
- `minDomains` forces use of at least that many domains; `nodeAffinityPolicy` and `nodeTaintsPolicy` control which nodes count.
- Combine zone (hard, skew 1) with hostname (soft) for strong availability.
- Spreading only applies at scheduling time; rebalance with the Descheduler or rollout restarts.
@diagram cmp
caption: Six replicas, maxSkew 1 across 3 zones
cards:
  - {h: "Zone a", kind: ok, items: ["2 replicas"]}
  - {h: "Zone b", kind: ok, items: ["2 replicas"]}
  - {h: "Zone c", kind: ok, items: ["2 replicas"]}
@h Spread across zones and nodes
```yaml title="topology-spread.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
spec:
  replicas: 6
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: web
          matchLabelKeys: [pod-template-hash]
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: web
      containers:
        - name: web
          image: nginx:1.27
```
@end

@concept PodDisruptionBudgets and node maintenance
@plain
Voluntary disruptions (drain, upgrade, autoscaler scale-down) go through the Eviction API, which respects PodDisruptionBudgets. Involuntary ones (crash, hardware) do not.
@problem
An upgrade that drains nodes can remove all replicas of a service in a minute.
@does
- PDB sets `minAvailable` or `maxUnavailable` for a selected set of Pods.
- `kubectl drain` cordons the node, evicts Pods through the API and waits when a PDB blocks.
- `unhealthyPodEvictionPolicy: AlwaysAllow` lets drains evict Pods that are not Ready, so a broken app cannot block an upgrade.
- Drains stuck for hours usually mean a PDB with zero allowed disruptions or a Pod with a local `emptyDir` needing `--delete-emptydir-data`.
- On Gardener-managed Kyma, node rolling follows the worker pool's `maxSurge` and `maxUnavailable` and respects PDBs; always uncordon and verify afterwards if you drain manually.
@diagram seq
caption: Drain with a PDB
actors: ["Operator|kubectl drain|ext", "Eviction API|cp|cp", "Scheduler|new Pod placement|cp"]
steps:
  - "0>1: cordon node, evict Pods | req"
  - "1>0: 429 blocked by PDB | bad"
  - "1>2: replacement Pod elsewhere | req"
  - "0>1: retry eviction | req"
  - "1>0: evicted | resp"
@h PDB and drain
```yaml title="pdb-api.yaml"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api
spec:
  minAvailable: 2
  unhealthyPodEvictionPolicy: AlwaysAllow
  selector:
    matchLabels:
      app: api
```
```bash title="Safe drain" lab
kubectl get pdb -A
kubectl drain worker-1 --ignore-daemonsets --delete-emptydir-data --timeout=10m
kubectl get node worker-1                  # SchedulingDisabled
kubectl uncordon worker-1                  # always restore afterwards
```
@end
