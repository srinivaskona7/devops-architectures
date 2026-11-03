---
title: Ingress and Gateway API
minutes: 50
objectives:
  - Route external HTTP traffic with Ingress and understand what a controller does
  - Model roles and routes with the Gateway API
  - Choose between Ingress and Gateway API and terminate TLS with cert-manager
---
Services expose ports. Real applications need hostnames, paths, TLS and routing rules. Ingress and Gateway API describe those, and a controller makes them real.

@concept Why L7 routing
@plain
A LoadBalancer Service gives one external IP per Service at layer 4. Layer 7 routing shares one entry point among many apps by reading the HTTP host and path.
@problem
One cloud load balancer per Service is costly and gives no host or path routing, TLS handling or redirects.
@does
- One load balancer or proxy receives all traffic and forwards by `Host` header and URL path.
- TLS can be terminated once at the edge.
- The routing rules are Kubernetes objects, so they are version controlled and reviewed.
- The object alone does nothing; a **controller** (NGINX, Envoy, Istio, an ALB controller) must be installed.
@diagram flow
caption: One entry, many backends
nodes:
  - "Client|shop.example.com|ext"
  - "Load balancer|L4 or L7|ext"
  - "Proxy|ingress or gateway|cp"
  - "Services|by host and path|app"
@h See what is installed
```bash title="Classes in the cluster" lab
kubectl get ingressclass
kubectl get gatewayclass
kubectl get ingress,gateway,httproute -A
```
@end

@concept Ingress
@plain
An Ingress is a single object with host and path rules pointing to Services, handled by the controller named in `ingressClassName`.
@problem
You need basic web routing that works on any cluster with minimal configuration.
@does
- Rules: host, path, `pathType` (`Prefix`, `Exact`, `ImplementationSpecific`) and backend Service and port.
- `tls` section references a Secret holding the certificate.
- Everything beyond that (rewrites, timeouts, auth, rate limits) is controller-specific **annotations**, which makes manifests non-portable.
- The NGINX community Ingress controller was retired by its maintainers (best-effort maintenance ended in March 2026), so plan migration to a maintained controller or Gateway API.
@diagram layers
caption: Ingress pieces
layers:
  - {label: "Declaration", nodes: ["Ingress|rules and TLS|app", "IngressClass|which controller|info"]}
  - {label: "Implementation", nodes: ["Controller Pods|NGINX, Traefik, ALB|cp"]}
  - {label: "Backends", nodes: ["Service web|/|ok", "Service api|/api|ok"]}
@h An Ingress with TLS
```yaml title="ingress.yaml"
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt
spec:
  ingressClassName: nginx
  tls:
    - hosts: [shop.example.com]
      secretName: shop-tls
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service: {name: api, port: {number: 80}}
          - path: /
            pathType: Prefix
            backend:
              service: {name: web, port: {number: 80}}
```
@check
Why can the same Ingress YAML behave differently on two clusters? || Annotations and defaults belong to the controller, and each controller interprets them differently.
@end

@concept Ingress controllers
@plain
The controller watches Ingress objects and configures a proxy. Some run a proxy inside the cluster; some program a cloud load balancer.
@problem
Choosing wrongly gives the wrong features, cost or failure modes.
@does
- **In-cluster proxy** (NGINX, Traefik, HAProxy, Envoy based): one LoadBalancer Service in front, flexible, you operate it.
- **Cloud native** (AWS Load Balancer Controller): creates an ALB per Ingress (or per group), traffic goes straight to Pod IPs with `target-type: ip`.
- **Mesh gateways** (Istio, used by Kyma): Envoy with richer policies.
- Use `ingress.group.name` on AWS to share one ALB among Ingresses and save cost.
@diagram cmp
caption: Where the proxy lives
cards:
  - {h: "In-cluster proxy", kind: app, items: ["NGINX, Traefik, Envoy", "One NLB in front", "You scale and patch it"]}
  - {h: "Cloud load balancer", kind: ext, items: ["ALB via controller", "Managed data plane", "Cost per ALB"]}
  - {h: "Mesh gateway", kind: info, items: ["Istio ingress gateway", "mTLS, policies", "Used in Kyma"]}
@h ALB Ingress on EKS
```yaml title="alb-ingress.yaml"
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop-alb
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/group.name: shared
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:eu-west-1:111122223333:certificate/example
spec:
  ingressClassName: alb
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service: {name: web, port: {number: 80}}
```
@end

@concept Gateway API model
@plain
Gateway API splits routing into role-based objects: **GatewayClass** (the implementation), **Gateway** (listeners, owned by the platform team) and **routes** (owned by app teams).
@problem
Ingress mixes infrastructure, security and app routing in one object and leans on annotations. Platform and app teams need separate ownership and a portable standard.
@does
- `GatewayClass` names a controller, like StorageClass does for storage.
- `Gateway` defines listeners (port, protocol, hostname, TLS) and which namespaces may attach (`allowedRoutes`).
- `HTTPRoute`, `GRPCRoute`, `TLSRoute`, `TCPRoute` attach to a Gateway through `parentRefs`.
- Native features: header matching, redirects, rewrites, traffic weights, mirroring. Cross-namespace references need a `ReferenceGrant`.
- The core API (`gateway.networking.k8s.io/v1`) is GA; some route kinds remain in the experimental channel.
@diagram layers
caption: Who owns what
layers:
  - {label: "Infrastructure provider", nodes: ["GatewayClass|controller|cp"]}
  - {label: "Platform team", nodes: ["Gateway|listeners and TLS|info"]}
  - {label: "App teams", nodes: ["HTTPRoute shop|host and rules|app", "HTTPRoute blog|host and rules|app"]}
