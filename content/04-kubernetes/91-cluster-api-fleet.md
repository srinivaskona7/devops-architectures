---
title: Cluster API and fleet management
minutes: 50
objectives:
  - Explain how Cluster API manages clusters as Kubernetes objects
  - Roll out upgrades and node pools declaratively across providers
  - Operate a fleet of clusters with GitOps and consistent policy
---
Once you run more than a few clusters, clicking in consoles does not scale. Fleet management treats clusters themselves as declarative objects.

@concept Why manage clusters declaratively
@plain
Instead of scripts that create clusters, you describe each cluster in YAML in Git and a controller makes it real and keeps it that way.
@problem
Hand-built clusters drift, upgrades are unrepeatable and nobody knows what is running where.
@does
- A management cluster runs controllers that create and upgrade workload clusters.
- Git is the source of truth; pull requests are the change process.
- The same model can describe EKS, Gardener shoots, vSphere or bare metal.
- Tools: Cluster API, Crossplane, Terraform with pipelines, Gardener (its own model), vendor consoles.
@diagram flow
caption: Declarative cluster lifecycle
nodes:
  - "Git|cluster manifests|ext"
  - "GitOps controller|applies to management cluster|cp"
  - "Provider controllers|call cloud APIs|app"
  - "Workload cluster|created and upgraded|ok"
@choose Cluster provisioning
Cluster API | many clusters on varied infrastructure | one managed cluster is enough
Terraform pipeline | you already use it for the rest of the cloud | you need continuous drift correction
Gardener | many conformant clusters with a central team | you need a single small cluster
@end

@concept Cluster API objects
@plain
Cluster API (CAPI) is a Kubernetes SIG project. It defines CRDs such as Cluster, Machine, MachineDeployment and MachineSet, similar to Pod, Deployment and ReplicaSet but for nodes.
@problem
Each cloud has different APIs for creating machines and control planes.
@does
- `Cluster` ties together a control plane object and an infrastructure object (for example `AWSCluster`).
- `KubeadmControlPlane` (or a managed variant such as `AWSManagedControlPlane` for EKS) handles control plane replicas and upgrades.
- `MachineDeployment` creates worker `Machine` objects from a `MachineTemplate` and a bootstrap config; rolling updates replace machines.
- `MachineHealthCheck` replaces unhealthy nodes automatically.
@diagram layers
caption: CAPI object tree
layers:
  - {label: "Cluster", nodes: ["Cluster|top object|cp"]}
  - {label: "Control plane", nodes: ["KubeadmControlPlane|3 replicas|cp", "AWSCluster|VPC and LB|ext"]}
  - {label: "Workers", nodes: ["MachineDeployment|N machines|app", "MachineTemplate|instance type, AMI|info"]}
@h Inspect with clusterctl
```bash title="clusterctl basics" lab
clusterctl init --infrastructure aws
clusterctl describe cluster prod-eu
kubectl get machines,machinedeployments -A
clusterctl get kubeconfig prod-eu > /tmp/prod-eu.kubeconfig
```
@check
Which CAPI object replaces broken nodes automatically? || A MachineHealthCheck, which deletes machines that fail its conditions so the MachineSet creates new ones.
@end

@concept Upgrades and node pools with CAPI
@plain
You change the Kubernetes version or machine template in YAML. CAPI performs a rolling replacement of control plane then workers.
@problem
In-place upgrades of nodes are risky and slow to roll back.
@does
- Control plane first: update `KubeadmControlPlane.spec.version`; it adds new machines then removes old ones.
- Workers: new `MachineTemplate` (immutable, so create a new one) referenced from the `MachineDeployment`, with `rollingUpdate` maxSurge and maxUnavailable.
- Respect version skew: workers may lag the control plane by a few minors (check the current skew policy).
- Pair with PodDisruptionBudgets so drains keep services up.
@diagram flow
caption: Upgrade order
numbered: true
nodes:
  - "Control plane version|bump in Git|cp"
  - "New CP machines|then old removed|info"
  - "New MachineTemplate|new image or version|app"
  - "Workers roll|drain and replace|ok"
@h MachineDeployment (shape)
```yaml title="Worker pool" nocheck
apiVersion: cluster.x-k8s.io/v1beta1
kind: MachineDeployment
metadata:
  name: prod-eu-workers
spec:
  clusterName: prod-eu
  replicas: 5
  strategy:
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels: {}
  template:
    spec:
      clusterName: prod-eu
      version: v{{v.kubernetes_latest_patch}}
      bootstrap:
        configRef:
          apiVersion: bootstrap.cluster.x-k8s.io/v1beta1
          kind: KubeadmConfigTemplate
          name: prod-eu-workers-v2
      infrastructureRef:
        apiVersion: infrastructure.cluster.x-k8s.io/v1beta2
        kind: AWSMachineTemplate
        name: prod-eu-workers-v2
```
:::note
CAPI API versions move. Generate templates with `clusterctl generate cluster` for your installed providers.
:::
@end

