---
title: GKE in depth
minutes: 75
objectives:
  - Choose between Autopilot and Standard clusters and size node pools sensibly
  - Plan upgrades with release channels, maintenance windows and surge settings
  - Use Gateway API, Dataplane V2, Workload Identity Federation for GKE, Binary Authorization and Config Connector
---
GKE is the part of Google Cloud closest to what you already run on EKS. The differences are in how much Google manages, how upgrades are scheduled and how identity is wired to Pods.

@concept Autopilot versus Standard
@plain
**Autopilot** manages the nodes for you and bills per Pod resource request. **Standard** gives you node pools to manage and bills for the VMs.
@problem
Node operations (sizing, patching, bin packing) take time, yet some workloads need full node control.
@does
- Autopilot: Google provisions and upgrades nodes, enforces hardened defaults, and charges for requested CPU, memory and ephemeral storage. Some node-level features (privileged Pods, host access, certain DaemonSets) are restricted. Check the current restrictions.
- Standard: you pick machine types, GPUs, Spot, taints, custom images and kernel settings; you pay for the VMs whether full or not.
- Both are regional or zonal clusters; use regional for production control plane availability.
- **AWS equivalent**: EKS with managed node groups (Standard) and EKS Auto Mode or Fargate (Autopilot). Main difference: Autopilot is the recommended default for most new clusters.
@diagram cmp
caption: Two operating modes
cards:
  - {h: "Autopilot", kind: ok, items: ["Google manages nodes", "Pay per Pod request", "Hardened defaults", "Some node restrictions"]}
  - {h: "Standard", kind: info, items: ["You manage node pools", "Pay for VMs", "Full node access", "Custom machine and GPU choice"]}
@choose Choosing a mode
Autopilot | most application platforms and teams without node expertise | you need privileged host access or unsupported node features
Standard | custom kernels, special hardware, tight bin-packing cost control | you want the least operational work
@h Create each
```bash title="Autopilot and Standard" lab
gcloud container clusters create-auto shop-auto --region=europe-west1 \
  --network=shop-net --subnetwork=shop-ew1 --release-channel=regular
gcloud container clusters create shop-std --region=europe-west1 --num-nodes=1 \
  --network=shop-net --subnetwork=shop-ew1 --release-channel=regular \
  --enable-ip-alias --cluster-secondary-range-name=pods --services-secondary-range-name=services \
  --enable-private-nodes --workload-pool=shop-dev-123456.svc.id.goog
```
@check
In Autopilot what do you pay for? || The CPU, memory and storage requested by your Pods.
@end

@concept Cluster networking choices and private clusters
@plain
GKE clusters are **VPC-native**: Pods and Services get IPs from secondary ranges of the subnet. Nodes can be **private** (no external IPs).
@problem
Pod IP exhaustion and exposed control planes are the two common production problems.
@does
- Plan the Pod range (for example a /14) and Service range up front. Default max Pods per node is 110 in Standard, with smaller ranges per node.
- **Private nodes** need Cloud NAT for outbound access. The control plane is reachable through a public endpoint (restricted by **authorized networks**), a private endpoint, or DNS-based endpoint access; check current options.
- Control plane connects to the VPC using Private Service Connect in newer clusters.
- **AWS equivalent**: EKS with VPC CNI and endpoint access settings. Main difference: Pods use alias IP ranges, not ENIs, so there is no per-node ENI limit on Pod count.
@diagram layers
caption: Address plan
layers:
  - {label: "Subnet", nodes: ["Node range|10.10.0.0/20|info"]}
  - {label: "Secondary ranges", nodes: ["Pods|10.64.0.0/14|app", "Services|10.68.0.0/20|app"]}
  - {label: "Control plane", nodes: ["Endpoint|authorized networks|cp"]}
@h Restrict the endpoint
```bash title="Authorized networks" lab
gcloud container clusters update shop-std --region=europe-west1 \
  --enable-master-authorized-networks --master-authorized-networks=203.0.113.0/24
gcloud container clusters get-credentials shop-std --region=europe-west1
```
@end

