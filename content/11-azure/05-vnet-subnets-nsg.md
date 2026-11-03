---
title: Virtual networks, subnets, NSGs and routing
minutes: 55
objectives:
  - Design a VNet address plan and subnets and compare them with an AWS VPC
  - Filter traffic with network security groups and application security groups
  - Control routing and outbound access with route tables and NAT Gateway
---
The VNet is the base of every private design in Azure. It looks like a VPC but several defaults differ.

@concept Virtual Network and address space
@plain
A **VNet** is your private network in one region, with one or more CIDR blocks, split into subnets.
@problem
Resources need private addresses, isolation and controlled paths to each other and to the internet.
@does
- **AWS equivalent**: VPC.
- **Main difference**: a VNet is regional and its subnets span all availability zones. There is no internet gateway to attach; internet access comes from public IPs, load balancers or NAT Gateway. DNS and DHCP are provided by the platform.
- Plan non-overlapping ranges across all VNets and on-premises; peering and VPN fail with overlaps. Address space can be extended later.
- Azure reserves 5 addresses per subnet (first four and last).
@diagram layers
caption: VNet structure
layers:
  - {label: "Region", nodes: ["VNet 10.10.0.0/16|one per region|env"]}
  - {label: "Subnets span all zones", nodes: ["snet-aks 10.10.0.0/20|nodes|app", "snet-data 10.10.32.0/24|private endpoints|app", "AzureBastionSubnet|10.10.33.0/26|info"]}
@h Create a VNet
```bash title="VNet and subnets" lab
az network vnet create -g rg-net -n vnet-hub --address-prefixes 10.10.0.0/16 \
  --subnet-name snet-aks --subnet-prefixes 10.10.0.0/20
az network vnet subnet create -g rg-net --vnet-name vnet-hub -n snet-data --address-prefixes 10.10.32.0/24
az network vnet subnet list -g rg-net --vnet-name vnet-hub --query '[].{n:name,p:addressPrefix}' -o table
```
@check
Does an Azure subnet belong to one availability zone? || No. It spans all zones in the region.
@end

@concept Subnets and delegation
@plain
Subnets partition the VNet. Some services demand their own subnet or a **delegation**, which hands the subnet to a specific service.
@problem
Managed services such as Application Gateway, Firewall and PostgreSQL Flexible Server inject network interfaces into your VNet and need dedicated room.
@does
- **AWS equivalent**: subnets, with services like RDS using a DB subnet group.
- **Main difference**: special names are required for some services, for example `AzureBastionSubnet`, `AzureFirewallSubnet`, `GatewaySubnet`.
- Delegation (`Microsoft.DBforPostgreSQL/flexibleServers`) allows only that service in the subnet.
- Size for growth: AKS nodes and pods with Azure CNI can consume many addresses.
@diagram cmp
caption: Subnet roles
cards:
  - {h: "Fixed name", kind: info, items: ["AzureBastionSubnet", "AzureFirewallSubnet", "GatewaySubnet"]}
  - {h: "Delegated", kind: cp, items: ["PostgreSQL Flexible Server", "App Service integration", "Container Apps environment"]}
  - {h: "Your workloads", kind: app, items: ["AKS nodes", "VMs", "Private endpoints"]}
@h Delegate a subnet
```bash title="Delegation" lab
az network vnet subnet create -g rg-net --vnet-name vnet-hub -n snet-pg \
  --address-prefixes 10.10.34.0/24 --delegations Microsoft.DBforPostgreSQL/flexibleServers
```
@end

@concept Network security groups
@plain
An **NSG** is a list of allow and deny rules with priorities, attached to a subnet or a network interface.
@problem
You need to restrict which sources and ports can reach your workloads.
@does
- **AWS equivalent**: security groups and network ACLs, combined.
- **Main difference**: NSGs are stateful like security groups but have explicit deny rules and priorities (100 to 4096, lowest first) like NACLs. Default rules allow VNet to VNet and outbound internet, and deny other inbound.
- Rules match on source, destination, port, protocol; use **service tags** such as `Internet`, `VirtualNetwork`, `Storage`, `AzureLoadBalancer` instead of IP lists.
- NSG on both subnet and NIC means traffic must pass both.
@diagram flow
caption: Inbound evaluation
nodes:
  - "Packet|from the internet|ext"
  - "Subnet NSG|priority order|cp"
  - "NIC NSG|if attached|cp"
  - "VM or node|allowed traffic only|app"
