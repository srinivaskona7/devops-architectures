---
title: Elastic Load Balancing and the Application Load Balancer
minutes: 50
objectives:
  - Choose between ALB, NLB and GWLB for a given traffic type
  - Configure ALB listeners, rules and target groups with path and host routing
  - Explain cross-zone behaviour, scaling and the load balancer security group pattern
---
A load balancer is the front door of most AWS applications. Choosing the right type and configuring it properly determines latency, cost and how safely you can deploy.

@concept The three load balancer types
@plain
Elastic Load Balancing offers three main types, each working at a different network layer: **ALB** for HTTP, **NLB** for TCP, UDP and TLS, **GWLB** for network appliances.
@problem
One tool cannot suit web routing, ultra-low-latency TCP and transparent firewall insertion at once.
@does
- **Application Load Balancer (ALB)**: layer 7. Routes on host, path, headers, query string and method; supports HTTP/2, gRPC, WebSockets, authentication actions, WAF and redirects.
- **Network Load Balancer (NLB)**: layer 4. Very high throughput, static IPs per AZ, optional Elastic IPs, preserves client IP, TLS termination, PrivateLink source.
- **Gateway Load Balancer (GWLB)**: layer 3 transparent. Sends all traffic through a fleet of appliances (firewalls, IDS) using GENEVE encapsulation.
- Classic Load Balancer is legacy; migrate off it.
@diagram cmp
caption: Which load balancer
cards:
  - {h: "ALB", kind: app, items: ["HTTP and HTTPS, gRPC", "Content based routing", "WAF, OIDC auth"]}
  - {h: "NLB", kind: info, items: ["TCP, UDP, TLS", "Static IP per AZ", "Millions of requests per second class"]}
  - {h: "GWLB", kind: cp, items: ["Transparent appliances", "GENEVE port 6081", "Inspection VPC pattern"]}
@h List them
```bash title="Inventory" lab
aws elbv2 describe-load-balancers --query 'LoadBalancers[].[LoadBalancerName,Type,Scheme,State.Code]' --output table
aws elbv2 describe-target-groups --query 'TargetGroups[].[TargetGroupName,Protocol,Port,TargetType]' --output table
```
@check
Which load balancer keeps the client source IP and gives you a static IP? || The NLB.
@end

@concept ALB architecture
@plain
An ALB is a set of managed nodes spread across the subnets you choose. DNS resolves its name to the IP addresses of those nodes, which scale up and down with load.
@problem
You need a single, highly available HTTP endpoint that survives the loss of an AZ and grows with traffic.
@does
- Needs at least two subnets in different AZs; public (internet-facing) or private (internal) scheme.
- IPs change as it scales, so always use the DNS name or a Route 53 alias, never the IPs.
- **Cross-zone load balancing** is always on for ALB, so each node can send to targets in any AZ; cross-AZ data between ALB and targets is not charged separately in the same way as other traffic, but check current pricing.
- Billed per hour plus **LCUs** (a blend of new connections, active connections, bytes and rule evaluations).
- Idle timeout defaults to 60 seconds; tune for long requests and keep application keep-alive higher.
@diagram flow
caption: Request path through an ALB
nodes:
  - "Client|DNS alias|ext"
  - "ALB nodes|one per AZ|cp"
  - "Listener rule|host and path|info"
  - "Target group|healthy targets|app"
@h Create with Terraform
```hcl title="alb.tf"
resource "aws_lb" "web" {
  name               = "web"
  load_balancer_type = "application"
  subnets            = var.public_subnet_ids
  security_groups    = [aws_security_group.alb.id]
  idle_timeout       = 60
  drop_invalid_header_fields = true
}
```
:::tip
Turn on access logs to S3 and deletion protection for production load balancers.
:::
@end

@concept Listeners and rules
@plain
A **listener** checks for connections on a port and protocol. Its **rules** pick an action based on conditions, evaluated in priority order.
@problem
One hostname often fronts many services. You need to send `/api` to one set of servers and `/static` to another, redirect HTTP to HTTPS, or return a fixed answer.
@does
- Conditions: host header, path pattern, HTTP header, query string, source IP, HTTP method.
- Actions: `forward` (one or several weighted target groups), `redirect`, `fixed-response`, `authenticate-oidc`, `authenticate-cognito`.
- The default rule catches everything unmatched. Priorities are unique numbers; lowest wins.
- Check the current quota for rules per listener.
@diagram flow
caption: Rule evaluation
numbered: true
nodes:
  - "Request|shop.example.com/api/orders|plain"
  - "Rule 10|host shop and path /api/*|info"
  - "Forward|api target group|app"
  - "Default rule|if nothing matches|warn"
@h Redirect and route
```hcl title="listeners.tf"
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.web.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.web.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate.web.arn
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "not found"
      status_code  = "404"
    }
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
  condition {
    path_pattern {
      values = ["/api/*"]
    }
  }
}
```
@check
Which rule wins when two match? || The one with the lower priority number.
@end

