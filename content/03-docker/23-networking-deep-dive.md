---
title: Container networking deep dive
minutes: 60
objectives:
  - Trace container traffic through veth pairs, bridges and iptables NAT rules
  - Use macvlan and ipvlan to give containers addresses on the physical network
  - Relate Docker networking to CNI plugins used by Kubernetes
---
The default bridge hides a lot of Linux networking. Seeing the pieces makes Kubernetes networking much less mysterious.

@concept Network namespaces and veth pairs
@plain
Each container has its own network namespace with its own interfaces, routes and firewall rules. A veth pair is a virtual cable between two namespaces.
@problem
Containers need isolated networks, yet must reach each other and the outside.
@does
- One end of the veth pair (`eth0`) is inside the container, the other (`vethXXXX`) is on the host, attached to a bridge.
- `ip netns` lists named namespaces; Docker keeps them under `/var/run/docker/netns`, so use `nsenter -t PID -n` instead.
- Kubernetes Pods share one namespace between containers (the pause container owns it).
- Loopback inside the namespace is private to the container.
@diagram flow
caption: Virtual cable
nodes:
  - "Container eth0|172.17.0.2|app"
  - "veth pair|virtual cable|info"
  - "docker0 bridge|172.17.0.1|cp"
  - "Host eth0|physical|ext"
@h Inspect
```bash title="Look inside" lab
docker run -d --name n1 alpine sleep 600
pid=$(docker inspect -f '{{.State.Pid}}' n1)
nsenter -t "$pid" -n ip addr
ip link show type veth
docker rm -f n1
```
@check
Which container owns the Pod network namespace in Kubernetes? || The pause (sandbox) container. Application containers join its namespace.
@end

@concept The bridge network and NAT
@plain
Docker's default bridge connects containers on a private subnet. iptables NAT rules translate their addresses when they talk outward and forward published ports in.
@problem
Private addresses are not routable outside, and a client outside must still reach published container ports.
@does
- Outbound: `MASQUERADE` rule in the `nat` table POSTROUTING chain rewrites the source to the host address.
- Inbound `-p 8080:80`: a `DNAT` rule in the DOCKER chain rewrites destination host:8080 to container:80.
- A userland proxy (`docker-proxy`) may also listen for local traffic unless disabled.
- Docker inserts rules in the `DOCKER-USER` chain hook: put your own filtering there, since Docker rewrites its own chains.
- Newer Docker releases are adding nftables support; check your version's docs.
@diagram seq
caption: Published port path
actors: ["Client|outside|ext", "Host iptables|nat table|cp", "Container|172.17.0.2:80|app"]
steps:
  - "0>1: to host 8080 | req"
  - "1>1: DNAT to 172.17.0.2:80 | warn"
  - "1>2: forwarded | req"
  - "2>0: reply via conntrack | resp"
@h Show the rules
```bash title="NAT rules (Linux host)" lab
docker run -d --name web -p 8080:80 nginx:1.27
iptables -t nat -S DOCKER | head
iptables -t nat -S POSTROUTING | grep MASQUERADE
iptables -S DOCKER-USER
docker rm -f web
```
:::warn
Published ports bypass `ufw` and similar tools because Docker writes iptables rules directly. Bind to `127.0.0.1:8080:80` or filter in DOCKER-USER.
:::
@end

@concept User-defined networks and DNS
@plain
Custom bridge networks add automatic DNS by container name and better isolation than the default bridge.
@problem
On the default bridge, containers can only find each other by IP or deprecated links.
@does
- `docker network create app-net` makes an isolated bridge with embedded DNS at 127.0.0.11 inside containers.
- Containers on different networks cannot talk unless attached to both.
- `--network-alias` gives extra names; `--internal` creates a network without external access.
- Compose creates one network per project by default and names services as hosts.
@diagram layers
caption: Isolation by network
layers:
  - {label: "Network frontend", nodes: ["web|published port|app", "api|also on backend|app"]}
  - {label: "Network backend (internal)", nodes: ["api|name resolution|app", "db|no outside access|ok"]}
@h Try it
```bash title="Two networks" lab
docker network create frontend
docker network create --internal backend
docker run -d --name db --network backend postgres:16 -e POSTGRES_PASSWORD=x
docker run -d --name api --network frontend alpine sleep 600
docker network connect backend api
docker exec api getent hosts db
```
@check
What does --internal do to a network? || Containers on it cannot reach outside networks. They can talk only to each other.
@end

