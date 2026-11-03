---
title: Hierarchical tenancy, vcluster and node isolation
minutes: 40
objectives:
  - Model teams and sub-teams with hierarchical namespaces or Capsule
  - Explain how vcluster gives each tenant a virtual control plane
  - Isolate noisy or untrusted workloads on dedicated nodes or sandboxed runtimes
---
Namespaces are flat. Real organisations are not. This section covers tools that add hierarchy, virtual clusters for stronger separation, and node-level isolation.

@concept Hierarchical namespaces and Capsule
@plain
Organisations have teams that contain sub-teams. Tools such as the Hierarchical Namespace Controller (HNC) and **Capsule** let you group namespaces under a tenant and propagate policy from parent to children.
@problem
With flat namespaces, giving a team ten namespaces means ten copies of RoleBindings, quotas and policies, and drift between them.
@does
- **HNC** adds parent and child relationships, and propagates selected objects (Roles, RoleBindings, NetworkPolicies) down the tree. Its development has slowed; check the project status before adopting.
- **Capsule** defines a `Tenant` custom resource owning many namespaces, with a shared quota, allowed StorageClasses and registries, and owners who may create namespaces within limits without cluster admin rights.
- Alternatives: Kyverno or Argo CD ApplicationSets generating the same objects into every namespace of a team.
@diagram flow
caption: A tenant owns many namespaces
nodes:
  - "Tenant team-a|owner group, quota|cp"
  - "team-a-dev|namespace|env"
  - "team-a-stage|namespace|env"
  - "team-a-prod|namespace|env"
@h Capsule tenant
```yaml title="capsule-tenant.yaml"
apiVersion: capsule.clastix.io/v1beta2
kind: Tenant
metadata:
  name: team-a
spec:
  owners:
    - name: oidc:team-a
      kind: Group
  namespaceOptions:
    quota: 5
  resourceQuotas:
    scope: Tenant
    items:
      - hard:
          requests.cpu: "16"
          requests.memory: 32Gi
  storageClasses:
    allowed:
      - gp3
```
@end

@concept Virtual clusters with vcluster
@plain
**vcluster** runs a complete Kubernetes API server (and its own data store) as Pods inside a namespace of a host cluster. The tenant gets a kubeconfig for the virtual cluster, where they are cluster admin.
@problem
Teams need cluster-level rights (install CRDs, create namespaces, run operators) but a real cluster per team is too costly and slow to create.
@does
- A **syncer** copies workload objects such as Pods and Services from the virtual cluster to the host namespace, where they actually run on shared nodes.
- Tenants see only their own namespaces and CRDs; the host sees ordinary Pods in one namespace with name suffixes.
- Creating one takes seconds, so they suit CI per pull request, ephemeral dev environments and platform teams offering self-service.
- The isolation is at the API level only. Pods still share the host kernel unless combined with dedicated nodes or sandboxing. Check the current vcluster documentation for the distribution and options.
@diagram layers
caption: Virtual and host cluster
layers:
  - {label: "Virtual cluster team-a", nodes: ["own API server|tenant is admin|cp", "own CRDs and namespaces|invisible to others|info"]}
  - {label: "Syncer", nodes: ["copies Pods, Services, PVCs|to the host namespace|warn"]}
  - {label: "Host cluster", nodes: ["namespace vcluster-team-a|quota applies here|env", "Shared nodes|real Pods run here|app"]}
@h Commands
```bash title="Create and use a vcluster" lab
vcluster create team-a --namespace vcluster-team-a
vcluster connect team-a --namespace vcluster-team-a        # switches kubeconfig context
kubectl get ns                                              # only the virtual cluster's namespaces
kubectl create ns demo && kubectl create deploy web --image=nginx:1.27 -n demo
vcluster disconnect
kubectl get pods -n vcluster-team-a                         # the synced Pod on the host
vcluster delete team-a --namespace vcluster-team-a
```
:::note
Put a ResourceQuota on the host namespace. The virtual cluster's own quotas are advisory for the tenant, but the host quota is the hard limit.
:::
@end

@concept Dedicated nodes with taints and affinity
@plain
Reserve nodes for a tenant or workload class by tainting them and adding a matching toleration and node selector to that tenant's Pods.
@problem
Noisy batch jobs slow latency sensitive services, and compliance may require that a tenant's Pods never share a node with others.
@does
- Taint repels all Pods that do not tolerate it; node labels with `nodeSelector` or affinity attract the right Pods. You need both to make a pool exclusive.
- Enforce the toleration and selector with a mutating policy (Kyverno or a ValidatingAdmissionPolicy plus defaults), otherwise tenants can omit them.
- On EKS use managed node groups or Karpenter NodePools per tenant; on Gardener use separate worker pools with labels and taints.
- Dedicated nodes cost more through lower packing efficiency; use them only where needed.
@diagram flow
caption: Taint plus selector gives an exclusive pool
nodes:
  - "Node pool tenant-a|taint tenant a NoSchedule|cp"
  - "Pod with toleration and selector|tenant a only|app"
  - "Other tenants' Pods|repelled by the taint|bad"
