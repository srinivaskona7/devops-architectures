---
title: VPC networking, connectivity, DNS and Cloud Armor
minutes: 60
objectives:
  - Design a global VPC with regional subnets, firewall rules and hierarchical firewall policies
  - Provide outbound access with Cloud Router and Cloud NAT and private access to Google and partner services
  - Connect networks with Shared VPC, peering and Network Connectivity Center and protect edges with Cloud DNS and Cloud Armor
---
Google Cloud networking is software defined and global. One VPC network spans every region, which removes a lot of the peering and gateway plumbing that AWS needs.

@concept Global VPC and subnets
@plain
A **VPC network** is a global virtual network. It contains **subnets**, and each subnet belongs to one region and spans all zones in it.
@problem
Multi-region applications need private connectivity between regions without building tunnels or peering for every region pair.
@does
- Create the VPC in **custom mode** (you define subnets). The auto mode network creates a subnet per region and is not recommended for production.
- Routes and firewall rules belong to the VPC, not to a subnet. VMs in different regions of the same VPC talk over internal IPs by default routes.
- Subnets can have **secondary ranges**, which GKE uses for Pods and Services.
- Subnets can be expanded but not shrunk or moved.
- **AWS equivalent**: VPC with subnets. Main difference: the VPC is global and a subnet is regional, not tied to one AZ.
@diagram layers
caption: One VPC, regional subnets
layers:
  - {label: "Global", nodes: ["VPC shop-net|routes and firewall rules|cp"]}
  - {label: "europe-west1", nodes: ["Subnet 10.10.0.0/20|zones a, b, c|info"]}
  - {label: "us-central1", nodes: ["Subnet 10.20.0.0/20|zones a, b, c|info"]}
@h Create a custom VPC
```bash title="VPC and subnet" lab
gcloud compute networks create shop-net --subnet-mode=custom --bgp-routing-mode=global
gcloud compute networks subnets create shop-ew1 --network=shop-net --region=europe-west1 \
  --range=10.10.0.0/20 --enable-private-ip-google-access \
  --secondary-range=pods=10.64.0.0/14,services=10.68.0.0/20
```
```hcl title="vpc.tf"
resource "google_compute_network" "shop" {
  name                    = "shop-net"
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "ew1" {
  name                     = "shop-ew1"
  region                   = "europe-west1"
  network                  = google_compute_network.shop.id
  ip_cidr_range            = "10.10.0.0/20"
  private_ip_google_access = true
  secondary_ip_range {
    range_name    = "pods"
    ip_cidr_range = "10.64.0.0/14"
  }
  secondary_ip_range {
    range_name    = "services"
    ip_cidr_range = "10.68.0.0/20"
  }
}
```
@check
Does a subnet span a region or a single zone? || A region, across all its zones.
@end

@concept Firewall rules
@plain
**VPC firewall rules** allow or deny traffic to and from VM network interfaces. They are stateful and enforced at the instance, not at the subnet edge.
@problem
You need to control east-west and north-south traffic at the workload without a network appliance.
@does
- Each network has implied rules: deny all ingress and allow all egress at the lowest priority.
- A rule has direction, priority (0 highest to 65535 lowest), action, source or destination ranges and targets (all instances, network tags or service accounts).
- Prefer **service account targets** over network tags, because tags can be set by anyone with VM edit rights.
- Health check ranges (`130.211.0.0/22`, `35.191.0.0/16`) must be allowed for load balancers.
- **AWS equivalent**: security groups and NACLs. Main difference: rules support deny and priorities, and target by tag or service account rather than being attached to a group.
@diagram flow
caption: Rule evaluation at the VM
nodes:
  - "Packet|to VM nic|plain"
  - "Highest priority match|number lower wins|info"
  - "Allow or deny|stateful|warn"
  - "Implied rule|deny ingress|bad"
@h Allow the load balancer and IAP
```bash title="Firewall rules" lab
gcloud compute firewall-rules create allow-lb-health --network=shop-net --direction=INGRESS \
  --action=ALLOW --rules=tcp:8080 --source-ranges=130.211.0.0/22,35.191.0.0/16 \
  --target-service-accounts=shop-api@shop-dev-123456.iam.gserviceaccount.com
gcloud compute firewall-rules create allow-iap-ssh --network=shop-net --direction=INGRESS \
  --action=ALLOW --rules=tcp:22 --source-ranges=35.235.240.0/20
```
:::warn
Check the current Google documentation for the health check and IAP ranges before you rely on these values.
:::
@end

