---
title: WAF, Shield, Macie and edge protection
minutes: 45
objectives:
  - Build WAF web ACLs with managed rules, rate limits and logging
  - Understand Shield Standard and Advanced and the role of CloudFront
  - Find sensitive data in S3 with Macie and apply data protection controls
---
Public applications face bots, injection attempts and floods. Data stores hold personal data. These services add layers around both.

@concept AWS WAF web ACLs
@plain
WAF inspects HTTP requests at an ALB, CloudFront, API Gateway or AppSync and allows, blocks, counts or challenges them based on rules.
@problem
Application layer attacks (SQL injection, XSS, bad bots, scrapers) bypass network firewalls because they look like valid HTTPS.
@does
- A **web ACL** has ordered rules, each with an action; the default action applies if nothing matches.
- **AWS managed rule groups**: Core rule set, Known bad inputs, SQL database, IP reputation, Bot Control, Account Takeover Prevention.
- **Rate-based rules** limit requests per IP in a window (for example 2000 per 5 minutes).
- Start new rules in **Count** mode, review logs, then switch to Block.
- WAF capacity units (WCU) limit complexity; check the current quota.
@diagram flow
caption: Request evaluation
nodes:
  - "Request|HTTP|ext"
  - "Web ACL rules|in priority order|cp"
  - "Allow, block, count, challenge|per rule|warn"
  - "ALB and pods|only allowed traffic|ok"
@h Web ACL
```hcl title="Regional web ACL with managed rules and a rate limit"
resource "aws_wafv2_web_acl" "shop" {
  name  = "shop"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-common"
    priority = 10
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "aws-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "rate-limit"
    priority = 20
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate-limit"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "shop"
    sampled_requests_enabled   = true
  }
}
```
@check
Why start a new rule in Count mode? || To see what it would block in the logs before risking blocking real users.
@end

@concept WAF logging and tuning
@plain
WAF logs every inspected request, including which rule matched, to CloudWatch Logs, S3 or Firehose.
@problem
Managed rules produce false positives, and without logs you cannot tell why a user was blocked.
@does
- Log destinations must have names starting with `aws-waf-logs-`.
- Redact sensitive fields (authorization headers, cookies) with `redacted_fields`.
- Use **labels** and scope-down statements to exclude paths (for example allow large uploads on `/upload`).
- Query blocked requests with Logs Insights; tune with rule exclusions rather than disabling whole groups.
- Add **Bot Control** and **Fraud Control** only where justified; they cost extra.
@diagram flow
caption: Tuning loop
numbered: true
nodes:
  - "Count mode|log only|info"
  - "Review logs|false positives|app"
  - "Exclude rule or path|scope down|warn"
  - "Block mode|enforce|ok"
@h Query
```text title="Logs Insights query for blocked requests by rule" nocheck
fields @timestamp, httpRequest.clientIp, httpRequest.uri, terminatingRuleId
| filter action = "BLOCK"
| stats count(*) as hits by terminatingRuleId, httpRequest.uri
| sort hits desc
| limit 20
```
@check
What lets you keep a managed rule group but allow one path? || A rule exclusion or a scope-down statement.
@end

@concept AWS Shield
@plain
Shield protects against DDoS attacks. **Standard** is automatic and free on all AWS resources; **Advanced** adds detection tuning, the response team, and cost protection.
@problem
Volumetric floods saturate bandwidth, and application floods exhaust servers.
@does
- Standard defends against common network and transport layer (L3/L4) attacks on CloudFront, Route 53, ALB, NLB and Elastic IP.
- Advanced is a subscription per organisation; protects named resources, gives near real-time metrics, access to the Shield Response Team, and credits for scaling charges during attacks.
- Best practice: put CloudFront and Route 53 in front, hide origins (allow only CloudFront prefix list), scale on demand, and use WAF rate rules for L7.
- Design for attack surface reduction: no direct public IPs on nodes, private subnets.
@diagram layers
caption: Layered DDoS design
layers:
  - {label: "Edge", nodes: ["Route 53|anycast DNS|ext", "CloudFront|absorbs traffic|ext"]}
  - {label: "Protection", nodes: ["Shield|L3 and L4|ok", "WAF|L7 rate rules|warn"]}
  - {label: "Origin", nodes: ["ALB in VPC|only CloudFront allowed|cp", "Pods|autoscaled|app"]}
