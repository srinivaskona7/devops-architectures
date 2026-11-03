---
title: IAM principals and policies
minutes: 45
objectives:
  - Distinguish users, groups, roles and the root user and choose the right one
  - Read and write identity-based and resource-based JSON policies
  - Apply least privilege using managed policies and generated policies
---
**IAM** decides who can do what to which resource. Every API call to AWS, whether from the console, the CLI, Terraform or a pod, is evaluated by IAM first. This file covers the building blocks; the next ones cover evaluation, roles and workload identity.

@concept Principals, identities and the root user
@plain
A **principal** is whoever makes a request. In IAM it is a user, a role, a federated identity, an AWS service, or an anonymous caller. The **root user** is the account owner with unrestricted power.
@problem
Without distinct identities you cannot attribute actions, grant different people different rights, or revoke one without breaking all.
@does
- **IAM user**: long-lived identity with a password and/or access keys. Avoid for people (use Identity Center) and for workloads (use roles).
- **IAM group**: a set of users to attach policies to. It is not a principal and cannot be named in a trust policy.
- **IAM role**: an identity with no credentials of its own that is assumed to get temporary credentials.
- **Root user**: a few tasks need it (closing the account, changing the support plan, some billing settings). Lock it with MFA and never create keys.
@diagram cmp
caption: Which identity for which job
cards:
  - {h: "Human", kind: app, items: ["Identity Center user", "Assumes a role per account", "Short sessions, MFA"]}
  - {h: "Workload on AWS", kind: ok, items: ["Instance profile, task role, IRSA", "No stored keys"]}
  - {h: "CI outside AWS", kind: info, items: ["OIDC federation to a role", "No stored keys"]}
  - {h: "IAM user with keys", kind: bad, items: ["Last resort", "Rotate, scope, monitor"]}
@h See identities
```bash title="List and inspect" lab
aws iam list-roles --query 'Roles[].RoleName' --output text | tr '\t' '\n' | head
aws iam list-users --query 'Users[].[UserName,PasswordLastUsed]' --output table
aws iam generate-credential-report >/dev/null && sleep 3
aws iam get-credential-report --query Content --output text | base64 -d | head -3
```
@check
Can a group be the principal in a role trust policy? || No. Groups are only containers for attaching permissions to users.
@end

@concept Anatomy of a policy
@plain
A policy is a JSON document listing statements. Each statement says Allow or Deny, for which actions, on which resources, and optionally under which conditions.
@problem
Permissions need to be precise and reviewable. A document format lets you version, diff and test them like code.
@does
- `Effect`: Allow or Deny. `Action`: service:Operation, wildcards allowed. `Resource`: ARNs. `Condition`: extra tests.
- `NotAction` and `NotResource` invert the match, and are easy to misuse.
- `Principal` appears only in resource-based and trust policies.
- `Sid` is an optional label. `Version` should be `2012-10-17` to enable policy variables.
@diagram flow
caption: Reading one statement
nodes:
  - "Effect|Allow or Deny|cp"
  - "Action|s3:GetObject|app"
  - "Resource|arn of bucket/prefix|env"
  - "Condition|only if tests pass|warn"
@h A minimal read-only policy
```json title="s3-read-reports.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListBucket",
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::acme-reports",
      "Condition": {"StringLike": {"s3:prefix": ["monthly/*"]}}
    },
    {
      "Sid": "ReadObjects",
      "Effect": "Allow",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::acme-reports/monthly/*"
    }
  ]
}
```
:::note
Note the two resources: `s3:ListBucket` applies to the bucket ARN, `s3:GetObject` to object ARNs (`bucket/key`). Mixing them is the most common reason an S3 policy "does not work".
:::
@end

@concept Identity-based, resource-based and trust policies
@plain
Permissions can be attached to the caller (identity-based), to the thing being called (resource-based), or to a role to say who may assume it (trust policy).
@problem
Cross-account and service-to-service access need the target to say who is welcome. Identity policies alone cannot express that.
@does
- **Identity-based**: attached to users, groups, roles. No `Principal` element.
- **Resource-based**: S3 bucket policies, SQS, SNS, KMS keys, Lambda, ECR, Secrets Manager and others. Has `Principal`.
- **Trust policy**: the resource-based policy of a role, controlling `sts:AssumeRole`.
- Within one account, an Allow in either identity or resource policy is enough (for most services). Across accounts, both sides must allow.
@diagram seq
caption: Cross-account S3 read needs both sides
actors: ["Role in account A|caller|app", "IAM in A|identity policy|cp", "Bucket in B|bucket policy|env"]
steps:
  - "0>1: s3:GetObject on bucket in B | req"
  - "1>0: identity policy allows | resp"
  - "0>2: request arrives | req"
  - "2>0: bucket policy names account A | resp"
  - "note 0..2: both allow, so access is granted"
@h Cross-account bucket policy
```json title="bucket-policy-cross-account.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowRoleFromAccountA",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111111111111:role/reports-reader"},
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::acme-reports/*"
    }
  ]
}
```
@check
Where do you say who can assume a role? || In the role's trust policy, which is a resource-based policy attached to the role.
@end

