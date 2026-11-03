---
title: Deploying, rolling back and upgrading EKS
minutes: 60
objectives:
  - Roll out a release with verification gates and roll back quickly
  - Use progressive delivery for the checkout path
  - Follow a tested runbook to upgrade the EKS control plane, add-ons and nodes
---
Deployment strategies are explained in the CI/CD folder. Here we apply them to the Shop and write the cluster upgrade runbook. The Kubernetes version numbers shown ({{v.eks_from}} to {{v.eks_to}}) are examples; confirm the current EKS release calendar before planning.

@concept Release checklist
@plain
A short list that the release engineer follows for every production release.
@problem
Releases done from memory skip steps, and the skipped step is always the one that mattered.
@does
- Before: staging green for the same tags, load test result within budget, migration reviewed, rollback plan known, no active incident, not Friday evening.
- During: promote, review the Argo CD diff, sync, watch the dashboard for 15 minutes (error rate, p95, saturation).
- After: smoke test, update the release note, tag the Git commit, close the change.
- Automate what you can: the smoke script and the dashboard link are in the release pull request template.
@diagram flow
caption: Release steps
nodes:
  - "Pre-checks|staging, budget|plain"
  - "Sync|Argo CD|app"
  - "Watch 15 minutes|dashboard|warn"
  - "Close|note and tag|ok"
@h Pull request template
```markdown title=".github/pull_request_template.md" nocheck
## Release checklist
- [ ] Staging ran the same image tags for 24 hours
- [ ] k6 smoke and load results attached
- [ ] Migration is backward compatible (expand step only)
- [ ] Rollback plan stated
- [ ] Error budget remaining above 50 percent
- [ ] On-call informed
```
@end

@concept Rolling update behaviour and what can go wrong
@plain
A rolling update replaces pods gradually. With `maxSurge 1` and `maxUnavailable 0` a new pod must be Ready before an old one is removed.
@problem
A bad version with a passing readiness probe still receives traffic; a bad probe blocks the rollout and looks like a hang.
@does
- Stuck rollouts show up as `kubectl rollout status` timing out; `kubectl describe pod` explains (image pull error, probe failure, quota).
- `progressDeadlineSeconds` (default 600) marks the rollout as failed, but does not roll back by itself.
- `minReadySeconds: 10` makes a pod stay Ready for 10 seconds before the next replaced one, catching early crashes.
- Argo CD shows the Application as Progressing then Degraded when a Deployment fails.
@diagram flow
caption: Rolling update in four replicas
nodes:
  - "3 old pods|serving|plain"
  - "1 new pod added|surge|info"
  - "Ready then one old removed|repeat|warn"
  - "3 new pods|done|ok"
@h Commands
```bash title="Watch and inspect a rollout" lab
kubectl -n shop rollout status deploy/orders --timeout=300s
kubectl -n shop get rs -l app=orders
kubectl -n shop describe deploy/orders | sed -n '/Events/,$p'
```
@end

@concept Rollback options
@plain
Three ways to go back: revert the Git commit (the GitOps way), sync Argo CD to a previous revision, or `kubectl rollout undo` as an emergency tool.
@problem
In an incident, people improvise rollbacks that leave Git and the cluster disagreeing, and Argo CD then reverts the improvised fix.
@does
- Preferred: `git revert <promotion commit>` then merge; Argo CD syncs the old tags. Takes minutes and leaves an audit trail.
- Fast: Argo CD history, "rollback" to a previous revision. For automated apps this needs auto-sync disabled first (otherwise it re-syncs to Git).
- Emergency: `kubectl rollout undo deploy/orders`. Argo CD will show the app OutOfSync; follow up with a Git revert.
- Database changes are not rolled back by any of these; use expand/contract so the old code works with the new schema.
@diagram cmp
caption: Rollback choices
cards:
  - {h: "Git revert", kind: ok, items: ["Source of truth stays right", "Audit trail", "Minutes"]}
  - {h: "Argo CD history", kind: info, items: ["Fast UI action", "Disable auto-sync first", "Git must be fixed after"]}
  - {h: "kubectl rollout undo", kind: warn, items: ["Seconds", "Creates drift", "Follow with a Git revert"]}
@h Commands
```bash title="Rollback" lab
# 1. GitOps rollback
git revert --no-edit HEAD
git push origin main
# 2. Emergency
kubectl -n shop rollout undo deploy/orders
kubectl -n shop rollout status deploy/orders
```
@check
Why must Git be fixed after a kubectl rollout undo? || Argo CD compares the cluster to Git. Without a Git change it reports drift and selfHeal would reapply the bad version.
@end

@concept Progressive delivery with Argo Rollouts
@plain
Argo Rollouts replaces a Deployment with a Rollout resource that shifts traffic in steps and checks metrics between them.
@problem
A rolling update exposes all users within minutes; for checkout you want 5 percent first and an automatic stop on errors.
@does
- Canary steps: 10 percent, pause 5 minutes with analysis, 50 percent, pause, 100 percent.
- `AnalysisTemplate` queries Prometheus; if the 5xx rate is above 1 percent the Rollout aborts and returns to the stable version.
- With the AWS Load Balancer Controller the traffic split uses weighted target groups, or use pod-count based canaries without a traffic router (coarser).
- Adds a controller to run and a CRD to learn; use it for orders and payments first, keep the rest on Deployments.
@diagram flow
caption: Canary with automatic abort
nodes:
  - "10 percent|new version|info"
  - "Analysis|5xx under 1 percent|warn"
  - "50 percent|pause|info"
  - "100 percent|promoted|ok"
