---
title: Istio traffic management and security
minutes: 45
objectives:
  - Route and split traffic with Gateway API and Istio resources
  - Enforce mTLS and workload authorisation
  - Debug a mesh with istioctl and proxy logs
---
Istio is the mesh you are most likely to meet on Kyma. This section covers the resources you will actually write and how to debug them.

@concept Gateways for ingress
@plain
A gateway is an Envoy proxy at the edge of the mesh that accepts external traffic. You configure it with the Kubernetes **Gateway API** (`Gateway`, `HTTPRoute`) or Istio's own `Gateway` and `VirtualService`.
@problem
Traffic from outside needs TLS termination, host and path routing, and the same policy and telemetry as internal calls.
@does
- Gateway API is the portable model; Istio implements it with `gatewayClassName: istio`. Istio's own resources remain widely used, and Kyma's API Gateway module builds on Istio.
- A `Gateway` defines listeners (port, hostname, TLS); an `HTTPRoute` attaches to it and routes by host, path or header to backend Services.
- TLS certificates come from Secrets, often created by cert-manager.
@diagram flow
caption: Request entering the mesh
nodes:
  - "Client|HTTPS|ext"
  - "Gateway|TLS termination|cp"
  - "HTTPRoute|match host and path|info"
  - "Service|backend Pods|app"
@h Gateway API example
```yaml title="gateway.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public
  namespace: shop
spec:
  gatewayClassName: istio
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
      hostname: shop.example.com
      tls:
        mode: Terminate
        certificateRefs:
          - name: shop-tls
      allowedRoutes:
        namespaces:
          from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop
  namespace: shop
spec:
  parentRefs:
    - name: public
  hostnames: ["shop.example.com"]
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api
      backendRefs:
        - name: api
          port: 80
```
@end

@concept Weighted routing and canaries
@plain
Traffic can be split between versions by percentage, independent of the number of Pods. This allows a canary release that sends 5 percent of requests to the new version.
@problem
With plain Services, traffic share follows Pod counts, so a 5 percent canary needs 20 Pods. And there is no quick way to shift traffic back.
@does
- Gateway API: `backendRefs` with `weight` in an `HTTPRoute`.
- Istio native: `DestinationRule` defines subsets by Pod label (`version: v2`); `VirtualService` routes weights to subsets.
- Header matching sends internal testers to the new version while the public stays on the old one.
- Progressive delivery tools (Argo Rollouts, Flagger) automate weight steps and rollback from metrics.
@diagram flow
caption: Canary split
nodes:
  - "Gateway|incoming traffic|cp"
  - "95 percent|api v1|app"
  - "5 percent|api v2 canary|warn"
  - "Metrics|errors and latency decide|ok"
@h Weighted HTTPRoute
```yaml title="canary-route.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: shop
spec:
  parentRefs:
    - name: public
  rules:
    - backendRefs:
        - name: api-v1
          port: 80
          weight: 95
        - name: api-v2
          port: 80
          weight: 5
```
@end

@concept Retries, timeouts and circuit breaking
@plain
The mesh can enforce time limits, retry failed calls, and eject unhealthy backends, so these policies are consistent for all services.
@problem
Without limits, a slow dependency makes every caller slow, and uncoordinated retries in many layers multiply load on a struggling service (a retry storm).
@does
- Per-route `timeout` and `retries` (attempts, perTryTimeout, retryOn) in a `VirtualService`.
- `DestinationRule.trafficPolicy.connectionPool` limits connections and pending requests; `outlierDetection` ejects hosts after consecutive 5xx errors.
- Retry only idempotent operations, and keep total attempts small. Total time must fit inside the caller's own timeout.
@diagram seq
caption: A retry on a failing backend
actors: ["Caller|Pod A|app", "Proxy|Envoy|info", "Backend|Pod B|app"]
steps:
  - "0>1: request | req"
  - "1>2: attempt 1 | req"
  - "2>1: 503 | bad"
  - "1>2: attempt 2 | req"
  - "2>1: 200 | resp"
  - "1>0: 200 | resp"
@h VirtualService and DestinationRule
```yaml title="resilience.yaml"
apiVersion: networking.istio.io/v1
kind: VirtualService
metadata:
  name: api
  namespace: shop
spec:
  hosts: ["api"]
  http:
    - route:
        - destination:
            host: api
      timeout: 5s
      retries:
        attempts: 2
        perTryTimeout: 2s
        retryOn: 5xx,connect-failure
---
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: api
  namespace: shop
spec:
  host: api
  trafficPolicy:
    connectionPool:
      http:
        http1MaxPendingRequests: 100
    outlierDetection:
      consecutive5xxErrors: 5
      interval: 10s
      baseEjectionTime: 30s
```
@end

