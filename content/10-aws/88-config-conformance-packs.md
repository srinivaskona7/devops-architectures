---
title: AWS Config rules and conformance packs
minutes: 45
objectives:
  - Record resource configuration and evaluate it with managed and custom Config rules
  - Deploy conformance packs and aggregators across an Organization
  - Remediate non-compliance automatically with Systems Manager Automation
---
AWS Config records what your resources look like and checks them against rules. This section goes beyond recording to compliance at scale.

@concept Config recorder, rules and evaluations
@plain
The **configuration recorder** stores a history of resource configuration items. **Rules** evaluate those items and mark each resource compliant or non-compliant.
@problem
You cannot answer "which of my buckets are unencrypted right now, and since when" from the console alone.
@does
- The recorder runs per account and Region; choose all supported resources or a list.
- A **managed rule** such as `s3-bucket-server-side-encryption-enabled` is provided by AWS (many exist).
- Triggers: configuration change or periodic.
- Config stores timelines so you can see changes and compliance history.
- Cost depends on configuration items recorded and rule evaluations; check current pricing.
@diagram flow
caption: Config in action
nodes:
  - "Resource change|bucket modified|app"
  - "Recorder|configuration item|cp"
  - "Rule|evaluate|info"
  - "Compliance|compliant or not|ok"
@h Managed rule
```hcl title="config-rule.tf"
resource "aws_config_config_rule" "s3_encrypted" {
  name = "s3-bucket-sse-enabled"
  source {
    owner             = "AWS"
    source_identifier = "S3_BUCKET_SERVER_SIDE_ENCRYPTION_ENABLED"
  }
}
```
@check
Which two triggers can a Config rule use? || Configuration change and periodic.
@end

@concept Custom rules with Lambda and Guard
@plain
When no managed rule fits, write a **custom Lambda rule** or a **Guard policy-as-code rule**.
@problem
Company-specific standards, such as a required tag format, are not covered by managed rules.
@does
- Custom Lambda: receives the configuration item and reports the evaluation with `PutEvaluations`.
- Custom policy (Guard): write the rule in the CloudFormation Guard DSL; no Lambda to maintain.
- Test locally with `cfn-guard`.
- Prefer Guard for simple property checks, Lambda for logic needing outside data.
@diagram cmp
caption: Custom rule options
cards:
  - {h: "Guard policy", kind: ok, items: ["Declarative DSL", "No code to host", "Property checks"]}
  - {h: "Lambda rule", kind: cp, items: ["Any logic", "External lookups", "You maintain code"]}
@h Guard rule
```text title="tags.guard" nocheck
rule s3_has_owner_tag when resourceType == "AWS::S3::Bucket" {
  configuration.tags exists
  some configuration.tags[*].key == "Owner"
}
```
@end

@concept Conformance packs
@plain
A **conformance pack** is a bundle of Config rules and remediation actions deployed together as a single template.
@problem
Managing hundreds of individual rules across accounts is tedious and inconsistent.
@does
- Defined in a YAML template like CloudFormation; AWS publishes sample packs for frameworks such as CIS, PCI DSS and NIST, and operational best practices (check the current list).
- Deploy to one account or across an Organization from the management or delegated administrator account.
- Shows a compliance score per pack.
- Updating the template updates all member accounts.
@diagram flow
caption: Pack deployment
nodes:
  - "Template|rules and remediation|info"
  - "Organization pack|from delegated admin|cp"
  - "Member accounts|rules deployed|app"
  - "Compliance score|per account|ok"
@h Pack template
```yaml title="pack.yaml" nocheck
Resources:
  S3Encrypted:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: s3-sse-enabled
      Source:
        Owner: AWS
        SourceIdentifier: S3_BUCKET_SERVER_SIDE_ENCRYPTION_ENABLED
  RootMfa:
    Type: AWS::Config::ConfigRule
    Properties:
      ConfigRuleName: root-mfa-enabled
      Source:
        Owner: AWS
        SourceIdentifier: ROOT_ACCOUNT_MFA_ENABLED
```
```bash title="Deploy to the Organization" nocheck
aws configservice put-organization-conformance-pack --organization-conformance-pack-name baseline \
  --template-body file://pack.yaml
```
@check
Where do you deploy an organization conformance pack from? || The management account or a delegated administrator.
@end