@concept Node pools and node auto-provisioning
@plain
A **node pool** is a group of nodes with the same configuration. **Node auto-provisioning (NAP)** creates and deletes node pools automatically to fit pending Pods.
@problem
Fixed pools waste money or block Pods that need different shapes, such as GPU or high memory.
@does
- Pools have machine type, disk, labels, taints, Spot flag, and autoscaling bounds (`--min-nodes`, `--max-nodes`).
- The cluster autoscaler adds nodes for pending Pods and removes underused ones. Use `--location-policy=BALANCED` or `ANY` (ANY is helpful for Spot).
- NAP picks machine families from resource limits you set (`--max-cpu`, `--max-memory`); custom compute classes (ComputeClass) express preferences and fallbacks. Check the current docs.
- **AWS equivalent**: managed node groups with Cluster Autoscaler or Karpenter. Main difference: NAP and ComputeClass fill the role of Karpenter.
@diagram flow
caption: Pending Pod to new node
nodes:
  - "Pending Pod|needs 8 vCPU|warn"
  - "Autoscaler|no fit in pools|cp"
  - "Provision|new pool or node|info"
  - "Pod runs|scheduled|ok"
@h Pools and NAP
```bash title="Node pool and NAP" lab
gcloud container node-pools create spot-pool --cluster=shop-std --region=europe-west1 \
  --machine-type=e2-standard-4 --spot --enable-autoscaling --min-nodes=0 --max-nodes=5 \
  --node-taints=workload=batch:NoSchedule
gcloud container clusters update shop-std --region=europe-west1 \
  --enable-autoprovisioning --min-cpu=1 --max-cpu=64 --min-memory=1 --max-memory=256
```
@check
What does NAP add compared with a fixed autoscaled pool? || It creates new pools with suitable machine shapes on demand.
@end

@concept Release channels and cluster upgrades
@plain
A **release channel** (Rapid, Regular, Stable, Extended) controls which Kubernetes versions your cluster gets and how fast. Google upgrades the control plane and, by default, auto-upgrades nodes.
@problem
Kubernetes releases every few months and unpatched clusters go out of support.
@does
- Rapid: newest versions first. Regular: the default balance. Stable: most validated. Extended: longer support at extra cost for selected versions. Check the current version table.
- Control plane upgrades are done by Google within maintenance windows and exclusions; node upgrades follow.
- Control plane is regional and stays available during upgrades in regional clusters; zonal control planes have short API downtime.
- Use maintenance windows and exclusions to avoid upgrades during peak events.
- **AWS equivalent**: EKS version support with manual upgrades. Main difference: upgrades are automatic unless you postpone them, and channels pick the cadence.
@diagram flow
caption: Version flow
nodes:
  - "Rapid|first release|warn"
  - "Regular|default|ok"
  - "Stable|most validated|info"
  - "Extended|longer support|env"
@h Windows and exclusions
```bash title="Maintenance control" lab
gcloud container clusters update shop-std --region=europe-west1 \
  --maintenance-window-start=2026-11-07T21:00:00Z --maintenance-window-end=2026-11-08T03:00:00Z \
  --maintenance-window-recurrence="FREQ=WEEKLY;BYDAY=SA,SU"
gcloud container clusters update shop-std --region=europe-west1 \
  --add-maintenance-exclusion-name=black-friday \
  --add-maintenance-exclusion-start=2026-11-20T00:00:00Z --add-maintenance-exclusion-end=2026-12-02T00:00:00Z
gcloud container get-server-config --region=europe-west1 --format="yaml(channels)"
```
:::warn
Exclusion scope and maximum length depend on the release channel. Check the current docs.
:::
@end

@concept Node upgrade strategies
@plain
Node upgrades replace nodes. **Surge upgrades** add extra nodes first; **blue-green upgrades** keep the old pool until the new one is ready.
@problem
Replacing nodes evicts Pods, which can break availability if not controlled.
@does
- Surge settings per pool: `--max-surge-upgrade` and `--max-unavailable-upgrade`. Default is one surge node and zero unavailable.
- Blue-green keeps old nodes for a soak period so you can roll back, at the cost of double capacity for a while.
- Pod Disruption Budgets, `terminationGracePeriodSeconds` and readiness probes decide how safely Pods move.
- Manual upgrades: `gcloud container clusters upgrade`.
- **AWS equivalent**: managed node group rolling update with `maxUnavailable`. Main difference: blue-green is built in.
@diagram flow
caption: Surge upgrade
numbered: true
nodes:
  - "Add surge node|new version|info"
  - "Cordon and drain|old node|warn"
  - "Pods reschedule|respect PDB|ok"
  - "Delete old node|repeat|app"
