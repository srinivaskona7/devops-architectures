---
title: Container networking basics
minutes: 45
objectives:
  - Explain bridge, host and none networks and how published ports work
  - Use user defined networks and built-in DNS so containers find each other by name
  - Trace a request from the host into a container with iptables and veth
---
Containers get a private network stack. Understanding the default bridge, port publishing and DNS removes most of the mystery when one service cannot reach another.

@concept Network drivers
@plain
A Docker network is a driver plus settings. The common drivers are bridge (single host), host, none, overlay (multi host) and macvlan.
@problem
You need to decide how isolated a container is, and how it reaches the world and its neighbours.
@does
- **bridge**: private subnet behind NAT; the default.
- **host**: container shares the host network stack; no isolation, no port mapping needed.
- **none**: only loopback.
- **overlay**: VXLAN across hosts (Swarm). **macvlan**: container gets its own MAC and LAN address.
@diagram cmp
caption: Driver choice at a glance
cards:
  - {h: "bridge", kind: ok, items: ["Own IP such as 172.18.0.2", "Ports published with -p", "Default choice"]}
  - {h: "host", kind: warn, items: ["Shares host interfaces", "Fastest, no NAT", "Port clashes, Linux only"]}
  - {h: "none", kind: info, items: ["Loopback only", "For offline batch jobs"]}
  - {h: "overlay and macvlan", kind: env, items: ["Multi host or LAN native", "More setup", "Specialised"]}
@h List and inspect
```bash title="Default networks" lab
docker network ls
docker network inspect bridge --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}'
docker run --rm --network host alpine:3.20 ip -br addr | head -3
docker run --rm --network none alpine:3.20 ip -br addr
```
@end

@concept The default bridge and veth pairs
@plain
Docker creates a Linux bridge (`docker0`). Each container gets a virtual cable (veth pair): one end inside as `eth0`, the other plugged into the bridge.
@problem
Packets between container and outside need a path. Knowing it lets you use `tcpdump` and `iptables` to find where they die.
@does
- Containers on one bridge talk by IP directly at layer 2.
- Outbound traffic is source-NATed (masqueraded) to the host IP.
- Inbound published ports use DNAT rules in the `DOCKER` iptables chain.
- The default `bridge` network has no name resolution; user-defined bridges do.
@diagram layers
caption: Path of a packet from container to internet
layers:
  - {label: "Container", nodes: ["eth0 172.17.0.2|inside net namespace|app"]}
  - {label: "Host", nodes: ["vethXXXX|other cable end|info", "docker0 bridge|172.17.0.1|cp", "iptables MASQUERADE|source NAT|warn", "ens5 or en0|real interface|env"]}
@h Look at the plumbing
```bash title="On a Linux host" lab
ip -br link show type bridge
ip -br link | grep veth | head
sudo iptables -t nat -S DOCKER | head      # DNAT rules for published ports
sudo iptables -t nat -S POSTROUTING | grep -i masq
```
@end

@concept Publishing ports
@plain
`-p 8080:80` asks Docker to forward host port 8080 to container port 80. Without it nothing outside the host can reach the container.
@problem
`EXPOSE` in a Dockerfile is only documentation. People expect it to open the port and it does not.
@does
- `-p 8080:80` binds all interfaces. `-p 127.0.0.1:8080:80` limits to localhost.
- `-P` publishes all EXPOSEd ports to random high ports.
- Published ports bypass `ufw` and firewalld rules on Linux because Docker edits iptables directly; bind to 127.0.0.1 or add rules in the `DOCKER-USER` chain.
- Within one user-defined network containers reach each other on the container port, no publishing needed.
@diagram flow
caption: A published port forwards to the container
numbered: true
nodes:
  - "Client|curl host:8080|ext"
  - "Host iptables|DNAT to 172.18.0.2:80|warn"
  - "Bridge|forward|info"
  - "Container|nginx on 80|ok"
@h Try it
```bash title="Publish and verify" lab
docker run -d --name w -p 127.0.0.1:8080:80 nginx:1.27-alpine
docker port w
curl -sI http://127.0.0.1:8080 | head -1
docker rm -f w
```
:::danger
`-p 5432:5432` for a database exposes it to every network the host sits on, bypassing the host firewall. Use `127.0.0.1:5432:5432` or no publishing at all.
:::
@end

