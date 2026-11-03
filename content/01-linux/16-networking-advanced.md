---
title: Advanced Linux networking
minutes: 55
objectives:
  - Build isolated networks with namespaces, veth pairs and bridges
  - Use policy routing and multiple routing tables
  - Read the conntrack table and understand NAT state
  - Shape and delay traffic with tc for failure testing
---
This is how container networking works underneath. The labs need root on a Linux machine or VM (not macOS directly) and are safe because they only create temporary interfaces. Clean-up steps are included.

@concept Network namespaces
@plain
A **network namespace** is a private copy of the network stack: its own interfaces, routes, firewall rules and ports. Each container or pod gets one.
@problem
Two services both wanting port 80 on one host would collide, and one should not be able to see the other's traffic.
@does
- `ip netns add` creates one; `ip netns exec name cmd` runs a command inside.
- A new namespace has only a loopback interface, and it is down until you bring it up.
- Kubernetes pods share one namespace between their containers, which is why they reach each other on localhost.
@diagram layers
caption: Two stacks on one kernel
layers:
  - {label: "Host namespace", nodes: ["eth0|real interface|env", "Routes and firewall|host rules|cp"]}
  - {label: "Namespace blue", nodes: ["lo|loopback|plain", "own port 80|isolated|app"]}
  - {label: "Namespace red", nodes: ["lo|loopback|plain", "own port 80|isolated|app"]}
@h Create two
```bash title="Namespaces" lab
sudo ip netns add blue && sudo ip netns add red
sudo ip netns exec blue ip link set lo up
sudo ip netns exec blue ip addr         # only lo exists
ip netns list
lsns -t net | head
```
@check
Why can two pods both listen on port 8080? || Each pod has its own network namespace and therefore its own port space.
@end

@concept veth pairs
@plain
A **veth pair** is a virtual cable with two ends. Whatever enters one end comes out the other, so you can place each end in a different namespace.
@problem
A namespace on its own is an island with no way to talk to anything.
@does
- `ip link add v0 type veth peer name v1` creates both ends.
- Move one end with `ip link set v1 netns blue`, assign addresses and bring both up.
- Docker and CNI plugins create one pair per container: one end inside, one end on a bridge on the host.
@diagram flow
caption: A cable between two namespaces
nodes:
  - "blue eth0|10.200.0.2/24|app"
  - "veth pair|virtual cable|cp"
  - "red eth0|10.200.0.3/24|app"
@h Connect two namespaces
```bash title="Direct link" lab
sudo ip link add v-blue type veth peer name v-red
sudo ip link set v-blue netns blue && sudo ip link set v-red netns red
sudo ip -n blue addr add 10.200.0.2/24 dev v-blue && sudo ip -n blue link set v-blue up
sudo ip -n red  addr add 10.200.0.3/24 dev v-red  && sudo ip -n red  link set v-red up
sudo ip netns exec blue ping -c 2 10.200.0.3
```
@end

@concept Bridges
@plain
A Linux **bridge** is a virtual switch. Many veth ends attach to it, and they can all talk at layer 2.
@problem
Point to point links do not scale to many containers. A switch lets any member talk to any other.
@does
- `ip link add br0 type bridge` and `ip link set veth master br0` attach ports.
- Give the bridge an IP and it becomes the gateway for the attached namespaces.
- `bridge fdb show` lists learned MAC addresses. Docker's default `docker0` is exactly this.
@diagram flow
caption: Containers on a bridge
nodes:
  - "ns blue|10.200.1.2|app"
  - "br0 bridge|10.200.1.1, the gateway|cp"
  - "ns red|10.200.1.3|app"
  - "Host eth0|uplink via NAT|ext"
@h Bridge with NAT
```bash title="Rebuild with a bridge" lab
sudo ip netns add green
sudo ip link add br0 type bridge && sudo ip addr add 10.200.1.1/24 dev br0 && sudo ip link set br0 up
for ns in blue green; do
  sudo ip link add h-$ns type veth peer name p-$ns
  sudo ip link set p-$ns netns $ns && sudo ip link set h-$ns master br0 && sudo ip link set h-$ns up
done
sudo ip -n blue  addr flush dev p-blue 2>/dev/null; sudo ip -n blue  addr add 10.200.1.2/24 dev p-blue; sudo ip -n blue  link set p-blue up
sudo ip -n green addr add 10.200.1.3/24 dev p-green; sudo ip -n green link set p-green up
sudo ip netns exec blue ping -c 2 10.200.1.3
sudo sysctl -w net.ipv4.ip_forward=1
sudo iptables -t nat -A POSTROUTING -s 10.200.1.0/24 ! -o br0 -j MASQUERADE
```
:::note
Your distribution may use nftables underneath; `iptables-nft` translates. Check `iptables --version`.
:::
@check
What does MASQUERADE do here? || It rewrites the namespaces' private source addresses to the host address for outbound traffic.
@end

@concept Routing tables and policy routing
@plain
The kernel chooses a route by longest prefix match in a routing table. **Policy routing** adds rules that pick which table to use based on source address, mark or other fields.
@problem
A host with two interfaces (for example public and management networks) answers on the wrong one with a single default route, and asymmetric traffic is dropped.
@does
- `ip route` shows the main table; `ip route get 8.8.8.8` shows the exact decision.
- `ip rule add from 10.0.2.0/24 table 100` sends traffic from that source to table 100, which has its own default route.
- Kubernetes CNIs and VPC CNI with multiple ENIs rely on this.
@diagram flow
caption: Rule chooses the table, table chooses the route
numbered: true
nodes:
  - "Packet|source 10.0.2.15|plain"
  - "ip rule|from 10.0.2.0/24 use table 100|cp"
  - "Table 100|default via 10.0.2.1 dev eth1|info"
  - "Out eth1|correct interface|ok"
