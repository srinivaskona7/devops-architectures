---
title: Resilience Hub and Fault Injection Service
minutes: 45
objectives:
  - Assess an application against RTO and RPO targets with Resilience Hub
  - Run controlled failure experiments with AWS Fault Injection Service
  - Build game days with stop conditions, alarms and clear hypotheses
---
Resilience is a claim until you test it. Resilience Hub compares your architecture with targets. Fault Injection Service (FIS) breaks things on purpose, safely.

@concept Resilience Hub assessments
@plain
**AWS Resilience Hub** analyses an application's resources against resilience policies you set and reports gaps with recommendations.
@problem
Teams state RTO and RPO targets, but nobody checks that the deployed architecture can meet them.
@does
- Define an **application** from CloudFormation stacks, Terraform state, AppRegistry, tags or Resource Groups.
- A **resilience policy** sets RTO and RPO for four disruption types: application, infrastructure, AZ and Region.
- The assessment estimates achievable RTO and RPO per type and flags resources that miss the targets.
- Recommendations cover alarms, SOPs and FIS tests.
@diagram flow
caption: Assessment loop
numbered: true
nodes:
  - "Application|stacks and tags|app"
  - "Policy|RTO and RPO targets|info"
  - "Assessment|estimated vs target|warn"
  - "Recommendations|fix and retest|ok"
@h Create a policy
```bash title="Policy" nocheck
aws resiliencehub create-resiliency-policy --policy-name tier1 --tier MissionCritical \
  --policy 'AZ={rtoInSecs=300,rpoInSecs=0},Hardware={rtoInSecs=300,rpoInSecs=0},Software={rtoInSecs=300,rpoInSecs=0},Region={rtoInSecs=3600,rpoInSecs=300}'
```
@check
Name the four disruption types in a policy. || Application (software), infrastructure (hardware), Availability Zone and Region.
@end

@concept Operational recommendations
@plain
Resilience Hub produces more than design advice. It suggests alarms, standard operating procedures and tests.
@problem
A resilient design still fails if nobody knows the recovery steps or gets alerted.
@does
- Alarm recommendations as CloudFormation you can adopt.
- SOP recommendations as Systems Manager documents for recovery tasks.
- FIS experiment templates mapped to the risks found.
- Drift detection between assessments flags design changes.
@diagram layers
caption: Outputs
layers:
  - {label: "Design", nodes: ["Gap report|resource level findings|warn"]}
  - {label: "Operations", nodes: ["Alarms|CloudWatch|info", "SOPs|SSM documents|info"]}
  - {label: "Validation", nodes: ["FIS tests|experiments|ok"]}
@h List assessments
```bash title="Assessments" lab
aws resiliencehub list-app-assessments --query 'assessmentSummaries[].[appArn,assessmentStatus,complianceStatus]' --output table
```
@end

@concept FIS experiment templates
@plain
**AWS Fault Injection Service** runs fault actions on your resources according to an **experiment template**.
@problem
Real failures are rare and unpredictable, so recovery code and runbooks go untested until a real outage.
@does
- Template: actions, targets (selected by tag, ARN or filter), stop conditions and an IAM role.
- Actions include stopping or terminating EC2 instances, CPU or memory stress through SSM, network latency or blackhole, throttling APIs, failing over RDS or Aurora, interrupting Spot, and Kubernetes pod faults for EKS. Check the current action list.
- Scenario library has prebuilt multi-action tests such as AZ power interruption; check availability.
- Experiments record start, end and results; you pay per action-minute.
@diagram flow
caption: Experiment
nodes:
  - "Template|actions and targets|cp"
  - "Run|inject fault|warn"
  - "Observe|alarms and traces|info"
  - "Stop condition|abort on alarm|bad"
@h Template
```json title="fis-template.json"
{
  "description": "Stop 25 percent of tagged web instances",
  "targets": {
    "WebInstances": {
      "resourceType": "aws:ec2:instance",
      "resourceTags": {"Role": "web"},
      "selectionMode": "PERCENT(25)"
    }
  },
  "actions": {
    "StopInstances": {
      "actionId": "aws:ec2:stop-instances",
      "parameters": {"startInstancesAfterDuration": "PT5M"},
      "targets": {"Instances": "WebInstances"}
    }
  },
  "stopConditions": [
    {"source": "aws:cloudwatch:alarm", "value": "arn:aws:cloudwatch:eu-west-1:111122223333:alarm:web-5xx-high"}
  ],
  "roleArn": "arn:aws:iam::111122223333:role/fis-experiment",
  "tags": {"Name": "web-instance-loss"}
}
```
```bash title="Create and start" nocheck
aws fis create-experiment-template --cli-input-json file://fis-template.json
aws fis start-experiment --experiment-template-id EXT1a2b3c4d5e6f7
```
@check
What aborts an experiment automatically? || A stop condition, usually a CloudWatch alarm.
@end

