---
title: Linkerd, Cilium and operating a mesh
minutes: 35
objectives:
  - Describe how Linkerd and Cilium implement mesh features
  - Use Hubble and mesh telemetry to see service traffic
  - Upgrade and troubleshoot a mesh safely
---
Istio is not the only option. This section shows how Linkerd and Cilium solve the same problems differently and how to run any mesh without surprises.

@concept Linkerd in practice
@plain
Linkerd injects a lightweight Rust proxy into each Pod and enables mTLS and golden metrics (success rate, request rate, latency) with no extra configuration.
@problem
You want encryption and basic observability between services quickly, without learning dozens of CRDs.
@does
- Enrol workloads with the annotation `linkerd.io/inject: enabled` on a namespace or Pod template.
- `linkerd check` validates the installation; `linkerd viz` adds a metrics dashboard and `linkerd viz stat` prints live success rate and latency.
- Policy uses `Server` and `AuthorizationPolicy` resources; traffic splitting uses Gateway API `HTTPRoute`.
- The control plane identity trust anchor certificate must be rotated before it expires; automate it with cert-manager.
@diagram flow
caption: Linkerd request path
nodes:
  - "App container|plain HTTP|app"
  - "linkerd-proxy|mTLS and metrics|info"
  - "linkerd-proxy at destination|terminates mTLS|info"
  - "Destination app|plain HTTP|app"
@h Enrol a namespace
```yaml title="linkerd-namespace.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  annotations:
    linkerd.io/inject: enabled
```
```bash title="Check and observe" lab
linkerd check
kubectl rollout restart deploy -n shop
linkerd viz stat deploy -n shop
linkerd viz tap deploy/api -n shop        # live requests; needs permission
```
@end

@concept Cilium as CNI and mesh
@plain
Cilium uses eBPF programs in the Linux kernel to route packets, enforce NetworkPolicy and observe traffic. It can replace kube-proxy and offers mesh features without a sidecar per Pod.
@problem
iptables based networking becomes slow with many Services, and standard NetworkPolicy cannot filter by DNS name or HTTP path.
@does
- `CiliumNetworkPolicy` adds L7 rules (HTTP methods and paths), DNS-name egress rules (`toFQDNs`), and identity based selection.
- **Hubble** gives flow visibility: who talked to whom, what was allowed or dropped, DNS and HTTP metadata.
- Transparent encryption between nodes with WireGuard or IPsec; optional mutual authentication through SPIFFE.
- On EKS you can run Cilium in place of or chained with the VPC CNI; this is a deliberate design choice made at cluster creation.
@diagram layers
caption: Where Cilium sits
layers:
  - {label: "Observability", nodes: ["Hubble|flows and verdicts|ok"]}
  - {label: "Policy", nodes: ["NetworkPolicy|L3 and L4|info", "CiliumNetworkPolicy|L7 and FQDN|info"]}
  - {label: "Datapath", nodes: ["eBPF in the kernel|routing, load balancing|cp"]}
@h Policy with a DNS name
```yaml title="cilium-fqdn.yaml"
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: api-egress
  namespace: shop
spec:
  endpointSelector:
    matchLabels:
      app: api
  egress:
    - toEndpoints:
        - matchLabels:
            io.kubernetes.pod.namespace: kube-system
            k8s-app: kube-dns
      toPorts:
        - ports:
            - port: "53"
              protocol: ANY
          rules:
            dns:
              - matchPattern: "*"
    - toFQDNs:
        - matchName: api.payments.example.com
      toPorts:
        - ports:
            - port: "443"
              protocol: TCP
```
@end

