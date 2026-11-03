---
title: Pod autoscaling with HPA, VPA and KEDA
minutes: 50
objectives:
  - Compute HPA replicas from the formula and configure behaviour
  - Choose between HPA, VPA and KEDA for a workload
  - Scale on custom, external and event metrics
---
Autoscaling adds copies of a Pod (horizontal) or resizes it (vertical). Each has rules that cause surprises if ignored.
 
@concept Metrics for autoscaling
@plain
Autoscalers read metrics through three APIs: resource metrics from metrics-server, custom metrics about Kubernetes objects, and external metrics from outside the cluster.
@problem
Scaling on CPU only misses queue depth, request rate or latency, which are often better signals.
@does
- `metrics.k8s.io`: CPU and memory per Pod, served by **metrics-server** (also powers `kubectl top`).
- `custom.metrics.k8s.io`: per-object metrics, provided by an adapter such as Prometheus Adapter.
- `external.metrics.k8s.io`: values like SQS length or Kafka lag, provided by an adapter such as KEDA.
- Without metrics-server, HPA shows `<unknown>` for targets.
@diagram layers
caption: Metric sources
layers:
  - {label: "Autoscalers", nodes: ["HPA|replicas|app", "VPA|requests|app"]}
  - {label: "Metric APIs", nodes: ["metrics.k8s.io|CPU and memory|cp", "custom.metrics.k8s.io|per object|cp", "external.metrics.k8s.io|outside systems|cp"]}
  - {label: "Providers", nodes: ["metrics-server|kubelet data|info", "Prometheus Adapter|PromQL|info", "KEDA|scalers|info"]}
@h Check metrics
```bash title="Is metrics-server healthy" lab
kubectl get apiservices | grep metrics
kubectl top nodes
kubectl top pods -n shop --sort-by=cpu
kubectl get --raw "/apis/metrics.k8s.io/v1beta1/namespaces/shop/pods" | head -c 300
```
@end

@concept The Horizontal Pod Autoscaler
@plain
The HPA changes `replicas` of a Deployment or StatefulSet to keep a metric near a target.
@problem
Load varies, and fixed replica counts are either wasteful or too small for peaks.
@does
- Formula: `desired = ceil(current replicas x current metric / target metric)`. Example: 4 replicas at 90% CPU with target 60% gives ceil(4 x 90/60) = 6.
- CPU utilisation is relative to the **request**, so missing requests break HPA.
- It evaluates every 15 s by default, ignores a 10% tolerance band, and uses the highest result when several metrics are given.
- Do not set `replicas` in Git for an HPA-managed workload.
- Not for scale to zero (HPA minimum is 1 unless the alpha HPAScaleToZero feature gate is enabled).
@diagram flow
caption: The HPA loop
nodes:
  - "Read metrics|every 15 s|info"
  - "Compute desired|formula|cp"
  - "Apply behaviour|stabilisation, rate|warn"
  - "Scale Deployment|set replicas|ok"
@h Compute the formula
```python title="HPA replica calculation" lab
import math
def desired(current, metric, target, tolerance=0.1):
    ratio = metric / target
    return current if abs(ratio - 1) <= tolerance else math.ceil(current * ratio)
print(desired(4, 90, 60))   # scale up
print(desired(6, 62, 60))   # inside tolerance
print(desired(10, 20, 60))  # scale down
```
@check
Why does HPA need CPU requests on the Pods? || Utilisation is measured as a percentage of the request; without one there is nothing to compare against.
@end

@concept HPA behaviour and a full manifest
@plain
The `behavior` section controls how fast the HPA may scale up or down and how long it waits before scaling down.
@problem
Without limits, noisy metrics cause flapping and aggressive scale-down removes capacity before load truly drops.
@does
- `scaleUp` and `scaleDown` each have `policies` (Pods or Percent per period) and `stabilizationWindowSeconds`.
- Defaults: scale down waits 300 s using the highest recommendation in the window; scale up has no window and can double or add 4 Pods per 15 s.
- `selectPolicy: Max | Min | Disabled`.
- Multiple metrics (CPU, memory, custom) are allowed.
@diagram cmp
caption: Typical tuning
cards:
  - {h: "Scale up", kind: ok, items: ["Fast, allow doubling", "Short window"]}
  - {h: "Scale down", kind: warn, items: ["Slow, 10 percent per minute", "5 to 15 min window"]}
@h HPA v2
```yaml title="hpa.yaml"
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 30
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: {type: Utilization, averageUtilization: 60}
    - type: Pods
      pods:
        metric: {name: http_requests_per_second}
        target: {type: AverageValue, averageValue: "100"}
  behavior:
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - {type: Percent, value: 100, periodSeconds: 15}
    scaleDown:
      stabilizationWindowSeconds: 600
      policies:
        - {type: Percent, value: 10, periodSeconds: 60}
```
@end

