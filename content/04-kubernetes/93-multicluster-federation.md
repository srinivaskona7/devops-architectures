---
title: Multi-cluster and federation
minutes: 50
objectives:
  - Choose between one large cluster and several smaller clusters
  - Connect clusters with service discovery, mesh and Cilium Cluster Mesh
  - Distribute workloads with Karmada or Argo CD and plan failover
---
Multiple clusters give isolation and resilience, but add networking, identity and deployment problems. This page covers the main patterns and their costs.

@concept Why more than one cluster
@plain
Teams use several clusters for blast radius, regional placement, compliance boundaries, separate environments and independent upgrades.
@problem
One huge cluster means one failed upgrade, one noisy neighbour or one misconfigured admission webhook can hurt everyone.
@does
- Reasons for many: failure isolation, data residency, per-tenant hard isolation, upgrade canaries, latency to users.
- Reasons for few: lower operating cost, easier sharing of capacity, less networking complexity.
- Namespaces and quotas give soft isolation; clusters (or vcluster) give hard isolation.
- A common compromise: per environment and per region clusters, shared by teams through namespaces.
@diagram cmp
caption: One versus many
cards:
  - {h: "Few big clusters", kind: info, items: ["Efficient use", "Simple networking", "Large blast radius"]}
  - {h: "Many small clusters", kind: ok, items: ["Strong isolation", "Independent upgrades", "More to operate"]}
@choose Isolation level
Namespace plus policy | trusted teams in one company | tenants are hostile or regulated differently
Virtual cluster | teams need their own API and CRDs | you need hardware isolation
Separate cluster | compliance, region or blast radius | cost and operations are the main constraint
@end

@concept Cross-cluster service discovery
@plain
By default a Service name resolves only inside its cluster. Multi-cluster discovery makes a service in another cluster reachable by name.
@problem
Applications spread over regions or clusters should not hard-code external load balancer addresses.
@does
- **MCS API** (`ServiceExport` and `ServiceImport`) is the Kubernetes standard: export a Service, and others see `name.namespace.svc.clusterset.local`. Implementations include Submariner, Cilium Cluster Mesh and some cloud products.
- Meshes (Istio multi-cluster, Linkerd multicluster) provide cross-cluster routing with mTLS and failover.
- Plain DNS plus global load balancers also work for north-south traffic.
- Cluster Pod CIDRs must not overlap for most flat-network designs.
@diagram flow
caption: Exported service
nodes:
  - "Service in cluster A|api|app"
  - "ServiceExport|marks it exported|info"
  - "ServiceImport in cluster B|virtual service|info"
  - "Client in B|calls api.shop.svc.clusterset.local|ok"
@h Export
```yaml title="MCS API export" nocheck
apiVersion: multicluster.x-k8s.io/v1alpha1
kind: ServiceExport
metadata:
  name: api
  namespace: shop
```
@check
What must not overlap in a flat multi-cluster network? || Pod and often Service CIDRs, since addresses must be unique across clusters.
@end

@concept Cilium Cluster Mesh and Submariner
@plain
Both connect the Pod networks of several clusters so that Pods in different clusters reach each other directly.
@problem
Without it, cross-cluster traffic has to leave through public load balancers with extra latency, cost and exposure.
@does
- **Cluster Mesh** (Cilium): each cluster runs a `clustermesh-apiserver`; agents read remote state, enabling global services (annotated `service.cilium.io/global`) with failover affinity and cross-cluster network policy.
- Requires unique cluster names and IDs, non-overlapping CIDRs and connectivity between nodes (or via a tunnel).
- **Submariner**: gateways with IPsec or WireGuard tunnels, Lighthouse for service discovery, works with different CNIs.
- Managed platforms limit this (for example EKS with VPC CNI needs peering or Transit Gateway and care with Pod IPs).
@diagram flow
caption: Global service with failover
nodes:
  - "Client Pod|cluster eu|app"
  - "Global service|same name in both clusters|cp"
  - "Local backends|preferred|ok"
  - "Remote backends|used on failure|warn"
@h Annotate a service
```yaml title="Cilium global service with local affinity"
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: shop
  annotations:
    service.cilium.io/global: "true"
    service.cilium.io/affinity: "local"
spec:
  selector:
    app: api
  ports:
    - port: 8080
```
@end

