---
title: Route 53 and DNS in AWS
minutes: 50
objectives:
  - Create public and private hosted zones and choose the right record type
  - Pick a routing policy for failover, latency, weighted or geographic needs
  - Use Route 53 Resolver endpoints to join AWS and on-premises DNS
---
DNS is the control plane of traffic. In AWS, Route 53 provides authoritative zones, health-based routing and the resolver that every VPC uses.

@concept Hosted zones and records
@plain
A **hosted zone** holds the DNS records for a domain. A **public** zone answers anyone on the internet; a **private** zone answers only inside the VPCs you associate.
@problem
You need names for your services that you control, with an API, and the ability to give internal services names that never leak outside.
@does
- Common records: A, AAAA, CNAME, MX, TXT, NS, SRV, CAA.
- **Alias records** point at AWS resources (ALB, NLB, CloudFront, S3 website, API Gateway, another record) and work at the zone apex, which a CNAME cannot. Queries to alias records for AWS targets are free; check pricing.
- After registering or delegating, point the registrar's NS records at the four name servers of the hosted zone.
- Hosted zones are charged monthly plus per query; check the current pricing.
@diagram flow
caption: Resolution of app.example.com
numbered: true
nodes:
  - "Client|asks its resolver|plain"
  - "Root and .com|delegation|ext"
  - "Route 53 name servers|authoritative|cp"
  - "Alias record|ALB IPs|app"
  - "Client connects|to ALB|ok"
@h Create a zone and alias
```hcl title="dns.tf"
resource "aws_route53_zone" "public" {
  name = "example.com"
}

resource "aws_route53_record" "app" {
  zone_id = aws_route53_zone.public.zone_id
  name    = "app.example.com"
  type    = "A"
  alias {
    name                   = aws_lb.web.dns_name
    zone_id                = aws_lb.web.zone_id
    evaluate_target_health = true
  }
}
```
```bash title="Inspect" lab
aws route53 list-hosted-zones --query 'HostedZones[].[Name,Id,Config.PrivateZone]' --output table
aws route53 list-resource-record-sets --hosted-zone-id Z0123456789ABC --query 'ResourceRecordSets[?Type==`A`].[Name,AliasTarget.DNSName]'
dig +short NS example.com
```
@check
Why use an alias instead of a CNAME at the zone apex? || A CNAME cannot coexist with the other apex records (SOA, NS); an alias is answered as an A or AAAA record and can sit at the apex.
@end

@concept Routing policies
@plain
A routing policy decides which answer Route 53 gives when several records share a name.
@problem
A single static answer cannot shift traffic during a failure, a rollout, or between Regions.
@does
- **Simple**: one or more values, returned together.
- **Weighted**: split traffic by weight, for gradual rollouts and testing.
- **Latency**: answer with the Region giving the lowest latency to the user.
- **Failover**: primary and secondary, driven by a health check.
- **Geolocation** and **Geoproximity**: by user location (country, continent) or with a bias; useful for data residency.
- **IP-based**: by client CIDR. **Multivalue answer**: up to eight healthy records.
@diagram cmp
caption: Which policy for which need
cards:
  - {h: "Weighted", kind: app, items: ["Canary 5 percent", "Blue green shift"]}
  - {h: "Latency", kind: info, items: ["Multi-Region active active", "Closest healthy Region"]}
  - {h: "Failover", kind: warn, items: ["Active passive", "Needs health check"]}
  - {h: "Geolocation", kind: cp, items: ["Residency rules", "Language by country"]}
@h Weighted canary
```hcl title="weighted.tf"
resource "aws_route53_record" "blue" {
  zone_id        = aws_route53_zone.public.zone_id
  name           = "api.example.com"
  type           = "CNAME"
  ttl            = 60
  set_identifier = "blue"
  records        = ["blue.example.com"]
  weighted_routing_policy {
    weight = 95
  }
}

resource "aws_route53_record" "green" {
  zone_id        = aws_route53_zone.public.zone_id
  name           = "api.example.com"
  type           = "CNAME"
  ttl            = 60
  set_identifier = "green"
  records        = ["green.example.com"]
  weighted_routing_policy {
    weight = 5
  }
}
```
@end

