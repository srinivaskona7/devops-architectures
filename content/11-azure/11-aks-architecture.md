---
title: AKS architecture, modes, node pools and networking
minutes: 60
objectives:
  - Compare AKS Standard and AKS Automatic and map AKS to EKS
  - Design system and user node pools with zones, autoscaling and Spot
  - Choose between kubenet, Azure CNI Overlay and Azure CNI Pod Subnet
---
You already run Kubernetes on Kyma and EKS. This page is about what Azure manages for you, what it leaves to you and the decisions that are hard to change later.
@concept AKS compared with EKS
@plain
**AKS** is Azure's managed Kubernetes. Microsoft runs the control plane free of charge on the Free tier, while you pay for the nodes.
@problem
Running the control plane (etcd, API server) yourself is heavy and risky.
@does
- **AWS equivalent**: EKS.
- **Main difference**: AKS has tiers: Free (no SLA), Standard (uptime SLA, recommended for production) and Premium (long-term support). The control plane fee exists on Standard. Node pools are scale sets, not managed node groups with launch templates. Identity integration uses Entra ID and Azure RBAC.
- Nodes live in a separate **node resource group** (`MC_...`) that AKS manages; do not edit its resources by hand.
- Kubernetes versions follow the upstream cadence with a support window; check `az aks get-versions`.
@diagram layers
caption: Who runs what
layers:
  - {label: "Microsoft managed", nodes: ["API server|HA, SLA on Standard|cp", "etcd|managed|cp", "Scheduler and controllers|managed|cp"]}
  - {label: "Shared", nodes: ["Node images|Microsoft supplies, you schedule upgrades|warn"]}
  - {label: "You manage", nodes: ["Node pools|size, count, zones|app", "Workloads|deployments, policies|app"]}
@h Create a cluster
```bash title="Minimal Standard cluster" lab
az aks create -g rg-shop-prod -n aks-shop-prod --tier standard --location westeurope \
  --node-count 3 --zones 1 2 3 --network-plugin azure --network-plugin-mode overlay \
  --enable-managed-identity --enable-oidc-issuer --enable-workload-identity --generate-ssh-keys
az aks get-credentials -g rg-shop-prod -n aks-shop-prod
kubectl get nodes -o wide
```
@check
What is the node resource group? || The managed group, named MC_..., that holds the cluster's VM scale sets, load balancers and disks.
@end

@concept AKS Standard versus AKS Automatic
@plain
**AKS Standard** gives you control of node pools and add-ons. **AKS Automatic** is an opinionated mode where Azure also manages node provisioning, scaling, networking defaults and guardrails.
@problem
Many teams spend most of their effort on node pool sizing, upgrades and security baselines rather than on their applications.
@does
- **AWS equivalent**: EKS Auto Mode compared with standard EKS (managed node groups, Karpenter).
- **Main difference**: Automatic enables Node Auto Provisioning (Karpenter based), Azure CNI Overlay with Cilium, managed Prometheus, Workload Identity, Deployment Safeguards (policy), automatic upgrades and managed ingress options by default. You cannot freely change many settings.
- Standard is better for custom networking, unusual node images or legacy needs.
- Region and feature availability changes; check the current docs.
@diagram cmp
caption: Choosing the mode
cards:
  - {h: "Standard", kind: info, items: ["You choose pools and CNI", "Full add-on control", "More operations work"]}
  - {h: "Automatic", kind: ok, items: ["Node Auto Provisioning", "Safeguards on by default", "Opinionated, less choice"]}
@choose Pick a mode
AKS Automatic | new product teams that want a safe default and less operations | you need custom node images, host-level agents or special CNI
AKS Standard | platform teams with their own baselines and GitOps | you want Azure to own upgrades and scaling decisions
@h Create an Automatic cluster
```bash title="AKS Automatic" lab
az aks create -g rg-shop-prod -n aks-auto --sku automatic --location westeurope --generate-ssh-keys
az aks show -g rg-shop-prod -n aks-auto --query '{sku:sku.name,tier:sku.tier,upgrade:autoUpgradeProfile.upgradeChannel}' -o json
```
@end

