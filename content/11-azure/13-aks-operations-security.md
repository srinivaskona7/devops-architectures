---
title: AKS upgrades, scaling, policy and Defender
minutes: 60
objectives:
  - Configure upgrade channels, node image updates and maintenance windows
  - Scale workloads with HPA and KEDA
  - Apply Azure Policy for AKS, network policy and Microsoft Defender for Containers
---
Day two on AKS is mostly upgrades, scaling and guardrails. Azure gives you managed options for each; this page shows how they differ from what you know on EKS.

@concept Kubernetes version upgrades and channels
@plain
AKS supports a rolling window of Kubernetes minor versions. An **auto-upgrade channel** tells AKS when to move the cluster for you.
@problem
Running an unsupported version means no patches and no support, while manual upgrades get forgotten.
@does
- **AWS equivalent**: EKS version upgrades (manual) with extended support for older versions at extra cost.
- **Main difference**: channels are `none`, `patch`, `stable`, `rapid` and `node-image`. `patch` keeps the minor version and applies the latest patch; `stable` follows N-1 minor; `rapid` follows the newest. Check the current docs for exact semantics and the support policy (including the long-term support option on the Premium tier).
- An upgrade surges extra nodes (`max-surge`), cordons and drains old ones, respecting PodDisruptionBudgets.
- Control plane first, then node pools.
@diagram flow
caption: Upgrade sequence
nodes:
  - "Control plane|upgraded first|cp"
  - "Surge node|added to the pool|env"
  - "Cordon and drain|respects PDBs|warn"
  - "Old node removed|repeat per node|ok"
@h Check and upgrade
```bash title="Upgrade" lab
az aks get-upgrades -g rg-shop-prod -n aks-shop-prod -o table
az aks nodepool update -g rg-shop-prod --cluster-name aks-shop-prod -n apps --max-surge 33%
az aks update -g rg-shop-prod -n aks-shop-prod --auto-upgrade-channel patch
az aks upgrade -g rg-shop-prod -n aks-shop-prod --kubernetes-version {{v.aks_to}}
```
:::tip
Replace the version with one returned by `az aks get-upgrades`. After any drain based work, check that no node stays cordoned: `kubectl get nodes`.
:::
@check
Which channel keeps the minor version and only applies patches? || patch.
@end

@concept Node image upgrades and maintenance windows
@plain
Node images (Ubuntu or Azure Linux) get security fixes weekly. A **maintenance configuration** says when AKS may replace nodes.
@problem
Unpatched nodes are vulnerable, but replacing them at peak hours hurts users.
@does
- **AWS equivalent**: managed node group AMI updates and EC2 Image Builder pipelines.
- **Main difference**: node image upgrades are separate from Kubernetes upgrades. Channels `NodeImage` or `SecurityPatch` automate them. `aksManagedAutoUpgradeSchedule` and `aksManagedNodeOSUpgradeSchedule` are the two maintenance configurations, one per channel.
- Unattended OS upgrades on Ubuntu nodes can reboot nodes; kured or the node OS channel manages that. Check current docs.
- Always set PodDisruptionBudgets and `topologySpreadConstraints`.
@diagram layers
caption: Two upgrade tracks
layers:
  - {label: "Kubernetes version", nodes: ["Cluster auto upgrade|channel patch or stable|cp"]}
  - {label: "Node OS", nodes: ["Node OS channel|NodeImage or SecurityPatch|info"]}
  - {label: "When", nodes: ["Maintenance window|weekday and hours|ok"]}
@h Weekly window
```bash title="Maintenance configuration" lab
az aks maintenanceconfiguration add -g rg-shop-prod --cluster-name aks-shop-prod -n aksManagedNodeOSUpgradeSchedule \
  --schedule-type Weekly --day-of-week Sunday --interval-weeks 1 --start-time 02:00 --duration 4 --utc-offset +00:00
az aks update -g rg-shop-prod -n aks-shop-prod --node-os-upgrade-channel NodeImage
```
@end

