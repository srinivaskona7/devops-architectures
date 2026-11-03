---
title: Cluster lifecycle on EKS and Gardener
minutes: 40
objectives:
  - Describe how clusters are created, scaled, replaced and retired as code
  - Manage EKS add-ons and Gardener shoots without drifting from Git
  - Plan backups and disaster recovery for what the provider does not protect
---
A cluster is not a pet. This section covers the full life of a cluster: creation as code, add-on management, the differences between EKS and Gardener/Kyma, backups, and replacing a cluster rather than repairing it.

@concept Clusters as code
@plain
Create clusters from declarative definitions (Terraform, eksctl, Gardener Shoot manifests, Crossplane) stored in Git, not by clicking in a console.
@problem
A hand-built cluster cannot be reproduced after a disaster, reviewed before a change, or compared with staging.
@does
- Separate layers: network and account, the cluster and node pools, platform add-ons, and applications. Each has its own state and change rhythm.
- Terraform with the AWS EKS module or `eksctl` for EKS; a `Shoot` custom resource applied to the Gardener garden cluster for Gardener; the Kyma runtime is provisioned through the BTP cockpit, CLI or Terraform provider.
- Platform add-ons (ingress, cert-manager, external-dns, policy engine, monitoring) are installed by GitOps so a new cluster converges to the same state.
@diagram layers
caption: Layers with separate change cycles
layers:
  - {label: "Applications", nodes: ["Helm and Kustomize releases|GitOps|app"]}
  - {label: "Platform add-ons", nodes: ["ingress, cert-manager, monitoring, policy|GitOps|info"]}
  - {label: "Cluster", nodes: ["control plane and node pools|Terraform, eksctl, Shoot|cp"]}
  - {label: "Foundation", nodes: ["VPC, IAM, DNS, accounts|Terraform|ext"]}
@h An eksctl definition
```yaml title="cluster.yaml"
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: shop
  region: eu-west-1
  version: "{{v.eks_to}}"
managedNodeGroups:
  - name: general
    instanceType: m6i.large
    minSize: 3
    maxSize: 9
    desiredCapacity: 3
    availabilityZones: ["eu-west-1a", "eu-west-1b", "eu-west-1c"]
    updateConfig:
      maxUnavailablePercentage: 33
addons:
  - name: vpc-cni
  - name: coredns
  - name: kube-proxy
  - name: aws-ebs-csi-driver
iam:
  withOIDC: true
```
```bash title="Create and connect" lab
eksctl create cluster -f cluster.yaml
aws eks update-kubeconfig --name shop --region eu-west-1
kubectl get nodes
```
@end

@concept EKS managed add-ons
@plain
EKS can install and upgrade core components (VPC CNI, CoreDNS, kube-proxy, EBS CSI driver, Pod Identity agent) as **managed add-ons** with versions that are tested against each Kubernetes version.
@problem
Core add-ons are easy to forget during an upgrade. An outdated CoreDNS or CNI breaks after a control plane upgrade or misses fixes.
@does
- `aws eks describe-addon-versions` lists versions compatible with a Kubernetes version; `update-addon` upgrades with a conflict resolution mode (`OVERWRITE`, `PRESERVE`).
- Custom configuration goes in the add-on's `configurationValues` JSON, so Terraform can own it instead of drifting through `kubectl edit`.
- Upgrade add-ons right after the control plane and before the nodes, following the version guidance in the EKS documentation.
@diagram flow
caption: Add-on step after the control plane
nodes:
  - "Control plane 1.34|done|cp"
  - "kube-proxy and CoreDNS|compatible versions|info"
  - "VPC CNI and CSI|compatible versions|info"
  - "Node groups|then upgraded|app"
@h Commands
```bash title="Inspect and upgrade an add-on" lab
aws eks describe-addon-versions --addon-name vpc-cni --kubernetes-version {{v.eks_to}} \
  --query 'addons[0].addonVersions[0:3].addonVersion'
aws eks describe-addon --cluster-name shop --addon-name coredns --query 'addon.{v:addonVersion,s:status}'
aws eks update-addon --cluster-name shop --addon-name coredns --addon-version vX.Y.Z-eksbuild.N --resolve-conflicts PRESERVE
```
@end

@concept Gardener shoots and Kyma runtimes
@plain
**Gardener** manages Kubernetes clusters called **shoots**. A shoot's control plane runs as Pods in another cluster (the seed), and workers run in your infrastructure account. The **Kyma runtime** on SAP BTP is a Gardener shoot with Kyma modules enabled.
@problem
Operating control planes, OS images and node rotation yourself is expensive. Gardener makes them declarative and automated.
@does
- The Shoot spec holds `kubernetes.version`, `provider.workers[]` (machine type, `minimum`, `maximum`, `maxSurge`, `maxUnavailable`, zones), `networking`, `maintenance` and `hibernation`.
- Hibernation scales workers to zero to save cost for non-production clusters.
- In Kyma, you manage modules (Istio, Serverless, API Gateway, Telemetry and others) through the Kyma custom resource; your workloads run on the shoot like any Kubernetes cluster.
- Typical access is through a kubeconfig from the BTP cockpit or the `kubectl oidc-login` plugin; verify which context you are on before every command.
@diagram flow
caption: Shoot control plane lives elsewhere
nodes:
  - "Garden|manages shoots|cp"
  - "Seed cluster|runs shoot control planes|cp"
  - "Shoot workers|your nodes and Pods|app"
  - "Kyma modules|Istio, API Gateway, Telemetry|info"
