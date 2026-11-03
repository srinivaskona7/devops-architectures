---
title: Core services 16 to 20, network and edge
minutes: 60
objectives:
  - Compare virtual networks, load balancers, DNS and CDN
  - State when to choose each service
  - List the limits to verify in the current docs
---
These services carry user traffic from the internet to your workloads. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
A request passes DNS, CDN, load balancer and then the network. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Traffic path
layers:
  - {label: "Services on this page", nodes: ["Virtual network|VPC|app", "Layer-7 load balancer|Application Load Balancer|info", "Layer-4 load balancer|Network Load Balancer|env", "DNS|Route 53|ok", "CDN|CloudFront|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 16 | Virtual network | VPC | VNet | VPC |
| 17 | Layer-7 load balancer | Application Load Balancer | Application Gateway | External Application Load Balancer |
| 18 | Layer-4 load balancer | Network Load Balancer | Load Balancer | Network Load Balancer |
| 19 | DNS | Route 53 | Azure DNS | Cloud DNS |
| 20 | CDN | CloudFront | Front Door or Azure CDN | Cloud CDN |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 16. Virtual network
@plain
A private network in the cloud where you place your resources, choose address ranges and control what can talk to what.
@problem
Without isolation, resources would sit on a shared flat network with no control over exposure.
@does
- **Names**: AWS VPC; Azure VNet; GCP VPC.
- **What it is**: Defines address space, subnets, routing and filtering rules, and connects to other networks.
- **Choose it when**: Every workload, as the base layer; Separating environments and tiers; Hybrid and peering designs.
- **Check in the current docs**: Address ranges cannot easily overlap if you later peer or connect networks; GCP VPCs are global while AWS VPCs and Azure VNets are regional; Subnet scope differs, with zonal subnets on AWS and regional ones on Azure and GCP.
@diagram cmp
caption: Virtual network on the three clouds
cards:
  - {h: "VPC", kind: warn, items: ["Subnets, route tables, security groups, NACLs"]}
  - {h: "VNet", kind: info, items: ["Subnets, NSGs, route tables"]}
  - {h: "VPC", kind: ok, items: ["Global VPC, regional subnets, firewall rules"]}
@h Example
A production network uses 10.20.0.0/16 with public, app and data subnets in three zones.
@h CLI on each cloud
```bash title="AWS CLI, Virtual network" nocheck
aws ec2 create-vpc --cidr-block 10.20.0.0/16
aws ec2 create-subnet --vpc-id vpc-0abc1234 --cidr-block 10.20.1.0/24 --availability-zone eu-west-1a
```
```bash title="Azure CLI, Virtual network" nocheck
az network vnet create --resource-group rg-demo --name vnet-prod --address-prefixes 10.20.0.0/16 --subnet-name app --subnet-prefixes 10.20.1.0/24
```
```bash title="gcloud, Virtual network" nocheck
gcloud compute networks create vpc-prod --subnet-mode=custom
gcloud compute networks subnets create app --network=vpc-prod --region=europe-west1 --range=10.20.1.0/24
```
@check
Which cloud has a global VPC by default? || Google Cloud.
@end

@concept 17. Layer-7 load balancer
@plain
A load balancer that reads HTTP requests and routes by host name, path and headers.
@problem
A plain network balancer cannot send /api and /images to different backends or terminate web features such as redirects.
@does
- **Names**: AWS Application Load Balancer; Azure Application Gateway; GCP External Application Load Balancer.
- **What it is**: Terminates TLS, routes by rules to backend pools, checks health, and integrates with a web firewall.
- **Choose it when**: HTTP and HTTPS applications; Path or host based routing; TLS termination and WAF attachment.
- **Check in the current docs**: Idle and request timeouts have defaults you may need to change; Scaling and billing units differ, so check the current docs; Azure Front Door is the global option while Application Gateway is regional.
@diagram cmp
caption: Layer-7 load balancer on the three clouds
cards:
  - {h: "Application Load Balancer", kind: warn, items: ["Listeners, rules, target groups"]}
  - {h: "Application Gateway", kind: info, items: ["Listeners, rules, backend pools"]}
  - {h: "External Application Load Balancer", kind: ok, items: ["URL maps, backend services, forwarding rules"]}
@h Example
api.example.com/orders goes to the orders pool and /users to the users pool, with HTTP redirected to HTTPS.
@h CLI on each cloud
```bash title="AWS CLI, Layer-7 load balancer" nocheck
aws elbv2 create-load-balancer --name web --type application --subnets subnet-aaa subnet-bbb --security-groups sg-0abc1234
```
```bash title="Azure CLI, Layer-7 load balancer" nocheck
az network application-gateway create --resource-group rg-demo --name appgw --sku Standard_v2 --capacity 2 --vnet-name vnet-prod --subnet agw --public-ip-address agw-ip
```
```bash title="gcloud, Layer-7 load balancer" nocheck
gcloud compute url-maps create web-map --default-service=web-backend
gcloud compute target-http-proxies create web-proxy --url-map=web-map
```
@check
What can a layer-7 balancer do that layer 4 cannot? || Route by host, path and headers.
@end

@concept 18. Layer-4 load balancer
@plain
A fast load balancer that forwards TCP or UDP connections without reading the application data.
@problem
Non-HTTP protocols, static IPs and very high connection rates do not fit a web-aware balancer.
@does
- **Names**: AWS Network Load Balancer; Azure Load Balancer; GCP Network Load Balancer.
- **What it is**: Distributes connections by flow, preserves client addresses in many modes, and supports health probes.
- **Choose it when**: Databases, game, MQTT and custom TCP or UDP; Static IP requirement; Extreme throughput and low latency.
- **Check in the current docs**: No path routing; Cross-zone behaviour and defaults differ, so check the current docs; Health probe sources must be allowed in firewalls.
@diagram cmp
caption: Layer-4 load balancer on the three clouds
cards:
  - {h: "Network Load Balancer", kind: warn, items: ["NLB with static IP per zone, TLS listener"]}
  - {h: "Load Balancer", kind: info, items: ["Standard Load Balancer, zone redundant"]}
  - {h: "Network Load Balancer", kind: ok, items: ["Passthrough and proxy network load balancers"]}
@h Example
A TCP service for IoT devices sits behind a network balancer with one static address per zone.
@h CLI on each cloud
```bash title="AWS CLI, Layer-4 load balancer" nocheck
aws elbv2 create-load-balancer --name tcp-lb --type network --subnets subnet-aaa subnet-bbb
```
```bash title="Azure CLI, Layer-4 load balancer" nocheck
az network lb create --resource-group rg-demo --name tcp-lb --sku Standard --vnet-name vnet-prod --subnet app --frontend-ip-name fe --backend-pool-name be
```
```bash title="gcloud, Layer-4 load balancer" nocheck
gcloud compute forwarding-rules create tcp-fr --region=europe-west1 --ports=443 --backend-service=tcp-backend --load-balancing-scheme=EXTERNAL
```
@check
When choose layer 4 over layer 7? || For non-HTTP protocols, static IPs or the highest throughput.
@end

@concept 19. DNS
@plain
The service that turns names such as shop.example.com into IP addresses and other records.
@problem
Users and services need stable names while IP addresses change.
@does
- **Names**: AWS Route 53; Azure Azure DNS; GCP Cloud DNS.
- **What it is**: Hosts zones, supports alias or routing records, health-based failover and private zones.
- **Choose it when**: Public domains and private internal names; Failover and weighted routing; Service discovery in a VPC.
- **Check in the current docs**: TTL controls how fast changes spread, so lower it before a migration; Registrar and name server delegation must match; Routing policy features differ, so check the current docs.
@diagram cmp
caption: DNS on the three clouds
cards:
  - {h: "Route 53", kind: warn, items: ["Hosted zones, alias, routing policies, health checks"]}
  - {h: "Azure DNS", kind: info, items: ["DNS zones, private zones, Traffic Manager for routing"]}
  - {h: "Cloud DNS", kind: ok, items: ["Managed zones, private zones, routing policies"]}
@h Example
Before a cutover the team lowers the TTL from 3600 to 60 seconds a day earlier, then switches the record.
@h CLI on each cloud
```bash title="AWS CLI, DNS" nocheck
aws route53 create-hosted-zone --name example.com --caller-reference demo-001
```
```bash title="Azure CLI, DNS" nocheck
az network dns zone create --resource-group rg-demo --name example.com
```
```bash title="gcloud, DNS" nocheck
gcloud dns managed-zones create example-zone --dns-name=example.com. --description=demo
```
@check
Why lower TTL before a migration? || Clients then pick up the new record quickly.
@end

@concept 20. CDN
@plain
A network of edge servers near users that cache content and shorten the path to your origin.
@problem
Distant users see high latency and the origin carries every request.
@does
- **Names**: AWS CloudFront; Azure Front Door or Azure CDN; GCP Cloud CDN.
- **What it is**: Caches static and sometimes dynamic content, terminates TLS at the edge and can apply security rules.
- **Choose it when**: Websites and media with global users; Offloading an origin; Edge TLS and WAF.
- **Check in the current docs**: Cache keys and invalidation rules decide correctness; Product lines are changing on Azure, so check the current docs for Front Door versus CDN tiers; Egress to users is priced by region.
@diagram cmp
caption: CDN on the three clouds
cards:
  - {h: "CloudFront", kind: warn, items: ["Distributions, behaviors, origin access control"]}
  - {h: "Front Door or Azure CDN", kind: info, items: ["Front Door profiles, endpoints, routes"]}
  - {h: "Cloud CDN", kind: ok, items: ["Cloud CDN on external load balancer backends"]}
@h Example
Static assets get a one-day cache time and a fingerprinted file name so releases do not need invalidation.
@h CLI on each cloud
```bash title="AWS CLI, CDN" nocheck
aws cloudfront create-distribution --origin-domain-name demo-bucket-123456.s3.amazonaws.com --default-root-object index.html
```
```bash title="Azure CLI, CDN" nocheck
az afd profile create --resource-group rg-demo --profile-name demo-afd --sku Standard_AzureFrontDoor
```
```bash title="gcloud, CDN" nocheck
gcloud compute backend-services update web-backend --global --enable-cdn
```
@check
Why fingerprint asset file names? || New names bypass old cached copies without invalidation.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Overlapping address ranges that block later peering.
- Using layer 7 balancing for plain TCP.
- Long DNS TTLs during cutovers.
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
service: Virtual network
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

