---
title: Transit Gateway deep dive
minutes: 50
objectives:
  - Explain attachments, route tables, associations and propagation
  - Design segmented networks and inspection VPCs with multiple route tables
  - Peer Regions, share the gateway with RAM and reason about cost
---
A Transit Gateway (TGW) is a regional router that connects VPCs, VPNs and Direct Connect through one hub, replacing a mesh of peerings.

@concept Why a transit gateway
@plain
A TGW is a hub. Each network attaches once, and the hub routes between them.
@problem
VPC peering is not transitive. N VPCs fully meshed need N x (N - 1) / 2 peerings.
@does
- Worked count: 10 VPCs need 10 x 9 / 2 = 45 peerings, but only 10 TGW attachments.
- Attachment types: VPC, VPN, Direct Connect gateway, peering (another TGW), and Connect (SD-WAN).
- Bandwidth per VPC attachment is limited (check the current quota); you pay per attachment-hour and per GB processed.
- Regional resource; use TGW peering for multiple Regions.
@diagram flow
caption: Hub and spoke
nodes:
  - "VPC A|spoke|app"
  - "Transit gateway|hub|cp"
  - "VPC B|spoke|app"
  - "On-premises|VPN or DX|ext"
@h Gateway and attachment
```hcl title="tgw.tf"
resource "aws_ec2_transit_gateway" "main" {
  description                     = "main"
  amazon_side_asn                 = 64512
  default_route_table_association = "disable"
  default_route_table_propagation = "disable"
}

resource "aws_ec2_transit_gateway_vpc_attachment" "app" {
  transit_gateway_id = aws_ec2_transit_gateway.main.id
  vpc_id             = aws_vpc.app.id
  subnet_ids         = aws_subnet.tgw[*].id
}
```
@check
How many peerings does a full mesh of 10 VPCs need? || 45.
@end

@concept Route tables, associations and propagation
@plain
Each attachment is **associated** with one TGW route table that decides where its traffic goes. An attachment can **propagate** its routes into any number of tables.
@problem
Without separate tables every attachment can reach every other one, which breaks segmentation.
@does
- Association: which table is used for traffic entering from that attachment (one only).
- Propagation: which tables learn this attachment's CIDRs automatically.
- Static routes can be added, including blackhole routes.
- Default tables are convenient but disable them when you want explicit segmentation.
@diagram layers
caption: Association and propagation
layers:
  - {label: "Attachments", nodes: ["Prod VPC|assoc prod table|app", "Dev VPC|assoc dev table|app", "Shared services|propagates to both|ok"]}
  - {label: "Route tables", nodes: ["prod table|sees shared and prod|cp", "dev table|sees shared and dev|cp"]}
@h Associate and propagate
```hcl title="tgw-routes.tf"
resource "aws_ec2_transit_gateway_route_table" "prod" {
  transit_gateway_id = aws_ec2_transit_gateway.main.id
}

resource "aws_ec2_transit_gateway_route_table_association" "prod_vpc" {
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.app.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.prod.id
}

resource "aws_ec2_transit_gateway_route_table_propagation" "shared_to_prod" {
  transit_gateway_attachment_id  = aws_ec2_transit_gateway_vpc_attachment.shared.id
  transit_gateway_route_table_id = aws_ec2_transit_gateway_route_table.prod.id
}
```
@check
How many route tables can one attachment be associated with? || One.
@end

@concept Segmentation patterns
@plain
Use separate route tables to isolate environments while sharing common services.
@problem
Prod and dev must not talk, but both need DNS, logging and package mirrors.
@does
- Prod table: routes to prod VPCs and shared services only.
- Dev table: routes to dev VPCs and shared services only.
- Shared services VPC propagates into both tables, while prod and dev do not propagate into each other.
- Verify with Network Manager Route Analyzer and VPC Reachability Analyzer.
@diagram cmp
caption: Isolation
cards:
  - {h: "Prod table", kind: ok, items: ["Prod VPCs", "Shared services", "On-premises"]}
  - {h: "Dev table", kind: info, items: ["Dev VPCs", "Shared services"]}
  - {h: "No route", kind: bad, items: ["Prod to dev", "Dev to on-premises"]}
