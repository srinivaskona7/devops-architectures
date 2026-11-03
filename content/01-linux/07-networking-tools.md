---
title: Linux networking tools
minutes: 50
objectives:
  - Inspect interfaces, addresses, routes and listening sockets
  - Test DNS, TCP and HTTP step by step to locate a failure
  - Capture packets and read basic firewall rules
---
When "the app is down", the network is the first suspect and the last thing most people can prove. A fixed order of checks, from the local interface outward, turns guessing into evidence.

@concept Interfaces, addresses and routes
@plain
A machine talks through **interfaces** (such as `eth0`), each with one or more **IP addresses**. The **routing table** decides which interface and next hop a packet uses.
@problem
Most "cannot connect" reports are a missing address, a wrong default gateway or a route that sends traffic the wrong way.
@does
- `ip addr` lists interfaces and addresses, `ip route` lists routes, `ip neigh` shows the ARP/neighbour cache.
- The route with `default via X` is where unknown destinations go.
- `ip route get 10.0.2.15` shows exactly which route and source address would be used for a destination.
- Changes made with `ip` are temporary; persistent configuration lives in netplan, NetworkManager or systemd-networkd.
@diagram flow
caption: Following a packet out of a host
numbered: true
nodes:
  - "Application|connect to 10.0.2.15:443|app"
  - "Routing table|longest prefix wins|info"
  - "Interface eth0|source IP chosen|env"
  - "Gateway or neighbour|next hop by MAC|cp"
@h Commands
```bash title="Inspect the local network" lab
ip -br addr                    # one line per interface, brief
ip route                       # routing table
ip route get 8.8.8.8           # which route would carry this destination
ip -s link show eth0           # packet, error and drop counters
ip neigh | head                # neighbours the host has talked to
cat /etc/resolv.conf           # which DNS servers it asks
```
@check
What does "default via 10.0.0.1 dev eth0" mean? || Traffic with no more specific route is sent to the gateway 10.0.0.1 through eth0.
@end

@concept Sockets and listening ports
@plain
A **socket** is one end of a conversation: an IP address and port. A service **listens** on a port, and every client connection is another socket.
@problem
"Is my service listening, on which address, and who is connected?" decides whether the problem is the app or the network.
@does
- `ss -tlnp` lists TCP listeners with the owning process. `ss -tn state established` lists live connections.
- Listening on `127.0.0.1` is local only; `0.0.0.0` or `::` accepts external connections.
- TCP states matter: many `TIME-WAIT` is normal under load, many `SYN-RECV` can signal a flood, many `CLOSE-WAIT` means the application did not close sockets.
- `lsof -i :8080` finds which process holds a port.
@diagram cmp
caption: Reading the Local Address column
cards:
  - {h: "127.0.0.1:5432", kind: warn, items: ["Loopback only", "Other hosts cannot connect", "Common cause of 'works locally'"]}
  - {h: "0.0.0.0:5432", kind: ok, items: ["All IPv4 interfaces", "Reachable remotely if firewalls allow", "Check security groups too"]}
  - {h: "[::]:5432", kind: info, items: ["All IPv6 interfaces", "Often also accepts IPv4", "Depends on bindv6only"]}
@h Commands
```bash title="Who listens and who is connected" lab
ss -tlnp                              # TCP listening sockets with process names
ss -s                                 # summary counts by state
ss -tn state established '( dport = :443 )' | head
ss -tn state close-wait | wc -l       # leaking connections?
sudo lsof -i :8080                    # what owns the port
```
@check
A service works with curl localhost but not from another host. First thing to check? || ss -tlnp: it may be bound to 127.0.0.1 only, or a firewall may block the port.
@end

@concept DNS troubleshooting
@plain
DNS turns names into addresses. Many outages that look like network failures are DNS failures.
@problem
Applications cache results, resolvers cache results, and different tools use different resolvers, so "it resolves for me" proves little.
@does
- `dig example.com` asks a resolver; `dig +short`, `dig @8.8.8.8` queries a specific server, `dig +trace` follows delegation from the root.
- `getent hosts name` uses the same path as most applications (nsswitch, `/etc/hosts`, resolver), so it is the better test.
- Record types: A/AAAA address, CNAME alias, MX mail, TXT text, NS delegation, SRV service.
- TTL says how long answers may be cached. Lower the TTL before a planned change.
@diagram seq
caption: A lookup through caching resolvers
actors: ["App|getaddrinfo|app", "Local cache|systemd-resolved|env", "Recursive resolver|VPC or ISP|cp", "Authoritative|owns the zone|ok"]
steps:
  - "0>1: api.example.com? | req"
  - "1>2: not cached, ask | req"
  - "2>3: ask the zone | req"
  - "3>2: A 203.0.113.10, TTL 300 | resp"
  - "2>1: answer, cache 300 s | resp"
  - "1>0: 203.0.113.10 | resp"
