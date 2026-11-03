---
title: Deployment strategies and progressive delivery
minutes: 55
objectives:
  - Choose between rolling, blue-green and canary releases for a given risk level
  - Run canaries with Argo Rollouts or Flagger using metric analysis
  - Handle feature flags, database migrations and rollbacks safely
---
How you swap the old version for the new one decides how many users see a bad release and how fast you can recover.

@concept Rolling updates
@plain
A Kubernetes Deployment replaces pods gradually. New pods start, pass readiness, and then old pods are removed, so the service stays available.
@problem
Stopping everything and starting the new version causes downtime. You need an update that keeps capacity while it changes.
@does
- `maxSurge` is how many extra pods may exist during the update. `maxUnavailable` is how many may be missing.
- Readiness probes decide when a new pod receives traffic. Without them, traffic reaches pods that are not ready.
- `kubectl rollout undo` reverts to the previous ReplicaSet. `minReadySeconds` and `progressDeadlineSeconds` add safety.
- Both versions run at the same time, so the change must be backward compatible.
@diagram flow
caption: Pods replaced step by step
numbered: true
nodes:
  - "3 old pods|v1 serving|app"
  - "Surge 1 new pod|v2 starting|info"
  - "v2 ready|old pod removed|ok"
  - "All v2|rollout complete|ok"
@h Strategy and probe
```yaml title="deployment.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shop
  namespace: shop
spec:
  replicas: 4
  minReadySeconds: 10
  progressDeadlineSeconds: 300
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels: {app: shop}
  template:
    metadata:
      labels: {app: shop}
    spec:
      containers:
        - name: shop
          image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop@sha256:4f3a9c1d2b7e8a0c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4
          ports: [{containerPort: 8080}]
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
            periodSeconds: 5
```
```bash title="Watch and revert" lab
kubectl -n shop rollout status deploy/shop --timeout=5m
kubectl -n shop rollout undo deploy/shop
```
@check
Which setting keeps full capacity during an update? || maxUnavailable set to 0, with maxSurge at least 1.
@end

@concept Blue-green deployments
@plain
Run two complete environments: blue is live, green has the new version. When green passes checks, switch traffic to it in one step. Blue stays for instant rollback.
@problem
A rolling update mixes versions and rolling back means another rollout. Some changes need a clean cutover with a quick return path.
@does
- The switch is a Service selector change, an Ingress or load balancer target group change, or a weighted rule.
- You can test green through a preview Service before the switch.
- It costs double capacity for a while. State and database changes still need compatibility between versions.
@diagram flow
caption: Switching the service from blue to green
nodes:
  - "Users|traffic|plain"
  - "Service|selector decides|cp"
  - "Blue v1|live|app"
  - "Green v2|tested, idle|info"
@h Switching by selector
```bash title="Cut over and cut back" lab
kubectl -n shop patch svc shop -p '{"spec":{"selector":{"app":"shop","track":"green"}}}'
# problem found, revert in seconds
kubectl -n shop patch svc shop -p '{"spec":{"selector":{"app":"shop","track":"blue"}}}'
```
@check
What is the main advantage over rolling updates? || Instant, clean cutover and rollback with no mixed versions serving at once.
@end

@concept Canary releases
@plain
A canary sends a small share of traffic, for example 5 percent, to the new version, watches metrics, and increases the share only if the version behaves well.
@problem
Staging cannot reproduce production traffic. A bug found by 5 percent of users is far cheaper than one found by all of them.
@does
- Steps raise weight in stages (5, 25, 50, 100) with pauses.
- Automated analysis compares metrics such as error rate and latency to thresholds. Failure aborts and returns traffic to the stable version.
- Traffic splitting needs support from an ingress controller, service mesh or Gateway API. Without it, weight is approximated by pod ratio.
@diagram flow
caption: Growing the canary
numbered: true
nodes:
  - "5 percent|analysis passes|warn"
  - "25 percent|analysis passes|warn"
  - "50 percent|analysis passes|info"
  - "100 percent|promoted|ok"
