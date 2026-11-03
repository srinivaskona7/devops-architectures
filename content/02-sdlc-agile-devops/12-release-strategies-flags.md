---
title: Release strategies, branching and feature flags
minutes: 45
objectives:
  - Compare rolling, blue-green, canary and recreate deployments and choose between them
  - Pick a branching strategy and a versioning scheme that fit continuous delivery
  - Use feature flags to separate deployment from release and manage their lifecycle
---
The safer and smaller a release is, the more often you can do it. This section covers how to push changes out with a limited blast radius and a fast way back.

@concept Deploy versus release
@plain
**Deploying** puts new code on servers. **Releasing** exposes the new behaviour to users. Separating the two removes most release-day risk.
@problem
When deploy and release are the same event, every deployment is a high-stakes moment and rollback means redeploying.
@does
- Deploy often, with new features hidden behind flags or routing rules.
- Release gradually to a small group, watch metrics, then widen.
- Rolling back a release becomes switching a flag, which takes seconds.
- Database changes must be compatible with both old and new code during the transition.
@diagram flow
caption: Decoupled deploy and release
numbered: true
nodes:
  - "Deploy|code is live, feature off|app"
  - "Enable for staff|1 percent|env"
  - "Expand|10, 50 percent|warn"
  - "Full release|100 percent|ok"
@h A release checklist in code
```bash title="Verify a rollout, then decide" lab
kubectl rollout status deployment/api -n shop --timeout=120s 2>/dev/null
kubectl get deploy api -n shop -o jsonpath='{.status.readyReplicas}/{.spec.replicas}{"\n"}' 2>/dev/null
echo "then check error rate and latency dashboards before widening exposure"
```
@check
Why is a flag rollback faster than a code rollback? || No build or deployment is needed; the new behaviour is simply turned off.
@end

@concept Rolling and recreate deployments
@plain
A **rolling** update replaces old instances with new ones a few at a time. A **recreate** deployment stops all old instances and then starts the new ones.
@problem
Stopping everything to upgrade causes downtime. But running two versions at once needs compatibility between them.
@does
- Kubernetes Deployments roll by default. `maxSurge` and `maxUnavailable` control how many extra and missing pods are allowed.
- Readiness probes decide when a new pod gets traffic; without them a rolling update can send traffic to a pod that is not ready.
- Recreate suits apps that cannot run two versions at once, at the price of downtime.
- Rollback with `kubectl rollout undo`.
@diagram flow
caption: Rolling update with three replicas
numbered: true
nodes:
  - "3 old pods|v1|app"
  - "Add 1 new|v2 becomes ready|info"
  - "Remove 1 old|repeat|warn"
  - "3 new pods|v2|ok"
@h Rolling configuration
```yaml title="Deployment strategy"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 3
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  selector:
    matchLabels: {app: api}
  template:
    metadata:
      labels: {app: api}
    spec:
      containers:
        - name: api
          image: registry.example.com/shop/api:1.4.2
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
            periodSeconds: 5
```
```bash title="Undo a bad rollout" lab
kubectl rollout history deployment/api -n shop 2>/dev/null
kubectl rollout undo deployment/api -n shop 2>/dev/null
```
@check
What does maxUnavailable 0 guarantee? || Capacity never drops below the desired replica count during the update, because new pods must be ready first.
@end

@concept Blue-green deployments
@plain
Run two complete environments: blue (current) and green (new). Test green, then switch traffic from blue to green in one step. Blue stays ready for instant rollback.
@problem
Rolling updates mix versions during the change. Some changes need a clean cutover and a very fast way back.
@does
- Traffic switch happens at a load balancer, ingress or service selector.
- Rollback is switching back; keep blue until confident.
- Costs double capacity during the switch.
- Database schema must work with both versions (expand-contract migrations).
@diagram flow
caption: Switching traffic from blue to green
nodes:
  - "Users|requests|ext"
  - "Router|selector or load balancer|cp"
  - "Blue v1|live now|app"
  - "Green v2|tested, idle|env"
@h Switch with a Service selector
```bash title="Cut over by changing the selector" lab
kubectl patch service api -n shop -p '{"spec":{"selector":{"app":"api","version":"green"}}}' --dry-run=client -o yaml 2>/dev/null | head -12
echo "rollback: patch the selector back to version blue"
```
@check
What is the main cost of blue-green? || Running two full environments at once, and keeping data schemas compatible.
@end

@concept Canary releases and progressive delivery
@plain
Send a small percentage of real traffic to the new version, compare its health with the old one, and increase gradually or abort automatically.
@problem
Tests cannot reproduce every production condition. Exposing only 5 percent of users limits harm from an unknown bug.
@does
- Traffic split by weight (service mesh, ingress, Argo Rollouts, Flagger) or by cohort (internal users first).
- Automated analysis compares error rate and latency against thresholds and rolls back by itself.
- Needs good metrics. Without them a canary is just a slower rollout.
- Progressive delivery combines canary, flags and automated analysis.
@diagram flow
caption: A canary ladder
numbered: true
nodes:
  - "5 percent|watch 10 min|warn"
  - "25 percent|watch 10 min|warn"
  - "50 percent|watch 10 min|info"
  - "100 percent|promote|ok"
