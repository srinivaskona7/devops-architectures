---
title: Namespaces, quotas and LimitRange
minutes: 45
objectives:
  - Use namespaces as the unit of tenancy and know what they do not isolate
  - Cap a tenant with ResourceQuota and set defaults with LimitRange
  - Onboard a team with a repeatable namespace template
---
Multi-tenancy means several teams or customers share one cluster. The cluster is cheaper and simpler to run, but you must prevent tenants from starving or harming each other. The namespace is where that starts.

@concept Tenancy models
@plain
There is a range from "everyone in one cluster" to "one cluster per tenant". Namespaces give soft isolation inside a cluster. Separate clusters give hard isolation.
@problem
Too little isolation lets one team's mistake or compromise affect others. Too much (a cluster per team) multiplies cost and operations.
@does
- **Soft multi-tenancy** (trusted teams in one company): namespaces plus RBAC, quotas, NetworkPolicy and Pod Security.
- **Hard multi-tenancy** (untrusted tenants): separate clusters, or virtual clusters with dedicated nodes and sandboxed runtimes.
- Kubernetes shares the control plane, the kernel on each node (unless sandboxed) and cluster-scoped resources such as CRDs between tenants in a cluster.
- Decide the model from the trust level and compliance needs, not from convenience.
@diagram cmp
caption: Isolation strength versus cost
cards:
  - {h: "Namespaces", kind: ok, items: ["Cheapest", "Shared control plane and kernel", "For trusted teams"]}
  - {h: "Virtual clusters", kind: info, items: ["Own API server per tenant", "Shared nodes", "Own CRDs and admin rights"]}
  - {h: "Cluster per tenant", kind: warn, items: ["Strongest isolation", "Highest cost", "Most operations"]}
@choose Which model
Namespace per team | internal teams who share a trust boundary | tenants that must not share a kernel or API server
Virtual cluster | teams need their own CRDs, cluster admin and CI environments | strict kernel level isolation is required
Cluster per tenant | regulation, noisy or hostile tenants, different versions | you cannot afford the operations overhead
@end

@concept Namespaces
@plain
A namespace is a named scope inside a cluster. Most objects (Pods, Services, Secrets, ConfigMaps, Roles) live in exactly one namespace, and names must be unique only within it.
@problem
Without scoping, every object name in the cluster would need to be unique, and permissions or limits could not be given to one team only.
@does
- Cluster-scoped objects (Nodes, PersistentVolumes, StorageClasses, CRDs, ClusterRoles, Namespaces themselves) are not namespaced; `kubectl api-resources --namespaced=false` lists them.
- Namespaces are the attachment point for RBAC RoleBindings, ResourceQuota, LimitRange, NetworkPolicy and Pod Security labels.
- They do **not** isolate network traffic by themselves, and a Service in one namespace is reachable from another as `svc.ns`.
- Deleting a namespace deletes everything in it. Protect production namespaces with RBAC and admission policy.
- Every namespace has the automatic label `kubernetes.io/metadata.name`, handy for selectors.
@diagram layers
caption: What attaches to a namespace
layers:
  - {label: "Namespace shop", nodes: ["Workloads|Pods, Services|app", "RoleBindings|who may do what|info", "ResourceQuota|how much in total|warn", "LimitRange|defaults per container|warn", "NetworkPolicy|who may talk|bad"]}
@h Commands
```bash title="Explore scope" lab
kubectl api-resources --namespaced=true | head -12
kubectl api-resources --namespaced=false | head -12
kubectl get ns --show-labels
kubectl config set-context --current --namespace=shop       # default namespace for kubectl
```
@end

@concept ResourceQuota
@plain
A **ResourceQuota** caps the total resources a namespace may consume or create: CPU and memory requests and limits, storage, and counts of objects.
@problem
One team deploys a runaway job or too many replicas and takes all the capacity from everyone else. Or a mistaken loop creates thousands of objects and burdens the API server.
@does
- `requests.cpu`, `requests.memory`, `limits.cpu`, `limits.memory`: totals across all Pods in the namespace.
- `requests.storage`, `persistentvolumeclaims`, per StorageClass quotas, and object counts such as `pods`, `services`, `services.loadbalancers`, `count/deployments.apps`.
- When compute quota is set, **every Pod must specify requests and limits** for those resources, or be rejected; a LimitRange can supply defaults.
- `scopes` and `scopeSelector` apply quota to a subset, such as Pods of a PriorityClass.
- Exceeding quota rejects creation at the API (HTTP 403 `exceeded quota`). For Deployments the error appears on the ReplicaSet events.
@diagram flow
caption: Admission against quota
nodes:
  - "Create Pod|requests 2 CPU|app"
  - "Quota check|used 7 of 8 CPU|cp"
  - "Rejected|403 exceeded quota|bad"
  - "Smaller request|fits|ok"
