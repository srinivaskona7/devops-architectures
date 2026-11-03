---
title: EKS upgrades and day-2 operations
minutes: 50
objectives:
  - Plan and execute a Kubernetes minor version upgrade end to end
  - Detect deprecated APIs and add-on incompatibilities before upgrading
  - Run PodDisruptionBudgets, topology spread and troubleshooting routines
---
Kubernetes releases a minor version about three times a year, and each EKS version has a finite support window. Upgrading is a routine task, not an event.

@concept Version support and cadence
@plain
EKS supports each Kubernetes minor version for a standard support period, then offers a paid extended support period, after which the cluster is upgraded automatically.
@problem
Skipping upgrades makes them bigger and riskier, and extended support costs more per cluster hour.
@does
- Only upgrade one minor version at a time ({{v.eks_from}} to {{v.eks_to}}, never two minors at once).
- You cannot downgrade a control plane.
- Check **EKS cluster insights** (`aws eks list-insights`) for deprecated API usage and add-on compatibility.
- Calendar: look up the current dates on the Amazon EKS Kubernetes versions page.
@diagram flow
caption: Yearly rhythm
nodes:
  - "New version released|upstream|plain"
  - "EKS availability|weeks to months later|info"
  - "Standard support|about 14 months|ok"
  - "Extended support|extra cost|warn"
@h Insights
```bash title="Pre-upgrade checks" lab
aws eks list-insights --cluster-name shop-prod \
  --filter kubernetesVersions={{v.eks_to}} \
  --query 'insights[].[name,insightStatus.status]' --output table
aws eks describe-cluster --name shop-prod --query cluster.version
kubectl get nodes -o custom-columns=NAME:.metadata.name,VER:.status.nodeInfo.kubeletVersion
```
@check
Can you jump two minor versions at once? || No; upgrade one minor version at a time.
@end

@concept Upgrade order and procedure
@plain
Upgrade the control plane first, then add-ons, then nodes. Each step is verified before the next.
@problem
Upgrading in the wrong order can break compatibility: nodes cannot be newer than the control plane, and add-ons may need newer versions.
@does
1. Read release notes and check deprecations and insights.
2. Upgrade non-production first and run smoke tests.
3. `aws eks update-cluster-version` (control plane, roughly 10 to 25 minutes, API remains available).
4. Update add-ons: vpc-cni, kube-proxy, coredns, CSI drivers.
5. Roll node groups, or let Karpenter drift replace nodes.
6. Update Helm-managed controllers such as the LB controller, Karpenter and cert-manager.
@diagram flow
caption: Upgrade sequence
numbered: true
nodes:
  - "Insights and notes|deprecations|info"
  - "Control plane|update-cluster-version|cp"
  - "Add-ons|vpc-cni, coredns, kube-proxy|env"
  - "Nodes|new AMI, drain|app"
  - "Controllers|Helm charts|app"
  - "Verify|smoke tests|ok"
@h Commands
```bash title="Control plane then add-ons" nocheck
aws eks update-cluster-version --name shop-prod --kubernetes-version {{v.eks_to}}
aws eks wait cluster-active --name shop-prod
for a in vpc-cni kube-proxy coredns; do
  aws eks update-addon --cluster-name shop-prod --addon-name $a --resolve-conflicts PRESERVE
done
aws eks update-nodegroup-version --cluster-name shop-prod --nodegroup-name general
```
```bash title="Find removed APIs in manifests" nocheck
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis
# or scan YAML in git
kubent
pluto detect-files -d ./manifests --target-versions k8s=v{{v.eks_to}}.0
```
@check
Why must you not downgrade a control plane? || EKS does not support it; rollback means creating a new cluster, so test before upgrading production.
@end

