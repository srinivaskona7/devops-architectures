---
title: Auto Scaling groups and launch templates
minutes: 45
objectives:
  - Create an Auto Scaling group from a launch template across several AZs
  - Explain health checks, capacity limits and AZ rebalancing
  - Use mixed instances and attribute-based selection for resilient capacity
---
An **Auto Scaling group (ASG)** keeps a fleet of EC2 instances at the size you ask for, replaces failed ones and spreads them across AZs. EKS managed node groups are ASGs underneath.

@concept What an ASG does
@plain
An ASG is a controller. You say minimum, desired and maximum instance counts and which template to use; it launches and terminates instances to match.
@problem
Manually replacing a failed instance or adding capacity at peak is slow and error prone, and nobody is awake at 3 a.m.
@does
- Holds `MinSize`, `MaxSize` and `DesiredCapacity`; scaling policies change desired capacity within the bounds.
- Spreads instances across the subnets (AZs) you give it and rebalances if an AZ becomes uneven.
- Replaces instances that fail EC2 status checks, and optionally ELB health checks.
- Registers instances with load balancer target groups automatically.
@diagram flow
caption: Reconciliation loop
nodes:
  - "Desired capacity|set by you or a policy|cp"
  - "ASG compares|with running healthy count|info"
  - "Launch or terminate|from the template|app"
  - "Register|target group|ok"
@h Create one
```hcl title="asg.tf"
resource "aws_autoscaling_group" "web" {
  name                      = "web"
  min_size                  = 2
  max_size                  = 12
  desired_capacity          = 3
  vpc_zone_identifier       = var.private_subnet_ids
  health_check_type         = "ELB"
  health_check_grace_period = 120
  target_group_arns         = [aws_lb_target_group.web.arn]

  launch_template {
    id      = aws_launch_template.web.id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "web"
    propagate_at_launch = true
  }
}
```
```bash title="Inspect" lab
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names web \
  --query 'AutoScalingGroups[].[DesiredCapacity,MinSize,MaxSize,Instances[].[InstanceId,AvailabilityZone,LifecycleState,HealthStatus]]'
aws autoscaling describe-scaling-activities --auto-scaling-group-name web --max-items 5 \
  --query 'Activities[].[StartTime,StatusCode,Description]' --output table
```
@check
Which values bound what a scaling policy can do? || MinSize and MaxSize; policies only change DesiredCapacity inside them.
@end

@concept Launch templates in an ASG
@plain
The ASG reads the launch template at each launch. Which version it uses is a setting on the group.
@problem
Using `$Latest` means any template edit changes future launches silently; pinning a version makes changes explicit.
@does
- Template versions are immutable. Reference a number, `$Default` or `$Latest`.
- Changing the version affects only new instances; existing instances keep their old configuration until replaced via **instance refresh**.
- Launch configurations are deprecated; use templates.
- Put IMDSv2, encrypted volumes, tags and the instance profile in the template.
@diagram flow
caption: Rolling a new image
numbered: true
nodes:
  - "New template version|new AMI|info"
  - "Set ASG version|number or default|cp"
  - "Instance refresh|replace gradually|app"
  - "All instances new|ok|ok"
@h Update the template
```bash title="Version and point the ASG" lab
aws ec2 create-launch-template-version --launch-template-id lt-0123456789abcdef0 \
  --source-version 3 --launch-template-data '{"ImageId":"ami-0123456789abcdef0"}'
aws autoscaling update-auto-scaling-group --auto-scaling-group-name web \
  --launch-template LaunchTemplateId=lt-0123456789abcdef0,Version='4'
```
@end

@concept Health checks and grace period
@plain
An ASG decides an instance is unhealthy from EC2 status checks, and optionally from the load balancer's view.
@problem
If only EC2 checks are used, an instance with a crashed application still looks healthy. If the grace period is too short, new instances are killed before they finish booting.
@does
- Set `health_check_type = ELB` to also use target group health.
- **Health check grace period** is the time after launch before checks count. Set it longer than your slowest bootstrap.
- Manually mark an instance unhealthy with `set-instance-health`, or protect from scale-in with instance protection.
- Pair with a lifecycle hook for cleaner bootstraps.
@diagram flow
caption: Why the grace period exists
nodes:
  - "Launch|instance pending|info"
  - "Boot and install|user data runs|warn"
  - "Grace period ends|checks begin|cp"
  - "Healthy|stays in service|ok"
