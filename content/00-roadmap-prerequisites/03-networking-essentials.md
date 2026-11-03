---
title: Networking essentials
minutes: 25
objectives:
  - Explain IP addresses, subnets and CIDR notation
  - Trace what happens between typing a URL and seeing a page
  - Read a TLS handshake and a load balancer diagram
---
Everything in cloud and Kubernetes is networking in disguise. These six ideas are enough to follow the rest of the path.

@concept IP addresses and CIDR
@plain
An **IP address** is the street address of a machine on a network. A **CIDR block** such as `10.0.0.0/16` describes a whole range of addresses: the number after the slash says how many leading bits are fixed.
@problem
Without a compact way to describe address ranges, you cannot split a network into parts, write firewall rules for groups of machines, or plan a VPC so its ranges do not collide with another network.
@does
- `/16` fixes 16 bits and leaves 16 free, so it holds 65,536 addresses.
- `/24` holds 256 addresses, `/28` holds 16.
- Cloud providers reserve a few addresses in each subnet, so usable space is slightly smaller.
- Private ranges (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`) are not routed on the public internet.
@diagram layers
caption: One VPC range split into subnets
layers:
  - {label: "VPC 10.0.0.0/16", nodes: ["65,536 addresses|whole network|info"]}
  - {label: "Public subnets", nodes: ["10.0.0.0/24|256 addresses|ext", "10.0.1.0/24|256 addresses|ext"]}
  - {label: "Private subnets", nodes: ["10.0.10.0/24|256 addresses|app", "10.0.11.0/24|256 addresses|app"]}
  - {label: "Data subnets", nodes: ["10.0.20.0/24|256 addresses|db", "10.0.21.0/24|256 addresses|db"]}
@body
```python title="Count addresses in a CIDR block"
import ipaddress

for cidr in ["10.0.0.0/16", "10.0.1.0/24", "10.0.2.0/28"]:
    net = ipaddress.ip_network(cidr)
    print(cidr, "->", net.num_addresses, "addresses,", net.network_address, "to", net.broadcast_address)
```
@check
How many addresses are in a /20? || 2 to the power of (32 minus 20), which is 4,096.
Why must VPC ranges not overlap with your office network? || Overlapping ranges cannot be routed to each other, so VPN and peering would fail.
@end

@concept DNS
@plain
**DNS** turns a name like `shop.example.com` into an IP address, the way a phone book turns a name into a number.
@problem
People remember names, but machines route by number. Servers also move and scale, so their addresses change; a name that can be repointed hides that change.
@does
- A resolver asks a chain of servers: root, then the top-level domain, then the domain's own name server.
- Answers are cached for a time set by the record's **TTL**.
- Record types matter: `A` (name to IPv4), `AAAA` (IPv6), `CNAME` (alias to another name), `TXT` (text), `MX` (mail).
@diagram seq
caption: Resolving shop.example.com
actors: ["Browser|client|app", "Resolver|recursive|env", "Root|. servers|plain", "Name server|example.com|ok"]
steps:
  - "0>1: shop.example.com?"
  - "1>2: who handles .com? | req"
  - "2>1: ask the .com servers | resp"
  - "1>3: shop.example.com? | req"
  - "3>1: A 203.0.113.10, TTL 300 | resp"
  - "1>0: 203.0.113.10 | resp"
  - "note 0..1: cached for 300 seconds"
@body
```bash title="Look up records"
dig +short A shop.example.com
dig +short CNAME www.example.com
dig +trace shop.example.com     # follow the whole delegation chain
```
:::tip
Before a migration, lower the record's TTL a day ahead so the change takes effect quickly, then raise it again afterwards.
:::
@end

@concept TCP, ports and HTTP
@plain
**TCP** delivers bytes reliably and in order between two machines. A **port** says which program on the machine should get them. **HTTP** is a set of rules, sent over TCP, for asking for pages and data.
@problem
The network underneath loses, duplicates and reorders packets. Programs need a dependable pipe, and one machine runs many programs that must not receive each other's data.
@does
- A connection starts with a three-step handshake (SYN, SYN-ACK, ACK).
- Common ports: 22 SSH, 53 DNS, 80 HTTP, 443 HTTPS, 5432 PostgreSQL, 3306 MySQL, 6379 Redis.
- An HTTP request has a method (GET, POST), a path, headers and an optional body; the response has a status code.
- Status families: 2xx success, 3xx redirect, 4xx the client was wrong, 5xx the server failed.
@diagram seq
caption: TCP handshake, then one HTTP request
actors: ["Client|browser|app", "Server|web app|ok"]
steps:
  - "0>1: SYN | req"
  - "1>0: SYN-ACK | resp"
  - "0>1: ACK | req"
  - "0>1: GET /products HTTP/1.1 | req"
  - "1>0: 200 OK + JSON | resp"
@body
| Status | Meaning | Typical cause |
|---|---|---|
| 200 | OK | Normal success |
| 301/302 | Redirect | Moved page, HTTP to HTTPS |
| 401 | Not authenticated | Missing or expired token |
| 403 | Not allowed | Authenticated but no permission |
| 404 | Not found | Wrong path or deleted resource |
| 429 | Too many requests | Rate limit reached |
| 502/503/504 | Bad gateway, unavailable, timeout | Backend down, overloaded or slow |
@end

@concept TLS and certificates
@plain
**TLS** encrypts a connection and proves who you are talking to. A **certificate** is a signed statement that a public key belongs to a name.
@problem
Without TLS anyone on the path can read or change traffic, and nothing stops an imposter from answering for a name.
@does
- The server presents a certificate; the client checks it was signed by an authority it trusts, matches the name and has not expired.
- Both sides agree on keys, then encrypt the rest of the session.
- In **mutual TLS (mTLS)** the client also presents a certificate, so each side knows the other. Service meshes use this between services.
@diagram flow
caption: What a client verifies in a server certificate
numbered: true
nodes:
  - "Chain|signed by a trusted CA|info"
  - "Name|matches the host requested|app"
  - "Dates|not expired, not yet valid|warn"
  - "Revocation|not on a blocklist|bad"
  - "Session keys|agreed, traffic encrypted|ok"
@body
```bash title="Inspect a certificate"
openssl s_client -connect shop.example.com:443 -servername shop.example.com </dev/null 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates
```
:::warn
Never disable certificate verification to "make it work" (`curl -k`, `verify=False`). Fix the trust chain or the name instead.
:::
@end

@concept Load balancing
@plain
A **load balancer** spreads incoming requests across several identical servers and stops sending traffic to servers that are unhealthy.
@problem
One server is a single point of failure and a ceiling on capacity. Clients should not need to know how many servers exist or which are alive.
@does
- **Layer 4** balancers route by IP and port and are very fast; **layer 7** balancers read HTTP and can route by host, path or header.
- Health checks remove failed servers automatically.
- Common algorithms: round robin, least connections, hashing for stickiness.
@diagram flow
caption: Clients, one entry point, many servers
nodes:
  - "Clients|many|ext"
  - "Load balancer|health checks|env"
  - { group: "Server pool", kind: app, nodes: ["App 1|healthy|ok", "App 2|healthy|ok", "App 3|failing|bad"] }
@choose Layer 4 or layer 7
Layer 4 (network) | raw TCP or UDP, databases, very high throughput | you need routing by path or host
Layer 7 (application) | web apps, path or host routing, header rules, WAF | you only need fast passthrough of non-HTTP traffic
@end

@concept Firewalls and NAT
@plain
A **firewall** allows or blocks traffic by rule. **NAT** lets many private machines share one public address when they reach out to the internet.
@problem
Machines on a private network need to download updates without being reachable from the internet, and most traffic should be blocked by default.
@does
- Rules match source, destination, port and protocol. Cloud security groups are **stateful**: replies to allowed traffic are allowed back automatically.
- **Source NAT** rewrites the sender's private address to the NAT device's public address and remembers the mapping.
- Default stance: deny everything, then allow only what is needed.
@diagram flow
caption: Outbound only through a NAT gateway
nodes:
  - "Private server|10.0.10.5|app"
  - "NAT gateway|public address|env"
  - "Internet|updates, APIs|ext"
@check
Why can an internet user not start a connection to the private server? || The NAT device only translates replies to connections the private server opened; there is no inbound mapping.
@end