@concept ClusterClass and topology
@plain
ClusterClass is a reusable blueprint. A Cluster then says "use this class, with these variables" instead of repeating every object.
@problem
Dozens of nearly identical clusters mean dozens of copied manifests that drift apart.
@does
- The class defines templates for control plane, infrastructure and worker classes, plus patches driven by variables.
- A `Cluster` with `spec.topology` sets class, version, replicas and variables.
- Upgrading the class or version rolls out through all clusters that use it, in a controlled way.
- Good for platform teams who offer a few "flavours" of cluster.
@diagram flow
caption: Blueprint to clusters
nodes:
  - "ClusterClass|standard-eks|cp"
  - "Cluster A|topology version {{v.kubernetes_latest}}|app"
  - "Cluster B|topology version {{v.kubernetes_latest}}|app"
  - "Cluster C|dev, smaller pool|app"
@end

@concept Fleet GitOps with Argo CD or Flux
@plain
A fleet needs the same add-ons (ingress, monitoring, policy) on every cluster, with per-cluster differences. GitOps tools do this from one repository.
@problem
Installing add-ons manually on each cluster guarantees inconsistency.
@does
- Argo CD `ApplicationSet` generators (cluster, list, git) create one Application per registered cluster or folder.
- Flux uses `Kustomization` per cluster with a shared base and overlays, or a hub controlling remote clusters through kubeconfig secrets.
- Keep add-on versions in one place; promote through dev, staging, prod folders.
- Secrets via External Secrets or SOPS, never in plain YAML.
@diagram flow
caption: Hub and spokes
nodes:
  - "Git repo|base and overlays|ext"
  - "Argo CD hub|ApplicationSet|cp"
  - "Cluster dev|overlay dev|app"
  - "Cluster prod|overlay prod|app"
@h ApplicationSet by cluster label
```yaml title="Install monitoring on every prod cluster" nocheck
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: monitoring
  namespace: argocd
spec:
  generators:
    - clusters:
        selector:
          matchLabels:
            env: prod
  template:
    metadata:
      name: "monitoring-{{name}}"
    spec:
      project: platform
      source:
        repoURL: https://git.example.com/platform/addons.git
        targetRevision: main
        path: monitoring/overlays/prod
      destination:
        server: "{{server}}"
        namespace: monitoring
      syncPolicy:
        automated: {prune: true, selfHeal: true}
```
@check
How does ApplicationSet know which clusters exist? || Argo CD cluster secrets are the inventory. The cluster generator creates one app per matching registered cluster.
@end

@concept Crossplane and composition
@plain
Crossplane turns cloud resources into Kubernetes objects and lets platform teams publish simple custom APIs built from them.
@problem
Developers need a database or a bucket, but should not learn every cloud option or hold cloud credentials.
@does
- Providers add managed resources (RDS, S3, VPC). Compositions map your own CRD (a `PostgreSQLInstance` claim) to several managed resources.
- The platform team owns the composition; teams request with a few fields.
- Overlaps with Terraform; Crossplane suits continuous reconciliation and self service through the Kubernetes API.
- Check current API versions (Composition functions and pipelines replaced older patch-and-transform styles).
@diagram layers
caption: Self service API
layers:
  - {label: "Developer", nodes: ["Claim|size small, region eu|app"]}
  - {label: "Platform", nodes: ["Composition|rules|cp", "XRD|API schema|cp"]}
  - {label: "Cloud", nodes: ["Subnet group|managed|ext", "Database|managed|ext", "Secret|connection details|ok"]}
@end

@concept Fleet policy, inventory and upgrades at scale
@plain
At scale the questions change: what versions are running, which clusters are out of date, which violate policy.
@problem
A fleet with 40 clusters on 5 different Kubernetes versions cannot be patched safely or audited.
@does
- Keep an inventory (CMDB or a Git file): cluster, owner, environment, version, region. This is also useful in your own `CLUSTERS.md`.
- Standardise versions: at most two minors in use; upgrade dev first, then staging, then production with soak time.
- Policy as code (Kyverno, Gatekeeper, ValidatingAdmissionPolicy) distributed through GitOps.
- Central observability: Prometheus remote write or Thanos, central log store, one dashboard per cluster label.
- Automate end-of-life tracking from the Kubernetes release calendar and provider support dates.
@diagram flow
caption: Promotion ring
nodes:
  - "Ring 0|lab cluster|info"
  - "Ring 1|dev|app"
  - "Ring 2|staging|warn"
  - "Ring 3|production|ok"
@h Version report
```bash title="Server version of every context" lab
for c in $(kubectl config get-contexts -o name); do
  v=$(kubectl --context "$c" version -o json 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])' 2>/dev/null)
  echo "$c ${v:-unreachable}"
done
```
@end