@concept Target groups
@plain
A **target group** is the set of backends a rule forwards to, with its own protocol, port, health check and attributes.
@problem
Backends come and go. The load balancer needs a dynamic, health-aware list.
@does
- Target types: `instance` (by ID), `ip` (any routable address including pods, on-premises via TGW), `lambda`, and `alb` (for NLB in front of ALB).
- Registered by hand, by an Auto Scaling group, or by a controller (AWS Load Balancer Controller for Kubernetes).
- Attributes: `deregistration_delay` (connection draining, default 300 seconds), `slow_start`, `stickiness` (cookie), `load_balancing.algorithm.type` (round robin or least outstanding requests), and anomaly mitigation.
- A target group can be attached to one ALB or NLB; one load balancer can use many groups.
@diagram layers
caption: Target group types
layers:
  - {label: "Listener rule", nodes: ["Forward action|weighted groups allowed|cp"]}
  - {label: "Target group", nodes: ["Health check|path, interval, thresholds|info", "Attributes|draining, stickiness, algorithm|env"]}
  - {label: "Targets", nodes: ["Instances|by ID|app", "IPs|pods, on-premises|app", "Lambda|function|app"]}
@h Weighted forward for canary
```hcl title="canary.tf"
resource "aws_lb_listener_rule" "canary" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 20
  action {
    type = "forward"
    forward {
      target_group {
        arn    = aws_lb_target_group.api_v1.arn
        weight = 95
      }
      target_group {
        arn    = aws_lb_target_group.api_v2.arn
        weight = 5
      }
    }
  }
  condition {
    host_header {
      values = ["api.example.com"]
    }
  }
}
```
```bash title="Inspect target health" lab
aws elbv2 describe-target-health --target-group-arn arn:aws:elasticloadbalancing:eu-west-1:111122223333:targetgroup/api/0123456789abcdef \
  --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State,TargetHealth.Reason]' --output table
```
@end

@concept Security groups and client IP
@plain
The load balancer and its targets each have security groups. The target should accept traffic only from the load balancer's group.
@problem
Targets in private subnets are still exposed if their security group accepts the whole VPC or the internet.
@does
- ALB group: allow 80/443 from the internet (or a prefix list for internal use).
- Target group: allow the app port from the ALB group by **reference**, not by CIDR.
- The ALB terminates the client connection, so the target sees the ALB's IP. The real client IP arrives in the `X-Forwarded-For` header; also `X-Forwarded-Proto` and `X-Forwarded-Port`. Configure the application to trust it only from the ALB.
- `drop_invalid_header_fields` and `desync_mitigation_mode` improve protection against request smuggling.
@diagram seq
caption: Client IP through an ALB
actors: ["Client|198.51.100.7|ext", "ALB|terminates TCP and TLS|cp", "App|target|app"]
steps:
  - "0>1: HTTPS request | tls"
  - "note 1..1: add X-Forwarded-For 198.51.100.7"
  - "1>2: new connection from ALB private IP | req"
  - "2>1: response | resp"
  - "1>0: response | tls"
@h Reference rule
```hcl title="sg-alb-app.tf"
resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
```
:::warn
Never trust `X-Forwarded-For` from direct clients. Only accept it when the request came from your load balancer.
:::
@check
How does an app behind an ALB learn the real client IP? || From the X-Forwarded-For header that the ALB adds.
@end

@concept Authentication and special actions
@plain
An ALB can authenticate users with OIDC or Cognito before forwarding, and can answer requests itself.
@problem
Internal tools often need SSO in front of them but have no login code.
@does
- `authenticate-oidc` redirects to your identity provider, then passes claims to the target in signed headers `x-amzn-oidc-data` and `x-amzn-oidc-accesstoken`. Verify the signature in the application.
- Needs HTTPS listener and outbound access from the ALB to the IdP.
- Redirect and fixed-response actions avoid needing a server for maintenance pages and HTTP to HTTPS redirects.
- Mutual TLS (client certificate verification) is available on ALB listeners; check the current documentation for modes.
@diagram seq
caption: OIDC login at the ALB
actors: ["Browser|user|ext", "ALB|authenticate-oidc|cp", "IdP|corporate SSO|ext", "App|target|app"]
steps:
  - "0>1: GET /admin | req"
  - "1>0: redirect to IdP | resp"
  - "0>2: login and MFA | tls"
  - "2>0: code back to ALB | resp"
  - "1>3: forward with signed claims | req"
@h Rule with OIDC
```hcl title="oidc-rule.tf"
resource "aws_lb_listener_rule" "admin" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 5
  action {
    type = "authenticate-oidc"
    authenticate_oidc {
      authorization_endpoint = "https://idp.example.com/oauth2/authorize"
      token_endpoint         = "https://idp.example.com/oauth2/token"
      user_info_endpoint     = "https://idp.example.com/oauth2/userinfo"
      issuer                 = "https://idp.example.com"
      client_id              = var.oidc_client_id
      client_secret          = var.oidc_client_secret
    }
    order = 1
  }
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.admin.arn
    order            = 2
  }
  condition {
    path_pattern {
      values = ["/admin/*"]
    }
  }
}
```
@end
