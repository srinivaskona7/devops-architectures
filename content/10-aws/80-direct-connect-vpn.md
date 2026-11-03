---
title: Direct Connect and Site-to-Site VPN
minutes: 55
objectives:
  - Compare Site-to-Site VPN, Direct Connect and combined designs
  - Design resilient hybrid connectivity with BGP and multiple links
  - Choose between private, transit and public virtual interfaces
---
Hybrid architectures need a reliable path between the data centre and AWS. VPN is quick and encrypted over the internet. Direct Connect is a private circuit with predictable performance.

@concept Site-to-Site VPN
@plain
A **Site-to-Site VPN** creates two IPsec tunnels between your customer gateway device and AWS over the internet.
@problem
You need encrypted connectivity within minutes, without ordering a circuit.
@does
- Each connection has **two tunnels** in different AZs; configure both on your device.
- Terminates on a virtual private gateway (one VPC) or a transit gateway (many VPCs).
- Routing is dynamic BGP (preferred) or static.
- Each tunnel has a bandwidth limit (about 1.25 Gbps; check the current quota). ECMP on a transit gateway can aggregate tunnels.
- Accelerated VPN uses Global Accelerator edge locations for steadier performance.
@diagram flow
caption: Redundant tunnels
nodes:
  - "On-premises router|customer gateway|ext"
  - "Two tunnels|IPsec over internet|warn"
  - "Transit gateway|or virtual gateway|cp"
  - "VPCs|private routes|ok"
@h Terraform
```hcl title="vpn.tf"
resource "aws_customer_gateway" "dc" {
  bgp_asn    = 65010
  ip_address = "203.0.113.10"
  type       = "ipsec.1"
}

resource "aws_vpn_connection" "dc" {
  customer_gateway_id = aws_customer_gateway.dc.id
  transit_gateway_id  = aws_ec2_transit_gateway.main.id
  type                = "ipsec.1"
  static_routes_only  = false
}
```
@check
Why configure both tunnels? || AWS can take one down for maintenance; both give redundancy.
@end

@concept Direct Connect basics
@plain
**AWS Direct Connect** is a dedicated private network connection from your site to an AWS Direct Connect location.
@problem
Internet VPN performance varies, and large transfers over the internet are slow and costly.
@does
- **Dedicated connections** (1, 10, 100 Gbps and more where offered) or **hosted connections** from partners at smaller speeds.
- Lead time is weeks, so order early.
- Traffic is not encrypted by default; add MACsec on supported ports or run an IPsec VPN over it.
- Data transfer out is cheaper than internet egress; check current rates.
- Needs a cross connect in a colocation facility, or a partner.
@diagram flow
caption: Physical path
nodes:
  - "Your router|data centre|ext"
  - "Cross connect|colocation facility|info"
  - "Direct Connect port|AWS location|cp"
  - "AWS Region|backbone|ok"
@h Describe connections
```bash title="Connections" lab
aws directconnect describe-connections --query 'connections[].[connectionName,bandwidth,connectionState,location]' --output table
```
@end

@concept Virtual interfaces and the Direct Connect gateway
@plain
A **virtual interface (VIF)** is a VLAN with a BGP session on a Direct Connect connection. A **Direct Connect gateway** lets one VIF reach VPCs in many Regions.
@problem
One physical link must carry private VPC traffic, transit gateway traffic and public AWS service traffic.
@does
- **Private VIF**: to a VPC through a virtual private gateway or Direct Connect gateway.
- **Transit VIF**: to a transit gateway through a Direct Connect gateway; best for many VPCs.
- **Public VIF**: reach AWS public endpoints such as S3 using public IPs.
- The Direct Connect gateway does not provide VPC to VPC transit by itself.
- BGP prefix limits apply; summarise routes (check current quotas).
@diagram layers
caption: One link, several VIFs
layers:
  - {label: "Physical", nodes: ["Connection|10 Gbps port|info"]}
  - {label: "Virtual interfaces", nodes: ["Private VIF|one VPC|app", "Transit VIF|transit gateway|cp", "Public VIF|AWS public services|ext"]}
  - {label: "AWS side", nodes: ["Direct Connect gateway|multi Region|ok"]}
