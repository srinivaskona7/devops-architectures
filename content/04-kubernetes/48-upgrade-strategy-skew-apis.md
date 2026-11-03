---
title: Upgrade strategy, version skew and deprecated APIs
minutes: 45
objectives:
  - Plan an upgrade around the release cadence and version skew rules
  - Find and fix deprecated API usage before it breaks
  - Prepare a checklist and rollback position for a control plane upgrade
---
Kubernetes ships a minor release about every four months and supports roughly the latest three. Staying current is routine work, not an event. This section covers how to plan upgrades so they stay boring.

@concept Release cadence and support windows
@plain
Kubernetes releases a new minor version (1.33, 1.34, 1.35 and so on) about three times a year. The community supports the newest three minor versions with patches. Managed services add their own windows.
@problem
A cluster left on one version falls out of security patches, add-ons stop supporting it, and a long jump later is risky because many changes arrive at once.
@does
- Upstream patch support is around 14 months per minor version. EKS standard support is 14 months, then paid extended support for a further 12 months. Gardener offers a version to Kyma and other shoots for a limited time and expires older ones, forcing an update.
- Always check the release notes "Urgent upgrade notes" and "Deprecation" sections for the target version.
- Plan a recurring slot, such as one minor upgrade per quarter, rather than reacting to end of life.
- Verify the exact supported versions in the provider console or CLI instead of relying on memory.
@diagram flow
caption: A steady upgrade rhythm
nodes:
  - "Dev cluster|upgrade first|env"
  - "Staging|a week of soak|warn"
  - "Production|scheduled window|cp"
  - "Next minor|about 4 months later|plain"
@h Checking what is available
```bash title="Versions you can use" lab
kubectl version                                                # client and server versions
kubectl get nodes -o custom-columns=NAME:.metadata.name,KUBELET:.status.nodeInfo.kubeletVersion
aws eks describe-cluster --name shop --query 'cluster.version' --output text
aws eks describe-cluster-versions --query 'clusterVersions[].{v:clusterVersion,s:status}' --output table
```
@end

@concept Version skew rules
@plain
Components of a cluster may run different minor versions, but only within strict limits. You upgrade the control plane first, then nodes, then clients.
@problem
Upgrading in the wrong order, or skipping minors, breaks API compatibility between the kubelet, the API server and your tools.
@does
- **kube-apiserver**: with several API servers (HA), they may differ by at most one minor.
- **kubelet**: may be up to **three minor versions older** than the API server (since 1.28) but never newer.
- **kube-proxy**: same as kubelet. **controller-manager and scheduler**: up to one minor older than the API server.
- **kubectl**: within one minor of the API server, either side.
- You cannot skip control plane minors; go 1.32 to 1.33 to 1.34. Nodes may be upgraded later and can skip within the allowed skew, though upgrading them every time is simpler.
@diagram layers
caption: Order of an upgrade
layers:
  - {label: "1 Control plane", nodes: ["kube-apiserver|first, one minor at a time|cp", "controller-manager and scheduler|follow|cp"]}
  - {label: "2 Nodes", nodes: ["kubelet and kube-proxy|never newer than the API server|app"]}
  - {label: "3 Add-ons and clients", nodes: ["CoreDNS, CNI, CSI, ingress|check compatibility matrix|info", "kubectl and CI tools|within one minor|plain"]}
@check
Can a kubelet be newer than the API server? || No. The kubelet must not be newer than the kube-apiserver.
Can you jump from 1.31 straight to 1.34 on the control plane? || No. Control plane upgrades go one minor version at a time.
@end

@concept Deprecated and removed APIs
@plain
Kubernetes deprecates API versions (for example `policy/v1beta1` PodDisruptionBudget) and later removes them. Manifests using a removed version stop applying, and controllers that still call it fail.
@problem
An upgrade succeeds but the next deploy, or a Helm chart, fails with "no matches for kind" because the old API version no longer exists.
@does
- Stable APIs follow a deprecation policy: GA versions are supported for at least twelve months or three releases after a replacement is announced; beta versions for about nine months.
- Objects stored in the cluster are migrated automatically to the new storage version, but your **manifests, charts and operators** are not.
- Warning headers appear in `kubectl` output ("... is deprecated in v1.xx, unavailable in v1.yy"). The metric `apiserver_requested_deprecated_apis` shows who still calls them.
- Check the deprecated API migration guide for the target version before every upgrade.
@diagram flow
caption: How an old API turns into an outage
nodes:
  - "Deprecated|warning headers only|warn"
  - "Removed in new minor|API server returns 404|bad"
  - "Deploy fails|chart or CI uses the old version|bad"
  - "Fix before upgrade|migrate manifests|ok"
@h Finding usage on a live cluster
```bash title="What still calls removed APIs" lab
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis | head
kubectl get --raw /metrics | grep 'apiserver_requested_deprecated_apis{' | grep 'removed_release="1.3'
kubectl api-resources --verbs=list -o name | head -20
kubectl convert -f old-ingress.yaml --output-version networking.k8s.io/v1   # needs the kubectl-convert plugin
```
@end

