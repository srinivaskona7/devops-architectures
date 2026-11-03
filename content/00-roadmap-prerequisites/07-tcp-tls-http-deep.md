---
title: TLS, HTTP versions, proxies and CIDR in depth
minutes: 50
objectives:
  - Walk through a TLS 1.3 handshake and explain what each side proves
  - Compare HTTP 1.1, HTTP 2 and HTTP 3 and choose where each helps
  - Distinguish layer 4 and layer 7 load balancers and forward and reverse proxies
  - Calculate CIDR ranges and plan non overlapping subnets
---
The networking essentials page gave the vocabulary. Here we go one level deeper, with arithmetic you can verify yourself.

@concept The TLS 1.3 handshake
@plain
TLS lets a client check it is talking to the right server and then encrypt everything that follows. The handshake agrees on keys before any application data is sent.
@problem
Plain TCP is readable and modifiable by anyone on the path. Without authentication a client cannot tell a real bank from an impostor.
@does
- The client sends supported ciphers and a key share. The server answers with its choice, its key share and its **certificate**.
- Both sides derive the same session keys using ephemeral Diffie-Hellman, so recording traffic today does not allow decryption after the server key leaks (**forward secrecy**).
- The client validates the certificate chain up to a trusted CA and checks the hostname matches.
- TLS 1.3 needs one round trip. Resumption can send data in zero round trips, with replay caveats.
@diagram seq
caption: TLS 1.3 handshake in one round trip
actors: ["Client|browser or curl|app", "Server|holds the certificate|cp"]
steps:
  - "0>1: ClientHello + key share | req"
  - "1>0: ServerHello + certificate + Finished | tls"
  - "note 0..0: verify chain and hostname"
  - "0>1: Finished | tls"
  - "0>1: HTTP request, encrypted | tls"
  - "1>0: HTTP response, encrypted | tls"
@h Watch it happen
```bash title="Inspect a real handshake" lab
curl -sv https://example.com -o /dev/null 2>&1 | grep -E 'TLSv|subject|issuer|expire|ALPN'
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | openssl x509 -noout -subject -issuer -dates
```
@check
What does the client check in the certificate? || That a trusted CA signed the chain, that it is within its dates, and that the hostname matches.
@end

@concept HTTP/1.1, HTTP/2 and HTTP/3
@plain
HTTP is the request and response language of the web. Its versions differ in how they move bytes, not in what a GET or a status code means.
@problem
HTTP/1.1 handles one request at a time per connection, so browsers open many connections, and a slow response blocks those behind it.
@does
- **HTTP/1.1**: text, one outstanding request per connection, keep-alive reuse.
- **HTTP/2**: binary framing and many parallel streams on one TCP connection, header compression. A lost packet still stalls all streams because TCP delivers in order.
- **HTTP/3**: runs over **QUIC** on UDP, so streams are independent and connection set-up combines transport and TLS. Support must be enabled at the edge and UDP 443 must be open.
- Clients learn the version through ALPN during TLS or the `Alt-Svc` header.
@diagram cmp
caption: What changed in each version
cards:
  - {h: "HTTP/1.1", kind: plain, items: ["Text protocol", "One request per connection at a time", "Many connections"]}
  - {h: "HTTP/2", kind: app, items: ["Multiplexed streams", "One TCP connection", "TCP head of line blocking"]}
  - {h: "HTTP/3", kind: ok, items: ["QUIC over UDP", "Independent streams", "Faster connect and migration"]}
@h Test each version
```bash title="Force a protocol version" lab
curl -sI --http1.1 https://example.com | head -1
curl -sI --http2 https://example.com | head -1
curl -sI --http3 https://cloudflare.com 2>&1 | head -1   # works only if your curl build supports HTTP/3
```
:::note
gRPC requires HTTP/2 end to end. A load balancer that downgrades to HTTP/1.1 breaks it.
:::
@end

