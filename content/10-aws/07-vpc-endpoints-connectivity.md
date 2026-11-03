---
title: Endpoints, PrivateLink, peering and Transit Gateway
minutes: 50
objectives:
  - Reach AWS services privately with gateway and interface endpoints
  - Publish and consume a service with PrivateLink
  - Choose between peering, Transit Gateway and VPN or Direct Connect for VPC connectivity
---
Once you have several VPCs and accounts you must decide how traffic crosses between them and how it reaches AWS services without going over the internet.

@concept Gateway endpoints
@plain
A **gateway endpoint** adds a route in your route table that sends S3 or DynamoDB traffic over the AWS network, not through NAT or the internet.
@problem
Pods pulling container layers or writing to S3 through a NAT gateway pay per GB and depend on internet egress.
@does
- Only S3 and DynamoDB. Free of charge for the endpoint itself.
- Implemented as a prefix list route in selected route tables, so no IP address is consumed.
- An **endpoint policy** limits which buckets or actions are reachable through it.
- Works only inside the VPC; not reachable from on-premises or over peering.
@diagram flow
caption: S3 traffic with and without a gateway endpoint
nodes:
  - "Pod|in private subnet|app"
  - "Route table|prefix list to vpce|cp"
  - "Gateway endpoint|AWS network|info"
  - "S3|same Region|ok"
@h Create one
```hcl title="s3-endpoint.tf"
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.eu-west-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for rt in aws_route_table.private : rt.id]
}
```
```bash title="Check the route" lab
aws ec2 describe-vpc-endpoints --query 'VpcEndpoints[].[VpcEndpointId,ServiceName,VpcEndpointType]' --output table
aws ec2 describe-route-tables --route-table-ids rtb-0123456789abcdef0 --query 'RouteTables[].Routes[?GatewayId!=`local`]'
```
@check
Why is the S3 gateway endpoint a good first cost saver? || It is free and removes S3 traffic from the NAT gateway data processing charge.
@end

@concept Interface endpoints and PrivateLink
@plain
An **interface endpoint** puts an elastic network interface with a private IP in your subnet that fronts an AWS service or a partner service. It is powered by **AWS PrivateLink**.
@problem
Private workloads need ECR, STS, Secrets Manager, CloudWatch and others without public internet, and cross-account teams want to expose one service without peering whole networks.
@does
- One ENI per AZ; DNS names for the service resolve to those private IPs when **private DNS** is enabled.
- Accessible from on-premises over VPN or Direct Connect, and across peering or Transit Gateway.
- Hourly plus per-GB charges; check current pricing. Share endpoints in a central VPC where sensible.
- Attach a security group to the endpoint and an endpoint policy for authorization.
- Typical EKS private cluster endpoints: `ecr.api`, `ecr.dkr`, `sts`, `ec2`, `logs`, `s3` (gateway) and `eks`.
@diagram layers
caption: Interface endpoint in a VPC
layers:
  - {label: "Your VPC", nodes: ["Pod|calls ecr.eu-west-1.amazonaws.com|app", "Endpoint ENI|10.20.16.40 per AZ|info"]}
  - {label: "AWS PrivateLink", nodes: ["Private DNS|overrides public name|cp"]}
  - {label: "Service", nodes: ["Amazon ECR|reached over AWS network|ok"]}
@h Create interface endpoints
```bash title="Private ECR path" lab
for svc in ecr.api ecr.dkr sts logs; do
  aws ec2 create-vpc-endpoint --vpc-id vpc-0123456789abcdef0 --vpc-endpoint-type Interface \
    --service-name com.amazonaws.eu-west-1.$svc --subnet-ids subnet-0aaa subnet-0bbb \
    --security-group-ids sg-0123456789abcdef0 --private-dns-enabled
done
```
```json title="endpoint-policy.json"
{
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": "*",
      "Action": ["ecr:GetAuthorizationToken", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"],
      "Resource": "*"
    }
  ]
}
```
:::note
ECR image layers come from S3, so a private ECR setup needs the S3 gateway endpoint too.
:::
@end

@concept Publishing a service with PrivateLink
@plain
A service provider puts a **Network Load Balancer** (or Gateway Load Balancer) in front of the service and creates an **endpoint service**. Consumers create an interface endpoint to it.
@problem
Peering exposes the whole network and requires non-overlapping ranges. PrivateLink exposes a single service, one direction, and works with overlapping CIDRs.
@does
- Provider approves connection requests (or auto-accepts) and can restrict allowed principals.
- Consumers see a private IP and a DNS name in their VPC; the provider never sees the consumer network, only the NLB source addresses (or proxy protocol data).
- Traffic is one way: consumer to provider.
- Cross-Region support exists in newer form; check the current documentation.
@diagram seq
caption: Consumer reaches a provider service
actors: ["Consumer app|VPC A|app", "Endpoint ENI|VPC A subnet|info", "NLB|provider VPC B|cp", "Service|targets|env"]
steps:
  - "0>1: connect to vpce DNS name | req"
  - "1>2: PrivateLink carries traffic | tls"
  - "2>3: forwarded to target | req"
  - "3>0: response returns the same path | resp"