@concept System and user node pools
@plain
A **system pool** runs critical add-ons such as CoreDNS and metrics-server. **User pools** run your applications.
@problem
Application load can starve cluster components if they share the same nodes.
@does
- **AWS equivalent**: managed node groups (a tainted group for system add-ons is a common pattern).
- **Main difference**: AKS enforces at least one system pool. System pools carry the taint `CriticalAddonsOnly=true:NoSchedule` when you add it. Pools can differ in VM size, OS (Linux, Windows), Ubuntu or Azure Linux image, zones and labels.
- Use at least 3 nodes across zones in the system pool in production.
- Node Auto Provisioning (Karpenter style) may replace pools in Automatic.
@diagram layers
caption: Pool design
layers:
  - {label: "System pool", nodes: ["3 x D4s_v5|zones 1 2 3|cp", "CoreDNS, konnectivity, metrics|taint CriticalAddonsOnly|info"]}
  - {label: "User pools", nodes: ["apps|autoscaling 3 to 20|app", "spot|batch, tolerates eviction|warn", "gpu|optional|plain"]}
@h Add a user pool
```bash title="Node pools" lab
az aks nodepool add -g rg-shop-prod --cluster-name aks-shop-prod -n apps --mode User --node-count 3 \
  --node-vm-size Standard_D4s_v5 --zones 1 2 3 --enable-cluster-autoscaler --min-count 3 --max-count 20 --labels workload=apps
az aks nodepool list -g rg-shop-prod --cluster-name aks-shop-prod -o table
```
@check
Which pool should run your application pods, system or user? || User pools. System pools are for cluster add-ons.
@end

@concept Cluster autoscaler and Node Auto Provisioning
@plain
The **cluster autoscaler** changes the node count within each pool. **Node Auto Provisioning (NAP)** picks VM sizes on demand without pre-defined pools.
@problem
Pods stay Pending when nodes are full, and idle nodes waste money.
@does
- **AWS equivalent**: Cluster Autoscaler and Karpenter.
- **Main difference**: the autoscaler is per node pool with `--min-count` and `--max-count`. NAP is Karpenter-based and uses `NodePool` and `AKSNodeClass` custom resources.
- Tune `balance-similar-node-groups` and `scale-down-unneeded-time` through the cluster autoscaler profile.
- Pods need accurate resource requests for either to work well.
@diagram flow
caption: Scale up path
nodes:
  - "Pod Pending|no capacity|warn"
  - "Autoscaler or NAP|decides|cp"
  - "New VM|joins the pool|env"
  - "Pod scheduled|running|ok"
@h Tune the autoscaler profile
```bash title="Autoscaler profile" lab
az aks update -g rg-shop-prod -n aks-shop-prod --cluster-autoscaler-profile \
  scale-down-unneeded-time=10m balance-similar-node-groups=true expander=least-waste
kubectl get nodes -L agentpool,topology.kubernetes.io/zone
```
@end

@concept Networking models kubenet Azure CNI Overlay and Pod Subnet
@plain
The network plugin decides where pods get IP addresses.
@problem
Pods that consume VNet addresses exhaust your address space quickly; pods on an overlay do not.
@does
- **AWS equivalent**: AWS VPC CNI (pod IPs from the VPC) versus overlay options like Cilium overlay.
- **Main difference**: **Azure CNI Overlay** gives nodes VNet IPs and pods IPs from a private overlay CIDR, so large clusters need few VNet addresses. **Azure CNI Pod Subnet** gives pods VNet IPs from a dedicated subnet. **kubenet** is the legacy option and is being retired; check the current docs. Traditional Azure CNI preallocates pod IPs per node.
- Overlay pods are not directly routable from outside the cluster; reach them through Services or ingress.
- Use the **Cilium dataplane** for eBPF and network policy.
@diagram cmp
caption: CNI choices
cards:
  - {h: "CNI Overlay", kind: ok, items: ["Pods use overlay CIDR", "Saves VNet IPs", "Default recommendation"]}
  - {h: "CNI Pod Subnet", kind: info, items: ["Pods get VNet IPs", "Direct reach from VNet", "Needs big subnet"]}
  - {h: "kubenet", kind: bad, items: ["Legacy route table model", "Retiring", "Avoid for new clusters"]}
@h Overlay with Cilium
```bash title="Overlay and Cilium" lab
az aks create -g rg-shop-prod -n aks-cilium --network-plugin azure --network-plugin-mode overlay \
  --pod-cidr 192.168.0.0/16 --network-dataplane cilium --network-policy cilium --generate-ssh-keys
```
@check
What is the main benefit of CNI Overlay? || Pods do not consume VNet IP addresses, so a small subnet supports large clusters.
@end