@h Commands
```bash title="DNS checks" lab
getent hosts localhost                 # what the application would see
dig +short example.com                 # default resolver
dig +short example.com @1.1.1.1        # compare with a public resolver
dig +noall +answer example.com TXT
resolvectl status | head -15           # systemd-resolved servers and domains
```
:::tip
When the two answers differ, the problem is in the default resolver or in a stale cache, not in the zone itself.
:::
@end

@concept Testing connections layer by layer
@plain
Test from the bottom up: link, address, route, DNS, TCP port, TLS, HTTP. The first layer that fails is the layer to fix.
@problem
Jumping straight to HTTP errors hides whether the cause is a DNS record, a closed port, an expired certificate or an application bug.
@does
- `ping` tests IP reachability (ICMP can be blocked, so a failure is not proof).
- `nc -vz host 443` tests whether a TCP connection opens.
- `curl -v` shows DNS, connect, TLS and HTTP timings; `-w` prints a timing breakdown.
- `openssl s_client -connect host:443 -servername host` shows the certificate chain and expiry.
- `mtr host` combines traceroute and ping to locate loss on a path.
@diagram flow
caption: Test one layer at a time
numbered: true
nodes:
  - "ip route get|have a route?|info"
  - "getent hosts|does the name resolve?|app"
  - "nc -vz host port|does TCP connect?|env"
  - "openssl s_client|is TLS valid?|cp"
  - "curl -v|what does HTTP return?|ok"
@h A timing breakdown
```bash title="Where did the time go" lab
curl -s -o /dev/null -w 'dns=%{time_namelookup}s connect=%{time_connect}s tls=%{time_appconnect}s first_byte=%{time_starttransfer}s total=%{time_total}s code=%{http_code}\n' https://example.com
nc -vz example.com 443
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | openssl x509 -noout -dates -subject
```
@choose Which test
ping | you want a quick reachability hint | ICMP is filtered; use nc
nc -vz | you need to know if a TCP port opens | you need the HTTP status
curl -v | you need the full HTTP exchange | you only need the port state
mtr | loss or latency happens somewhere along the path | the target is on the same subnet
@end

@concept Packet capture with tcpdump
@plain
`tcpdump` records the packets crossing an interface. It is the final authority on what really went over the wire.
@problem
When logs and metrics disagree, only the packets show whether a request left, whether a reply came back, and whether anything was reset.
@does
- `-i eth0` picks the interface, `-nn` skips name lookups, `-c 50` stops after 50 packets, `-w file.pcap` saves for Wireshark.
- Filters use BPF syntax: `host 10.0.0.5 and tcp port 443`.
- Look for `Flags [S]` (SYN), `[S.]` (SYN-ACK), `[R]` (reset) and retransmissions.
- Capture needs root and can expose secrets, so limit scope and duration.
@diagram seq
caption: A normal TCP handshake as seen in a capture
actors: ["Client|10.0.0.5|app", "Server|10.0.0.9:443|env"]
steps:
  - "0>1: SYN [S] | req"
  - "1>0: SYN-ACK [S.] | resp"
  - "0>1: ACK [.] | req"
  - "note 0..1: a [R] reply to the SYN means the port is closed"
@h Commands
```bash title="Capture safely" nocheck
sudo tcpdump -i any -nn -c 20 'tcp port 443 and host 10.0.0.9'
sudo tcpdump -i eth0 -nn -w /tmp/web.pcap -G 60 -W 1 'port 8080'   # one 60-second file
sudo tcpdump -nn -r /tmp/web.pcap 'tcp[tcpflags] & tcp-rst != 0'   # find resets
```
@end

@concept Firewalls: nftables and iptables
@plain
A host firewall decides which packets are accepted, dropped or rewritten. `nftables` is the modern tool; `iptables` is the older interface that many systems and container runtimes still use.
@problem
A closed port can come from the service, a host firewall, a cloud security group or a Kubernetes NetworkPolicy. You need to read the host layer.
@does
- Rules live in tables and chains; a packet walks the chain from top to bottom until a rule matches.
- Typical policy: accept established connections, accept loopback, allow specific ports, drop the rest.
- NAT rewrites addresses; it is how containers and Kubernetes Services reach out and receive traffic.
- Docker and kube-proxy add their own rules; do not flush tables on a container host.
@diagram flow
caption: The simplified path of an incoming packet
nodes:
  - "Network interface|packet arrives|plain"
  - "PREROUTING|NAT and marking|env"
  - "INPUT or FORWARD|filter rules|warn"
  - "Local process or next hop|delivered|ok"
@h Reading rules
```bash title="Inspect firewall rules" nocheck
sudo nft list ruleset | head -40
sudo iptables -S | head -20                   # rules as commands
sudo iptables -t nat -S | head -20            # NAT rules (Docker, kube-proxy)
sudo ufw status verbose                       # Ubuntu's simple front end
```
```text title="A minimal nftables policy (example)"
table inet filter {
  chain input {
    type filter hook input priority 0; policy drop;
    ct state established,related accept
    iif lo accept
    tcp dport { 22, 443 } accept
    icmp type echo-request accept
  }
}
```
:::warn
Test firewall changes from a console or with a scheduled rollback. A wrong rule on a remote host locks you out of SSH.
:::
@end