@concept Seeing traffic with Hubble
@plain
Hubble records network flows with Kubernetes identity (namespace, Pod, labels) and the policy verdict for each, so you can answer "why is this connection dropped" directly.
@problem
Debugging NetworkPolicy by guesswork is slow. You need to see the actual dropped packets and which policy decided.
@does
- `hubble observe` streams flows; filter by namespace, Pod, verdict (`FORWARDED`, `DROPPED`), protocol and HTTP status.
- `hubble status` and `cilium status` check agents; the Hubble UI draws a service map.
- Flows are kept in a ring buffer on each node, so they are for live debugging, not long-term audit. Export to storage for history.
@diagram flow
caption: From packet to verdict
nodes:
  - "Packet|Pod to Pod|plain"
  - "eBPF policy check|identity based|cp"
  - "Verdict|forwarded or dropped|warn"
  - "Hubble flow|visible to you|ok"
@h Commands
```bash title="Find drops" lab
cilium status --wait
hubble observe --namespace shop --verdict DROPPED --last 50
hubble observe --from-pod shop/web-0 --to-service shop/api --protocol http
hubble observe --namespace shop --type policy-verdict
```
@end

@concept Observing the mesh with metrics and traces
@plain
Proxies emit uniform metrics for every service pair and propagate trace headers. Prometheus scrapes the metrics; a tracing backend receives spans.
@problem
Without the mesh each service exposes different metrics, if any, and tracing is missing for services nobody instrumented.
@does
- **Golden signals** per workload: request rate, error rate, latency percentiles, bytes.
- Tracing needs the application to **forward trace headers** (W3C `traceparent` or B3). The proxy cannot join spans without them.
- Keep label cardinality under control; per-path labels can explode the number of time series.
- Kyma ships a Telemetry module that configures pipelines for logs, traces and metrics towards your backend.
@diagram flow
caption: Telemetry pipeline
nodes:
  - "Proxy metrics|requests, latency|info"
  - "Prometheus|scrape|db"
  - "Grafana|golden signal dashboards|ok"
  - "Tracing backend|spans via OTLP|ext"
@h Useful queries
```promql title="PromQL for mesh traffic" nocheck
# request rate per destination service (Istio standard metrics)
sum(rate(istio_requests_total{reporter="destination"}[5m])) by (destination_service_name)

# error ratio
sum(rate(istio_requests_total{reporter="destination",response_code=~"5.."}[5m]))
  / sum(rate(istio_requests_total{reporter="destination"}[5m]))

# p99 latency
histogram_quantile(0.99, sum(rate(istio_request_duration_milliseconds_bucket{reporter="destination"}[5m])) by (le, destination_service_name))
```
@end

@concept Upgrading and troubleshooting a mesh
@plain
Treat the mesh as a platform component with its own upgrade process: control plane first, then data plane, in a canary fashion.
@problem
A mesh upgrade that restarts every Pod at once, or a control plane version that does not support your Kubernetes version, takes down the traffic layer.
@does
- Check the compatibility table of the mesh against the target Kubernetes version before a cluster upgrade.
- **Istio revision based upgrade**: install a second control plane revision (`istioctl install --set revision=1-24-0`), move a namespace by changing its `istio.io/rev` label, restart workloads, then remove the old revision. Ambient ztunnel upgrades per node.
- **Linkerd**: upgrade CRDs, then control plane, then restart workloads to pick up the new proxy.
- Alert on proxy out of sync, certificate expiry, and control plane restarts.
- If the mesh breaks traffic during an incident, the fastest mitigation is removing injection and restarting the affected workload, which is why you rehearse it.
@diagram flow
caption: Canary control plane upgrade
numbered: true
nodes:
  - "Install new revision|alongside the old|info"
  - "Move one namespace|change rev label|app"
  - "Verify|traffic and metrics|warn"
  - "Move the rest|then delete the old revision|ok"
@h Commands
```bash title="Revision switch" lab
istioctl install --set revision=1-24-0 -y
kubectl label namespace shop istio-injection- istio.io/rev=1-24-0 --overwrite
kubectl rollout restart deploy -n shop
istioctl proxy-status | head
kubectl get pods -n shop -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.metadata.annotations.sidecar\.istio\.io/status}{"\n"}{end}' | head -3
```
@check
Why must apps forward trace headers when a mesh is present? || The proxy creates spans per hop but cannot know which inbound request caused an outbound call unless the application passes the trace context along.
@end
