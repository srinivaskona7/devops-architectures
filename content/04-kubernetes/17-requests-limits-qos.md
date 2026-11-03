---
title: Requests, limits and QoS
minutes: 50
objectives:
  - Size requests and limits and explain what each one does in the kernel
  - Explain CPU throttling and OOM kills
  - Predict QoS class and eviction order
---
Resource settings are the contract between your Pod and the scheduler, the kubelet and the Linux kernel. Most mysterious latency and restarts trace back to them.

@concept Requests and limits
@plain
A **request** is what the scheduler reserves for a container. A **limit** is the ceiling the kernel enforces at run time.
@problem
Without requests the scheduler packs Pods blindly. Without limits one noisy Pod can starve its neighbours.
@does
- The scheduler adds up requests of Pods on a node and compares with the node's **allocatable**; limits are ignored for placement.
- CPU is measured in cores (`500m` is half a core); memory in bytes (`256Mi`).
- CPU is **compressible**: over the limit you are slowed down. Memory is **incompressible**: over the limit you are killed.
- Requests are also the basis for HPA utilisation percentages and for quota.
@diagram layers
caption: Who uses which number
layers:
  - {label: "Scheduler", nodes: ["requests|where does it fit|cp"]}
  - {label: "Kernel cgroups", nodes: ["cpu.weight|from CPU request, relative share|info", "cpu.max|from CPU limit, hard cap|warn", "memory.max|from memory limit, OOM kill|bad"]}
  - {label: "Autoscalers", nodes: ["HPA|percent of request|app"]}
@h Container resources
```yaml title="resources.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
        - name: api
          image: ghcr.io/example/api:1.4.2
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              memory: 512Mi
```
@end

@concept CPU throttling
@plain
A CPU limit is enforced with the CFS quota: in each 100 ms period the container may use only `limit x 100 ms` of CPU time, then it is paused until the next period.
@problem
A container with a 1-core limit can still show low average CPU but suffer long latency, because bursts hit the cap within a period.
@does
- A multi-threaded app with a limit of 1 CPU and 4 busy threads uses its quota in 25 ms and stalls for 75 ms.
- Metric `container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total` shows the throttled share.
- Many teams set CPU **requests** but no CPU **limits**, so spare CPU can be used and the request still guarantees a share; memory requests equal limits. This is a trade-off, not a rule: limits are needed for fairness in shared tenancy and some compliance regimes.
- Runtimes must see the limit: modern JVM and Go (1.25+) respect cgroup limits; older Go needs `GOMAXPROCS` set (automaxprocs).
@diagram seq
caption: One 100 ms period with a 1 CPU limit and 4 threads
actors: ["Threads x4|app|app", "CFS quota|1 CPU = 100ms|warn"]
steps:
  - "0>1: run 4 threads in parallel | req"
  - "note 1..1: 100 ms quota used up in 25 ms"
  - "1>0: throttled for 75 ms | bad"
  - "1>0: new period, run again | resp"
@h Measure throttling
```promql title="PromQL for throttling" nocheck
# percentage of periods throttled per container
sum by (pod, container) (rate(container_cpu_cfs_throttled_periods_total[5m]))
  / sum by (pod, container) (rate(container_cpu_cfs_periods_total[5m]))
# actual use versus request
sum by (pod) (rate(container_cpu_usage_seconds_total[5m]))
```
:::tip
Alert on sustained throttling above about 25 percent for latency-sensitive services, then raise the limit or remove it, rather than only raising the request.
:::
@check
Why can a service be throttled at 20 percent average CPU? || Throttling is decided per 100 ms period; short bursts across many threads can exhaust the quota while the average stays low.
@end

@concept Memory limits and OOM kills
@plain
Exceeding the memory limit makes the kernel's OOM killer terminate the container's process. Kubernetes shows `OOMKilled` and exit code 137.
@problem
Memory cannot be slowed down like CPU, so the only enforcement is killing.
@does
- Page cache and mapped files count toward the cgroup. Reclaimable cache is dropped first; anonymous memory is not.
- Set memory request equal to limit for predictable behaviour and QoS `Guaranteed` (if CPU also matches).
- JVM: set `-XX:MaxRAMPercentage` (for example 75) so heap plus off-heap fits the limit. Node.js: `--max-old-space-size`.
- Swap is off by default; limited swap support exists for Burstable Pods, so do not assume it.
- Node-level memory pressure causes **kubelet eviction** (graceful), different from a container OOM kill.
@diagram flow
caption: Memory ceiling hit
nodes:
  - "Allocation grows|heap and cache|warn"
  - "Reaches limit|cgroup memory.max|bad"
  - "OOM killer|SIGKILL|bad"
  - "Restart|CrashLoop if repeated|warn"
