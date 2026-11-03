---
title: Node upgrades, drain and PodDisruptionBudgets
minutes: 45
objectives:
  - Drain a node safely and explain what a PodDisruptionBudget protects
  - Choose between in-place, surge and blue-green node pool upgrades
  - Diagnose a drain that never finishes
---
Nodes are replaced far more often than control planes. The skill is to move workloads off a node without breaking availability, using drain, eviction and PodDisruptionBudgets together.
@concept Cordon, drain and the eviction API
@plain
**Cordon** marks a node unschedulable. **Drain** cordons and then asks every Pod on the node to leave using the Eviction API, which respects PodDisruptionBudgets and graceful shutdown.
@problem
Simply shutting a node down kills its Pods abruptly. Services drop requests and StatefulSet members vanish without warning.
@does
- `kubectl drain NODE --ignore-daemonsets --delete-emptydir-data` evicts all Pods except DaemonSet Pods and warns about local data.
- Evicted Pods are recreated by their controller on other nodes; **bare Pods are not recreated** and block drain unless `--force`.
- Each eviction sends SIGTERM and waits `terminationGracePeriodSeconds` before SIGKILL.
- Use `--timeout`, and `--disable-eviction` only in emergencies because it bypasses PDBs.
- Always `kubectl uncordon NODE` after maintenance on a node you keep.
@diagram flow
caption: What drain does
numbered: true
nodes:
  - "Cordon|no new Pods|warn"
  - "Evict Pod|checks PDB first|cp"
  - "Graceful stop|SIGTERM then grace period|app"
  - "Recreated|on another node|ok"
@h Commands
```bash title="Maintenance on one node" lab
kubectl cordon node-3
kubectl drain node-3 --ignore-daemonsets --delete-emptydir-data --timeout=300s
kubectl get pods -A -o wide --field-selector spec.nodeName=node-3
# do the maintenance, then
kubectl uncordon node-3
kubectl get nodes
```
:::warn
On Gardener-managed clusters such as Kyma, reconciliation can reset node state. Check that cordoned nodes are uncordoned afterwards, and prefer replacing nodes through the worker pool instead of long manual maintenance.
:::
@end

@concept PodDisruptionBudgets
@plain
A **PodDisruptionBudget (PDB)** limits how many Pods of a set can be down because of voluntary disruptions such as drain. It does not stop crashes or node failures.
@problem
A drain or autoscaler could evict all replicas of a service at once, causing an outage that nobody intended.
@does
- Set either `minAvailable` or `maxUnavailable` (not both), as a number or percentage, with a label selector.
- The Eviction API refuses an eviction that would break the budget, returning 429, and drain retries.
- `status.disruptionsAllowed` shows how many Pods may be evicted right now.
- `unhealthyPodEvictionPolicy: AlwaysAllow` lets drain evict Pods that are not ready, which prevents stuck drains with crashing Pods (stable since 1.31).
@diagram flow
caption: Eviction checked against a budget
nodes:
  - "Drain asks to evict|Pod 1 of 3|app"
  - "PDB minAvailable 2|allowed 1|cp"
  - "Evicted|2 left running|ok"
  - "Second eviction|would leave 1|bad"
@h A PDB
```yaml title="pdb.yaml"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api
  namespace: shop
spec:
  maxUnavailable: 1
  unhealthyPodEvictionPolicy: AlwaysAllow
  selector:
    matchLabels:
      app: api
```
```bash title="Inspect budgets" lab
kubectl get pdb -n shop
kubectl describe pdb api -n shop | grep -E 'Allowed|Current|Desired'
```
:::tip
A PDB with `minAvailable` equal to the replica count (or `maxUnavailable: 0`) blocks every drain. That is the most common reason an upgrade hangs.
:::
@end

