---
title: Accounts, Organizations and Control Tower
minutes: 50
objectives:
  - Explain why an AWS account is the strongest isolation boundary and how to structure many of them
  - Design an Organizations hierarchy and write service control policies safely
  - Describe what Control Tower automates and when to use Account Factory
---
Everything in AWS lives inside an **account**. Real companies run dozens or hundreds of them, so the first skill is not a service but a structure: how accounts are grouped, who may create them, and which guardrails apply to all of them.

@concept The AWS account as a boundary
@plain
An account is a container for resources, with its own users, quotas, bill and blast radius. Nothing is shared with another account unless you explicitly allow it.
@problem
If production, development and security tooling share one account, a mistaken `delete` or a leaked key in development can reach production. Quotas are also per account, so one noisy team can exhaust limits for everyone.
@does
- IAM permissions, service quotas, VPCs and costs are scoped to an account (and mostly to a Region inside it).
- Cross-account access is always explicit: a role in the target account that trusts the caller.
- A new account starts with one **root user** (the sign-up email). Protect it with MFA and do not create access keys for it.
@diagram cmp
caption: One account for everything versus an account per purpose
cards:
  - {h: "Single account", kind: bad, items: ["One blast radius", "Shared quotas and bill", "Complex IAM to separate teams"]}
  - {h: "Account per environment", kind: ok, items: ["Prod isolated from dev", "Separate quotas and costs", "Simple, strong IAM boundaries"]}
@h Look at where you are
```bash title="Who am I and which account" lab
aws sts get-caller-identity                       # account ID, user or role ARN
aws iam list-account-aliases                      # friendly name, if any
aws account get-contact-information 2>/dev/null   # needs account:GetContactInformation
```
@check
Why is an account a stronger boundary than a VPC or a tag? || IAM, quotas, billing and resources are all scoped to it, so a mistake or compromise cannot cross it without an explicit cross-account trust.
@end

@concept AWS Organizations and OUs
@plain
**AWS Organizations** joins many accounts under one **management account**. Accounts are arranged in a tree of **organizational units (OUs)** under a **root**, and policies attached to a node apply to everything below it.
@problem
Creating accounts by hand gives you no central billing, no common rules and no way to answer "which accounts do we own?". Organizations gives one inventory and one place to enforce policy.
@does
- Consolidated billing: one payer, shared Savings Plans and volume discounts.
- Programmatic account creation with `organizations create-account`.
- Policy types: service control policies (SCPs), resource control policies (RCPs), tag policies, backup policies, AI opt-out policies.
- Trusted service access lets services such as CloudTrail, Config, GuardDuty and Identity Center work across the organization, usually through a **delegated administrator** account so the management account stays almost empty.
@diagram layers
caption: A common OU layout
layers:
  - {label: "Root", nodes: ["Management account|billing and Organizations only|cp"]}
  - {label: "Foundation OUs", nodes: ["Security OU|log archive, audit|ok", "Infrastructure OU|network, shared services|info"]}
  - {label: "Workload OUs", nodes: ["Prod OU|production accounts|app", "NonProd OU|dev and test accounts|env", "Sandbox OU|experiments with low limits|warn"]}
@h Inspect an organization
```bash title="Organizations CLI" lab
aws organizations describe-organization --query 'Organization.[Id,MasterAccountId]'
aws organizations list-roots --query 'Roots[0].Id' --output text
ROOT_ID=$(aws organizations list-roots --query 'Roots[0].Id' --output text)
aws organizations list-organizational-units-for-parent --parent-id "$ROOT_ID"
aws organizations list-accounts --query 'Accounts[].[Id,Name,Status]' --output table
```
:::warn
Run workloads in the management account only if you have no choice. SCPs do not apply to it, so it cannot be restricted by the guardrails you build.
:::
@end

@concept Multi-account strategy
@plain
A multi-account strategy decides which accounts exist and why. The usual split is by function (security, network, shared tooling) and then by workload and environment.
@problem
Without a plan, accounts appear ad hoc, naming drifts, and the log or network team cannot find or protect what it needs.
@does
- **Log archive** account receives CloudTrail, Config and flow logs, write-only for others, with Object Lock where required.
- **Audit/security** account hosts read-only security tooling and aggregated findings.
- **Network** account owns Transit Gateway, shared VPCs or central egress and inspection.
- **Shared services** hold CI runners, image pipelines and registries.
- Workload accounts per application and environment, so IAM and cost are clear.
@diagram flow
caption: How a request for a new workload becomes an account
numbered: true
nodes:
  - "Team request|name, owner, environment|plain"
  - "Account vending|pipeline or Account Factory|cp"
  - "Baseline applied|logging, roles, guardrails|info"
  - "Network attached|VPC from IPAM, TGW route|env"
  - "Handed over|team assumes a role|ok"