@concept Health checks and failover
@plain
Route 53 **health checks** probe an endpoint from several locations and mark it healthy or not. Records tied to a failing check are removed from answers.
@problem
DNS would keep sending users to a dead endpoint without a signal about its state.
@does
- Types: endpoint (HTTP, HTTPS, TCP), calculated (combine others) and CloudWatch alarm based (for private resources that Route 53 cannot reach directly).
- Evaluate target health on alias records to inherit the health of the ALB/NLB targets.
- Clients cache by TTL, so keep TTLs short (for example 60 seconds) on failover records. Some resolvers ignore low TTLs.
- Failover is only as good as the check: test a meaningful path such as `/healthz` that exercises dependencies, but avoid making it so strict that a minor dependency outage drops the whole site.
@diagram seq
caption: Failover to a secondary Region
actors: ["Route 53 checkers|multiple locations|cp", "Primary|eu-west-1|app", "Secondary|eu-central-1|env", "Client|resolver|plain"]
steps:
  - "0>1: HTTPS /healthz | req"
  - "1>0: timeout, check unhealthy | bad"
  - "3>0: query api.example.com | req"
  - "0>3: answers with secondary | resp"
  - "3>2: client connects | req"
@h Failover records
```bash title="Create a health check" lab
aws route53 create-health-check --caller-reference "api-primary-$(date +%s)" \
  --health-check-config Type=HTTPS,FullyQualifiedDomainName=api-primary.example.com,Port=443,ResourcePath=/healthz,RequestInterval=30,FailureThreshold=3
aws route53 get-health-check-status --health-check-id 11111111-2222-3333-4444-555555555555
```
@check
Why keep a low TTL on failover records? || Resolvers cache answers for the TTL, so a long TTL delays clients moving to the secondary.
@end

@concept Private hosted zones
@plain
A **private hosted zone** serves DNS names only to the VPCs associated with it, such as `db.internal.example.com`.
@problem
Internal services need stable names, and you do not want to publish them or their IPs on the internet.
@does
- VPC must have `enableDnsSupport` and `enableDnsHostnames` turned on.
- Can be associated with VPCs in other accounts and Regions (authorise first, then associate).
- **Split-horizon**: the same name can exist in a public and a private zone with different answers; inside associated VPCs the private zone wins.
- Interface endpoint private DNS and EKS private cluster endpoints use private zones under the hood.
@diagram layers
caption: Split horizon DNS
layers:
  - {label: "Inside associated VPCs", nodes: ["Private zone|api.example.com -> 10.20.16.10|ok"]}
  - {label: "Everyone else", nodes: ["Public zone|api.example.com -> ALB public|info"]}
@h Create and associate
```bash title="Private zone across accounts" lab
aws route53 create-hosted-zone --name internal.example.com --caller-reference "internal-$(date +%s)" \
  --vpc VPCRegion=eu-west-1,VPCId=vpc-0123456789abcdef0
# in the zone-owning account, authorise another account's VPC
aws route53 create-vpc-association-authorization --hosted-zone-id Z0123456789ABC --vpc VPCRegion=eu-west-1,VPCId=vpc-0bbb
# in the other account, accept
aws route53 associate-vpc-with-hosted-zone --hosted-zone-id Z0123456789ABC --vpc VPCRegion=eu-west-1,VPCId=vpc-0bbb
```
@end

@concept Route 53 Resolver
@plain
The **Route 53 Resolver** is the DNS server every VPC already has at the VPC base address plus two (for example `10.20.0.2`) and at `169.254.169.253`. **Resolver endpoints** connect it with on-premises DNS.
@problem
On-premises servers must resolve AWS private names, and VPC workloads must resolve corporate names.
@does
- **Inbound endpoint**: ENIs in your VPC that on-premises DNS can forward to.
- **Outbound endpoint** plus **forwarding rules**: send queries for chosen domains (for example `corp.example.com`) to on-premises servers. Share rules with AWS RAM to many accounts.
- **Resolver DNS Firewall** filters outbound queries by domain lists.
- Per-ENI query limit exists (check the current quota); heavy DNS from pods can hit it, so run CoreDNS caching and consider NodeLocal DNSCache.
@diagram flow
caption: Hybrid DNS
nodes:
  - "Pod|queries CoreDNS|app"
  - "VPC resolver|base IP plus two|cp"
  - "Outbound endpoint|forward corp.example.com|info"
  - "On-premises DNS|answers|ext"
@h Forwarding rule
```hcl title="resolver.tf"
resource "aws_route53_resolver_rule" "corp" {
  domain_name          = "corp.example.com"
  rule_type            = "FORWARD"
  resolver_endpoint_id = aws_route53_resolver_endpoint.out.id
  target_ip {
    ip = "192.168.10.10"
  }
}
```
:::tip
Debug from a pod with `kubectl exec -it dnsutils -- dig +short db.internal.example.com` and compare against `dig @169.254.169.253` from a node.
:::
@choose DNS for Kubernetes on AWS
ExternalDNS with Route 53 | Ingress and Service hostnames managed from the cluster | names must be created by a separate process
Manual records | a handful of stable names | frequent app changes
Private zone plus Resolver rules | hybrid internal naming | public-only services
@end