@h Manifest
```yaml title="dedicated-pool.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing
  namespace: team-a
spec:
  replicas: 2
  selector:
    matchLabels:
      app: billing
  template:
    metadata:
      labels:
        app: billing
    spec:
      nodeSelector:
        tenant: team-a
      tolerations:
        - key: tenant
          operator: Equal
          value: team-a
          effect: NoSchedule
      containers:
        - name: billing
          image: registry.example.com/team-a/billing:2.1.0
```
```bash title="Prepare the nodes" lab
kubectl label node node-5 tenant=team-a
kubectl taint node node-5 tenant=team-a:NoSchedule
kubectl get nodes -L tenant
```
@end

@concept Sandboxed runtimes and stronger isolation
@plain
Containers share the host kernel. For untrusted code, a **RuntimeClass** can select a sandbox (gVisor, Kata Containers, Firecracker based) that puts a smaller kernel or a micro VM between the workload and the host.
@problem
A kernel exploit in one container can reach every other container on the node. Running arbitrary customer code needs a stronger boundary than namespaces and cgroups.
@does
- `RuntimeClass` maps a name to a runtime handler configured on the node, and Pods opt in with `runtimeClassName`.
- Sandboxes add overhead and may not support every syscall or device; test your workload.
- Combine with Pod Security restricted, NetworkPolicy, dedicated nodes and no service account token.
- On EKS, Fargate gives a micro VM per Pod; on Gardener, availability of sandboxed runtimes depends on the worker image and extensions, so verify with your provider.
@diagram cmp
caption: Isolation layers
cards:
  - {h: "runc container", kind: warn, items: ["Shared kernel", "Fast, standard"]}
  - {h: "gVisor", kind: info, items: ["User space kernel", "Syscall interception", "Some overhead"]}
  - {h: "Kata or micro VM", kind: ok, items: ["Own kernel per Pod", "Strongest boundary", "More memory and start time"]}
@h RuntimeClass
```yaml title="runtimeclass.yaml"
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
scheduling:
  nodeSelector:
    sandbox: gvisor
---
apiVersion: v1
kind: Pod
metadata:
  name: untrusted-job
  namespace: team-a
spec:
  runtimeClassName: gvisor
  automountServiceAccountToken: false
  containers:
    - name: job
      image: registry.example.com/team-a/runner:1.0
```
@end

@concept Fair sharing with Kueue and noisy neighbours
@plain
Beyond quotas, batch-heavy clusters use a queueing system such as **Kueue** to admit jobs by tenant share, and Pod-level controls to limit noisy neighbours.
@problem
A hard quota either wastes idle capacity or lets a tenant starve others once the cluster is full. Batch jobs need fair, queued admission, not instant failure.
@does
- Kueue adds `ClusterQueue`, `LocalQueue` and `ResourceFlavor`. Tenants submit Jobs to their LocalQueue; Kueue admits them when quota is available and can borrow unused capacity from other queues within a cohort.
- Noisy neighbours also come from CPU throttling, shared disks, and network. Use requests that reflect reality, topology spread, and Guaranteed QoS for latency sensitive Pods.
- Set `ephemeral-storage` limits and PID limits to stop single Pods from exhausting node resources.
@diagram flow
caption: Queued admission
nodes:
  - "Tenant submits Job|to LocalQueue|app"
  - "Kueue|checks share and cohort|cp"
  - "Admitted|Pods created|ok"
  - "Waiting|until capacity frees|warn"
@h Queue sketch
```yaml title="kueue.yaml"
apiVersion: kueue.x-k8s.io/v1beta1
kind: ClusterQueue
metadata:
  name: team-a
spec:
  namespaceSelector:
    matchLabels:
      team: team-a
  cohort: shared
  resourceGroups:
    - coveredResources: ["cpu", "memory"]
      flavors:
        - name: default
          resources:
            - name: cpu
              nominalQuota: 16
            - name: memory
              nominalQuota: 64Gi
---
apiVersion: kueue.x-k8s.io/v1beta1
kind: LocalQueue
metadata:
  name: main
  namespace: team-a
spec:
  clusterQueue: team-a
```
@check
Do taints alone make a node pool exclusive? || No. A taint repels other Pods, but the tenant's Pods also need a node selector or affinity so they do not land on shared nodes.
Does vcluster isolate the kernel? || No. It isolates the API. Pods still share the host kernel unless you add dedicated nodes or a sandboxed runtime.
@end
