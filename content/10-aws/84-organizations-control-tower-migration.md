---
title: Migrating an Organization to a Control Tower landing zone
minutes: 55
objectives:
  - Assess an existing Organization before enabling Control Tower
  - Enrol existing accounts and OUs with Account Factory and baselines
  - Apply controls, customise with AFT or Customizations for Control Tower and plan rollback
---
Many teams start with a hand-built Organization and later want a managed landing zone. This section shows a safe migration path.

@concept What Control Tower adds
@plain
**AWS Control Tower** sets up a multi-account landing zone with a log archive account, an audit account, IAM Identity Center, baseline CloudTrail and Config, and controls (guardrails).
@problem
Hand-built baselines drift and every new account needs the same logging, access and guardrail steps repeated.
@does
- Home Region is fixed at setup; governed Regions are selectable.
- Security OU holds Log Archive and Audit accounts; Sandbox OU is optional.
- Controls: preventive (SCP or RCP), detective (Config rules) and proactive (CloudFormation hooks).
- **Account Factory** vends new accounts with a baseline; enrolment brings existing accounts under governance.
@diagram layers
caption: Landing zone
layers:
  - {label: "Management", nodes: ["Management account|Organizations and Control Tower|cp"]}
  - {label: "Security OU", nodes: ["Log Archive|CloudTrail and Config logs|info", "Audit|read access for security|info"]}
  - {label: "Workload OUs", nodes: ["Enrolled accounts|baselined|ok", "New accounts|Account Factory|ok"]}
@h Check status
```bash title="Landing zone" lab
aws controltower list-landing-zones
aws organizations list-roots --query 'Roots[].[Id,Name]'
```
@check
Which two accounts does Control Tower create for logging and audit? || Log Archive and Audit.
@end

@concept Pre-migration assessment
@plain
Inventory what already exists so Control Tower does not collide with your current setup.
@problem
Existing CloudTrail, Config recorders, roles and Regions can block or complicate enrolment.
@does
- List OUs, accounts, SCPs and delegated administrators.
- Existing AWS Config recorders and delivery channels in target Regions may need to be removed or adapted before enrolment, because Control Tower manages them (check the current prerequisites).
- Existing IAM Identity Center configuration, organization trail and StackSets with conflicting names.
- Decide the home Region and governed Regions; they are costly to change.
- Document exceptions; plan a pilot OU first.
@diagram flow
caption: Assessment
numbered: true
nodes:
  - "Inventory|OUs, accounts, SCPs|info"
  - "Conflicts|Config, trails, roles|warn"
  - "Decide Regions|home and governed|cp"
  - "Pilot OU|first enrolment|ok"
@h Inventory scripts
```bash title="Inventory" lab
aws organizations list-accounts --query 'Accounts[].[Id,Name,Status]' --output table
aws organizations list-policies --filter SERVICE_CONTROL_POLICY --query 'Policies[].[Name,AwsManaged]' --output table
aws configservice describe-configuration-recorders --region eu-west-1
```
@check
Why choose the home Region carefully? || It is hard to change later and hosts Control Tower resources.
@end

@concept Enabling the landing zone
@plain
Set up Control Tower from the management account, creating or reusing the Security OU accounts.
@problem
Wrong inputs at this step lock in bad choices such as Region and logging retention.
@does
- Requires an Organization with all features and a management account.
- You can reuse existing account emails for Log Archive and Audit or let Control Tower create them.
- Choose log retention periods and KMS encryption for logs.
- Takes roughly an hour; monitor the setup status.
- Landing zone updates are applied through the console or API, and changes in drift must be repaired.
@diagram flow
caption: Enable
nodes:
  - "Prepare|prerequisites|info"
  - "Launch landing zone|home Region and OUs|cp"
  - "Verify|trail, config, SSO|ok"
@h Landing zone API shape
```bash title="Create landing zone" nocheck
aws controltower create-landing-zone --version 3.3 \
  --manifest file://landing-zone-manifest.json
```
:::note
Check the current landing zone version and manifest format in the documentation before running this.
:::
@end

@concept Enrolling existing accounts and OUs
@plain
Enrolment installs the Control Tower baseline in an existing account so it follows the same guardrails as new ones.
@problem
Hundreds of legacy accounts cannot be recreated, yet they need the same governance.
@does
- Register an OU first (applies baseline and controls to its accounts), or enrol single accounts through Account Factory.
- Prerequisites: the account has the `AWSControlTowerExecution` role trusting the management account, no conflicting Config or CloudTrail, and enough free quota.
- Enrol the pilot OU, test workloads, then move to production OUs in waves.
- Account moves between OUs inherit that OU's controls and SCPs, so review before moving.
@diagram flow
caption: Waves
numbered: true
nodes:
  - "Create role|AWSControlTowerExecution|warn"
  - "Register OU|baseline applied|cp"
  - "Verify workloads|no breakage|app"
  - "Next wave|production OUs|ok"