@choose Account granularity
Per application and environment | prod needs strict isolation and clear cost | you have a handful of tiny services with one owner
Per environment shared by apps | small team, few apps | teams must not see each other's data
Shared sandbox accounts | learning with automatic cleanup | anything holding real data
@check
Which account should hold organization-wide audit logs? || A dedicated log archive account with restricted write access, not the management account and not the workload accounts that produce the logs.
@end

@concept Service control policies
@plain
An **SCP** is a ceiling on what any principal in an account can do. It never grants access; it only removes the possibility of it.
@problem
IAM administrators inside an account can grant themselves anything. Central teams need rules that account admins cannot override, such as "never leave approved Regions" or "never disable CloudTrail".
@does
- Attached to the root, an OU or an account; inherited downward. An action is allowed only if every level between the root and the account allows it.
- Apply to all IAM users and roles in member accounts, including the member's root user. They do not apply to the management account or to service-linked roles.
- The default `FullAWSAccess` policy is attached everywhere; the common pattern is to keep it and add **deny** statements.
- There is a quota on SCP count per target and policy size; check the current quota.
@diagram flow
caption: An action must pass every layer
numbered: true
nodes:
  - "Request|iam user or role in account|plain"
  - "SCP root|allowed?|cp"
  - "SCP OU|allowed?|cp"
  - "SCP account|allowed?|cp"
  - "IAM policies|allowed?|app"
  - "Allowed|all layers agree|ok"
@h Deny leaving approved Regions
```json title="region-guardrail.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyOutsideApprovedRegions",
      "Effect": "Deny",
      "NotAction": ["iam:*", "organizations:*", "sts:*", "support:*", "cloudfront:*", "route53:*", "budgets:*"],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {"aws:RequestedRegion": ["eu-west-1", "eu-central-1"]},
        "ArnNotLike": {"aws:PrincipalARN": "arn:aws:iam::*:role/OrgBreakGlass"}
      }
    },
    {
      "Sid": "ProtectCloudTrail",
      "Effect": "Deny",
      "Action": ["cloudtrail:StopLogging", "cloudtrail:DeleteTrail"],
      "Resource": "*"
    }
  ]
}
```
```bash title="Create and attach" lab
aws organizations create-policy --name region-guardrail --type SERVICE_CONTROL_POLICY \
  --description "Approved Regions only" --content file://region-guardrail.json
aws organizations attach-policy --policy-id p-examplepolicyid --target-id ou-examplerootid-exampleouid
```
:::danger
Test an SCP on a sandbox OU first. A wrong deny can lock every role out, including the ones your pipelines use. Keep a break-glass role excluded by condition, as above.
:::
@check
Can an SCP allow an action that IAM does not? || No. An SCP only limits. The identity or resource policy still has to grant the permission.
@end

@concept Other organization policies and RCPs
@plain
SCPs control what your principals can do. **Resource control policies (RCPs)** control what can be done to your resources, whoever the caller is. Tag, backup and declarative policies standardise configuration.
@problem
You may need to guarantee that no S3 bucket in the organization can be reached by an outside account, even if a developer writes a permissive bucket policy.
@does
- RCPs set a maximum permission on resources of supported services in member accounts, including requests from principals outside the organization. Check the documentation for the services currently supported.
- **Tag policies** define allowed tag keys and values; they report non-compliance and can enforce on supported resource types.
- **Backup policies** apply AWS Backup plans organization-wide.
- **Declarative policies** enforce a baseline configuration of a service, for example blocking public access for AMIs or enforcing IMDSv2 defaults, regardless of API changes.
@diagram cmp
caption: Which policy limits whom
cards:
  - {h: "SCP", kind: cp, items: ["Limits principals in your accounts", "Ceiling for IAM users and roles"]}
  - {h: "RCP", kind: info, items: ["Limits access to your resources", "Also covers outside principals"]}
  - {h: "Declarative", kind: env, items: ["Fixes a service setting", "Holds even if APIs change"]}
