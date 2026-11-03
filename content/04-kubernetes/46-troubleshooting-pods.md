---
title: Troubleshooting playbook, Pod startup and runtime
minutes: 50
objectives:
  - Follow a repeatable method to find the layer that is failing
  - Diagnose Pending, CrashLoopBackOff, ImagePullBackOff, OOMKilled and evictions with exact commands
  - Fix the cause rather than restart the symptom
---
Most Kubernetes incidents fall into a small set of patterns. This playbook starts with a method and then walks through each pattern with the commands to confirm it and the usual fix.

@concept The troubleshooting method
@plain
Work from the outside in and from the object to its owner: is it scheduled, is it started, is it ready, is it reachable. Each stage has its own evidence.
@problem
Random restarts and `kubectl delete pod` hide the cause and the problem returns. A fixed order avoids guesswork and keeps you from changing three things at once.
@does
- Stage 1, **scheduling**: Pod phase `Pending`, event `FailedScheduling`.
- Stage 2, **start**: image pull, volume mount, container create (`ImagePullBackOff`, `ContainerCreating`, `CreateContainerConfigError`).
- Stage 3, **run**: process exits or is killed (`CrashLoopBackOff`, `OOMKilled`).
- Stage 4, **ready and reachable**: readiness probe, Service endpoints, DNS, NetworkPolicy.
- Always check what changed: a rollout, a node event, a quota, a new policy.
@diagram flow
caption: The four stages of a Pod
numbered: true
nodes:
  - "Scheduled|node chosen|cp"
  - "Started|image and volumes ready|app"
  - "Running|process stays up|info"
  - "Ready and reachable|in endpoints|ok"
@h First five commands
```bash title="Always start here" lab
kubectl get pods -n shop -o wide                              # phase, restarts, node
kubectl describe pod POD -n shop | tail -25                   # conditions and events
kubectl events -n shop --for pod/POD
kubectl logs POD -n shop --previous --tail=50
kubectl rollout history deploy/api -n shop                    # what changed recently
```
@check
Why start with events rather than logs for a Pending Pod? || A Pending Pod has not started, so it has no logs. The scheduler explains itself in events.
@end

@concept Pending Pods
@plain
A Pod stays **Pending** when no node can run it yet. The scheduler tells you the reason in a `FailedScheduling` event.
@problem
New Pods never start, a rollout stalls, or the cluster autoscaler does not add nodes.
@does
- `Insufficient cpu` or `Insufficient memory`: requests exceed free capacity. Reduce requests or add nodes.
- `node(s) had untolerated taint`: add a toleration or use a different pool.
- `didn't match Pod's node affinity/selector`: labels on nodes do not exist.
- `pod has unbound immediate PersistentVolumeClaims`: the PVC is pending (see storage).
- `exceeded quota` appears when the Deployment cannot create a Pod at all; look at ReplicaSet events instead.
- A topology spread or anti-affinity rule that cannot be satisfied also leaves Pods Pending.
@diagram flow
caption: Scheduler filters until nothing is left
nodes:
  - "All nodes|10 nodes|plain"
  - "Resource filter|7 fit|info"
  - "Taints and affinity|2 fit|warn"
  - "Volume zone|0 fit|bad"
  - "Pending|FailedScheduling|bad"
@h Commands
```bash title="Why is it Pending" lab
kubectl get pods -n shop --field-selector=status.phase=Pending
kubectl describe pod POD -n shop | grep -A8 -i 'events'
kubectl describe nodes | grep -A6 'Allocated resources'      # requests already placed
kubectl get nodes -o custom-columns=NAME:.metadata.name,TAINTS:.spec.taints
kubectl get resourcequota,limitrange -n shop
kubectl describe rs -n shop -l app=api | tail -15            # quota errors show on the ReplicaSet
```
:::tip
Requests, not actual usage, decide scheduling. A node at 10% CPU use can be "full" if the sum of requests is high. Compare `kubectl top nodes` with the Allocated resources output.
:::
@end