@h Rules
```bash title="NSG" lab
az network nsg create -g rg-net -n nsg-web
az network nsg rule create -g rg-net --nsg-name nsg-web -n allow-https --priority 100 \
  --direction Inbound --access Allow --protocol Tcp --destination-port-ranges 443 --source-address-prefixes Internet
az network vnet subnet update -g rg-net --vnet-name vnet-hub -n snet-aks --network-security-group nsg-web
```
@check
Which rule wins when two NSG rules match? || The one with the lower priority number.
@end

@concept Application security groups and service tags
@plain
An **ASG** is a label you put on NICs so NSG rules can refer to "the web servers" instead of IP addresses. A **service tag** is a Microsoft-maintained group of IP ranges.
@problem
IP-based rules rot as servers come and go, and public service ranges change.
@does
- **AWS equivalent**: security group referencing another security group, and managed prefix lists.
- **Main difference**: ASGs are only usable as sources or destinations inside NSG rules in the same region and VNet; they do not make a group boundary themselves.
- Service tags like `Storage.WestEurope`, `AzureContainerRegistry`, `AzureMonitor` are used in NSG and Firewall rules.
@diagram flow
caption: ASG based rule
nodes:
  - "asg-web|tag on web NICs|info"
  - "NSG rule|source asg-web to asg-db 5432|cp"
  - "asg-db|tag on database NICs|info"
  - "Result|web may reach db|ok"
@h Create ASG rule
```bash title="ASG" lab
az network asg create -g rg-net -n asg-web
az network asg create -g rg-net -n asg-db
az network nsg rule create -g rg-net --nsg-name nsg-data -n web-to-db --priority 110 --access Allow \
  --protocol Tcp --direction Inbound --source-asgs asg-web --destination-asgs asg-db --destination-port-ranges 5432
```
@end

@concept Route tables and user defined routes
@plain
Azure adds **system routes** automatically. A **route table** with **user defined routes (UDR)** overrides them, for example to send all traffic to a firewall.
@problem
Default routing sends internet traffic straight out. Security teams want inspection by a central firewall or virtual appliance.
@does
- **AWS equivalent**: VPC route tables.
- **Main difference**: route tables are optional objects you attach to subnets; without one, system routes apply (VNet, peering, internet). Next hop types include `VirtualAppliance`, `VirtualNetworkGateway`, `Internet`, `None`. Longest prefix wins; ties prefer UDR over BGP over system.
- BGP routes from VPN and ExpressRoute can be propagated into subnets.
- Look at the effective routes of a NIC when debugging.
@diagram flow
caption: Forced tunnelling to a firewall
nodes:
  - "Spoke subnet|route table attached|app"
  - "0.0.0.0/0 UDR|next hop 10.0.1.4|cp"
  - "Azure Firewall|inspects|warn"
  - "Internet|after policy|ext"
@h Create the UDR
```bash title="Route table" lab
az network route-table create -g rg-net -n rt-spoke
az network route-table route create -g rg-net --route-table-name rt-spoke -n default \
  --address-prefix 0.0.0.0/0 --next-hop-type VirtualAppliance --next-hop-ip-address 10.0.1.4
az network vnet subnet update -g rg-net --vnet-name vnet-spoke -n snet-aks --route-table rt-spoke
az network nic show-effective-route-table -g rg-lab -n vm1-nic -o table
```
@check
What does a 0.0.0.0/0 route to a virtual appliance do? || Sends all non-local traffic through the appliance, for example a firewall.
@end

