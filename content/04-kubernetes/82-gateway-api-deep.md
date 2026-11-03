---
title: Gateway API in depth
minutes: 55
objectives:
  - Explain the role-oriented model of GatewayClass, Gateway and routes
  - Configure HTTPRoute matching, traffic splitting, filters and cross-namespace access
  - Operate TLS, policy attachment and migration from Ingress
---
Gateway API is the successor of Ingress. It is expressive, role based and portable across implementations such as Istio, Cilium, Envoy Gateway and the Kyma API Gateway module.

@concept The role-oriented resource model
@plain
Gateway API splits what Ingress mixed together. Infrastructure providers define a GatewayClass, cluster operators create Gateways, and app teams attach routes.
@problem
One Ingress object forced platform and application owners to edit the same file, and annotations differed for every controller.
@does
- `GatewayClass` names a controller (like StorageClass).
- `Gateway` declares listeners: port, protocol, hostname and TLS.
- `HTTPRoute`, `GRPCRoute`, `TLSRoute`, `TCPRoute` and `UDPRoute` describe routing and attach to a Gateway through `parentRefs`. Route types beyond HTTPRoute vary in maturity; check the current support level.
- Standard channel resources are GA (`v1`) for GatewayClass, Gateway, HTTPRoute and GRPCRoute. Experimental ones need the experimental CRD bundle.
@diagram layers
caption: Who owns which object
layers:
  - {label: "Infrastructure provider", nodes: ["GatewayClass|controller name|ext"]}
  - {label: "Cluster operator", nodes: ["Gateway|listeners and TLS|cp"]}
  - {label: "Application developer", nodes: ["HTTPRoute|paths, headers, backends|app", "Service|backend|ok"]}
@h Core objects
```yaml title="Gateway and HTTPRoute" 
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: public
  namespace: infra
spec:
  gatewayClassName: istio
  listeners:
    - name: https
      protocol: HTTPS
      port: 443
      hostname: "*.example.com"
      tls:
        mode: Terminate
        certificateRefs:
          - name: wildcard-example-com
      allowedRoutes:
        namespaces:
          from: Selector
          selector:
            matchLabels:
              gateway-access: "true"
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api
  namespace: shop
spec:
  parentRefs:
    - name: public
      namespace: infra
  hostnames: ["api.example.com"]
  rules:
    - matches:
        - path: {type: PathPrefix, value: /v1}
      backendRefs:
        - name: api
          port: 8080
```
@check
Which object does the application team normally own? || The route (HTTPRoute and similar). The Gateway belongs to the cluster operator, and the GatewayClass to the infrastructure provider.
@end

@concept Listeners, hostnames and allowedRoutes
@plain
A listener is a port and protocol on a Gateway, optionally limited to a hostname. `allowedRoutes` decides which namespaces may attach routes to it.
@problem
In a shared cluster, any team could claim any hostname or path on a shared entry point.
@does
- `from: Same` allows only the Gateway namespace, `All` any, `Selector` namespaces by label.
- Routes whose hostnames do not intersect with the listener hostname are not accepted.
- Status conditions on routes (`Accepted`, `ResolvedRefs`) tell you why attachment failed.
- Conflicts on the same hostname and path are resolved by oldest creation time, then name.
@diagram flow
caption: Attachment decision
nodes:
  - "Route parentRefs|names the Gateway|app"
  - "Namespace allowed|allowedRoutes|cp"
  - "Hostname matches|listener hostname|cp"
  - "Accepted|status condition|ok"
@h Read the status
```bash title="Why was my route not accepted" lab
kubectl get gateway -A
kubectl get httproute api -n shop -o jsonpath='{range .status.parents[*].conditions[*]}{.type}{"="}{.status}{" "}{.reason}{"\n"}{end}'
kubectl describe gateway public -n infra | tail -25
```
@end

@concept HTTPRoute matching and filters
@plain
Each rule has matches (path, headers, query, method) and optional filters that change the request or response before it reaches the backend.
@problem
Ingress annotations for redirects and rewrites were controller specific and not portable.
@does
- Path types: `Exact`, `PathPrefix` and `RegularExpression` (implementation specific).
- Most specific match wins: exact over prefix, longer prefix first, then header and query matches.
- Standard filters: `RequestHeaderModifier`, `ResponseHeaderModifier`, `RequestRedirect`, `URLRewrite`, `RequestMirror`. `ExtensionRef` points at custom filters.
- Timeouts and retries have been added in newer releases; check support in your implementation.
@diagram flow
caption: Rule evaluation
nodes:
  - "Request|host, path, headers|plain"
  - "Match|most specific rule|info"
  - "Filters|rewrite, headers, redirect|warn"
  - "Backend|Service port|ok"
@h Redirect and rewrite
```yaml title="HTTP to HTTPS redirect and a path rewrite"
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: redirect-http
  namespace: infra
spec:
  parentRefs:
    - name: public
      sectionName: http
  rules:
    - filters:
        - type: RequestRedirect
          requestRedirect:
            scheme: https
            statusCode: 301
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: legacy
  namespace: shop
spec:
  parentRefs:
    - name: public
      namespace: infra
  rules:
    - matches:
        - path: {type: PathPrefix, value: /old}
      filters:
        - type: URLRewrite
          urlRewrite:
            path: {type: ReplacePrefixMatch, replacePrefixMatch: /new}
      backendRefs:
        - name: api
          port: 8080
```
@end