@concept Blue/green cluster upgrades
@plain
Instead of upgrading in place, build a second cluster on the new version, shift traffic to it, and retire the old one.
@problem
An in-place upgrade cannot be rolled back. Some teams need a reversible path for critical systems.
@does
- Needs everything as code (Terraform, GitOps) so the new cluster reaches parity quickly.
- Traffic moves with weighted Route 53 records or a shared ALB/NLB front.
- Stateful data stays outside the cluster (RDS, DynamoDB, S3) or is replicated.
- Costs double briefly and operations are more complex; in-place with good staging is enough for most teams.
@diagram flow
caption: Cluster blue/green
nodes:
  - "Blue 1.31|serving 100 percent|cp"
  - "Green 1.32|built from code|info"
  - "Weighted DNS|10, 50, 100 percent|warn"
  - "Retire blue|after soak time|ok"
@choose Upgrade strategy
In place | a good staging cluster, GitOps, PDBs in place | you cannot tolerate any rollback risk
Blue/green cluster | critical systems, big API changes | you lack automation to rebuild quickly
@end

@concept Disruption control with PDBs and topology spread
@plain
A **PodDisruptionBudget** limits how many pods of an app may be voluntarily evicted at once. **Topology spread constraints** distribute pods across AZs and nodes.
@problem
Drains during upgrades can take all replicas of a service down together, or leave them all in one AZ.
@does
- PDB `minAvailable: 1` or `maxUnavailable: 1` keeps service up while nodes roll. A PDB set to zero allowed disruptions blocks every drain.
- `topologySpreadConstraints` with `topologyKey: topology.kubernetes.io/zone` spreads replicas across AZs.
- Combine with at least two replicas and readiness probes.
- Single replica Deployments cannot be both HA and drainable; give them two.
@diagram cmp
caption: Protection tools
cards:
  - {h: "PDB", kind: ok, items: ["Limits concurrent evictions", "Respected by drain and Karpenter"]}
  - {h: "Topology spread", kind: info, items: ["Spreads across zones", "Survives AZ loss"]}
  - {h: "Anti-affinity", kind: app, items: ["Avoid same node", "Stricter, can block scheduling"]}
@h Manifests
```yaml title="PDB and spread for the web deployment"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web
  namespace: shop
spec:
  maxUnavailable: 1
  selector:
    matchLabels:
      app: web
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
          labelSelector:
            matchLabels:
              app: web
      containers:
        - name: web
          image: nginx:1.27
```
@check
What does a PDB with maxUnavailable 0 do to upgrades? || It blocks node drains, so the node update stalls.
@end

@concept Troubleshooting routine
@plain
When nodes do not join, pods stay Pending or traffic fails, work from the control plane outward.
@problem
EKS failures are spread across IAM, networking and Kubernetes, and guessing wastes time.
@does
- Node not joining: node role has `AmazonEKSWorkerNodePolicy`, `AmazonEKS_CNI_Policy`, `AmazonEC2ContainerRegistryReadOnly`; security groups allow node to control plane (TCP 443); an access entry of type `EC2_LINUX` exists; check the node's `journalctl -u kubelet`.
- Pod Pending: `kubectl describe pod` events (insufficient CPU, no IPs, taints, unbound PVC).
- ImagePullBackOff: ECR permissions, VPC endpoint or NAT, image tag exists.
- Use the EKS **node monitoring agent** and `aws eks` log collector script for node diagnostics.
- Check CloudTrail and the authenticator logs for IAM errors.
@diagram flow
caption: Pending pod triage
nodes:
  - "describe pod|events|info"
  - "Capacity?|CPU, memory, IPs|warn"
  - "Scheduling rules?|taints, affinity, PVC|app"
  - "Fix and retry|scale or relax|ok"
@h Commands
```bash title="First minute commands" lab
kubectl get pods -A --field-selector=status.phase!=Running | head -20
kubectl describe pod <pod> -n shop | tail -20
kubectl get events -A --sort-by=.lastTimestamp | tail -15
kubectl get nodes -o wide
kubectl top nodes
```
@check
Where do you look first for a pod stuck in Pending? || The Events section of `kubectl describe pod`.
@end
