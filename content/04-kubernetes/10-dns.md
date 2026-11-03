---
title: DNS and service discovery
minutes: 35
objectives:
  - Explain Service and Pod DNS names and the search path
  - Understand ndots and why it multiplies lookups
  - Tune CoreDNS and NodeLocal DNSCache
---
Almost every connection in a cluster begins with a DNS lookup. DNS problems look like random application failures, so know how it works.

@concept Cluster DNS names
@plain
CoreDNS answers names for Services and Pods inside the cluster domain, `cluster.local` by default.
@problem
Hard coding IPs breaks as soon as a Pod restarts. Names give stable discovery.
@does
- Service: `<svc>.<namespace>.svc.cluster.local` returns the ClusterIP (or the Pod IPs for headless).
- Pod: `<ip-with-dashes>.<namespace>.pod.cluster.local`.
- StatefulSet Pod: `<pod>.<svc>.<namespace>.svc.cluster.local`.
- SRV records exist for named ports: `_http._tcp.web.shop.svc.cluster.local`.
- Within the same namespace the short name `web` works; across namespaces use `web.shop`.
@diagram flow
caption: A lookup from a Pod
nodes:
  - "App|calls web|app"
  - "/etc/resolv.conf|nameserver 10.96.0.10|info"
  - "CoreDNS|cluster zone|cp"
  - "Answer|ClusterIP|ok"
@h What the Pod sees
```bash title="Pod resolver config" lab
kubectl exec deploy/web -- cat /etc/resolv.conf
kubectl run dns --rm -it --image=busybox:1.36 --restart=Never -- nslookup kubernetes.default
kubectl get svc -n kube-system kube-dns
```
@end

@concept ndots and the search path
@plain
`options ndots:5` means any name with fewer than five dots is first tried with each search domain appended, before being tried as is.
@problem
This makes short names convenient but turns a lookup of `api.example.com` into several wasted queries that all fail with NXDOMAIN first.
@does
- Default search list: `<ns>.svc.cluster.local svc.cluster.local cluster.local` plus any node domain.
- Looking up `api.example.com` (2 dots) tries three or more cluster suffixes before the real name; with A and AAAA that is many queries.
- Fixes: use a trailing dot (`api.example.com.`), set a lower `ndots` in `dnsConfig`, or use NodeLocal DNSCache.
- Also lower dependence on external names that fail slowly.
@diagram seq
caption: One external lookup with ndots 5
actors: ["App|getaddrinfo|app", "CoreDNS|cluster|cp"]
steps:
  - "0>1: api.example.com.shop.svc.cluster.local | req"
  - "1>0: NXDOMAIN | bad"
  - "0>1: api.example.com.svc.cluster.local | req"
  - "1>0: NXDOMAIN | bad"
  - "0>1: api.example.com | req"
  - "1>0: answer | resp"
@h Set ndots for a Pod
```yaml title="dnsconfig.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: client
spec:
  dnsPolicy: ClusterFirst
  dnsConfig:
    options:
      - name: ndots
        value: "2"
      - name: single-request-reopen
  containers:
    - name: app
      image: busybox:1.36
      command: ["sleep", "3600"]
```
@check
Why is `api.example.com.` with a trailing dot faster? || It is a fully qualified name, so the resolver skips the search list.
@end

@concept CoreDNS configuration
@plain
CoreDNS is a plug-in based DNS server configured by a `Corefile` in a ConfigMap. Each plug-in does one job: cluster zone, cache, forward, health.
@problem
You may need to forward a corporate domain to an internal resolver, or rewrite names.
@does
- The `kubernetes` plug-in serves the cluster zone from the API.
- `forward . /etc/resolv.conf` sends everything else to the node's resolvers.
- `cache 30` caches answers; `errors`, `log`, `prometheus :9153` help observability.
- Add stub zones for private domains, then restart CoreDNS.
- On Kyma and EKS CoreDNS is managed; customisations may use a supported `coredns-custom` ConfigMap or add-on config. Check the platform docs.
@diagram layers
caption: CoreDNS plug-in chain
layers:
  - {label: "Client", nodes: ["Pod resolver|port 53|app"]}
  - {label: "Plug-ins", nodes: ["errors|log failures|info", "cache|30 s|info", "kubernetes|cluster.local|cp", "forward|upstream|ext"]}
