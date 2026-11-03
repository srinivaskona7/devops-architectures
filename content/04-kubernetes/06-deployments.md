---
title: ReplicaSets, Deployments and rollouts
minutes: 45
objectives:
  - Explain how Deployments, ReplicaSets and Pods relate
  - Tune rolling update surge and unavailability and roll back safely
  - Choose between rolling, blue green and canary releases
---
Deployments are the default way to run stateless apps. Understanding the ReplicaSet underneath makes rollouts, rollbacks and stuck deployments readable.

@concept ReplicaSets
@plain
A ReplicaSet keeps a fixed number of identical Pods running. If a Pod disappears it creates another.
@problem
Bare Pods are not replaced when a node fails or someone deletes them.
@does
- Uses a label selector to count its Pods and adopts matching ones.
- Creates Pods from `spec.template` and names them `<replicaset>-<random>`.
- It has no upgrade logic. You rarely use it directly; Deployments create one ReplicaSet per version.
@diagram flow
caption: Ownership chain
nodes:
  - "Deployment|desired version|app"
  - "ReplicaSet|one per template hash|info"
  - "Pods|replicas|ok"
@h See the chain
```bash title="Deployment to Pods" lab
kubectl create deployment web --image=nginx:1.26 --replicas=3
kubectl get deploy,rs,pods -l app=web
kubectl get rs -l app=web -o jsonpath='{.items[0].metadata.ownerReferences[0].name}{"\n"}'
```
@end

@concept Deployments
@plain
A Deployment manages ReplicaSets to move your app from one version to another in a controlled way.
@problem
Updating an app by replacing all Pods at once causes downtime, and fixing a bad release by hand is slow.
@does
- Changing `spec.template` (image, env, resources) creates a new ReplicaSet and scales it up while the old one scales down.
- Keeps `revisionHistoryLimit` (default 10) old ReplicaSets for rollback.
- Changing only `replicas` does not create a new revision.
- `kubectl rollout status` reports progress and `progressDeadlineSeconds` (default 600) marks it failed when stuck.
@diagram seq
caption: Rolling to a new image
actors: ["Deployment ctrl|controller|cp", "RS v1|old|plain", "RS v2|new|app"]
steps:
  - "0>2: create, scale 1 | req"
  - "2>0: Pod Ready | resp"
  - "0>1: scale down 1 | req"
  - "0>2: scale 2 | req"
  - "0>1: scale down to 0 | req"
@h A production Deployment
```yaml title="deployment.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  labels:
    app: web
spec:
  replicas: 3
  revisionHistoryLimit: 5
  progressDeadlineSeconds: 300
  selector:
    matchLabels:
      app: web
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app: web
    spec:
      containers:
        - name: web
          image: nginx:1.27
          ports:
            - containerPort: 80
          readinessProbe:
            httpGet: {path: /, port: 80}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {memory: 256Mi}
```
@end

@concept Rolling update tuning
@plain
`maxSurge` is how many extra Pods may exist during a rollout. `maxUnavailable` is how many may be missing. Both accept a number or a percentage.
@problem
Too aggressive a rollout drops capacity; too cautious a one is slow or blocked by quota.
@does
- Defaults are 25% for both. For 4 replicas that is 1 surge and 1 unavailable.
- `maxUnavailable: 0` with `maxSurge: 1` never reduces capacity but needs room for one extra Pod.
- A new Pod counts as available only after readiness passes (plus `minReadySeconds`). **Without a readiness probe a bad version rolls out fully.**
- `Recreate` strategy stops all old Pods first; use it when two versions cannot coexist (for example a single-writer volume).
@diagram cmp
caption: Strategy trade-offs
cards:
  - {h: "RollingUpdate 0 unavailable", kind: ok, items: ["No capacity loss", "Needs spare quota", "Default choice"]}
  - {h: "RollingUpdate default 25%", kind: info, items: ["Faster", "Brief capacity dip"]}
  - {h: "Recreate", kind: warn, items: ["Downtime", "No version overlap", "Single-writer volumes"]}