@h Lock the origin
```hcl title="Allow only CloudFront to reach the ALB"
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_vpc_security_group_ingress_rule" "from_cloudfront" {
  security_group_id = aws_security_group.alb.id
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
```
@check
What does Shield Advanced add to Standard? || Tuned detection, access to the response team, and cost protection for attack-driven scaling.
@end

@concept Network Firewall and security groups
@plain
Security groups filter by IP and port at the instance or pod level. AWS Network Firewall filters at the VPC edge with domain and signature rules.
@problem
Security groups cannot allow "only *.amazonaws.com" or block known malicious domains for egress.
@does
- Security groups are stateful allow lists; reference other groups instead of CIDRs.
- NACLs are stateless subnet filters; use sparingly.
- Network Firewall supports stateful rules, domain allow lists (SNI), and Suricata-compatible rules, deployed in a dedicated inspection subnet.
- Route 53 Resolver DNS Firewall blocks lookups to malicious domains.
- Egress control matters for EKS: restrict pods to required endpoints, since malware needs outbound access.
@diagram flow
caption: Egress inspection
nodes:
  - "Pod|outbound request|app"
  - "NAT or Network Firewall|domain allow list|cp"
  - "Allowed domains|ECR, STS, partner APIs|ok"
  - "Blocked|everything else|bad"
@h Domain allow list
```json title="Network Firewall rule group (domain list)" nocheck
{
  "RulesSource": {
    "RulesSourceList": {
      "Targets": [".amazonaws.com", ".example.com"],
      "TargetTypes": ["TLS_SNI", "HTTP_HOST"],
      "GeneratedRulesType": "ALLOWLIST"
    }
  }
}
```
@check
Why is egress filtering valuable? || Compromised workloads need outbound access to download tools or exfiltrate data; blocking it limits damage.
@end

@concept Amazon Macie
@plain
Macie scans S3 buckets for sensitive data (personal information, credentials, financial data) using managed and custom identifiers, and reports on bucket security posture.
@problem
You cannot protect data you do not know you have, and a bucket of customer exports can be forgotten.
@does
- Inventory of buckets with public access, encryption and sharing status.
- **Sensitive data discovery jobs** scan objects; automated discovery samples continuously.
- Findings (policy and sensitive data) go to Security Hub and EventBridge.
- Custom data identifiers use regex plus keywords.
- Cost is per bucket and per GB inspected; scope jobs to relevant buckets.
@diagram flow
caption: Discover and protect
numbered: true
nodes:
  - "S3 buckets|inventory|app"
  - "Macie job|scan objects|cp"
  - "Findings|PII, keys|warn"
  - "Remediate|encrypt, restrict, delete|ok"
@h Job
```bash title="Start a discovery job" nocheck
aws macie2 enable-macie
aws macie2 create-classification-job --job-type ONE_TIME --name scan-exports \
  --s3-job-definition '{"bucketDefinitions":[{"accountId":"111122223333","buckets":["shop-customer-exports"]}]}'
aws macie2 list-findings --max-results 5
```
@check
What does Macie examine? || The contents and configuration of S3 buckets to find sensitive data and risky settings.
@end

@concept Data protection checklist
@plain
A short list of controls that apply to every data store on a typical EKS application.
@problem
Security is easy to promise and hard to verify; a checklist makes review repeatable.
@does
- Encrypt at rest with KMS (RDS, EBS, S3, DynamoDB, EFS) and in transit with TLS; enforce `aws:SecureTransport` in bucket policies.
- Block public access at account level for S3.
- Private subnets and VPC endpoints for AWS APIs; no public database endpoints.
- Backups in a separate account or Region with immutability.
- Least privilege IAM with Pod Identity or IRSA, no static keys.
- Logging: CloudTrail, VPC flow logs, WAF logs, ALB logs, EKS audit logs.
@diagram layers
caption: Defence in depth for the shop
layers:
  - {label: "Edge", nodes: ["WAF and Shield|filtering|warn", "ACM TLS|in transit|ok"]}
  - {label: "Workload", nodes: ["Network policy|pod isolation|info", "Pod Identity|no keys|ok"]}
  - {label: "Data", nodes: ["KMS encryption|at rest|ok", "Backups|isolated copy|ok"]}
@h Bucket policy
```json title="Deny non-TLS access to a bucket"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::shop-customer-exports", "arn:aws:s3:::shop-customer-exports/*"],
      "Condition": {"Bool": {"aws:SecureTransport": "false"}}
    }
  ]
}
```
@check
Which condition key forces TLS in S3 policies? || aws:SecureTransport.
@end
