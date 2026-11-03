---
title: CNI deep dive, Cilium, Calico and eBPF
minutes: 55
objectives:
  - Explain what a CNI plugin does when a Pod starts
  - Compare overlay, routed and eBPF dataplanes and choose between Cilium and Calico
  - Replace kube-proxy and observe traffic with Hubble
---
The network plugin decides how Pods get addresses, how they reach each other and how policy is enforced. Most hard production network problems are CNI problems.

@concept What a CNI plugin does
@plain
The Container Network Interface is a small contract. When the runtime creates a Pod sandbox it calls the plugin with ADD, and the plugin creates the network interface and assigns an IP.
@problem
Kubernetes defines the network model (every Pod can reach every Pod without NAT) but not how to build it. Plugins fill that gap in different ways.
@does
- The runtime reads config from `/etc/cni/net.d` and runs binaries from `/opt/cni/bin`.
- Calls are `ADD`, `DEL`, `CHECK` and `VERSION`. IPAM (address management) is often a separate delegated plugin.
- Most modern CNIs run an agent DaemonSet that programs routes, iptables or eBPF, and the binary only talks to that agent.
- A node stays `NotReady` with "cni plugin not initialized" until a config file appears.
@diagram seq
caption: Pod sandbox creation
actors: ["Kubelet|CRI call|cp", "Runtime|containerd|app", "CNI plugin|binary and agent|info"]
steps:
  - "0>1: RunPodSandbox | req"
  - "1>2: ADD with netns path | req"
  - "2>2: veth, IP, routes | warn"
  - "2>1: result with IP | resp"
  - "1>0: sandbox ready | resp"
@h Look at a node
```bash title="Inspect CNI config on a node" lab
kubectl debug node/NODE -it --image=busybox:1.36 -- sh -c 'ls /host/etc/cni/net.d /host/opt/cni/bin'
kubectl get pods -n kube-system -o wide | grep -E 'cilium|calico|aws-node|flannel'
kubectl get nodes -o custom-columns=NAME:.metadata.name,PODCIDR:.spec.podCIDR
```
@check
Why is a new node NotReady when the CNI is missing? || The kubelet reports the network plugin as not ready until a CNI config exists, so no Pods can get an interface.
@end

@concept Overlay, routed and native networking
@plain
Pod traffic between nodes either travels inside a tunnel (overlay), is routed using the underlying network, or uses cloud-native addresses.
@problem
Choosing wrongly gives extra overhead or IP exhaustion, or needs router changes you cannot make.
@does
- **Overlay** (VXLAN or Geneve): works anywhere, adds about 50 bytes of header, so watch the MTU.
- **Routed** (BGP in Calico, or direct routes on one L2 network): no encapsulation, needs the fabric to carry or learn Pod routes.
- **Cloud native**: AWS VPC CNI gives Pods real VPC addresses from ENIs, so security groups and flow logs work, but subnets can run out of IPs. Prefix delegation and custom networking reduce that pressure.
- MTU mismatches show as large requests hanging while small ones work.
@diagram cmp
caption: Dataplane styles
cards:
  - {h: "Overlay", kind: info, items: ["VXLAN or Geneve", "Works on any network", "Lower MTU and CPU cost"]}
  - {h: "Routed or BGP", kind: ok, items: ["No encapsulation", "Needs router support", "Good for on-premises"]}
  - {h: "VPC native", kind: warn, items: ["Pod gets VPC IP", "Security groups apply", "Subnet IP planning needed"]}
@h Check MTU
```bash title="Detect MTU trouble" lab
kubectl exec -n shop POD -- ping -M do -s 1400 -c 3 10.0.5.20
kubectl exec -n shop POD -- ip link show eth0 | head -2
```
@choose Dataplane
Overlay | mixed networks and quick start | you can route pod CIDRs and want lowest overhead
BGP routed | on-premises with BGP capable switches | the network team cannot peer with nodes
VPC native (EKS) | you need security groups per Pod and VPC visibility | subnets are small and IPs scarce
@end

@concept Calico
@plain
Calico is a mature CNI known for routing with BGP and a rich policy engine. It can use iptables, nftables or an eBPF dataplane.
@problem
Teams needing predictable routing, large scale and policy beyond standard NetworkPolicy.
@does
- Components: `calico-node` (Felix for policy, BIRD for BGP), Typha for large clusters, and the IPAM.
- Modes: IP-in-IP, VXLAN or unencapsulated BGP.
- Extra CRDs: `GlobalNetworkPolicy`, `NetworkPolicy` with ordering, deny rules and host endpoint protection.
- `calicoctl` (or `kubectl calico`) inspects nodes and IP pools.
@diagram layers
caption: Calico pieces
layers:
  - {label: "Control", nodes: ["Calico API|CRDs and IPAM|cp", "Typha|fan-out cache|info"]}
  - {label: "Each node", nodes: ["Felix|programs policy|app", "BIRD|BGP routes|app", "Dataplane|iptables or eBPF|ok"]}
@h IP pool and global policy
```yaml title="Calico pool and a default-deny policy" nocheck
apiVersion: projectcalico.org/v3
kind: IPPool
metadata:
  name: default-pool
spec:
  cidr: 10.244.0.0/16
  ipipMode: Never
  vxlanMode: CrossSubnet
  natOutgoing: true
---
apiVersion: projectcalico.org/v3
kind: GlobalNetworkPolicy
metadata:
  name: default-deny-app-namespaces
spec:
  selector: projectcalico.org/namespace starts with 'app-'
  types: [Ingress, Egress]
```
@end

