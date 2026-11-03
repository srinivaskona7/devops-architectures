---
title: Gardener and Kyma concepts
minutes: 55
objectives:
  - Explain gardens, seeds and shoots and how a shoot control plane is hosted
  - Read a Shoot specification and understand maintenance and hibernation
  - Describe how Kyma sits on a Gardener cluster and what the module model is
---
SAP BTP Kyma runtime is a Kubernetes cluster managed with Gardener, with Kyma modules installed on top. Knowing both layers helps you decide where a problem belongs.

@concept Garden, seed and shoot
@plain
Gardener is a Kubernetes extension that manages Kubernetes clusters at scale. It uses Kubernetes to run Kubernetes.
@problem
Providing hundreds of conformant clusters with consistent upgrades needs a control layer that is itself cloud neutral.
@does
- **Garden cluster**: runs the Gardener API (`Shoot`, `Seed`, `Project`, `CloudProfile` objects).
- **Seed cluster**: a Kubernetes cluster that hosts the control planes (kube-apiserver, etcd, controllers) of many shoots as Pods in per-shoot namespaces.
- **Shoot cluster**: the end user cluster. Its worker nodes run in the customer's cloud account (or the provider's), while the control plane is in the seed.
- **Soil**: the initial seed that hosts the garden itself.
@diagram layers
caption: Gardener topology
layers:
  - {label: "Garden", nodes: ["Gardener API|Shoot, Seed, Project|cp", "Gardener controller manager|reconciles|cp"]}
  - {label: "Seed", nodes: ["Shoot A control plane|apiserver, etcd as Pods|app", "Shoot B control plane|apiserver, etcd as Pods|app"]}
  - {label: "Shoots", nodes: ["Workers of A|VMs in cloud account|ok", "Workers of B|VMs in cloud account|ok"]}
@check
Where does a shoot's kube-apiserver run? || As a Pod in a namespace of the seed cluster, not on the shoot's own worker nodes.
@end

@concept Reading a Shoot specification
@plain
A Shoot object describes the cluster: provider, region, Kubernetes version, networking, worker pools, maintenance and hibernation.
@problem
Cluster configuration must be reviewable and repeatable like any other code.
@does
- `spec.provider.workers[]`: pool name, machine type and image, `minimum`, `maximum`, zones, taints, labels.
- `spec.kubernetes.version`, and optional kube-apiserver, kubelet and audit settings.
- `spec.networking`: type (calico or cilium), pods, services and nodes CIDRs.
- `spec.maintenance`: time window and whether to auto update Kubernetes patch version and machine image.
- `spec.hibernation` schedules to stop worker nodes for savings. Fields differ per Gardener version and landscape; check your landscape's docs.
@diagram flow
caption: What a Shoot controls
nodes:
  - "Shoot spec|desired cluster|app"
  - "Gardener reconcile|extensions per cloud|cp"
  - "Control plane in seed|plus infrastructure|info"
  - "Workers join|cluster ready|ok"
@h Excerpt
```yaml title="Shoot excerpt" nocheck
apiVersion: core.gardener.cloud/v1beta1
kind: Shoot
metadata:
  name: dev-eu
  namespace: garden-myproject
spec:
  region: eu-central-1
  kubernetes:
    version: {{v.kubernetes_latest_patch}}
  networking:
    type: calico
    nodes: 10.250.0.0/16
  provider:
    type: aws
    workers:
      - name: pool-a
        machine: {type: m5.xlarge, image: {name: gardenlinux}}
        minimum: 2
        maximum: 6
        zones: [eu-central-1a, eu-central-1b]
  maintenance:
    timeWindow: {begin: 220000+0000, end: 230000+0000}
    autoUpdate:
      kubernetesVersion: true
      machineImageVersion: true
```
@end

@concept Maintenance, updates and hibernation
@plain
Gardener updates clusters in a maintenance window and can hibernate them, which stops workers while keeping the cluster definition and data.
@problem
Patching many clusters by hand is slow, and idle dev clusters waste money.
@does
- Patch version and machine image updates can happen automatically in the window. Minor Kubernetes upgrades are normally your decision and must be done stepwise (one minor at a time).
- Rolling node replacement drains nodes respecting PDBs. Pods without PDBs or with long shutdowns may be disrupted; set them properly.
- Hibernation scales workers to zero on a schedule; PVC data persists but Pods stop.
- Be aware of the drain and cordon lesson from earlier: after manual maintenance, check that nodes are uncordoned since reconciliation may interfere.
@diagram flow
caption: Maintenance window
nodes:
  - "Window opens|22:00 UTC|plain"
  - "New image or patch|rolling update|info"
  - "Drain with PDB|per node|warn"
  - "Pods rescheduled|cluster healthy|ok"
@h Check from kubectl
```bash title="After maintenance" lab
kubectl get nodes -o custom-columns=NAME:.metadata.name,VERSION:.status.nodeInfo.kubeletVersion,SCHEDULABLE:.spec.unschedulable,OS:.status.nodeInfo.osImage
kubectl get pdb -A
kubectl get events -A --sort-by=.lastTimestamp | tail -15
```
@check
Why define PDBs for Gardener maintenance? || Node replacement drains nodes. PDBs limit how many replicas of a service are evicted at once.
@end

