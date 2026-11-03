---
title: Network topologies and account structure
minutes: 55
objectives:
  - Design an account or subscription layout that limits blast radius
  - Plan non-overlapping address space and choose between peering and a hub
  - Control ingress, egress and private access with a layered network design
---
The network and the account layout are the hardest parts of a cloud design to change. Decide them early and deliberately.

@concept Why separate accounts, subscriptions and projects
@plain
Each cloud has a top-level boundary for resources and billing: AWS account, Azure subscription, Google Cloud project. Using several gives hard walls between workloads.
@problem
One big account means one mistake or one stolen credential can reach everything, and quotas, costs and permissions all mix together.
@does
- Isolates blast radius, permissions, quotas and billing.
- Lets production have stricter rules than development.
- Central groups apply guardrails above the accounts: AWS Organizations, Azure management groups, Google Cloud folders and organization.
- Split by environment and by workload sensitivity, not by every microservice.
@diagram layers
caption: A common hierarchy
layers:
  - {label: "Organization root", nodes: ["Guardrails|policies for all|cp"]}
  - {label: "Shared", nodes: ["Security|logs and findings|warn", "Network|hub and egress|info", "Tooling|CI and registry|app"]}
  - {label: "Workloads", nodes: ["Prod|strict|ok", "Non-prod|relaxed|plain", "Sandbox|budget capped|env"]}
@check
Why use several accounts? || Hard boundaries for blast radius, permissions, quotas and billing.
@end

@concept A landing zone layout
@plain
A landing zone is a pre-built account structure with security, logging, networking and guardrails already set up before teams arrive.
@problem
Without it, every team builds its own network and security, differently and often wrongly.
@does
- A management account used only for organisation tasks.
- A log archive account for audit logs, write-only for others.
- A security account for detection tools and read access.
- A network account for the hub, shared egress and DNS.
- Workload accounts created by automation with baseline settings.
- Vendor tools: AWS Control Tower, Azure landing zones, Google Cloud setup guides. Check the current docs for each.
@diagram flow
caption: Account vending
nodes:
  - "Request|team asks for account|plain"
  - "Pipeline|creates from template|cp"
  - "Baseline|logging, roles, network|info"
  - "Handover|team deploys|ok"
@h Baseline in code
```hcl title="account-baseline.tf" nocheck
module "baseline" {
  source      = "./modules/account-baseline"
  account_id  = var.account_id
  environment = "prod"
  log_bucket  = var.central_log_bucket
  budget_usd  = 5000
}
```
@check
What does an account vending pipeline guarantee? || Every new account starts with the same logging, roles and network baseline.
@end

@concept Address planning
@plain
Every network needs IP ranges in CIDR notation. Ranges that overlap cannot be connected directly.
@problem
Overlapping ranges block peering, VPN and merges, and renumbering is painful.
@does
- Use private ranges 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16. Keep a central register.
- Size by growth. A /16 has 65,536 addresses. A /24 has 256, and clouds reserve a few per subnet (check the provider).
- Give each network a unique block that includes room for on-premises ranges.
- Kubernetes pods may use large secondary ranges, so plan for them.
@diagram cmp
caption: Plan once
cards:
  - {h: "Without a plan", kind: bad, items: ["Every team picks 10.0.0.0/16", "Peering fails", "Renumbering projects"]}
  - {h: "With a register", kind: ok, items: ["Unique block per network", "Room for growth", "On-premises ranges reserved"]}
@h Arithmetic
A /16 holds 2^(32-16) = 65,536 addresses. Carving it into /24 subnets gives 2^(24-16) = 256 subnets of 256 addresses each. Three zones with public, app and data tiers need 9 subnets, a small part of that block.
```python title="cidr.py"
import ipaddress

net = ipaddress.ip_network("10.20.0.0/16")
subs = list(net.subnets(new_prefix=24))
print(net.num_addresses, len(subs), subs[0], subs[1])
```
@check
How many /24 subnets fit in a /16? || 256.
@end

@concept Tiered subnets and traffic control
@plain
Inside a network, group resources by role into subnets with different exposure.
@problem
Putting databases in the same public subnet as web servers exposes them to the internet.
@does
- Public tier: load balancers only. Private app tier: compute with no public addresses. Data tier: databases, reachable only from the app tier.
- Control with security groups, network security groups or firewall rules: allow by reference to groups rather than wide CIDRs.
- Deny by default. Log denied flows.
- Place each tier in at least two or three zones.
@diagram layers
caption: Three-tier layout across zones
layers:
  - {label: "Public", nodes: ["Load balancer|internet facing|cp", "NAT|outbound only|info"]}
  - {label: "Private app", nodes: ["App servers or pods|no public IP|app"]}
  - {label: "Private data", nodes: ["Database|only from app tier|ok"]}