@h Data perimeter example
```json title="rcp-s3-org-only.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "OnlyOrgPrincipalsOrAwsServices",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": "*",
      "Condition": {
        "StringNotEqualsIfExists": {"aws:PrincipalOrgID": "o-exampleorgid"},
        "BoolIfExists": {"aws:PrincipalIsAWSService": "false"}
      }
    }
  ]
}
```
:::note
This is an illustration of the data perimeter idea. Real RCPs need exceptions for third-party integrations, so roll out with logging and review.
:::
@end

@concept Control Tower and landing zones
@plain
**AWS Control Tower** builds and maintains a **landing zone**: a pre-configured multi-account environment with logging, guardrails and an account vending machine.
@problem
Doing the foundation by hand (Organizations, CloudTrail, Config, baseline roles, SCPs) takes weeks and drifts. Control Tower gives a supported starting point.
@does
- Creates Security and Log Archive accounts, an organization-wide CloudTrail and AWS Config recording.
- **Controls** (formerly guardrails) are preventive (implemented as SCPs or RCPs), detective (AWS Config rules) or proactive (CloudFormation hooks).
- **Account Factory** provisions accounts from a template; **Account Factory for Terraform (AFT)** and Customizations for Control Tower (CfCT) add your own baselines through a pipeline.
- Lands under a home Region; check the current list of governed Regions and drift repair options.
@diagram layers
caption: What Control Tower sets up
layers:
  - {label: "Governance", nodes: ["Controls|preventive, detective, proactive|cp", "Dashboard|compliance by OU|info"]}
  - {label: "Foundation accounts", nodes: ["Management|Control Tower runs here|plain", "Log Archive|CloudTrail, Config logs|ok", "Audit|security tooling|ok"]}
  - {label: "Vending", nodes: ["Account Factory|console or Service Catalog|app", "AFT or CfCT|Git driven customization|env"]}
@h Look at a landing zone
```bash title="Control Tower CLI" lab
aws controltower list-landing-zones
aws controltower list-enabled-controls --target-identifier arn:aws:organizations::111122223333:ou/o-exampleorgid/ou-examplerootid-exampleouid
aws servicecatalog search-provisioned-products --filters 'SearchQuery=type:CONTROL_TOWER_ACCOUNT' 2>/dev/null | head -20
```
@choose Landing zone approach
Control Tower | you want a supported baseline fast | you need an unusual layout it cannot model
Organizations plus Terraform | you want full control and have platform engineers | you have no team to maintain it
Custom plus Control Tower controls | you adopt controls but vend accounts yourself | you want zero custom code
@check
What is the difference between a preventive and a detective control? || Preventive blocks the action up front (SCP or RCP). Detective only reports non-compliance after the fact (an AWS Config rule).
@end

@concept Account lifecycle, billing and quotas
@plain
Accounts are created, tagged, budgeted, and eventually closed. Each has quotas that you may need to raise.
@problem
Surprise bills, forgotten sandbox accounts and exhausted limits are the most frequent account-level incidents.
@does
- **AWS Budgets** alerts per account, OU or tag. Cost allocation tags must be activated in Billing before they appear in reports.
- **Service Quotas** shows each quota and its current value; many can be raised by request. Some are hard limits. Always check the current quota instead of relying on remembered numbers.
- Closing an account moves it to a suspended state for a period before permanent deletion; check the current rules and limits on closures per period.
- Alternate contacts (billing, security, operations) should point to monitored mailboxes, not a person.
@diagram flow
caption: Account lifecycle
nodes:
  - "Vend|baseline and budget|cp"
  - "Operate|tags, quotas, guardrails|app"
  - "Review|cost and access|info"
  - "Close|move to suspended OU first|warn"
@h Quotas and budgets
```bash title="Quotas and budgets" lab
aws service-quotas list-service-quotas --service-code vpc \
  --query 'Quotas[].[QuotaName,Value,Adjustable]' --output table | head -20
aws service-quotas get-service-quota --service-code ec2 --quota-code L-1216C47A   # Running On-Demand Standard instances (vCPUs)
aws budgets describe-budgets --account-id 111122223333 --query 'Budgets[].BudgetName'
```
:::tip
Put a low-limit, auto-nuke or budget-action policy on Sandbox accounts. Cost surprises almost always start there.
:::
@end
