---
title: Reliability, performance, cost and sustainability in the shop
minutes: 50
objectives:
  - Design a three-tier EKS workload that survives instance, pod and AZ failure
  - Scale pods, nodes and data tier with the right signals
  - Apply cost and sustainability levers without hurting reliability
---
Failures are normal: instances die, deployments break, AZs degrade. Reliability is the discipline of making those events boring.

@concept Failure domains and static stability
@plain
A failure domain is the largest thing that fails together: a pod, a node, an AZ, a Region, an account. Static stability means the system keeps working during a failure without needing new capacity or manual action.
@problem
Systems that need to launch new capacity during an AZ outage fail exactly when the control plane and APIs are busiest.
@does
- Run at least three replicas across three AZs with topology spread, so losing one AZ leaves two thirds capacity.
- Over-provision to survive an AZ loss: size each of three zones at 50 percent utilisation or use headroom (pause pods).
- Avoid dependence on the control plane at failure time (for example, pre-provisioned NAT per AZ, pre-created replicas).
- Keep zonal affinity: ALB cross-zone is on, but internal calls prefer same-zone to cut latency and cost.
@diagram flow
caption: Blast radius ladder
nodes:
  - "Pod|restart or reschedule|ok"
  - "Node|replace with Karpenter|info"
  - "AZ|spread and headroom|warn"
  - "Region|DR plan|bad"
@h Spread and headroom
```yaml title="Deployment spread across zones and nodes"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
  namespace: shop
spec:
  replicas: 6
  selector:
    matchLabels:
      app: orders
  template:
    metadata:
      labels:
        app: orders
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: orders
        - maxSkew: 1
          topologyKey: kubernetes.io/hostname
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: orders
      containers:
        - name: orders
          image: nginx:1.27
          resources:
            requests: {cpu: 500m, memory: 512Mi}
            limits: {memory: 512Mi}
```
@check
What does static stability mean? || The workload continues to operate during a failure without launching new capacity or manual intervention.
@end

@concept Health, retries and graceful degradation
@plain
Probes tell Kubernetes what is healthy; timeouts, retries with backoff and circuit breakers stop one failure from spreading.
@problem
A slow dependency without timeouts exhausts threads in every caller and a minor issue becomes a full outage.
@does
- **Readiness** removes a pod from Service endpoints; **liveness** restarts a stuck container; **startup** protects slow starts. Do not put dependency checks in liveness.
- Timeouts on every network call, retries only for idempotent operations, with exponential backoff and jitter, and retry budgets.
- Circuit breakers and bulkheads; degrade features (cached catalog, queued orders) instead of failing whole requests.
- Queues (SQS) decouple order intake from processing; use DLQs for poison messages.
@diagram seq
caption: A retry with backoff and a circuit breaker
actors: ["web|caller|app", "orders|service|cp", "Aurora|database|ext"]
steps:
  - "0>1: request | req"
  - "1>2: query slow | bad"
  - "1>0: 503 after timeout | bad"
  - "note 0..0: backoff with jitter, then retry"
  - "0>1: retry | req"
  - "1>0: cached result | resp"
@h Probes
```yaml title="Probes for a service"
containers:
  - name: orders
    image: nginx:1.27
    startupProbe:
      httpGet: {path: /healthz, port: 8080}
      failureThreshold: 30
      periodSeconds: 2
    readinessProbe:
      httpGet: {path: /ready, port: 8080}
      periodSeconds: 5
    livenessProbe:
      httpGet: {path: /healthz, port: 8080}
      periodSeconds: 10
      failureThreshold: 3
```
@check
Why not check the database in a liveness probe? || A database outage would restart every pod and make the incident worse.
@end

@concept Scaling the tiers
@plain
Scale pods with HPA (or KEDA for event signals), nodes with Karpenter, and data with replicas, caching and capacity settings.
@problem
Traffic changes by hour and by campaign. Static sizing wastes money or fails at peak.
@does
- **HPA** on CPU, memory or custom metrics (requests per second via Prometheus adapter or KEDA).
- **KEDA** scales to zero on SQS queue depth or schedules.
- **Karpenter** adds nodes in about a minute; use low-priority **pause pods** for headroom.
- Aurora readers scale reads (Application Auto Scaling for Aurora replicas); Serverless v2 scales compute.
- ElastiCache and CloudFront offload reads; DynamoDB on-demand absorbs spikes.
@diagram flow
caption: Scaling chain
nodes:
  - "Traffic rises|more requests|plain"
  - "HPA adds pods|seconds|app"
  - "Pending pods|need nodes|warn"
  - "Karpenter adds nodes|about a minute|cp"
  - "Aurora readers or ACUs|data tier|ok"
