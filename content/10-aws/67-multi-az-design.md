---
title: Multi-AZ design for the three-tier shop
minutes: 50
objectives:
  - Lay out subnets, NAT, load balancers and nodes so one AZ can fail
  - Handle AZ failure in the data tier and avoid cross-AZ traffic costs
  - Test AZ loss with fault injection
---
Availability Zones are separate data centre groups within a Region. Using three of them is the standard way to survive a facility problem without leaving the Region.
@concept What an AZ gives you
@plain
An AZ is one or more data centres with independent power, cooling and networking, connected to others in the Region by fast links.
@problem
A single data centre fault, power event or network problem must not take the application down.
@does
- Latency between AZs is low (single-digit milliseconds) so synchronous replication (Multi-AZ RDS, Aurora storage) is possible.
- AZ names are per account mapped to physical zones; use **AZ IDs** (`use1-az1`) when coordinating across accounts.
- Not all services are zonal: S3, DynamoDB, SQS are regional; EC2, EBS, NAT Gateway, subnets are zonal.
- Regional services still have their own failure modes; check their SLAs.
@diagram layers
caption: Zonal versus regional
layers:
  - {label: "Zonal", nodes: ["EC2 and EBS|one AZ|warn", "NAT Gateway|one AZ|warn", "Subnets|one AZ|warn"]}
  - {label: "Regional", nodes: ["S3, DynamoDB, SQS|many AZs|ok", "ALB, NLB|nodes per AZ|ok", "Aurora storage|3 AZs|ok"]}
@h List zones
```bash title="Zones and their IDs" lab
aws ec2 describe-availability-zones --query 'AvailabilityZones[].[ZoneName,ZoneId,State]' --output table
```
@check
Why use AZ IDs in cross-account work? || AZ names map to different physical zones in different accounts, but IDs are consistent.
@end

@concept Network layout across AZs
@plain
Replicate each subnet tier in every AZ, give each AZ its own NAT Gateway, and route private subnets to the NAT in the same AZ.
@problem
One NAT Gateway for the VPC is a single point of failure and a cross-AZ data cost.
@does
- Public subnets: ALB, NAT Gateways. Private subnets: nodes and pods. Database subnets: Aurora, ElastiCache.
- One route table per private subnet pointing at the NAT in the same AZ.
- Gateway endpoints for S3 and DynamoDB; interface endpoints for ECR, STS, Secrets Manager, CloudWatch Logs reduce NAT traffic.
- ALB spans all AZs; enable cross-zone load balancing (default on for ALB).
@diagram flow
caption: Per AZ egress path
nodes:
  - "Pods in private subnet a|10.20.16.0/20|app"
  - "Route table a|0.0.0.0/0 to NAT a|info"
  - "NAT Gateway a|public subnet a|cp"
  - "Internet gateway|egress|ext"
@h Terraform routes
```hcl title="Private route per AZ to its own NAT"
resource "aws_route" "private_default" {
  count                  = length(var.azs)
  route_table_id         = aws_route_table.private[count.index].id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.this[count.index].id
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.us-east-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id
}
```
@check
Why one NAT Gateway per AZ? || It avoids a single point of failure and cross-AZ data processing for egress.
@end

@concept Compute and pod placement
@plain
Spread nodes and pods across all AZs, keep spare capacity in each, and make volumes zone-aware.
@problem
An EBS-backed pod cannot move to another AZ, and a node group confined to one AZ cannot reschedule after a failure.
@does
- Managed node groups and Karpenter span all subnets of the cluster; use topology spread on workloads.
- PodDisruptionBudgets protect during drains; the AZ failure itself is an involuntary disruption.
- For stateful sets on EBS, run multiple replicas across zones with application-level replication; the PV stays in its zone.
- Use `topology.kubernetes.io/zone` labels for zone-aware routing; Kubernetes **Topology Aware Routing** (`service.kubernetes.io/topology-mode: Auto`) keeps traffic in-zone when endpoints are balanced.
- Test: cordon and drain all nodes of one AZ in staging.
@diagram flow
caption: What happens when AZ b fails
numbered: true
nodes:
  - "AZ b unreachable|nodes NotReady|bad"
  - "ALB stops targets in b|health checks|warn"
  - "Pods rescheduled|Karpenter adds nodes in a and c|app"
  - "Capacity restored|headroom absorbs load|ok"
@h Topology aware routing
```yaml title="Keep service traffic in-zone when possible"
apiVersion: v1
kind: Service
metadata:
  name: orders
  namespace: shop
  annotations:
    service.kubernetes.io/topology-mode: Auto
spec:
  selector:
    app: orders
  ports:
    - port: 80
      targetPort: 8080
```
@check
Can an EBS volume follow a pod to another AZ? || No; an EBS volume is bound to one AZ.
@end