@concept Pod disruption budgets and safe drains
@plain
A **PodDisruptionBudget (PDB)** limits how many replicas can be down during voluntary disruptions such as upgrades.
@problem
A drain with no PDB can evict all replicas at once, and a PDB that is too strict blocks upgrades forever.
@does
- **AWS equivalent**: the same Kubernetes object on EKS.
- **Main difference**: AKS upgrades wait on PDBs for a limited time (the drain timeout, default 30 minutes) and then fail rather than evict by force; the `undrainable-node-behavior` setting controls this. Check current docs.
- Use `maxUnavailable: 1` for most stateless Services.
- Verify nothing remains cordoned after a failed upgrade.
@diagram flow
caption: Drain meets PDB
nodes:
  - "Drain starts|evict pods|warn"
  - "PDB check|minAvailable met|cp"
  - "Evicted|pod rescheduled|ok"
  - "Blocked|upgrade waits then fails|bad"
@h Example PDB
```yaml title="pdb-api.yaml"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: api
  namespace: shop
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: api
```
```bash title="Safety checks" lab
kubectl get pdb -A
kubectl get nodes | grep -i SchedulingDisabled || echo "no cordoned nodes"
```
@check
What happens if a PDB never allows an eviction? || The drain stalls and the upgrade eventually fails.
@end

@concept HPA, VPA and KEDA
@plain
**HPA** scales pods on CPU or memory. **VPA** adjusts requests. **KEDA** scales on external events such as queue length and can scale to zero.
@problem
CPU is a poor signal for queue workers and event consumers, and idle workers waste nodes.
@does
- **AWS equivalent**: HPA plus KEDA on EKS, or ECS service auto scaling on queue depth.
- **Main difference**: AKS has a managed **KEDA add-on** (`--enable-keda`) with Azure scalers for Service Bus, Storage Queue, Event Hubs, Azure Monitor, Prometheus and Redis. Authentication through workload identity with `TriggerAuthentication`.
- KEDA creates and drives an HPA under the hood.
- Pair with cluster autoscaler or NAP so nodes follow pods.
@diagram flow
caption: Event driven scaling
nodes:
  - "Queue or metric|Service Bus, Redis|ext"
  - "KEDA scaler|polls the source|cp"
  - "HPA|desired replicas|info"
  - "Deployment|zero to N pods|app"
@h ScaledObject on a Redis list
```bash title="Enable KEDA" lab
az aks update -g rg-shop-prod -n aks-shop-prod --enable-keda
kubectl get pods -n kube-system | grep keda
```
```yaml title="scaledobject-worker.yaml"
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: order-worker
  namespace: shop
spec:
  scaleTargetRef:
    name: order-worker
  minReplicaCount: 0
  maxReplicaCount: 20
  cooldownPeriod: 120
  triggers:
    - type: redis
      metadata:
        address: redis-shop-prod.redis.cache.windows.net:6380
        listName: orders
        listLength: "10"
        enableTLS: "true"
      authenticationRef:
        name: redis-auth
```
@end

@concept Azure Policy for AKS
@plain
The **Azure Policy add-on** installs Gatekeeper (OPA) and syncs built-in constraints so Azure Policy can audit or deny Kubernetes objects.
@problem
Cluster admins cannot review every manifest. You need guardrails such as no privileged containers, resource limits required and only approved registries.
@does
- **AWS equivalent**: OPA Gatekeeper or Kyverno on EKS, plus Config for the cluster resource.
- **Main difference**: the compliance result shows up in the same Azure Policy dashboard as your Azure resources, and one assignment covers many clusters. Built-in initiatives include the Kubernetes Pod Security Baseline and Restricted standards.
- Custom constraint templates are allowed; Gatekeeper is still used underneath.
- AKS **Deployment Safeguards** (on by default in Automatic) enforce best practice checks as warning or enforcement.
@diagram flow
caption: Policy to Gatekeeper
nodes:
  - "Policy assignment|initiative on the cluster|cp"
  - "Policy add-on|syncs constraints|info"
  - "Gatekeeper|admission webhook|warn"
  - "Pod denied or admitted|compliance reported|ok"
