---
title: Core services 21 to 25, connectivity and protection
minutes: 60
objectives:
  - Compare private endpoints, hybrid links, hubs, NAT and web protection
  - State when to choose each service
  - List the limits to verify in the current docs
---
These services connect networks privately and protect the edge. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
Private access, hybrid links, hubs, egress and edge filtering. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Connectivity map
layers:
  - {label: "Services on this page", nodes: ["Private connectivity to services|PrivateLink|app", "Hybrid connectivity|Direct Connect or Site-to-Site VPN|info", "Hub networking|Transit Gateway|env", "NAT egress|NAT Gateway|ok", "Web firewall and DDoS protection|WAF and Shield|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 21 | Private connectivity to services | PrivateLink | Private Link | Private Service Connect |
| 22 | Hybrid connectivity | Direct Connect or Site-to-Site VPN | ExpressRoute or VPN Gateway | Cloud Interconnect or Cloud VPN |
| 23 | Hub networking | Transit Gateway | Virtual WAN or hub VNet | Network Connectivity Center |
| 24 | NAT egress | NAT Gateway | NAT Gateway | Cloud NAT |
| 25 | Web firewall and DDoS protection | WAF and Shield | Web Application Firewall and DDoS Protection | Cloud Armor |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 21. Private connectivity to services
@plain
A way to reach a service through a private address inside your network so traffic never crosses the public internet.
@problem
Public endpoints for storage, databases or partner services widen the attack surface and complicate firewall rules.
@does
- **Names**: AWS PrivateLink; Azure Private Link; GCP Private Service Connect.
- **What it is**: Creates private endpoints that map a service to an IP in your subnet, and can publish your own service to consumers.
- **Choose it when**: Private access to storage and databases; Exposing a service to other accounts; Compliance requiring no public path.
- **Check in the current docs**: DNS must resolve the service name to the private address; Endpoints are billed per hour and per data processed; Overlapping address ranges are tolerated, but check the current docs per product.
@diagram cmp
caption: Private connectivity to services on the three clouds
cards:
  - {h: "PrivateLink", kind: warn, items: ["Interface and gateway endpoints, endpoint services"]}
  - {h: "Private Link", kind: info, items: ["Private endpoints and Private Link services"]}
  - {h: "Private Service Connect", kind: ok, items: ["Endpoints and published service attachments"]}
@h Example
An application reaches a storage account at a 10.20.3.x address, and public access to the account is disabled.
@h CLI on each cloud
```bash title="AWS CLI, Private connectivity to services" nocheck
aws ec2 create-vpc-endpoint --vpc-id vpc-0abc1234 --service-name com.amazonaws.eu-west-1.secretsmanager --vpc-endpoint-type Interface --subnet-ids subnet-aaa
```
```bash title="Azure CLI, Private connectivity to services" nocheck
az network private-endpoint create --resource-group rg-demo --name pe-storage --vnet-name vnet-prod --subnet data --private-connection-resource-id /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-demo/providers/Microsoft.Storage/storageAccounts/stdemo123 --group-id blob --connection-name pe-conn
```
```bash title="gcloud, Private connectivity to services" nocheck
gcloud compute addresses create psc-ip --region=europe-west1 --subnet=app
gcloud compute forwarding-rules create psc-endpoint --region=europe-west1 --network=vpc-prod --address=psc-ip --target-service-attachment=projects/producer/regions/europe-west1/serviceAttachments/svc
```
@check
What commonly breaks a private endpoint? || DNS still resolving to the public address.
@end

@concept 22. Hybrid connectivity
@plain
Links between your office or data center and the cloud network, either over encrypted internet tunnels or a dedicated circuit.
@problem
Moving to the cloud rarely happens at once, so on-premises systems must talk to cloud systems securely and predictably.
@does
- **Names**: AWS Direct Connect or Site-to-Site VPN; Azure ExpressRoute or VPN Gateway; GCP Cloud Interconnect or Cloud VPN.
- **What it is**: VPN gives quick encrypted tunnels over the internet. Dedicated circuits give steadier latency and higher bandwidth through a provider or colocation.
- **Choose it when**: VPN for fast start and backup; Dedicated link for steady high volume; Regulated data needing private paths.
- **Check in the current docs**: Dedicated circuits take weeks to order, so plan early; Dedicated circuits are not encrypted by default, so add encryption if required; Use two links for resilience, and check the current docs for SLA conditions.
@diagram cmp
caption: Hybrid connectivity on the three clouds
cards:
  - {h: "Direct Connect or Site-to-Site VPN", kind: warn, items: ["Direct Connect with virtual interfaces, VPN connections"]}
  - {h: "ExpressRoute or VPN Gateway", kind: info, items: ["ExpressRoute circuits, VPN Gateway"]}
  - {h: "Cloud Interconnect or Cloud VPN", kind: ok, items: ["Dedicated or Partner Interconnect, HA VPN"]}
@h Example
A bank orders two dedicated circuits at different sites and keeps a VPN as the backup path.
@h CLI on each cloud
```bash title="AWS CLI, Hybrid connectivity" nocheck
aws ec2 create-vpn-connection --type ipsec.1 --customer-gateway-id cgw-0abc1234 --vpn-gateway-id vgw-0abc1234
```
```bash title="Azure CLI, Hybrid connectivity" nocheck
az network vnet-gateway create --resource-group rg-demo --name vpngw --vnet vnet-prod --public-ip-address vpngw-ip --gateway-type Vpn --vpn-type RouteBased --sku VpnGw1
```
```bash title="gcloud, Hybrid connectivity" nocheck
gcloud compute vpn-gateways create ha-vpn --network=vpc-prod --region=europe-west1
```
@check
Why keep a VPN next to a dedicated circuit? || It is a backup path if the circuit fails.
@end

@concept 23. Hub networking
@plain
A central router that connects many networks, so each one links once to the hub instead of to every other.
@problem
Peering every network with every other grows quadratically and is hard to manage and inspect.
@does
- **Names**: AWS Transit Gateway; Azure Virtual WAN or hub VNet; GCP Network Connectivity Center.
- **What it is**: Provides central routing, shared services and a place to insert firewalls, with attachments for networks and on-premises links.
- **Choose it when**: Many VPCs or VNets; Shared egress and inspection; Hybrid connectivity at scale.
- **Check in the current docs**: Hub data processing charges apply, so check the current docs; Route tables and propagation need careful design; Hub becomes a critical shared dependency.
@diagram cmp
caption: Hub networking on the three clouds
cards:
  - {h: "Transit Gateway", kind: warn, items: ["Attachments, route tables, peering between gateways"]}
  - {h: "Virtual WAN or hub VNet", kind: info, items: ["Virtual WAN hubs or hub-and-spoke with peering"]}
  - {h: "Network Connectivity Center", kind: ok, items: ["Hubs and spokes, VPC spokes"]}
@h Example
Twenty spoke networks attach to one hub, so the company needs 20 attachments, not 190 peerings. Pairs are 20 times 19 divided by 2.
@h CLI on each cloud
```bash title="AWS CLI, Hub networking" nocheck
aws ec2 create-transit-gateway --description hub
aws ec2 create-transit-gateway-vpc-attachment --transit-gateway-id tgw-0abc1234 --vpc-id vpc-0abc1234 --subnet-ids subnet-aaa
```
```bash title="Azure CLI, Hub networking" nocheck
az network vwan create --resource-group rg-demo --name demo-vwan --type Standard
az network vhub create --resource-group rg-demo --name hub1 --vwan demo-vwan --address-prefix 10.100.0.0/24 --location westeurope
```
```bash title="gcloud, Hub networking" nocheck
gcloud network-connectivity hubs create demo-hub
```
@check
How many peerings fully connect 20 networks? || 20 x 19 / 2 = 190.
@end

@concept 24. NAT egress
@plain
A managed service that lets private machines start outbound internet connections without being reachable from outside.
@problem
Private servers still need to fetch updates and call external APIs.
@does
- **Names**: AWS NAT Gateway; Azure NAT Gateway; GCP Cloud NAT.
- **What it is**: Translates private source addresses to shared public addresses and tracks connections.
- **Choose it when**: Private subnets needing outbound access; Fixed public IPs for partner allow-lists; Replacing self-managed NAT instances.
- **Check in the current docs**: Per-hour and per-gigabyte charges can be large, so use private endpoints for cloud services; Port exhaustion limits connections to one destination; AWS NAT is zonal, so use one per zone for resilience.
@diagram cmp
caption: NAT egress on the three clouds
cards:
  - {h: "NAT Gateway", kind: warn, items: ["NAT gateway per zone with Elastic IP"]}
  - {h: "NAT Gateway", kind: info, items: ["NAT Gateway attached to subnets"]}
  - {h: "Cloud NAT", kind: ok, items: ["Cloud NAT on a router"]}
@h Example
A private subnet uses one NAT address in the partner allow-list, and storage traffic uses private endpoints to avoid NAT data charges.
@h CLI on each cloud
```bash title="AWS CLI, NAT egress" nocheck
aws ec2 create-nat-gateway --subnet-id subnet-public1 --allocation-id eipalloc-0abc1234
```
```bash title="Azure CLI, NAT egress" nocheck
az network nat gateway create --resource-group rg-demo --name natgw --public-ip-addresses nat-ip --idle-timeout 10
```
```bash title="gcloud, NAT egress" nocheck
gcloud compute routers create nat-router --network=vpc-prod --region=europe-west1
gcloud compute routers nats create nat1 --router=nat-router --region=europe-west1 --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges
```
@check
How reduce NAT data charges? || Send cloud service traffic through private endpoints.
@end

@concept 25. Web firewall and DDoS protection
@plain
Edge protection that filters malicious web requests and absorbs floods of traffic.
@problem
Public apps face injection attempts, bots and volumetric attacks that application code alone cannot absorb.
@does
- **Names**: AWS WAF and Shield; Azure Web Application Firewall and DDoS Protection; GCP Cloud Armor.
- **What it is**: Applies managed and custom rules, rate limits and IP lists on a load balancer or CDN, plus network-level DDoS defence.
- **Choose it when**: Any internet-facing web app; Rate limiting and bot control; Compliance requirements.
- **Check in the current docs**: Start rules in count or preview mode to avoid blocking real users; Tiers of DDoS protection differ and may cost extra, so check the current docs; Rules attach to specific resource types.
@diagram cmp
caption: Web firewall and DDoS protection on the three clouds
cards:
  - {h: "WAF and Shield", kind: warn, items: ["WAF web ACLs, Shield Standard and Advanced"]}
  - {h: "Web Application Firewall and DDoS Protection", kind: info, items: ["WAF policies on Front Door or Application Gateway, DDoS Protection"]}
  - {h: "Cloud Armor", kind: ok, items: ["Security policies, preconfigured rules"]}
@h Example
A team runs managed rules in count mode for a week, reviews false positives, then switches to block.
@h CLI on each cloud
```bash title="AWS CLI, Web firewall and DDoS protection" nocheck
aws wafv2 list-web-acls --scope REGIONAL --region eu-west-1
```
```bash title="Azure CLI, Web firewall and DDoS protection" nocheck
az network front-door waf-policy create --resource-group rg-demo --name demowaf --sku Premium_AzureFrontDoor
```
```bash title="gcloud, Web firewall and DDoS protection" nocheck
gcloud compute security-policies create demo-policy --description=demo
```
@check
Why start in count mode? || To find false positives before blocking.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Private endpoints without matching DNS.
- A single hybrid link with no backup.
- NAT charges from cloud service traffic.
- Always confirm limits, prices and regional availability in the current documentation before committing.
@diagram flow
caption: A safe habit before adopting any service
nodes:
  - "Define need|workload, size, latency|plain"
  - "Map services|three cloud names|info"
  - "Check docs|limits, price, regions|warn"
  - "Prototype|measure on real data|app"
  - "Decide|record in an ADR|ok"
@h Habit as a checklist
```yaml title="service-evaluation.yaml" nocheck
service: Private connectivity to services
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

