---
title: Data transfer and networking costs
minutes: 45
objectives:
  - Identify which data flows are free, charged per GB or charged per hour
  - Reduce NAT Gateway, cross-AZ and internet egress costs with endpoints and caching
  - Find the top transfer cost drivers with Cost Explorer and VPC Flow Logs
---
Data transfer is the line item that surprises teams most: it has many rules and is billed in many places. Prices vary by Region, so check the current pricing page and use the principles here.

@concept The pricing rules
@plain
Roughly: data in from the internet is free, data out to the internet is charged per GB, traffic between AZs in a Region is charged per GB, and traffic inside one AZ over private IPs is free.
@problem
Architects draw boxes without arrows' price tags; the invoice later shows transfer costs rivalling compute.
@does
- **Inbound** from the internet: free.
- **Outbound** to the internet: charged per GB with a small free tier and volume tiers.
- **Cross-AZ** in the same Region: charged per GB, billed on both sides.
- **Cross-Region**: charged per GB from the source Region.
- **Same AZ, private IP**: free. Using public or Elastic IPs between instances in the same AZ is billed like cross-AZ.
- Many services add their own processing charge (NAT Gateway, Transit Gateway, load balancers, PrivateLink).
@diagram cmp
caption: Direction and price
cards:
  - {h: "Free", kind: ok, items: ["Inbound from internet", "Same AZ over private IP", "S3 to CloudFront"]}
  - {h: "Per GB", kind: warn, items: ["Internet egress", "Cross-AZ", "Cross-Region"]}
  - {h: "Per hour and per GB", kind: bad, items: ["NAT Gateway", "Transit Gateway", "Interface endpoints"]}
@h Read the usage types
```bash title="Cost of data transfer by usage type" lab
aws ce get-cost-and-usage --time-period Start=2026-10-01,End=2026-11-01 --granularity MONTHLY \
  --metrics UnblendedCost --group-by Type=DIMENSION,Key=USAGE_TYPE \
  --filter '{"Dimensions":{"Key":"USAGE_TYPE_GROUP","Values":["EC2: Data Transfer - Internet (Out)","EC2: Data Transfer - Inter AZ","EC2: Data Transfer - Region to Region (Out)","EC2: NAT Gateway - Data Processed"]}}' \
  --query 'ResultsByTime[0].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]' --output table
```
@check
Is traffic between two instances in the same AZ always free? || Only over private IPs; using public or Elastic IPs is charged.
@end

@concept NAT Gateway costs
@plain
A NAT Gateway charges an hourly fee plus a per-GB data processing charge on everything that passes through, in addition to normal data transfer.
@problem
Private nodes pulling images, calling S3 or DynamoDB, and shipping logs push terabytes through NAT.
@does
- Add **gateway endpoints** for S3 and DynamoDB (free); traffic bypasses NAT.
- Add **interface endpoints** for ECR (api, dkr), STS, Secrets Manager, CloudWatch Logs, SSM; they cost per hour per AZ plus per GB, which is usually lower than NAT per GB at high volume.
- Use ECR pull-through cache and node image caching to reduce pulls.
- Find big talkers with VPC Flow Logs or NAT Gateway metrics (`BytesOutToDestination`).
- Keep a NAT per AZ for reliability, accepting the hourly cost; remove NATs in dev AZs if resilience is not needed.
@diagram flow
caption: Move traffic off NAT
nodes:
  - "Pods in private subnet|S3, ECR, STS|app"
  - "Gateway and interface endpoints|private path|ok"
  - "NAT Gateway|only true internet traffic|warn"
  - "Internet|partner APIs|ext"
@h Endpoints
```hcl title="Interface endpoints for ECR and STS"
locals {
  interface_services = ["ecr.api", "ecr.dkr", "sts", "secretsmanager", "logs"]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(local.interface_services)
  vpc_id              = var.vpc_id
  service_name        = "com.amazonaws.us-east-1.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = var.private_subnet_ids
  security_group_ids  = [var.endpoint_sg_id]
  private_dns_enabled = true
}
```
@check
Which endpoint type is free? || Gateway endpoints for S3 and DynamoDB.
@end