@choose Segmentation
Separate tables | environments, compliance zones | a tiny network with one team
Single default table | a lab | any regulated workload
@end

@concept Centralised inspection and egress
@plain
Send traffic through a central inspection VPC with firewalls, or through a central NAT, using appliance mode and route design.
@problem
Each VPC running its own firewall and NAT is costly and inconsistent.
@does
- Spokes route `0.0.0.0/0` to the TGW; the TGW forwards to the inspection VPC attachment.
- Enable **appliance mode** on the inspection attachment so both directions of a flow use the same AZ and the stateful firewall sees both.
- Egress VPC holds NAT gateways in each AZ and routes back to the TGW.
- Watch cross-AZ and TGW data processing charges.
@diagram flow
caption: Inspected path
numbered: true
nodes:
  - "Spoke VPC|default route to TGW|app"
  - "Transit gateway|spoke table|cp"
  - "Inspection VPC|firewall|warn"
  - "Egress VPC|NAT|ext"
@h Appliance mode
```hcl title="appliance.tf"
resource "aws_ec2_transit_gateway_vpc_attachment" "inspection" {
  transit_gateway_id     = aws_ec2_transit_gateway.main.id
  vpc_id                 = aws_vpc.inspection.id
  subnet_ids             = aws_subnet.inspection_tgw[*].id
  appliance_mode_support = "enable"
}
```
@check
Why enable appliance mode? || So both directions of a flow stay in the same AZ and a stateful appliance sees them.
@end

@concept Inter-Region peering and sharing
@plain
TGW peering links gateways in different Regions. AWS RAM shares a gateway with other accounts.
@problem
Multi-Region and multi-account networks need one coherent fabric.
@does
- Peering attachments use static routes only (no propagation across peering).
- Traffic stays on the AWS backbone and is encrypted at the physical layer.
- Share the TGW to the whole organization with RAM, so each account creates its own VPC attachment, which the owner can auto-accept.
- Keep the TGW in a dedicated network account.
@diagram flow
caption: Two Regions
nodes:
  - "TGW eu-west-1|network account|cp"
  - "Peering|static routes|info"
  - "TGW us-east-1|network account|cp"
@h Share with RAM
```bash title="Share the gateway" nocheck
aws ram create-resource-share --name tgw-share \
  --resource-arns arn:aws:ec2:eu-west-1:111122223333:transit-gateway/tgw-0abc123 \
  --principals arn:aws:organizations::111122223333:organization/o-exampleorgid
```
@end

@concept Cost, limits and troubleshooting
@plain
Costs have an hourly attachment fee and a per GB processing fee. Troubleshooting follows the route chain.
@problem
Surprise bills and silent blackholes are the common TGW incidents.
@does
- Estimate: 20 attachments x 730 hours x hourly price, plus GB x per GB price. Check the current prices.
- Overlapping CIDRs cannot be routed; plan addresses centrally.
- Debug: VPC route table to TGW, TGW association table has a route, return route exists, security groups and NACLs allow.
- Use Flow Logs on attachments and Reachability Analyzer.
@diagram flow
caption: Packet checklist
numbered: true
nodes:
  - "Source subnet route|to TGW|info"
  - "TGW table|has destination|cp"
  - "Return route|both directions|warn"
  - "Security groups|allow|ok"
@h Reachability
```bash title="Analyze a path" nocheck
aws ec2 create-network-insights-path --source eni-0aaa --destination eni-0bbb --protocol tcp --destination-port 443
```
@check
Why might traffic reach the destination but replies fail? || A missing return route in the destination VPC or TGW table.
@end