@concept ImagePullBackOff and ErrImagePull
@plain
The kubelet could not download the container image. It retries with an increasing delay, which is the BackOff in the name.
@problem
The Pod is scheduled but never starts, and the rollout stalls on the new ReplicaSet.
@does
- Read the exact error in `describe`: `manifest unknown` (tag does not exist), `unauthorized` or `denied` (credentials), `no such host` or timeout (network or DNS), `toomanyrequests` (registry rate limit).
- Private registry: create a docker-registry Secret and reference it in `imagePullSecrets`, or attach it to the ServiceAccount.
- On EKS with ECR the node role needs `AmazonEC2ContainerRegistryReadOnly`; ECR tokens are handled by the kubelet credential provider. Cross-account ECR needs a repository policy.
- Check the architecture: an arm64-only image on amd64 nodes fails differently (`exec format error`) after pulling.
@diagram flow
caption: Narrowing an image pull failure
nodes:
  - "Event text|read it exactly|info"
  - "manifest unknown|wrong tag or name|warn"
  - "unauthorized|pull secret or IAM|warn"
  - "timeout|egress, proxy, DNS|bad"
@h Commands
```bash title="Pull failures" lab
kubectl describe pod POD -n shop | grep -E 'Failed|Back-off|image' 
kubectl get pod POD -n shop -o jsonpath='{.spec.containers[*].image}{"\n"}'
kubectl create secret docker-registry regcred -n shop \
  --docker-server=registry.example.com --docker-username=ci --docker-password="$REG_TOKEN"
kubectl patch serviceaccount default -n shop -p '{"imagePullSecrets":[{"name":"regcred"}]}'
kubectl debug node/NODE -it --image=busybox:1.36 -- nslookup registry.example.com
```
@end

@concept CrashLoopBackOff
@plain
The container starts, exits, and the kubelet restarts it with a delay that doubles from 10 seconds up to 5 minutes. CrashLoopBackOff is a symptom, never a cause.
@problem
The application never becomes stable. Restart counts rise and the rollout does not complete.
@does
- First get the exit code: `kubectl get pod -o jsonpath='{.status.containerStatuses[0].lastState.terminated}'`. **1** is an application error, **137** is SIGKILL (often OOM or failed liveness), **143** is SIGTERM, **126 / 127** mean command not executable or not found.
- Read `logs --previous`. Typical causes are missing config or Secret values, an unreachable dependency at startup, bad command or args, and a liveness probe that kills a slow starter.
- If there are no logs, the process may fail before logging; use `kubectl debug` with a copy that overrides the command.
- A Pod that exits 0 under a Deployment also loops, since Deployments expect long running processes.
@diagram cmp
caption: Exit code tells you where to look
cards:
  - {h: "Exit 1 or 2", kind: warn, items: ["Application error", "Read previous logs", "Check config and dependencies"]}
  - {h: "Exit 137", kind: bad, items: ["SIGKILL", "OOMKilled or liveness", "Check reason field"]}
  - {h: "Exit 126 or 127", kind: bad, items: ["Command not executable or found", "Wrong entrypoint or image"]}
  - {h: "Exit 0", kind: info, items: ["Finished normally", "Wrong workload type, use a Job"]}
@h Commands
```bash title="Diagnose a crash loop" lab
kubectl get pod POD -n shop -o jsonpath='{.status.containerStatuses[0].lastState.terminated}{"\n"}'
kubectl logs POD -n shop --previous --tail=80
kubectl describe pod POD -n shop | grep -E 'Liveness|Readiness|Startup|Restart Count'
kubectl debug POD -n shop -it --copy-to=api-debug --container=api -- sh   # copy with a shell instead of the app
kubectl delete pod api-debug -n shop
```
@end

