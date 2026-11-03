---
title: User data, metadata and Systems Manager
minutes: 45
objectives:
  - Bootstrap instances with user data and cloud-init safely
  - Replace SSH with Session Manager and port forwarding
  - Use Run Command, Patch Manager and Parameter Store for fleet operations
---
How an instance configures itself on boot and how you reach it afterwards decide whether your fleet is reproducible and secure.

@concept User data and cloud-init
@plain
**User data** is a script or cloud-config you pass at launch. The instance runs it once at first boot through **cloud-init**.
@problem
Manually logging in to configure each server is slow and cannot scale or be reviewed.
@does
- Maximum size is 16 KB; keep it tiny and fetch the rest from S3 or a package repository.
- Scripts start with a shebang; `#cloud-config` YAML configures packages, users and files.
- Runs as root, once by default. Output logs in `/var/log/cloud-init-output.log`.
- User data is not secret; anyone with `ec2:DescribeInstanceAttribute` or access to the metadata can read it. Never place passwords in it; use Secrets Manager or Parameter Store.
- Prefer baking an AMI for anything slow or critical, and use user data for the last mile (cluster join, environment-specific config).
@diagram flow
caption: Boot sequence
numbered: true
nodes:
  - "Launch|AMI plus user data|cp"
  - "cloud-init runs|first boot only|app"
  - "Fetch config|SSM Parameter Store|info"
  - "Join cluster|node ready|ok"
@h cloud-config example
```yaml title="user-data.yaml"
#cloud-config
package_update: true
packages:
  - amazon-cloudwatch-agent
write_files:
  - path: /etc/motd
    content: |
      managed by platform team
runcmd:
  - systemctl enable --now amazon-ssm-agent
  - systemctl enable --now amazon-cloudwatch-agent
```
```bash title="Debug" lab
sudo cat /var/log/cloud-init-output.log | tail -30
sudo cloud-init status --long
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/user-data | head
```
@check
Where can you read what user data ran? || In /var/log/cloud-init-output.log and `cloud-init status --long`.
@end

@concept Launch templates
@plain
A **launch template** is a versioned recipe for an instance: AMI, type, key, roles, network, storage, tags and user data.
@problem
Repeating the same long parameter list everywhere leads to inconsistency. Templates are required by Auto Scaling groups and recommended everywhere.
@does
- Versions are immutable; reference `$Latest`, `$Default` or a number.
- Enforce IMDSv2, EBS encryption and detailed tags centrally.
- Parameters can come from SSM, such as `resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64`.
@diagram layers
caption: What a template contains
layers:
  - {label: "Image and size", nodes: ["AMI|resolve:ssm or ID|app", "Instance type|or overrides|app"]}
  - {label: "Security", nodes: ["Instance profile|role|cp", "IMDSv2 required|hop limit 1|ok", "Security groups|ENI settings|info"]}
  - {label: "Storage and boot", nodes: ["EBS gp3 encrypted|block mapping|env", "User data|bootstrap|env"]}
@h Terraform
```hcl title="launch-template.tf"
resource "aws_launch_template" "worker" {
  name_prefix   = "worker-"
  image_id      = "resolve:ssm:/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
  instance_type = "m7g.large"

  iam_instance_profile {
    name = aws_iam_instance_profile.worker.name
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = 50
      volume_type = "gp3"
      encrypted   = true
    }
  }

  user_data = base64encode(file("${path.module}/user-data.yaml"))
}
```
@end

@concept SSM Session Manager
@plain
**Session Manager** gives you a shell on an instance through the SSM agent, with no inbound ports, bastion hosts or SSH keys.
@problem
SSH needs open port 22, key distribution, bastions and gives weak auditing.
@does
- Needs the SSM agent (preinstalled on Amazon Linux and many AMIs), an instance profile with `AmazonSSMManagedInstanceCore`, and outbound HTTPS to SSM endpoints (via NAT or `ssm`, `ssmmessages`, `ec2messages` interface endpoints).
- Access controlled by IAM, including conditions on tags; sessions logged to CloudWatch Logs or S3 and recorded in CloudTrail.
- **Port forwarding** reaches private databases and remote hosts via the instance. Works as an SSH proxy as well.
- Works for EKS nodes as well; for pods use `kubectl exec` instead.
@diagram seq
caption: Shell without inbound ports
actors: ["You|aws ssm start-session|app", "SSM service|IAM authorised|cp", "SSM agent|on the instance|env"]
steps:
  - "0>1: StartSession(instance) | req"
  - "note 1..1: IAM check, log destination"
  - "1>2: agent already holds an outbound channel | tls"
  - "2>0: shell stream through SSM | resp"
