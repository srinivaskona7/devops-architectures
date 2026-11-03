---
title: Network Load Balancer and Gateway Load Balancer
minutes: 45
objectives:
  - Configure an NLB with static IPs, TLS listeners and client IP preservation
  - Explain NLB security groups, cross-zone and health check behaviour
  - Build a transparent inspection path with GWLB and GENEVE
---
When you need raw TCP or UDP, static addresses, extreme throughput, or transparent security appliances, the Network and Gateway Load Balancers take over from the ALB.
@concept NLB basics
@plain
The **Network Load Balancer** forwards TCP, UDP and TLS connections at layer 4 with very low latency. It does not look inside HTTP.
@problem
Non-HTTP protocols (databases, MQTT, gRPC with passthrough, game traffic), fixed IPs for firewall allow-lists and PrivateLink all need layer 4.
@does
- One subnet per AZ; each gets a static private IP, or an Elastic IP for internet-facing NLBs.
- Listener protocols: TCP, UDP, TCP_UDP, TLS, QUIC passthrough options (check current support).
- Preserves the client source IP for instance targets by default; for IP targets it can be configured. Enable **proxy protocol v2** to pass the client IP to targets that cannot see it.
- Can have security groups attached (a more recent option); if you create without one you cannot add it later in some cases, so check the current documentation before design.
- **Cross-zone load balancing is off by default** and billed for inter-AZ data when enabled.
@diagram flow
caption: NLB data path
nodes:
  - "Client|TCP or UDP|ext"
  - "NLB node|static IP per AZ|cp"
  - "Target group|instances, IPs, ALB|app"
  - "Target|sees client IP|ok"
@h Terraform
```hcl title="nlb.tf"
resource "aws_lb" "tcp" {
  name               = "tcp-front"
  load_balancer_type = "network"
  internal           = false

  subnet_mapping {
    subnet_id     = var.public_subnet_ids[0]
    allocation_id = aws_eip.nlb_a.id
  }
  subnet_mapping {
    subnet_id     = var.public_subnet_ids[1]
    allocation_id = aws_eip.nlb_b.id
  }
  enable_cross_zone_load_balancing = false
}

resource "aws_lb_target_group" "mqtt" {
  name        = "mqtt"
  port        = 1883
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = var.vpc_id
  proxy_protocol_v2 = false
  preserve_client_ip = "true"
  health_check {
    protocol = "TCP"
  }
}
```
@check
Why use an NLB when firewalls on the partner side need fixed IPs? || NLB gives one static IP per AZ, and Elastic IPs for internet-facing ones, so allow-lists stay stable.
@end

@concept NLB TLS, health checks and draining
@plain
An NLB can terminate TLS, run TCP or HTTP health checks, and hold existing connections during deregistration.
@problem
Terminating TLS in each backend means certificate rotation everywhere; a hung backend still accepting TCP should leave rotation.
@does
- TLS listeners use ACM certificates and a security policy; ALPN policies support HTTP/2 passthrough.
- Health checks: TCP, HTTP, HTTPS. Targets in an AZ with no healthy target: with cross-zone off, that AZ fails open to all targets (fail-open behaviour when all targets are unhealthy; check current docs).
- **Connection termination on deregistration** is off by default; connections remain until idle timeout (350 seconds for TCP flows). Tune with `deregistration_delay.connection_termination.enabled`.
- Idle timeout for TCP is 350 seconds; use TCP keepalive on long-lived connections.
@diagram seq
caption: TLS terminated at the NLB
actors: ["Client|TLS 1.3|ext", "NLB|ACM certificate|cp", "Target|plain TCP|app"]
steps:
  - "0>1: TLS handshake | tls"
  - "1>2: TCP to target port | req"
  - "2>1: bytes | resp"
  - "1>0: encrypted bytes | tls"
@h Listener
```hcl title="nlb-tls.tf"
resource "aws_lb_listener" "tls" {
  load_balancer_arn = aws_lb.tcp.arn
  port              = 8883
  protocol          = "TLS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.mqtt.arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mqtt.arn
  }
}
```
:::note
Idle timeout and keepalive values are documented per load balancer type and can change. Check the current limits for your design.
:::
@end

