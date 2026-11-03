---
title: Lifecycle hooks, instance refresh and warm pools
minutes: 45
objectives:
  - Use lifecycle hooks to run work on launch and terminate with correct timeouts
  - Roll out a new AMI using instance refresh with checkpoints and rollback
  - Reduce scale-out latency with warm pools and understand when they pay off
---
Production fleets need controlled starts, graceful shutdowns and safe rollouts. These three features provide them.

@concept Lifecycle hooks
@plain
A **lifecycle hook** pauses an instance in a wait state when it launches or before it terminates, so your automation can finish its work first.
@problem
Without a hook, an instance enters service the moment it boots (before config is ready) and is removed instantly on scale-in, cutting off in-flight jobs and skipping log upload.
@does
- States: `Pending:Wait` on launch and `Terminating:Wait` on terminate.
- The ASG publishes a notification to EventBridge, SNS or SQS. Your automation does the work, then calls `complete-lifecycle-action` with CONTINUE or ABANDON.
- `HeartbeatTimeout` is how long to wait (default one hour); `record-lifecycle-action-heartbeat` extends it. `DefaultResult` applies on timeout.
- On Kubernetes, the node termination handler or Karpenter handles this role for you.
@diagram seq
caption: Terminate hook
actors: ["ASG|scale-in|cp", "EventBridge|notification|info", "Automation|Lambda or SSM|app", "Instance|being removed|env"]
steps:
  - "0>3: Terminating:Wait | req"
  - "0>1: lifecycle event | req"
  - "1>2: run drain job | req"
  - "2>3: drain pods, upload logs | req"
  - "2>0: complete-lifecycle-action CONTINUE | resp"
@h Hook and completion
```hcl title="hook.tf"
resource "aws_autoscaling_lifecycle_hook" "drain" {
  name                   = "drain"
  autoscaling_group_name = aws_autoscaling_group.web.name
  lifecycle_transition   = "autoscaling:EC2_INSTANCE_TERMINATING"
  heartbeat_timeout      = 300
  default_result         = "CONTINUE"
}
```
```bash title="Complete from automation" lab
aws autoscaling complete-lifecycle-action --lifecycle-hook-name drain --auto-scaling-group-name web \
  --lifecycle-action-result CONTINUE --instance-id i-0123456789abcdef0
aws autoscaling describe-lifecycle-hooks --auto-scaling-group-name web
```
:::warn
If your automation fails and the default result is CONTINUE, the instance terminates without cleanup. Choose the default deliberately and alarm on hook timeouts.
:::
@check
What happens when a hook times out? || The ASG applies the DefaultResult (CONTINUE or ABANDON).
@end

@concept Instance refresh
@plain
**Instance refresh** replaces instances in an ASG gradually so they pick up a new template version, while keeping a minimum healthy percentage.
@problem
Changing a template does nothing to running instances. Terminating all at once causes an outage.
@does
- `MinHealthyPercentage` sets how much capacity must stay healthy; `InstanceWarmup` sets the wait before counting a new instance healthy.
- **Checkpoints** pause the refresh at percentages (for example 20 and 50) so you can verify before continuing.
- **Auto rollback** returns to the previous configuration if alarms fire or the refresh fails (check the current documentation for supported triggers).
- Skip-matching skips instances already on the target configuration.
@diagram flow
caption: Rolling replacement with a checkpoint
numbered: true
nodes:
  - "Start refresh|new template version|cp"
  - "Replace 20 percent|keep 90 percent healthy|app"
  - "Checkpoint|pause and verify|warn"
  - "Continue|remaining instances|app"
  - "Complete|ok|ok"