@h Configure
```bash title="Surge settings" lab
gcloud container node-pools update default-pool --cluster=shop-std --region=europe-west1 \
  --max-surge-upgrade=2 --max-unavailable-upgrade=0
gcloud container clusters upgrade shop-std --region=europe-west1 --master --cluster-version={{v.gke_to}}
```
```yaml title="pdb.yaml"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: shop-api
spec:
  minAvailable: 2
  selector:
    matchLabels:
      app: shop-api
```
@check
What stops a node drain from taking all replicas down at once? || A Pod Disruption Budget.
@end

@concept Gateway API on GKE
@plain
**Gateway API** is the Kubernetes standard for ingress traffic. GKE provides GatewayClasses that create Google Cloud load balancers from `Gateway` and `HTTPRoute` objects.
@problem
Ingress is limited and annotation-heavy. Gateway API separates infrastructure (platform team) from routes (app teams).
@does
- GatewayClasses include `gke-l7-global-external-managed`, `gke-l7-regional-external-managed`, `gke-l7-rilb` and multi-cluster classes. Check the current list.
- `Gateway` defines listeners and addresses; `HTTPRoute` binds paths and hosts to Services with weights; `HealthCheckPolicy`, `GCPBackendPolicy` and `GCPGatewayPolicy` tune the backend.
- Container-native load balancing uses NEGs, so traffic goes straight to Pods.
- **AWS equivalent**: AWS Load Balancer Controller with Ingress or Gateway API. Main difference: it is fully managed in the cluster with no controller to install.
@diagram flow
caption: Gateway to load balancer
nodes:
  - "Gateway|listener and class|cp"
  - "HTTPRoute|host and path|info"
  - "Service and NEG|Pod endpoints|app"
  - "Google LB|created for you|ok"
@h Gateway and route
```yaml title="gateway.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shop-gw
  namespace: shop
spec:
  gatewayClassName: gke-l7-global-external-managed
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      tls:
        mode: Terminate
        options:
          networking.gke.io/cert-manager-certs: shop-cert
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop-route
  namespace: shop
spec:
  parentRefs:
    - name: shop-gw
  hostnames: ["shop.example.com"]
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api
      backendRefs:
        - name: api
          port: 8080
    - backendRefs:
        - name: web
          port: 80
```
@end

@concept Dataplane V2 and network policy
@plain
**Dataplane V2** is GKE's networking dataplane based on Cilium and eBPF. It enforces Kubernetes NetworkPolicy and offers logging.
@problem
Older iptables-based policy enforcement scales poorly and gives little visibility.
@does
- Enabled at cluster creation with `--enable-dataplane-v2`; it is the default for Autopilot. No Calico install needed.
- Supports standard NetworkPolicy, plus network policy logging, FQDN network policies (check current availability) and Hubble-based observability in some configurations.
- Cannot be switched on later for an existing cluster in the general case; plan ahead.
- **AWS equivalent**: VPC CNI network policy support or Cilium on EKS. Main difference: it is built in and supported by Google.
@diagram flow
caption: eBPF policy path
nodes:
  - "Pod A|client|app"
  - "eBPF program|allow or drop|cp"
  - "Pod B|server|app"
  - "Policy log|denied flows|info"
