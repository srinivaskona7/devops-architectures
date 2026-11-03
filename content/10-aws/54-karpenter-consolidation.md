---
title: Karpenter consolidation, drift and operations
minutes: 45
objectives:
  - Configure consolidation and disruption budgets to cut cost safely
  - Use drift and expiry to roll AMIs and configuration
  - Debug unschedulable pods and Karpenter decisions
---
Launching nodes is half the job. Karpenter also removes and replaces them to keep the fleet cheap and fresh. Done carelessly, that disrupts workloads, so you control it with budgets.

@concept Consolidation
@plain
Consolidation deletes empty nodes and replaces underused nodes with fewer or cheaper ones, moving pods in between.
@problem
After a traffic peak the cluster stays large and nearly empty. Manual scale-down is slow and conservative.
@does
- `consolidationPolicy: WhenEmpty` only removes empty nodes; `WhenEmptyOrUnderutilized` also repacks.
- `consolidateAfter` is a delay after a pod change before consolidation is considered.
- Single-node, multi-node and Spot-to-Spot consolidation exist; Spot-to-Spot is behind a feature gate (check the docs).
- Karpenter respects PDBs and `do-not-disrupt`. Pods without a controller are not moved.
@diagram flow
caption: Three nodes become two
numbered: true
nodes:
  - "3 nodes 30 percent used|waste|warn"
  - "Simulate|can pods fit on fewer?|info"
  - "Cordon and drain|honor PDBs|app"
  - "Delete node|cost drops|ok"
@h Observe
```bash title="Decisions and events" lab
kubectl get nodeclaims
kubectl get events -A --field-selector reason=DisruptionLaunching,reason=DisruptionTerminating
kubectl -n kube-system logs deploy/karpenter | grep -i -E 'consolidat|disrupt' | tail
kubectl describe nodepool general | sed -n '/Disruption/,/Limits/p'
```
@check
What is the difference between WhenEmpty and WhenEmptyOrUnderutilized? || The second also repacks partly used nodes, not only removes empty ones.
@end

@concept Disruption budgets
@plain
A budget limits how many nodes Karpenter may disrupt at once, optionally only in a time window and only for certain reasons.
@problem
A new AMI or a quiet period might make Karpenter replace most nodes together and cause incidents.
@does
- `budgets` list `nodes` (count or percent), optional `reasons` (`Empty`, `Drifted`, `Underutilized`) and `schedule` with `duration`.
- Several budgets apply together; the most restrictive wins.
- Block all voluntary disruption during business hours with `nodes: "0"` and a cron schedule.
- Involuntary events (Spot interruption, failures) are not affected by budgets.
@diagram cmp
caption: Example budget policy
cards:
  - {h: "Always", kind: info, items: ["At most 10 percent of nodes"]}
  - {h: "Weekdays 09:00 to 17:00 UTC", kind: warn, items: ["Zero for Underutilized", "Drift still allowed 1 node"]}
  - {h: "Spot interruptions", kind: bad, items: ["Not limited", "Always handled"]}
@h Budgets
```yaml title="NodePool disruption section"
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: general
spec:
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand"]
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 5m
    budgets:
      - nodes: "10%"
      - nodes: "0"
        reasons: ["Underutilized"]
        schedule: "0 9 * * mon-fri"
        duration: 8h
```
@check
Do budgets limit Spot interruptions? || No; involuntary disruptions are outside budgets.
@end

@concept Drift and expiry
@plain
**Drift** means a node no longer matches its NodePool or EC2NodeClass (new AMI, changed subnets, changed requirements). Karpenter replaces drifted nodes. **expireAfter** replaces nodes at a maximum age.
@problem
Node patching by hand is slow. You want fresh AMIs and consistent config without a maintenance window project.
@does
- Changing `amiSelectorTerms` to a new AMI marks all nodes drifted; they are replaced gradually, within your budgets.
- Kubernetes upgrade flow: upgrade control plane, then Karpenter drifts nodes to the new AMI for that minor version.
- `expireAfter: 720h` bounds node lifetime (about 30 days), a good security hygiene default.
- Test AMI changes on a canary NodePool first.
@diagram flow
caption: Rolling a new AMI
nodes:
  - "Change AMI alias|al2023@v2025..|app"
  - "Nodes drift|marked for replacement|warn"
  - "Budgeted replacement|10 percent at a time|info"
  - "Fleet updated|all nodes new|ok"
@h Pin and roll
```bash title="Roll by changing the AMI alias" nocheck
kubectl patch ec2nodeclass default --type merge \
  -p '{"spec":{"amiSelectorTerms":[{"alias":"al2023@v20250115"}]}}'
kubectl get nodeclaims -w
```
@check
What triggers drift? || A change in NodePool or EC2NodeClass settings, including a new selected AMI, so existing nodes no longer match.
@end

@concept Debugging provisioning problems
@plain
When pods stay Pending, Karpenter logs say why no instance could be launched.
@problem
Causes are spread: no capacity, limits reached, impossible requirements, missing IAM permissions, subnet IP exhaustion.
@does
- Look at pod events (`FailedScheduling`), `kubectl get nodeclaims`, and the controller log.
- `InsufficientInstanceCapacity` → widen instance types or zones.
- `NodePool limits exceeded` → raise limits or find the leak.
- `UnauthorizedOperation` → check the controller's role (Pod Identity or IRSA) and the node role pass-role permission.
- `no subnets found` → fix the `karpenter.sh/discovery` tag.
- Nodes launch but do not join → node role access entry, security group, AMI/bootstrap.
@diagram flow
caption: Triage
nodes:
  - "Pod Pending|FailedScheduling|warn"
  - "NodeClaim created?|yes or no|info"
  - "Log reason|capacity, limits, IAM|app"
  - "Fix and wait|new batch|ok"
@h Commands
```bash title="Find the reason" lab
kubectl get pods -A --field-selector=status.phase=Pending
kubectl describe pod <pod> -n shop | grep -A5 Events
kubectl get nodeclaims -o wide
kubectl -n kube-system logs deploy/karpenter --tail=100 | grep -i -E 'error|failed|insufficient'
```
@check
Where do you look when no NodeClaim is created? || The Karpenter logs and the pod's scheduling constraints; requirements may be impossible or limits reached.
@end

@concept Cost and safety checklist
@plain
Karpenter saves money mostly through right-sizing, Spot and consolidation. Keep a short list of controls.
@problem
Savings disappear when requests are inflated or Spot is unmanaged; risk rises when budgets are missing.
@does
- Wide instance requirements, ARM (Graviton) nodes where images are multi-arch.
- Limits per NodePool tied to a budget; alerts on node count and spend.
- PDBs and zone spread on every production workload; PreStop hooks for graceful stop.
- Pinned AMI in production and canary in dev; `expireAfter` set.
- Dashboards: `karpenter_nodes_total`, `karpenter_pods_startup_duration_seconds`, interruption counts.
@diagram layers
caption: Control layers
layers:
  - {label: "Cost", nodes: ["Spot mix|savings|ok", "Graviton|lower price per vCPU|ok", "Consolidation|fewer nodes|ok"]}
  - {label: "Safety", nodes: ["PDBs|keep replicas up|warn", "Budgets|slow churn|warn", "Limits|cap spend|warn"]}
@h Multi-arch check
```bash title="Check image architectures" nocheck
docker buildx imagetools inspect 111122223333.dkr.ecr.us-east-1.amazonaws.com/shop/web:1.4.2 | grep -E 'Platform'
```
@check
Which setting guards against a runaway scale-out? || NodePool limits.
@end