@h Mark and protect
```bash title="Health operations" lab
aws autoscaling set-instance-health --instance-id i-0123456789abcdef0 --health-status Unhealthy
aws autoscaling set-instance-protection --auto-scaling-group-name web --instance-ids i-0123456789abcdef0 --protected-from-scale-in
```
:::warn
A grace period of 0 with ELB checks and a slow bootstrap causes a launch and kill loop. Watch scaling activities for repeated replacements.
:::
@check
What problem does the grace period solve? || It stops the ASG from replacing instances that are still booting and not yet able to pass health checks.
@end

@concept Availability Zones and rebalancing
@plain
An ASG tries to keep an equal number of instances per AZ. If an AZ fails or lacks capacity, it launches elsewhere.
@problem
A single-AZ fleet fails with its AZ. Unbalanced fleets lose more capacity in an outage.
@does
- Provide subnets in at least two AZs (three is common).
- **AZ rebalancing** terminates and relaunches instances to restore balance, after launching new ones first. Disable it with the `AZRebalance` suspend process if your workload cannot tolerate it, though that reduces resilience.
- **Capacity rebalancing** (for Spot) launches a replacement when AWS signals a rebalance recommendation.
- For EKS, size per-AZ node groups when using EBS volumes because volumes are AZ bound.
@diagram layers
caption: Balanced fleet
layers:
  - {label: "AZ a", nodes: ["2 instances|app|app"]}
  - {label: "AZ b", nodes: ["2 instances|app|app"]}
  - {label: "AZ c", nodes: ["2 instances|app|app"]}
@h Suspend a process
```bash title="Process control" lab
aws autoscaling suspend-processes --auto-scaling-group-name web --scaling-processes AZRebalance
aws autoscaling resume-processes  --auto-scaling-group-name web --scaling-processes AZRebalance
aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names web --query 'AutoScalingGroups[].SuspendedProcesses'
```
@end

@concept Mixed instances and attribute-based selection
@plain
A single instance type can run out of capacity or Spot supply. A **mixed instances policy** lets one ASG use several types and purchase options.
@problem
Hard-coding one type causes `InsufficientInstanceCapacity` and expensive, interrupted Spot fleets.
@does
- `instances_distribution` sets On-Demand base, percentage above the base, and the Spot allocation strategy.
- **Attribute-based instance type selection** lets you state requirements (vCPU, memory range, architecture) instead of listing types.
- Use **weights** (`weighted_capacity`) when types differ in size, so desired capacity is measured in units such as vCPUs.
- Keep all types comparable in performance; otherwise load balancing becomes uneven.
@diagram cmp
caption: Listing types versus attributes
cards:
  - {h: "Explicit types", kind: info, items: ["You control the exact list", "Must update for new generations"]}
  - {h: "Attribute based", kind: ok, items: ["State vCPU and memory range", "New types picked up automatically"]}
@h Attribute-based override
```hcl title="abis.tf"
resource "aws_autoscaling_group" "flex" {
  name                = "flex"
  min_size            = 2
  max_size            = 30
  vpc_zone_identifier = var.private_subnet_ids

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = 1
      on_demand_percentage_above_base_capacity = 20
      spot_allocation_strategy                 = "price-capacity-optimized"
    }
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.worker.id
        version            = "$Latest"
      }
      override {
        instance_requirements {
          vcpu_count {
            min = 4
            max = 8
          }
          memory_mib {
            min = 8192
            max = 32768
          }
          cpu_manufacturers     = ["intel", "amd"]
          burstable_performance = "excluded"
        }
      }
    }
  }
}
```
@check
What does an On-Demand base capacity of 2 mean? || The first two instances are always On-Demand; the rest follow the Spot/On-Demand percentage.
@end