@h Start and monitor
```bash title="Refresh" lab
aws autoscaling start-instance-refresh --auto-scaling-group-name web \
  --preferences '{"MinHealthyPercentage":90,"InstanceWarmup":120,"CheckpointPercentages":[20,50],"CheckpointDelay":600,"AutoRollback":true,"SkipMatching":true}'
aws autoscaling describe-instance-refreshes --auto-scaling-group-name web \
  --query 'InstanceRefreshes[0].[Status,PercentageComplete,StatusReason]'
aws autoscaling cancel-instance-refresh --auto-scaling-group-name web
```
```hcl title="refresh-in-terraform.tf"
resource "aws_autoscaling_group" "web_refresh" {
  name                = "web-refresh"
  min_size            = 3
  max_size            = 9
  vpc_zone_identifier = var.private_subnet_ids

  launch_template {
    id      = aws_launch_template.web.id
    version = aws_launch_template.web.latest_version
  }

  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 90
      instance_warmup        = 120
    }
  }
}
```
@check
Does updating the launch template version replace running instances? || No. You need an instance refresh (or manual replacement) to roll it out.
@end

@concept Warm pools
@plain
A **warm pool** keeps pre-initialised instances stopped (or hibernated or running) next to the ASG, so scale-out takes seconds instead of the full boot time.
@problem
Applications with long initialisation (large images, big caches, JVM warm-up) cannot respond to sudden spikes if each instance takes several minutes.
@does
- Pool states: `Stopped` (pay only for EBS), `Hibernated`, or `Running`.
- On scale-out the ASG takes instances from the pool first, then launches from scratch if the pool is empty.
- Lifecycle hooks run when instances enter the pool, so pre-initialisation work is done once.
- Costs: EBS and, for running, full instance cost. Savings: lower over-provisioning. Check current pricing and support for your instance types; EKS support has specific requirements.
@diagram flow
caption: Pool in front of the group
nodes:
  - "Warm pool|stopped, initialised|info"
  - "Scale-out event|spike|warn"
  - "Start instance|seconds|app"
  - "In service|ok|ok"
@h Add a pool
```bash title="Warm pool" lab
aws autoscaling put-warm-pool --auto-scaling-group-name web --pool-state Stopped \
  --min-size 2 --max-group-prepared-capacity 6 --instance-reuse-policy ReuseOnScaleIn=true
aws autoscaling describe-warm-pool --auto-scaling-group-name web --query 'Instances[].[InstanceId,LifecycleState]'
```
@choose Reducing scale-out time
Smaller, faster image (baked AMI) | any fleet; always first | image is already minimal
Warm pool | boot plus init takes minutes and spikes are sharp | scale events are slow and predictable
Predictive scaling | repeating daily pattern | traffic is random
Over-provision | cannot tolerate any delay | cost is tight
@end

@concept Auto Scaling for EKS and Karpenter
@plain
EKS managed node groups use ASGs. **Karpenter** and **Cluster Autoscaler** decide when nodes are needed from pending pods.
@problem
Pod autoscaling alone cannot create capacity; something must add nodes when pods are unschedulable.
@does
- **Cluster Autoscaler** changes ASG desired capacity based on pending pods and node utilisation; needs ASG tags `k8s.io/cluster-autoscaler/enabled`.
- **Karpenter** launches instances directly (no ASG) matching pod requirements, consolidating and replacing nodes, and handles Spot interruptions.
- Order of scaling: HPA or KEDA scales pods, then the node autoscaler adds nodes.
- Do not put manual scaling policies on an ASG managed by Cluster Autoscaler.
@diagram flow
caption: Pod to node scaling
numbered: true
nodes:
  - "HPA|more pod replicas|app"
  - "Pods pending|no room|warn"
  - "Cluster Autoscaler or Karpenter|add nodes|cp"
  - "Node ready|pods scheduled|ok"
@h Cluster Autoscaler tags
```hcl title="ca-tags.tf"
resource "aws_autoscaling_group" "ng" {
  name                = "eks-ng"
  min_size            = 2
  max_size            = 10
  vpc_zone_identifier = var.private_subnet_ids
  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }
  tag {
    key                 = "k8s.io/cluster-autoscaler/enabled"
    value               = "true"
    propagate_at_launch = false
  }
  tag {
    key                 = "k8s.io/cluster-autoscaler/prod"
    value               = "owned"
    propagate_at_launch = false
  }
}
```
:::note
Item 9 of this track covers Karpenter in depth. Here the key point is that the ASG remains a building block for managed node groups.
:::
@check
What triggers node scale-out in Kubernetes? || Pods that cannot be scheduled (Pending), which Cluster Autoscaler or Karpenter react to.
@end
