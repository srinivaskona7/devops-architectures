---
title: Private Link, peering, Virtual WAN and DNS
minutes: 55
objectives:
  - Reach PaaS services privately with private endpoints and matching private DNS zones
  - Connect VNets with peering, hub and spoke and Virtual WAN
  - Operate Azure DNS and Private DNS including a DNS Private Resolver
---
Private connectivity is where most Azure outages begin: the endpoint exists, but DNS still points to the public address. Understand the pairs.

@concept Private Link and private endpoints
@plain
A **private endpoint** is a network interface with a private IP in your subnet that maps to one specific instance of a PaaS service, such as a storage account or database.
@problem
PaaS services default to public addresses. You want them reachable only from inside your network.
@does
- **AWS equivalent**: interface VPC endpoints (PrivateLink).
- **Main difference**: one private endpoint is per resource and per sub-resource (`blob`, `file`, `postgresqlServer`). Private Link also covers your own services behind a Standard Load Balancer. Usually you then disable public network access on the service.
- The endpoint is a separate billed resource; traffic through it is also charged by volume (check pricing).
- Approval can be automatic or manual across tenants.
@diagram flow
caption: Private path to storage
nodes:
  - "Pod or VM|in the VNet|app"
  - "Private endpoint|10.10.32.5|cp"
  - "Private Link|Microsoft backbone|info"
  - "Storage account|public access off|ok"
@h Create one
```bash title="Private endpoint for blob" lab
SA=$(az storage account show -g rg-shop-prod -n stshopprod --query id -o tsv)
az network private-endpoint create -g rg-net -n pe-st-blob --vnet-name vnet-hub --subnet snet-data \
  --private-connection-resource-id "$SA" --group-id blob --connection-name st-blob
az storage account update -g rg-shop-prod -n stshopprod --public-network-access Disabled
```
@check
Does a private endpoint alone make clients use the private IP? || No. DNS must resolve the service name to the private IP.
@end

@concept Private DNS zones for private endpoints
@plain
A **private DNS zone** such as `privatelink.blob.core.windows.net` holds the record that points the service name to the private endpoint IP, linked to the VNets that need it.
@problem
Without it, `stshopprod.blob.core.windows.net` still resolves to a public address and requests fail once public access is off.
@does
- **AWS equivalent**: private hosted zone, or the private DNS that interface endpoints enable automatically.
- **Main difference**: in Azure it is a separate step you must wire. Create the zone, link it to the VNet, and add a DNS zone group to the endpoint so records update automatically.
- Each service has its own zone name (blob, file, `privatelink.postgres.database.azure.com`, vault, azurecr); check the list in the docs.
- Central hub design: keep zones in one subscription and link to every VNet.
@diagram seq
caption: Name resolution with private DNS
actors: ["Client|pod or VM|app", "Azure DNS|168.63.129.16|cp", "Private zone|privatelink record|info", "Storage|private endpoint|ok"]
steps:
  - "0>1: stshopprod.blob.core.windows.net | req"
  - "1>2: CNAME to privatelink name | req"
  - "2>1: A record 10.10.32.5 | resp"
  - "1>0: private IP | resp"
  - "0>3: connect | tls"
@h Zone and link
```bash title="Private DNS" lab
az network private-dns zone create -g rg-net -n privatelink.blob.core.windows.net
az network private-dns link vnet create -g rg-net -z privatelink.blob.core.windows.net -n link-hub \
  --virtual-network vnet-hub --registration-enabled false
az network private-endpoint dns-zone-group create -g rg-net --endpoint-name pe-st-blob -n default \
  --private-dns-zone privatelink.blob.core.windows.net --zone-name blob
nslookup stshopprod.blob.core.windows.net
```
:::tip
Assign the built-in policy "Configure private endpoints to use private DNS zones" so records are created automatically.
:::
@end

@concept VNet peering
@plain
**Peering** connects two VNets so they talk over private IPs on the Microsoft backbone.
@problem
Workloads in different VNets, regions or subscriptions need low-latency private connectivity.
@does
- **AWS equivalent**: VPC peering.
- **Main difference**: peering is configured from both sides (two links). Like AWS it is non-transitive, but you can enable **gateway transit** and **use remote gateways** to share a VPN or ExpressRoute gateway, and route through a hub firewall with UDRs.
- Works across regions (global peering) and subscriptions, and even tenants with rights.
- Address spaces must not overlap.
@diagram flow
caption: Hub and spoke with peering
nodes:
  - "Spoke A|shop workloads|app"
  - "Hub VNet|firewall, DNS, gateway|cp"
  - "Spoke B|data platform|app"
  - "On premises|VPN or ExpressRoute|ext"
@h Peer two networks
```bash title="Peering" lab
HUB=$(az network vnet show -g rg-net -n vnet-hub --query id -o tsv)
SPOKE=$(az network vnet show -g rg-shop-prod -n vnet-shop --query id -o tsv)
az network vnet peering create -g rg-net -n hub-to-shop --vnet-name vnet-hub --remote-vnet "$SPOKE" --allow-vnet-access
az network vnet peering create -g rg-shop-prod -n shop-to-hub --vnet-name vnet-shop --remote-vnet "$HUB" --allow-vnet-access
```
@check
Is peering transitive? || No. Spokes talk through a hub only if routing, such as a firewall UDR, is set up.
@end

