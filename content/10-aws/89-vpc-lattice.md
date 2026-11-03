---
title: Amazon VPC Lattice
minutes: 45
objectives:
  - Explain services, service networks, listeners and target groups in VPC Lattice
  - Secure service to service calls with auth policies and SigV4
  - Compare Lattice with PrivateLink, Transit Gateway and a service mesh
---
VPC Lattice is an application networking layer. It connects services across VPCs and accounts with built-in discovery, routing and authorisation, without managing overlapping networks.

@concept Why Lattice exists
@plain
Lattice lets one service call another by name, across VPCs and accounts, with routing and access control handled by AWS.
@problem
Connecting many services across VPCs normally needs peering or a transit gateway, non-overlapping CIDRs, DNS plumbing and per-service security groups.
@does
- Works at layer 7 (HTTP, HTTPS, gRPC) and also TCP in recent releases; check the current protocol support.
- Overlapping IP ranges are fine, because clients reach a Lattice-provided address, not the target IP.
- Targets can be instances, IPs, Lambda functions, ALBs and Kubernetes pods through the Gateway API controller.
- Billed per service, per GB processed and per request; check current pricing.
@diagram flow
caption: Service to service
nodes:
  - "Client in VPC A|calls orders.example|app"
  - "Service network|association|cp"
  - "Lattice service|rules and auth|info"
  - "Targets in VPC B|pods or functions|ok"
@h List
```bash title="Inspect" lab
aws vpc-lattice list-service-networks
aws vpc-lattice list-services --query 'items[].[name,dnsEntry.domainName]' --output table
```
@check
Can two VPCs with overlapping CIDRs use Lattice? || Yes, since clients connect through Lattice rather than routing to target IPs.
@end

@concept Services, listeners, rules and target groups
@plain
A **service** has **listeners** (protocol and port). **Rules** match requests and forward to **target groups**, like a managed ALB for service to service traffic.
@problem
Each team re-implements routing, weights and health checks differently.
@does
- Rule conditions: path, header, method; actions: forward with weights or fixed response.
- Weighted forwarding supports canary releases between two target groups.
- Health checks per target group.
- A custom domain name and certificate can be attached.
@diagram layers
caption: Service anatomy
layers:
  - {label: "Service", nodes: ["Listener HTTPS 443|protocol and port|cp"]}
  - {label: "Rules", nodes: ["Path /orders|forward 90 to v1 and 10 to v2|info"]}
  - {label: "Targets", nodes: ["Target group v1|instances|app", "Target group v2|lambda|app"]}
@h Terraform
```hcl title="lattice-service.tf"
resource "aws_vpclattice_service" "orders" {
  name      = "orders"
  auth_type = "AWS_IAM"
}

resource "aws_vpclattice_target_group" "v1" {
  name = "orders-v1"
  type = "IP"
  config {
    port           = 8080
    protocol       = "HTTP"
    vpc_identifier = aws_vpc.app.id
  }
}

resource "aws_vpclattice_listener" "https" {
  name               = "http"
  protocol           = "HTTP"
  port               = 80
  service_identifier = aws_vpclattice_service.orders.id
  default_action {
    forward {
      target_groups {
        target_group_identifier = aws_vpclattice_target_group.v1.id
        weight                  = 100
      }
    }
  }
}
```
@end

@concept Service networks and associations
@plain
A **service network** is a logical boundary. Services and VPCs are associated with it, and associated VPCs can reach the associated services.
@problem
You need a simple way to say which VPCs may reach which services.
@does
- Associate services with a network, and VPCs with the same network.
- Share networks across accounts using AWS RAM.
- Security groups on the VPC association restrict which clients in the VPC may call.
- Alternative for single-service sharing: a service-level association or a resource gateway for databases and TCP resources; check current features.
@diagram flow
caption: Associations
nodes:
  - "Service network|shared with RAM|cp"
  - "VPC associations|clients|app"
  - "Service associations|providers|ok"
@h Associate a VPC
```hcl title="assoc.tf"
resource "aws_vpclattice_service_network" "main" {
  name      = "shop"
  auth_type = "AWS_IAM"
}

resource "aws_vpclattice_service_network_vpc_association" "app" {
  vpc_identifier             = aws_vpc.app.id
  service_network_identifier = aws_vpclattice_service_network.main.id
  security_group_ids         = [aws_security_group.lattice_clients.id]
}
```
@check
How are service networks shared between accounts? || With AWS RAM.
@end