@h Gateway association
```hcl title="dx-gateway.tf"
resource "aws_dx_gateway" "main" {
  name            = "main"
  amazon_side_asn = 64512
}

resource "aws_dx_gateway_association" "tgw" {
  dx_gateway_id         = aws_dx_gateway.main.id
  associated_gateway_id = aws_ec2_transit_gateway.main.id
  allowed_prefixes      = ["10.0.0.0/16", "10.1.0.0/16"]
}
```
@check
Which VIF type serves many VPCs through a transit gateway? || A transit VIF.
@end

@concept Resilience models
@plain
AWS recommends resilience levels from development up to maximum resiliency, based on the number of locations and links.
@problem
A single link and location is a single point of failure for the whole data centre connection.
@does
- **Maximum resiliency**: two locations with two devices each, so four connections. Survives device, link and location failure.
- **High resiliency**: two locations with one connection each. Survives a location failure.
- **Development and test**: one connection with a VPN backup.
- Add a Site-to-Site VPN as a backup path with lower BGP preference.
- The SLA applies only to supported resilient designs; check the current text.
@diagram cmp
caption: Resilience tiers
cards:
  - {h: "Maximum", kind: ok, items: ["Two locations", "Two devices each", "4 connections"]}
  - {h: "High", kind: info, items: ["Two locations", "One connection each", "2 connections"]}
  - {h: "Dev and test", kind: warn, items: ["One connection", "VPN backup"]}
@choose Resilience level
Maximum | production that cannot lose connectivity | a lab environment
High | production with some tolerance for device failure | single device failure is unacceptable
Dev and test | non critical workloads | any production dependency
@end

@concept BGP routing and path selection
@plain
BGP exchanges routes between your router and AWS. When several paths exist, the most specific route and the documented preference order decide.
@problem
Traffic must take the intended path and fail over predictably.
@does
- Longest prefix match wins first. For equal prefixes AWS prefers Direct Connect over VPN (check the current preference documentation).
- Influence inbound traffic with AS path prepending or communities, outbound with local preference.
- Use BFD for fast failure detection and BGP MD5 authentication.
- Example: if `10.0.0.0/8` is advertised on Direct Connect and `10.0.0.0/16` on VPN, traffic to `10.0.1.5` takes the VPN because the /16 is more specific.
@diagram flow
caption: Failover
nodes:
  - "Primary DX|preferred|ok"
  - "Link fails|BFD detects|bad"
  - "VPN backup|takes over|warn"
@h Inspect propagated routes
```bash title="TGW routes" nocheck
aws ec2 search-transit-gateway-routes --transit-gateway-route-table-id tgw-rtb-0abc \
  --filters Name=type,Values=propagated --query 'Routes[].[DestinationCidrBlock,State]'
```
@check
For 10.0.1.5, which wins, the /8 on DX or the /16 on VPN? || The /16 on VPN, because longest prefix wins.
@end

@concept Hybrid DNS and monitoring
@plain
Name resolution must work both ways, and the links must be monitored.
@problem
Connectivity without DNS means services still cannot find one another, and a silent tunnel failure goes unnoticed.
@does
- Route 53 Resolver **inbound endpoints** accept queries from on-premises; **outbound endpoints** with rules forward corporate domains to on-premises DNS.
- Place endpoints in at least two AZs.
- Monitor `ConnectionState`, `ConnectionBpsEgress` and VPN `TunnelState`; alarm on state changes.
- Usual production design: Direct Connect primary and VPN backup.
@diagram flow
caption: Hybrid DNS
nodes:
  - "On-prem DNS|corp zone|ext"
  - "Resolver endpoints|inbound and outbound|cp"
  - "Private hosted zone|aws zone|info"
@h Forwarding rule and alarm
```hcl title="resolver.tf"
resource "aws_route53_resolver_rule" "corp" {
  domain_name          = "corp.example.com"
  rule_type            = "FORWARD"
  resolver_endpoint_id = aws_route53_resolver_endpoint.out.id
  target_ip {
    ip = "10.200.0.2"
  }
}

resource "aws_cloudwatch_metric_alarm" "tunnel" {
  alarm_name          = "vpn-tunnel-down"
  namespace           = "AWS/VPN"
  metric_name         = "TunnelState"
  dimensions          = { VpnId = "vpn-0abc123" }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "LessThanThreshold"
}
```
@check
Which design is usual for production hybrid? || Direct Connect primary with VPN backup, or two resilient Direct Connect locations.
@end
