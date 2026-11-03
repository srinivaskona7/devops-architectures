---
title: Security groups, NACLs and flow logs
minutes: 40
objectives:
  - Compare security groups and network ACLs and choose where each belongs
  - Write security group rules that reference other groups instead of CIDRs
  - Enable and query VPC Flow Logs to debug rejected traffic
---
Two firewalls protect traffic in a VPC and they behave differently. Understanding the difference is the quickest way to debug "connection timed out".

@concept Security groups
@plain
A **security group** is a stateful firewall attached to a network interface (an instance, load balancer, endpoint or database). It lists what is allowed in and out.
@problem
Hosts need to accept traffic only from the right sources, and the rules must follow the host rather than an IP range that changes.
@does
- **Allow rules only**; everything not allowed is dropped. No deny rules.
- **Stateful**: return traffic for an allowed connection is permitted automatically.
- A rule source can be a CIDR, a prefix list or **another security group**, so "app tier accepts from the load balancer group" survives scaling.
- Default: new groups allow all outbound and no inbound. Multiple groups on one interface are combined (union). Check the current quota for rules per group and groups per interface.
@diagram flow
caption: Referencing groups instead of IPs
nodes:
  - "Internet|port 443|ext"
  - "alb-sg|allows 443 from anywhere|info"
  - "app-sg|allows 8080 from alb-sg|app"
  - "db-sg|allows 5432 from app-sg|ok"
@h Rules in Terraform
```hcl title="sg.tf"
resource "aws_security_group" "app" {
  name   = "app"
  vpc_id = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "from_alb" {
  security_group_id            = aws_security_group.app.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
```
```bash title="Find groups open to the world" lab
aws ec2 describe-security-groups \
  --filters Name=ip-permission.cidr,Values=0.0.0.0/0 \
  --query 'SecurityGroups[].[GroupId,GroupName]' --output table
```
@check
Why is a security group rule that references another group better than a CIDR? || It follows instances as they scale or change IPs and states the intent directly.
@end

@concept Network ACLs
@plain
A **network ACL (NACL)** is a stateless firewall on the subnet boundary. Rules are numbered and evaluated in order, and they can allow or deny.
@problem
Sometimes you need a coarse subnet-wide block, for example to deny a hostile IP range, which security groups cannot express.
@does
- **Stateless**: you must allow both directions, including the ephemeral return ports (1024-65535 is a common range).
- Rules are processed from the lowest number; the first match wins; a final `*` rule denies everything.
- One NACL per subnet; the default NACL allows all.
- Use sparingly. Most designs keep the default allow-all and rely on security groups.
@diagram cmp
caption: Security group versus NACL
cards:
  - {h: "Security group", kind: ok, items: ["Attached to an interface", "Stateful", "Allow rules only", "All rules evaluated"]}
  - {h: "Network ACL", kind: warn, items: ["Attached to a subnet", "Stateless", "Allow and deny", "First matching rule wins"]}
@h Deny a range
```bash title="NACL rules" lab
aws ec2 create-network-acl-entry --network-acl-id acl-0123456789abcdef0 \
  --ingress --rule-number 90 --protocol -1 --cidr-block 198.51.100.0/24 --rule-action deny
aws ec2 describe-network-acls --network-acl-ids acl-0123456789abcdef0 \
  --query 'NetworkAcls[].Entries[].[RuleNumber,Egress,RuleAction,CidrBlock,Protocol]' --output table
```
:::warn
Forgetting the return path is the classic NACL bug: the request arrives, the reply is dropped on the way out, and the client sees a timeout.
:::
@end

@concept Debugging with Reachability Analyzer
@plain
**Reachability Analyzer** examines your configuration, not live traffic, and tells you whether a path between two resources exists and which component blocks it.
@problem
A timeout can be caused by a route, security group, NACL, endpoint policy or missing attachment. Guessing among them wastes hours.
@does
- Define a source and destination (instance, ENI, gateway, endpoint, IP), protocol and port.
- Returns an explanation such as "blocked by security group sg-0abc, no inbound rule matched".
- Covers peering, TGW, VPN and endpoints in the path. Charged per analysis; check current pricing.
@diagram flow
caption: Typical triage order for a timeout
numbered: true
nodes:
  - "Route exists?|both directions|info"
  - "Security groups|source egress and target ingress|app"
  - "NACLs|both directions plus ephemeral ports|warn"
  - "Target listening?|process and OS firewall|env"
  - "Reachability Analyzer|confirms the first block|cp"