@concept Firewall policies
@plain
**Firewall policies** are rule sets you attach to the organization, a folder or a VPC network. They are evaluated before VPC firewall rules.
@problem
Central security teams need baseline rules that project owners cannot override.
@does
- Evaluation order: organization policy, folder policy, then VPC rules and network policy. A rule action can be `allow`, `deny` or `goto_next` to delegate downward.
- Rules can use **secure tags**, FQDN, geolocation and threat intelligence objects (some features need the Cloud NGFW Standard or Enterprise tier; check the docs).
- **AWS equivalent**: AWS Network Firewall policies and Firewall Manager. Main difference: policies are part of the VPC firewall itself and need no appliance.
@diagram flow
caption: Hierarchical evaluation
numbered: true
nodes:
  - "Organization policy|baseline|cp"
  - "Folder policy|per environment|env"
  - "Network policy|per VPC|info"
  - "VPC rules|per project|app"
@h Create a policy
```bash title="Organization firewall policy" lab
gcloud compute network-firewall-policies create shop-baseline --global --project=shop-dev-123456
gcloud compute network-firewall-policies rules create 1000 --firewall-policy=shop-baseline --global-firewall-policy \
  --action=deny --direction=INGRESS --layer4-configs=tcp:3389 --src-ip-ranges=0.0.0.0/0 --project=shop-dev-123456
gcloud compute network-firewall-policies associations create --firewall-policy=shop-baseline --network=shop-net \
  --name=shop-assoc --global-firewall-policy --project=shop-dev-123456
```
@check
Which is evaluated first, an organization firewall policy or a VPC firewall rule? || The organization firewall policy.
@end

@concept Cloud Router and Cloud NAT
@plain
**Cloud Router** is a managed BGP speaker. **Cloud NAT** gives private VMs and GKE nodes outbound internet access without external IPs.
@problem
Instances without public IPs still need to pull images, reach SaaS APIs and fetch updates.
@does
- Cloud NAT is software defined, attached to a Cloud Router in one region, and has no instance or bandwidth bottleneck of its own.
- Choose automatic or manual external IPs. Use manual IPs when a third party needs to allow-list your egress.
- Watch for **port exhaustion**. Tune minimum ports per VM and enable logging for errors.
- Cloud Router also exchanges routes with VPN and Interconnect.
- **AWS equivalent**: NAT Gateway. Main difference: it is not a VM in a subnet; it is a regional configuration with no zone to choose and no per-gateway hourly appliance.
@diagram flow
caption: Outbound through Cloud NAT
nodes:
  - "Private VM|no external IP|app"
  - "Cloud NAT|regional config|cp"
  - "Reserved IPs|stable egress|info"
  - "Internet|SaaS or registry|ext"
@h Create
```bash title="Router and NAT" lab
gcloud compute routers create shop-router --network=shop-net --region=europe-west1
gcloud compute addresses create shop-nat-ip --region=europe-west1
gcloud compute routers nats create shop-nat --router=shop-router --region=europe-west1 \
  --nat-external-ip-pool=shop-nat-ip --nat-all-subnet-ip-ranges --enable-logging
```
@end

@concept Private Google Access and Private Service Connect
@plain
**Private Google Access** lets VMs without external IPs reach Google APIs. **Private Service Connect (PSC)** creates a private endpoint inside your VPC for a Google API or a published service.
@problem
Sending traffic to storage or a SaaS over the internet is a risk and often blocked by policy.
@does
- Private Google Access is a subnet setting that routes to Google API addresses over Google's network.
- PSC endpoints give a private IP in your subnet that forwards to a service attachment. Producers publish services through a **service attachment**; consumers connect without peering or overlapping-IP problems.
- PSC also reaches Cloud SQL, Memorystore and other managed services in newer configurations; check each service doc.
- **AWS equivalent**: VPC gateway endpoints and PrivateLink. Main difference: PSC works across organizations, with NAT between consumer and producer address spaces.
@diagram flow
caption: Private endpoint to a published service
nodes:
  - "Consumer VPC|PSC endpoint 10.10.0.50|app"
  - "Google backbone|no internet|cp"
  - "Service attachment|producer side|info"
  - "Producer service|ILB behind it|ok"
@h Endpoint for Google APIs
```bash title="PSC endpoint for all Google APIs" lab
gcloud compute addresses create psc-apis --global --purpose=PRIVATE_SERVICE_CONNECT \
  --addresses=10.10.255.1 --network=shop-net
gcloud compute forwarding-rules create pscapis --global --network=shop-net \
  --address=psc-apis --target-google-apis-bundle=all-apis
```
@check
Which subnet setting allows VMs without external IPs to reach Cloud Storage? || Private Google Access.
@end

