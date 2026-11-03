---
title: TLS certificates, WAF and CloudFront
minutes: 50
objectives:
  - Issue and attach ACM certificates and choose security policies
  - Protect an ALB with AWS WAF rules and rate limits
  - Put CloudFront in front of an origin with caching, OAC and private origins
---
Edge security and delivery sit in front of the load balancer. Together TLS, WAF and a CDN reduce attack surface and origin load.

@concept AWS Certificate Manager
@plain
**ACM** issues and renews public TLS certificates for free when used with integrated services (ALB, NLB, CloudFront, API Gateway).
@problem
Manual certificate purchases and renewals cause outages when they expire.
@does
- **DNS validation** via a CNAME record in Route 53 (or elsewhere) renews automatically as long as the record stays.
- Certificates are Regional; CloudFront requires the certificate in `us-east-1`.
- Private keys of public ACM certificates cannot be exported; use ACM Private CA or exportable certificates (a newer paid option) if you need them on your own servers.
- Multiple certificates can be attached to one listener; SNI selects among them.
@diagram flow
caption: Certificate lifecycle
numbered: true
nodes:
  - "Request|domain names|plain"
  - "DNS validation|CNAME record|info"
  - "Issued|attach to listener|ok"
  - "Auto renewal|while the CNAME exists|cp"
@h Terraform
```hcl title="acm.tf"
resource "aws_acm_certificate" "web" {
  domain_name               = "example.com"
  subject_alternative_names = ["*.example.com"]
  validation_method         = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "validation" {
  for_each = {
    for o in aws_acm_certificate.web.domain_validation_options : o.domain_name => o
  }
  zone_id = aws_route53_zone.public.zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 60
}

resource "aws_acm_certificate_validation" "web" {
  certificate_arn         = aws_acm_certificate.web.arn
  validation_record_fqdns = [for r in aws_route53_record.validation : r.fqdn]
}
```
@check
In which Region must a CloudFront certificate live? || us-east-1.
@end

@concept TLS policies and end-to-end encryption
@plain
A **security policy** on a listener sets the TLS versions and ciphers it accepts. For sensitive data you can also encrypt between the load balancer and the targets.
@problem
Old protocol versions are vulnerable, and plaintext inside the VPC may violate compliance.
@does
- Choose a TLS 1.2 plus 1.3 or TLS 1.3-only policy (names like `ELBSecurityPolicy-TLS13-1-2-2021-06`); check the current list of policy names.
- ALB can re-encrypt to HTTPS targets; it does not validate the target certificate, so a self-signed one is acceptable.
- NLB can either terminate TLS or pass it through.
- For service-to-service encryption in Kubernetes consider a service mesh or Kyma's Istio mTLS.
@diagram cmp
caption: Termination options
cards:
  - {h: "Terminate at LB", kind: ok, items: ["Central certificates", "Plain HTTP to targets", "Simplest"]}
  - {h: "Re-encrypt", kind: info, items: ["TLS to targets", "Meets in-transit rules", "More CPU on targets"]}
  - {h: "Passthrough", kind: warn, items: ["NLB TCP listener", "Backend owns certificate", "No L7 features"]}
@h Test a listener
```bash title="Check protocol and certificate" lab
openssl s_client -connect app.example.com:443 -servername app.example.com -tls1_3 </dev/null 2>/dev/null | grep -E "Protocol|Cipher|Verify"
aws elbv2 describe-ssl-policies --names ELBSecurityPolicy-TLS13-1-2-2021-06 --query 'SslPolicies[0].SslProtocols'
```
@end

@concept AWS WAF
@plain
**AWS WAF** inspects HTTP requests on an ALB, CloudFront, API Gateway or AppSync and allows, blocks, counts or challenges them.
@problem
Applications face injection attempts, bots and floods that the application code should not need to filter.
@does
- A **web ACL** holds ordered rules; each rule has an action. The default action applies when nothing matches.
- **Managed rule groups** from AWS and vendors (core rule set, known bad inputs, SQL injection, IP reputation, bot control).
- **Rate-based rules** limit requests per IP (or other key) in a window.
- Start new rules in **count** mode and review logs before switching to block.
- Web ACL capacity units (WCU) limit rule complexity; check the current quota. Logs go to S3, CloudWatch Logs or Firehose.
@diagram flow
caption: WAF decision
numbered: true
nodes:
  - "Request|arrives at ALB|plain"
  - "Rate rule|per IP limit|warn"
  - "Managed rules|core and bad inputs|cp"
  - "Allow|default action|ok"
  - "Block 403|rule matched|bad"
