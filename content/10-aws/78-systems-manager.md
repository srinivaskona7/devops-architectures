---
title: Systems Manager operations toolkit
minutes: 50
objectives:
  - Manage fleets with the SSM Agent, managed nodes and Session Manager
  - Store configuration in Parameter Store and patch with Patch Manager
  - Automate runbooks with Automation and Run Command
---
Systems Manager (SSM) is the operations hub for EC2, on-premises servers and containers. It replaces login keys, ad-hoc scripts and spreadsheets of patch levels.

@concept Managed nodes and the SSM Agent
@plain
A **managed node** is a machine running the SSM Agent whose IAM role lets it talk to Systems Manager.
@problem
Operating a fleet by logging in to each server does not scale or leave an audit trail.
@does
- The agent is preinstalled on Amazon Linux and many AMIs.
- The instance profile needs the managed policy `AmazonSSMManagedInstanceCore`.
- The node needs outbound HTTPS to the ssm, ssmmessages and ec2messages endpoints, through NAT or three interface VPC endpoints.
- **Default Host Management Configuration** can grant the role to instances account-wide.
- Fleet Manager lists nodes and their agent versions.
@diagram flow
caption: Why a node is managed
nodes:
  - "SSM Agent|installed and running|app"
  - "Instance role|AmazonSSMManagedInstanceCore|warn"
  - "Network path|NAT or VPC endpoints|env"
  - "Managed node|shows in Fleet Manager|ok"
@h Check the fleet
```bash title="Which nodes are online" lab
aws ssm describe-instance-information \
  --query 'InstanceInformationList[].[InstanceId,PingStatus,PlatformName,AgentVersion]' --output table
```
@check
An instance does not appear in Fleet Manager. Name three causes. || Missing role permissions, no network path to the SSM endpoints, or the agent not running.
@end

@concept Session Manager
@plain
**Session Manager** gives a shell on an instance through the AWS API, with no inbound ports, bastion hosts or key pairs.
@problem
Classic remote login needs open port 22, key distribution and offers poor auditing.
@does
- Access controlled by IAM (`ssm:StartSession`) with conditions on tags, so a team can reach only its own instances.
- Sessions can log to CloudWatch Logs or S3 and are recorded in CloudTrail.
- Port forwarding reaches private databases with the document `AWS-StartPortForwardingSessionToRemoteHost`.
- Requires the Session Manager plugin for the CLI.
@diagram seq
caption: Shell without key pairs
actors: ["Engineer|CLI with plugin|ext", "SSM service|IAM check and log|cp", "Agent|on instance|app"]
steps:
  - "0>1: start-session | tls"
  - "note 1..1: IAM allows and logs"
  - "2>1: open channel outbound | tls"
  - "0>2: commands via service | req"
@h Allow only tagged instances
```json title="session-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "ssm:StartSession",
    "Resource": "arn:aws:ec2:eu-west-1:111122223333:instance/*",
    "Condition": {"StringEquals": {"ssm:resourceTag/Team": "payments"}}
  }]
}
```
```bash title="Port forward to a private database" nocheck
aws ssm start-session --target i-0123456789abcdef0 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host=db.internal,portNumber=5432,localPortNumber=15432
```
@check
How do you restrict engineers to their own team's instances? || An IAM condition on ssm:resourceTag for StartSession.
@end

@concept Parameter Store
@plain
**Parameter Store** is a hierarchical key value store for configuration and secrets, with versions and IAM access.
@problem
Configuration hard coded in images or environment files is hard to change and audit.
@does
- Types: `String`, `StringList`, `SecureString` (KMS encrypted).
- Hierarchy such as `/shop/prod/db/host` allows IAM policies on a path and `get-parameters-by-path`.
- Standard parameters have no charge; advanced parameters allow bigger values and policies such as expiry (check current pricing).
- Public parameters hold the latest AMI IDs, for example `/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`.
- Secrets Manager adds automatic rotation; use it for database credentials.
@diagram flow
caption: Config at runtime
nodes:
  - "Parameter|versioned path|info"
  - "IAM path policy|read only prod|warn"
  - "App or task|fetches at start|app"
@h Write and read
```bash title="Parameters" nocheck
aws ssm put-parameter --name /shop/prod/db/host --type String --value db.internal --overwrite
aws ssm put-parameter --name /shop/prod/db/password --type SecureString --value "$PW"
aws ssm get-parameters-by-path --path /shop/prod --recursive --with-decryption
```
```hcl title="param.tf"
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}
```
@end

@concept Run Command and State Manager
@plain
**Run Command** runs a document (script) on many nodes at once. **State Manager** keeps nodes in a desired state by applying documents on a schedule.
@problem
Fleet-wide changes through login loops are slow, unaudited and fail halfway.
@does
- Target by instance IDs, tags or resource groups; control with `max-concurrency` and `max-errors`.
- Output goes to S3 or CloudWatch Logs.
- Documents: `AWS-RunShellScript`, `AWS-RunPowerShellScript`, `AWS-ConfigureAWSPackage` and your own.
- State Manager associations install agents and enforce configuration, for example the CloudWatch agent on every node.
@diagram flow
caption: Targeted rollout
nodes:
  - "Document|script or package|info"
  - "Targets|tag Env equals prod|env"
  - "Rate control|10 percent at a time|warn"
  - "Results|S3 or logs|ok"