@h Argo Rollouts example
```yaml title="Canary steps" nocheck
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: api
spec:
  replicas: 10
  strategy:
    canary:
      steps:
        - setWeight: 5
        - pause: {duration: 10m}
        - setWeight: 25
        - pause: {duration: 10m}
        - setWeight: 50
        - pause: {duration: 10m}
  selector:
    matchLabels: {app: api}
  template:
    metadata:
      labels: {app: api}
    spec:
      containers:
        - name: api
          image: registry.example.com/shop/api:1.5.0
```
@choose Deployment strategy
Rolling | most stateless services with backward compatible changes | two versions cannot run side by side
Blue-green | instant cutover and instant rollback matter | capacity is too costly to double
Canary | risky changes where real traffic is the best test | you lack metrics to judge health
Recreate | batch jobs or apps that need exclusive access | users cannot tolerate downtime
@end

@concept Feature flags
@plain
A feature flag is a runtime switch that turns behaviour on or off, for everyone or for chosen users, without deploying.
@problem
Long-lived branches hide unfinished work; big-bang releases cannot be undone quickly.
@does
- Types: **release flags** (temporary, hide unfinished work), **ops flags** (kill switches), **experiment flags** (A/B tests), **permission flags** (long-lived entitlements).
- Evaluated by a library against rules: user, percentage, region.
- Flags need an owner and an expiry date; stale flags are technical debt and multiply test paths.
- Tools: OpenFeature (standard API), LaunchDarkly, Unleash, Flagsmith, or a simple config.
@diagram cmp
caption: Four kinds of flags
cards:
  - {h: "Release", kind: warn, items: ["Short lived", "Remove after full rollout"]}
  - {h: "Ops kill switch", kind: bad, items: ["Disable a risky path fast", "Long lived by design"]}
  - {h: "Experiment", kind: info, items: ["A/B tests", "Ends with a decision"]}
  - {h: "Permission", kind: ok, items: ["Plan-based features", "Part of the product"]}
@h Percentage rollout logic
```python title="Stable bucketing for a percentage flag" lab
import hashlib
def enabled(flag, user_id, percent):
    h = int(hashlib.sha256(f"{flag}:{user_id}".encode()).hexdigest(), 16) % 100
    return h < percent
users = [f"u{i}" for i in range(1000)]
on = sum(enabled("new-checkout", u, 10) for u in users)
print(f"{on} of 1000 users see it at 10 percent")
print("same user is stable:", enabled("new-checkout", "u7", 10) == enabled("new-checkout", "u7", 10))
```
@check
Why hash the user id rather than random per request? || The same user must always get the same experience.
@end

@concept Branching strategies
@plain
A branching strategy defines how changes move from a developer to main to production. The main options are trunk-based development, GitHub Flow, GitFlow and release branches.
@problem
A complex branching model with long-lived branches causes painful merges, and delays integration and releases.
@does
- **Trunk-based**: short-lived branches merged to main daily; flags for unfinished work; best for continuous delivery.
- **GitHub Flow**: branch, pull request, merge to main, deploy.
- **GitFlow**: develop, feature, release and hotfix branches; suits packaged software with multiple supported versions but is heavy for services.
- **Release branches** are cut from main for stabilisation or long-term support, with fixes cherry-picked.
@diagram cmp
caption: Branching styles
cards:
  - {h: "Trunk-based", kind: ok, items: ["Merge to main daily", "Flags hide work", "Best for CD"]}
  - {h: "GitHub Flow", kind: app, items: ["Short PR branches", "Deploy from main"]}
  - {h: "GitFlow", kind: warn, items: ["Develop and release branches", "Heavy, for versioned products"]}
@h Release branch hotfix
```bash title="Cherry-pick a fix to a release branch" lab
git switch -c release/1.4 v1.4.0 2>/dev/null
git cherry-pick -x 3f1c0e9 2>/dev/null || echo "cherry-pick the merged fix commit from main"
git tag -a v1.4.1 -m "Hotfix 1.4.1" 2>/dev/null
```
@check
What does git cherry-pick -x add? || A line in the commit message naming the original commit, which keeps traceability.
@end

@concept Versioning and release notes
@plain
A version number tells consumers what changed. **Semantic versioning** uses MAJOR.MINOR.PATCH: major for breaking changes, minor for compatible features, patch for compatible fixes.
@problem
Without clear versions, users cannot tell if an upgrade is safe, and incident responders cannot tell what is running.
@does
- Tag releases in Git (`v1.4.2`) and build images from the tag, tagging them with the version and immutable digest.
- Conventional Commits (`feat:`, `fix:`, `feat!:`) let tools compute the next version and generate release notes.
- Services deployed continuously may use commit SHA or date based versions, with semver reserved for libraries and APIs.
- Keep a changelog with user-visible changes, migration steps and known issues.
@diagram flow
caption: From commit messages to a release
numbered: true
nodes:
  - "Conventional commits|feat, fix|app"
  - "Tool computes version|1.4.2 to 1.5.0|info"
  - "Tag and build|image from tag|env"
  - "Release notes|generated|ok"
@h Examples
```bash title="Semver and conventional commits" lab
git log --oneline -5 2>/dev/null
echo "fix: handle empty cart        -> patch 1.4.2 -> 1.4.3"
echo "feat: add order tracking      -> minor 1.4.2 -> 1.5.0"
echo "feat!: remove v1 orders API   -> major 1.4.2 -> 2.0.0"
git describe --tags --abbrev=0 2>/dev/null || echo "no tags yet"
```
@check
What bump does a backwards-incompatible API change need? || A major version bump.
@end