@concept NLB with PrivateLink and ALB-type targets
@plain
An NLB is the entry point for **PrivateLink endpoint services**, and an NLB can forward to an ALB to combine static IPs with layer 7 routing.
@problem
Customers want a stable IP for a layer 7 service, or want to consume your service privately from other VPCs.
@does
- `target_type = alb` registers an ALB as an NLB target: clients connect to the NLB's static IPs, which forward to the ALB.
- PrivateLink: attach the NLB to an endpoint service; consumers create interface endpoints.
- Client IP is not preserved across PrivateLink unless proxy protocol is enabled.
@diagram flow
caption: Static IP with layer 7 routing
nodes:
  - "Partner firewall|allow-lists NLB IPs|ext"
  - "NLB|static IPs|cp"
  - "ALB target|content routing|app"
  - "Services|target groups|ok"
@choose Fronting a web service
ALB only | HTTP routing, WAF and no IP allow-list needed | clients need fixed IPs
NLB then ALB | fixed IPs plus path routing | the extra hop and cost are unacceptable
NLB only | pure TCP or UDP | you need header based routing
@end

@concept Gateway Load Balancer
@plain
**GWLB** puts a fleet of virtual appliances (firewalls, intrusion prevention) transparently in the path of traffic, and scales them as one.
@problem
Inserting an appliance by hand means asymmetric routing, no scaling, and failover scripts.
@does
- Operates at layer 3; wraps packets in **GENEVE** (UDP 6081) and sends them to appliances, which return them unchanged.
- Preserves the 5-tuple flow stickiness so both directions of a flow reach the same appliance.
- Exposed to other VPCs through a **GWLB endpoint** (a PrivateLink type) that appears as a route target.
- Appliances register in a target group with GENEVE protocol and health checks (TCP, HTTP or HTTPS).
@diagram flow
caption: Traffic inspected transparently
numbered: true
nodes:
  - "Workload subnet|route 0.0.0.0/0 to GWLB endpoint|app"
  - "GWLB endpoint|in the workload VPC|info"
  - "GWLB|in the inspection VPC|cp"
  - "Appliance|inspects and returns|warn"
  - "Internet or destination|after inspection|ext"
@h Setup outline
```hcl title="gwlb.tf"
resource "aws_lb" "gwlb" {
  name               = "inspection"
  load_balancer_type = "gateway"
  subnets            = var.inspection_subnet_ids
}

resource "aws_lb_target_group" "appliances" {
  name     = "appliances"
  port     = 6081
  protocol = "GENEVE"
  vpc_id   = var.inspection_vpc_id
  health_check {
    protocol = "TCP"
    port     = 443
  }
}

resource "aws_vpc_endpoint_service" "gwlb" {
  acceptance_required        = false
  gateway_load_balancer_arns = [aws_lb.gwlb.arn]
}
```
@check
Which port and protocol does GWLB use to talk to appliances? || GENEVE over UDP 6081.
@end

@concept Choosing and costing
@plain
Each type has a different pricing metric and failure behaviour, so decide with both technical and cost data.
@problem
A wrongly chosen load balancer leads to avoidable monthly charges or functional limits.
@does
- ALB: LCU billed by the highest of new connections, active connections, processed bytes, rule evaluations.
- NLB: NLCU on bytes, new and active flows. GWLB: GLCU on similar metrics. Check current pricing for each.
- Many Kubernetes Services of type LoadBalancer each create their own NLB; consolidate behind a shared ingress ALB to reduce count.
- Public IPv4 addresses on internet-facing load balancers are billed; consider dual-stack or IPv6-only clients where possible.
@diagram cmp
caption: Cost levers
cards:
  - {h: "Consolidate", kind: ok, items: ["Shared ALB with many host rules", "Ingress groups in Kubernetes"]}
  - {h: "Avoid cross-AZ", kind: info, items: ["Keep NLB cross-zone off if balanced", "Topology aware routing"]}
  - {h: "Delete orphans", kind: warn, items: ["Load balancers left from deleted clusters", "Check with describe-load-balancers"]}
@h Find idle load balancers
```bash title="Requests per load balancer" lab
for lb in $(aws elbv2 describe-load-balancers --query 'LoadBalancers[].LoadBalancerArn' --output text); do
  name=$(echo "$lb" | sed 's#.*:loadbalancer/##')
  echo "$name"
done
aws cloudwatch get-metric-statistics --namespace AWS/ApplicationELB --metric-name RequestCount \
  --dimensions Name=LoadBalancer,Value=app/web/0123456789abcdef --statistics Sum --period 86400 \
  --start-time "$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
```
@end