@concept OOMKilled and memory limits
@plain
When a container uses more memory than its limit, the kernel's OOM killer ends it. Kubernetes records `Reason: OOMKilled` with exit code 137.
@problem
The Pod restarts at seemingly random times, and logs end abruptly with no error.
@does
- Confirm with `lastState.terminated.reason`. The cause can be a leak, a limit set too low, or runtime settings such as the JVM heap not matching the container limit.
- Memory is incompressible, unlike CPU, which is throttled. Set the memory limit equal to the request for predictable behaviour and Guaranteed or Burstable QoS.
- The limit counts page cache and tmpfs (`emptyDir` with `medium: Memory`) too, not just heap.
- Use the working set metric, not RSS, when sizing. VPA in recommendation mode helps pick numbers.
- A **node level** OOM (the node ran out of memory) is different: the kernel kills by score and the kubelet may evict Pods first.
@diagram seq
caption: Limit exceeded
actors: ["Container|memory limit 256Mi|app", "Kernel|cgroup OOM killer|cp", "Kubelet|restarts|app"]
steps:
  - "0>0: allocates beyond 256Mi | warn"
  - "1>0: SIGKILL | bad"
  - "2>2: records OOMKilled, exit 137 | warn"
  - "2>0: restart after backoff | req"
@h Commands
```bash title="Confirm and size" lab
kubectl get pod POD -n shop -o jsonpath='{range .status.containerStatuses[*]}{.name}{" "}{.lastState.terminated.reason}{" "}{.lastState.terminated.exitCode}{"\n"}{end}'
kubectl top pod POD -n shop --containers
kubectl get pod POD -n shop -o jsonpath='{.status.qosClass}{"\n"}'
kubectl describe node NODE | grep -A3 -i 'oom\|MemoryPressure'
```
```yaml title="Right sized memory"
apiVersion: v1
kind: Pod
metadata:
  name: api
spec:
  containers:
    - name: api
      image: registry.example.com/shop/api:1.8.3
      env:
        - name: JAVA_TOOL_OPTIONS
          value: "-XX:MaxRAMPercentage=70"
      resources:
        requests: {cpu: 250m, memory: 768Mi}
        limits: {memory: 768Mi}
```
@end

@concept Evictions and node pressure
@plain
When a node runs low on memory, disk or process IDs, the kubelet evicts Pods to protect the node. Evicted Pods show status `Failed` with reason `Evicted`.
@problem
Pods vanish from a node with no deployment change, and `Evicted` Pods pile up in the namespace.
@does
- Conditions: `MemoryPressure`, `DiskPressure`, `PIDPressure` on the node. A pressured node also gets a taint, so new Pods avoid it.
- Eviction order favours Pods that exceed their requests and have low priority; Guaranteed Pods are last.
- `ephemeral-storage` requests and limits protect against logs and `emptyDir` filling the disk.
- Evicted Pods are replaced by their controller; the old objects are leftovers (clean up with a field selector).
- This differs from **preemption** (scheduler removes lower priority Pods to place a higher one) and from API-initiated eviction during drain.
@diagram flow
caption: From pressure to eviction
nodes:
  - "Memory or disk low|below threshold|warn"
  - "Node condition|taint added|info"
  - "Kubelet evicts|lowest priority over request first|bad"
  - "Controller recreates|on a healthy node|ok"
@h Commands
```bash title="Find and clean evictions" lab
kubectl describe node NODE | grep -E 'Conditions' -A8
kubectl get pods -A --field-selector=status.phase=Failed | grep Evicted | head
kubectl get pod POD -n shop -o jsonpath='{.status.reason}{" "}{.status.message}{"\n"}'
kubectl delete pods -n shop --field-selector=status.phase=Failed
kubectl top node NODE
```
@check
Which resource is incompressible, CPU or memory? || Memory. CPU is throttled; memory over the limit causes an OOM kill.
Why do Guaranteed Pods survive evictions longest? || Their requests equal their limits, so they never use more than they asked for, which is the first eviction criterion.
@end