@concept Workload placement with Karmada and OCM
@plain
Karmada and Open Cluster Management (OCM) offer a control plane that spreads workloads across member clusters by policy.
@problem
Deploying the same app to ten clusters by hand, with small differences, is slow and error prone.
@does
- Karmada accepts normal Kubernetes manifests plus `PropagationPolicy` (where to run, how to split replicas by weight) and `OverridePolicy` (per-cluster differences).
- It can also reschedule when a cluster fails, and aggregate status.
- Alternatives: Argo CD ApplicationSets (push manifests to each cluster), Flux with remote clusters, and cloud fleet products.
- Original Kubernetes Federation v1 and KubeFed v2 are archived; do not start new work with them.
@diagram flow
caption: Karmada propagation
nodes:
  - "Deployment + PropagationPolicy|in Karmada API|app"
  - "Karmada scheduler|picks clusters|cp"
  - "Cluster eu|3 replicas|ok"
  - "Cluster us|2 replicas|ok"
@h Policy
```yaml title="Propagation policy" nocheck
apiVersion: policy.karmada.io/v1alpha1
kind: PropagationPolicy
metadata:
  name: api
spec:
  resourceSelectors:
    - apiVersion: apps/v1
      kind: Deployment
      name: api
  placement:
    clusterAffinity:
      clusterNames: [eu, us]
    replicaScheduling:
      replicaSchedulingType: Divided
      weightPreference:
        staticWeightList:
          - targetCluster: {clusterNames: [eu]}
            weight: 3
          - targetCluster: {clusterNames: [us]}
            weight: 2
```
@end

@concept Global traffic and failover
@plain
Users reach the nearest healthy cluster through DNS or an anycast/global load balancer that checks cluster health.
@problem
If a region fails, traffic must move without waiting for people.
@does
- Weighted or latency DNS (Route 53, SAP-supplied DNS) with health checks, or global load balancers (AWS Global Accelerator, cloud CDN).
- Keep DNS TTL low enough for your RTO; remember resolvers may cache longer.
- Data is the hard part: active-active requires multi-region databases or conflict handling; active-passive requires replication and a tested promotion.
- Test with game days: block a region and measure.
@diagram flow
caption: Failover path
nodes:
  - "User|resolves app.example.com|plain"
  - "Global DNS with health check|picks region|cp"
  - "Region eu healthy|serves|ok"
  - "Region us standby|takes over|warn"
@check
Why is data harder than traffic in multi-region failover? || Traffic can be redirected quickly, but writes must be replicated and consistent, and promotion of a replica risks data loss or split brain.
@end

@concept Identity, secrets and policy across clusters
@plain
Several clusters need consistent identity for people, workloads and secrets without copying long-lived credentials.
@problem
Per-cluster passwords and kubeconfigs multiply and are rarely rotated.
@does
- People: OIDC with your IdP (SAP IAS or Astra Connect SSO in your case), the same groups mapped to RBAC in each cluster through GitOps.
- Workloads: SPIFFE/SPIRE or mesh identity with a shared trust root for mTLS across clusters.
- Secrets: External Secrets Operator per cluster reading from one secret manager with scoped access.
- Policy: the same Kyverno or ValidatingAdmissionPolicy bundle delivered by GitOps.
@diagram layers
caption: Shared control concerns
layers:
  - {label: "Identity", nodes: ["OIDC IdP|users and groups|ext", "Trust root|workload identity|ext"]}
  - {label: "Delivery", nodes: ["Git|RBAC, policy, add-ons|ext"]}
  - {label: "Clusters", nodes: ["Cluster eu|synced|app", "Cluster us|synced|app", "Cluster dev|synced|app"]}
@end

@concept Operating a multi-cluster setup
@plain
Day-two work includes keeping versions aligned, monitoring all clusters in one place and writing runbooks that name the cluster.
@problem
More clusters means more places for configuration to drift and more chances to run a command in the wrong one.
@does
- Central metrics with Prometheus remote write or Thanos/Mimir, with a `cluster` label on every series.
- Centralised logs and alerts that include cluster name; dashboards with a cluster variable.
- Standard tooling for contexts: one kubeconfig per cluster and a prompt that shows it.
- Document each cluster in an inventory (owner, version, purpose, access method) and test restores per cluster.
@diagram flow
caption: Central observability
nodes:
  - "Cluster eu|Prometheus agent|app"
  - "Cluster us|Prometheus agent|app"
  - "Central store|Thanos or Mimir|cp"
  - "Dashboards and alerts|cluster label|ok"
@h Add a cluster label
```yaml title="Prometheus external label"
global:
  external_labels:
    cluster: prod-eu
    region: eu-central-1
```
@end