@concept Auth policies and SigV4
@plain
Lattice evaluates **auth policies** (resource policies in IAM policy language) on service networks and services, for clients that sign requests with SigV4.
@problem
Network reachability alone does not say whether this caller may use this API.
@does
- Auth type `AWS_IAM` requires signed requests; `NONE` allows any caller in the network.
- Policies can allow by principal, org ID, path and method using `vpc-lattice-svcs:` condition keys.
- The network-level policy is evaluated first, then the service-level policy; both must allow.
- Pods and functions sign with their workload identity, so policies refer to roles, not IPs.
@diagram seq
caption: Authorised call
actors: ["Client|signs with SigV4|app", "Lattice|evaluates auth policy|cp", "Target|orders|ok"]
steps:
  - "0>1: signed request | tls"
  - "1>1: network and service policy | warn"
  - "1>2: forward if allowed | req"
  - "2>0: response | resp"
@h Policy
```json title="auth-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": "*",
    "Action": "vpc-lattice-svcs:Invoke",
    "Resource": "*",
    "Condition": {
      "StringEquals": {"aws:PrincipalOrgID": "o-exampleorgid"},
      "StringLike": {"vpc-lattice-svcs:RequestPath": "/orders/*"}
    }
  }]
}
```
```bash title="Apply policy" nocheck
aws vpc-lattice put-auth-policy --resource-identifier svc-0abc123 --policy file://auth-policy.json
```
@check
Which auth type requires signed requests? || AWS_IAM.
@end

@concept Lattice with Kubernetes
@plain
The AWS Gateway API Controller maps Kubernetes Gateway API objects (Gateway, HTTPRoute) to Lattice services and target groups.
@problem
Cross-cluster, cross-VPC service calls usually need a mesh or per-service load balancers.
@does
- A `Gateway` with class `amazon-vpc-lattice` represents a service network.
- An `HTTPRoute` becomes a Lattice service and rules; pods become targets.
- Works across EKS clusters and with EC2 or Lambda targets in the same service network.
- Use IAM auth with pod identity for callers.
@diagram flow
caption: Gateway API to Lattice
nodes:
  - "HTTPRoute|Kubernetes object|app"
  - "Gateway API controller|reconciles|cp"
  - "Lattice service|created|info"
  - "Pods|targets|ok"
@h Manifests
```yaml title="gateway.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shop
spec:
  gatewayClassName: amazon-vpc-lattice
  listeners:
    - name: http
      protocol: HTTP
      port: 80
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: orders
spec:
  parentRefs:
    - name: shop
      sectionName: http
  rules:
    - backendRefs:
        - name: orders
          kind: Service
          port: 8080
```
@end

@concept Lattice versus PrivateLink, Transit Gateway and meshes
@plain
These tools overlap but solve different problems.
@problem
Choosing wrongly adds cost or leaves gaps in security and routing.
@does
- **PrivateLink**: one provider service exposed to consumer VPCs through endpoints, layer 4, no routing rules.
- **Transit Gateway**: network connectivity between networks (layer 3), needs distinct CIDRs and security groups per service.
- **Lattice**: application layer discovery, routing and IAM auth across VPCs and accounts, overlapping IPs allowed.
- **Service mesh** (Istio, App Mesh style): in-cluster features such as mTLS, retries and rich telemetry via sidecars; AWS App Mesh is being retired, so check its end-of-support date before using it.
@diagram cmp
caption: Network options
cards:
  - {h: "PrivateLink", kind: info, items: ["Layer 4", "One service to many consumers", "Endpoint per VPC"]}
  - {h: "Transit Gateway", kind: cp, items: ["Layer 3 hub", "Needs unique CIDRs", "Broad connectivity"]}
  - {h: "VPC Lattice", kind: ok, items: ["Layer 7 routing", "IAM auth policies", "Overlap allowed"]}
@choose Pick one
VPC Lattice | many services across VPCs and accounts need routing and IAM auth | you only need raw network reachability
PrivateLink | one service shared with consumers who may overlap | you need path routing
Transit Gateway | broad network connectivity including on-premises | you want per-service authorisation
@check
Which supports overlapping CIDRs and path routing? || VPC Lattice.
@end

@concept Observability and limits
@plain
Lattice emits access logs and metrics for each service, giving visibility into service to service traffic.
@problem
East-west traffic is often a blind spot.
@does
- Access logs to CloudWatch Logs, S3 or Firehose per service or network, with request path, caller identity and target latency.
- Metrics for request count, response codes and latency per service and target group.
- Check quotas for services per network, associations and rules.
- Cost scales with requests and data; model it with the current rates before moving high-volume traffic.
@diagram flow
caption: Visibility
nodes:
  - "Lattice service|requests|cp"
  - "Access logs|caller and latency|info"
  - "Alarms|5xx and latency|warn"
@h Enable logs
```hcl title="lattice-logs.tf"
resource "aws_vpclattice_access_log_subscription" "orders" {
  resource_identifier = aws_vpclattice_service.orders.arn
  destination_arn     = aws_cloudwatch_log_group.lattice.arn
}
```
@end