@h Confirm an OOM kill
```bash title="Find OOM kills" lab
kubectl get pod api-7d9 -o jsonpath='{.status.containerStatuses[0].lastState.terminated}{"\n"}'
kubectl top pod api-7d9 --containers
kubectl describe pod api-7d9 | grep -E 'OOMKilled|Exit Code|Limits' -A2
kubectl get events -A --field-selector reason=OOMKilling
```
@end

@concept QoS classes and eviction order
@plain
Kubernetes labels each Pod `Guaranteed`, `Burstable` or `BestEffort` from its requests and limits, and uses it to decide who dies first under pressure.
@problem
When a node runs out of memory, someone must be removed. The order should protect important Pods.
@does
- **Guaranteed**: every container has CPU and memory requests equal to limits. Lowest OOM score.
- **Burstable**: at least one request or limit set, but not Guaranteed.
- **BestEffort**: nothing set at all. First to be killed.
- Kubelet eviction ranks Pods by whether they exceed requests, then priority, then usage above request. Within the kernel OOM killer, `oom_score_adj` follows QoS.
@diagram cmp
caption: QoS classes
cards:
  - {h: "Guaranteed", kind: ok, items: ["requests equal limits for CPU and memory", "Last to be evicted"]}
  - {h: "Burstable", kind: warn, items: ["Some requests or limits", "Evicted when above request"]}
  - {h: "BestEffort", kind: bad, items: ["No requests or limits", "First to be evicted"]}
@h Read the class
```bash title="QoS of running Pods" lab
kubectl get pods -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,QOS:.status.qosClass | sort -k3 | head -20
kubectl get pod api-7d9 -o jsonpath='{.status.qosClass}{"\n"}'
```
@check
A Pod has memory requests equal to limits but only a CPU request. QoS? || Burstable. Guaranteed needs requests equal to limits for both CPU and memory in every container.
@end

@concept Right-sizing, in-place resize and PriorityClass
@plain
Good numbers come from measurement. Newer Kubernetes can resize a running Pod, and PriorityClass says which Pods matter more.
@problem
Guessing requests wastes money (too high) or causes evictions and throttling (too low).
@does
- Measure P95 or P99 usage over a representative window; set request near typical usage plus headroom, memory limit above peak.
- Tools: VPA in recommendation mode, Goldilocks, Kubecost, Prometheus queries.
- **In-place Pod resize** (`resizePolicy`, beta and on by default from 1.33) changes CPU and memory of a running container without recreation.
- **PriorityClass** gives integer priority; the scheduler can **preempt** lower priority Pods to place a higher one. `preemptionPolicy: Never` prevents preempting others.
@diagram flow
caption: Measure, set, verify
numbered: true
nodes:
  - "Observe usage|P95 for a week|info"
  - "Set request|usage plus headroom|app"
  - "Watch throttling and OOM|verify|warn"
  - "Review monthly|drift|ok"
@h Priority classes
```yaml title="priorityclass.yaml"
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
description: Batch work that yields to services
```
@end

@concept Node pressure, eviction and allocatable
@plain
Each node reserves resources for the OS and kubelet and evicts Pods before the machine runs out of memory or disk.
@problem
If Pods can use all RAM, the kubelet and kernel starve and the whole node fails instead of one Pod.
@does
- Allocatable = capacity - `kube-reserved` - `system-reserved` - eviction threshold.
- Hard thresholds (for example `memory.available<100Mi`) trigger immediate eviction; soft thresholds wait a grace period.
- Under pressure the node gets conditions `MemoryPressure`, `DiskPressure`, `PIDPressure` and a `NoSchedule` taint.
- Evicted Pods end in `Failed` with reason `Evicted`; clean them with a periodic job since they linger.
@diagram flow
caption: Pressure response
nodes:
  - "Memory low|below threshold|warn"
  - "Node condition set|MemoryPressure|warn"
  - "Taint added|no new Pods|bad"
  - "Evict by QoS and usage|free memory|ok"
@h Inspect node accounting
```bash title="What is allocated" lab
kubectl describe node worker-1 | sed -n '/Allocated resources/,/Events/p'
kubectl top nodes
kubectl get pods -A --field-selector=status.phase=Failed | grep Evicted | head
```
@end