@h Verify context safely
```bash title="Know where you are" lab
kubectl config get-contexts
kubectl config current-context
kubectl get nodes -L topology.kubernetes.io/zone,node.kubernetes.io/instance-type
kubectl get kyma -A 2>/dev/null | head       # present only on Kyma runtimes
kubectl get namespace kyma-system
```
@end

@concept Add-on inventory and GitOps for platform components
@plain
Keep one list of everything that runs in `kube-system` and platform namespaces, with version and owner, and install it from Git with a GitOps controller.
@problem
Without an inventory you cannot answer "what must I upgrade before moving to {{v.eks_to}}?" and new clusters differ subtly from old ones.
@does
- Pin chart versions in Git; renovate or similar tooling opens pull requests for updates.
- Use an **app of apps** (Argo CD) or Flux Kustomizations so one commit bootstraps a new cluster.
- Group by wave: CRDs and CNI first, then controllers (cert-manager, ingress), then policies, then apps.
- Record the supported Kubernetes range per add-on in the repository README.
@diagram flow
caption: Bootstrap order
numbered: true
nodes:
  - "CRDs and CNI|foundation|cp"
  - "cert-manager, ingress, DNS|controllers|info"
  - "Policies and RBAC|guardrails|warn"
  - "Applications|workloads|app"
@h Flux bootstrap sketch
```yaml title="clusters/prod/platform.yaml"
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: platform
  namespace: flux-system
spec:
  interval: 10m
  path: ./platform/overlays/prod
  prune: true
  sourceRef:
    kind: GitRepository
    name: fleet
  healthChecks:
    - apiVersion: apps/v1
      kind: Deployment
      name: ingress-nginx-controller
      namespace: ingress
```
@end

@concept Backup and disaster recovery
@plain
The provider protects the control plane and etcd. You protect your application data, your manifests and your ability to rebuild.
@problem
Deleted namespaces, corrupt volumes or a lost region cannot be fixed by the cloud provider. A backup that was never restored is only a hope.
@does
- **Manifests**: Git is the backup of desired state. **Data**: CSI VolumeSnapshots, cloud snapshots (EBS), database native backups.
- **Velero** backs up cluster objects and volume snapshots to object storage and restores them into the same or another cluster.
- Define RPO (how much data you can lose) and RTO (how long recovery may take) per application, then test a restore on a schedule.
- Remember secrets and keys: restoring encrypted Secrets also needs the key or external secrets source.
@diagram flow
caption: What protects what
nodes:
  - "Git|manifests and charts|plain"
  - "Velero|objects and volumes to S3|app"
  - "Snapshots and DB backups|application data|db"
  - "Restore drill|proves it works|ok"
@h Velero schedule
```yaml title="velero-schedule.yaml"
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-shop
  namespace: velero
spec:
  schedule: "0 2 * * *"
  template:
    includedNamespaces: ["shop"]
    snapshotVolumes: true
    ttl: 168h0m0s
```
```bash title="Restore drill" lab
velero backup get
velero restore create --from-backup daily-shop-20261031020000 --namespace-mappings shop:shop-restore
velero restore describe daily-shop-20261031020000-20261031100000 --details
```
@end

@concept Replace rather than repair
@plain
For major changes, build a new cluster beside the old one and move traffic, instead of mutating the old one in place.
@problem
In-place upgrades of control plane, CNI or networking mode cannot always be undone, and drifted clusters accumulate surprises.
@does
- **Blue-green clusters**: create cluster B from the same code with the new version, deploy through GitOps, test, then move traffic using DNS weights or a global load balancer.
- Works best for stateless services; stateful data needs replication or a planned cutover.
- Costs temporary double capacity but gives a complete rollback path: point DNS back.
- Decommission only after a soak, and remove DNS records, load balancers and volumes to avoid orphans.
@diagram flow
caption: Traffic shift between clusters
nodes:
  - "Cluster A {{v.eks_from}}|serving 100%|env"
  - "Cluster B {{v.eks_to}}|built from Git|app"
  - "DNS weights|10, 50, 100 percent|cp"
  - "Retire A|after soak|plain"
@choose Upgrade or replace
In-place upgrade | routine minor upgrades with good test coverage | you also change CNI mode, IP family or other one-way settings
Blue-green cluster | large changes, risky add-on swaps, compliance rebuilds | you cannot move stateful data or afford double capacity
@check
Who backs up your application data on EKS? || You do. AWS operates the control plane and etcd, but volumes and databases need your own snapshots or backups.
@end