@h Default deny plus allow
```yaml title="networkpolicy.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow-web
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
```bash title="Create with Dataplane V2" lab
gcloud container clusters create shop-dp2 --region=europe-west1 --enable-dataplane-v2 --enable-ip-alias
```
@check
Which technology powers Dataplane V2? || Cilium with eBPF.
@end

@concept Workload Identity Federation for GKE
@plain
**Workload Identity Federation for GKE** lets Kubernetes service accounts access Google Cloud APIs without keys. It replaces node service account sharing and downloaded JSON keys.
@problem
Pods on a node share the node's identity unless you give each workload its own.
@does
- Enable the workload pool `PROJECT_ID.svc.id.goog` on the cluster (default on Autopilot) and `GKE_METADATA` on node pools.
- Current approach: grant IAM roles **directly to the Kubernetes service account** principal, for example `principal://iam.googleapis.com/projects/NUM/locations/global/workloadIdentityPools/PROJECT.svc.id.goog/subject/ns/NAMESPACE/sa/KSA`. The older approach binds a Google service account with `roles/iam.workloadIdentityUser` and annotates the KSA.
- Not every Google API supports direct principal access; check the docs and fall back to the annotation method.
- **AWS equivalent**: IRSA or EKS Pod Identity. Main difference: no OIDC provider setup per cluster; the pool is built in.
@diagram seq
caption: Pod calls a Google API
actors: ["Pod|KSA shop-api|app", "GKE metadata|node proxy|cp", "STS|token exchange|cp", "Google API|storage|ext"]
steps:
  - "0>1: ask for token | req"
  - "1>2: exchange KSA token | tls"
  - "2>1: federated token | resp"
  - "0>3: call with token | tls"
@h Grant a role to a KSA
```bash title="Direct principal binding" lab
PROJECT_NUMBER=$(gcloud projects describe shop-dev-123456 --format="value(projectNumber)")
gcloud projects add-iam-policy-binding shop-dev-123456 \
  --role="roles/storage.objectUser" \
  --member="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/shop-dev-123456.svc.id.goog/subject/ns/shop/sa/shop-api"
kubectl create serviceaccount shop-api -n shop
```
@end

@concept Binary Authorization, Config Connector and GKE Enterprise
@plain
**Binary Authorization** only admits signed or attested images. **Config Connector** manages Google Cloud resources as Kubernetes objects. **GKE Enterprise** adds fleet management, policy and service mesh across clusters.
@problem
Untrusted images, drift between clusters and cloud resources, and managing many clusters need extra controls.
@does
- Binary Authorization: a policy lists required attestors (for example the build system) and default rules; enable with `--binauthz-evaluation-mode=PROJECT_SINGLETON_POLICY_ENFORCE`. Use dry-run mode first.
- Config Connector: install as a GKE add-on, then apply objects such as `SQLInstance` or `StorageBucket`; it reconciles them like Crossplane or AWS ACK.
- GKE Enterprise (a paid tier, check current packaging) includes fleets, Config Sync (GitOps), Policy Controller (OPA Gatekeeper), Cloud Service Mesh and multi-cluster Gateway. Even without Enterprise, fleets and some features are available.
- **AWS equivalent**: ECR signing with admission policy, ACK, and EKS Anywhere or Argo CD. Main difference: these are Google-managed components integrated into the console.
@diagram layers
caption: Control layers
layers:
  - {label: "Supply chain", nodes: ["Binary Authorization|admit attested images|ok"]}
  - {label: "Cloud resources", nodes: ["Config Connector|CRDs for Google resources|info"]}
  - {label: "Fleet", nodes: ["Config Sync|GitOps|app", "Policy Controller|guardrails|app", "Service mesh|mTLS and traffic|app"]}
@h Config Connector resource
```yaml title="bucket.yaml"
apiVersion: storage.cnrm.cloud.google.com/v1beta1
kind: StorageBucket
metadata:
  name: shop-uploads-123
  namespace: shop
  annotations:
    cnrm.cloud.google.com/project-id: shop-dev-123456
spec:
  location: EUROPE-WEST1
  uniformBucketLevelAccess: true
  versioning:
    enabled: true
```
```bash title="Enable features" lab
gcloud container clusters update shop-std --region=europe-west1 \
  --binauthz-evaluation-mode=PROJECT_SINGLETON_POLICY_ENFORCE
gcloud container clusters update shop-std --region=europe-west1 --update-addons=ConfigConnector=ENABLED
```
:::note
Add-on flags change between versions. Check `gcloud container clusters update --help` for your version.
:::
@check
What should you use first when rolling out Binary Authorization? || Dry-run mode, to see violations without blocking.
@end
