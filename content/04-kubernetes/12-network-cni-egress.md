---
title: CNI choices, load balancers and egress
minutes: 40
objectives:
  - Compare overlay, routed and VPC native Pod networking
  - Place cloud load balancers correctly with target types and health checks
  - Control and troubleshoot egress traffic
---
Below Services and Ingress sits the real network. IP planning, load balancer behaviour and egress paths decide whether the cluster scales and stays reachable.

@concept Pod networking models
@plain
CNI plug-ins connect Pods in one of three ways: an overlay tunnel, plain routing, or addresses taken directly from the cloud network.
@problem
The choice affects IP consumption, performance, observability and how firewalls see Pod traffic.
@does
- **Overlay** (VXLAN, Geneve; Flannel, Calico, Cilium): Pod IPs are private to the cluster; needs encapsulation and sets a smaller MTU.
- **Routed** (Calico BGP): no encapsulation, routes advertised to the network.
- **VPC native** (AWS VPC CNI, Azure CNI): Pods get real VPC IPs; firewalls and security groups see Pods, but subnets can run out of addresses.
- Prefix delegation on the AWS VPC CNI assigns /28 blocks per ENI to raise Pod density.
@diagram cmp
caption: Trade-offs
cards:
  - {h: "Overlay", kind: info, items: ["Few IPs from the VPC", "Encapsulation overhead", "Works anywhere"]}
  - {h: "Routed", kind: app, items: ["Fast, simple path", "Needs routing support"]}
  - {h: "VPC native", kind: warn, items: ["Pods are VPC IPs", "Plan subnet sizes", "Security groups for Pods"]}
@h Check IP headroom
```bash title="EKS Pod IP usage" lab
kubectl -n kube-system get ds aws-node -o jsonpath='{.spec.template.spec.containers[0].env}' | head -c 600
kubectl get nodes -o custom-columns=NAME:.metadata.name,PODS:.status.allocatable.pods
aws ec2 describe-subnets --subnet-ids subnet-0abc --query 'Subnets[].AvailableIpAddressCount'
```
@end

@concept Cloud load balancers
@plain
A `type: LoadBalancer` Service or an Ingress makes a controller create a cloud load balancer. How it reaches Pods depends on the target type.
@problem
Traffic can take extra hops, lose the client IP or fail health checks if the load balancer and Service settings disagree.
@does
- **Instance targets** send to NodePorts, then kube-proxy forwards to a Pod. An extra hop, and `externalTrafficPolicy: Local` affects health.
- **IP targets** (VPC CNI) send straight to Pod IPs, skipping kube-proxy. Readiness gates keep Pods out of rotation until registered.
- NLB (layer 4) keeps source IP and is fast; ALB (layer 7) adds host routing, WAF and OIDC authentication.
- Pod readiness gates (`elbv2.k8s.aws/pod-readiness-gate-inject`) avoid dropped traffic during rollouts.
@diagram flow
caption: IP target path on EKS
nodes:
  - "Client|internet|ext"
  - "NLB or ALB|AWS|ext"
  - "Pod IP|direct|app"
@h Namespace readiness gate
```yaml title="readiness-gate-namespace.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    elbv2.k8s.aws/pod-readiness-gate-inject: enabled
```
@check
Why use IP targets rather than instance targets with the VPC CNI? || Traffic reaches Pods directly: one less hop, true source IP kept, and no dependence on NodePort and kube-proxy.
@end

@concept Egress and NAT
@plain
Egress is traffic leaving the cluster. By default Pods reach the internet through the node's route, usually a NAT gateway, so all Pods share a few source IPs.
@problem
Partners may whitelist your IP, and unexpected outbound connections are a data exfiltration risk.
@does
- On clouds the node subnet's NAT gateway sets the visible source IP; one NAT per zone avoids cross-zone cost.
- Private endpoints (VPC endpoints for S3, ECR) keep traffic off NAT and reduce cost.
- NetworkPolicy egress rules and DNS-aware policies (Cilium FQDN policy) restrict destinations.
- Istio `egress` gateway funnels outbound mesh traffic through a fixed point; Kyma can use it for stable egress identity.
@diagram flow
caption: Egress path with controls
nodes:
  - "Pod|app|app"
  - "NetworkPolicy|allowed destinations|warn"
  - "Node route|subnet|info"
  - "NAT gateway|fixed public IP|ext"
@h Find your egress IP
```bash title="What IP do outside systems see" lab
kubectl run egress --rm -it --image=curlimages/curl --restart=Never -- curl -s https://checkip.amazonaws.com
```
@end

@concept MTU, hairpin and common network faults
@plain
Some failures only appear with large packets, specific paths or when a Pod calls its own Service.
@problem
"Works for small requests, hangs for big ones" wastes days if you do not suspect MTU.
@does
- Overlay adds headers, so inner MTU must be lower than the node MTU (for example 1450 on a 1500 network). A mismatch breaks large TLS handshakes silently.
- **Hairpin**: a Pod calling its own Service IP needs the CNI to loop back; most do it correctly.
- Conntrack exhaustion shows `nf_conntrack: table full` in node logs.
- Cross-node failures with healthy same-node traffic point to security groups, firewall, or blocked overlay ports (UDP 4789, 8472, 6081).
@diagram flow
caption: Narrowing a network fault
numbered: true
nodes:
  - "Same node works|local path|ok"
  - "Cross node fails|overlay or firewall|bad"
  - "Small ok, big fails|MTU|warn"
  - "Random timeouts|conntrack|warn"
@h Probe MTU and path
```bash title="From a debug Pod" lab
kubectl run net --rm -it --image=nicolaka/netshoot --restart=Never -- bash
# inside
ping -M do -s 1400 10.0.2.9      # do not fragment; lower the size until it passes
ip link show eth0 | grep mtu
tracepath 10.0.2.9
```
@end

@concept Service mesh and network observability preview
@plain
A mesh adds a proxy to each Pod (or node) to supply mTLS, retries and metrics without app changes. eBPF tools show flows without a mesh.
@problem
You cannot see or secure service-to-service traffic from the Service object alone.
@does
- Istio and Linkerd use sidecars or ambient mode (Istio) with per-node ztunnel for L4 mTLS and optional waypoint proxies for L7.
- Kyma ships an Istio module, so sidecar injection is a namespace label (`istio-injection=enabled`).
- Cilium Hubble and Retina show flow level visibility based on eBPF.
- A mesh costs CPU, memory and operational complexity; adopt it for a clear need such as mTLS everywhere.
@diagram layers
caption: Where the proxy sits
layers:
  - {label: "Sidecar mode", nodes: ["App|container|app", "Envoy sidecar|in each Pod|info"]}
  - {label: "Ambient mode", nodes: ["ztunnel|per node L4|info", "waypoint|optional L7|info"]}
@h Enable sidecars in a namespace
```bash title="Label a namespace for Istio injection" lab
kubectl label namespace shop istio-injection=enabled
kubectl rollout restart deployment -n shop        # Pods must be recreated
kubectl get pods -n shop -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.containers[*].name}{"\n"}{end}'
```
@end
