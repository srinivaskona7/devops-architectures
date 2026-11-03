---
title: CloudFront deep dive
minutes: 55
objectives:
  - Configure distributions, origins, behaviors and cache policies
  - Secure origins with Origin Access Control, signed URLs and WAF
  - Use CloudFront Functions and Lambda@Edge and troubleshoot cache hit ratio
---
CloudFront is a global content delivery network. Correct cache keys and secure origins make the difference between a fast, cheap site and an expensive one.

@concept Distributions, origins and behaviors
@plain
A **distribution** has one or more **origins** (S3, ALB, custom HTTP) and **behaviors** that map URL path patterns to an origin and cache settings.
@problem
Users far from the origin see latency, and the origin carries every request.
@does
- Edge locations cache responses; regional edge caches add a second tier.
- Default behavior `*` plus path behaviors such as `/api/*` and `/static/*`.
- Viewer protocol policy (redirect to HTTPS), allowed methods, compression, HTTP/2 and HTTP/3.
- Custom domain needs an ACM certificate in us-east-1.
@diagram flow
caption: Request path
nodes:
  - "Viewer|nearest edge|ext"
  - "Edge cache|hit returns here|cp"
  - "Regional cache|second tier|info"
  - "Origin|S3 or ALB|app"
@h Terraform sketch
```hcl title="cf.tf"
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
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn = aws_acm_certificate.site.arn
    ssl_support_method  = "sni-only"
  }
}
```
:::note
The cache policy ID above is the AWS managed CachingOptimized policy; check the current ID in the console or documentation.
:::
@check
In which Region must a CloudFront ACM certificate live? || us-east-1.
@end

@concept Cache keys, TTLs and invalidation
@plain
The **cache key** decides which requests share one cached object. TTLs decide how long it lives.
@problem
A cache key that includes needless headers or query strings fragments the cache and the hit ratio collapses.
@does
- Cache policies choose which headers, cookies and query strings are in the key and set min, default and max TTL.
- Origin request policies forward values to the origin without adding them to the key.
- Respect origin `Cache-Control`; for static assets use content-hashed filenames and long TTLs.
- Invalidation (`/*`) removes objects; paths are billed after a free monthly allowance (check current terms). Prefer versioned file names.
- Hit ratio example: 900 hits out of 1,000 requests is 90 percent.
@diagram cmp
caption: Cache key discipline
cards:
  - {h: "Tight key", kind: ok, items: ["Only needed query strings", "No cookies for static", "High hit ratio"]}
  - {h: "Loose key", kind: bad, items: ["All headers", "All cookies", "Low hit ratio and high origin load"]}
@h Invalidate
```bash title="Invalidate a path" nocheck
aws cloudfront create-invalidation --distribution-id E1ABCDEF12345 --paths "/index.html" "/config.json"
```
@check
Better than invalidating on every deploy? || Content-hashed file names with long TTLs.
@end

@concept Securing origins
@plain
**Origin Access Control (OAC)** lets only CloudFront read a private S3 bucket. For ALB origins, restrict by secret header or managed prefix list.
@problem
If the origin is reachable directly, users bypass WAF, caching and geo rules.
@does
- S3: bucket policy allows `cloudfront.amazonaws.com` with condition `AWS:SourceArn` equal to the distribution.
- ALB: security group allows the AWS-managed CloudFront origin-facing prefix list; add a custom header check for stronger assurance.
- VPC origins let CloudFront reach private ALBs or EC2 without public IPs; check current support.
- HTTPS between CloudFront and origin with a valid certificate.
@diagram flow
caption: Private bucket
nodes:
  - "Viewer|HTTPS|ext"
  - "CloudFront|OAC signs request|cp"
  - "S3 bucket|public access blocked|ok"
@h Bucket policy for OAC
```json title="oac-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "cloudfront.amazonaws.com"},
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::example-site/*",
    "Condition": {"StringEquals": {"AWS:SourceArn": "arn:aws:cloudfront::111122223333:distribution/E1ABCDEF12345"}}
  }]
}
```
@check
How does an S3 policy bind access to one distribution? || A condition on AWS:SourceArn.
@end

@concept Signed URLs, cookies and WAF
@plain
**Signed URLs and cookies** restrict who may fetch content. **AWS WAF** filters malicious requests at the edge.
@problem
Paid or private content must not be shareable by anyone with the URL, and bots can hammer your origin.
@does
- Use **key groups** with public keys (not the old account-level trusted signers); sign with the private key in your app.
- Policies include expiry, IP range, and path.
- WAF web ACL with managed rules, rate-based rules and geo or bot control attaches to the distribution (global scope).
- Security headers via response headers policies.
@diagram layers
caption: Edge protection
layers:
  - {label: "Filter", nodes: ["WAF|managed and rate rules|bad"]}
  - {label: "Authorise", nodes: ["Signed URL or cookie|key group|warn"]}
  - {label: "Serve", nodes: ["Edge cache|content|ok"]}