@concept Scanning with pluto and kubent
@plain
**pluto** and **kube-no-trouble (kubent)** scan manifests, Helm releases or a live cluster and report API versions that are deprecated or removed in a given Kubernetes version.
@problem
Reading release notes by hand will miss something. You want a CI check that fails when a manifest will not work on the next version.
@does
- `pluto detect-files -d manifests/ --target-versions k8s=v{{v.eks_to}}.0` scans files in a directory.
- `pluto detect-helm --target-versions k8s=v{{v.eks_to}}.0` reads releases installed through Helm, which is where hidden old versions live because the release Secret stores the old manifest.
- `pluto detect-all-in-cluster` scans several sources in the live cluster.
- `kubent` inspects the cluster and Helm 3 releases and uses the cluster version to guess the target.
- Exit codes are non-zero when findings exist, so they fit CI gates. Rendered Helm output can also go through `pluto detect -`.
@diagram flow
caption: Scanning before an upgrade
numbered: true
nodes:
  - "Repo manifests|Kustomize or Helm output|plain"
  - "Installed releases|stored in Secrets|db"
  - "pluto or kubent|compares to target version|app"
  - "Report|fix, then upgrade|ok"
@h Commands
```bash title="Pre-upgrade scan" lab
kustomize build overlays/prod | pluto detect - --target-versions k8s=v{{v.eks_to}}.0
pluto detect-helm --target-versions k8s=v{{v.eks_to}}.0 -o wide
pluto detect-files -d ./manifests --target-versions k8s=v{{v.eks_to}}.0
kubent --target-version {{v.eks_to}}
```
:::note
Pass the version you really plan to move to. Confirm the flag spelling with `pluto detect-helm --help`, because option names have changed between releases.
:::
@end

@concept Pre-upgrade checklist
@plain
A short, written checklist turns an upgrade from a risky event into a repeatable procedure.
@problem
Upgrades fail from avoidable causes: an add-on that does not support the new version, PodDisruptionBudgets that block drains, a lack of free capacity, or no recent backup.
@does
- **Compatibility**: CNI, CSI, CoreDNS, ingress controller, service mesh, cert-manager, operators and policy engines support the target version.
- **APIs**: scans above are clean; Helm chart versions are current.
- **Capacity**: enough spare CPU and memory, IP addresses in subnets (EKS), and quota so surge nodes and drained Pods fit.
- **Availability**: at least 2 replicas for important workloads and sensible PDBs; no single-replica StatefulSet with a `maxUnavailable: 0` PDB.
- **Backups**: etcd is managed on EKS and Gardener, so back up **your data**: Velero or volume snapshots, plus manifests in Git.
- **Observability**: dashboards and alerts are open during the window; a rollback or abort criterion is written down.
@diagram cmp
caption: Four areas to confirm
cards:
  - {h: "Compatibility", kind: info, items: ["Add-ons support target", "APIs scanned", "Charts updated"]}
  - {h: "Capacity", kind: warn, items: ["Spare nodes for surge", "Free IPs in subnets", "Quota headroom"]}
  - {h: "Availability", kind: ok, items: ["Replicas above one", "PDBs allow a drain", "Topology spread"]}
  - {h: "Recovery", kind: bad, items: ["Data backups tested", "Manifests in Git", "Stop criteria written"]}
@h Commands
```bash title="Readiness checks" lab
kubectl get pdb -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get nodes
kubectl top nodes
kubectl get deploy,sts -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,REPLICAS:.spec.replicas | awk '$3==1'
```
@end

@concept Upgrading the control plane
@plain
The control plane is upgraded as one operation by the provider. You start it, wait, and verify. For self-managed clusters, `kubeadm upgrade` does the same steps on each control plane node.
@problem
If the API server is replaced badly, nothing can be managed. Providers do it with rolling replacement so the API stays available, but the operation is one-way: control plane minor upgrades cannot be reversed.
@does
- EKS: `aws eks update-cluster-version` (or Terraform). The API server remains available. Add-ons are upgraded separately through managed add-on versions.
- Gardener (and Kyma on BTP): change `kubernetes.version` in the Shoot spec through the dashboard, `gardenctl` or the Kyma environment. Gardener rolls control plane first, then worker pools according to the maintenance window.
- kubeadm: `kubeadm upgrade plan`, then `kubeadm upgrade apply v{{v.eks_to}}.x` on the first control plane node, `kubeadm upgrade node` on the others, then upgrade kubelet packages.
- Verify with `kubectl version`, component health, and a test deployment.
@diagram seq
caption: EKS control plane upgrade
actors: ["Operator|CLI or Terraform|ext", "EKS|control plane|cp", "Add-ons|CoreDNS, CNI, kube-proxy|app"]
steps:
  - "0>1: update-cluster-version {{v.eks_to}} | req"
  - "note 1..1: new API servers replace old, API stays up"
  - "1>0: status Successful | resp"
  - "0>2: update managed add-on versions | req"
  - "0>1: nodes still old, within skew | warn"
@h Commands
```bash title="EKS control plane" lab
aws eks update-cluster-version --name shop --kubernetes-version {{v.eks_to}}
aws eks describe-update --name shop --update-id UPDATE_ID --query 'update.status'
aws eks list-addons --cluster-name shop
aws eks describe-addon-versions --addon-name coredns --kubernetes-version {{v.eks_to}} --query 'addons[0].addonVersions[0].addonVersion'
aws eks update-addon --cluster-name shop --addon-name coredns --addon-version vX.Y.Z-eksbuild.N
```
@end
