---
title: ECS services, discovery and App Runner
minutes: 50
objectives:
  - Run ECS services with load balancers, deployments and autoscaling
  - Use capacity providers and service discovery
  - Decide between ECS, EKS and App Runner for a workload
---
After tasks run, services need traffic, scaling, safe deployments and a way to find each other. This section also compares ECS with EKS and App Runner.

@concept ECS services and deployments
@plain
A service keeps the desired number of tasks running and replaces failed ones. It also performs rolling or blue/green deployments of new task definition revisions.
@problem
Manually starting and replacing containers does not give zero downtime updates.
@does
- Rolling update (ECS controller) uses `minimumHealthyPercent` and `maximumPercent`. With desired 4, min 100 and max 200, ECS starts up to 4 new tasks before stopping old ones.
- The **deployment circuit breaker** stops a failing rollout and can roll back automatically.
- Blue/green through CodeDeploy, or the native ECS blue/green strategy where available (check the current documentation).
- Health: ALB target health plus container health checks.
@diagram flow
caption: Rolling deployment
numbered: true
nodes:
  - "New revision|task definition web:12|app"
  - "Start new tasks|up to maximum percent|info"
  - "Healthy|pass ALB checks|ok"
  - "Stop old tasks|drain|warn"
@h Service with circuit breaker
```hcl title="service.tf"
resource "aws_ecs_service" "web" {
  name            = "web"
  cluster         = aws_ecs_cluster.shop.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 4
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets         = var.private_subnet_ids
    security_groups = [aws_security_group.web.id]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }
}
```
@check
Desired 4, min healthy 100, max 200. How many tasks can run at once during deploy? || Up to 8.
@end

@concept Service auto scaling
@plain
Application Auto Scaling changes a service's desired count based on metrics.
@problem
Fixed task counts waste money at night and fail under peak load.
@does
- **Target tracking** on `ECSServiceAverageCPUUtilization`, memory, or ALB `RequestCountPerTarget`.
- **Step** and **scheduled** scaling are also available.
- Set min and max capacity and sensible cooldowns.
- Scale-in protects against dropped requests through ALB deregistration delay.
@diagram flow
caption: Target tracking
nodes:
  - "Metric|CPU 70 percent target|info"
  - "Autoscaling|adjusts desired count|cp"
  - "Service|tasks added or removed|app"
@h Policy
```hcl title="autoscale.tf"
resource "aws_appautoscaling_target" "web" {
  service_namespace  = "ecs"
  resource_id        = "service/shop/web"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = 2
  max_capacity       = 20
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "cpu70"
  policy_type        = "TargetTrackingScaling"
  service_namespace  = aws_appautoscaling_target.web.service_namespace
  resource_id        = aws_appautoscaling_target.web.resource_id
  scalable_dimension = aws_appautoscaling_target.web.scalable_dimension
  target_tracking_scaling_policy_configuration {
    target_value = 70
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
```
@check
Which metric scales on traffic share per task behind an ALB? || ALBRequestCountPerTarget.
@end

@concept Capacity providers
@plain
A **capacity provider** tells a cluster where tasks may run: Fargate, Fargate Spot or an Auto Scaling group of EC2 instances.
@problem
You want a cheap Spot share with an on-demand baseline, or automatic EC2 scaling to fit tasks.
@does
- Strategy: `base` guarantees a minimum on one provider; `weight` splits the rest.
- Example: base 2 on FARGATE, then weight 1 FARGATE and weight 3 FARGATE_SPOT. For 10 tasks, 2 base plus 8 split 1:3 gives 2 + 2 = 4 on FARGATE and 6 on Spot.
- EC2 providers use **managed scaling** to add instances when tasks are pending.
- Fargate Spot tasks may be interrupted with a two minute warning (SIGTERM); handle it.
@diagram cmp
caption: Strategy split
cards:
  - {h: "FARGATE", kind: ok, items: ["Base 2", "Weight 1", "4 of 10 tasks"]}
  - {h: "FARGATE_SPOT", kind: warn, items: ["Weight 3", "Cheaper, can be interrupted", "6 of 10 tasks"]}
@h Strategy
```hcl title="capacity.tf"
resource "aws_ecs_cluster_capacity_providers" "shop" {
  cluster_name       = aws_ecs_cluster.shop.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"]
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    base              = 2
    weight            = 1
  }
  default_capacity_provider_strategy {
    capacity_provider = "FARGATE_SPOT"
    weight            = 3
  }
}
```
@end