@concept NAT Gateway and outbound access
@plain
**NAT Gateway** gives a subnet a fixed set of outbound public IPs and many more ports for connections.
@problem
Without explicit outbound, default outbound IPs are unpredictable and subject to SNAT port exhaustion under load.
@does
- **AWS equivalent**: NAT gateway.
- **Main difference**: you attach it to a subnet, not place it in one. It is zonal or non-zonal; for zone resilience deploy one per zone with matching subnets (check current guidance, StandardV2 adds zone-redundancy where available).
- Default outbound access for new VNets is being retired; plan explicit outbound with NAT Gateway, Firewall or a load balancer with outbound rules.
- Provides allow-listable IPs for partners.
@diagram flow
caption: Outbound path
nodes:
  - "Pod or VM|private IP|app"
  - "Subnet|NAT Gateway attached|env"
  - "NAT Gateway|public IP prefix|cp"
  - "Internet|sees fixed IPs|ext"
@h Create and attach
```bash title="NAT Gateway" lab
az network public-ip create -g rg-net -n pip-nat --sku Standard --allocation-method Static
az network nat gateway create -g rg-net -n natgw --public-ip-addresses pip-nat --idle-timeout 10
az network vnet subnet update -g rg-net --vnet-name vnet-hub -n snet-aks --nat-gateway natgw
```
:::warn
A Standard public IP is closed by default. NAT Gateway is outbound only, so inbound still needs a load balancer or other entry point.
:::
@end

@concept Public IPs and service endpoints
@plain
A **public IP** is a separately billed address object. A **service endpoint** extends your subnet identity to a PaaS service over the Azure backbone.
@problem
You need to expose or reach services without sending sensitive traffic across the open internet.
@does
- **AWS equivalent**: Elastic IP, and gateway VPC endpoints for S3.
- **Main difference**: Standard SKU IPs are static, zone-redundant by default in supported regions and secure by default. Basic SKU public IPs are retired or being retired; check current docs.
- Service endpoints (`Microsoft.Storage`, `Microsoft.Sql`) let a storage firewall allow a subnet, but the service still has a public IP. Private endpoints are the stronger option and are covered next.
@diagram cmp
caption: Reaching a PaaS service
cards:
  - {h: "Public endpoint", kind: bad, items: ["Over the internet path", "Firewall by IP", "Public IP exposed"]}
  - {h: "Service endpoint", kind: warn, items: ["Backbone route", "Allow a subnet", "Still a public address"]}
  - {h: "Private endpoint", kind: ok, items: ["Private IP in your VNet", "Public access can be off", "Needs private DNS"]}
@h Service endpoint example
```bash title="Storage firewall by subnet" lab
az network vnet subnet update -g rg-net --vnet-name vnet-hub -n snet-aks --service-endpoints Microsoft.Storage
az storage account network-rule add -g rg-shop-prod --account-name stshopprod --vnet-name vnet-hub --subnet snet-aks
```
@end

@concept Network observability
@plain
NSG flow logs, Network Watcher and Connection Monitor show what the network is doing.
@problem
"The app cannot reach the database" needs evidence, not guesses.
@does
- **AWS equivalent**: VPC Flow Logs, Reachability Analyzer.
- **Main difference**: Microsoft is moving from NSG flow logs to VNet flow logs; check the current docs for which to enable. Network Watcher tools include IP flow verify, next hop, connection troubleshoot and packet capture.
- Send logs to a storage account or Log Analytics for traffic analytics.
@diagram flow
caption: Debug order
nodes:
  - "IP flow verify|which NSG rule decides|info"
  - "Next hop|which route is used|info"
  - "Connection troubleshoot|end to end test|info"
  - "Flow logs|history of traffic|ok"
@h Test a path
```bash title="Network Watcher" lab
az network watcher test-ip-flow -g rg-lab --vm vm1 --direction Outbound --protocol TCP \
  --local 10.10.0.4:50000 --remote 10.10.32.5:5432
az network watcher show-next-hop -g rg-lab --vm vm1 --source-ip 10.10.0.4 --dest-ip 8.8.8.8
```
@check
Which tool tells you which NSG rule blocked a packet? || IP flow verify in Network Watcher.
@end
