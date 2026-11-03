---
title: IAM Identity Center, SCPs and access governance
minutes: 50
objectives:
  - Set up workforce access with IAM Identity Center permission sets and SSO profiles
  - Apply service control policies and permission boundaries as guardrails
  - Use IAM Access Analyzer to find external access and unused permissions
---
Access governance means every human and machine has the least access needed, granted through one central place, with guardrails that no individual account can bypass.

@concept IAM Identity Center
@plain
IAM Identity Center (successor to AWS SSO) gives your workforce single sign-on to all accounts in an Organization. Users sign in once through your identity provider (Astra Connect, Okta, Entra ID) and pick an account and role.
@problem
Long-lived IAM users with access keys per account are hard to offboard, audit and rotate.
@does
- A **permission set** is a template of policies; assigning it to a user or group in an account creates a managed role `AWSReservedSSO_<name>_<hash>` there.
- Identity sources: the built-in directory, Active Directory, or an external IdP via SAML and SCIM provisioning.
- Sessions are short (1 to 12 hours) and temporary credentials are issued through the CLI.
- Groups map to permission sets per account, so access reviews become group reviews.
@diagram flow
caption: Sign in once, assume per account
nodes:
  - "Identity provider|SSO and MFA|ext"
  - "Identity Center|portal|cp"
  - "Permission set|PlatformAdmin|info"
  - "Account role|temporary credentials|ok"
@h CLI
```bash title="Configure and use an SSO profile" lab
aws configure sso    # prompts for start URL, region, account and permission set
aws sso login --profile shop-prod-admin
aws sts get-caller-identity --profile shop-prod-admin
aws eks update-kubeconfig --name shop-prod --profile shop-prod-admin
```
@check
What does Identity Center create in a member account? || An IAM role per assigned permission set, named AWSReservedSSO.
@end

@concept Permission sets and groups
@plain
A permission set combines AWS managed policies, customer managed policies, an inline policy, a permissions boundary and a session duration.
@problem
Hand-crafted roles per team and account lead to inconsistency and over-broad access.
@does
- Standard set: `ReadOnly`, `Developer` (edit in a namespace/workload scope), `PlatformAdmin`, `BillingViewer`, `SecurityAudit`.
- Attach customer managed policies by name; they must exist in every target account.
- Use **attribute-based access control** with IdP attributes (department, cost-center) passed as session tags.
- Manage the whole thing as code (Terraform `aws_ssoadmin_permission_set`).
@diagram layers
caption: People to access
layers:
  - {label: "Groups in IdP", nodes: ["platform-eng|admin|app", "shop-devs|developer|app", "auditors|read only|app"]}
  - {label: "Permission sets", nodes: ["PlatformAdmin|4h session|cp", "Developer|8h session|cp", "SecurityAudit|read only|cp"]}
  - {label: "Accounts", nodes: ["shop-prod|workload|env", "shop-dev|workload|env", "log-archive|logs|env"]}
@h Terraform
```hcl title="Permission set with a managed policy"
resource "aws_ssoadmin_permission_set" "dev" {
  name             = "Developer"
  instance_arn     = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  session_duration = "PT8H"
}

resource "aws_ssoadmin_managed_policy_attachment" "dev_view" {
  instance_arn       = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  managed_policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
  permission_set_arn = aws_ssoadmin_permission_set.dev.arn
}
```
@check
Why assign permission sets to groups rather than users? || Joiners and leavers then change group membership in the IdP, not AWS configuration.
@end

@concept Service control policies
@plain
An SCP is an Organization policy that sets the maximum permissions for accounts in an OU. It never grants access; it only limits what IAM can allow.
@problem
Even an account administrator could disable CloudTrail, leave the Organization, or use a Region you do not operate in.
@does
- Attach SCPs to the root, OUs or accounts; permissions are the intersection of the SCP chain and IAM.
- They do not affect the management account or service-linked roles.
- Typical guardrails: deny non-approved Regions, deny disabling CloudTrail/GuardDuty/Config, deny leaving the Organization, deny root user actions, require encryption.
- Test in a sandbox OU first; a wrong deny can lock out automation.
@diagram flow
caption: Effective permission
nodes:
  - "SCP at root|allow list or deny|cp"
  - "SCP at OU|narrower|info"
  - "IAM policy|grant|app"
  - "Allowed only if all agree|intersection|ok"
