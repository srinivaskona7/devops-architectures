---
title: Load balancing, Firewall and edge services
minutes: 55
objectives:
  - Pick between Load Balancer, Application Gateway, Front Door and Traffic Manager
  - Place Azure Firewall and WAF in a secure design
  - Wire a health probe and backend pool for a real service
---
Azure splits load balancing into four services along two axes: layer 4 or 7, and regional or global. Know which axis you need.

@concept Four load balancing services
@plain
**Load Balancer** is layer 4 regional. **Application Gateway** is layer 7 regional. **Front Door** is layer 7 global. **Traffic Manager** is DNS based global.
@problem
Choosing wrongly gives you the wrong protocol support, no WAF, or no failover across regions.
@does
- **AWS equivalent**: NLB, ALB, CloudFront with Global Accelerator, and Route 53 routing policies.
- **Main difference**: AWS has fewer, more integrated services. In Azure you often combine them, for example Front Door in front of Application Gateway in front of AKS.
- Pick by layer (TCP vs HTTP) and scope (one region vs many).
@diagram cmp
caption: Decision grid
cards:
  - {h: "Regional", kind: app, items: ["Load Balancer layer 4", "Application Gateway layer 7"]}
  - {h: "Global", kind: info, items: ["Front Door layer 7", "Traffic Manager DNS"]}
@choose Pick one
Load Balancer | any TCP or UDP service inside a region | you need URL routing or WAF
Application Gateway | HTTP routing and WAF in one region | you need global anycast edge
Front Door | global HTTP with CDN and WAF | the traffic is raw TCP
Traffic Manager | DNS failover for any internet endpoint | you need fast failover; DNS caching delays it
@end

@concept Azure Load Balancer
@plain
**Load Balancer** distributes TCP and UDP flows at layer 4 with health probes. Standard SKU is the one to use.
@problem
You need a high-throughput, low-latency front for non-HTTP or internal services such as databases, DNS or AKS Services.
@does
- **AWS equivalent**: NLB, and Gateway Load Balancer is also available in Azure for appliances.
- **Main difference**: Standard SKU is zone-redundant and closed by default until an NSG allows traffic. It can be public or internal. It provides outbound SNAT rules. Basic SKU is retired; check the current docs.
- Rules map frontend IP and port to a backend pool using a probe.
- Kubernetes `Service type LoadBalancer` on AKS creates these automatically.
@diagram flow
caption: Load balancer parts
nodes:
  - "Frontend IP|public or private|ext"
  - "Rule|port 443 to 8443|cp"
  - "Health probe|TCP or HTTP|info"
  - "Backend pool|VMs or scale set|app"
@h Create
```bash title="Standard LB" lab
az network lb create -g rg-net -n lb-app --sku Standard --vnet-name vnet-hub --subnet snet-aks \
  --frontend-ip-name fe --backend-pool-name be
az network lb probe create -g rg-net --lb-name lb-app -n hp --protocol Tcp --port 8443
az network lb rule create -g rg-net --lb-name lb-app -n r443 --protocol Tcp --frontend-port 443 \
  --backend-port 8443 --frontend-ip-name fe --backend-pool-name be --probe-name hp
```
@check
What does a Standard Load Balancer do with inbound traffic until an NSG allows it? || Blocks it. Standard is secure by default.
@end

@concept Application Gateway and WAF
@plain
**Application Gateway** is a regional layer 7 load balancer with path and host routing, TLS termination, autoscaling and an integrated Web Application Firewall.
@problem
You need HTTP routing and protection from common web attacks inside a VNet.
@does
- **AWS equivalent**: ALB with AWS WAF.
- **Main difference**: lives in its own dedicated subnet. Use the v2 SKU (`Standard_v2` or `WAF_v2`) only; v1 is retired. WAF policies are separate objects with managed rule sets (OWASP CRS) and custom rules.
- Components: frontend IP, listeners, rules, backend pools, HTTP settings and probes.
- On AKS it can act as ingress (AGIC) or, preferably, the newer Application Gateway for Containers; see the AKS pages.
@diagram flow
caption: Application Gateway request path
nodes:
  - "Client|HTTPS|ext"
  - "Listener and WAF|OWASP rules|cp"
  - "Routing rule|path and host|info"
  - "Backend pool|VMs, AKS, App Service|app"
@h Create a WAF v2 gateway
```bash title="Application Gateway" lab
az network public-ip create -g rg-net -n pip-agw --sku Standard
az network application-gateway create -g rg-net -n agw-shop --sku WAF_v2 --capacity 2 \
  --vnet-name vnet-hub --subnet snet-agw --public-ip-address pip-agw \
  --priority 100 --http-settings-port 8080 --frontend-port 443
```
:::note
Check the current CLI help; creating with HTTPS needs a certificate argument. Many teams create gateways with Bicep or Terraform instead.
:::
@end

@concept Front Door
@plain
**Azure Front Door** is a global entry point on Microsoft's edge network: HTTP/2 and HTTP/3, caching, WAF, TLS and routing to origins in any region.
@problem
Users worldwide need a fast, protected front end with automatic failover between regions.
@does
- **AWS equivalent**: CloudFront with AWS WAF and Global Accelerator features.
- **Main difference**: one service combines CDN, global load balancing and WAF. Use Standard or Premium; Premium adds Private Link origins and managed rule sets. Classic is being retired.
- Concepts: profile, endpoint, origin group, origin, route, rule set, security policy.
- To lock the origin down, allow only the `AzureFrontDoor.Backend` service tag and check the `X-Azure-FDID` header.
@diagram flow
caption: Global flow
nodes:
  - "User|nearest edge|ext"
  - "Front Door|WAF, cache, TLS|cp"
  - "Origin group|health probed|info"
  - "Origins|region A and B|app"