@h Use it
```bash title="Shell and port forward" lab
aws ssm start-session --target i-0123456789abcdef0
aws ssm start-session --target i-0123456789abcdef0 \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["db.internal.example.com"],"portNumber":["5432"],"localPortNumber":["15432"]}'
aws ssm describe-instance-information --query 'InstanceInformationList[].[InstanceId,PingStatus,PlatformName]' --output table
```
```json title="ssm-tag-scoped.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ssm:StartSession",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {"StringEquals": {"ssm:resourceTag/env": "dev"}}
    }
  ]
}
```
:::tip
Close port 22 in security groups, then enforce it with an AWS Config rule. Session Manager covers the use case.
:::
@check
What must an instance have to be reachable with Session Manager? || The SSM agent, an instance profile permitting SSM, and outbound HTTPS to the SSM endpoints.
@end

@concept Run Command, State Manager and Patch Manager
@plain
Systems Manager can run commands on many instances, keep them in a desired state, and patch them on a schedule.
@problem
Fleet-wide changes through individual logins are slow and unaudited.
@does
- **Run Command**: run a document (script) on instances chosen by tag, with rate control and logging.
- **State Manager**: associate a document with targets on a schedule to keep configuration applied.
- **Patch Manager**: baselines define which patches are approved; maintenance windows apply them. Report compliance.
- For immutable fleets (ASG with baked AMIs) prefer replacing instances to patching in place.
@diagram flow
caption: Patch cycle
numbered: true
nodes:
  - "Baseline|approved patches|info"
  - "Maintenance window|scheduled|cp"
  - "Run patch document|Run Command|app"
  - "Compliance report|per instance|ok"
@h Run on a tag
```bash title="Run Command" lab
aws ssm send-command --document-name AWS-RunShellScript \
  --targets Key=tag:env,Values=dev --parameters 'commands=["uptime","df -h /"]' \
  --max-concurrency 10% --max-errors 1 --comment "health snapshot"
aws ssm list-command-invocations --details --query 'CommandInvocations[].[InstanceId,Status]' --output table | head
```
@end

@concept Parameter Store and Secrets Manager
@plain
**Parameter Store** holds configuration values and optionally encrypted secrets. **Secrets Manager** adds automatic rotation for credentials.
@problem
Configuration and credentials copied into AMIs, user data or Git are hard to change and leak.
@does
- Parameters are hierarchical (`/prod/shop/db_host`) with IAM permissions per path; `SecureString` uses KMS.
- Standard parameters are free; advanced tier adds size and policies (check pricing).
- Secrets Manager rotates secrets (for example RDS passwords) with Lambda functions, and supports cross-Region replication. Charged per secret and per API calls.
- Public SSM parameters list the latest AMI IDs.
- On Kubernetes, the Secrets Store CSI driver with the AWS provider mounts these as files or syncs to Secrets.
@diagram flow
caption: Fetching config at boot
nodes:
  - "Instance role|ssm:GetParameter on /prod/shop/*|cp"
  - "Parameter Store|SecureString via KMS|info"
  - "App|reads at start|app"
@h Use
```bash title="Parameters" lab
aws ssm put-parameter --name /prod/shop/db_host --type String --value db.internal.example.com
aws ssm put-parameter --name /prod/shop/api_key --type SecureString --value "change-me"
aws ssm get-parameters-by-path --path /prod/shop --with-decryption --query 'Parameters[].Name'
aws secretsmanager get-secret-value --secret-id prod/shop/db --query SecretString --output text
```
@choose Where to keep values
Parameter Store | configuration and simple secrets | automatic rotation required
Secrets Manager | database credentials with rotation | plain config values
Kubernetes Secret | in-cluster consumption | long-term source of truth without encryption at rest
@end