@h Attach WAF
```hcl title="cf-waf.tf"
resource "aws_wafv2_web_acl" "edge" {
  name  = "edge"
  scope = "CLOUDFRONT"
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
        limit              = 2000
        aggregate_key_type = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "rate"
      sampled_requests_enabled   = true
    }
  }
  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "edge"
    sampled_requests_enabled   = true
  }
}
```
@end

@concept Edge compute with Functions and Lambda@Edge
@plain
Run small code at the edge. **CloudFront Functions** are tiny JavaScript for viewer events. **Lambda@Edge** is full Lambda for viewer and origin events.
@problem
URL rewrites, redirects, header edits and simple auth should not need a trip to the origin.
@does
- CloudFront Functions: sub-millisecond, viewer request and response only, no network access, tiny size limits; ideal for rewrites and header manipulation.
- Lambda@Edge: origin events too, network calls, larger code; deployed from us-east-1, higher cost and latency.
- CloudFront KeyValueStore lets functions read small config data.
- Test with the built-in test events.
@diagram cmp
caption: Edge code options
cards:
  - {h: "CloudFront Functions", kind: ok, items: ["Viewer events", "Very cheap and fast", "No network"]}
  - {h: "Lambda@Edge", kind: cp, items: ["Viewer and origin events", "Network access", "More power and cost"]}
@h SPA rewrite function
```javascript title="rewrite.js" nocheck
function handler(event) {
  var request = event.request;
  if (!request.uri.includes('.')) {
    request.uri = '/index.html';
  }
  return request;
}
```
@check
Which option can call an external API? || Lambda@Edge, not CloudFront Functions.
@end

@concept Origin failover and performance
@plain
Origin groups fail over to a secondary origin on selected status codes. Compression, HTTP/3 and Origin Shield improve performance.
@problem
A failing origin returns errors to every user, and many edge locations hitting one origin raises load.
@does
- **Origin group**: primary and secondary origin, failover on 500, 502, 503, 504 (for GET, HEAD, OPTIONS).
- **Origin Shield** adds a central cache layer in one chosen Region to collapse requests; extra cost, enable for expensive origins.
- Brotli and gzip compression, connection keep-alive timeouts, and custom error pages with error caching TTL.
- Continuous deployment lets you send a share of traffic to a staging distribution.
@diagram flow
caption: Failover
nodes:
  - "CloudFront|origin group|cp"
  - "Primary origin|returns 503|bad"
  - "Secondary origin|S3 static copy|ok"
@h Real-time check
```bash title="Check headers" lab
curl -sI https://www.example.com/app.js | grep -iE 'x-cache|age|via|cache-control'
```
@check
What header shows a cache hit? || X-Cache: Hit from cloudfront.
@end

@concept Logging, cost and troubleshooting
@plain
Standard logs, real-time logs and CloudWatch metrics show hit ratio, errors and bytes.
@problem
Low hit ratios and surprise transfer bills are usually discovered late.
@does
- Standard access logs to S3; real-time logs to Kinesis for immediate analysis; additional metrics for cache hit rate and origin latency.
- Costs: data transfer out per GB by price class, requests per 10,000, invalidations, functions, WAF, logging. Price classes limit which edge locations serve you; check current definitions.
- Egress example: 10 TB per month at a rate of R per GB costs 10,000 x R; compute with the current tiered rate.
- 403 from S3 origin: policy or OAC mismatch. 502/504: origin TLS or timeout. Stale content: TTL or cache key.
@diagram flow
caption: Debug order
numbered: true
nodes:
  - "Check headers|X-Cache and Age|info"
  - "Check behavior|path pattern|app"
  - "Check origin|policy, TLS, timeout|warn"
  - "Check cache key|headers and query strings|cp"
@h Metrics alarm
```hcl title="cf-alarm.tf"
resource "aws_cloudwatch_metric_alarm" "errors" {
  provider            = aws.us_east_1
  alarm_name          = "cf-5xx"
  namespace           = "AWS/CloudFront"
  metric_name         = "5xxErrorRate"
  dimensions          = { DistributionId = "E1ABCDEF12345", Region = "Global" }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 2
  threshold           = 5
  comparison_operator = "GreaterThanThreshold"
}
```
@end