@h Create profile and endpoint
```bash title="Front Door" lab
az afd profile create -g rg-net --profile-name fd-shop --sku Standard_AzureFrontDoor
az afd endpoint create -g rg-net --profile-name fd-shop --endpoint-name shop --enabled-state Enabled
az afd origin-group create -g rg-net --profile-name fd-shop --origin-group-name og-web \
  --probe-request-type GET --probe-protocol Https --probe-path /healthz --probe-interval-in-seconds 30 \
  --sample-size 4 --successful-samples-required 3
```
@check
Which Front Door tier supports Private Link origins? || Premium.
@end

@concept Traffic Manager
@plain
**Traffic Manager** answers DNS queries with the best endpoint according to a routing method. It never sees your traffic.
@problem
You want simple multi-region failover or weighted rollout for any internet-facing endpoint, not only HTTP.
@does
- **AWS equivalent**: Route 53 routing policies with health checks.
- **Main difference**: it is only a DNS responder, so failover speed depends on TTL and client caching. Methods: Priority, Weighted, Performance, Geographic, Multivalue, Subnet.
- Probes check endpoints over HTTP, HTTPS or TCP.
- Prefer Front Door for HTTP workloads where fast failover matters.
@diagram seq
caption: DNS based routing
actors: ["Client|resolver|ext", "Traffic Manager|priority profile|cp", "West Europe|primary|app", "North Europe|secondary|app"]
steps:
  - "0>1: shop.trafficmanager.net | req"
  - "1>0: IP of primary if healthy | resp"
  - "0>2: HTTPS to primary | tls"
  - "note 1..1: probes mark primary down"
  - "1>0: IP of secondary | resp"
  - "0>3: HTTPS to secondary | tls"
@h Priority profile
```bash title="Traffic Manager" lab
az network traffic-manager profile create -g rg-net -n tm-shop --routing-method Priority --unique-dns-name shop-tm-example \
  --protocol HTTPS --port 443 --path /healthz
az network traffic-manager endpoint create -g rg-net --profile-name tm-shop -n weu --type externalEndpoints \
  --target shop-weu.example.com --priority 1
```
@end

@concept Azure Firewall
@plain
**Azure Firewall** is a managed, stateful network and application firewall with FQDN rules, threat intelligence and optional TLS inspection.
@problem
Central egress control, east-west filtering and logging that NSGs, which only know IPs and ports, cannot provide.
@does
- **AWS equivalent**: AWS Network Firewall (with Gateway Load Balancer for third-party appliances).
- **Main difference**: SKUs Basic, Standard and Premium; managed through Firewall Policy. Lives in `AzureFirewallSubnet` and is usually the next hop in spoke UDRs. Billed per deployment hour plus data processed, so it is a notable cost in small environments.
- Rule collections: DNAT, network, application (FQDN and FQDN tags like `AzureKubernetesService`).
- Logs go to Log Analytics.
@diagram flow
caption: Egress through the firewall
nodes:
  - "Spoke workloads|UDR to firewall|app"
  - "Azure Firewall|policy rules|warn"
  - "Allowed FQDNs|registry, updates|ok"
  - "Everything else|denied and logged|bad"
@h Create firewall and policy
```bash title="Firewall" lab
az network firewall policy create -g rg-net -n fwp-hub --sku Standard
az network firewall policy rule-collection-group create -g rg-net --policy-name fwp-hub -n rcg-egress --priority 200
az network firewall policy rule-collection-group collection add-filter-collection -g rg-net --policy-name fwp-hub \
  --rcg-name rcg-egress --name allow-mcr --collection-priority 200 --action Allow --rule-name mcr --rule-type ApplicationRule \
  --source-addresses 10.10.0.0/16 --protocols Https=443 --target-fqdns mcr.microsoft.com
```
:::tip
Check the current AKS egress documentation for the required outbound FQDNs and service tags when forcing AKS traffic through a firewall.
:::
@check
Why is Azure Firewall more capable than an NSG? || It filters on FQDNs, threat intelligence and application layer, and it is central and stateful with policy inheritance.
@end

@concept DDoS protection and WAF placement
@plain
Azure gives basic DDoS protection to every public IP by default. DDoS Network Protection and IP Protection add tuning, telemetry and cost protection. WAF can be on Front Door or Application Gateway.
@problem
Public endpoints will be scanned and attacked, and the layers must be placed without duplicating cost.
@does
- **AWS equivalent**: AWS Shield Standard and Advanced, AWS WAF.
- **Main difference**: DDoS protection plans attach to VNets (Network Protection) or single public IPs (IP Protection); check current pricing.
- Typical HTTP design: Front Door with WAF at the edge, private origin via Private Link, optional Application Gateway WAF only where you need regional rules.
- Keep one primary WAF layer and avoid double blocking confusion.
@diagram layers
caption: Defence layers
layers:
  - {label: "Edge", nodes: ["Front Door WAF|bots, OWASP, rate limit|cp"]}
  - {label: "Region", nodes: ["Application Gateway WAF|optional second layer|info", "Azure Firewall|egress and east west|warn"]}
  - {label: "Network", nodes: ["DDoS protection|on public IPs|ok", "NSGs|subnet filters|plain"]}
@h Check DDoS and WAF state
```bash title="Inspect" lab
az network ddos-protection list -o table
az network front-door waf-policy list -g rg-net --query '[].{n:name,mode:policySettings.mode}' -o table
```
@end
