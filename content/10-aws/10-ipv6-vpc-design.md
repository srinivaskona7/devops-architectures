---
title: IPv6 and reference VPC designs
minutes: 40
objectives:
  - Enable IPv6 and dual-stack subnets and understand egress-only gateways
  - Explain why EKS IPv6 clusters avoid pod IP exhaustion
  - Apply a reference VPC design with a checklist for production
---
IPv4 addresses are scarce and billed. IPv6 solves the scale problem, and a reference design ties together everything in this section.

@concept IPv6 in a VPC
@plain
IPv6 addresses are 128 bits long and globally unique. AWS gives a VPC a /56 block, and each subnet gets a /64.
@problem
Large container platforms run out of private IPv4 addresses, overlap between networks, and pay for public IPv4 addresses.
@does
- Add an Amazon-provided IPv6 CIDR (or bring your own via IPAM) to the VPC and subnets. Every IPv6 address is public by routing design; privacy comes from security groups and routes.
- **Dual-stack** subnets support IPv4 and IPv6; **IPv6-only** subnets exist for some workloads.
- Outbound-only IPv6 from private subnets uses an **egress-only internet gateway**; no NAT is needed.
- **DNS64 and NAT64** let IPv6-only workloads reach IPv4-only services through a NAT gateway.
@diagram cmp
caption: IPv4 and IPv6 at the edge
cards:
  - {h: "IPv4 private", kind: info, items: ["RFC 1918", "NAT gateway for outbound", "Overlaps are common"]}
  - {h: "IPv6", kind: ok, items: ["Globally unique", "Egress-only IGW for outbound", "Security groups control inbound"]}
@h Enable on a VPC
```bash title="Dual stack" lab
aws ec2 associate-vpc-cidr-block --vpc-id vpc-0123456789abcdef0 --amazon-provided-ipv6-cidr-block
aws ec2 create-egress-only-internet-gateway --vpc-id vpc-0123456789abcdef0
aws ec2 create-route --route-table-id rtb-0123456789abcdef0 --destination-ipv6-cidr-block ::/0 \
  --egress-only-internet-gateway-id eigw-0123456789abcdef0
```
@check
How do private subnets get IPv6 outbound access without inbound? || Route ::/0 to an egress-only internet gateway.
@end

@concept IPv6 and EKS
@plain
An EKS cluster can be created in IPv6 mode, where pods receive IPv6 addresses and nodes keep IPv4 for the control plane path.
@problem
IPv4 pod addressing runs out of IPs in busy clusters, and secondary CIDR tricks add complexity.
@does
- Choose the IP family at cluster creation (`ipFamily: ipv6`); it cannot be changed later.
- Each node gets a prefix of IPv6 addresses for its pods; there is no per-ENI IP limit on pods.
- Pods reach IPv4 services through host-local IPv4 addresses via NAT-like behaviour of the VPC CNI.
- Requires dual-stack subnets and a supported set of add-ons; confirm the current constraints in the EKS user guide before committing.
@diagram flow
caption: Pod addressing in IPv6 mode
nodes:
  - "Dual-stack subnet|IPv4 and IPv6 /64|info"
  - "VPC CNI|assigns IPv6 prefix to node|cp"
  - "Pod|IPv6 address|app"
  - "Egress|to IPv4 hosts via node IPv4|ok"
@h Create an IPv6 cluster
```yaml title="eksctl-ipv6.yaml"
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: prod-ipv6
  region: eu-west-1
  version: "{{v.eks_to}}"
kubernetesNetworkConfig:
  ipFamily: IPv6
addons:
  - name: vpc-cni
  - name: coredns
  - name: kube-proxy
iam:
  withOIDC: true
managedNodeGroups:
  - name: ng-1
    instanceType: m6i.large
    desiredCapacity: 3
```
:::note
Check the supported Kubernetes versions in EKS before using a version number from an example.
:::
@end

@concept Reference three-tier VPC
@plain
A common production layout uses three AZs, with public, private and isolated subnets in each, one NAT gateway per AZ and endpoints for AWS services.
@problem
Teams reinvent the same layout with small variations that later hinder peering, inspection and audits.
@does
- /16 per VPC from IPAM; /24 public subnets; large private subnets for nodes and pods; /26 or /24 isolated subnets for databases; small subnets for TGW attachments.
- Gateway endpoints for S3 and DynamoDB, interface endpoints for ECR, STS, logs and others.
- Flow logs to S3, DNS query logging, default security group stripped of rules.
- Spoke to TGW; inspection and egress in shared network account.
@diagram layers
caption: One VPC across three AZs
layers:
  - {label: "Edge", nodes: ["ALB|public subnets x3|info", "NAT per AZ|public subnets x3|info"]}
  - {label: "Compute", nodes: ["EKS nodes and pods|private subnets x3|app"]}
  - {label: "Data", nodes: ["RDS and ElastiCache|isolated subnets x3|ok"]}
  - {label: "Shared", nodes: ["Endpoints|S3, ECR, STS, logs|cp", "TGW attachment|small subnets x3|cp"]}
@h Community module usage
```hcl title="vpc-module.tf"
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "prod"
  cidr = "10.20.0.0/16"
  azs  = ["eu-west-1a", "eu-west-1b", "eu-west-1c"]

  public_subnets   = ["10.20.0.0/24", "10.20.1.0/24", "10.20.2.0/24"]
  private_subnets  = ["10.20.32.0/19", "10.20.64.0/19", "10.20.96.0/19"]
  database_subnets = ["10.20.10.0/26", "10.20.10.64/26", "10.20.10.128/26"]

  enable_nat_gateway     = true
  one_nat_gateway_per_az = true
  enable_dns_hostnames   = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
}
```
@check
Where should databases live in this design? || In isolated subnets with no route to an internet or NAT gateway.
@end

@concept Production VPC checklist
@plain
A short list to review before an environment goes live.
@problem
Network mistakes are slow and risky to fix after workloads depend on them.
@does
- CIDR unique and registered; room for growth; pod IP strategy decided.
- At least two AZs (three for quorum systems); NAT per AZ; route tables explicit.
- Endpoints for S3 and heavy AWS services; endpoint policies where data perimeters matter.
- Flow logs, Route 53 Resolver query logs and a plan for Reachability Analyzer.
- Security groups reference groups; no `0.0.0.0/0` on admin ports; Session Manager instead of SSH.
- IaC for everything, with drift detection.
@diagram flow
caption: Review flow
numbered: true
nodes:
  - "Address plan|IPAM approved|info"
  - "Topology|AZs, subnets, routes|app"
  - "Private access|endpoints and DNS|cp"
  - "Observability|logs and analyzer|env"
  - "Go live|reviewed IaC|ok"
@h Guardrail script
```bash title="Spot-check open admin ports" lab
aws ec2 describe-security-groups \
  --filters Name=ip-permission.from-port,Values=22,3389 Name=ip-permission.cidr,Values=0.0.0.0/0 \
  --query 'SecurityGroups[].[GroupId,GroupName,VpcId]' --output table
aws ec2 describe-vpc-endpoints --query 'length(VpcEndpoints)'
aws ec2 describe-flow-logs --query 'FlowLogs[].[ResourceId,LogDestinationType,FlowLogStatus]' --output table
```
@end