@concept Vertical Pod Autoscaler
@plain
The VPA watches real usage and recommends, or applies, better CPU and memory requests for a workload.
@problem
Developers guess requests wrongly, and usage drifts with each release.
@does
- Components: recommender, updater and admission controller.
- `updateMode`: `Off` (recommendations only), `Initial` (set at Pod creation), `Recreate` or `Auto` (evict and recreate with new values; newer versions can resize in place).
- Do not use VPA and HPA on the same CPU or memory metric; HPA on custom metrics plus VPA is fine.
- Start with `Off` and use the output to set requests in Git.
- It is an add-on, not part of core Kubernetes; EKS and Gardener offer it as an add-on or extension.
@diagram flow
caption: VPA recommendation path
nodes:
  - "Usage history|metrics|info"
  - "Recommender|target, lower, upper|cp"
  - "Updater or admission|apply on recreate|warn"
  - "New requests|right-sized Pod|ok"
@h Recommendation only
```yaml title="vpa.yaml"
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: api
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  updatePolicy:
    updateMode: "Off"
  resourcePolicy:
    containerPolicies:
      - containerName: "*"
        minAllowed: {cpu: 50m, memory: 64Mi}
        maxAllowed: {cpu: "2", memory: 4Gi}
```
```bash title="Read the advice" lab
kubectl describe vpa api | sed -n '/Recommendation/,$p'
```
@end

@concept KEDA, event-driven scaling
@plain
KEDA scales workloads on events such as queue length, Kafka lag, cron schedules or Prometheus queries, including down to zero.
@problem
HPA alone cannot scale to zero or read most external systems directly.
@does
- A `ScaledObject` references a Deployment and one or more **triggers**; KEDA creates and manages an HPA for 1..N and handles 0<->1 itself.
- `ScaledJob` creates Jobs per event batch for long tasks.
- 60+ scalers: AWS SQS, Kafka, RabbitMQ, Prometheus, Cron, HTTP (add-on).
- `TriggerAuthentication` references credentials or pod identity so secrets stay out of triggers.
- Used for workers where idle cost should be nil, and for burst processing.
@diagram flow
caption: KEDA with SQS
nodes:
  - "SQS queue|messages waiting|ext"
  - "KEDA|polls and decides|cp"
  - "HPA|1 to N|info"
  - "Workers|Deployment|app"
@h Scale on queue length
```yaml title="scaledobject.yaml"
apiVersion: keda.sh/v1alpha1
kind: TriggerAuthentication
metadata:
  name: aws-pod-identity
  namespace: shop
spec:
  podIdentity:
    provider: aws
---
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: worker
  namespace: shop
spec:
  scaleTargetRef:
    name: worker
  minReplicaCount: 0
  maxReplicaCount: 50
  cooldownPeriod: 300
  triggers:
    - type: aws-sqs-queue
      authenticationRef:
        name: aws-pod-identity
      metadata:
        queueURL: https://sqs.eu-west-1.amazonaws.com/111122223333/orders
        queueLength: "20"
        awsRegion: eu-west-1
```
@choose Pod autoscaler
HPA | CPU or request-rate scaling of web services | you need scale to zero or external queues
KEDA | queues, streams, schedules, scale to zero | plain CPU scaling is enough
VPA (Off mode) | finding correct requests | you want it to restart Pods during peak hours
@end

@concept Autoscaling pitfalls
@plain
Most autoscaling incidents come from slow starts, missing limits on dependencies or fighting controllers.
@problem
Autoscalers react after load arrives; slow Pod startup means users already felt the spike.
@does
- Readiness delay: new Pods take time to be ready, so keep a `minReplicas` buffer for the typical spike.
- Scaling a stateless tier can overload the database; cap `maxReplicas` or use connection pooling.
- Metrics lag (scrape interval, 15 s HPA loop) adds delay of up to a minute.
- Pending Pods from HPA need the **Cluster Autoscaler or Karpenter** to add nodes, adding minutes more.
- Pre-warm with `minReplicas`, small image sizes, `startupProbe` tuned, and overprovisioning Pods (low-priority placeholders).
@diagram flow
caption: Why scale-up takes minutes
numbered: true
nodes:
  - "Load rises|metric lags|warn"
  - "HPA adds Pods|15 s loop|info"
  - "Pods Pending|no room|warn"
  - "Node provisioned|1 to 3 min|bad"
  - "Image pulled and ready|probe|ok"
@h Watch an HPA
```bash title="HPA diagnostics" lab
kubectl get hpa api -w
kubectl describe hpa api | sed -n '/Conditions/,$p'
kubectl get events --field-selector involvedObject.kind=HorizontalPodAutoscaler
```
@end
