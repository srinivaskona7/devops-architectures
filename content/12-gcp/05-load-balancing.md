---
title: Cloud Load Balancing and Cloud CDN
minutes: 55
objectives:
  - Pick the right Google Cloud load balancer for a traffic type and scope
  - Build a global external Application Load Balancer from its component objects
  - Use health checks, managed certificates, URL maps and Cloud CDN
---
Google Cloud has one load balancing family with many modes. The names reflect scope (global or regional), exposure (external or internal) and layer (application or network).
@concept The load balancer family
@plain
You choose a load balancer by the traffic it carries (HTTP or TCP), by whether clients are outside or inside, and by whether it is global or regional.
@problem
There are many modes and the console wizard hides how they differ, so people pick the wrong one.
@does
- **Global external Application LB**: HTTP(S), one anycast IP worldwide, the default for public sites.
- **Regional external Application LB**: HTTP(S) in one region, for data residency or Standard network tier.
- **Internal Application LB** (regional, or cross-region): HTTP(S) for private services inside the VPC.
- **External passthrough Network LB**: TCP or UDP, preserves client IP, regional.
- **Internal passthrough Network LB**: private TCP or UDP in a region.
- **Proxy Network LB**: TCP with TLS offload, global or regional.
- **AWS equivalent**: ALB, NLB, and Global Accelerator in front. Main difference: the global Application LB gives anycast and a global backend pool with no extra service.
@diagram cmp
caption: Choose by layer and scope
cards:
  - {h: "Application LB", kind: app, items: ["HTTP(S), gRPC", "Global or regional", "External or internal", "Cloud Armor, CDN"]}
  - {h: "Proxy Network LB", kind: info, items: ["TCP with TLS offload", "Global or regional", "Terminates the connection"]}
  - {h: "Passthrough Network LB", kind: cp, items: ["TCP and UDP", "Regional", "Keeps client IP"]}
@choose Choosing a mode
Global external Application LB | public web and APIs with users in many places | traffic is not HTTP or you must keep traffic in one region
Regional external Application LB | residency limits or a single region | you need a single global anycast address
Internal Application LB | private microservices with L7 routing | clients come from the internet
Passthrough Network LB | UDP, non-HTTP and client IP preservation | you need L7 routing or TLS offload
@end

@concept Anatomy of a global external Application LB
@plain
The load balancer is not one object. It is a chain: forwarding rule, target proxy, URL map, backend service, and health check, plus backends.
@problem
Terraform and gcloud need every part, and a missing link gives a confusing failure.
@does
- **Forwarding rule**: IP address and port, the entry point.
- **Target HTTPS proxy**: terminates TLS using certificates and an SSL policy.
- **URL map**: host and path rules to backend services or buckets.
- **Backend service**: protocol, health check, balancing mode, Cloud Armor and CDN settings.
- **Backends**: instance groups, NEGs (zonal for Pods, serverless for Cloud Run, internet NEGs), or Cloud Storage buckets.
- **AWS equivalent**: listener, rules and target groups of an ALB. Main difference: these are separate, reusable objects.
@diagram flow
caption: Object chain
nodes:
  - "Forwarding rule|IP and 443|cp"
  - "Target proxy|TLS and certs|info"
  - "URL map|host and path|info"
  - "Backend service|health and policy|app"
  - "NEG or MIG|endpoints|app"
@h Build it with gcloud
```bash title="External Application LB" lab
gcloud compute health-checks create http shop-hc --port=8080 --request-path=/healthz
gcloud compute backend-services create shop-api-bes --global --protocol=HTTP --health-checks=shop-hc \
  --load-balancing-scheme=EXTERNAL_MANAGED
gcloud compute url-maps create shop-map --default-service=shop-api-bes
gcloud compute target-https-proxies create shop-proxy --url-map=shop-map --ssl-certificates=shop-cert
gcloud compute forwarding-rules create shop-fr --global --target-https-proxy=shop-proxy \
  --ports=443 --address=shop-ip --load-balancing-scheme=EXTERNAL_MANAGED
```
@check
Which object holds host and path routing rules? || The URL map.
@end