@concept Gardener extensions and operations
@plain
Gardener keeps cloud specifics out of its core. Extensions (provider, OS, network, DNS, certificates) handle each environment.
@problem
Supporting AWS, Azure, GCP, OpenStack and others in one codebase would be unmaintainable.
@does
- Extension CRDs such as `Infrastructure`, `Worker`, `ControlPlane`, `Network` and `OperatingSystemConfig` are reconciled by provider extensions in the seed.
- Shoot lifecycle shows in `status.lastOperation` and `status.conditions` (`APIServerAvailable`, `ControlPlaneHealthy`, `EveryNodeReady`, `SystemComponentsHealthy`).
- Shoots get a `shoot-info` ConfigMap in `kube-system` and managed components in `kube-system`.
- Operators use `gardenctl` to target gardens and obtain shoot kubeconfigs; credentials are short lived via the `gardenlogin` plugin.
@diagram flow
caption: Reconcile through extensions
nodes:
  - "Shoot change|new worker pool|app"
  - "Worker extension|creates machine class|info"
  - "machine-controller-manager|creates VMs|cp"
  - "Node joins|Ready|ok"
@h Operator commands
```bash title="gardenctl workflow" lab
gardenctl target --garden mylandscape --project myproject --shoot dev-eu
gardenctl kubectl-env bash > /tmp/env.sh && source /tmp/env.sh
kubectl get nodes
kubectl -n kube-system get cm shoot-info -o yaml | head -20
```
:::note
Commands depend on your landscape's setup. Follow your team's gardenctl configuration guide.
:::
@end

@concept Kyma runtime on top of Gardener
@plain
SAP BTP, Kyma runtime provides a Gardener shoot already prepared with Kyma. You get a kubeconfig, a managed set of modules and BTP integration.
@problem
Teams want Kubernetes and BTP services together, without installing and wiring the platform pieces themselves.
@does
- Kyma runs in a BTP subaccount and is created via BTP cockpit, CLI or service instance. The cluster is a Gardener shoot managed by SAP.
- Access is by OIDC through the BTP identity provider (SAP IAS), commonly with the `kubelogin` plugin and a downloaded kubeconfig.
- Cluster add-ons (Istio, API Gateway, Serverless, Telemetry, etc.) are provided as Kyma modules managed via the `Kyma` custom resource, with release channels.
- SAP is responsible for the control plane and the modules' lifecycle; you own namespaces and applications.
@diagram layers
caption: Layers of BTP Kyma runtime
layers:
  - {label: "SAP BTP", nodes: ["Subaccount|entitlements, IAS|ext", "Service Manager|service instances|ext"]}
  - {label: "Kyma", nodes: ["Kyma Infrastructure Manager|creates the cluster|cp", "Lifecycle Manager|installs modules|cp"]}
  - {label: "Gardener", nodes: ["Shoot|managed Kubernetes|info"]}
  - {label: "Your workloads", nodes: ["Namespaces|apps and functions|app"]}
@h First contact
```bash title="Check a Kyma cluster" lab
kubectl get kyma -n kyma-system -o jsonpath='{.items[0].status.state}{"\n"}'
kubectl get modules -A 2>/dev/null | head
kubectl get nodes -L topology.kubernetes.io/zone
```
@end

@concept The Kyma custom resource and release channels
@plain
The `Kyma` resource in `kyma-system` lists enabled modules and their channel. Lifecycle Manager reads it and installs or upgrades the modules.
@problem
Choosing and upgrading features needs a simple declarative handle.
@does
- Each module entry has `name`, optional `channel` (`regular`, `fast`) or a fixed `version`, and optional custom resource policy.
- `kubectl get kyma default -n kyma-system -o yaml` shows each module's state (`Ready`, `Processing`, `Error`, `Warning`) and the installed version.
- Each module has its own CR (for example `Istio`, `APIGateway`, `Telemetry`) holding module configuration.
- Removing a module deletes its CR and may remove workloads, so read the module's deletion notes first.
- Module names and fields change over releases; check the current Kyma docs.
@diagram flow
caption: Module lifecycle
nodes:
  - "Kyma CR|lists modules|app"
  - "Lifecycle Manager|reads templates|cp"
  - "Module manager|installs workloads|info"
  - "Module state|Ready or Error|ok"
@h Enable a module
```yaml title="Kyma resource with modules" nocheck
apiVersion: operator.kyma-project.io/v1beta2
kind: Kyma
metadata:
  name: default
  namespace: kyma-system
spec:
  channel: regular
  modules:
    - name: istio
    - name: api-gateway
    - name: serverless
    - name: telemetry
```
```bash title="Status of modules" lab
kubectl get kyma default -n kyma-system -o jsonpath='{range .status.modules[*]}{.name}{" "}{.state}{" "}{.version}{"\n"}{end}'
```
@check
Where do you enable or disable a Kyma module? || In the Kyma custom resource (or the BTP cockpit, which edits it).
@end