@concept Why a drain hangs
@plain
A drain finishes only when every evictable Pod has left. A single blocker keeps it waiting forever unless you set a timeout.
@problem
An upgrade pipeline hangs on one node, nodes stay cordoned, and capacity shrinks.
@does
- **PDB with zero allowed disruptions**: scale up, loosen the PDB, or fix the unhealthy Pod.
- **Single replica** with `minAvailable: 1`: add a replica, or accept a short outage with a documented exception.
- **Pod not terminating**: a finalizer, a stuck volume detach, or an app ignoring SIGTERM; check the grace period.
- **Replacement cannot schedule**: no capacity, topology constraints, or a PVC pinned to another zone.
- **Bare Pod or local storage**: needs `--force` or `--delete-emptydir-data`.
@diagram cmp
caption: Common blockers and the fix
cards:
  - {h: "PDB allows zero", kind: bad, items: ["Check disruptionsAllowed", "Add replicas", "Loosen the budget"]}
  - {h: "Replacement Pending", kind: warn, items: ["No capacity or zone", "Add a node or surge", "Check PVC zone"]}
  - {h: "Pod will not stop", kind: warn, items: ["SIGTERM ignored", "Finalizer present", "Lower grace period carefully"]}
@h Diagnose
```bash title="Find the blocker" lab
kubectl drain node-3 --ignore-daemonsets --delete-emptydir-data --timeout=120s 2>&1 | tail -5
kubectl get pdb -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed
kubectl get pods -A -o wide --field-selector spec.nodeName=node-3 | grep -v DaemonSet
kubectl get pods -A --field-selector=status.phase=Pending
kubectl get pod POD -n shop -o jsonpath='{.metadata.finalizers}{" "}{.metadata.deletionTimestamp}{"\n"}'
```
@check
What does a PDB protect against? || Voluntary disruptions through the Eviction API, such as drain and autoscaler scale down. It does not prevent crashes or node failure.
@end

@concept Graceful shutdown for Pods
@plain
When a Pod is deleted, it is removed from Service endpoints and the container receives SIGTERM at roughly the same time. A `preStop` hook and `terminationGracePeriodSeconds` give the app time to finish.
@problem
During drains and rollouts, in-flight requests fail because the app stops immediately, or because load balancers still send traffic to a Pod that is shutting down.
@does
- Endpoint removal and SIGTERM are asynchronous; traffic can still arrive for a few seconds. A `preStop` sleep of 5 to 10 seconds, or app-level draining, hides this race.
- The app must handle SIGTERM: stop accepting, finish requests, close connections, then exit. Shell wrappers that do not forward signals break this.
- The grace period (30 s default) includes `preStop` time. Raise it for slow jobs.
- Native `sleep` lifecycle action exists in newer releases, so distroless images do not need a shell for the preStop.
@diagram seq
caption: Termination order for a Pod
actors: ["API server|deletes Pod|cp", "Endpoints and LB|stop routing|ext", "Container|your app|app"]
steps:
  - "0>1: remove from endpoints | req"
  - "0>2: preStop sleep 10 | req"
  - "2>2: SIGTERM, drain requests | warn"
  - "2>0: exits cleanly | resp"
  - "0>2: SIGKILL after grace period | bad"
@h Manifest
```yaml title="graceful-deployment.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: shop
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
      terminationGracePeriodSeconds: 45
      containers:
        - name: api
          image: registry.example.com/shop/api:1.8.3
          lifecycle:
            preStop:
              sleep:
                seconds: 10
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
```
@end

@concept Node upgrade strategies
@plain
Nodes are upgraded either **in place** (update software on the same machine), by **rolling replacement** (new nodes join, old ones drain and leave), or by **blue-green node pools**.
@problem
Mutating long-lived nodes accumulates drift and risk. Replacing them is cleaner but needs spare capacity and tolerant workloads.
@does
- **Surge (rolling replacement)**: create up to N extra nodes with the new version first, then drain old ones. EKS managed node groups use `maxUnavailable` or percentage settings; Gardener worker pools use `maxSurge` and `maxUnavailable`.
- **Blue-green pool**: create a new node group or pool, cordon and drain the old, delete it. Easy to roll back until the old pool is gone.
- **In-place** (kubeadm, self-managed): fastest for small clusters, hardest to undo.
- **Karpenter**: set drift or expire policies and a new AMI selector; nodes are replaced within disruption budgets.
- Prefer immutable images and regular rotation, even without a Kubernetes upgrade, to pick up OS patches.
@diagram flow
caption: Blue-green node pool
numbered: true
nodes:
  - "Create pool v2|new version nodes|ok"
  - "Cordon pool v1|stop scheduling|warn"
  - "Drain pool v1|PDBs respected|cp"
  - "Delete pool v1|after soak|plain"
