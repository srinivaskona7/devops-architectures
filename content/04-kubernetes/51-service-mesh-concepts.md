---
title: Service mesh concepts and data planes
minutes: 40
objectives:
  - Explain what a service mesh adds and what it costs
  - Compare sidecar and ambient data planes
  - Choose between Istio, Linkerd and Cilium for a given need
---
A **service mesh** moves common network features (encryption, retries, traffic splitting, telemetry) out of every application and into the platform. It is powerful and not free, so the first question is whether you need one.
@concept What a service mesh does
@plain
A mesh adds a managed layer between your services. A **data plane** handles the traffic; a **control plane** configures it. Applications keep making ordinary HTTP or gRPC calls.
@problem
Each team re-implements TLS between services, retries, timeouts and metrics in a different library and language. Security teams cannot prove that internal traffic is encrypted.
@does
- **mTLS**: automatic encryption and service identity between workloads, with certificate rotation.
- **Traffic management**: retries, timeouts, circuit breaking, weighted routing for canaries, fault injection.
- **Observability**: request rate, errors and latency for every service pair without code changes, plus tracing headers.
- **Authorisation**: allow or deny calls by workload identity, method and path.
@diagram flow
caption: Control plane configures the data plane
nodes:
  - "Control plane|istiod or linkerd destination|cp"
  - "Data plane|proxies on the traffic path|app"
  - "Service A|plain calls|env"
  - "Service B|plain calls|env"
@h Is a mesh needed
```bash title="Questions to answer with data" lab
kubectl get pods -A | wc -l                                  # how many workloads
kubectl get svc -A | wc -l                                   # how many services talk to each other
kubectl get networkpolicy -A | wc -l                         # existing segmentation
```
:::tip
If you only need ingress TLS, a few retries in code and NetworkPolicy, you do not need a mesh. Adopt one for a concrete requirement such as mandatory internal mTLS, progressive delivery or cross-cluster traffic.
:::
@end

@concept The sidecar model
@plain
In the classic design, a proxy container (Envoy for Istio, linkerd2-proxy for Linkerd) is injected into every Pod. Traffic in and out of the application container passes through it.
@problem
The network features must apply to unmodified applications in any language, at the Pod boundary.
@does
- A mutating webhook injects the sidecar when a namespace or Pod carries the injection label or annotation. Traffic is redirected by iptables rules set by an init container or a CNI plugin.
- Each Pod carries its own proxy, so CPU and memory overhead scale with Pod count, and each proxy adds latency in both directions.
- Sidecars must start before the app and stop after it; ordering problems cause connection errors on start and shutdown. Native sidecar containers (restartable init containers, stable since 1.33) address this.
- Changing the mesh version means restarting Pods to pick up the new proxy.
@diagram layers
caption: A Pod with a sidecar
layers:
  - {label: "Pod", nodes: ["app container|port 8080|app", "sidecar proxy|mTLS, retries, metrics|info"]}
  - {label: "Network", nodes: ["Other Pods|mTLS between sidecars|env"]}
@h Enable injection for a namespace
```yaml title="namespace-injected.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    istio-injection: enabled
```
```bash title="Check the sidecar" lab
kubectl label namespace shop istio-injection=enabled --overwrite
kubectl rollout restart deploy -n shop            # existing Pods need a restart
kubectl get pods -n shop -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.containers[*].name}{"\n"}{end}'
```
@end

@concept The ambient model
@plain
Istio **ambient mode** removes per-Pod sidecars. A small agent on each node (ztunnel) handles L4 features such as mTLS and identity. Optional **waypoint proxies** per namespace or service handle L7 features like HTTP routing.
@problem
Sidecars cost resources on every Pod, couple the mesh lifecycle to application restarts, and add friction for jobs and short-lived Pods.
@does
- **ztunnel** (a Rust DaemonSet) provides mTLS, L4 authorisation and telemetry for all Pods on a node, using the HBONE tunnel protocol.
- **Waypoint** proxies (Envoy) are deployed only where L7 policy is required, and are managed through the Kubernetes Gateway API.
- Enrol a namespace with the label `istio.io/dataplane-mode=ambient`; no Pod restart is needed.
- Ambient reached general availability in Istio 1.24. Check the current documentation for supported platforms and CNI interplay.
@diagram cmp
caption: Sidecar versus ambient
cards:
  - {h: "Sidecar", kind: app, items: ["Envoy in every Pod", "Full L7 per Pod", "Restart to upgrade", "Highest resource use"]}
  - {h: "Ambient", kind: ok, items: ["ztunnel per node for L4", "Waypoint only where L7 is needed", "No Pod restart to enrol", "Lower overhead"]}
