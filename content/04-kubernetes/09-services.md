---
title: Services and kube-proxy
minutes: 50
objectives:
  - Choose the right Service type and write its manifest
  - Explain how kube-proxy implements ClusterIPs in iptables, IPVS and nftables modes
  - Read EndpointSlices to debug a Service with no traffic
---
Pod IPs are temporary. A Service gives a set of Pods one stable address and load balances across the healthy ones.

@concept The Kubernetes network model
@plain
Every Pod gets its own IP. Any Pod can reach any other Pod directly without NAT, and nodes can reach all Pods.
@problem
Without a simple flat model, applications would need port mapping and address translation logic.
@does
- The CNI plug-in implements Pod to Pod routing (overlay, routed or cloud-native VPC addresses).
- Services add a stable virtual IP on top; NetworkPolicy restricts the flat network.
- Four traffic types: container to container (localhost), Pod to Pod, Pod to Service, external to Service.
- On EKS with the VPC CNI each Pod IP is a VPC address, so IP exhaustion in subnets is a real limit.
@diagram layers
caption: Layers of Kubernetes networking
layers:
  - {label: "External", nodes: ["Ingress or Gateway|HTTP routing|ext", "LoadBalancer|cloud L4|ext"]}
  - {label: "Service layer", nodes: ["ClusterIP|virtual IP|cp", "kube-proxy|rules on each node|cp"]}
  - {label: "Pod network", nodes: ["CNI|Pod to Pod|app", "Pod CIDRs|IP ranges|env"]}
@h See addresses
```bash title="Pod and node IPs" lab
kubectl get pods -A -o wide | head
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.podCIDR}{"\n"}{end}'
kubectl cluster-info dump | grep -m2 -E 'service-cluster-ip-range|cluster-cidr'
```
@end

@concept Service types
@plain
A Service picks Pods with a label selector and exposes them in one of four ways: `ClusterIP`, `NodePort`, `LoadBalancer` or `ExternalName`.
@problem
Clients need one durable address, whether inside the cluster, on node ports or on the internet.
@does
- **ClusterIP** (default): virtual IP reachable only inside the cluster.
- **NodePort**: also opens a port (30000 to 32767) on every node.
- **LoadBalancer**: also asks the cloud to create an external load balancer.
- **ExternalName**: a DNS CNAME to an outside name, no proxying.
- **Headless** (`clusterIP: None`): no virtual IP; DNS returns Pod IPs.
@diagram cmp
caption: Each type builds on the previous
cards:
  - {h: "ClusterIP", kind: app, items: ["Internal virtual IP", "Default"]}
  - {h: "NodePort", kind: info, items: ["ClusterIP plus a node port", "Rarely exposed directly"]}
  - {h: "LoadBalancer", kind: ok, items: ["NodePort plus cloud LB", "One LB per Service, costs money"]}
  - {h: "ExternalName", kind: ext, items: ["CNAME only", "No ports or selector"]}
@h ClusterIP and LoadBalancer
```yaml title="services.yaml"
apiVersion: v1
kind: Service
metadata:
  name: web
spec:
  selector:
    app: web
  ports:
    - name: http
      port: 80
      targetPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: web-public
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-type: external
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
spec:
  type: LoadBalancer
  loadBalancerClass: service.k8s.aws/nlb
  externalTrafficPolicy: Local
  selector:
    app: web
  ports:
    - {name: https, port: 443, targetPort: 8080}
```
:::note
The annotations above are for the AWS Load Balancer Controller. Other clouds and Kyma use different annotations, so check the provider documentation.
:::
@check
Which port is `port` and which is `targetPort`? || `port` is what clients call on the Service; `targetPort` is the container port receiving traffic.
@end

@concept How kube-proxy implements a Service
@plain
kube-proxy runs on each node and programs the kernel so that traffic to a Service IP is redirected to one of its Pod IPs. It does not carry traffic itself in the common modes.
@problem
A virtual IP exists on no interface. Something must translate it to a real Pod on every node, and keep up as Pods come and go.
@does
- Watches Services and EndpointSlices and rewrites kernel rules (DNAT) on change.
- **iptables mode** (default for a long time): chains of rules with random probability; lookup cost grows linearly with Services.
- **IPVS mode**: kernel load balancer with hash tables and algorithms like round robin and least connection; scales better.
- **nftables mode**: newer, faster rule updates; GA in Kubernetes 1.33.
- Some CNIs (Cilium) replace kube-proxy with eBPF.
@diagram seq
caption: A Pod calls a Service IP
actors: ["Client Pod|10.0.1.5|app", "Node kernel|DNAT rules|cp", "Backend Pod|10.0.2.9|ok"]
steps:
  - "0>1: to 10.96.0.10:80 | req"
  - "note 1..1: pick endpoint, rewrite destination"
  - "1>2: to 10.0.2.9:8080 | req"
  - "2>0: reply, conntrack reverses | resp"