@h Roll, watch, undo
```bash title="Rollout commands" lab
kubectl set image deployment/web web=nginx:1.27.1
kubectl rollout status deployment/web --timeout=120s
kubectl rollout history deployment/web
kubectl rollout undo deployment/web                 # back one revision
kubectl rollout undo deployment/web --to-revision=2
kubectl rollout restart deployment/web              # new Pods, same spec
kubectl rollout pause deployment/web                # batch several edits
```
@check
Why might a rollout with a broken image never finish yet cause no outage? || New Pods fail readiness so they never count as available, and with maxUnavailable limits the old Pods stay. The rollout stalls at the progress deadline.
@end

@concept Blue green and canary releases
@plain
Blue green runs two full versions and switches traffic at once. A canary sends a small share of traffic to the new version first.
@problem
Rolling updates mix versions with no control over who sees the new one and give weak rollback signals.
@does
- **Blue green**: two Deployments, one Service. Change the Service selector (or route) to flip, flip back to roll back. Costs double capacity.
- **Canary with plain Kubernetes**: two Deployments behind one Service; share is proportional to Pod counts, which is coarse.
- **Precise canary**: weighted routes in Gateway API, Istio (used by Kyma) or Argo Rollouts and Flagger, with metric-based promotion.
@diagram flow
caption: Weighted canary
nodes:
  - "Gateway route|weights 90 and 10|cp"
  - "Service web-stable|v1|ok"
  - "Service web-canary|v2|warn"
  - "Metrics check|error rate and latency|info"
@h Weighted routing with Gateway API
```yaml title="canary-route.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: web
spec:
  parentRefs:
    - name: shared-gateway
  hostnames: ["shop.example.com"]
  rules:
    - backendRefs:
        - {name: web-stable, port: 80, weight: 90}
        - {name: web-canary, port: 80, weight: 10}
```
@choose Release strategy
Rolling update | stateless apps with compatible versions | breaking schema or API changes
Blue green | instant switch and instant rollback | capacity is tight
Canary | risky changes you want to measure | you have no metrics to judge success
@end

@concept Scaling, labels and Deployment pitfalls
@plain
`kubectl scale` changes replicas. Most Deployment trouble comes from a few repeating mistakes.
@problem
Small spec errors silently produce outages or stuck rollouts.
@does
- Selector is immutable; to change it you recreate the Deployment.
- Do not set `replicas` in Git when an HPA manages them, otherwise every sync resets it.
- Use immutable image tags or digests, never `latest`, so a rollout equals a spec change.
- Set requests, a readiness probe and a PodDisruptionBudget on every production Deployment.
- ConfigMap changes do not restart Pods; roll them with a hash annotation or tools like Reloader.
@diagram flow
caption: A safe release checklist
nodes:
  - "Pinned image|tag or digest|ok"
  - "Readiness probe|gates rollout|ok"
  - "Requests|capacity planning|ok"
  - "PDB|protects from drains|ok"
@h Quick checks
```bash title="Is the Deployment healthy" lab
kubectl get deploy web -o jsonpath='{.status}' | head -c 400
kubectl describe deploy web | grep -E 'Replicas|Strategy|Conditions' -A4
kubectl get deploy -A -o json | grep -c '"image": ".*:latest"'   # count of latest tags
```
@end

@concept Progress, availability and PodDisruptionBudgets
@plain
A Deployment reports conditions `Progressing` and `Available`. A PodDisruptionBudget limits how many Pods voluntary actions such as drains may remove.
@problem
During node upgrades, a drain could evict every replica of a service at the same moment.
@does
- `Available` is true when at least `replicas - maxUnavailable` Pods are ready.
- A PDB (`minAvailable` or `maxUnavailable`) is honoured by the eviction API, so `kubectl drain` waits instead of breaking the service.
- A PDB does not protect against node crashes or `kubectl delete pod`.
- A PDB with `minAvailable` equal to replicas blocks drains forever; leave room for one Pod.
@diagram seq
caption: A drain respecting a PDB
actors: ["kubectl drain|operator|ext", "Eviction API|cp|cp", "PDB|web minAvailable 2|warn"]
steps:
  - "0>1: evict web-1 | req"
  - "1>2: allowed | req"
  - "2>1: yes, 3 ready | resp"
  - "0>1: evict web-2 | req"
  - "2>1: no, only 2 ready | bad"
@h A PDB
```yaml title="pdb.yaml"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: web
```
@end