@h Enrol a namespace
```bash title="Ambient enrolment" lab
istioctl install --set profile=ambient
kubectl label namespace shop istio.io/dataplane-mode=ambient
istioctl ztunnel-config workloads | head
kubectl get pods -n istio-system -l app=ztunnel -o wide
```
@end

@concept Istio, Linkerd and Cilium compared
@plain
Three popular meshes make different trade-offs. Istio has the broadest features, Linkerd aims for simplicity and a small footprint, and Cilium builds networking, policy and optional mesh features on eBPF.
@problem
Choosing by popularity leads to a heavy mesh where a light one would do, or a light one that lacks a feature you must have.
@does
- **Istio**: Envoy based, rich traffic and security policy (VirtualService, DestinationRule, AuthorizationPolicy, Gateway API), sidecar or ambient. The mesh behind Kyma's Istio module.
- **Linkerd**: its own Rust micro-proxy, automatic mTLS by default, small CRD surface. Stable releases from the open source project are not distributed as binaries by Buoyant after 2024, so verify how you source them and their licence.
- **Cilium**: CNI with eBPF dataplane, NetworkPolicy and CiliumNetworkPolicy, Hubble observability, transparent encryption (WireGuard or IPsec), and service mesh features using node level Envoy.
- Do not run two meshes on the same workloads.
@diagram cmp
caption: Where each shines
cards:
  - {h: "Istio", kind: app, items: ["Most features", "Ambient or sidecar", "Largest learning curve"]}
  - {h: "Linkerd", kind: ok, items: ["Simple and light", "mTLS on by default", "Fewer routing features"]}
  - {h: "Cilium", kind: info, items: ["eBPF networking", "Hubble flow visibility", "Mesh features are newer"]}
@choose Picking one
Istio | you need rich L7 traffic control, a Kyma/SAP integrated mesh or multi cluster | the team cannot invest in operating it
Linkerd | you want mTLS and golden metrics with the least complexity | you need advanced routing and extension points
Cilium | you already use it as CNI and want policy plus flow visibility | you need the broad L7 feature set of Envoy meshes
No mesh | few services, ingress TLS and NetworkPolicy are enough | compliance requires mTLS everywhere
@end

@concept Costs and failure modes
@plain
A mesh adds a new moving part on the path of every request. Know the overhead and the typical failure modes before you enable it.
@problem
Teams enable a mesh and then see higher latency, higher bills, unexplained 503s and upgrade outages, with no one who understands the proxy layer.
@does
- **Resources**: sidecar proxies use memory and CPU per Pod; measure with `kubectl top pod --containers`. Ambient reduces but does not remove this.
- **Latency**: each hop adds a small amount of time; verify p99 against your SLO.
- **Failure modes**: sidecar not ready at app start, `503 UC` or `NR` responses from misconfigured routes, certificate or clock problems, jobs that never finish because the sidecar keeps running, and control plane outage freezing config pushes (existing traffic keeps flowing).
- **Operations**: the mesh version must be upgraded in step with Kubernetes; canary the control plane and then data plane.
@diagram flow
caption: Typical start-up failure
nodes:
  - "App starts first|calls a service|app"
  - "Sidecar not ready|no route yet|bad"
  - "Connection reset|looks like app bug|bad"
  - "Hold app until proxy ready|startup ordering|ok"
@h Measure before and after
```bash title="Overhead and health" lab
kubectl top pod -n shop --containers | sort -k4 -h | tail
istioctl analyze -n shop                               # config validation
istioctl proxy-status                                  # are proxies in sync with the control plane
kubectl logs deploy/api -n shop -c istio-proxy --tail=20
```
@check
Does an Istio control plane outage stop traffic between running Pods? || No. Proxies keep the last configuration they received. New or changed config and new Pods are affected.
@end

@concept Adopting a mesh step by step
@plain
Introduce a mesh gradually: observe first, then secure, then add traffic features, one namespace at a time.
@problem
Turning on strict mTLS and sidecars everywhere on day one breaks the services that talk to non-mesh clients and databases.
@does
- Start with a non-critical namespace and permissive mTLS, which accepts both plain and mTLS traffic.
- Watch dashboards (request success rate, latency, mTLS percentage), then move to strict mode.
- Add policy (AuthorizationPolicy) from a default deny with explicit allows, similar to NetworkPolicy.
- Handle special cases: Jobs, databases, and traffic from outside the mesh through an ingress gateway.
@diagram flow
caption: A safe adoption order
numbered: true
nodes:
  - "Install and observe|permissive mode|info"
  - "Enrol namespaces|one at a time|app"
  - "Strict mTLS|after metrics confirm|warn"
  - "Policy and routing|canaries, authz|ok"
@h PeerAuthentication in steps
```yaml title="peerauthentication.yaml"
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: shop
spec:
  mtls:
    mode: PERMISSIVE     # change to STRICT after every client is in the mesh
```
@end