@concept Cilium and eBPF
@plain
Cilium uses eBPF, small verified programs that run inside the Linux kernel, to route, filter and observe traffic without long iptables chains.
@problem
iptables rule lists grow linearly with Services, making updates slow and packet paths long in big clusters. Policy by IP breaks when Pods churn.
@does
- Identity based policy: Pods get a numeric identity from their labels, and policy matches identities, not IPs.
- eBPF programs attach to the network device and socket layer for load balancing, policy and visibility.
- Needs a modern kernel (see the Cilium requirements page). Managed offerings may restrict modes.
- Extras: `CiliumNetworkPolicy` with L7 rules (HTTP, DNS, Kafka), transparent encryption (WireGuard or IPsec), Cluster Mesh, Gateway API and Hubble.
@diagram flow
caption: Packet path with eBPF
nodes:
  - "Pod|veth|app"
  - "eBPF at tc hook|policy and service lookup|info"
  - "Destination Pod|same or other node|ok"
  - "Hubble|flow events|ext"
@h Install and verify
```bash title="Cilium CLI checks" lab
cilium status --wait
cilium config view | grep -E 'kube-proxy-replacement|tunnel|routing-mode'
cilium connectivity test
```
:::note
Settings and Helm values change between Cilium releases. Take the install values from the docs for your version.
:::
@check
What does identity based policy avoid? || Dependence on Pod IPs, which change constantly. Policy follows label-derived identities.
@end

@concept Replacing kube-proxy
@plain
kube-proxy programs iptables or IPVS rules to turn Service addresses into Pod addresses. Cilium and Calico eBPF can do this in the kernel instead.
@problem
Large Service counts make iptables updates slow, and DNAT with conntrack costs CPU and complicates source IPs.
@does
- Cilium: `kubeProxyReplacement=true` and `k8sServiceHost`/`k8sServicePort`, since there is no kube-proxy to reach the API on first start.
- Gains: O(1) lookups, Maglev consistent hashing, direct server return, and preserving client source IP for NodePort.
- Remove the kube-proxy DaemonSet and flush its leftovers (reboot nodes or clean iptables).
- On managed clusters check whether kube-proxy can be disabled (EKS add-on can be removed, Gardener has a shoot setting).
- The newer nftables mode of kube-proxy is another way to improve scale; check your Kubernetes version.
@diagram flow
caption: Service lookup in each design
nodes:
  - "Client Pod|dials ClusterIP|app"
  - "iptables or IPVS|kube-proxy rules|warn"
  - "eBPF map|Cilium service table|ok"
  - "Backend Pod|chosen endpoint|app"
@h Helm values (shape)
```yaml title="Cilium values for kube-proxy replacement" nocheck
kubeProxyReplacement: true
k8sServiceHost: api.cluster.example.com
k8sServicePort: 443
routingMode: tunnel
tunnelProtocol: vxlan
hubble:
  enabled: true
  relay:
    enabled: true
```
@end

@concept Observability with Hubble
@plain
Hubble shows network flows between Pods, including which policy allowed or dropped them, using data from the eBPF dataplane.
@problem
When NetworkPolicy blocks traffic, tcpdump on a node is slow and does not know Pod names or verdicts.
@does
- `hubble observe` streams flows filtered by namespace, Pod, verdict (`FORWARDED`, `DROPPED`) and protocol.
- Shows DNS queries and HTTP when L7 visibility is enabled.
- The UI draws a service map. Metrics export to Prometheus.
- Flow data may contain sensitive endpoints, so protect access.
@diagram flow
caption: Finding a policy drop
nodes:
  - "Client cannot connect|timeout|bad"
  - "hubble observe --verdict DROPPED|flows|info"
  - "Policy name in reason|which rule|warn"
  - "Add allow rule|fix|ok"
@h Commands
```bash title="Find dropped flows" lab
cilium hubble port-forward &
hubble observe --namespace shop --verdict DROPPED --last 20
hubble observe --from-pod shop/web --to-pod shop/api --protocol tcp
```
@check
Which verdict shows a NetworkPolicy block? || DROPPED, along with the policy denial reason in the flow.
@end

@concept Choosing and migrating a CNI
@plain
A CNI is a foundation decision. Changing it later usually means rebuilding nodes or clusters, so decide early and test upgrades.
@problem
Wrong choice leads to IP exhaustion, missing policy features or lack of support from your platform.
@does
- Use what your platform supports: EKS defaults to VPC CNI (Cilium can chain or replace it); Gardener lets you choose Calico or Cilium per shoot; Kyma on Gardener commonly uses the provider's default network setup.
- Evaluate: policy features (L7, FQDN, host policy), observability, encryption, scale, kernel support, and operations skills.
- Migration: new cluster and move workloads is safest. Cilium also documents node-by-node migration with overlapping Pod CIDRs; read it fully and rehearse.
- Keep NetworkPolicy tests in CI so a CNI change can be verified.
@diagram flow
caption: Decision path
nodes:
  - "Platform default|supported and simple|ok"
  - "Need L7 or FQDN policy|Cilium or Calico enterprise features|info"
  - "Need BGP routing|Calico or Cilium BGP|info"
  - "Migrate|new cluster or rehearsed rolling|warn"
@choose CNI choice
VPC CNI | EKS with security groups per Pod | IPs are scarce and you need eBPF features
Cilium | eBPF, L7 policy, Hubble, kube-proxy replacement | kernels are old or the platform does not allow it
Calico | BGP, mature policy model, mixed environments | you want built-in L7 and flow observability
@end
