---
title: ECS and Fargate tasks
minutes: 55
objectives:
  - Describe clusters, task definitions, tasks and services
  - Write a Fargate task definition with correct roles and logging
  - Choose between Fargate and EC2 launch types
---
Amazon ECS is AWS's own container orchestrator. It is simpler than Kubernetes and deeply integrated with IAM, load balancers and CloudWatch.

@concept ECS building blocks
@plain
A **cluster** groups capacity. A **task definition** describes containers. A **task** is a running instance of it. A **service** keeps a desired number of tasks running.
@problem
You need to run containers reliably without managing a control plane.
@does
- The ECS control plane is free and fully managed. You pay for the compute (Fargate or EC2).
- Task definitions are versioned as `family:revision`.
- Run once with `RunTask` (batch) or continuously with a service (web).
- Compute: **Fargate** (serverless), **EC2** (your instances) or ECS Anywhere (your hardware).
@diagram layers
caption: ECS objects
layers:
  - {label: "Definition", nodes: ["Task definition|family and revision|info"]}
  - {label: "Runtime", nodes: ["Service|desired count|cp", "Task|running containers|app"]}
  - {label: "Capacity", nodes: ["Fargate|serverless|ok", "EC2 instances|you manage|env"]}
@h List
```bash title="Inspect" nocheck
aws ecs list-clusters
aws ecs describe-services --cluster shop --services web --query 'services[].[serviceName,desiredCount,runningCount]'
```
@check
What keeps a number of tasks running and replaces failed ones? || An ECS service.
@end

@concept Task definition anatomy
@plain
The task definition lists containers, images, CPU and memory, ports, environment, secrets, logging and roles.
@problem
The same image needs different resources and settings in each environment, and secrets must not be baked in.
@does
- Fargate requires `networkMode: awsvpc`, and task-level `cpu` and `memory` from supported combinations (check the current table).
- `essential: true` containers stop the whole task if they exit.
- `secrets` inject values from Secrets Manager or Parameter Store at start.
- Logging with the `awslogs` driver sends stdout to CloudWatch Logs.
- Fargate platform includes ephemeral storage (20 GiB default, configurable up to a higher maximum; check the current quota).
@diagram flow
caption: Inside a definition
nodes:
  - "Task cpu and memory|sizes the task|cp"
  - "Container web|image and ports|app"
  - "Sidecar|logging or proxy|info"
  - "Roles|execution and task|warn"
@h Fargate task definition
```json title="taskdef.json"
{
  "family": "web",
  "requiresCompatibilities": ["FARGATE"],
  "networkMode": "awsvpc",
  "cpu": "512",
  "memory": "1024",
  "runtimePlatform": {"cpuArchitecture": "ARM64", "operatingSystemFamily": "LINUX"},
  "executionRoleArn": "arn:aws:iam::111122223333:role/ecsExecution",
  "taskRoleArn": "arn:aws:iam::111122223333:role/webTask",
  "containerDefinitions": [{
    "name": "web",
    "image": "111122223333.dkr.ecr.eu-west-1.amazonaws.com/web:1.4.2",
    "essential": true,
    "portMappings": [{"containerPort": 8080}],
    "secrets": [{"name": "DB_PASSWORD", "valueFrom": "arn:aws:secretsmanager:eu-west-1:111122223333:secret:db-AbCdEf"}],
    "logConfiguration": {
      "logDriver": "awslogs",
      "options": {"awslogs-group": "/ecs/web", "awslogs-region": "eu-west-1", "awslogs-stream-prefix": "web"}
    }
  }]
}
```
@end

@concept Task role versus execution role
@plain
Two roles apply. The **execution role** lets ECS pull the image, write logs and fetch secrets. The **task role** is what your application code uses to call AWS.
@problem
Mixing them gives the app permissions it should not have, or leaves ECS unable to start the task.
@does
- Execution role: ECR pull, `logs:CreateLogStream`, `logs:PutLogEvents`, secret read for injected values. Use the managed policy `AmazonECSTaskExecutionRolePolicy` plus secret access.
- Task role: trusts `ecs-tasks.amazonaws.com`, holds only the application permissions.
- Credentials reach the container through the task metadata credential endpoint, so the SDK works with no keys.
- Each service should have its own task role.
@diagram seq
caption: Who uses which role
actors: ["ECS agent|platform|cp", "ECR and Secrets|AWS|ext", "App code|container|app"]
steps:
  - "0>1: pull image and secrets | tls"
  - "note 0..0: uses execution role"
  - "2>1: call S3 or DynamoDB | req"
  - "note 2..2: uses task role"
