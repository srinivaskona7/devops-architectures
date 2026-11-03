---
title: CodeDeploy deployment strategies
minutes: 45
objectives:
  - Describe CodeDeploy for EC2, Lambda and ECS compute platforms
  - Write an appspec and choose in-place, rolling, canary and blue/green configurations
  - Wire alarms and hooks for automatic rollback
---
CodeDeploy automates application releases so that a bad version is caught and rolled back before all users see it.

@concept What CodeDeploy does
@plain
CodeDeploy coordinates releasing a new revision to a fleet, a Lambda alias or an ECS service, following an `appspec` file and a deployment configuration.
@problem
Scripts that SSH to servers cannot shift traffic gradually, check health or roll back reliably.
@does
- Three compute platforms: EC2 or on-premises (agent based), AWS Lambda, Amazon ECS.
- An **application** holds **deployment groups**; a deployment applies a revision.
- Integrates with Auto Scaling groups, load balancers, CloudWatch alarms and SNS.
- No extra charge for EC2, Lambda or ECS targets; on-premises instances are billed (check current pricing).
@diagram cmp
caption: Three platforms
cards:
  - {h: "EC2 and on-premises", kind: info, items: ["Agent on host", "In-place or blue/green", "appspec hooks"]}
  - {h: "Lambda", kind: app, items: ["Alias traffic shift", "Canary or linear", "Pre and post traffic hooks"]}
  - {h: "ECS", kind: cp, items: ["Blue/green task sets", "ALB listener shift", "Test listener"]}
@h Application and group
```bash title="Create" nocheck
aws deploy create-application --application-name shop --compute-platform ECS
aws deploy create-deployment --application-name shop --deployment-group-name prod \
  --revision revisionType=S3,s3Location={bucket=artifacts,key=appspec.zip,bundleType=zip}
```
@check
Which platforms does CodeDeploy support? || EC2 or on-premises, Lambda and ECS.
@end

@concept In-place and rolling deployments on EC2
@plain
An **in-place** deployment stops the app on each instance, installs the new revision and restarts it, in batches.
@problem
You need to update long-lived servers without taking everything down at once.
@does
- Configs: `OneAtATime`, `HalfAtATime`, `AllAtOnce` or custom minimum healthy hosts.
- Instances are deregistered from the load balancer during update, then re-registered after validation.
- Capacity drops during the update; plan for the minimum healthy percentage.
- Example: 10 instances with HalfAtATime updates 5 at a time, so capacity is 50 percent while a batch is running.
@diagram flow
caption: Half at a time
numbered: true
nodes:
  - "Batch 1|5 instances out|warn"
  - "Update and validate|appspec hooks|app"
  - "Back in service|re-register|ok"
  - "Batch 2|next 5|warn"
@h appspec for EC2
```yaml title="appspec.yml"
version: 0.0
os: linux
files:
  - source: /
    destination: /opt/shop
hooks:
  BeforeInstall:
    - location: scripts/stop.sh
      timeout: 60
  AfterInstall:
    - location: scripts/configure.sh
      timeout: 120
  ApplicationStart:
    - location: scripts/start.sh
      timeout: 60
  ValidateService:
    - location: scripts/health.sh
      timeout: 120
```
@check
10 instances, HalfAtATime. Capacity during a batch? || 50 percent (5 of 10 serving).
@end

@concept Blue/green deployments
@plain
**Blue/green** creates a complete new environment (green), tests it, then moves traffic from blue and keeps blue for quick rollback.
@problem
In-place changes alter the running version, so rollback means redeploying and capacity dips.
@does
- EC2: copies the Auto Scaling group, installs the revision, then shifts the load balancer.
- ECS: creates a replacement task set behind a second target group, then moves the listener.
- You can pay for double capacity during the window; set the termination wait time for the blue environment.
- Rollback is switching traffic back, which takes seconds.
@diagram flow
caption: Traffic switch
nodes:
  - "ALB listener|production traffic|cp"
  - "Blue tasks|current version|info"
  - "Green tasks|new version|ok"
@h ECS appspec
```yaml title="appspec-ecs.yml"
version: 0.0
Resources:
  - TargetService:
      Type: AWS::ECS::Service
      Properties:
        TaskDefinition: "arn:aws:ecs:eu-west-1:111122223333:task-definition/web:13"
        LoadBalancerInfo:
          ContainerName: "web"
          ContainerPort: 8080
Hooks:
  - AfterAllowTestTraffic: "arn:aws:lambda:eu-west-1:111122223333:function:smoke-test"
```
@end

@concept Canary and linear traffic shifting
@plain
**Canary** sends a small percentage first, then the rest. **Linear** adds a fixed percentage on an interval.
@problem
All-at-once shifts expose every user to a bad release.
@does
- Predefined configs, for example `CodeDeployDefault.LambdaCanary10Percent5Minutes` and `CodeDeployDefault.ECSLinear10PercentEvery1Minutes`.
- Canary 10 percent for 5 minutes then 100: total shift time about 5 minutes.
- Linear 10 percent every 1 minute reaches 100 percent after 10 steps, about 9 to 10 minutes.
- Combine with alarms and pre/post traffic hooks that run tests.
@diagram flow
caption: Canary then full
nodes:
  - "10 percent|new version|warn"
  - "Wait 5 min|watch alarms|info"
  - "100 percent|complete|ok"