@h Run an analysis
```bash title="Analyze a path" lab
PATH_ID=$(aws ec2 create-network-insights-path --source i-0aaa --destination i-0bbb \
  --protocol tcp --destination-port 5432 --query 'NetworkInsightsPath.NetworkInsightsPathId' --output text)
AN=$(aws ec2 start-network-insights-analysis --network-insights-path-id "$PATH_ID" \
  --query 'NetworkInsightsAnalysis.NetworkInsightsAnalysisId' --output text)
sleep 20
aws ec2 describe-network-insights-analyses --network-insights-analysis-ids "$AN" \
  --query 'NetworkInsightsAnalyses[].[Status,NetworkPathFound]'
```
@check
Does Reachability Analyzer send real packets? || No. It analyses the configuration of the path.
@end

@concept VPC Flow Logs
@plain
**Flow logs** record metadata about IP traffic: source, destination, ports, protocol, bytes and whether it was accepted or rejected. They do not contain payloads.
@problem
You need evidence of who talks to whom, which traffic is being blocked, and what is driving data transfer cost.
@does
- Enable at VPC, subnet or interface level. Destinations: CloudWatch Logs, S3 or Kinesis Data Firehose.
- Default format has fixed fields; custom formats add `pkt-srcaddr`, `pkt-dstaddr` (original addresses behind NAT or an endpoint), `flow-direction`, `tcp-flags`, `az-id`, `traffic-path` and more.
- Aggregation interval of 1 or 10 minutes. Records show an `ACCEPT` or `REJECT` action, where reject means a security group or NACL denied it.
- For a busy network, deliver to S3 in Parquet and query with Athena.
@diagram flow
caption: Flow log pipeline
nodes:
  - "ENI traffic|metadata only|app"
  - "Flow logs|custom format|cp"
  - "S3 Parquet|partitioned by day|ok"
  - "Athena|top talkers and rejects|info"
@h Enable and query
```hcl title="flowlogs.tf"
resource "aws_flow_log" "vpc" {
  vpc_id               = aws_vpc.main.id
  traffic_type         = "ALL"
  log_destination_type = "s3"
  log_destination      = aws_s3_bucket.flowlogs.arn
  max_aggregation_interval = 60
  log_format = "$${version} $${account-id} $${interface-id} $${srcaddr} $${dstaddr} $${srcport} $${dstport} $${protocol} $${bytes} $${action} $${pkt-srcaddr} $${pkt-dstaddr} $${az-id}"
  destination_options {
    file_format = "parquet"
  }
}
```
```sql title="Top rejected destinations" nocheck
SELECT dstaddr, dstport, count(*) AS rejects
FROM vpc_flow_logs
WHERE action = 'REJECT' AND day = '2026-10-31'
GROUP BY dstaddr, dstport ORDER BY rejects DESC LIMIT 20;
```
:::note
In Terraform strings, `$${` produces a literal `${`, which is the flow log field syntax.
:::
@end

@concept Network Firewall, Traffic Mirroring and egress control
@plain
For deeper control than security groups, use **AWS Network Firewall** for stateful inspection and domain filtering, and **Traffic Mirroring** to copy packets for analysis.
@problem
Compliance often requires restricting outbound traffic to approved domains and inspecting traffic between VPCs.
@does
- Network Firewall: managed, deployed in firewall subnets per AZ; supports Suricata-compatible rules and domain allow-lists.
- Common pattern: a central inspection VPC attached to a Transit Gateway in **appliance mode**, so both directions of a flow hit the same AZ's firewall.
- Gateway Load Balancer fronts third-party appliances in the same pattern.
- DNS Firewall (Route 53 Resolver) blocks lookups of malicious or unapproved domains.
@diagram layers
caption: Centralised egress inspection
layers:
  - {label: "Spokes", nodes: ["Workload VPCs|default route to TGW|app"]}
  - {label: "Hub", nodes: ["Transit Gateway|appliance mode on inspection attachment|cp"]}
  - {label: "Inspection VPC", nodes: ["Network Firewall|allow-list domains|warn", "NAT gateway|single egress IP set|info"]}
  - {label: "Outside", nodes: ["Internet|approved destinations only|ext"]}
@choose Egress control
Security group only | simple internal services | you must restrict by domain name
Network Firewall | domain and protocol filtering centrally | a tiny dev account
Proxy (Squid) on EC2 | existing proxy skills, per-user logging | you want fully managed
@end
