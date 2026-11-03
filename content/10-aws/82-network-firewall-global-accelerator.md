---
title: Network Firewall and Global Accelerator
minutes: 45
objectives:
  - Deploy AWS Network Firewall with stateless and stateful rule groups
  - Place firewall endpoints in distributed and centralised designs
  - Use Global Accelerator for static anycast entry points and fast failover
---
Network Firewall inspects traffic inside your VPCs. Global Accelerator improves how users reach your endpoints. Both operate at the network layer.

@concept What Network Firewall is
@plain
**AWS Network Firewall** is a managed, stateful network firewall and intrusion prevention service deployed as endpoints in your VPC subnets.
@problem
Security groups and NACLs cannot filter by domain name, inspect protocols or block known bad signatures.
@does
- Rule engines: stateless (fast, 5-tuple) then stateful (Suricata compatible rules, domain lists, protocol detection).
- Scales automatically; one firewall endpoint per AZ.
- Logs alert and flow records to S3, CloudWatch Logs or Firehose.
- Managed rule groups from AWS cover threat signatures and domain reputation; check current groups.
@diagram flow
caption: Inspection path
nodes:
  - "Workload subnet|route to endpoint|app"
  - "Firewall endpoint|per AZ|cp"
  - "Rule engines|stateless then stateful|warn"
  - "Internet gateway or NAT|allowed traffic|ext"
@h Policy outline
```hcl title="firewall.tf"
resource "aws_networkfirewall_firewall_policy" "main" {
  name = "main"
  firewall_policy {
    stateless_default_actions          = ["aws:forward_to_sfe"]
    stateless_fragment_default_actions = ["aws:forward_to_sfe"]
    stateful_rule_group_reference {
      resource_arn = aws_networkfirewall_rule_group.domains.arn
    }
  }
}
```
@check
Which service filters traffic by domain name inside a VPC? || Network Firewall (stateful domain list rules).
@end

@concept Rule groups and domain filtering
@plain
A **rule group** is a reusable set of rules. Stateful groups can allow or deny by domain list, or use Suricata rule strings.
@problem
Workloads should only reach approved external domains, and egress must be controlled without maintaining IP lists.
@does
- Domain list rule groups match the TLS SNI or HTTP host header for chosen protocols.
- Default action `drop established` with alert logging blocks unmatched flows (strict rule order).
- Capacity is fixed when a rule group is created, so size it with headroom.
- Suricata rules allow custom signatures.
@diagram cmp
caption: Rule types
cards:
  - {h: "Stateless", kind: info, items: ["5-tuple match", "Pass, drop, forward", "Fast, no flow state"]}
  - {h: "Stateful domain list", kind: ok, items: ["SNI and host match", "Allow list egress", "Logs"]}
  - {h: "Suricata", kind: cp, items: ["Custom signatures", "IPS", "Regex content"]}
@h Allow list
```hcl title="domains.tf"
resource "aws_networkfirewall_rule_group" "domains" {
  name     = "allowed-domains"
  type     = "STATEFUL"
  capacity = 100
  rule_group {
    rules_source {
      rules_source_list {
        generated_rules_type = "ALLOWLIST"
        target_types         = ["HTTP_HOST", "TLS_SNI"]
        targets              = [".amazonaws.com", "github.com"]
      }
    }
  }
}
```
@check
Why size rule group capacity with headroom? || Capacity is fixed at creation and cannot be raised later.
@end

@concept Firewall deployment models
@plain
Deploy firewall endpoints in each VPC (distributed) or in one inspection VPC reached through a transit gateway (centralised).
@problem
The right placement depends on how many VPCs you have and who owns policy.
@does
- Distributed: endpoint in each VPC, local policy; more endpoints to pay for, less transit traffic.
- Centralised: one inspection VPC with TGW appliance mode; consistent policy, extra hop and TGW data charges.
- Ingress needs an edge route table to send internet gateway traffic through the endpoint first.
- Compare with Gateway Load Balancer for third party appliances.
@diagram flow
caption: Centralised
nodes:
  - "Spoke VPCs|default route to TGW|app"
  - "Transit gateway|appliance mode|cp"
  - "Inspection VPC|firewall endpoints|warn"
  - "Internet|egress|ext"
@choose Placement
Distributed | few VPCs with team-owned rules | many accounts needing one policy
Centralised | many VPCs and a security team | very high cross-AZ transit volume
Third party via GWLB | you must use a vendor firewall | a managed AWS option satisfies needs
@end

@concept Logging and tuning
@plain
Send alert and flow logs somewhere searchable, then tune rules from real traffic.
@problem
A new firewall in drop mode breaks applications that nobody listed.
@does
- Start in alert mode, analyse in Athena or CloudWatch Logs Insights, then move to drop.
- Log fields include the matching rule SID and action.
- Review monthly; remove stale domains.
- Cost: hourly endpoint charge per AZ plus per GB processed; check the current prices.
@diagram flow
caption: Safe rollout
numbered: true
nodes:
  - "Alert only|observe|info"
  - "Analyse logs|find legitimate flows|app"
  - "Allow list|add rules|warn"
  - "Enforce drop|block rest|ok"