@h Lambda appspec
```yaml title="appspec-lambda.yml"
version: 0.0
Resources:
  - orders:
      Type: AWS::Lambda::Function
      Properties:
        Name: "orders"
        Alias: "live"
        CurrentVersion: "12"
        TargetVersion: "13"
Hooks:
  - BeforeAllowTraffic: "orders-pre-traffic-check"
  - AfterAllowTraffic: "orders-post-traffic-check"
```
@check
How long does Linear10PercentEvery1Minute take to reach 100 percent? || About 10 minutes (ten steps of one minute), the last step completing the shift.
@end

@concept Alarms and automatic rollback
@plain
CodeDeploy can watch CloudWatch alarms and automatically roll back if they fire.
@problem
Humans notice errors late; a bad version keeps serving traffic.
@does
- Attach up to the quota number of alarms to a deployment group (check the current quota).
- Rollback on deployment failure or alarm threshold.
- Good alarms: 5xx rate, p99 latency, Lambda errors, business metrics.
- Rollback redeploys the last good revision (EC2) or restores traffic (blue/green).
@diagram flow
caption: Rollback loop
nodes:
  - "Shift traffic|canary step|app"
  - "Alarm in ALARM|errors up|bad"
  - "Auto rollback|previous version|warn"
@h Group settings
```hcl title="deploy-group.tf"
resource "aws_codedeploy_deployment_group" "web" {
  app_name               = aws_codedeploy_app.shop.name
  deployment_group_name  = "prod"
  service_role_arn       = aws_iam_role.codedeploy.arn
  deployment_config_name = "CodeDeployDefault.OneAtATime"
  alarm_configuration {
    enabled = true
    alarms  = [aws_cloudwatch_metric_alarm.errors.alarm_name]
  }
  auto_rollback_configuration {
    enabled = true
    events  = ["DEPLOYMENT_FAILURE", "DEPLOYMENT_STOP_ON_ALARM"]
  }
}
```
@end

@concept Lifecycle hooks and agent
@plain
Hooks run scripts or Lambda functions at defined points; EC2 deployments need the CodeDeploy agent installed.
@problem
A deployment must run migrations, health checks and warm-up in the right order.
@does
- EC2 hook order: ApplicationStop, DownloadBundle, BeforeInstall, Install, AfterInstall, ApplicationStart, ValidateService (plus load balancer hooks).
- Lambda and ECS use Lambda-based hooks that report `Succeeded` or `Failed` via `PutLifecycleEventHookExecutionStatus`.
- Install the agent through Systems Manager Distributor or user data, and give the instance profile S3 read access to the bundle.
- Keep hooks idempotent.
@diagram flow
caption: EC2 hook order
numbered: true
nodes:
  - "ApplicationStop|old version|warn"
  - "BeforeInstall|prep|info"
  - "AfterInstall|configure|info"
  - "ApplicationStart|start|app"
  - "ValidateService|health|ok"
@h Hook report
```python title="hook.py"
import boto3

codedeploy = boto3.client("codedeploy")

def handler(event, context):
    status = "Succeeded"  # replace with real checks
    codedeploy.put_lifecycle_event_hook_execution_status(
        deploymentId=event["DeploymentId"],
        lifecycleEventHookExecutionId=event["LifecycleEventHookExecutionId"],
        status=status)
```
@check
What must a Lambda hook call back to CodeDeploy? || PutLifecycleEventHookExecutionStatus with Succeeded or Failed.
@end

@concept Choosing a deployment strategy
@plain
Pick by risk, cost of duplicate capacity and how quickly you must roll back.
@problem
Using the same strategy for everything wastes money or accepts needless risk.
@does
- Internal tools and dev: in-place, all at once.
- Stateless services: rolling or canary.
- Customer-facing critical paths: blue/green canary with alarms.
- Stateful changes: expand and contract migrations so old and new versions both run against the schema.
- Kubernetes users have rollout controllers (Argo Rollouts) instead; CodeDeploy covers ECS, EC2 and Lambda.
@diagram cmp
caption: Strategy fit
cards:
  - {h: "In-place", kind: warn, items: ["Cheapest", "Capacity dips", "Slower rollback"]}
  - {h: "Rolling", kind: info, items: ["Batches", "Mixed versions", "No extra fleet"]}
  - {h: "Blue/green canary", kind: ok, items: ["Safest", "Double capacity briefly", "Fast rollback"]}
@choose Strategy
In-place | dev and low risk with spare capacity | strict uptime requirements
Rolling | stateless fleets with health checks | schema changes incompatible with old version
Blue/green canary | production APIs with alarms | cost of duplicate capacity is prohibited
@end
