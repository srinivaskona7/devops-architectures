---
title: EKS compute with node groups and Fargate
minutes: 45
objectives:
  - Create managed node groups with the right AMI type and update strategy
  - Use Fargate profiles where serverless pods fit
  - Choose between node group, Fargate and Karpenter
---
Pods run on worker capacity. EKS offers three ways to supply it, and most real clusters use more than one.

@concept Managed node groups
@plain
A managed node group is an Auto Scaling group of EC2 instances that EKS creates, registers and upgrades for you. Nodes are normal EC2 instances in your account.
@problem
Self-managed nodes need AMI selection, bootstrap scripts, drain logic during upgrades and node-to-cluster auth wiring.
@does
- Choose instance types, min, max and desired size, subnets, labels and taints.
- EKS handles join, health and a rolling update that cordons and drains nodes, honoring PodDisruptionBudgets.
- Capacity type can be `ON_DEMAND` or `SPOT`.
- Use launch templates for custom user data, disk size or security groups.
- Cluster Autoscaler can scale the group; Karpenter replaces that approach.
@diagram flow
caption: A managed group in the cluster
nodes:
  - "Node group|ASG, 3 AZs|app"
  - "EC2 nodes|AL2023 or Bottlerocket|env"
  - "kubelet|joins cluster|cp"
  - "Pods|scheduled|ok"
@h Create one
```bash title="eksctl managed node group" nocheck
eksctl create nodegroup --cluster shop-prod --name general \
  --node-type m6i.xlarge --nodes 3 --nodes-min 3 --nodes-max 9 \
  --node-private-networking --managed
```
```hcl title="Terraform node group with taint"
resource "aws_eks_node_group" "batch" {
  cluster_name    = aws_eks_cluster.this.name
  node_group_name = "batch"
  node_role_arn   = aws_iam_role.node.arn
  subnet_ids      = var.private_subnet_ids
  capacity_type   = "SPOT"
  instance_types  = ["m6i.large", "m5.large", "m6a.large"]

  scaling_config {
    desired_size = 2
    min_size     = 0
    max_size     = 10
  }

  taint {
    key    = "workload"
    value  = "batch"
    effect = "NO_SCHEDULE"
  }
}
```
@check
Who creates the EC2 instances of a managed group? || EKS, through an Auto Scaling group in your account.
@end

@concept Node AMIs and operating systems
@plain
EKS provides optimized AMIs: Amazon Linux 2023, Bottlerocket (a minimal container OS), Windows, and GPU/accelerated variants.
@problem
General Linux images carry packages you do not need and require patching; node OS patching is a security routine.
@does
- **AL2023** is the current default Amazon Linux for new nodes (AL2 is end of life, check the support date).
- **Bottlerocket**: read-only root file system, API-driven updates, smaller attack surface.
- Nodes are replaced, not patched: update the AMI version and roll the group.
- Access nodes with **SSM Session Manager** instead of SSH keys.
@diagram cmp
caption: Picking an AMI family
cards:
  - {h: "AL2023", kind: app, items: ["General purpose", "Familiar shell and packages"]}
  - {h: "Bottlerocket", kind: ok, items: ["Minimal and immutable", "Fast updates, less flexibility"]}
  - {h: "Windows", kind: warn, items: ["Windows containers only", "Higher cost and limits"]}
@h Find the recommended AMI
```bash title="Latest recommended AMI id from SSM" nocheck
aws ssm get-parameter --name /aws/service/eks/optimized-ami/{{v.eks_to}}/amazon-linux-2023/x86_64/standard/recommended/image_id \
  --query Parameter.Value --output text
```
@check
Why use SSM Session Manager for node access? || It needs no inbound ports or SSH keys and logs sessions through IAM and CloudTrail.
@end

