---
title: CloudTrail and AWS Config
minutes: 45
objectives:
  - Build an organisation trail that is tamper resistant and queryable
  - Use AWS Config rules and conformance packs to detect drift and noncompliance
  - Answer who did what and what changed using Trail, Lake and Config history
---
CloudTrail records API calls. Config records resource configuration over time. Together they answer who did it, what changed and whether it is allowed.

@concept CloudTrail events and trails
@plain
CloudTrail logs every AWS API call (console, CLI, SDK, other services) with the caller, time, source IP, request and response outcome.
@problem
After an incident or an audit you need proof of who deleted a bucket or opened a security group.
@does
- **Management events** (control plane) are recorded for 90 days in the event history for free; a **trail** delivers them to S3 permanently.
- **Data events** (S3 object access, Lambda invoke, DynamoDB item access) are off by default and billed per volume.
- **Insights events** flag unusual API call rates.
- An **organisation trail** from the management account covers all accounts and Regions.
- Enable log file integrity validation and send logs to a dedicated, locked-down log archive account.
@diagram flow
caption: From API call to archive
nodes:
  - "API call|console or CLI|app"
  - "CloudTrail|event recorded|cp"
  - "S3 log archive|separate account|ok"
  - "CloudWatch Logs|alarms|info"
@h Create an organisation trail
```bash title="Multi-Region organisation trail with validation" nocheck
aws cloudtrail create-trail --name org-trail --s3-bucket-name org-trail-logs-111122223333 \
  --is-multi-region-trail --is-organization-trail --enable-log-file-validation \
  --kms-key-id alias/cloudtrail
aws cloudtrail start-logging --name org-trail
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=DeleteBucket --max-results 5
```
@check
How long is CloudTrail event history kept without a trail? || 90 days for management events.
@end

@concept Protecting and querying logs
@plain
Logs are evidence. Make them immutable and searchable.
@problem
Attackers delete logs, and grepping gigabytes of JSON in S3 is slow.
@does
- Bucket policy allows only CloudTrail to write; enable versioning, S3 Object Lock or MFA delete, SSE-KMS and a lifecycle to Glacier.
- SCP denies `cloudtrail:StopLogging` and `DeleteTrail`.
- **CloudTrail Lake** is a managed event data store with SQL queries and retention up to years.
- Alternatively use Athena over the S3 logs with a partitioned table.
- Alert on sensitive events: root login, `ConsoleLogin` without MFA, IAM policy changes, `CreateAccessKey`.
@diagram layers
caption: Defence of the audit trail
layers:
  - {label: "Collection", nodes: ["Organisation trail|all accounts|cp"]}
  - {label: "Protection", nodes: ["Object Lock and KMS|immutable|ok", "SCP guard|cannot stop logging|warn"]}
  - {label: "Analysis", nodes: ["CloudTrail Lake|SQL|info", "Athena|S3 queries|info"]}
@h Query
```sql title="Who deleted security groups last week (CloudTrail Lake)"
SELECT eventTime, userIdentity.arn, sourceIPAddress, requestParameters
FROM <event-data-store-id>
WHERE eventName = 'DeleteSecurityGroup'
  AND eventTime > timestamp '2026-10-24 00:00:00'
ORDER BY eventTime DESC
LIMIT 50
```
@check
Which control stops an administrator from turning logging off? || An SCP denying StopLogging and DeleteTrail, plus Object Lock on the bucket.
@end

@concept Reading a CloudTrail event
@plain
Each event is a JSON record. A few fields answer most questions.
@problem
Raw events are verbose and intimidating during an incident.
@does
- `eventName` and `eventSource` say what was called.
- `userIdentity` shows the principal; for assumed roles `sessionContext.sessionIssuer` shows the underlying role, and for SSO the user name appears in the session name.
- `sourceIPAddress` and `userAgent` identify where it came from.
- `errorCode` of `AccessDenied` shows attempts that failed, which are valuable for detection.
- `requestParameters` and `responseElements` show specifics such as the instance ID.
@diagram cmp
caption: Fields to read first
cards:
  - {h: "Who", kind: info, items: ["userIdentity.arn", "sessionIssuer"]}
  - {h: "What", kind: app, items: ["eventSource", "eventName", "requestParameters"]}
  - {h: "From where", kind: warn, items: ["sourceIPAddress", "userAgent"]}
  - {h: "Result", kind: ok, items: ["errorCode", "responseElements"]}