@h A team quota
```yaml title="quota.yaml"
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-a
  namespace: team-a
spec:
  hard:
    requests.cpu: "8"
    requests.memory: 16Gi
    limits.memory: 24Gi
    persistentvolumeclaims: "10"
    requests.storage: 200Gi
    services.loadbalancers: "1"
    count/deployments.apps: "30"
```
```bash title="Usage versus limit" lab
kubectl describe resourcequota team-a -n team-a
kubectl get resourcequota -A
```
@end

@concept LimitRange
@plain
A **LimitRange** sets default requests and limits for containers that do not specify any, and minimum and maximum values per container, Pod or PersistentVolumeClaim.
@problem
Quota demands requests on every Pod, so teams that forget get rejections. And without a maximum one container can claim a whole node.
@does
- `default` sets limits and `defaultRequest` sets requests for containers that omit them.
- `min` and `max` reject containers outside the range; `maxLimitRequestRatio` limits the gap between request and limit.
- Applied at admission time; it does not change running Pods.
- Choose defaults that are safe, such as a small request and a memory limit equal to the request.
@diagram flow
caption: A container without resources
nodes:
  - "Pod without resources|forgot to set them|warn"
  - "LimitRange admission|fills defaults|cp"
  - "Quota admission|counts the defaults|info"
  - "Pod created|has requests and limits|ok"
@h Defaults and bounds
```yaml title="limitrange.yaml"
apiVersion: v1
kind: LimitRange
metadata:
  name: defaults
  namespace: team-a
spec:
  limits:
    - type: Container
      defaultRequest:
        cpu: 100m
        memory: 128Mi
      default:
        memory: 256Mi
      max:
        cpu: "2"
        memory: 4Gi
    - type: PersistentVolumeClaim
      max:
        storage: 50Gi
```
@check
Why do Pods get rejected after you add a compute ResourceQuota? || Quota requires every Pod to declare requests and limits for the quota'd resources. Add them or provide a LimitRange with defaults.
@end

@concept Priority classes and fairness
@plain
When capacity is short, **PriorityClass** decides which Pods may preempt others. API Priority and Fairness protects the API server from one noisy client.
@problem
Critical services must not wait behind batch jobs, and one tenant's controller must not saturate the API server for everybody.
@does
- A PriorityClass gives a Pod an integer priority. The scheduler may evict lower priority Pods to place a higher one (preemption). `preemptionPolicy: Never` disables evicting others.
- Restrict who may use high priorities with a quota scoped to PriorityClass, or an admission policy; otherwise every team marks their Pods critical.
- **API Priority and Fairness** (`FlowSchema`, `PriorityLevelConfiguration`) queues API requests fairly per user or service account; check `apiserver_flowcontrol_*` metrics when controllers are throttled.
@diagram flow
caption: Preemption
nodes:
  - "High priority Pod Pending|no room|warn"
  - "Scheduler finds victims|lower priority Pods|cp"
  - "Victims evicted|graceful stop|bad"
  - "High priority Pod runs|capacity reclaimed|ok"
@h Priority classes
```yaml title="priorityclasses.yaml"
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
  name: batch
value: 1000
preemptionPolicy: Never
description: Batch jobs that must not displace others
```
@end

@concept A namespace template for onboarding
@plain
Create tenant namespaces from one template so every team gets the same guardrails: labels, quota, LimitRange, default-deny NetworkPolicy, Pod Security level and RBAC.
@problem
Hand-made namespaces differ. Some lack quota, some lack policy, and nobody can tell which is correct.
@does
- Keep the template in Git as a Helm chart or Kustomize base, and apply it per tenant through GitOps.
- Labels carry ownership and cost metadata (`team`, `cost-center`, `env`) that cost tools use later.
- Bind a team group (from your identity provider) to the `edit` ClusterRole in its namespace, not `cluster-admin`.
- Tools such as Capsule or the Hierarchical Namespace Controller automate this pattern; plain GitOps works too.
@diagram layers
caption: Contents of the namespace template
layers:
  - {label: "Identity", nodes: ["Labels|team, cost-center|info", "RoleBinding|group gets edit|info"]}
  - {label: "Limits", nodes: ["ResourceQuota|capacity cap|warn", "LimitRange|defaults|warn"]}
  - {label: "Safety", nodes: ["Pod Security labels|baseline or restricted|bad", "Default deny NetworkPolicy|segmentation|bad"]}
@h Template
```yaml title="tenant-namespace.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: team-a
  labels:
    team: team-a
    cost-center: "cc-1042"
    pod-security.kubernetes.io/enforce: baseline
    pod-security.kubernetes.io/warn: restricted
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: team-a-edit
  namespace: team-a
subjects:
  - kind: Group
    name: oidc:team-a
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: ClusterRole
  name: edit
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: team-a
spec:
  podSelector: {}
  policyTypes: ["Ingress"]
```
```bash title="Verify the tenant" lab
kubectl auth can-i create deployments -n team-a --as-group oidc:team-a --as someone
kubectl auth can-i create clusterrolebindings --as-group oidc:team-a --as someone
```
@end