@h Compare error rates by version
```text title="PromQL, labels depend on your instrumentation"
sum by (version) (rate(http_requests_total{app="shop",code=~"5.."}[5m]))
  / sum by (version) (rate(http_requests_total{app="shop"}[5m]))
```
:::note
Canary gates are only as good as the metrics they read. Define the success metrics before you automate.
:::
@end

@concept Argo Rollouts
@plain
Argo Rollouts adds a `Rollout` resource, a replacement for Deployment, with built-in canary and blue-green strategies, traffic routing and automated analysis.
@problem
A plain Deployment cannot do weighted traffic steps, pauses, or metric-based abort.
@does
- `strategy.canary.steps` lists `setWeight`, `pause` and `analysis` steps.
- `trafficRouting` integrates with NGINX, ALB, Istio, Linkerd and Gateway API. Without it, weights are approximated by replica counts.
- `AnalysisTemplate` queries Prometheus and other providers. Failure causes automatic rollback.
- `kubectl argo rollouts promote` continues a paused rollout and `abort` stops one.
@diagram flow
caption: Rollout with analysis
nodes:
  - "setWeight 10|first step|warn"
  - "pause 2m|let traffic flow|plain"
  - "analysis|Prometheus query|info"
  - "setWeight 50 then 100|promote|ok"
@h Rollout and analysis
```yaml title="rollout.yaml"
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: shop
  namespace: shop
spec:
  replicas: 5
  selector:
    matchLabels: {app: shop}
  template:
    metadata:
      labels: {app: shop}
    spec:
      containers:
        - name: shop
          image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:1.5.0
          ports: [{containerPort: 8080}]
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: {duration: 2m}
        - analysis:
            templates:
              - templateName: success-rate
        - setWeight: 50
        - pause: {duration: 5m}
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate
  namespace: shop
spec:
  metrics:
    - name: success-rate
      interval: 1m
      count: 3
      failureLimit: 1
      successCondition: result[0] >= 0.99
      provider:
        prometheus:
          address: http://prometheus.monitoring.svc:9090
          query: |
            sum(rate(http_requests_total{app="shop",code!~"5.."}[2m]))
            / sum(rate(http_requests_total{app="shop"}[2m]))
```
```bash title="Operate" lab
kubectl argo rollouts get rollout shop -n shop --watch
kubectl argo rollouts promote shop -n shop
kubectl argo rollouts abort shop -n shop
```
@check
What happens if the analysis fails? || The rollout aborts and traffic goes back to the stable version.
@end

@concept Flagger
@plain
Flagger is a progressive delivery operator from the Flux project. You keep your normal Deployment and add a `Canary` resource. Flagger creates the primary and canary copies and moves traffic by calling your mesh or ingress.
@problem
You want canary automation without replacing Deployments with a new kind, and with integration into Flux workflows.
@does
- Supports Istio, Linkerd, NGINX, Contour, Gateway API, App Mesh and others. Check the current docs for the provider list.
- `analysis` defines interval, threshold, step weight and metrics (built-in request success rate and duration, or custom Prometheus queries).
- Webhooks can run load tests or smoke tests during the analysis.
- Failure after the threshold rolls back automatically.
@diagram flow
caption: Flagger flow
nodes:
  - "Deployment updated|new image|app"
  - "Flagger|creates canary, shifts weight|cp"
  - "Metrics check|success rate and latency|info"
  - "Promote or rollback|primary updated|ok"
@h Canary resource
```yaml title="canary.yaml"
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: shop
  namespace: shop
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: shop
  service:
    port: 8080
  analysis:
    interval: 1m
    threshold: 5
    maxWeight: 50
    stepWeight: 10
    metrics:
      - name: request-success-rate
        thresholdRange:
          min: 99
        interval: 1m
      - name: request-duration
        thresholdRange:
          max: 500
        interval: 1m
```
@check
Which object do you keep with Flagger that Argo Rollouts replaces? || The normal Deployment. Flagger wraps it, while Argo Rollouts replaces it with a Rollout.
@end