@h Gateway and route
```yaml title="gateway.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shared-gateway
  namespace: infra
spec:
  gatewayClassName: istio
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
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
  name: shop
  namespace: shop
spec:
  parentRefs:
    - name: shared-gateway
      namespace: infra
  hostnames: ["shop.example.com"]
  rules:
    - matches:
        - path: {type: PathPrefix, value: /api}
          headers:
            - {name: x-tenant, value: acme}
      backendRefs:
        - {name: api, port: 80}
    - filters:
        - type: RequestRedirect
          requestRedirect: {scheme: https, statusCode: 301}
      matches:
        - path: {type: PathPrefix, value: /old}
```
@check
Which object lets a team in namespace shop use a Gateway in namespace infra? || The Gateway's `allowedRoutes` must permit that namespace; the HTTPRoute then names the Gateway in `parentRefs`.
@end

@concept Ingress versus Gateway API
@plain
Ingress is frozen: still supported, but no new features. Gateway API is the successor and where new routing capabilities land.
@problem
Teams ask which to use for new work and how to migrate.
@does
- Prefer Gateway API for new clusters when your controller supports it (Istio, Envoy Gateway, Cilium, NGINX Gateway Fabric, GKE and AWS Gateway controllers).
- Keep Ingress where it works and migration offers no gain.
- The `ingress2gateway` tool converts many Ingress objects into Gateway resources.
- Check controller conformance reports rather than assuming a feature exists.
@diagram cmp
caption: Comparison
cards:
  - {h: "Ingress", kind: warn, items: ["One object, HTTP only", "Annotations for features", "Feature frozen"]}
  - {h: "Gateway API", kind: ok, items: ["Role oriented objects", "Typed filters, weights, grpc", "Active development"]}
@choose Which API
Ingress | simple HTTP routing on an existing controller | you need weights, header routing or shared Gateways
Gateway API | multi-team platforms, canaries, non-HTTP routes | your controller lacks conformance for the features you need
@h Migration helper
```bash title="Convert Ingress to Gateway objects" nocheck
ingress2gateway print --providers ingress-nginx --all-namespaces > gateway-objects.yaml
kubectl apply --dry-run=server -f gateway-objects.yaml
```
@end

@concept TLS and cert-manager
@plain
cert-manager requests certificates from an issuer (Let's Encrypt, a private CA, Vault, AWS PCA) and keeps them renewed as Kubernetes Secrets.
@problem
Manual certificate handling expires at the worst moment.
@does
- `Issuer` and `ClusterIssuer` describe the CA; `Certificate` asks for a certificate and names the Secret to store it.
- ACME **HTTP-01** proves control through a temporary route; **DNS-01** uses a DNS record and supports wildcards.
- Ingress annotation or Gateway listener annotation lets cert-manager create the Certificate automatically.
- It renews by default at two thirds of the lifetime. Monitor `certmanager_certificate_expiration_timestamp_seconds`.
@diagram seq
caption: Issuing a certificate with DNS-01
actors: ["cert-manager|controller|cp", "ACME CA|Let's Encrypt|ext", "DNS|Route 53|ext"]
steps:
  - "0>1: order for example.com | req"
  - "1>0: challenge token | resp"
  - "0>2: create TXT record | req"
  - "1>2: verify TXT | tls"
  - "1>0: signed certificate | resp"
@h Issuer and Certificate
```yaml title="cert-manager.yaml"
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: platform@example.com
    privateKeySecretRef:
      name: letsencrypt-account-key
    solvers:
      - dns01:
          route53:
            region: eu-west-1
---
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: shop
  namespace: shop
spec:
  secretName: shop-tls
  dnsNames: ["shop.example.com"]
  issuerRef:
    name: letsencrypt
    kind: ClusterIssuer
```
@end

@concept Kyma APIRule and Istio gateways
@plain
Kyma exposes workloads with its own APIRule custom resource, which creates Istio VirtualService and optional authentication rules behind the Kyma gateway.
@problem
On Kyma you rarely install an ingress controller, so you need to know the platform's native way to publish a service.
@does
- The Kyma API Gateway module manages an Istio ingress gateway and a default domain.
- An `APIRule` selects a Service, host and rules (access strategies such as JWT, or `no_auth` for public paths).
- You can alternatively write Istio `Gateway` and `VirtualService`, or Gateway API where the module supports it. Check your Kyma release notes, since the APIRule API version has changed (v1beta1 to v2).
- Identity usually comes from SAP IAS or XSUAA via JWT validation or an OAuth2 proxy.
@diagram flow
caption: A Kyma request path
nodes:
  - "Client|HTTPS|ext"
  - "Istio ingress gateway|Envoy|cp"
  - "JWT check|IAS issuer|warn"
  - "Service|your workload|app"
@h Inspect Kyma exposure
```bash title="Kyma gateways" lab
kubectl get apirules -A
kubectl get gateways.networking.istio.io -A
kubectl get virtualservices -A
kubectl get kyma default -n kyma-system -o jsonpath='{.status.modules}'
```
:::note
APIRule field names differ between versions. Run `kubectl explain apirule.spec --api-version=gateway.kyma-project.io/v2` on your cluster to see the live schema.
:::
@end