@concept Host and none modes
@plain
`--network host` shares the host's network namespace. `--network none` gives only loopback.
@problem
NAT adds cost and hides source addresses for some workloads; others must have no network at all.
@does
- Host mode: no NAT, best throughput, but port conflicts with the host and no network isolation. On Docker Desktop and Colima it means the VM, not your Mac.
- None: used for batch jobs that process local files, or when attaching a custom network later.
- Kubernetes `hostNetwork: true` gives the same behaviour to Pods (used by CNI agents and node exporters) and is restricted by Pod Security.
@diagram cmp
caption: Network modes
cards:
  - {h: "bridge", kind: info, items: ["Private subnet", "NAT for outbound", "Port publishing"]}
  - {h: "host", kind: warn, items: ["Shares host stack", "No NAT", "Port conflicts"]}
  - {h: "none", kind: ok, items: ["Loopback only", "Strong isolation"]}
@h Check
```bash title="Compare modes" lab
docker run --rm --network none alpine ip addr
docker run --rm --network host alpine ip addr | head -5
```
@end

@concept macvlan and ipvlan
@plain
macvlan gives each container its own MAC and IP on your physical network, so it looks like a separate machine. ipvlan shares the parent's MAC but gives separate IPs.
@problem
Legacy software or monitoring needs containers reachable by real LAN addresses without NAT or port mapping.
@does
- macvlan needs a parent interface and a subnet range the container may use. Many switches limit MAC addresses per port and Wi-Fi often blocks it.
- Host cannot reach macvlan containers directly (a kernel rule); add a macvlan interface on the host as a workaround.
- ipvlan L2 mode is like macvlan with one MAC; L3 mode routes between subnets and works with BGP-based fabrics.
- Cloud networks usually do not allow macvlan (AWS drops unknown MACs). Prefer VPC CNI or secondary IPs.
@diagram flow
caption: macvlan on the LAN
nodes:
  - "Physical switch|LAN 192.168.1.0/24|ext"
  - "Host eth0|parent interface|env"
  - "macvlan net|own MAC per container|cp"
  - "Container|192.168.1.50|app"
@h Create a macvlan network
```bash title="macvlan network" lab
docker network create -d macvlan --subnet=192.168.1.0/24 --gateway=192.168.1.1 --ip-range=192.168.1.48/28 -o parent=eth0 lan
docker run -d --name cam --network lan --ip 192.168.1.50 nginx:1.27
# host to container access needs a macvlan shim interface
ip link add shim link eth0 type macvlan mode bridge
ip addr add 192.168.1.47/32 dev shim && ip link set shim up && ip route add 192.168.1.48/28 dev shim
```
@check
Why can the host not ping its own macvlan containers? || The kernel does not pass traffic between a parent interface and its macvlan children. A shim interface on the host fixes it.
@end

@concept Overlay networks and Swarm
@plain
An overlay network connects containers across several hosts by wrapping their traffic in VXLAN tunnels.
@problem
Containers on different machines need to share one virtual network.
@does
- Docker Swarm's overlay uses VXLAN on UDP 4789 and a gossip control plane on 7946; encryption is optional (`--opt encrypted`) and uses IPsec.
- Kubernetes CNI overlays (Flannel VXLAN, Calico VXLAN, Cilium tunnel) use the same idea.
- Costs: header overhead (reduce MTU by about 50 bytes), extra CPU, harder packet capture.
- Swarm is in maintenance mode compared with Kubernetes; use overlay knowledge mostly to understand CNI.
@diagram flow
caption: VXLAN encapsulation
nodes:
  - "Container A|10.0.0.2 on host 1|app"
  - "VXLAN tunnel|UDP 4789|info"
  - "Host network|underlay|ext"
  - "Container B|10.0.0.3 on host 2|app"
@end

@concept Debugging container networks
@plain
Debug in layers: interface, address, route, DNS, firewall, then application.
@problem
"The container cannot connect" has many possible causes and random changes waste time.
@does
- Use a toolbox image such as `nicolaka/netshoot` attached to the same network or namespace (`--network container:NAME`).
- Check: `ip addr`, `ip route`, `ss -tlnp`, `dig`, `curl -v`, `tcpdump -i any port 80`, `conntrack -L`.
- On the host: `iptables -t nat -L -n -v`, `bridge link`, `ip -s link` for drops.
- MTU issues: large transfers stall while pings work; test `ping -M do -s 1472`.
@diagram flow
caption: Layered checks
numbered: true
nodes:
  - "Interface and address|ip addr|plain"
  - "Route and gateway|ip route|info"
  - "DNS|dig|info"
  - "Firewall and NAT|iptables|warn"
  - "Application|ss, curl|ok"
@h netshoot
```bash title="Join a container's namespace" lab
docker run --rm -it --network container:web nicolaka/netshoot sh -c 'ip route; ss -tlnp; curl -sI localhost'
docker run --rm -it --net host --cap-add NET_ADMIN --cap-add NET_RAW nicolaka/netshoot tcpdump -ni any port 8080 -c 5
```
@end