@h Execution role trust
```json title="execution-role-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
    "Action": "sts:AssumeRole"
  }]
}
```
```bash title="Enrol an OU" nocheck
aws controltower enable-baseline \
  --baseline-identifier arn:aws:controltower:eu-west-1::baseline/17BSJV3IGJ2QSGA2 \
  --baseline-version 4.0 \
  --target-identifier arn:aws:organizations::111122223333:ou/o-exampleorgid/ou-abcd-11111111
```
@check
Which role must exist in an account before it can be enrolled? || AWSControlTowerExecution.
@end

@concept Controls and SCP migration
@plain
Replace homemade SCPs with Control Tower controls where an equivalent exists, and keep custom SCPs for the rest.
@problem
Two overlapping sets of preventive policies confuse troubleshooting and may hit the SCP size limit.
@does
- Mandatory controls always apply; strongly recommended and elective controls are chosen per OU.
- Control Tower SCPs are managed by Control Tower; do not edit them manually.
- Custom SCPs remain allowed, attached separately; test with the policy simulator and a sandbox account.
- Detective controls surface non-compliance as Config findings in the dashboard.
- Check the current control catalogue; it grows.
@diagram cmp
caption: Policy ownership
cards:
  - {h: "Control Tower controls", kind: cp, items: ["Managed for you", "Per OU", "Do not edit"]}
  - {h: "Custom SCPs", kind: info, items: ["Your policy code", "Terraform managed", "Test before attach"]}
@h Enable a control
```bash title="Control" nocheck
aws controltower enable-control \
  --control-identifier arn:aws:controltower:eu-west-1::control/AWS-GR_RESTRICT_ROOT_USER \
  --target-identifier arn:aws:organizations::111122223333:ou/o-exampleorgid/ou-abcd-11111111
```
@end

@concept Customisation with AFT and CfCT
@plain
**Account Factory for Terraform (AFT)** and **Customizations for Control Tower (CfCT)** add your own baselines, networking and roles to new accounts.
@problem
The Control Tower baseline is intentionally small; real accounts need VPCs, roles and tooling.
@does
- AFT: a Terraform pipeline triggered by account request files in Git; runs global and per-account customisations.
- CfCT: CloudFormation StackSets and SCPs from a manifest, triggered by Control Tower lifecycle events.
- Choose one approach to avoid duplication; AFT suits Terraform shops.
- Run both from a dedicated deployment account, not the management account.
@diagram flow
caption: Account request to baseline
numbered: true
nodes:
  - "Pull request|account request file|app"
  - "AFT pipeline|Terraform|cp"
  - "Account Factory|creates account|info"
  - "Customisations|VPC, roles, tags|ok"
@h Account request module
```hcl title="account-request.tf"
module "payments_prod" {
  source = "./modules/aft-account-request"

  control_tower_parameters = {
    AccountEmail              = "aws-payments-prod@example.com"
    AccountName               = "payments-prod"
    ManagedOrganizationalUnit = "Workloads/Prod"
    SSOUserEmail              = "platform@example.com"
    SSOUserFirstName          = "Platform"
    SSOUserLastName           = "Team"
  }

  account_tags = {
    owner = "payments"
    env   = "prod"
  }
}
```
@check
What triggers AFT to build an account? || A merged account request file in Git.
@end

@concept Rollback, drift and operations
@plain
Plan how to repair drift and what to do if enrolment fails.
@problem
Manual changes to Control Tower resources put the landing zone or an OU into a drifted state.
@does
- Common drift: moved accounts, edited managed SCPs or removed roles; the dashboard shows it and offers repair.
- Failed enrolment leaves the account in a failed state; fix the cause then retry.
- Decommissioning a landing zone is possible but heavy; do not treat it as a casual rollback.
- Keep the management account nearly empty; root access protected with MFA.
- Re-run landing zone updates after Control Tower releases new versions.
@diagram flow
caption: Repair loop
nodes:
  - "Drift detected|dashboard|warn"
  - "Review change|who and why|info"
  - "Repair|re-register OU|cp"
  - "Verify|status healthy|ok"
@h Check drift
```bash title="Drift status" lab
aws controltower list-enabled-baselines --query 'enabledBaselines[].[baselineIdentifier,statusSummary.status]' --output table
```
@end