@h Add a stub zone
```yaml title="coredns-stub.yaml"
apiVersion: v1
kind: ConfigMap
metadata:
  name: coredns-custom
  namespace: kube-system
data:
  corp.server: |
    corp.example.com:53 {
        errors
        cache 30
        forward . 10.20.0.2 10.20.0.3
    }
```
:::note
The `coredns-custom` name and the import mechanism depend on the platform (AKS and Gardener use it; vanilla CoreDNS needs an `import` line in the Corefile). Verify yours before applying.
:::
@end

@concept DNS scale and NodeLocal DNSCache
@plain
Heavy lookup traffic can overload CoreDNS and conntrack. NodeLocal DNSCache runs a caching agent on every node.
@problem
UDP DNS through NAT hits conntrack races that cause five second timeouts, and a few CoreDNS Pods become a bottleneck.
@does
- Pods query a link-local address on their own node; cache hits return immediately, misses go upstream over TCP.
- Run enough CoreDNS replicas, spread across zones, and consider cluster-proportional-autoscaler to scale them with node count.
- Watch `coredns_dns_request_duration_seconds` and `coredns_dns_responses_total{rcode="SERVFAIL"}`.
@diagram flow
caption: With a node cache
nodes:
  - "Pod|lookup|app"
  - "node-local-dns|cache hit|ok"
  - "CoreDNS|on miss|cp"
  - "Upstream DNS|external names|ext"
@h Check health
```bash title="CoreDNS status" lab
kubectl -n kube-system get deploy coredns
kubectl -n kube-system logs deploy/coredns --tail=20
kubectl -n kube-system top pods -l k8s-app=kube-dns
kubectl -n kube-system get ds node-local-dns
```
@end

@concept Debugging DNS
@plain
DNS failures show as timeouts, NXDOMAIN or slow requests. Separate the layers: Pod resolver, CoreDNS, upstream.
@problem
Applications report "unknown host" without saying whether the name, the server or the network is wrong.
@does
- Run `nslookup` and `dig` from a debug Pod, in the same namespace and with the same `dnsPolicy`.
- NXDOMAIN: wrong name or namespace. SERVFAIL: upstream problem. Timeout: NetworkPolicy blocking UDP/TCP 53 egress to CoreDNS, or CoreDNS down.
- A default-deny egress policy must explicitly allow DNS.
- Alpine (musl) images resolve slightly differently from glibc; test in the real image when it matters.
@diagram flow
caption: Isolating the failure
numbered: true
nodes:
  - "Resolv.conf correct|nameserver and search|info"
  - "dig @CoreDNS|server answers|info"
  - "dig @upstream|outside works|info"
  - "Policy allows 53|egress rule|warn"
@h Commands
```bash title="Test from a debug Pod" lab
kubectl run dig --rm -it --image=nicolaka/netshoot --restart=Never -- bash
# inside
dig web.shop.svc.cluster.local +short
dig @10.96.0.10 example.com +time=2 +tries=1
dig +search web.shop
```
@end

@concept ExternalDNS and public names
@plain
ExternalDNS watches Services, Ingresses and Gateway routes and creates matching records in Route 53, Cloud DNS or similar.
@problem
Hand-editing public DNS for every new hostname is slow and drifts from what the cluster serves.
@does
- Reads the `external-dns.alpha.kubernetes.io/hostname` annotation or the host in an Ingress or HTTPRoute.
- Creates A, AAAA or CNAME records pointing at the load balancer, and owns them with TXT markers.
- `--policy=upsert-only` prevents deletions; `--txt-owner-id` separates clusters sharing a zone.
- On Kyma the API Gateway module and Gardener DNS management serve a similar purpose for default domains.
@diagram flow
caption: Publishing a hostname
nodes:
  - "Ingress or Service|host shop.example.com|app"
  - "ExternalDNS|watches|cp"
  - "Cloud DNS API|Route 53|ext"
  - "Record|points to LB|ok"
@h Annotation example
```yaml title="svc-dns.yaml"
apiVersion: v1
kind: Service
metadata:
  name: web-public
  annotations:
    external-dns.alpha.kubernetes.io/hostname: shop.example.com
    external-dns.alpha.kubernetes.io/ttl: "300"
spec:
  type: LoadBalancer
  selector:
    app: web
  ports:
    - {port: 443, targetPort: 8080}
```
@end