@concept Updating node groups
@plain
Updating a group replaces its nodes with new ones using a newer AMI or Kubernetes version, one batch at a time.
@problem
A node upgrade must not drop traffic. Draining evicts pods, so the cluster needs enough spare capacity and sane budgets.
@does
- `maxUnavailable` (count or percent) in `updateConfig` controls the batch size.
- Pods with a PodDisruptionBudget that cannot be satisfied block the drain; the update fails after a timeout unless forced.
- Order: control plane first, then add-ons, then nodes. Nodes may lag the control plane by a limited number of minor versions (check the version skew policy).
@diagram flow
caption: Rolling node replacement
numbered: true
nodes:
  - "Launch new node|new AMI|info"
  - "Cordon old node|no new pods|warn"
  - "Drain|honor PDBs|app"
  - "Terminate old|EC2 removed|ok"
@h Command
```bash title="Rolling update" nocheck
aws eks update-nodegroup-version --cluster-name shop-prod --nodegroup-name general
aws eks update-nodegroup-config --cluster-name shop-prod --nodegroup-name general \
  --update-config maxUnavailablePercentage=33
aws eks wait nodegroup-active --cluster-name shop-prod --nodegroup-name general
```
:::warn
After Gardener- or controller-driven maintenance, verify no node stays cordoned: `kubectl get nodes` should not show SchedulingDisabled.
:::
@check
What stops a drain from completing? || A PodDisruptionBudget that cannot be satisfied, or pods without a controller to recreate them.
@end

@concept Fargate
@plain
Fargate runs each pod in its own small, AWS-managed micro VM. There are no nodes for you to patch or scale.
@problem
Small teams or bursty jobs may not want node management at all, and some compliance cases want per-pod isolation.
@does
- A **Fargate profile** selects pods by namespace and labels; matching pods go to Fargate automatically.
- Each pod gets its own ENI and IP in private subnets; billing is per vCPU and memory requested, rounded up to supported sizes.
- Limits: no DaemonSets, no privileged pods, no hostPath or hostNetwork, no GPUs, EBS volumes unsupported (EFS works). Check current limits.
- Pods start slower than on warm nodes.
- Logging is via the built-in Fluent Bit router configured with a ConfigMap `aws-logging` in `aws-observability`.
@diagram flow
caption: Profile matching
nodes:
  - "Pod created|namespace batch|app"
  - "Admission webhook|matches profile|cp"
  - "Fargate micro VM|one pod each|env"
  - "Private subnet ENI|own IP|info"
@h Profile
```bash title="Create a profile" nocheck
eksctl create fargateprofile --cluster shop-prod --name batch \
  --namespace batch --labels tier=serverless
```
@check
Can a DaemonSet run on Fargate? || No; each pod has its own micro VM and DaemonSets are not supported.
@end

@concept Choosing compute
@plain
Match compute to the workload, and keep a small stable system node group even if you use Karpenter.
@problem
Using one compute type for everything either wastes money or blocks features.
@does
- Run controllers such as Karpenter itself on a managed node group or Fargate, so they never depend on the capacity they create.
- Use Karpenter or Spot groups for stateless scalable workloads.
- Use dedicated groups with taints for GPU, high memory or licensed software.
@choose Compute choice
Managed node group | stable baseline, system add-ons, predictable pools | you want per-pod right sizing and fast scale
Karpenter | variable workloads and cost optimisation | you need only a handful of fixed nodes
Fargate | isolated jobs, no node ops | you need DaemonSets, GPUs or EBS
Spot | stateless, interruption tolerant | databases and single replicas
@diagram layers
caption: Typical production layout
layers:
  - {label: "Baseline", nodes: ["System MNG|CoreDNS, Karpenter, ingress|cp"]}
  - {label: "Elastic", nodes: ["Karpenter on-demand|web tier|app", "Karpenter Spot|workers|env"]}
  - {label: "Special", nodes: ["GPU pool|taint gpu|warn", "Fargate|ad hoc jobs|ext"]}
@end