@h Rollout and analysis
```yaml title="deploy/base/orders-rollout.yaml" nocheck
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: orders
spec:
  replicas: 3
  selector:
    matchLabels: {app: orders}
  strategy:
    canary:
      steps:
        - setWeight: 10
        - pause: {duration: 5m}
        - analysis:
            templates:
              - templateName: error-rate
        - setWeight: 50
        - pause: {duration: 5m}
  template:
    metadata:
      labels: {app: orders}
    spec:
      containers:
        - name: orders
          image: shop/orders
---
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: error-rate
spec:
  metrics:
    - name: five-xx-ratio
      interval: 1m
      count: 5
      failureLimit: 1
      successCondition: result[0] < 0.01
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(http_requests_total{service="orders",status=~"5.."}[2m]))
            / sum(rate(http_requests_total{service="orders"}[2m]))
```
:::note
Check the current Argo Rollouts docs for exact field names and the traffic router setup before using this. It is marked nocheck because the CRD is not part of the base build.
:::
@end

@concept EKS upgrade runbook - plan
@plain
EKS upgrades one minor version at a time: control plane first, then add-ons, then nodes. Staging goes first.
@problem
An unplanned upgrade breaks workloads that used removed APIs or older add-on versions, and cannot be undone: the control plane does not downgrade.
@does
- Read the release notes of the target version and the EKS upgrade guide; check the EKS Upgrade Insights and `kubectl get --raw /metrics` for deprecated API usage (or tools such as `pluto` and `kubent`).
- Skip is not allowed: from {{v.eks_from}} to {{v.eks_to}}, never two minors at once.
- Window: low traffic, staff available, no release in progress, a rollback plan for workloads (not for the control plane).
- Rehearse in staging and measure the time of each step; production repeats the same steps.
- Version skew: nodes may lag the control plane by a small number of minor versions (check the current Kubernetes version skew policy).
@diagram flow
caption: Upgrade order
nodes:
  - "Check APIs and add-ons|before|plain"
  - "Control plane|about 20 to 40 min|cp"
  - "Add-ons|CNI, CoreDNS, kube-proxy|info"
  - "Node groups|rolling replace|app"
  - "Verify|smoke and dashboards|ok"
@end

@concept EKS upgrade runbook - execution
@plain
The steps with the commands, and the checks after each.
@problem
In the middle of an upgrade nobody should be deciding what to do next.
@does
- Change `kubernetes_version` in Terraform for the environment, plan, review, apply (the control plane upgrade takes some minutes with the API still serving).
- Update add-on versions through Terraform to versions compatible with the new Kubernetes version (list with `aws eks describe-addon-versions`).
- Update the node group: Terraform changes the version, EKS launches new nodes, cordons and drains old ones respecting PDBs, one node at a time (`max_unavailable = 1`). Watch for pods stuck due to a PDB.
- After each stage run the smoke script and look at error rate and p95.
- Lesson learned: verify no node stays cordoned afterwards (`kubectl get nodes` shows `SchedulingDisabled`) and uncordon manually if it does.
@diagram seq
caption: Node group rolling update
actors: ["Terraform|apply|app", "EKS|managed node group|cp", "Old node|being drained|warn", "New node|replacement|ok"]
steps:
  - "0>1: version change | req"
  - "1>3: launch new node | req"
  - "3>1: Ready | resp"
  - "1>2: cordon and drain | req"
  - "note 2..2: PDB limits evictions"
  - "2>3: pods rescheduled | resp"
@h Commands
```bash title="Upgrade checks" lab
kubectl version
kubectl get nodes -o wide
aws eks describe-addon-versions --kubernetes-version {{v.eks_to}} --addon-name coredns --query 'addons[].addonVersions[].addonVersion' --output text | head
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis | head
kubectl get nodes | grep SchedulingDisabled || echo "no cordoned nodes"
```
:::warn
The Kubernetes version `{{v.eks_to}}` above is an example. Replace it with the version one minor above your cluster and check the current EKS calendar for end-of-support dates.
:::
@end

@concept Upgrade timing and downtime budget
@plain
Estimate how long the node roll takes so the window is long enough.
@problem
A window that is too short leaves the cluster half-upgraded when people go home.
@does
- Per node: launch and join about 3 minutes, drain with grace period up to 30 seconds per pod plus rescheduling, about 4 minutes in total, plus a 2 minute health wait. Say 9 minutes.
- 3 nodes one at a time: 27 minutes; with 6 nodes at peak: 54 minutes.
- Control plane 30 minutes, add-ons 15 minutes, verification 20 minutes.
- Total for 3 nodes: 30 + 15 + 27 + 20 = 92 minutes. Plan a 2 hour window; for 6 nodes 119 minutes, plan 3 hours.
- With `maxUnavailable: 0` on Deployments, PDBs and 3 replicas, customers see no downtime. The SLO budget of 43.2 minutes a month is not touched.
@diagram flow
caption: Window budget
nodes:
  - "Control plane|30 min|cp"
  - "Add-ons|15 min|info"
  - "3 nodes x 9 min|27 min|app"
  - "Verify|20 min|ok"
@h Check the sum
```python title="window.py" lab
def window(nodes, per_node=9, cp=30, addons=15, verify=20):
    return cp + addons + nodes * per_node + verify

for n in (3, 6):
    print(n, "nodes:", window(n), "minutes")
```
@end