@h Enable and check
```bash title="Policy add-on" lab
az aks enable-addons -g rg-shop-prod -n aks-shop-prod --addons azure-policy
kubectl get constrainttemplates 2>/dev/null | head
az policy state list --resource "$(az aks show -g rg-shop-prod -n aks-shop-prod --query id -o tsv)" \
  --query '[?complianceState==`NonCompliant`].policyDefinitionName' -o tsv
```
@check
Which engine enforces Azure Policy rules inside the cluster? || OPA Gatekeeper.
@end

@concept Network policy and namespace isolation
@plain
**NetworkPolicy** objects control pod to pod traffic. AKS supports Azure Network Policy Manager, Calico and Cilium engines.
@problem
By default every pod can reach every other pod.
@does
- **AWS equivalent**: VPC CNI network policy support, Calico or Cilium on EKS.
- **Main difference**: pick the engine at cluster creation (`--network-policy azure|calico|cilium`). Cilium (with the Cilium dataplane on CNI Overlay) is the recommended choice and adds FQDN and layer 7 policy in the advanced edition; check the current docs. Windows nodes support differs.
- Start with default deny per namespace, then add allow rules.
@diagram flow
caption: Shop traffic rules
nodes:
  - "web|can call api|app"
  - "api|can call db and redis|app"
  - "db and redis|accept only from api|env"
  - "Everything else|denied|bad"
@h Default deny and allow api to db
```yaml title="netpol-shop.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: shop
spec:
  podSelector: {}
  policyTypes: ["Ingress"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-web-to-api
  namespace: shop
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes: ["Ingress"]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: web
      ports:
        - port: 8080
```
@end

@concept Microsoft Defender for Containers
@plain
**Defender for Containers** scans images in ACR, assesses cluster configuration and detects runtime threats in AKS.
@problem
Vulnerable images, misconfigurations and compromised pods go unnoticed without continuous checks.
@does
- **AWS equivalent**: GuardDuty EKS protection, Inspector for ECR.
- **Main difference**: it is a single plan under Defender for Cloud. It deploys a sensor DaemonSet on nodes and uses Azure Policy for Kubernetes. Findings and recommendations appear in Defender for Cloud with attack paths; it also covers EKS and GKE through multicloud connectors.
- It is a paid plan, billed per vCore or per image scan; check current pricing.
- Image vulnerability assessment can block or flag deployments with admission rules.
@diagram layers
caption: What Defender covers
layers:
  - {label: "Build and registry", nodes: ["ACR image scanning|CVEs, on push and continuous|info"]}
  - {label: "Cluster posture", nodes: ["Misconfiguration checks|policy based|warn"]}
  - {label: "Runtime", nodes: ["Sensor on nodes|process and network alerts|bad"]}
@h Enable on the cluster
```bash title="Defender" lab
az aks update -g rg-shop-prod -n aks-shop-prod --enable-defender
az security pricing show -n Containers --query pricingTier -o tsv
```
@check
Where do Defender alerts for AKS appear? || In Microsoft Defender for Cloud.
@end

@concept Pod security and image admission
@plain
Pod Security Admission labels on a namespace enforce baseline or restricted pod rules, and signed image or registry allow-lists limit what runs.
@problem
Privileged pods and unknown images turn a single compromise into a cluster compromise.
@does
- **AWS equivalent**: Pod Security Admission and Kyverno on EKS, ECR image signing with Notation.
- **Main difference**: AKS removed the old Pod Security Policy. Use the built-in Pod Security Admission labels or Azure Policy initiatives. The Image Integrity add-on (Ratify) can verify Notation signatures; check the current status.
- Combine with `securityContext`: non-root, read-only root filesystem, drop all capabilities.
@diagram flow
caption: Admission layers
nodes:
  - "Manifest|kubectl or GitOps|ext"
  - "Pod Security Admission|baseline or restricted|cp"
  - "Gatekeeper|registry and limits|warn"
  - "Admitted|runs|ok"
@h Enforce restricted
```bash title="Namespace labels" lab
kubectl label namespace shop pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/warn=restricted --overwrite
kubectl get ns shop --show-labels
```
@end