@concept Stop conditions and safety
@plain
Experiments must be bounded. Stop conditions, narrow targets and a dedicated role keep them safe.
@problem
A chaos test that spreads past its target becomes an outage.
@does
- Stop condition alarms on user-facing symptoms such as error rate or latency.
- Targets limited by tags and a percentage; start in a non-production environment.
- The FIS role has least privilege and is only assumable by `fis.amazonaws.com`.
- Notify the team, record the hypothesis, and have a rollback.
- Use SCPs to restrict who can start experiments in production.
@diagram flow
caption: Guardrails
nodes:
  - "Hypothesis|what should happen|info"
  - "Small blast radius|one AZ or 25 percent|warn"
  - "Stop alarm|auto abort|bad"
  - "Review|fix gaps|ok"
@h FIS role trust
```json title="fis-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "fis.amazonaws.com"},
    "Action": "sts:AssumeRole",
    "Condition": {"StringEquals": {"aws:SourceAccount": "111122223333"}}
  }]
}
```
@end

@concept AZ failure and database failover tests
@plain
Two high-value tests simulate losing an AZ and forcing a database failover.
@problem
Multi-AZ designs often hide single points of failure such as one NAT gateway per VPC or a hard coded AZ.
@does
- AZ impairment: network disruption against subnets in one AZ, plus stopping instances there; observe the load balancer and Auto Scaling replacing capacity.
- Aurora or RDS failover action: measure application reconnect time and connection pool behaviour.
- Check that clients retry with backoff and that DNS TTLs are short enough.
- Compare measured recovery with your RTO.
@diagram seq
caption: AZ loss test
actors: ["FIS|experiment|cp", "AZ a|impaired|bad", "Load balancer|health checks|info", "ASG|replaces capacity|app"]
steps:
  - "0>1: network disruption | bad"
  - "2>1: targets unhealthy | warn"
  - "2>2: shift traffic to other AZs | req"
  - "3>3: launch replacements | req"
@h Aurora failover action
```json title="fis-aurora.json"
{
  "description": "Fail over the Aurora cluster",
  "targets": {
    "Cluster": {
      "resourceType": "aws:rds:cluster",
      "resourceArns": ["arn:aws:rds:eu-west-1:111122223333:cluster:shop-aurora"],
      "selectionMode": "ALL"
    }
  },
  "actions": {
    "Failover": {
      "actionId": "aws:rds:failover-db-cluster",
      "targets": {"Clusters": "Cluster"}
    }
  },
  "stopConditions": [{"source": "none"}],
  "roleArn": "arn:aws:iam::111122223333:role/fis-experiment"
}
```
@check
Which hidden single points of failure do AZ tests often reveal? || A single NAT gateway, hard coded AZs, or single-AZ dependencies.
@end

@concept Game days and continuous validation
@plain
A **game day** is a planned exercise where a team runs failures and practises response. Continuous experiments keep results fresh.
@problem
One-off tests decay as the system changes.
@does
- Write a hypothesis, for example "if one AZ is lost, error rate stays under 1 percent and recovers in 5 minutes".
- Run in staging first, then in production at a quiet time with the team watching dashboards.
- Schedule recurring experiments with EventBridge Scheduler or run FIS from a pipeline step.
- Capture findings as tickets, fix, and rerun.
- Link results to Resilience Hub assessments to prove the RTO and RPO.
@diagram flow
caption: Game day cycle
numbered: true
nodes:
  - "Hypothesis|expected outcome|info"
  - "Run experiment|bounded failure|warn"
  - "Measure|errors and recovery time|app"
  - "Fix and repeat|tickets and retest|ok"
@h Schedule an experiment
```hcl title="fis-schedule.tf"
resource "aws_scheduler_schedule" "weekly_fis" {
  name                = "weekly-fis-staging"
  schedule_expression = "cron(0 10 ? * TUE *)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = "arn:aws:scheduler:::aws-sdk:fis:startExperiment"
    role_arn = aws_iam_role.scheduler.arn
    input = jsonencode({
      ExperimentTemplateId = "EXT1a2b3c4d5e6f7"
      ClientToken          = "weekly"
    })
  }
}
```
@check
What makes a game day useful? || A clear hypothesis, bounded failure, measurement and follow-up fixes.
@end