@h Inspect the rules
```bash title="On a node" nocheck
kubectl -n kube-system get cm kube-proxy -o jsonpath='{.data.config\.conf}' | grep mode
iptables -t nat -L KUBE-SERVICES -n | head
ipvsadm -Ln | head            # when mode is ipvs
nft list table ip kube-proxy | head   # when mode is nftables
conntrack -L | head
```
@check
Why do conntrack table limits matter? || NAT'd connections are tracked per flow; a full table drops new connections, often seen as random timeouts under load.
@end

@concept EndpointSlices
@plain
An EndpointSlice lists the IPs, ports and readiness of Pods behind a Service. The old single `Endpoints` object is replaced by sharded slices.
@problem
One Endpoints object for a Service with thousands of Pods had to be rewritten and shipped to every node on each change.
@does
- Each slice holds up to 100 endpoints by default, so a change only updates one small object.
- Each endpoint has conditions `ready`, `serving` and `terminating`, plus topology hints (zone, node).
- The EndpointSlice controller creates them from the Service selector; kube-proxy and service meshes consume them.
- A Service with no slices or no ready endpoints is the first thing to check when traffic fails.
@diagram flow
caption: From Pods to node rules
nodes:
  - "Pods|ready or not|app"
  - "EndpointSlice controller|builds slices|cp"
  - "EndpointSlice|ip, port, conditions|info"
  - "kube-proxy|programs node|cp"
@h Debug a Service
```bash title="Service has no traffic" lab
kubectl get svc web -o wide
kubectl get endpointslices -l kubernetes.io/service-name=web
kubectl get endpointslices -l kubernetes.io/service-name=web -o jsonpath='{range .items[*].endpoints[*]}{.addresses}{" ready="}{.conditions.ready}{"\n"}{end}'
kubectl get pods -l app=web --show-labels      # do the labels match the selector
```
:::tip
Empty endpoints almost always mean the selector does not match the Pod labels, or readiness is failing. Check these before suspecting the network.
:::
@end

@concept Traffic policies and session behaviour
@plain
Traffic policies control which endpoints a Service may use: any, only local to the node, or preferring the same zone.
@problem
Cross-zone traffic costs money and adds latency, and node-to-node hops hide the real client IP.
@does
- `externalTrafficPolicy: Local` sends external traffic only to Pods on the receiving node, preserves the client source IP and avoids a hop. Nodes without Pods fail the load balancer health check.
- `internalTrafficPolicy: Local` does the same for in-cluster callers.
- `trafficDistribution: PreferClose` (beta in 1.31, GA in 1.33) prefers endpoints in the caller's zone; falls back if none are healthy.
- `sessionAffinity: ClientIP` pins a client to one Pod for a time; it is crude, prefer app level sessions.
@diagram cmp
caption: External traffic policy
cards:
  - {h: "Cluster (default)", kind: info, items: ["Any node, any Pod", "Extra hop, source IP lost", "Even spread"]}
  - {h: "Local", kind: ok, items: ["Only Pods on this node", "Source IP kept", "Uneven spread possible"]}
@h Zone aware routing
```yaml title="zone-aware-service.yaml"
apiVersion: v1
kind: Service
metadata:
  name: api
spec:
  selector:
    app: api
  trafficDistribution: PreferClose
  ports:
    - {port: 80, targetPort: 8080}
```
@end

@concept Debugging Service connectivity
@plain
A methodical order finds a broken Service quickly: Pod, selector, endpoints, port, DNS, policy.
@problem
"Connection refused" and timeouts mean different things, and guessing wastes hours.
@does
- **Connection refused**: reached something, nothing listening on that port (wrong `targetPort`).
- **Timeout**: packets dropped, usually NetworkPolicy, security group, or no endpoints.
- **Could not resolve host**: DNS or wrong namespace in the name.
- Test from a throw-away Pod in the same namespace and compare Pod IP, Service IP and DNS name.
@diagram flow
caption: Working outward
numbered: true
nodes:
  - "Pod IP works|app is up|ok"
  - "Service IP works|selector and endpoints|info"
  - "DNS name works|CoreDNS|info"
  - "From outside|LB, ingress, policy|warn"
@h Layered test
```bash title="Curl each layer" lab
kubectl run net --rm -it --image=nicolaka/netshoot --restart=Never -- bash
# inside the shell
curl -sv http://10.0.2.9:8080/healthz      # Pod IP
curl -sv http://web.shop.svc/healthz       # service DNS
nslookup web.shop.svc
```
@end