@h Try it
```bash title="Policy route demo" lab
ip route show
ip rule show
ip route get 1.1.1.1
sudo ip route add 192.0.2.0/24 dev lo table 100        # 192.0.2.0/24 is documentation space
sudo ip rule add from 10.200.1.0/24 table 100
ip rule show | head -4
sudo ip rule del from 10.200.1.0/24 table 100; sudo ip route flush table 100
```
@check
What does "ip route get" tell you? || The route, interface and source address the kernel would use for that destination.
@end

@concept Connection tracking
@plain
**conntrack** records every flow the kernel firewall and NAT handle, so reply packets are matched to the right connection and rewritten consistently.
@problem
Stateful firewalls and NAT need memory of each flow. When the table fills, new connections are dropped with the log line "nf_conntrack: table full, dropping packet".
@does
- `conntrack -L` lists entries; `conntrack -C` counts them. `/proc/sys/net/netfilter/nf_conntrack_max` is the limit.
- Kubernetes Services with kube-proxy in iptables or IPVS mode depend on conntrack; busy nodes may need a larger table.
- Entries for UDP such as DNS expire fast, but a high rate of short flows can still fill the table.
@diagram flow
caption: A tracked flow
nodes:
  - "SYN from pod|new entry|app"
  - "conntrack table|ESTABLISHED, NAT mapping|cp"
  - "Reply packet|matched, unrewritten|ok"
  - "Timeout|entry removed|plain"
@h Inspect
```bash title="Conntrack usage" lab
sudo conntrack -C 2>/dev/null; cat /proc/sys/net/netfilter/nf_conntrack_count /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null
sudo conntrack -L 2>/dev/null | head -3
sudo dmesg | grep -i 'conntrack' | tail -3
```
```python title="Headroom as a percentage" lab
count, maximum = 180_000, 262_144
print(round(count / maximum * 100, 1), "percent used")      # 68.7
```
:::tip
Alert at 70 percent of `nf_conntrack_max` and raise it with sysctl when pods open many short connections. Memory use is per entry, so check the current kernel documentation.
:::
@check
What symptom indicates a full conntrack table? || New connections time out and the kernel logs "table full, dropping packet".
@end

@concept Traffic control with tc
@plain
`tc` configures queueing disciplines on an interface. With the `netem` module it can add delay, loss and bandwidth limits, which is a cheap way to test how your application behaves on a bad network.
@problem
Applications are tested on perfect local networks and fail in production with 2 percent packet loss or 200 ms latency.
@does
- `tc qdisc add dev eth0 root netem delay 100ms 20ms loss 1%` adds 100 ms delay with 20 ms jitter and 1 percent loss to everything leaving that interface.
- `tbf` limits rate. Remove with `tc qdisc del dev eth0 root`.
- Apply inside a namespace to avoid disturbing the host. Chaos tools wrap the same feature.
@diagram flow
caption: Shaping a test link
nodes:
  - "App in namespace|sends requests|app"
  - "netem qdisc|delay, loss, rate|warn"
  - "Interface|slower, lossy link|env"
  - "Observe|timeouts, retries|ok"
@h Inject latency
```bash title="Delay in a namespace" lab
sudo ip netns exec blue tc qdisc add dev p-blue root netem delay 100ms 10ms loss 1%
sudo ip netns exec blue ping -c 5 10.200.1.3        # round trip about 100 ms
sudo ip netns exec blue tc qdisc show dev p-blue
sudo ip netns exec blue tc qdisc del dev p-blue root
```
:::danger
Never run netem on the interface you are using to log in to a remote machine without a timed rollback such as `sleep 60; tc qdisc del ...` in the background.
:::
@end

@concept Cleaning up and mapping to containers
@plain
Everything above is what Docker and Kubernetes automate. Knowing the mapping lets you debug a CNI problem with plain Linux tools.
@problem
When a pod cannot reach a service, kubectl output rarely tells you which layer is broken.
@does
- Pod namespace plus a veth to the node (bridge or routed). Service load balancing is NAT rules or IPVS plus conntrack. NetworkPolicies are firewall rules.
- `nsenter -t <pid> -n ip addr` enters a container's namespace from the host, without any tools inside the image.
- Always remove lab objects: namespaces, bridges and iptables rules persist until reboot.
@diagram layers
caption: Where Kubernetes networking lives in Linux
layers:
  - {label: "Pod", nodes: ["Network namespace|eth0 plus lo|app"]}
  - {label: "Node plumbing", nodes: ["veth pair|pod to node|cp", "Bridge or routes|CNI choice|cp"]}
  - {label: "Services and policy", nodes: ["iptables or IPVS|service VIPs|env", "conntrack|flow state|env"]}
@h Clean up and enter a container namespace
```bash title="Teardown and nsenter" lab
sudo iptables -t nat -D POSTROUTING -s 10.200.1.0/24 ! -o br0 -j MASQUERADE
sudo ip netns del blue; sudo ip netns del red; sudo ip netns del green
sudo ip link del br0
ip netns list; ip link show br0 2>&1 | head -1
# from a node running containers:
# pid=$(docker inspect -f '{{.State.Pid}}' mycontainer); sudo nsenter -t $pid -n ss -tnp
```
@check
How do you run `ss` inside a distroless container's network? || `nsenter -t PID -n ss` from the host uses the host tools in the container's namespace.
@end