@concept Load balancers: layer 4 and layer 7
@plain
A load balancer spreads incoming traffic over several servers and stops sending to unhealthy ones. Layer 4 balancers look at IP and port. Layer 7 balancers read the HTTP request.
@problem
One server is a single point of failure and a capacity ceiling. Clients also need one stable address while servers come and go.
@does
- **L4** (AWS Network Load Balancer): forwards TCP or UDP connections, very fast, keeps the client IP, cannot route by path.
- **L7** (AWS Application Load Balancer, ingress controllers): routes by host, path or header, terminates TLS, can redirect and add headers.
- Algorithms include round robin, least connections and hashing. Health checks remove failing targets.
- In Kubernetes a `Service` of type LoadBalancer creates an L4 balancer; an `Ingress` or Gateway uses an L7 one.
@diagram flow
caption: Layer 7 routing by path
nodes:
  - "Client|https://shop.example.com|ext"
  - "L7 balancer|terminates TLS, reads path|cp"
  - "/api|api pods|app"
  - "/static|web pods|app"
@choose Which balancer
L4 (NLB, Service LoadBalancer) | raw TCP, UDP, extreme throughput, static IPs | you need path routing or HTTP rules
L7 (ALB, Ingress, Gateway API) | host and path routing, WAF, redirects | non-HTTP protocols
@check
Which type can see the URL path? || Only layer 7, because it parses the HTTP request.
@end

@concept Forward and reverse proxies
@plain
A proxy is a server that passes requests on behalf of someone else. A **forward proxy** acts for clients going out. A **reverse proxy** acts for servers receiving traffic.
@problem
Organizations need to control and log outbound access, and services need a single entry point that adds caching, TLS, compression and protection.
@does
- Forward proxy (Squid, corporate proxy): clients set `HTTPS_PROXY`; the proxy filters destinations and logs. HTTPS goes through using the CONNECT method.
- Reverse proxy (nginx, Envoy, HAProxy): clients think it is the server and it picks a backend. Ingress controllers and service mesh sidecars are reverse proxies.
- Proxies add headers such as `X-Forwarded-For` so the backend can learn the real client address. Trust these only from your own proxies.
@diagram cmp
caption: Same idea, opposite sides
cards:
  - {h: "Forward proxy", kind: info, items: ["Sits near the clients", "Controls outbound traffic", "Set with HTTPS_PROXY"]}
  - {h: "Reverse proxy", kind: app, items: ["Sits near the servers", "Routes, caches, terminates TLS", "Ingress, Envoy, nginx"]}
@h Using a proxy
```bash title="Proxy settings" nocheck
export HTTPS_PROXY=http://proxy.corp.example:3128
export NO_PROXY=localhost,127.0.0.1,.svc,.cluster.local   # skip the proxy for internal names
curl -sI https://example.com | head -1
curl -sI -H 'X-Forwarded-For: 1.2.3.4' http://localhost:8080   # a backend should not trust this from the internet
```
@end

@concept CIDR arithmetic you can do by hand
@plain
A CIDR block like `10.0.0.0/16` fixes the first 16 of 32 bits. The remaining bits are host addresses, so the block holds 2 to the power of (32 minus prefix) addresses.
@problem
Choosing VPC and subnet sizes badly is expensive to undo. Overlapping ranges also block VPC peering and VPN links.
@does
- /24 gives 2^8 = 256 addresses, /22 gives 1024, /16 gives 65536.
- Block size in the changing octet is 256 minus the mask value. For /26 the mask is 255.255.255.192, so blocks are 64 long: .0, .64, .128, .192.
- AWS reserves 5 addresses in every subnet, so a /24 offers 251 usable.
- Private ranges are 10.0.0.0/8, 172.16.0.0/12 (172.16.0.0 to 172.31.255.255) and 192.168.0.0/16.
@diagram flow
caption: Worked example for 192.168.1.130/26
numbered: true
nodes:
  - "Mask|/26 = 255.255.255.192|info"
  - "Block size|256 - 192 = 64|plain"
  - "Network|130 falls in 128 to 191|app"
  - "Range|.128 network, .191 broadcast|ok"
  - "Hosts|.129 to .190 = 62|ok"