@concept Backends and NEGs
@plain
A backend can be a managed instance group or a **network endpoint group (NEG)**, which lists IP and port endpoints directly.
@problem
Sending traffic to a node and then through kube-proxy adds a hop and uneven balancing.
@does
- **Zonal NEG** with container-native load balancing sends traffic straight to Pod IPs. GKE manages it with the `cloud.google.com/neg` annotation or the Gateway controller.
- **Serverless NEG** points to Cloud Run, Cloud Run functions or App Engine.
- **Internet NEG** points at an external FQDN or IP, and **hybrid NEG** at on-premises endpoints.
- Balancing mode: utilization, rate or connection, with capacity scalers for draining.
- **AWS equivalent**: target groups of type ip, lambda. Main difference: a NEG is a resource you can attach to several backend services.
@diagram layers
caption: Backend types
layers:
  - {label: "Backend service", nodes: ["Health check and policy|one per service|cp"]}
  - {label: "Backend", nodes: ["Instance group|VMs|vm", "Zonal NEG|Pod IPs|app", "Serverless NEG|Cloud Run|app", "Hybrid NEG|on-premises|ext"]}
@h Serverless NEG
```bash title="Cloud Run behind the LB" lab
gcloud compute network-endpoint-groups create shop-web-neg --region=europe-west1 \
  --network-endpoint-type=serverless --cloud-run-service=shop-web
gcloud compute backend-services add-backend shop-web-bes --global \
  --network-endpoint-group=shop-web-neg --network-endpoint-group-region=europe-west1
```
@end

@concept Health checks
@plain
Health checks probe backends. Unhealthy ones stop receiving new connections.
@problem
Without a check, the load balancer sends traffic to crashed or starting instances.
@does
- Protocols: HTTP, HTTPS, HTTP/2, TCP, SSL and gRPC. Set `--request-path`, interval, timeout, healthy and unhealthy thresholds.
- Probes come from Google ranges, so your firewall must allow `130.211.0.0/22` and `35.191.0.0/16`, and for some modes other ranges (check the docs).
- On GKE, a BackendConfig or HealthCheckPolicy can configure the check; by default it derives from the readiness probe path in some cases, so set it explicitly.
- **AWS equivalent**: target group health checks. Main difference: a health check is a separate resource reusable by several backend services.
@diagram flow
caption: Probe path
nodes:
  - "Google prober|from fixed ranges|cp"
  - "Firewall|must allow range|warn"
  - "Backend /healthz|returns 200|app"
  - "Pool state|healthy or not|ok"
@h Tune
```bash title="Health check settings" lab
gcloud compute health-checks update http shop-hc --check-interval=5s --timeout=5s \
  --healthy-threshold=2 --unhealthy-threshold=3
gcloud compute backend-services get-health shop-api-bes --global
```
@check
A new LB shows all backends unhealthy though pods are fine. What is the first thing to check? || The firewall rule for the health check source ranges.
@end

@concept TLS certificates and SSL policies
@plain
Certificates attach to the target HTTPS proxy. Google can issue and renew them for you.
@problem
Expired certificates cause outages.
@does
- **Google-managed certificates** require DNS to point to the load balancer IP (classic) or a DNS authorization record (certificate manager). Issuance can take a while.
- **Certificate Manager** supports wildcard certs through DNS authorization and certificate maps.
- Self-managed certificates are uploaded and you renew them.
- An **SSL policy** sets minimum TLS version and cipher profile.
- **AWS equivalent**: ACM with the ALB listener security policy. Main difference: attach to the proxy, and Certificate Manager scales to many domains.
@diagram flow
caption: Managed certificate
nodes:
  - "Domain DNS|points at LB or auth record|ext"
  - "Certificate Manager|validates domain|cp"
  - "Certificate map|attached to proxy|info"
  - "HTTPS clients|TLS 1.2 and above|ok"
@h Create
```bash title="Managed certificate" lab
gcloud certificate-manager dns-authorizations create shop-auth --domain="shop.example.com"
gcloud certificate-manager certificates create shop-cert --domains="shop.example.com" \
  --dns-authorizations=shop-auth
gcloud compute ssl-policies create modern-tls --profile=MODERN --min-tls-version=1.2
```
@end