@h Security group rule by reference
```hcl title="db-sg.tf"
resource "aws_vpc_security_group_ingress_rule" "db_from_app" {
  security_group_id            = aws_security_group.db.id
  referenced_security_group_id = aws_security_group.app.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
```
@check
Which tier can have a public address? || Only the load balancer or edge tier.
@end

@concept Peering versus hub-and-spoke
@plain
Peering connects two networks directly. A hub connects many networks through a central router.
@problem
Full-mesh peering grows quickly and gives no central place to inspect traffic.
@does
- Peering is simple and cheap for a few networks. It is generally not transitive, so A to B and B to C does not mean A to C.
- A hub (Transit Gateway, Virtual WAN, Network Connectivity Center, or a hub network with a firewall) scales to many spokes and centralises egress and inspection.
- Hubs add data processing charges and become critical shared infrastructure.
@diagram flow
caption: Spokes through a hub
nodes:
  - "Spoke prod|workload network|app"
  - "Hub|routing and inspection|cp"
  - "Spoke dev|workload network|app"
  - "On-premises|VPN or dedicated link|ext"
@h Count of links
Full mesh for n networks needs n(n-1)/2 peerings. For n = 12: 12 x 11 / 2 = 66 peerings. A hub needs 12 attachments.
```python title="mesh.py"
for n in (4, 12, 20):
    print(n, n * (n - 1) // 2, n)
```
@choose Connect networks
Peering | two to five networks, simple needs | you need central inspection or transitive routing
Hub and spoke | many networks, shared services | a single small environment
Private endpoints only | only specific services are shared | you need full network reachability
@check
Is peering transitive? || No, it generally is not.
@end

@concept Ingress, egress and private access
@plain
Control what comes in, what goes out and how services talk without crossing the internet.
@problem
Open egress lets malware call home, and public endpoints for data services widen the attack surface.
@does
- Ingress: CDN or WAF at the edge, load balancer in the public tier, nothing else public.
- Egress: NAT or a firewall with allow-lists for known destinations. Log it.
- Private access: private endpoints for storage, databases and secrets, with matching private DNS.
- Hybrid: VPN for quick start, dedicated links for steady traffic, two of them for resilience.
@diagram flow
caption: Controlled path in and out
nodes:
  - "Internet|users|ext"
  - "CDN and WAF|edge filter|cp"
  - "Load balancer|public tier|info"
  - "App|private tier|app"
  - "Private endpoint|to storage and secrets|ok"
@check
What often breaks private endpoints? || DNS that still resolves to the public address.
@end

@concept DNS and name strategy
@plain
Names should point to services, not to IP addresses, and internal names need a plan.
@problem
Hard-coded IPs break at the first failover, and unmanaged private zones create name clashes.
@does
- Public zone per product domain. Private zones for internal names, attached to the networks that need them.
- Alias or CNAME records to load balancers. Short TTLs before cutovers.
- Central resolvers in the hub for hybrid name resolution.
- Naming convention: environment, region, service.
@diagram layers
caption: Name layers
layers:
  - {label: "Public", nodes: ["shop.example.com|alias to CDN|ext"]}
  - {label: "Internal", nodes: ["orders.prod.internal|private zone|info"]}
  - {label: "Hybrid", nodes: ["Forwarders|on-premises and cloud|cp"]}
@h Naming pattern
```text title="naming.txt" nocheck
<env>-<region>-<service>-<resource>
prod-euw1-orders-db
dev-euw1-orders-db
```
@check
Why use short TTLs before a cutover? || Clients then pick up the new record quickly.
@end

@concept Reference design and review
@plain
Combine accounts, address plan, tiers, hub and edge into one diagram and test it against failures.
@problem
Parts designed separately fail to fit together, such as a hub with no route for the logging account.
@does
- Draw the account tree, then one workload network with tiers, then the hub, then the edge.
- Walk three failure cases: loss of a zone, loss of the hub, a stolen credential in one account.
- Record the choices in ADRs, and enforce with policy.
@diagram flow
caption: Reference path
numbered: true
nodes:
  - "Org guardrails|policies and logs|cp"
  - "Network account|hub, DNS, egress|info"
  - "Workload account|three-tier network|app"
  - "Edge|CDN, WAF|ext"
  - "Review|failure walk-through|ok"
@check
Which three failures should a network review walk? || Loss of a zone, loss of the hub, and a stolen credential in one account.
@end