@h Web ACL
```hcl title="waf.tf"
resource "aws_wafv2_web_acl" "web" {
  name  = "web"
  scope = "REGIONAL"
  default_action {
    allow {}
  }
  rule {
    name     = "rate"
    priority = 1
    action {
      block {}
    }
    statement {
      rate_based_statement {
        limit              = 1000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate"
      sampled_requests_enabled   = true
    }
  }
  rule {
    name     = "core"
    priority = 2
    override_action {
      count {}
    }
    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "core"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "web"
    sampled_requests_enabled   = true
  }
}

resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.web.arn
  web_acl_arn  = aws_wafv2_web_acl.web.arn
}
```
:::tip
The core rule set runs in count mode here so you can review false positives first. Switch `override_action` to `none {}` when you are confident.
:::
@check
Why start with count mode? || It shows what would be blocked without affecting real users, so you can tune false positives.
@end

@concept CloudFront basics
@plain
**CloudFront** is a global CDN. Edge locations cache content close to users and speed up dynamic traffic via the AWS backbone.
@problem
Serving everything from one Region is slow for distant users, expensive in egress, and exposes the origin to floods.
@does
- A **distribution** has origins (S3, ALB, custom HTTP), **behaviors** (path patterns with cache and origin settings) and a viewer protocol policy.
- **Cache policy** defines cache key (headers, query strings, cookies) and TTLs; **origin request policy** defines what is forwarded; keep the cache key minimal for a high hit ratio.
- **Origin Access Control (OAC)** lets only CloudFront read a private S3 bucket. For ALB origins use a custom header secret or the managed prefix list for CloudFront origin-facing IPs in the ALB security group, plus VPC origins (a newer option for private ALBs).
- Edge compute: CloudFront Functions (light) and Lambda@Edge.
- Invalidations are available but cost beyond a free monthly allotment; prefer versioned file names.
@diagram flow
caption: Request through CloudFront
nodes:
  - "Viewer|nearest edge|ext"
  - "Edge cache|hit returns immediately|ok"
  - "Origin shield or regional cache|optional|info"
  - "Origin|S3 or ALB|app"
@h S3 origin with OAC
```hcl title="cloudfront.tf"
resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  default_root_object = "index.html"
  aliases             = ["www.example.com"]

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3-site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn = aws_acm_certificate.cf.arn
    ssl_support_method  = "sni-only"
  }
}
```
:::note
The cache policy ID above is the AWS managed CachingOptimized policy. Confirm the ID with `aws cloudfront list-cache-policies --type managed`.
:::
@end

@concept Securing the origin and combining edge services
@plain
If CloudFront and WAF protect you, attackers must not be able to bypass them by calling the origin directly.
@problem
A public ALB reachable by anyone makes edge protections optional.
@does
- Restrict the ALB security group to the CloudFront managed prefix list (`com.amazonaws.global.cloudfront.origin-facing`).
- Add a secret header injected by CloudFront and checked by an ALB rule or WAF rule.
- Attach WAF to CloudFront (global scope, `us-east-1`) for edge filtering; use another web ACL on the ALB if you also serve direct traffic.
- Shield Standard is automatic; Shield Advanced adds support and cost protection for critical apps.
@diagram layers
caption: Defence layers for a public site
layers:
  - {label: "Edge", nodes: ["Shield|DDoS protection|ok", "WAF|web ACL|cp", "CloudFront|cache and TLS|info"]}
  - {label: "Regional", nodes: ["ALB|only CloudFront prefix list allowed|app"]}
  - {label: "Workload", nodes: ["Pods or instances|private subnets|env"]}
@h Lock the ALB
```bash title="Prefix list in the ALB security group" lab
PL=$(aws ec2 describe-managed-prefix-lists --filters Name=prefix-list-name,Values=com.amazonaws.global.cloudfront.origin-facing \
  --query 'PrefixLists[0].PrefixListId' --output text)
aws ec2 authorize-security-group-ingress --group-id sg-0123456789abcdef0 \
  --ip-permissions "IpProtocol=tcp,FromPort=443,ToPort=443,PrefixListIds=[{PrefixListId=$PL}]"
```
@choose Public web entry
CloudFront plus ALB | global users and cacheable content | purely internal services
ALB with WAF only | one Region, mostly dynamic | heavy static assets
API Gateway | managed API features such as keys and throttling | you already have an ALB doing routing
@check
How do you make sure traffic cannot skip CloudFront? || Allow only the CloudFront origin-facing prefix list (and a secret header) on the origin.
@end