@concept Private clusters, egress and outbound types
@plain
A **private cluster** exposes the API server on a private IP. The **outbound type** decides how nodes reach the internet.
@problem
A public API endpoint is an attack surface, and uncontrolled egress hides data exfiltration.
@does
- **AWS equivalent**: EKS private endpoint access and egress through NAT or a firewall.
- **Main difference**: outbound types are `loadBalancer` (default), `managedNATGateway`, `userAssignedNATGateway` and `userDefinedRouting` (to a firewall). API server VNet integration is another option that avoids private link; check current docs.
- A private API needs a private DNS zone and a network path from your CI runners (self-hosted agents in the VNet) or `az aks command invoke`.
- Authorized IP ranges can restrict a public API server instead.
@diagram flow
caption: Private API access
nodes:
  - "Engineer or runner|VNet or VPN|ext"
  - "Private DNS|privatelink.westeurope.azmk8s.io|info"
  - "API server private IP|in your VNet|cp"
  - "Nodes|egress by NAT or firewall|app"
@h Private cluster and run a command
```bash title="Private cluster" lab
az aks create -g rg-shop-prod -n aks-private --enable-private-cluster --outbound-type managedNATGateway \
  --vnet-subnet-id "$(az network vnet subnet show -g rg-shop-prod --vnet-name vnet-shop -n snet-aks --query id -o tsv)" --generate-ssh-keys
az aks command invoke -g rg-shop-prod -n aks-private --command "kubectl get pods -A"
```
@end

@concept Storage classes on AKS
@plain
AKS ships CSI drivers for Azure Disk, Azure Files and Blob, with ready storage classes.
@problem
Stateful pods need volumes that follow them across nodes and zones.
@does
- **AWS equivalent**: EBS CSI, EFS CSI, Mountpoint for S3.
- **Main difference**: `managed-csi` (StandardSSD LRS) and `managed-csi-premium` are disk classes. Zone-aware disks are ReadWriteOnce and tied to a zone; use ZRS disks (`StandardSSD_ZRS`, `Premium_ZRS`) so a pod can move across zones. Azure Files classes give ReadWriteMany.
- `volumeBindingMode: WaitForFirstConsumer` avoids creating a disk in the wrong zone.
- Snapshots are supported through the CSI snapshot controller.
@diagram cmp
caption: Which volume
cards:
  - {h: "Azure Disk", kind: app, items: ["ReadWriteOnce", "Zonal unless ZRS", "Databases"]}
  - {h: "Azure Files", kind: info, items: ["ReadWriteMany", "SMB or NFS", "Shared content"]}
  - {h: "Blob CSI", kind: warn, items: ["Object as files", "Read heavy data", "Not POSIX complete"]}
@h A ZRS premium class
```yaml title="storageclass-zrs.yaml"
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: premium-zrs
provisioner: disk.csi.azure.com
parameters:
  skuName: Premium_ZRS
reclaimPolicy: Delete
allowVolumeExpansion: true
volumeBindingMode: WaitForFirstConsumer
```
@check
Why use ZRS disks on a zonal cluster? || A pod can reattach its disk in another zone after a zone failure.
@end

@concept Cluster access and Azure RBAC for Kubernetes
@plain
You can sign in to AKS with Entra ID and authorise inside the cluster with Azure RBAC role assignments or with Kubernetes RBAC bound to Entra groups.
@problem
Local cluster admin certificates are shared secrets with no audit trail.
@does
- **AWS equivalent**: EKS access entries and aws-auth mapping.
- **Main difference**: enable `--enable-aad`, `--enable-azure-rbac` and disable local accounts with `--disable-local-accounts`. Built-in roles include `Azure Kubernetes Service RBAC Reader/Writer/Admin/Cluster Admin`. Kubelogin converts the Entra token for kubectl.
- Assign roles to groups at cluster or namespace scope.
- Cluster User Role is only for downloading kubeconfig.
@diagram seq
caption: kubectl with Entra
actors: ["kubectl|kubelogin plugin|app", "Entra ID|issues token|ext", "API server|Azure RBAC check|cp"]
steps:
  - "0>1: get token for AKS server app | req"
  - "1>0: token | resp"
  - "0>2: request with bearer token | tls"
  - "2>0: allowed or forbidden | resp"
@h Enable Entra and Azure RBAC
```bash title="Entra integration" lab
az aks update -g rg-shop-prod -n aks-shop-prod --enable-aad --enable-azure-rbac --disable-local-accounts
az role assignment create --assignee-object-id "$GID" --assignee-principal-type Group \
  --role "Azure Kubernetes Service RBAC Writer" --scope "$(az aks show -g rg-shop-prod -n aks-shop-prod --query id -o tsv)/namespaces/shop"
kubelogin convert-kubeconfig -l azurecli
```
@end