@h Logging config
```hcl title="fw-logging.tf"
resource "aws_networkfirewall_logging_configuration" "main" {
  firewall_arn = aws_networkfirewall_firewall.main.arn
  logging_configuration {
    log_destination_config {
      log_destination      = { logGroup = "/nfw/alerts" }
      log_destination_type = "CloudWatchLogs"
      log_type             = "ALERT"
    }
  }
}
```
@check
Why start in alert mode? || To learn legitimate traffic before blocking it.
@end

@concept Global Accelerator basics
@plain
**AWS Global Accelerator** gives your application two static anycast IP addresses that route users onto the AWS backbone at the nearest edge location.
@problem
Internet paths vary, DNS caching slows failover, and clients or firewalls may need fixed IP addresses.
@does
- Listeners accept TCP or UDP on chosen ports; endpoint groups per Region hold endpoints (ALB, NLB, EC2, Elastic IP).
- Health checks and traffic dials move traffic away from unhealthy endpoints within seconds, with no DNS TTL wait.
- Client IP preservation is available for some endpoint types.
- Billed by hour per accelerator plus a data transfer premium; check current pricing.
@diagram flow
caption: Anycast entry
nodes:
  - "User|nearest edge|ext"
  - "Anycast IPs|2 static addresses|cp"
  - "AWS backbone|private path|info"
  - "Regional endpoints|ALB or NLB|app"
@h Terraform
```hcl title="ga.tf"
resource "aws_globalaccelerator_accelerator" "web" {
  name            = "web"
  ip_address_type = "IPV4"
  enabled         = true
}

resource "aws_globalaccelerator_listener" "https" {
  accelerator_arn = aws_globalaccelerator_accelerator.web.id
  protocol        = "TCP"
  port_range {
    from_port = 443
    to_port   = 443
  }
}
```
@check
Why does failover not wait for DNS TTL? || Clients use fixed anycast IPs and Global Accelerator itself reroutes.
@end

@concept Global Accelerator versus CloudFront and Route 53
@plain
CloudFront caches HTTP content at the edge. Route 53 answers DNS. Global Accelerator speeds up and stabilises any TCP or UDP path.
@problem
Teams pick one for everything and miss the better fit.
@does
- CloudFront: cacheable web content, WAF, edge functions, HTTP only.
- Global Accelerator: non-HTTP (gaming, IoT, VoIP), static IPs, instant regional failover for dynamic apps.
- Route 53: low-cost DNS-level routing (latency, weighted, failover); subject to DNS caching.
- Combine them: CloudFront for assets plus Global Accelerator for an API with fixed IPs.
@diagram cmp
caption: Which edge tool
cards:
  - {h: "CloudFront", kind: ok, items: ["Caches HTTP", "WAF", "Edge compute"]}
  - {h: "Global Accelerator", kind: cp, items: ["TCP and UDP", "Static IPs", "Fast failover"]}
  - {h: "Route 53", kind: info, items: ["DNS routing", "Health checks", "Cheapest"]}
@choose Edge choice
CloudFront | content is cacheable HTTP | you need fixed IPs for a TCP service
Global Accelerator | static IP or non-HTTP traffic | caching would solve the problem
Route 53 only | simple multi-Region failover with tolerable TTL | seconds-level failover is required
@end

@concept Multi-Region failover with Global Accelerator
@plain
Place endpoint groups in two Regions and use traffic dials and health checks to steer traffic.
@problem
A Region impairment should shift users automatically and deployments should shift traffic gradually.
@does
- Each endpoint group has a **traffic dial** (0 to 100 percent); set one to 0 to drain a Region.
- Endpoint weights balance inside a group.
- Health checks (TCP, HTTP, HTTPS) decide endpoint health.
- Example: dial eu-west-1 at 90 and us-east-1 at 10 sends a small share to the second Region for warm-up.
@diagram flow
caption: Dialled Regions
nodes:
  - "Accelerator|static IPs|cp"
  - "Group eu-west-1|dial 90|ok"
  - "Group us-east-1|dial 10|info"
@h Endpoint group
```hcl title="ga-group.tf"
resource "aws_globalaccelerator_endpoint_group" "eu" {
  listener_arn          = aws_globalaccelerator_listener.https.id
  endpoint_group_region = "eu-west-1"
  traffic_dial_percentage = 90
  health_check_protocol = "HTTPS"
  health_check_path     = "/healthz"
  endpoint_configuration {
    endpoint_id = aws_lb.web.arn
    weight      = 128
  }
}
```
@check
How do you drain a Region for maintenance? || Set its endpoint group traffic dial to 0.
@end