@concept Traffic splitting and canary
@plain
`backendRefs` accept a `weight`. Traffic is divided in proportion to the weights, so canary and blue-green releases need no extra tool.
@problem
Gradual rollouts previously needed a mesh or controller-specific annotations.
@does
- Weights are relative integers, not percentages. 90 and 10 gives 90 and 10 percent.
- A weight of 0 sends no traffic but keeps the backend defined.
- Combine with header matches so testers reach the canary first.
- Argo Rollouts and Flagger can drive these weights automatically.
@diagram flow
caption: Weighted split
nodes:
  - "HTTPRoute|rule with two backends|app"
  - "api-stable|weight 90|ok"
  - "api-canary|weight 10|warn"
@h Canary route
```yaml title="90 / 10 split with a header override"
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: shop
spec:
  parentRefs:
    - name: public
      namespace: infra
  rules:
    - matches:
        - headers:
            - name: x-canary
              value: "true"
      backendRefs:
        - name: api-canary
          port: 8080
    - backendRefs:
        - name: api-stable
          port: 8080
          weight: 90
        - name: api-canary
          port: 8080
          weight: 10
```
@check
Are weights percentages? || No, they are relative shares. The share of a backend is its weight divided by the sum of weights.
@end

@concept TLS, certificates and cross-namespace references
@plain
A Gateway listener terminates TLS using a Secret. If the Secret or a backend is in another namespace, a ReferenceGrant in the target namespace must allow it.
@problem
Cross-namespace references would let any team read another team's Secrets or send traffic to its Services.
@does
- `certificateRefs` point at `kubernetes.io/tls` Secrets. cert-manager can create them from Gateway annotations or its Gateway support.
- `ReferenceGrant` lists allowed `from` (kind and namespace) and `to` (kind, optionally name). Without it status shows `RefNotPermitted`.
- TLS mode `Passthrough` forwards encrypted traffic to the backend by SNI using `TLSRoute`.
- Backend TLS (gateway to Pod) is configured through `BackendTLSPolicy`, which is still maturing; check the current docs.
@diagram seq
caption: Cross-namespace secret
actors: ["Gateway|namespace infra|cp", "ReferenceGrant|namespace certs|info", "Secret|wildcard cert|ok"]
steps:
  - "0>1: may I read this Secret | req"
  - "1>1: from Gateway in infra | warn"
  - "1>0: allowed | resp"
  - "0>2: load certificate | tls"
@h ReferenceGrant
```yaml title="Let Gateways in infra use a Secret in certs"
apiVersion: gateway.networking.k8s.io/v1beta1
kind: ReferenceGrant
metadata:
  name: allow-infra-gateway
  namespace: certs
spec:
  from:
    - group: gateway.networking.k8s.io
      kind: Gateway
      namespace: infra
  to:
    - group: ""
      kind: Secret
      name: wildcard-example-com
```
@end

@concept Policy attachment and implementations
@plain
Policy attachment adds behaviour such as rate limits, retries or auth to a Gateway or Route by pointing a separate policy object at it using `targetRefs`.
@problem
Not every feature fits into the core API, and putting it in annotations brings back the portability problem.
@does
- Implementations define their own policy CRDs: Istio `AuthorizationPolicy` and `RequestAuthentication` with `targetRefs`, Cilium and Envoy Gateway policy types, and so on.
- Check the Gateway API implementations page for conformance level and features. Conformance is per feature, not all or nothing.
- Kyma's API Gateway module exposes `APIRule` (v2) on Istio. Newer Kyma releases are adding Gateway API support, so confirm in the current Kyma docs which to use.
- Always read status of `GatewayClass` for `Accepted`.
@diagram layers
caption: Policy attaches from the side
layers:
  - {label: "Gateway API", nodes: ["Gateway|listeners|cp", "HTTPRoute|rules|app"]}
  - {label: "Policy objects", nodes: ["AuthorizationPolicy|targetRefs Gateway|warn", "Timeout or retry policy|targetRefs route|warn"]}
  - {label: "Data plane", nodes: ["Envoy proxies|programmed by controller|ok"]}
@h Istio policy bound to a Gateway
```yaml title="Require JWT on a Gateway (Istio)"
apiVersion: security.istio.io/v1
kind: RequestAuthentication
metadata:
  name: jwt
  namespace: infra
spec:
  targetRefs:
    - group: gateway.networking.k8s.io
      kind: Gateway
      name: public
  jwtRules:
    - issuer: https://ias.example.com
      jwksUri: https://ias.example.com/oauth2/certs
```
@end

@concept Migrating from Ingress
@plain
Migration means translating Ingress rules and annotations into Gateways and routes, then moving traffic gradually.
@problem
Ingress-NGINX is being retired (the Kubernetes project announced its end of maintenance in 2026; check the current announcement), and annotations do not carry over.
@does
- The `ingress2gateway` tool converts many Ingress resources, but annotations need manual review.
- Run both side by side with different load balancers. Lower DNS TTLs, then shift records or weighted DNS.
- Check each annotation: rewrite, auth, rate limits, body size, timeouts. Map to filters, policies or implementation CRDs.
- Test with `curl --resolve host:443:IP` before changing DNS.
@diagram flow
caption: Migration steps
numbered: true
nodes:
  - "Inventory|ingresses and annotations|plain"
  - "Convert|ingress2gateway|info"
  - "Run in parallel|new LB address|app"
  - "Shift DNS|weighted records|warn"
  - "Retire Ingress|remove old controller|ok"
@h Commands
```bash title="Convert and test" lab
ingress2gateway print --providers ingress-nginx --namespace shop > /tmp/gw.yaml
kubectl apply --dry-run=server -f /tmp/gw.yaml
curl -sk --resolve api.example.com:443:203.0.113.10 https://api.example.com/healthz
```
:::note
Flag names of ingress2gateway change between releases. Run `ingress2gateway print --help` first.
:::
@check
How can you test a new Gateway before changing DNS? || Call its address directly with curl --resolve host:port:IP so that the Host header and SNI still match.
@end