@concept Feature flags
@plain
A feature flag is a runtime switch that turns code on or off without a deploy. It separates deploying code from releasing a feature.
@problem
Unfinished features block trunk-based development, and a bad feature needs a redeploy to remove.
@does
- Flags enable dark launches, gradual percentage rollouts, targeting by user group, and instant kill switches.
- OpenFeature is a vendor-neutral API. Providers include LaunchDarkly, Unleash, flagd, Flagsmith and others.
- Treat flags as debt: give each an owner and an expiry, and delete the code path after full rollout.
- Complement rather than replace canaries. A canary checks the build, a flag checks the feature.
@diagram cmp
caption: What each tool controls
cards:
  - {h: "Canary", kind: info, items: ["Which build gets traffic", "Infrastructure level", "Rollback by weight"]}
  - {h: "Feature flag", kind: app, items: ["Which feature is active", "Application level", "Rollback by switch"]}
@h Flag in code
```python title="OpenFeature style check" lab
# pip install openfeature-sdk ; a provider must be configured at startup
from openfeature import api

client = api.get_client()
if client.get_boolean_value("new-checkout", False):
    print("new checkout flow")
else:
    print("old checkout flow")
```
:::warn
Test both flag states. Stale flags and untested combinations cause outages that are hard to reproduce.
:::
@end

@concept Database migrations
@plain
Schema changes must work with both the old and new application version, because during any rollout both run at once. The safe method is **expand and contract**.
@problem
Renaming a column while the old pods still read it breaks them. A rollback of the app cannot undo a destructive schema change.
@does
- **Expand**: add the new column or table, nullable, with no removal. Deploy code that writes both and reads the new one safely.
- **Migrate**: backfill data in batches.
- **Contract**: remove old columns in a later release, after no version uses them.
- Run migrations as a separate step (a Job, Argo CD PreSync hook, or Helm hook), not on app startup in every replica.
- Use tools such as Flyway, Liquibase, Alembic or golang-migrate, and test migrations against a copy of production data.
@diagram flow
caption: Expand and contract across releases
numbered: true
nodes:
  - "Release 1|add new column nullable|info"
  - "Release 2|write both, read new|app"
  - "Backfill|batches in background|warn"
  - "Release 3|drop old column|ok"
@h Migration job
```yaml title="Migration Job run before the rollout"
apiVersion: batch/v1
kind: Job
metadata:
  name: shop-migrate-150
  namespace: shop
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop-migrate:1.5.0
          args: ["up"]
          envFrom:
            - secretRef: {name: shop-db}
```
@check
Why not drop a column in the same release that stops using it? || During and after rollback the old version still runs and needs the column.
@end

@concept Rollbacks and automatic recovery
@plain
Rollback means returning to the last known good version quickly. In GitOps, that is a revert commit. With progressive delivery, it can be automatic.
@problem
Slow, manual rollback extends outages, and rollback plans written during an incident are error prone.
@does
- Deployment history: `kubectl rollout undo`. Helm: `helm rollback`. Argo Rollouts: abort. All keep the previous ReplicaSet or revision.
- GitOps: `git revert` the change, so Git stays the truth. Avoid `argocd app rollback` as the only fix, as auto-sync will fight it.
- Define the rollback trigger in advance: error rate, latency, failed health check, or failed smoke test.
- Practise it. Rollback of schema or data changes needs a separate plan.
@diagram seq
caption: Automatic rollback from a failed canary
actors: ["Rollout|controller|cp", "Metrics|Prometheus|ext", "Traffic|users|plain"]
steps:
  - "0>1: query error rate | req"
  - "1>0: above threshold | resp"
  - "note 0..0: abort rollout"
  - "0>2: all traffic to stable | req"
@h Revert paths
```bash title="Three ways back" lab
kubectl -n shop rollout undo deploy/shop            # plain Deployment
helm -n shop rollback shop 12                       # Helm revision number
git revert --no-edit HEAD && git push               # GitOps: let the controller apply it
```
@end