@concept Data tier failure behaviour
@plain
Each data service handles AZ loss differently; know the recovery time and client behaviour of each.
@problem
Assuming everything fails over instantly leads to long outages from DNS caching, connection pools and cold caches.
@does
- **Aurora**: reader promoted, service typically restored in under 60 seconds and often under 30; with no reader the instance is recreated, which AWS says typically takes under 10 minutes. Clients must reconnect to the cluster endpoint.
- **RDS Multi-AZ instance**: standby promoted, typically 60 to 120 seconds (RDS user guide), via a DNS change.
- **ElastiCache with Multi-AZ**: replica promoted; cache starts partially warm; apps must tolerate misses.
- **DynamoDB, S3, SQS**: regionally replicated, no action needed.
- **EFS**: regional; mount targets in each AZ; clients use the local AZ target.
- **Kafka (MSK)**: replication factor 3 with `min.insync.replicas=2` across AZs.
@diagram cmp
caption: Failover characteristics
cards:
  - {h: "Aurora", kind: ok, items: ["About 30 s", "Cluster endpoint"]}
  - {h: "RDS Multi-AZ", kind: app, items: ["1 to 2 min", "DNS change"]}
  - {h: "ElastiCache", kind: warn, items: ["Replica promoted", "Cold data possible"]}
  - {h: "DynamoDB, S3, SQS", kind: info, items: ["Regional", "No action"]}
@h Test failover
```bash title="Rehearse database failover in staging" lab
aws rds failover-db-cluster --db-cluster-identifier shop-aurora-staging
aws elasticache test-failover --replication-group-id shop-cache-staging --node-group-id 0001
```
@check
Why do clients matter during failover? || DNS caching, connection pools and retry logic decide how fast the application actually recovers.
@end

@concept Cross-AZ traffic costs and balance
@plain
Traffic between AZs is billed per GB in each direction. Multi-AZ designs must watch chatty paths.
@problem
A cluster that spreads microservice calls randomly can generate a large cross-AZ bill without any failure.
@does
- Data transfer between AZs in the same Region has a per-GB charge (check current pricing); within an AZ over private IPs it is free.
- Sources of cross-AZ traffic: service-to-service calls, ALB cross-zone, replication, NAT from another AZ, Kafka consumers.
- Reduce: Topology Aware Routing, keep consumers in the same AZ as brokers when possible (rack-aware fetching), same-AZ NAT, caching.
- Do not sacrifice availability to save these costs for tier 0 services; measure first with VPC Flow Logs and Cost Explorer usage types (`DataTransfer-Regional-Bytes`).
@diagram flow
caption: Cost-aware traffic
nodes:
  - "web pod a|calls orders|app"
  - "Same-zone endpoint|free|ok"
  - "Other-zone endpoint|per GB both ways|warn"
@h Find it
```bash title="Cross-AZ spend in Cost Explorer" nocheck
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-10-31 --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE_GROUP","Values":["EC2: Data Transfer - Inter AZ"]}}'
```
@check
Name two sources of hidden cross-AZ traffic. || Service calls spread across zones, and cross-zone load balancing or replication.
@end

@concept Fault injection and game days
@plain
Prove the design works by breaking it on purpose in a controlled way.
@problem
Untested redundancy often fails because of a missed dependency, a wrong timeout or a quota.
@does
- **AWS Fault Injection Service (FIS)** runs experiments such as stopping instances, throttling APIs, network disruption between subnets, and pod faults on EKS.
- Use stop conditions linked to CloudWatch alarms so an experiment aborts if customers are affected.
- Start in staging; define a hypothesis (error rate stays under 1 percent), run, learn, fix.
- AWS Resilience Hub assesses an application against RTO and RPO targets.
@diagram flow
caption: Experiment loop
numbered: true
nodes:
  - "Hypothesis|AZ loss keeps 99 percent|info"
  - "Experiment|FIS template|app"
  - "Observe|dashboards and alarms|warn"
  - "Fix and repeat|improve|ok"
@h Experiment template
```json title="FIS template pausing network to one subnet (sketch)" nocheck
{
  "description": "Disrupt connectivity of subnet in AZ b",
  "targets": {"subnets": {"resourceType": "aws:ec2:subnet", "resourceTags": {"Name": "shop-private-b"}, "selectionMode": "ALL"}},
  "actions": {"disrupt": {"actionId": "aws:network:disrupt-connectivity", "parameters": {"scope": "all", "duration": "PT5M"}, "targets": {"Subnets": "subnets"}}},
  "stopConditions": [{"source": "aws:cloudwatch:alarm", "value": "arn:aws:cloudwatch:us-east-1:111122223333:alarm:shop-error-rate"}],
  "roleArn": "arn:aws:iam::111122223333:role/fis-experiment"
}
```
@check
What is a stop condition in FIS? || An alarm that aborts the experiment if customer impact appears.
@end
