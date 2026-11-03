---
title: VPC fundamentals, CIDR planning and subnets
minutes: 45
objectives:
  - Plan non-overlapping CIDR ranges for many VPCs and clusters
  - Lay out public, private and isolated subnets across Availability Zones
  - Build route tables and Internet and NAT gateways that match the layout
---
A **VPC** is your private network inside a Region. Its address plan is the one decision that is very hard to change later, so it gets its own careful treatment.

@concept What a VPC is
@plain
A VPC is a virtual network that you define with an IP range. Resources such as EC2 instances, load balancers, databases and EKS nodes get private IP addresses from it.
@problem
Without isolation every customer would share one flat network. A VPC gives you your own address space, routing and firewall rules.
@does
- Spans all Availability Zones (AZs) of one Region; subnets live in exactly one AZ.
- Has a primary IPv4 CIDR (between /16 and /28) and optionally secondary CIDRs and IPv6 CIDRs. Check the current quota for CIDRs per VPC.
- Includes an implicit router, a main route table, a default security group and a default NACL.
- Every account has a **default VPC** in each Region. Do not run production in it; create your own.
@diagram layers
caption: Building blocks inside one Region
layers:
  - {label: "Region", nodes: ["VPC 10.20.0.0/16|your network|cp"]}
  - {label: "AZ a", nodes: ["Public subnet|10.20.0.0/24|info", "Private subnet|10.20.10.0/22|app"]}
  - {label: "AZ b", nodes: ["Public subnet|10.20.1.0/24|info", "Private subnet|10.20.14.0/22|app"]}
@h Inspect what exists
```bash title="List VPCs and subnets" lab
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,IsDefault]' --output table
aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-0123456789abcdef0 \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,AvailableIpAddressCount]' --output table
```
@end

@concept CIDR planning
@plain
CIDR notation `10.20.0.0/16` means the first 16 bits are fixed and the remaining 16 are yours: 65,536 addresses. A smaller number after the slash means a bigger network.
@problem
Overlapping ranges cannot be peered, routed through a Transit Gateway, or joined to a VPN. Choosing `10.0.0.0/16` for every VPC guarantees pain.
@does
- Use RFC 1918 space (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). Reserve ranges per environment, Region and business unit in a central register or **VPC IPAM**.
- Size for Kubernetes: with the AWS VPC CNI each pod gets a VPC IP by default, so EKS needs far more addresses than node counts suggest. Plan large private subnets (for example /19 or /20) or use a secondary CIDR for pods (custom networking) or prefix delegation.
- AWS reserves five addresses in every subnet (network, router, DNS, future, broadcast).
- Leave room: do not allocate every block on day one.
@diagram cmp
caption: Planning approaches
cards:
  - {h: "Default 10.0.0.0/16 everywhere", kind: bad, items: ["Overlaps on first peering", "Forces NAT or renumbering"]}
  - {h: "Central register or IPAM", kind: ok, items: ["Unique block per VPC", "Summarised routes", "Room for growth"]}
@h Calculate and request from IPAM
```python title="CIDR arithmetic with the standard library"
import ipaddress
vpc = ipaddress.ip_network("10.20.0.0/16")
subnets = list(vpc.subnets(new_prefix=20))     # sixteen /20 blocks
print(len(subnets), "x /20,", subnets[0].num_addresses - 5, "usable each")
print(subnets[0], subnets[1])
```
```bash title="Allocate with IPAM" lab
aws ec2 create-ipam --description org-ipam --operating-regions RegionName=eu-west-1
aws ec2 create-vpc --ipv4-ipam-pool-id ipam-pool-0123456789abcdef0 --ipv4-netmask-length 16
```
:::tip
Allocate each VPC from a /16 and keep a summary route in mind: one /14 per environment lets a single route cover all VPCs in that environment.
:::
@check
How many addresses can you use in a /24 subnet? || 251, because AWS reserves five of the 256.
@end

@concept Subnets and Availability Zones
@plain
A subnet is a slice of the VPC range placed in one AZ. Whether it is "public" or "private" depends only on its route table.
@problem
To survive an AZ failure you need workloads in more than one AZ, and to protect databases you need places with no internet route at all.
@does
- **Public subnet**: route to an Internet Gateway; instances may have public IPs.
- **Private subnet**: no direct internet route; outbound through NAT if needed.
- **Isolated subnet**: no route to the internet at all, for databases and internal tiers.
- Use at least two, preferably three AZs. Use AZ IDs (`euw1-az1`) when coordinating across accounts because AZ names are shuffled per account.
@diagram flow
caption: Typical three-tier layout
nodes:
  - "Public subnets|ALB and NAT|info"
  - "Private app subnets|EKS nodes, EC2|app"
  - "Isolated data subnets|RDS, no internet route|ok"
@h Create a subnet
```hcl title="subnet.tf"
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.20.16.0/20"
  availability_zone = "eu-west-1a"
  tags = {
    Name                              = "private-a"
    "kubernetes.io/role/internal-elb" = "1"
  }
}
```
:::note
The `kubernetes.io/role/elb` tag (public) and `kubernetes.io/role/internal-elb` tag (private) let the AWS Load Balancer Controller discover subnets for load balancers.
:::
@check
What makes a subnet public? || A route in its route table to an Internet Gateway (plus a public or Elastic IP on the resource).
@end