@concept Virtual WAN
@plain
**Virtual WAN** is a managed hub network service that combines VPN, ExpressRoute, VNet connections and routing in Microsoft-run hubs.
@problem
Large estates with many branches and VNets get unmanageable with hand-built hubs and UDRs.
@does
- **AWS equivalent**: Transit Gateway plus Cloud WAN.
- **Main difference**: hubs are managed, support any-to-any routing by default, and can host a secured hub with Azure Firewall. Costs more than DIY peering for small estates; custom hub VNets give more control.
- SKUs Basic and Standard; check the current docs.
- Route tables and propagation determine which connections see each other.
@diagram layers
caption: Virtual WAN
layers:
  - {label: "Managed hub per region", nodes: ["vWAN hub|router, VPN, ExpressRoute|cp", "Secured hub|Firewall Manager|warn"]}
  - {label: "Connections", nodes: ["VNet spokes|connections|app", "Branches|site to site VPN|ext", "Users|point to site|ext"]}
@h Create the WAN
```bash title="Virtual WAN" lab
az network vwan create -g rg-net -n vwan-main --type Standard -l westeurope
az network vhub create -g rg-net -n hub-weu --vwan vwan-main --address-prefix 10.200.0.0/23 -l westeurope
az network vhub connection create -g rg-net --vhub-name hub-weu -n conn-shop --remote-vnet "$SPOKE"
```
@choose Hub model
Hub VNet with peering | small estate, you want full control and low cost | dozens of branches need managed routing
Virtual WAN | many branches and regions, any-to-any needs | you need custom NVAs in unusual topologies
@end

@concept Azure DNS public zones
@plain
**Azure DNS** hosts your public DNS zones on Microsoft's name servers.
@problem
You need reliable authoritative DNS managed with the same tools and RBAC as the rest of Azure.
@does
- **AWS equivalent**: Route 53 public hosted zones.
- **Main difference**: Azure DNS has no health-checked routing or domain registration; use Traffic Manager or Front Door for steering. Alias records point to Azure resources such as public IPs, Front Door and Traffic Manager.
- Delegate by setting the registrar NS records to the four Azure name servers.
- Supports DNSSEC; check the current status for your region.
@diagram flow
caption: Delegation
nodes:
  - "Registrar|NS records|ext"
  - "Azure DNS zone|example.com|cp"
  - "Alias A record|www to Front Door|info"
  - "Client|resolves www|plain"
@h Zone and records
```bash title="Azure DNS" lab
az network dns zone create -g rg-net -n example.com
az network dns zone show -g rg-net -n example.com --query nameServers -o tsv
az network dns record-set cname set-record -g rg-net -z example.com -n www --cname shop.azurefd.net
```
@end

@concept DNS Private Resolver and hybrid DNS
@plain
**DNS Private Resolver** is a managed service with inbound and outbound endpoints and forwarding rules, so on-premises and Azure can resolve each other's names.
@problem
Private DNS zones are only visible inside linked VNets. On-premises clients cannot query them, and Azure cannot reach corporate names without a DNS VM.
@does
- **AWS equivalent**: Route 53 Resolver inbound and outbound endpoints.
- **Main difference**: the built-in resolver at 168.63.129.16 is only reachable from inside Azure. The Private Resolver adds an inbound IP on a delegated subnet for on-premises forwarders, and an outbound endpoint with a ruleset for forwarding domains to corporate DNS.
- Needs dedicated subnets for inbound and outbound endpoints.
@diagram flow
caption: Hybrid resolution
nodes:
  - "On premises DNS|conditional forward|ext"
  - "Inbound endpoint|private IP in VNet|cp"
  - "Private DNS zones|privatelink records|info"
  - "Outbound ruleset|forward corp.local|cp"
@h Create a resolver
```bash title="Private Resolver" lab
az dns-resolver create -g rg-net -n dnspr-hub --id "$(az network vnet show -g rg-net -n vnet-hub --query id -o tsv)" -l westeurope
```
:::note
The `dns-resolver` commands may need the `dns-resolver` CLI extension. Check `az extension list-available`.
:::
@check
Why can an on-premises machine not resolve a privatelink zone directly? || The zone is only visible from linked VNets, so it must query an inbound resolver endpoint.
@end

@concept Private Link for your own service
@plain
You can publish a service behind a Standard Load Balancer as a **Private Link service**, and other VNets or tenants consume it through their own private endpoint.
@problem
Sharing an internal API with another team or customer without peering whole networks, which would expose everything and require non-overlapping address ranges.
@does
- **AWS equivalent**: VPC endpoint service (PrivateLink provider side).
- **Main difference**: the provider uses NAT IPs from a subnet, so overlapping address spaces are fine. The consumer creates a private endpoint using the alias or resource ID. Approval can be manual or auto for named subscriptions.
- One direction only: the consumer connects to the provider.
- On AKS, an internal Service can be exposed this way with annotations; check the current cloud provider docs.
@diagram flow
caption: Provider and consumer
nodes:
  - "Consumer VNet|private endpoint|app"
  - "Private Link|one way connection|info"
  - "Provider Standard LB|Private Link service|cp"
  - "Backend|your API pods or VMs|app"
@h Publish a service
```bash title="Private Link service" lab
az network private-link-service create -g rg-net -n pls-shop-api --vnet-name vnet-hub --subnet snet-pls \
  --lb-name lb-app --lb-frontend-ip-configs fe --location westeurope
az network private-link-service show -g rg-net -n pls-shop-api --query alias -o tsv
```
@check
Why do overlapping address spaces work with Private Link but not with peering? || Traffic is NATed into the provider subnet and reached through a private endpoint IP in the consumer VNet.
@end