@h Run on tagged nodes
```bash title="Run Command" nocheck
aws ssm send-command --document-name AWS-RunShellScript \
  --targets Key=tag:Env,Values=prod --max-concurrency 10% --max-errors 1 \
  --parameters 'commands=["systemctl is-active nginx"]'
```
@check
Which two settings limit the blast radius of Run Command? || max-concurrency and max-errors.
@end

@concept Patch Manager
@plain
**Patch Manager** scans nodes for missing OS patches and installs them in maintenance windows, using patch baselines.
@problem
Unpatched servers are a leading cause of breaches, and manual patching drifts.
@does
- A **patch baseline** defines approved classifications, severities and auto-approval delay (for example 7 days after release).
- Patch groups or tags attach nodes to a baseline.
- Two operations: `Scan` (report) and `Install`; schedule through a maintenance window or a patch policy in Quick Setup, which can span an organization.
- Compliance reports show per-node missing patches.
- Immutable fleets patch by building new AMIs instead; combine with Image Builder.
@diagram flow
caption: Patch cycle
numbered: true
nodes:
  - "Baseline|rules and delay|info"
  - "Scan|find missing|app"
  - "Install in window|reboot if needed|warn"
  - "Compliance|report|ok"
@h Baseline
```hcl title="patch.tf"
resource "aws_ssm_patch_baseline" "linux" {
  name             = "al2023-security"
  operating_system = "AMAZON_LINUX_2023"
  approval_rule {
    approve_after_days = 7
    patch_filter {
      key    = "CLASSIFICATION"
      values = ["Security"]
    }
    patch_filter {
      key    = "SEVERITY"
      values = ["Critical", "Important"]
    }
  }
}
```
@check
What does approve_after_days do? || Waits that many days after a patch is released before the baseline approves it.
@end

@concept Automation runbooks
@plain
**Automation** runs multi-step runbooks that call AWS APIs, with approvals, branching and rate control.
@problem
Operational procedures, such as restoring from a snapshot, live in wikis and are done differently by each person.
@does
- AWS-owned runbooks exist for many tasks, such as `AWS-RestartEC2Instance`, `AWS-CreateImage`, `AWS-UpdateLinuxAmi`.
- Custom runbooks in YAML or JSON with actions like `aws:executeAwsApi`, `aws:runCommand`, `aws:approve`.
- Run with an assume role so people need not have wide permissions.
- Trigger from EventBridge, Config remediation or OpsCenter.
@diagram flow
caption: Runbook
numbered: true
nodes:
  - "Trigger|alarm or person|ext"
  - "Approve|optional|warn"
  - "Steps|API and commands|app"
  - "Outcome|logged execution|ok"
@h Simple runbook
```yaml title="restart-runbook.yaml"
schemaVersion: "0.3"
description: Stop and start an instance
assumeRole: "{{ AutomationAssumeRole }}"
parameters:
  AutomationAssumeRole:
    type: String
  InstanceId:
    type: String
mainSteps:
  - name: stop
    action: aws:changeInstanceState
    inputs:
      InstanceIds:
        - "{{ InstanceId }}"
      DesiredState: stopped
  - name: start
    action: aws:changeInstanceState
    inputs:
      InstanceIds:
        - "{{ InstanceId }}"
      DesiredState: running
```
@end

@concept Maintenance windows, Inventory and Change Manager
@plain
Maintenance windows schedule tasks. Inventory lists software. Change Manager adds approval workflows.
@problem
Changes must happen at agreed times with a record of what and who.
@does
- **Maintenance windows**: cron schedule, duration, cutoff and registered targets with tasks (Run Command, Automation, Lambda, Step Functions).
- **Inventory** collects applications, network settings and files into a queryable store, aggregated by Resource Data Sync to S3.
- **Change Manager** needs approvers and change calendars to block changes during freezes.
- **Explorer and OpsCenter** give a dashboard and an operational issue queue.
- Multi-account use is through a delegated administrator and Quick Setup.
@diagram layers
caption: Operations features
layers:
  - {label: "Change", nodes: ["Change Manager|approval and calendar|warn", "Maintenance windows|schedule|info"]}
  - {label: "Act", nodes: ["Run Command|ad hoc|app", "Automation|runbooks|app", "Patch Manager|baselines|app"]}
  - {label: "Know", nodes: ["Inventory|what is installed|ok", "Fleet Manager|nodes|ok"]}
@h Window
```hcl title="window.tf"
resource "aws_ssm_maintenance_window" "sunday" {
  name     = "sunday-patching"
  schedule = "cron(0 2 ? * SUN *)"
  duration = 3
  cutoff   = 1
}
```
Duration 3 hours with cutoff 1 hour means no new task starts after 2 hours into the window.
@check
Window duration 3 h and cutoff 1 h. When does the last task start? || At most 2 hours after the window starts.
@end