@h Verify with Python
```python title="Check CIDR math" lab
import ipaddress as ip
for c in ["192.168.1.130/26", "10.0.4.0/22", "172.16.0.0/12"]:
    n = ip.ip_network(c, strict=False)
    print(c, "->", n, n.netmask, "first", n[0], "last", n[-1], "size", n.num_addresses)
print(ip.ip_network("10.0.0.0/16").overlaps(ip.ip_network("10.0.4.0/22")))   # True
```
Expected results: 192.168.1.130/26 is network 192.168.1.128/26 with 64 addresses; 10.0.4.0/22 spans 10.0.4.0 to 10.0.7.255 with 1024 addresses; 172.16.0.0/12 has 1048576 addresses.
@check
How many addresses are in a /20? || 2^(32-20) = 2^12 = 4096.
@end

@concept Planning a VPC and subnets
@plain
Planning means carving one large block into non overlapping subnets per tier and availability zone, leaving room to grow.
@problem
Kubernetes pods can use one VPC IP each (AWS VPC CNI), so a small subnet can run out of addresses long before it runs out of CPU.
@does
- Pick a VPC block that does not overlap on-premises or other VPCs, for example 10.0.0.0/16.
- Split by zone and tier. A /16 contains 256 /24 subnets, so 10.0.0.0/24, 10.0.1.0/24 and so on.
- Give node and pod subnets more space (/20 is 4096 addresses) than load balancer or database subnets (/24).
- Keep some blocks unused for future tiers.
@diagram layers
caption: One VPC across three zones
layers:
  - {label: "VPC 10.0.0.0/16", nodes: ["65536 addresses|reserve growth space|env"]}
  - {label: "Public", nodes: ["10.0.0.0/24 zone a|251 usable|ext", "10.0.1.0/24 zone b|251 usable|ext", "10.0.2.0/24 zone c|251 usable|ext"]}
  - {label: "Private nodes", nodes: ["10.0.16.0/20 zone a|4091 usable|app", "10.0.32.0/20 zone b|4091 usable|app", "10.0.48.0/20 zone c|4091 usable|app"]}
@h Generate the plan
```python title="Subnet plan generator" lab
import ipaddress as ip
vpc = ip.ip_network("10.0.0.0/16")
subs = list(vpc.subnets(new_prefix=20))      # 16 blocks of 4096
print(len(subs), "blocks of", subs[0].num_addresses)
for z, s in zip("abc", subs[1:4]):
    print("nodes zone", z, s, "usable in AWS", s.num_addresses - 5)
```
:::warn
You cannot resize a subnet in place. Check the current AWS documentation for adding secondary CIDR blocks if you outgrow the VPC.
:::
@end

@concept NAT, ports and connection limits
@plain
**NAT** rewrites addresses so many private hosts can share one public address. The device remembers each flow in a table keyed by addresses and ports.
@problem
IPv4 has only 2^32 = 4294967296 addresses, far fewer than devices. Private hosts also should not be reachable directly from the internet.
@does
- A NAT gateway lets private subnets start outbound connections while blocking inbound ones.
- Each flow to the same destination IP and port needs a distinct source port, and about 64000 ephemeral ports exist, so one NAT address can hold roughly that many simultaneous connections to one destination. Check the current AWS limits.
- Port exhaustion shows as intermittent connect timeouts under heavy outbound traffic.
- IPv6 has 2^128 addresses and removes the need for NAT, though firewalls remain.
@diagram flow
caption: Outbound traffic through a NAT gateway
nodes:
  - "Pod 10.0.16.5:41000|private address|app"
  - "NAT gateway|rewrites to public IP and port|cp"
  - "Internet server|sees the public address|ext"
@h See your public address and ports
```bash title="NAT facts" lab
curl -s https://checkip.amazonaws.com        # the address the world sees
ip -4 addr show | grep inet                  # your private address
cat /proc/sys/net/ipv4/ip_local_port_range   # source ports available per destination
ss -s | head -3                              # socket counts
```
@check
Why can a busy NAT gateway cause random timeouts? || It can run out of source ports for flows to the same destination.
@end