@h Deny Regions
```json title="Deny actions outside approved Regions"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyOtherRegions",
      "Effect": "Deny",
      "NotAction": ["iam:*", "organizations:*", "route53:*", "cloudfront:*", "support:*", "sts:*"],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {"aws:RequestedRegion": ["us-east-1", "eu-west-1"]}
      }
    },
    {
      "Sid": "ProtectSecurityServices",
      "Effect": "Deny",
      "Action": ["cloudtrail:StopLogging", "cloudtrail:DeleteTrail", "guardduty:DeleteDetector", "config:StopConfigurationRecorder"],
      "Resource": "*"
    }
  ]
}
```
@check
Does an SCP grant permissions? || No; it only restricts what IAM policies may allow.
@end

@concept Permission boundaries and least privilege
@plain
A **permissions boundary** caps the permissions an IAM role can ever have, even if someone attaches AdministratorAccess to it.
@problem
Developers need to create roles for their workloads without being able to create a role more powerful than themselves.
@does
- Allow role creation only when the new role carries a specific boundary policy (`iam:PermissionsBoundary` condition).
- The boundary and the identity policy must both allow an action.
- Good practice: start with Access Analyzer-generated policies from CloudTrail activity, then tighten.
- Prefer roles and temporary credentials; avoid IAM users and access keys. Rotate or delete unused keys.
@diagram flow
caption: Delegated role creation
nodes:
  - "Developer role|can CreateRole|app"
  - "Condition|boundary must be attached|warn"
  - "New workload role|identity policy|info"
  - "Effective|policy AND boundary|ok"
@h Policy
```json title="Create roles only with the boundary"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["iam:CreateRole", "iam:AttachRolePolicy", "iam:PutRolePolicy"],
      "Resource": "arn:aws:iam::111122223333:role/shop-*",
      "Condition": {
        "StringEquals": {"iam:PermissionsBoundary": "arn:aws:iam::111122223333:policy/ShopBoundary"}
      }
    }
  ]
}
```
@check
What stops a developer from creating a role with admin rights? || The boundary condition forces the new role to carry a boundary that caps its permissions.
@end

@concept IAM Access Analyzer
@plain
Access Analyzer finds resources shared outside your account or Organization, validates policies, and reports unused access.
@problem
A public S3 bucket, a role trusting an unknown account, or a forgotten admin role are invisible in day-to-day work.
@does
- **External access findings** for S3, IAM roles, KMS keys, SQS, Lambda, secrets and more.
- **Unused access findings** list unused roles, users, keys and permissions (extra cost).
- **Policy validation and generation**: check JSON for errors and create least-privilege policies from CloudTrail.
- Findings go to Security Hub and EventBridge for alerts.
@diagram flow
caption: Continuous review
nodes:
  - "Analyzer|org zone of trust|cp"
  - "Findings|public or cross-account|warn"
  - "Triage|intended or fix|info"
  - "Archive or remediate|closed|ok"
@h CLI
```bash title="Create an organisation analyzer and list findings" nocheck
aws accessanalyzer create-analyzer --analyzer-name org-analyzer --type ORGANIZATION
aws accessanalyzer list-findings-v2 --analyzer-arn arn:aws:access-analyzer:us-east-1:111122223333:analyzer/org-analyzer \
  --filter '{"status":{"eq":["ACTIVE"]}}' --query 'findings[].[resourceType,resource]' --output table
```
@check
What does external access analysis detect? || Resources shared outside your account or organisation, such as public buckets or cross-account trust.
@end

@concept Organizations, accounts and break-glass
@plain
Multiple accounts are the strongest security boundary: separate workloads, environments and logging into different accounts under one Organization.
@problem
One account for everything means one blast radius, one quota pool and tangled permissions.
@does
- Typical layout: management (billing only), security tooling, log archive, shared services/network, then workload accounts per environment.
- AWS **Control Tower** or a landing zone sets baseline guardrails.
- Lock the root user: MFA, no access keys, root access management features, alarm on root login.
- Keep a **break-glass** role with MFA and strong alerting for when SSO is down.
@diagram layers
caption: Account structure
layers:
  - {label: "Management", nodes: ["Org root|billing, SCPs|cp"]}
  - {label: "Security OU", nodes: ["Security tooling|GuardDuty, Security Hub admin|ok", "Log archive|CloudTrail, Config|ok"]}
  - {label: "Infrastructure OU", nodes: ["Network|Transit Gateway|info", "Shared services|ECR, CI|info"]}
  - {label: "Workloads OU", nodes: ["shop-prod|production|app", "shop-dev|development|app"]}
@h Root alarm
```bash title="Show who signed in as root recently" nocheck
aws cloudtrail lookup-events --lookup-attributes AttributeKey=Username,AttributeValue=root --max-results 5 \
  --query 'Events[].[EventTime,EventName]' --output table
```
@check
Why use several accounts? || Accounts limit blast radius, quotas and permissions between workloads and environments.
@end