@h Trust policy
```json title="task-role-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ecs-tasks.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
```
@check
The task cannot pull the image from ECR. Which role is missing a permission? || The execution role.
@end

@concept Fargate networking and sizing
@plain
Each Fargate task gets its own ENI and private IP in your subnet (`awsvpc`), with its own security group.
@problem
Tasks must reach registries and AWS APIs, and be reachable only by the right sources.
@does
- Tasks in private subnets need NAT or VPC endpoints for ECR (api and dkr), S3 (gateway), CloudWatch Logs and Secrets Manager.
- Every task consumes one IP, so size subnets for peak tasks plus deployments.
- Security group per service: allow the app port from the load balancer security group only.
- Sizing example: 4 tasks at 0.5 vCPU and 1 GB. Total 2 vCPU and 4 GB. Use measured utilisation to right size.
@diagram flow
caption: Private subnet needs
nodes:
  - "Task ENI|private IP|app"
  - "VPC endpoints|ECR, logs, secrets|ok"
  - "S3 gateway endpoint|image layers|ok"
  - "ALB|ingress|cp"
@h Security group reference
```hcl title="ecs-sg.tf"
resource "aws_vpc_security_group_ingress_rule" "web_from_alb" {
  security_group_id            = aws_security_group.web.id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
```
@end

@concept Fargate versus EC2 launch type
@plain
Fargate runs tasks without you managing servers. The EC2 launch type runs tasks on your own instances.
@problem
Choosing wrongly means paying for idle servers or lacking features such as GPUs.
@does
- Fargate: per second billing for vCPU and memory, strong task isolation, no patching, Spot and ARM supported.
- EC2: lower unit cost at high steady utilisation with Savings Plans, GPUs, large sizes, daemon tasks, host access.
- Mixed with capacity providers in one cluster.
- Fargate does not support privileged containers or host networking.
@diagram cmp
caption: Launch types
cards:
  - {h: "Fargate", kind: ok, items: ["No servers", "Per task billing", "Isolated per task", "Fast to adopt"]}
  - {h: "EC2", kind: info, items: ["You patch hosts", "GPU and special hardware", "Cheaper when packed", "Daemon tasks"]}
@choose Compute choice
Fargate | small team and variable load | you need GPUs or privileged mode
EC2 | steady high utilisation or special hardware | nobody can patch and scale instances
@check
Which launch type supports privileged containers? || EC2, not Fargate.
@end

@concept Logging, metrics and ECS Exec
@plain
ECS sends container output to CloudWatch Logs and metrics to CloudWatch; **ECS Exec** opens a shell in a running container using SSM.
@problem
Containers are ephemeral; you cannot SSH in, yet you must debug.
@does
- `awslogs` or FireLens (Fluent Bit) route logs to CloudWatch, S3 or third parties.
- Container Insights adds task level CPU, memory and network metrics.
- ECS Exec needs `enableExecuteCommand`, the Session Manager plugin and task role SSM messages permissions. Commands are logged via CloudTrail and can be logged to S3 or CloudWatch.
- Task stopped reasons appear in `describe-tasks` (for example `CannotPullContainerError`).
@diagram flow
caption: Debug a task
nodes:
  - "Stopped reason|describe-tasks|warn"
  - "Logs|CloudWatch|info"
  - "ECS Exec|shell via SSM|app"
@h Open a shell
```bash title="ECS Exec" nocheck
aws ecs execute-command --cluster shop --task "$TASK_ID" --container web --interactive --command "/bin/sh"
aws ecs describe-tasks --cluster shop --tasks "$TASK_ID" --query 'tasks[].stoppedReason'
```
@check
What does a CannotPullContainerError usually point to? || Missing network path to the registry or missing execution role permission.
@end