@h HPA
```yaml title="HPA on CPU with sensible bounds"
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: web
  namespace: shop
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: web
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 60
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
```
@check
What gives headroom while Karpenter launches nodes? || Low-priority pause pods that are evicted when real pods need the space.
@end

@concept Performance efficiency
@plain
Choose the right resource type, measure, and keep reviewing as AWS releases new options.
@problem
Defaults and old instance types drift out of line with the workload.
@does
- Use **Graviton** (arm64) instances for better price-performance where images support it.
- Use CloudFront for static and cacheable content; ElastiCache for hot reads; S3 for media; gp3 volumes with explicit IOPS.
- Set requests from measured usage (VPA recommendations); avoid CPU limits that throttle; keep memory limits equal to requests for predictability.
- Load test before launch with realistic data and track p99, not only averages.
- Use Performance Insights for SQL, X-Ray or OpenTelemetry traces for service latency.
@diagram cmp
caption: Levers by tier
cards:
  - {h: "Edge", kind: info, items: ["CloudFront caching", "HTTP/2 and compression"]}
  - {h: "Compute", kind: app, items: ["Graviton", "Right-sized requests"]}
  - {h: "Data", kind: ok, items: ["Indexes and readers", "Cache-aside with TTL"]}
@h Load test
```bash title="Quick load test against staging" nocheck
# k6, hey, or wrk are common choices
hey -z 60s -c 50 https://staging.shop.example.com/api/products
```
@check
Why track p99 latency rather than the average? || Averages hide the slow tail that real users experience.
@end

@concept Cost and sustainability levers
@plain
Cost and sustainability mostly push the same way: use less, and use it efficiently.
@problem
Idle capacity costs money and energy. Unbounded logs and cross-AZ chatter add hidden spend.
@does
- Right-size and consolidate with Karpenter; use Spot for stateless pools; Graviton for efficiency.
- Scale non-production to zero outside working hours.
- Lifecycle S3 data to cheaper tiers; set log retention; expire old images.
- Reduce data transfer: VPC endpoints, same-zone routing where possible, CloudFront.
- Choose Regions with lower carbon intensity when latency and data residency allow.
- Measure with the Customer Carbon Footprint Tool and cost allocation tags.
@diagram flow
caption: Savings with no reliability loss
nodes:
  - "Right-size|requests from data|info"
  - "Spot for stateless|diversified|app"
  - "Off-hours shutdown|dev and test|warn"
  - "Retention and lifecycle|logs, images, S3|ok"
@h Scale dev to zero overnight
```yaml title="KEDA cron scaler for a dev namespace"
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: web-office-hours
  namespace: shop-dev
spec:
  scaleTargetRef:
    name: web
  minReplicaCount: 0
  maxReplicaCount: 3
  triggers:
    - type: cron
      metadata:
        timezone: Asia/Kolkata
        start: 0 9 * * 1-5
        end: 0 19 * * 1-5
        desiredReplicas: "2"
```
@check
Name one change that cuts both cost and energy use. || Right-sizing or removing idle capacity.
@end

@concept Pillar trade-offs and a review checklist
@plain
Pillars compete: more redundancy raises cost, more controls slow releases. Decide per workload and write it down.
@problem
Unspoken trade-offs become surprises in incidents and bills.
@does
- Tier workloads: tier 0 (payments, login) gets multi-AZ, tested DR, strict change control; tier 2 (internal tools) gets cheaper, simpler designs.
- Record decisions in short architecture decision records (ADRs).
- Revisit decisions at each review or incident.
@diagram layers
caption: Tiering example
layers:
  - {label: "Tier 0", nodes: ["Checkout, login|multi-AZ, warm standby DR|bad"]}
  - {label: "Tier 1", nodes: ["Catalog, search|multi-AZ, backup restore DR|warn"]}
  - {label: "Tier 2", nodes: ["Reports, internal tools|single AZ acceptable|ok"]}
@choose Spend on resilience
Warm standby | revenue loss per minute is high | the app tolerates hours of downtime
Backup and restore | the system is internal or rebuilt easily | RTO is under an hour
@end