@concept Service discovery and Service Connect
@plain
Services find each other by name. **Cloud Map** gives DNS names; **ECS Service Connect** adds a managed proxy with retries, metrics and short names.
@problem
Task IPs change on every deployment, so hard coded addresses break.
@does
- Cloud Map service discovery registers task IPs in a private DNS namespace.
- Service Connect defines a namespace and port aliases; a sidecar proxy handles load balancing, outlier detection and per-request metrics.
- Alternative: an internal ALB per service, simple but costs per ALB.
- For cross-cluster or cross-VPC, consider VPC Lattice.
@diagram flow
caption: Service Connect
nodes:
  - "web task|calls http://orders|app"
  - "Proxy sidecar|resolve and retry|cp"
  - "orders tasks|healthy endpoints|app"
@h Namespace
```bash title="Create namespace" nocheck
aws servicediscovery create-private-dns-namespace --name shop.local --vpc vpc-0abc123
aws ecs update-service --cluster shop --service web --service-connect-configuration enabled=true,namespace=shop.local
```
@check
Why not use task IPs directly? || They change on every task replacement.
@end

@concept ECS versus EKS
@plain
ECS is simple and AWS specific. EKS is Kubernetes, portable, with a large ecosystem and more to operate.
@problem
Teams adopt Kubernetes for fashion and then carry its operational weight without needing it.
@does
- ECS: no cluster upgrades, no control plane fee, IAM native, fewer concepts. Best for AWS-only teams with modest scale and few platform engineers.
- EKS: Helm, operators, CRDs, service mesh, portability, hiring pool; control plane billed per cluster per hour (check current pricing) plus upgrade work.
- Both run on Fargate or EC2; both integrate with ALB, IAM and CloudWatch.
- Switching later is a rewrite of manifests and deployment tooling, not of the containers.
@diagram cmp
caption: Decision inputs
cards:
  - {h: "ECS", kind: ok, items: ["Fewer moving parts", "No version upgrades", "AWS only"]}
  - {h: "EKS", kind: cp, items: ["Kubernetes ecosystem", "Portable APIs", "More operations"]}
@choose Orchestrator
ECS on Fargate | small team and plain web services | you need CRDs, operators or Helm charts
EKS | you already use Kubernetes tooling and need portability | nobody owns cluster upgrades
App Runner | a single web service from image or source | you need sidecars or private non-HTTP services
@check
Name two reasons to choose EKS over ECS. || Kubernetes ecosystem and portability (Helm, operators, CRDs); existing Kubernetes skills.
@end

@concept AWS App Runner
@plain
App Runner builds or pulls your web app and runs it with HTTPS, scaling and a load balancer, with almost no configuration.
@problem
Small teams want to deploy a container web app without learning VPCs, ALBs and task definitions.
@does
- Source: ECR image or a code repository (supported runtimes).
- Auto scaling on concurrency, with a configurable minimum so there is no cold start. Billed for provisioned memory while idle and vCPU while active.
- Optional **VPC connector** for outbound private access, and private ingress via a VPC endpoint.
- Limits: HTTP-only services, no sidecars, fewer controls. Check the current service availability notes before starting new projects.
@diagram flow
caption: App Runner
nodes:
  - "ECR image|or source repo|info"
  - "App Runner service|scaling and TLS|cp"
  - "HTTPS URL|managed domain|ext"
  - "VPC connector|private database|ok"
@h Terraform
```hcl title="apprunner.tf"
resource "aws_apprunner_service" "web" {
  service_name = "web"
  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.apprunner_ecr.arn
    }
    image_repository {
      image_identifier      = "111122223333.dkr.ecr.eu-west-1.amazonaws.com/web:1.4.2"
      image_repository_type = "ECR"
      image_configuration {
        port = "8080"
      }
    }
  }
}
```
@end

@concept ECS troubleshooting
@plain
Most ECS issues sit in a few places: image pull, health checks, memory limits and permissions.
@problem
Tasks flap between running and stopped and the service never becomes stable.
@does
- `CannotPullContainerError`: no route to ECR or missing execution role permission.
- `Task failed ELB health checks`: wrong health check path or port, or the app is slow to start; use a health check grace period.
- Exit code 137: killed for out of memory or SIGKILL; raise memory.
- `ResourceInitializationError`: secrets or ENI setup failed, often missing endpoints.
- Use service events: `aws ecs describe-services` shows recent messages.
@diagram flow
caption: Triage order
numbered: true
nodes:
  - "Service events|why tasks stop|warn"
  - "Stopped reason|describe-tasks|info"
  - "Container logs|CloudWatch|info"
  - "Network and roles|endpoints, SGs, IAM|cp"
@h Read recent events
```bash title="Service events" lab
aws ecs describe-services --cluster shop --services web --query 'services[0].events[:5].[createdAt,message]' --output table
```
@check
A task exits with code 137. What is the first suspect? || Out of memory kill; check memory limits and usage.
@end
