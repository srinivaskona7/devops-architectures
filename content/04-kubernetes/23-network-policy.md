---
title: NetworkPolicy and segmentation
minutes: 40
objectives:
  - Write default deny and allow rules for ingress and egress
  - Explain selectors, namespaces, ipBlock and how rules combine
  - Verify policies and know the limits of the standard API
---
By default every Pod can talk to every other Pod. NetworkPolicy turns the flat network into a set of allowed paths.

@concept How NetworkPolicy works
@plain
A NetworkPolicy selects Pods and lists which traffic is allowed to or from them. Once a Pod is selected by any policy for a direction, everything not allowed in that direction is denied.
@problem
A compromised Pod in one namespace can scan and attack every other Pod in the cluster.
@does
- Needs a CNI that enforces policy (Calico, Cilium, AWS VPC CNI with network policy enabled, Antrea). With a plain Flannel the object is accepted and does nothing.
- `podSelector` chooses the protected Pods; `policyTypes` says Ingress, Egress or both.
- Policies are additive allow lists; there is no deny rule. Order does not matter.
- Allows are by Pod labels, namespace labels and IP blocks, and by port and protocol.
@diagram flow
caption: Isolation switches on when selected
nodes:
  - "No policy|all traffic allowed|bad"
  - "Policy selects Pod|ingress denied except listed|warn"
  - "Add allow rules|only needed paths|ok"
@h Default deny for a namespace
```yaml title="default-deny.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: shop
spec:
  podSelector: {}
  policyTypes: ["Ingress", "Egress"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
  namespace: shop
spec:
  podSelector: {}
  policyTypes: ["Egress"]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - {protocol: UDP, port: 53}
        - {protocol: TCP, port: 53}
```
:::warn
Default-deny egress without a DNS allow rule breaks every lookup. Add the DNS policy in the same change.
:::
@end

@concept Allowing application traffic
@plain
Add small allow policies per tier: frontend to API, API to database, ingress controller to frontend.
@problem
Deny-all alone stops the application working. You must declare the real call graph.
@does
- `from` and `to` entries are OR'd; within one entry `namespaceSelector` and `podSelector` together are AND'd.
- Select the Ingress controller or mesh gateway namespace so external traffic can reach front-end Pods.
- Use `ipBlock` with `except` for external CIDRs; Pod IPs are not matched by ipBlock in most implementations.
- Name ports, and keep policies next to the workload manifests so they change together.
@diagram flow
caption: A three-tier allow chain
nodes:
  - "Ingress gateway|namespace istio-system|ext"
  - "web|allowed from gateway|app"
  - "api|allowed from web|app"
  - "db|allowed from api|app"
@h API tier policy
```yaml title="allow-api.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-allow
  namespace: shop
spec:
  podSelector:
    matchLabels:
      app: api
  policyTypes: ["Ingress", "Egress"]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app: web
      ports:
        - {protocol: TCP, port: 8080}
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: db
      ports:
        - {protocol: TCP, port: 5432}
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except: ["169.254.169.254/32", "10.0.0.0/8"]
      ports:
        - {protocol: TCP, port: 443}
```
@check
In one `from` item you list namespaceSelector and podSelector together. AND or OR? || AND: the Pod must match both. Separate list items are OR.
@end

@concept Testing and observing policies
@plain
Policies are easy to get wrong and fail silently. Test with real traffic and observe drops.
@problem
A typo in a label silently opens or closes a path.
@does
- Run a temporary Pod with the same labels as the caller and `curl` the target; also test a forbidden path.
- Cilium Hubble and Calico flow logs show allowed and denied flows; AWS VPC CNI writes policy decision logs when enabled.
- Tools: `netpol-analyzer`, Cilium's network policy editor, `kubectl describe networkpolicy`.
- Include policy tests in CI against a kind cluster with Calico or Cilium.
@diagram flow
caption: Test loop
numbered: true
nodes:
  - "Write policy|small and labelled|info"
  - "Positive test|expected path works|ok"
  - "Negative test|other path fails|ok"
  - "Observe flows|Hubble or logs|info"
@h Probe
```bash title="Positive and negative test" lab
kubectl -n shop run t1 --rm -it --image=curlimages/curl --labels=app=web --restart=Never -- curl -s -m 3 http://api:8080/healthz
kubectl -n shop run t2 --rm -it --image=curlimages/curl --labels=app=other --restart=Never -- curl -s -m 3 http://api:8080/healthz
kubectl -n shop describe networkpolicy api-allow
hubble observe --namespace shop --verdict DROPPED --last 20
```
@end

@concept Limits of NetworkPolicy and extended policies
@plain
The standard API is layer 3 and 4 only. Larger needs use CNI-specific or newer APIs.
@problem
You may need to allow by DNS name, apply cluster-wide defaults or add explicit denies.
@does
- No FQDN rules, no HTTP path rules, no logging, and no cluster-scoped policy in the base API.
- Cilium `CiliumNetworkPolicy` and Calico `GlobalNetworkPolicy` add FQDN, L7, deny and ordered rules.
- The upstream **AdminNetworkPolicy** and **BaselineAdminNetworkPolicy** APIs (network-policy-api project, still alpha) add cluster-scoped allow, deny and default behaviour.
- A service mesh adds identity-based **AuthorizationPolicy** (Istio) at L7 with mTLS, used in Kyma.
@diagram layers
caption: Layers of network control
layers:
  - {label: "L3 and L4", nodes: ["NetworkPolicy|portable base|ok"]}
  - {label: "CNI extensions", nodes: ["Cilium policy|FQDN and L7|info", "Calico global policy|ordered deny|info"]}
  - {label: "Mesh", nodes: ["Istio AuthorizationPolicy|identity and path|info"]}
@h Istio AuthorizationPolicy
```yaml title="authorizationpolicy.yaml"
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: api-from-web
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
            paths: ["/orders/*"]
```
@end