@concept Aggregators and advanced queries
@plain
An **aggregator** collects Config data from many accounts and Regions into one view. **Advanced queries** use SQL-like syntax over resource configuration.
@problem
Each account's Config data is separate, so central teams cannot search the estate.
@does
- Aggregator in a central account, authorised per account or via Organizations.
- Query across all accounts: "all EC2 instances not using IMDSv2".
- Compliance dashboards by rule, account and Region.
- Pair with Security Hub for findings and with Athena for long term analysis of delivered snapshots.
@diagram flow
caption: Central view
nodes:
  - "Member accounts|recorders|app"
  - "Aggregator|central account|cp"
  - "Query and dashboards|estate wide|ok"
@h SQL query
```bash title="Advanced query" nocheck
aws configservice select-aggregate-resource-config \
  --configuration-aggregator-name org-agg \
  --expression "SELECT accountId, resourceId WHERE resourceType = 'AWS::EC2::Instance' AND configuration.metadataOptions.httpTokens = 'optional'"
```
@check
What does an aggregator give a central team? || A single place to see configuration and compliance across accounts and Regions.
@end

@concept Automatic remediation
@plain
A Config rule can trigger an **SSM Automation runbook** to fix a non-compliant resource, automatically or after approval.
@problem
Detecting issues without fixing them leaves a growing backlog.
@does
- Use AWS-owned runbooks such as `AWS-EnableS3BucketEncryption`, or your own.
- Automatic remediation retries a few times; manual remediation waits for a click.
- The remediation role needs only the permissions the fix requires.
- Be careful with destructive fixes; prefer remediating configuration (encryption, tags) over deletion.
@diagram flow
caption: Detect and fix
numbered: true
nodes:
  - "Rule marks non-compliant|bucket unencrypted|bad"
  - "Remediation|SSM Automation|cp"
  - "Fix applied|encryption on|ok"
  - "Re-evaluate|compliant|ok"
@h Remediation config
```hcl title="remediation.tf"
resource "aws_config_remediation_configuration" "s3_encrypt" {
  config_rule_name = aws_config_config_rule.s3_encrypted.name
  target_type      = "SSM_DOCUMENT"
  target_id        = "AWS-EnableS3BucketEncryption"
  automatic        = true
  maximum_automatic_attempts = 3
  retry_attempt_seconds      = 60
  parameter {
    name           = "BucketName"
    resource_value = "RESOURCE_ID"
  }
  parameter {
    name         = "SSEAlgorithm"
    static_value = "AES256"
  }
  parameter {
    name         = "AutomationAssumeRole"
    static_value = "arn:aws:iam::111122223333:role/config-remediation"
  }
}
```
@end

@concept Config versus Control Tower, Security Hub and cost
@plain
Config is the detective data layer. Control Tower, Security Hub and others consume it.
@problem
Teams enable several overlapping tools and pay twice for the same data.
@does
- Control Tower detective controls are Config rules that it manages; do not duplicate them.
- Security Hub standards use Config rules under the hood and require Config to be on.
- Reduce cost by recording only needed resource types and excluding high-churn ones, or by using periodic recording for chatty resources.
- Cost sketch: recorded items per month x price per item + evaluations x price per evaluation; check the current rates.
- Keep delivery to S3 and use lifecycle rules for history.
@diagram layers
caption: Relationships
layers:
  - {label: "Consumers", nodes: ["Control Tower controls|detective|info", "Security Hub standards|findings|info"]}
  - {label: "Evaluation", nodes: ["Config rules and packs|compliance|cp"]}
  - {label: "Data", nodes: ["Configuration recorder|history|ok"]}
@h Recorder with exclusions
```hcl title="recorder.tf"
resource "aws_config_configuration_recorder" "main" {
  name     = "default"
  role_arn = aws_iam_role.config.arn
  recording_group {
    all_supported = false
    resource_types = ["AWS::EC2::Instance", "AWS::S3::Bucket", "AWS::IAM::Role", "AWS::RDS::DBInstance"]
  }
}
```
@check
Why trim recorded resource types? || To reduce cost by skipping resources and churn you never evaluate.
@end