@concept mTLS and PeerAuthentication
@plain
Istio gives every workload a certificate based identity (a SPIFFE ID built from namespace and service account) and encrypts traffic between proxies. `PeerAuthentication` controls whether plain traffic is still accepted.
@problem
Internal traffic is plain text by default, and any compromised Pod can read or forge calls to other services.
@does
- Modes: `PERMISSIVE` (accept both), `STRICT` (mTLS only), `DISABLE`. Set mesh-wide in the root namespace, or per namespace or workload.
- Certificates are issued by istiod and rotated automatically (24 hours by default).
- Identity is the service account, so give each workload its own ServiceAccount.
- Check the effective mode with `istioctl x describe pod` and look for mTLS on the connection.
@diagram flow
caption: Strict mTLS between workloads
nodes:
  - "Workload identity|SPIFFE from ServiceAccount|info"
  - "istiod CA|issues short-lived certs|cp"
  - "Proxy A to proxy B|mutual TLS|ok"
  - "Plain client|rejected in STRICT|bad"
@h Strict mode
```yaml title="strict-mtls.yaml"
apiVersion: security.istio.io/v1
kind: PeerAuthentication
metadata:
  name: default
  namespace: shop
spec:
  mtls:
    mode: STRICT
```
@end

@concept AuthorizationPolicy
@plain
An `AuthorizationPolicy` allows or denies requests based on who is calling (identity or namespace), where it goes (host, method, path) and request attributes such as headers or JWT claims.
@problem
mTLS proves who is calling, but it does not decide whether the call is allowed. Without policy, every workload in the mesh can call every other.
@does
- Like NetworkPolicy, once any ALLOW policy selects a workload, requests that match no ALLOW are denied. An empty policy `spec: {}` in a namespace denies everything.
- Evaluation order: CUSTOM, then DENY, then ALLOW.
- `principals` refer to identities (`cluster.local/ns/shop/sa/web`), while `namespaces` match caller namespaces.
- L7 rules (path, method) need a sidecar or, in ambient mode, a waypoint proxy; L4 rules work with ztunnel.
@diagram flow
caption: Policy evaluation
nodes:
  - "Request arrives|with peer identity|app"
  - "DENY policies|any match rejects|bad"
  - "ALLOW policies|no match rejects|warn"
  - "Allowed|forwarded to app|ok"
@h Allow only the web frontend
```yaml title="authz-api.yaml"
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: api-allow-web
  namespace: shop
spec:
  selector:
    matchLabels:
      app: api
  action: ALLOW
  rules:
    - from:
        - source:
            principals: ["cluster.local/ns/shop/sa/web"]
      to:
        - operation:
            methods: ["GET", "POST"]
            paths: ["/api/*"]
```
@end

@concept Debugging Istio
@plain
Most mesh problems are configuration mismatches or startup ordering. Istio ships tools that compare what you wrote with what each proxy actually received.
@problem
A route does nothing, requests return 503 with a cryptic flag, or one namespace behaves differently, and the Envoy configuration is large and unreadable.
@does
- `istioctl analyze` validates configuration and flags typical mistakes (a missing gateway, a host that matches nothing).
- `istioctl proxy-status` shows whether each proxy is synced with istiod; `istioctl proxy-config routes|clusters|listeners POD` shows what a proxy knows.
- Envoy access logs show response flags such as `UH` (no healthy upstream), `UF` (upstream connection failure), `NR` (no route), `URX` (retry limit).
- On Kyma, the Istio module is managed: change mesh-wide settings through the Istio custom resource, not by editing the installed control plane.
@diagram flow
caption: Narrowing a 503
nodes:
  - "istioctl analyze|config errors|info"
  - "proxy-status|are proxies synced|cp"
  - "proxy-config|route and cluster present|app"
  - "Access log flag|UH, NR, UF, URX|warn"
@h Commands
```bash title="Mesh triage" lab
istioctl analyze -A
istioctl proxy-status
istioctl proxy-config routes deploy/api -n shop
istioctl proxy-config clusters deploy/api -n shop | grep -i api
kubectl logs deploy/api -n shop -c istio-proxy --tail=30
kubectl get peerauthentication,authorizationpolicy,virtualservice,destinationrule -A
```
@check
What does an empty AuthorizationPolicy do? || It selects all workloads in the namespace with no allow rules, so it denies all requests.
Which Istio resource limits connections and ejects failing hosts? || DestinationRule, through connectionPool and outlierDetection.
@end