@h Example event
```json title="Trimmed CloudTrail event"
{
  "eventTime": "2026-10-30T08:35:12Z",
  "eventSource": "ec2.amazonaws.com",
  "eventName": "AuthorizeSecurityGroupIngress",
  "userIdentity": {
    "type": "AssumedRole",
    "arn": "arn:aws:sts::111122223333:assumed-role/AWSReservedSSO_Developer_abc123/alice"
  },
  "sourceIPAddress": "203.0.113.10",
  "requestParameters": {"groupId": "sg-0123456789abcdef0", "ipPermissions": {"items": [{"fromPort": 22, "toPort": 22, "ipRanges": {"items": [{"cidrIp": "0.0.0.0/0"}]}}]}}
}
```
@check
What does sessionIssuer tell you? || Which IAM role an assumed-role session came from.
@end

@concept AWS Config recorder and history
@plain
Config records the configuration of supported resources and every change, building a timeline per resource.
@problem
CloudTrail says someone called ModifyDBInstance; it does not give you the full before and after configuration of the database.
@does
- A **configuration recorder** tracks resource types in each Region; a delivery channel sends snapshots and history to S3.
- `get-resource-config-history` shows a resource at past times; relationships link a security group to its instances.
- **Advanced queries** use SQL-like syntax across resources.
- An **aggregator** consolidates accounts and Regions.
- Config is billed per configuration item recorded, so record only what you need in non-production.
@diagram flow
caption: Configuration timeline
nodes:
  - "Resource changes|SG rule added|app"
  - "Config item|new snapshot|cp"
  - "History|before and after|info"
  - "Rules|evaluate|warn"
@h Commands
```bash title="Inspect a resource's history and query" nocheck
aws configservice get-resource-config-history --resource-type AWS::EC2::SecurityGroup \
  --resource-id sg-0123456789abcdef0 --limit 3
aws configservice select-resource-config \
  --expression "SELECT resourceId, resourceType WHERE resourceType = 'AWS::S3::Bucket' AND configuration.publicAccessBlockConfiguration.blockPublicAcls = false"
```
@check
What does Config give that CloudTrail does not? || The full configuration of a resource over time, not just the API call.
@end

@concept Config rules, conformance packs and remediation
@plain
A Config rule evaluates resources as compliant or noncompliant. A conformance pack bundles many rules. Remediation actions fix findings with SSM Automation.
@problem
Policies written in a wiki do not enforce themselves.
@does
- **Managed rules** such as `s3-bucket-public-read-prohibited`, `encrypted-volumes`, `rds-instance-public-access-check`, `restricted-ssh`.
- **Custom rules** use Lambda or Guard policy-as-code.
- Evaluation is triggered by configuration change or periodically.
- Remediation can be automatic (for example, enable S3 block public access) or manual approval.
- Findings flow to Security Hub; organisation conformance packs deploy standards across accounts.
@diagram flow
caption: Detect and fix
numbered: true
nodes:
  - "Rule|rds public access check|info"
  - "Noncompliant resource|publicly accessible|bad"
  - "Remediation|SSM Automation|app"
  - "Compliant|re-evaluated|ok"
@h Rule
```bash title="Add managed rules" nocheck
aws configservice put-config-rule --config-rule '{
  "ConfigRuleName":"rds-no-public-access",
  "Source":{"Owner":"AWS","SourceIdentifier":"RDS_INSTANCE_PUBLIC_ACCESS_CHECK"}}'
aws configservice describe-compliance-by-config-rule --config-rule-names rds-no-public-access
```
```hcl title="Terraform"
resource "aws_config_config_rule" "ebs_encrypted" {
  name = "encrypted-volumes"

  source {
    owner             = "AWS"
    source_identifier = "ENCRYPTED_VOLUMES"
  }
}
```
@check
How does a custom Guard rule differ from a managed rule? || You write the evaluation logic as policy-as-code, while managed rules are prebuilt.
@end

@concept Investigation workflow
@plain
Combine the tools: Config shows what changed, CloudTrail shows who changed it, GuardDuty shows whether it looked malicious.
@problem
Without a routine, teams jump between consoles and lose time.
@does
- Start from the resource: Config timeline gives the exact time of change.
- Query CloudTrail around that timestamp for the actor and source IP.
- Check GuardDuty and Access Analyzer for related findings.
- Decide: revert (infrastructure as code apply), revoke credentials, or accept.
- Record the outcome in the incident ticket and improve the preventive control (SCP, Config rule).
@diagram flow
caption: Who changed this security group
numbered: true
nodes:
  - "Config timeline|time of change|info"
  - "CloudTrail|actor and IP|app"
  - "GuardDuty|malicious?|warn"
  - "Revert and harden|IaC apply and SCP|ok"
@h Commands
```bash title="Correlate by time" nocheck
aws cloudtrail lookup-events --lookup-attributes AttributeKey=ResourceName,AttributeValue=sg-0123456789abcdef0 \
  --start-time 2026-10-30T08:00:00Z --end-time 2026-10-30T09:00:00Z \
  --query 'Events[].[EventTime,EventName,Username]' --output table
```
@check
In which order do you use Config and CloudTrail? || Config pinpoints what and when; CloudTrail then identifies who and from where.
@end