@concept Internet egress and CloudFront
@plain
Serving users directly from EC2 or ALB incurs internet egress at the standard rate. CloudFront often costs less per GB and reduces origin load.
@problem
Media and API responses leaving through the ALB form a large and growing part of the bill.
@does
- Data transfer from AWS origins (S3, ALB) to CloudFront is free; you pay CloudFront rates to users, usually lower with volume discounts and free tier.
- Cache static and cacheable API responses; compress (gzip, brotli) responses.
- CloudFront **security savings bundle** and committed-use pricing exist (check current offer).
- Serve images through an image optimiser; avoid sending large JSON unnecessarily (pagination, field selection).
- Direct Connect or Private connectivity reduce egress for hybrid traffic.
@diagram flow
caption: Cheaper path to users
nodes:
  - "User|download|ext"
  - "CloudFront|cached at edge|cp"
  - "ALB origin|fewer requests|app"
  - "S3|free to CloudFront|ok"
@h Compression and caching
```hcl title="CloudFront cache policy with compression"
resource "aws_cloudfront_cache_policy" "static" {
  name        = "shop-static"
  default_ttl = 86400
  max_ttl     = 31536000
  min_ttl     = 0

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}
```
@check
Is transfer from an S3 origin to CloudFront charged? || No, origin-to-CloudFront transfer from AWS origins is free; CloudFront to users is billed.
@end

@concept Cross-AZ and cross-Region traffic in practice
@plain
Distributed systems send data between zones constantly: service calls, replication, consumers, backups.
@problem
Cross-AZ costs scale with traffic volume and are invisible without measurement.
@does
- Enable **Topology Aware Routing** on Services and prefer same-zone targets; ALB cross-zone load balancing introduces cross-AZ hops (acceptable for availability).
- Kafka: rack-aware consumers (follower fetching) reduce cross-AZ reads.
- Databases: send reads to a same-AZ replica only if the driver supports it; otherwise accept the cost.
- Cross-Region: replicate only what you need, compress, and schedule bulk copies; use S3 Replication Time Control only where required.
- Measure with Flow Logs enriched with AZ info or tools like Kubecost network cost allocation.
@diagram cmp
caption: Where cross-AZ appears
cards:
  - {h: "Service mesh and calls", kind: warn, items: ["Random endpoint choice", "Fix with topology routing"]}
  - {h: "Data stores", kind: info, items: ["Replication is necessary", "Reads to local replicas"]}
  - {h: "Queues and streams", kind: app, items: ["Consumer placement", "Rack awareness"]}
@h VPC Flow Logs for analysis
```bash title="Enable flow logs to S3 with AZ details" nocheck
aws ec2 create-flow-logs --resource-type VPC --resource-ids vpc-0123456789abcdef0 \
  --traffic-type ALL --log-destination-type s3 \
  --log-destination arn:aws:s3:::shop-flow-logs/prod/ \
  --log-format '${srcaddr} ${dstaddr} ${bytes} ${az-id} ${pkt-src-aws-service} ${flow-direction}'
```
@check
What is one way to keep Kubernetes service traffic in-zone? || Topology Aware Routing on the Service.
@end

@concept A checklist for transfer savings
@plain
Work through the big levers in order of effort versus payoff.
@problem
Without a list, teams optimise small items first.
@does
- 1. S3 and DynamoDB gateway endpoints everywhere (free, immediate).
- 2. Interface endpoints for ECR, STS, Secrets Manager, Logs where NAT volume is high.
- 3. CloudFront in front of public content and APIs where cacheable.
- 4. Topology Aware Routing and consumer placement.
- 5. Compress logs and responses; sample verbose logs; lower retention.
- 6. Review cross-Region replication and backup copies.
- 7. Keep dev environments on one AZ and one NAT, if acceptable.
- Re-run the usage-type report monthly and track GB per request or per order.
@diagram flow
caption: Order of attack
numbered: true
nodes:
  - "Gateway endpoints|free|ok"
  - "Interface endpoints|where NAT heavy|info"
  - "CloudFront|egress|app"
  - "Topology routing|cross-AZ|warn"
  - "Compression and retention|volume|plain"
@h Quick NAT check
```bash title="NAT gateway bytes in the last day" nocheck
aws cloudwatch get-metric-statistics --namespace AWS/NATGateway --metric-name BytesOutToDestination \
  --dimensions Name=NatGatewayId,Value=nat-0123456789abcdef0 \
  --start-time "$(date -u -v-1d +%FT%TZ)" --end-time "$(date -u +%FT%TZ)" --period 86400 --statistics Sum
```
@check
Which saving is free and immediate? || Adding S3 and DynamoDB gateway endpoints.
@end