@h Provider side
```hcl title="endpoint-service.tf"
resource "aws_vpc_endpoint_service" "orders" {
  acceptance_required        = true
  network_load_balancer_arns = [aws_lb.orders_nlb.arn]
  allowed_principals         = ["arn:aws:iam::444455556666:root"]
}
```
@choose Cross-VPC access
PrivateLink | one service shared with many consumers or overlapping CIDRs | all-to-all network connectivity
Peering or TGW | broad network reachability | you need to hide the rest of the network
@check
Can PrivateLink work between VPCs with the same CIDR? || Yes. Only the endpoint ENI address is used, not routing between the ranges.
@end

@concept VPC peering
@plain
A **peering connection** links two VPCs so they route to each other using private IPs, in the same or different accounts and Regions.
@problem
Two VPCs need direct, low-cost, low-latency communication without a gateway device.
@does
- Needs non-overlapping CIDRs. Not transitive: A to B and B to C does not give A to C.
- Requires routes on both sides and security group or NACL permissions. Security group references work across peered VPCs in the same Region.
- No bandwidth bottleneck; same-AZ traffic within the same Region is cheaper than cross-AZ; check pricing.
- Does not scale to a mesh: n VPCs need n(n-1)/2 connections.
@diagram cmp
caption: Peering is not transitive
cards:
  - {h: "A to B", kind: ok, items: ["Peering exists", "Routes on both sides"]}
  - {h: "B to C", kind: ok, items: ["Peering exists", "Routes on both sides"]}
  - {h: "A to C", kind: bad, items: ["No path", "Needs its own peering or a TGW"]}
@h Create and route
```bash title="Peer two VPCs" lab
aws ec2 create-vpc-peering-connection --vpc-id vpc-0aaa --peer-vpc-id vpc-0bbb --peer-owner-id 444455556666
aws ec2 accept-vpc-peering-connection --vpc-peering-connection-id pcx-0123456789abcdef0
aws ec2 create-route --route-table-id rtb-0aaa --destination-cidr-block 10.30.0.0/16 --vpc-peering-connection-id pcx-0123456789abcdef0
```
@end

@concept Transit Gateway
@plain
A **Transit Gateway (TGW)** is a regional hub. VPCs, VPNs and Direct Connect attach to it, and route tables on the TGW decide who can talk to whom.
@problem
Meshes of peerings become unmanageable, and you also want central inspection and shared on-premises connectivity.
@does
- Attachments: VPC, VPN, Direct Connect gateway, peering to another TGW (cross-Region), Connect (SD-WAN).
- **TGW route tables** with association and propagation enable segmentation, for example prod and dev isolated, both reaching shared services.
- Share through AWS RAM across the organization. Each VPC attachment lives in one subnet per AZ.
- Billed per attachment-hour and per GB processed; check current pricing and quotas.
@diagram layers
caption: Hub and spoke with segmentation
layers:
  - {label: "Hub", nodes: ["Transit Gateway|route tables per segment|cp"]}
  - {label: "Spokes", nodes: ["Prod VPC|attachment|app", "Dev VPC|attachment|env", "Shared services VPC|attachment|info"]}
  - {label: "Outside", nodes: ["Site-to-site VPN|branch|ext", "Direct Connect|datacentre|ext"]}
@h Create and attach
```hcl title="tgw.tf"
resource "aws_ec2_transit_gateway" "hub" {
  description                     = "org hub"
  default_route_table_association = "disable"
  default_route_table_propagation = "disable"
  auto_accept_shared_attachments  = "enable"
}

resource "aws_ec2_transit_gateway_vpc_attachment" "prod" {
  transit_gateway_id = aws_ec2_transit_gateway.hub.id
  vpc_id             = aws_vpc.prod.id
  subnet_ids         = aws_subnet.tgw[*].id
}
```
:::tip
Disable default association and propagation and manage route tables explicitly. The defaults put every attachment in one flat network.
:::
@check
How does a TGW provide isolation between prod and dev? || Separate TGW route tables, with each attachment associated to one table and propagating only to the tables that should reach it.
@end

@concept VPN, Direct Connect and choosing connectivity
@plain
**Site-to-Site VPN** gives encrypted tunnels over the internet. **Direct Connect** is a dedicated private link from your site to AWS.
@problem
Hybrid environments need predictable connection to on-premises systems.
@does
- VPN: two tunnels per connection for redundancy, quick to set up; throughput per tunnel is limited (check the current limit). BGP or static routes.
- Direct Connect: dedicated or hosted ports, consistent latency, a private virtual interface to a VPC or Direct Connect gateway, or a transit virtual interface to a TGW. Not encrypted by default; use MACsec or VPN over it where required.
- Use both for resilience: Direct Connect primary, VPN backup.
@diagram flow
caption: Hybrid options
nodes:
  - "On-premises|datacentre|ext"
  - "VPN or Direct Connect|encrypted or dedicated|cp"
  - "Transit Gateway|hub|info"
  - "VPCs|workloads|app"
@choose Connectivity
Peering | two VPCs, simple and cheap | many VPCs or on-premises transit
Transit Gateway | many VPCs, segmentation, hybrid | two VPCs that never grow
PrivateLink | publish one service | full network reachability needed
Site-to-Site VPN | fast start, backup path | large steady throughput needs
Direct Connect | steady, high volume, consistent latency | you need it this week
@end