@concept URL maps, redirects and traffic splitting
@plain
The URL map matches hosts and paths and can rewrite, redirect, split traffic and apply header actions.
@problem
One public address must serve several apps, redirect HTTP to HTTPS, and enable canaries.
@does
- Host rules choose a path matcher. Path rules route `/api/*` to one backend and `/static/*` to a bucket backend.
- Route rules support weighted backend services, header-based matching, URL rewrites and retry policies.
- HTTP to HTTPS redirect uses a second URL map and a forwarding rule on port 80.
- **AWS equivalent**: listener rules with weighted forward. Main difference: it is defined in a URL map document you can import and export as YAML.
@diagram flow
caption: Routing decision
nodes:
  - "Request|shop.example.com/api|plain"
  - "Host rule|shop.example.com|info"
  - "Path matcher|/api/* to api|info"
  - "Backend service|95 percent v1, 5 percent v2|app"
@h URL map YAML
```yaml title="url-map.yaml"
name: shop-map
defaultService: global/backendServices/shop-web-bes
hostRules:
  - hosts: ["shop.example.com"]
    pathMatcher: main
pathMatchers:
  - name: main
    defaultService: global/backendServices/shop-web-bes
    pathRules:
      - paths: ["/api/*"]
        routeAction:
          weightedBackendServices:
            - backendService: global/backendServices/shop-api-bes
              weight: 95
            - backendService: global/backendServices/shop-api-v2-bes
              weight: 5
```
```bash title="Import it" lab
gcloud compute url-maps import shop-map --source=url-map.yaml --global
```
@end

@concept Cloud CDN
@plain
**Cloud CDN** caches content at Google edge locations for backend services and backend buckets behind the global external Application LB.
@problem
Serving static assets from origin wastes latency and bandwidth.
@does
- Enable per backend service or bucket with `--enable-cdn`. Cache modes: `CACHE_ALL_STATIC`, `USE_ORIGIN_HEADERS`, `FORCE_CACHE_ALL`.
- Cache keys can include host, protocol and query strings. Signed URLs and cookies restrict access.
- Invalidate with `gcloud compute url-maps invalidate-cdn-cache`.
- Compressed responses and `Cache-Control` headers from origin decide hit rate.
- **AWS equivalent**: CloudFront. Main difference: Cloud CDN is a feature of the load balancer, not a separate distribution with its own domain.
@diagram flow
caption: Cache hit and miss
nodes:
  - "Client|nearby edge|ext"
  - "Cloud CDN|cache lookup|cp"
  - "Load balancer|on miss|info"
  - "Origin|bucket or service|app"
@h Enable CDN
```bash title="CDN on a backend bucket" lab
gcloud compute backend-buckets create shop-assets-bb --gcs-bucket-name=shop-assets-123 \
  --enable-cdn --cache-mode=CACHE_ALL_STATIC
gcloud compute url-maps invalidate-cdn-cache shop-map --path="/static/*" --global
```
@check
Does Cloud CDN need a separate distribution domain? || No. It is enabled on the load balancer backend.
@end

@concept Internal and passthrough load balancers
@plain
Internal Application LBs route private HTTP traffic. Passthrough Network LBs forward packets without terminating connections.
@problem
Private microservices and non-HTTP protocols still need balancing, and some need client IPs preserved.
@does
- Internal Application LB (regional) uses Envoy proxies in a proxy-only subnet that you must create.
- Passthrough Network LB uses backend services with a regional scope and supports TCP, UDP and others. Return traffic goes directly to the client (direct server return).
- GKE `Service` of type `LoadBalancer` creates a passthrough Network LB by default, and an internal one with the `networking.gke.io/load-balancer-type: "Internal"` annotation.
- **AWS equivalent**: internal ALB and NLB. Main difference: proxy-only subnets are required for the proxy modes.
@diagram flow
caption: Internal L7 path
nodes:
  - "Client in VPC|private IP|app"
  - "Internal ALB|proxy-only subnet|cp"
  - "URL map|routes|info"
  - "Backend|NEG or MIG|app"
@h Proxy-only subnet
```bash title="Required for regional proxy LBs" lab
gcloud compute networks subnets create proxy-only-ew1 --network=shop-net --region=europe-west1 \
  --range=10.10.200.0/23 --purpose=REGIONAL_MANAGED_PROXY --role=ACTIVE
```
@end