@concept Route tables
@plain
A route table is a list of destination ranges and where to send them. The most specific match (longest prefix) wins.
@problem
Traffic needs rules for where to go: other subnets, the internet, a peered VPC, a VPN, a firewall.
@does
- Every VPC has a `local` route for its own CIDRs; it cannot be removed.
- Targets: Internet Gateway, NAT gateway, Transit Gateway, VPC peering, VPN or Direct Connect gateway, gateway endpoints, network interface (appliance), egress-only IGW.
- Each subnet is associated with one route table (the main one by default). Use explicit associations.
- Edge associations also let you route traffic entering via an IGW or VGW.
@diagram flow
caption: Longest prefix match for a packet to 10.30.4.7
numbered: true
nodes:
  - "Packet|to 10.30.4.7|plain"
  - "10.20.0.0/16 local|no match|info"
  - "10.30.0.0/16 tgw|matches|ok"
  - "0.0.0.0/0 nat|less specific|warn"
  - "Sent to Transit Gateway|most specific wins|cp"
@h Route tables
```bash title="Show and add routes" lab
aws ec2 describe-route-tables --filters Name=vpc-id,Values=vpc-0123456789abcdef0 \
  --query 'RouteTables[].Routes[].[DestinationCidrBlock,GatewayId,NatGatewayId,TransitGatewayId,State]' --output table
aws ec2 create-route --route-table-id rtb-0123456789abcdef0 \
  --destination-cidr-block 0.0.0.0/0 --nat-gateway-id nat-0123456789abcdef0
```
@end

@concept Internet Gateway and public addressing
@plain
An **Internet Gateway (IGW)** connects a VPC to the public internet. It performs one-to-one NAT between a private address and the instance's public or Elastic IP.
@problem
Private addresses are not routable on the internet; something must translate them.
@does
- Horizontally scaled and managed; no bandwidth limit to plan for.
- A resource is reachable from the internet only if its subnet routes `0.0.0.0/0` to the IGW, it has a public IPv4 or Elastic IP, and security group and NACL allow it.
- Public IPv4 addresses are charged hourly; check current pricing. Prefer load balancers in front of private workloads.
- **Egress-only internet gateway** gives IPv6 outbound without inbound.
@diagram flow
caption: Internet reachability checklist
numbered: true
nodes:
  - "IGW attached|to the VPC|cp"
  - "Route 0.0.0.0/0|to the IGW|info"
  - "Public or Elastic IP|on the resource|env"
  - "Security group and NACL|allow the port|warn"
  - "Reachable|all four true|ok"
@h Terraform
```hcl title="igw.tf"
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route" "public_default" {
  route_table_id         = aws_route_table.public.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.main.id
}
```
@check
Why can an instance with a public IP still be unreachable? || The route, security group or NACL may not allow it; all of them must permit the traffic.
@end

@concept NAT gateways
@plain
A **NAT gateway** lets instances in private subnets start connections to the internet while blocking inbound connections from it.
@problem
Private nodes still need to pull images, patches and call external APIs, but must not be directly reachable.
@does
- Lives in a **public subnet** with an Elastic IP; private route tables send `0.0.0.0/0` to it.
- Zonal: create one per AZ and route each AZ to its own, to avoid cross-AZ charges and a single point of failure. Regional NAT gateways exist as a newer option; check the current documentation.
- Billed per hour plus per GB processed. High NAT data cost is a classic surprise; use VPC endpoints for AWS services to bypass it.
- Source IP seen by the internet is the Elastic IP, useful for allow-listing at partners.
@diagram seq
caption: Outbound connection through NAT
actors: ["Pod or instance|10.20.16.5|app", "NAT gateway|public subnet|cp", "Internet|203.0.113.10|ext"]
steps:
  - "0>1: SYN to 203.0.113.10 | req"
  - "1>2: source rewritten to the Elastic IP | req"
  - "2>1: reply | resp"
  - "1>0: destination rewritten back | resp"
  - "note 0..2: unsolicited inbound packets are dropped"
@h Per-AZ NAT with Terraform
```hcl title="nat.tf"
resource "aws_eip" "nat" {
  for_each = toset(["a", "b", "c"])
  domain   = "vpc"
}

resource "aws_nat_gateway" "az" {
  for_each      = aws_eip.nat
  allocation_id = each.value.id
  subnet_id     = aws_subnet.public[each.key].id
}
```
:::warn
A single NAT gateway for all AZs is cheaper but loses outbound access for every AZ if its AZ fails, and adds cross-AZ data charges. Choose deliberately per environment.
:::
@choose Outbound design
One NAT per AZ | production | tiny dev environments
Single NAT | dev and cost-sensitive tests | production with availability goals
VPC endpoints plus NAT | heavy traffic to S3, ECR and other AWS services | you only call third-party hosts
@end