@concept Shared VPC and VPC peering
@plain
**Shared VPC** lets a host project own the network while service projects use its subnets. **VPC Network Peering** connects two VPC networks privately.
@problem
Many teams in separate projects need one controlled network, or two networks need to talk.
@does
- Shared VPC: the host project is attached at organization or folder level. Grant `roles/compute.networkUser` on specific subnets to service project principals. Central network team controls firewalls and routes.
- Peering is non-transitive and exchanges subnet routes; overlapping ranges are not allowed. Custom routes can be exported or imported.
- Both are free to set up; traffic charges follow the usual rules.
- **AWS equivalent**: resource sharing of subnets with RAM, and VPC peering. Main difference: Shared VPC is a first-class feature with service-project IAM, which many Google Cloud landing zones use as the default.
@diagram layers
caption: Shared VPC model
layers:
  - {label: "Host project", nodes: ["VPC and subnets|owned by network team|cp", "Firewall policies|central|info"]}
  - {label: "Service projects", nodes: ["shop-prod|uses subnet shop-ew1|app", "data-prod|uses subnet data-ew1|app"]}
@h Enable
```bash title="Shared VPC" lab
gcloud compute shared-vpc enable net-host-123456
gcloud compute shared-vpc associated-projects add shop-prod-123456 --host-project=net-host-123456
gcloud compute networks peerings create shop-to-data --network=shop-net \
  --peer-project=data-prod-123456 --peer-network=data-net
```
@end

@concept Network Connectivity Center and hybrid links
@plain
**Network Connectivity Center (NCC)** is a hub for connecting VPC spokes, VPN tunnels, Interconnect attachments and routers. Cloud VPN and Cloud Interconnect are the links to on-premises.
@problem
As networks multiply, full-mesh peering and manual routes become unmanageable, and peering is not transitive.
@does
- Create a hub and attach spokes (VPC spokes, hybrid spokes, router appliances). Spokes then exchange routes.
- HA VPN gives an IPsec link with a 99.99 percent SLA when configured with two tunnels. Dedicated or Partner Interconnect gives private high bandwidth.
- Cloud Router with BGP advertises routes in both directions.
- **AWS equivalent**: Transit Gateway with VPN and Direct Connect. Main difference: NCC is newer and its feature set differs. Check the current docs for transitivity and limits.
@diagram flow
caption: Hub and spokes
nodes:
  - "On-premises|BGP over VPN|ext"
  - "NCC hub|route exchange|cp"
  - "VPC spoke prod|shop-net|app"
  - "VPC spoke data|data-net|app"
@h Hub and spoke
```bash title="NCC" lab
gcloud network-connectivity hubs create shop-hub --description="Shop hub"
gcloud network-connectivity spokes linked-vpc-network create prod-spoke --hub=shop-hub \
  --vpc-network=projects/shop-prod-123456/global/networks/shop-net --global
```
@end

@concept Cloud DNS and Cloud Armor
@plain
**Cloud DNS** hosts public and private zones. **Cloud Armor** is a WAF and DDoS protection service attached to load balancers.
@problem
You need name resolution inside the VPC and in public, and protection from attacks and abusive clients at the edge.
@does
- Private zones are visible only to attached VPC networks. DNS forwarding zones and inbound server policies connect to on-premises resolvers. Response policies override names.
- Cloud DNS offers routing policies such as weighted, geolocation and failover.
- Cloud Armor security policies hold ordered rules with preconfigured WAF rules, rate limiting, IP and geo matching. They attach to backend services of the external Application LB and some others.
- **AWS equivalent**: Route 53 and WAF plus Shield. Main difference: Cloud Armor always lives with the load balancer and the standard tier includes basic L3 and L4 DDoS defence; check the tier details.
@diagram flow
caption: Edge protection
nodes:
  - "Client|internet|ext"
  - "Cloud Armor policy|WAF, rate limit|bad"
  - "Global load balancer|anycast IP|cp"
  - "Backend|GKE or MIG|app"
@h Private zone and a rate-limit policy
```bash title="DNS and Armor" lab
gcloud dns managed-zones create shop-internal --dns-name="shop.internal." --visibility=private \
  --networks=shop-net --description="Private zone"
gcloud compute security-policies create shop-waf --description="Shop edge policy"
gcloud compute security-policies rules create 1000 --security-policy=shop-waf \
  --expression="evaluatePreconfiguredWaf('sqli-v33-stable')" --action=deny-403
gcloud compute backend-services update shop-api-bes --global --security-policy=shop-waf
```
@check
Where do you attach a Cloud Armor policy? || To a backend service of a supported load balancer.
@end