@concept User defined networks and DNS
@plain
On a network you create yourself, Docker runs an embedded DNS server at 127.0.0.11. Containers resolve each other by container name or service alias.
@problem
Container IPs change on every restart, so hardcoding them breaks. The default bridge offers no names.
@does
- `docker network create app-net`, then `--network app-net` for each container.
- Name lookup of `db` returns the container IP; multiple containers with the same `--network-alias` are returned round-robin.
- Different networks are isolated: a container in `frontend` cannot reach one only in `backend`.
- Unknown names are forwarded to the host's DNS servers.
@diagram layers
caption: Two networks isolate the database from the edge
layers:
  - {label: "frontend network", nodes: ["proxy|published port 443|ext", "api|member of both|app"]}
  - {label: "backend network", nodes: ["api|reaches db by name|app", "db|no published port|ok"]}
@h Demonstrate
```bash title="Name resolution" lab
docker network create app-net
docker run -d --name db --network app-net -e POSTGRES_PASSWORD=dev postgres:16
docker run --rm --network app-net alpine:3.20 nslookup db
docker run --rm --network app-net alpine:3.20 cat /etc/resolv.conf
docker rm -f db; docker network rm app-net
```
@check
Why can containers on the default bridge not resolve each other by name? || Embedded DNS is only enabled on user-defined networks; the legacy bridge needs links or IPs.
@end

@concept Host, overlay and macvlan in practice
@plain
Special drivers trade isolation for performance or reach. Use them deliberately.
@problem
Some workloads (packet capture, high throughput proxies, legacy apps needing a LAN IP) cannot live behind NAT.
@does
- **host**: use for a monitoring agent or when NAT overhead matters. Beware port conflicts.
- **overlay**: Docker Swarm builds VXLAN tunnels (UDP 4789) between nodes, with optional encryption. Kubernetes uses CNI plugins (Calico, Cilium, VPC CNI) instead.
- **macvlan and ipvlan**: container appears as a separate device on the LAN.
- On macOS and Windows Docker Desktop, `--network host` refers to the VM, not your Mac.
@diagram rows
caption: Reach of each driver
rows:
  - {arrows: false, items: ["bridge|one host, NAT|ok", "host|one host, no isolation|warn"]}
  - {arrows: false, items: ["overlay|many hosts, VXLAN|info", "macvlan|LAN address per container|env"]}
@choose Picking a driver
bridge | almost every application | you need raw LAN presence
host | agents, sniffers, latency critical proxies | you run several copies of the same port
overlay | Swarm services across hosts | you run Kubernetes, use its CNI
macvlan | legacy apps needing a LAN IP | the switch limits MAC addresses per port
@end

@concept Troubleshooting container networking
@plain
When a container cannot reach something, test each hop in order: its own interface, the bridge, DNS, the destination port and finally the host firewall.
@problem
Without a method, network problems turn into guesswork about NAT, DNS and firewalls.
@does
- Inside the container: `ip addr`, `ip route`, `cat /etc/resolv.conf`, `getent hosts NAME`.
- On the host: `docker network inspect NET`, `ip -br link`, `iptables -t nat -L -n`.
- `connection refused` means something answered and rejected, usually an app bound to 127.0.0.1. A timeout means packets were dropped, usually a firewall, security group or wrong network.
- On AWS check the security group and NACL for traffic leaving the host as well.
@diagram flow
caption: Hop by hop checks
numbered: true
nodes:
  - "Container interface|ip addr, ip route|info"
  - "DNS|getent hosts name|info"
  - "Port|nc -vz host port|app"
  - "Host and cloud firewall|iptables, security group|warn"
@h Commands
```bash title="Distinguish refused from timeout" lab
docker run --rm --network app-net alpine:3.20 sh -c 'nc -zv -w 2 db 5432; echo "exit=$?"'
docker run --rm alpine:3.20 sh -c 'nc -zv -w 2 10.255.255.1 80; echo "exit=$?"'   # timeout: packets dropped
docker exec api ss -ltn | head                  # is the app bound to 0.0.0.0 or 127.0.0.1
```
@end