@concept Managed, inline and customer policies
@plain
A **managed policy** is a standalone policy attached in many places. An **inline policy** is embedded in one identity. AWS managed policies are written by AWS; customer managed ones are yours.
@problem
Copy-pasting permissions into each role creates drift. AWS managed policies are convenient but broad and change without your review.
@does
- Customer managed policies are versioned (up to five versions, check the current quota) so you can roll back.
- AWS managed policies such as `ReadOnlyAccess` are fine for exploration, risky as production grants.
- Inline policies die with the identity: useful for a strict one-to-one relationship.
- There are size limits per policy and number of attached policies per role; check the current quotas.
@diagram flow
caption: Policy lifecycle in infrastructure as code
numbered: true
nodes:
  - "Write JSON|in Git|plain"
  - "Validate|access analyzer checks|info"
  - "Review|pull request|cp"
  - "Apply|Terraform|app"
  - "Attach|role or group|ok"
@h Terraform for a role and customer policy
```hcl title="iam.tf"
data "aws_iam_policy_document" "reports_read" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::acme-reports/monthly/*"]
  }
}

resource "aws_iam_policy" "reports_read" {
  name   = "reports-read"
  policy = data.aws_iam_policy_document.reports_read.json
}

resource "aws_iam_role_policy_attachment" "reports" {
  role       = aws_iam_role.app.name
  policy_arn = aws_iam_policy.reports_read.arn
}
```
@choose Policy kind
Customer managed | reuse and version control | a one-off tightly bound to one role
Inline | a permission that must never be reused | many roles need the same grant
AWS managed | quick read-only exploration | production least privilege
@end

@concept ARNs, wildcards and policy variables
@plain
An **ARN** names a resource: `arn:partition:service:region:account:resource`. Wildcards `*` and `?` and variables like `${aws:username}` let one policy cover many resources.
@problem
Hardcoding every resource name makes policies huge; a blanket `*` makes them dangerous.
@does
- Partition is `aws`, `aws-cn` or `aws-us-gov`. Some services leave region or account empty, S3 bucket ARNs have neither.
- Variables such as `${aws:PrincipalTag/team}` or `${aws:userid}` personalise one policy per caller.
- Prefer exact ARNs, then prefix wildcards. Avoid `Action: "*"` with `Resource: "*"` outside break-glass roles.
@diagram layers
caption: ARN parts
layers:
  - {label: "arn", nodes: ["aws|partition|plain", "ec2|service|app", "eu-west-1|region|info", "111122223333|account|cp", "instance/i-0abc|resource|env"]}
@h Per-user S3 prefix
```json title="home-prefix.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::acme-home/${aws:userid}/*"
    }
  ]
}
```
:::warn
`Version` must be `2012-10-17` or variables are treated as literal text.
:::
@check
Why do S3 ARNs have no account or Region? || Bucket names are globally unique within a partition, so the ARN needs only the name.
@end

@concept Least privilege in practice
@plain
Least privilege means granting only what is needed. In practice you start narrow, observe denials, and tighten from usage data.
@problem
Teams start with `AdministratorAccess` to unblock themselves and never come back. Over-permissioned roles are what turn a leaked token into a breach.
@does
- IAM Access Analyzer can **generate a policy** from CloudTrail activity of a role over a chosen period.
- `Last accessed` data for services and actions shows what is unused.
- `aws iam simulate-principal-policy` tests whether an identity may perform an action before you deploy.
- Use tags and conditions to scale (for example a team can touch only resources tagged with its name).
@diagram flow
caption: Tightening loop
numbered: true
nodes:
  - "Start broad in dev|log everything|warn"
  - "Collect CloudTrail|real usage|info"
  - "Generate policy|from activity|cp"
  - "Review and deploy|Git|app"
  - "Prod gets the tight version|ok|ok"
@h Simulate and check usage
```bash title="Policy simulator and last accessed" lab
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::111122223333:role/app \
  --action-names s3:GetObject s3:DeleteObject \
  --resource-arns arn:aws:s3:::acme-reports/monthly/a.csv \
  --query 'EvaluationResults[].[EvalActionName,EvalDecision]' --output table
JOB=$(aws iam generate-service-last-accessed-details \
  --arn arn:aws:iam::111122223333:role/app --query JobId --output text)
aws iam get-service-last-accessed-details --job-id "$JOB" \
  --query 'ServicesLastAccessed[?TotalAuthenticatedEntities>`0`].[ServiceNamespace,LastAuthenticated]'
```
@end

@concept Passwords, MFA and access keys
@plain
Humans prove identity with a password plus **MFA**; programs with access keys or, better, temporary credentials.
@problem
Stolen long-lived keys are the most common cloud breach path. They sit in repos, laptops and CI variables for years.
@does
- Enforce MFA for console users; prefer phishing-resistant passkeys or FIDO2 security keys where supported.
- An access key is an ID plus secret. A user can hold at most two, so rotation is possible without outage.
- `aws iam list-access-keys` and the credential report show age and last use. Delete unused keys.
- Roles issue temporary credentials via STS that expire, so a leak is time-limited.
@diagram cmp
caption: Long-lived keys versus temporary credentials
cards:
  - {h: "Access key", kind: bad, items: ["Never expires on its own", "Leaks live in Git history", "Needs rotation process"]}
  - {h: "STS credentials", kind: ok, items: ["Expire in minutes to hours", "Tied to a role and session", "Nothing to rotate"]}
@h Find old keys
```bash title="Audit keys" lab
aws iam get-credential-report --query Content --output text | base64 -d \
  | awk -F, 'NR>1 && $9=="true" {print $1, "key1 last used:", $11}'
aws iam update-access-key --user-name ci-legacy --access-key-id AKIAEXAMPLEEXAMPLE --status Inactive
```
:::danger
If a key was ever committed, treat it as compromised: deactivate it, check CloudTrail for its use, then delete. Removing the commit is not enough.
:::
@end