@choose Strategy
Surge rolling replacement | the default for managed node groups and Gardener pools | zero spare capacity or quota for extra nodes
Blue-green pool | big version jumps, new OS or instance family, easy rollback | IP space or quota is tight
In place | small self-managed clusters you can rebuild | production where a failed node upgrade must be reversible
@h Commands
```bash title="EKS managed node group" lab
aws eks update-nodegroup-config --cluster-name shop --nodegroup-name general \
  --update-config maxUnavailablePercentage=33
aws eks update-nodegroup-version --cluster-name shop --nodegroup-name general
kubectl get nodes -L eks.amazonaws.com/nodegroup,topology.kubernetes.io/zone -w
```
@end

@concept Node rotation and Gardener notes
@plain
Nodes should be rotated regularly, not only on Kubernetes upgrades. Gardener (the system under Kyma and SAP's managed Kubernetes) does this through maintenance windows and worker pool settings.
@problem
Old nodes miss OS security updates and carry drift. Unplanned rotation during business hours causes disruption.
@does
- A Gardener Shoot has a `maintenance` section with a time window and flags to auto update Kubernetes patch versions and machine image versions. Machine image updates replace nodes, so the window decides when workloads move.
- Worker pools define `minimum`, `maximum`, `maxSurge`, `maxUnavailable`, zones, and machine type; pools can be changed without touching others.
- Run workloads with 2 or more replicas, topology spread across zones, PDBs and graceful shutdown, so any rotation looks like a normal rollout.
- Verify the live Shoot spec in your landscape before relying on field names; they differ by Gardener version.
@diagram layers
caption: What decides node replacement
layers:
  - {label: "Provider settings", nodes: ["Maintenance window|when nodes may be replaced|cp", "maxSurge and maxUnavailable|how many at once|cp"]}
  - {label: "Your workloads", nodes: ["PDBs|keep minimum available|ok", "Replicas and spread|survive one node or zone|ok", "Graceful shutdown|no dropped requests|ok"]}
@h Commands
```bash title="Watch a rotation" lab
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,OS:.status.nodeInfo.osImage,AGE:.metadata.creationTimestamp
kubectl get events -A --field-selector reason=NodeNotSchedulable --watch
kubectl get pods -A -o wide | grep -v Running
kubectl get pdb -A
```
@check
Why spread replicas across zones and nodes? || So a drain or node loss removes only some replicas and the PDB can still allow evictions.
@end

@concept After the upgrade, verify and roll back
@plain
After each step you verify cluster health with a short, fixed set of commands. Rolling back means undoing what you can: node pools, add-ons and manifests. The control plane version cannot be downgraded.
@problem
Problems found hours later are hard to attribute. Without a stop rule you keep going on a degraded cluster.
@does
- Check API server health, node versions and readiness, system Pods, and deprecated API metrics, then run a smoke test deployment and your synthetic checks.
- Compare alert rates and error budget against the pre-upgrade baseline.
- Rollback options: keep old node pool until the soak ends; pin add-on versions so you can revert them; revert application manifests in Git.
- For a failed control plane upgrade on a managed service, the provider normally handles it; open a support case early. Recovering from a bad state without a downgrade path is why you test in a non-production cluster first.
@diagram flow
caption: Verify after each stage
nodes:
  - "Control plane|API ready, version correct|cp"
  - "Add-ons|DNS, CNI, CSI healthy|info"
  - "Nodes|Ready and new version|app"
  - "Workloads|smoke tests and SLOs|ok"
@h Post-upgrade checks
```bash title="Smoke commands" lab
kubectl version
kubectl get --raw='/readyz?verbose' | tail -5
kubectl get nodes -o wide
kubectl get pods -n kube-system
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl run smoke --rm -it --restart=Never --image=busybox:1.36 -- nslookup kubernetes.default
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis | head
```
@end
