---
title: IAM evaluation logic, conditions and boundaries
minutes: 50
objectives:
  - Walk through the policy evaluation order and predict allow or deny
  - Use condition keys to restrict by tag, network, MFA and organization
  - Apply permission boundaries and session policies to delegate safely
---
When access is unexpectedly denied or allowed, the answer is in the evaluation logic. Knowing it turns IAM from trial and error into reasoning.

@concept The evaluation order
@plain
For each request AWS gathers every applicable policy and decides with a simple rule: explicit deny wins, otherwise something must allow, otherwise the default is deny.
@problem
Policies come from many layers (SCP, RCP, boundary, session, identity, resource). Without a model you cannot tell which one blocked you.
@does
- Default is **implicit deny**.
- An **explicit deny** in any applicable policy ends evaluation: denied.
- SCPs and RCPs, permission boundaries and session policies are **filters**: the action must be allowed by each that applies.
- Then an identity-based or resource-based **Allow** grants it. Within one account, a resource policy that names the caller's ARN can allow even without an identity policy.
@diagram flow
caption: Decision sequence within one account
numbered: true
nodes:
  - "Any explicit deny?|yes means denied|bad"
  - "SCP and RCP allow?|if organization member|cp"
  - "Boundary and session allow?|if present|cp"
  - "Identity or resource Allow?|needed|app"
  - "Allowed|otherwise implicit deny|ok"
@h Ask the simulator why
```bash title="Decode an authorization failure" lab
aws sts decode-authorization-message --encoded-message "$ENCODED" --query DecodedMessage --output text | python3 -m json.tool | head -40
aws iam simulate-custom-policy --policy-input-list file://p.json \
  --action-names s3:GetObject --resource-arns arn:aws:s3:::acme-reports/a.csv \
  --query 'EvaluationResults[0].EvalDecision'
```
@check
If an SCP allows an action and the identity policy has no matching Allow, what happens? || Implicit deny. An SCP never grants permissions.
@end

@concept Same-account versus cross-account
@plain
Inside one account, an identity policy or a resource policy can alone grant access. Across accounts both the caller's account and the resource's account must allow.
@problem
Engineers see cross-account access fail even though the bucket policy allows, because the caller's role has no matching identity policy.
@does
- Cross-account: identity policy in the caller's account **and** resource policy (or trust policy) in the target account.
- Same account and the resource policy names an IAM **role or user ARN**: allowed without an identity policy. If it names the account root, identity policies still must allow.
- KMS differs: key policy must allow the account (or principal) before IAM policies matter.
@diagram cmp
caption: Who must say yes
cards:
  - {h: "Same account", kind: ok, items: ["Identity Allow is enough", "Or resource policy naming the principal"]}
  - {h: "Cross account", kind: warn, items: ["Caller account identity Allow", "Target resource policy Allow", "Both, no exceptions"]}
  - {h: "KMS keys", kind: cp, items: ["Key policy must allow first", "Then IAM grants may add access"]}
@h Cross-account role trust
```json title="trust-from-account-a.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111111111111:root"},
      "Action": "sts:AssumeRole",
      "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
    }
  ]
}
```
:::note
With `:root` as principal, account A still has to give its own roles `sts:AssumeRole` permission on the target role in an identity policy.
:::
@end

@concept Condition operators and context keys
@plain
A `Condition` block compares **context keys** (facts about the request) with values using operators. All keys in a block must match (AND); multiple values for one key are OR.
@problem
A bare Allow is too coarse. Real rules are "only from our network", "only with MFA", "only on resources tagged to the caller's team".
@does
- Operators: `StringEquals`, `StringLike`, `ArnLike`, `IpAddress`, `Bool`, `NumericLessThan`, `DateGreaterThan`, with `IfExists` and `ForAllValues` / `ForAnyValue` set modifiers.
- Global keys: `aws:SourceIp`, `aws:SourceVpc`, `aws:SourceVpce`, `aws:PrincipalOrgID`, `aws:RequestedRegion`, `aws:CurrentTime`, `aws:SecureTransport`, `aws:MultiFactorAuthPresent`, `aws:PrincipalTag/key`, `aws:ResourceTag/key`.
- Service keys such as `s3:prefix` or `ec2:InstanceType` exist per action; check the Service Authorization Reference.
@diagram flow
caption: Condition evaluation
nodes:
  - "Request context|ip, tags, mfa, time|info"
  - "Operator|StringEquals, IpAddress|cp"
  - "Policy value|from the document|app"
  - "Match?|true means statement applies|ok"
@h Common guardrails
```json title="conditions-examples.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyInsecureTransport",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::acme-data", "arn:aws:s3:::acme-data/*"],
      "Condition": {"Bool": {"aws:SecureTransport": "false"}}
    },
    {
      "Sid": "OnlyFromOurVpcEndpoint",
      "Effect": "Deny",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::acme-data", "arn:aws:s3:::acme-data/*"],
      "Condition": {"StringNotEquals": {"aws:SourceVpce": "vpce-0123456789abcdef0"}}
    }
  ]
}
```
:::warn
A `Deny` with `aws:SourceVpce` also blocks you in the console and CLI from outside the VPC. Keep an exception for an admin role.
:::
@check
How are two keys in one Condition block combined? || With AND: every key must match for the statement to apply.
@end

@concept Tag-based access control
@plain
**ABAC** (attribute-based access control) compares tags on the principal with tags on the resource, so one policy scales to many teams.
@problem
Role-per-team-per-resource policies explode in number. ABAC keeps a small set of policies while teams and resources grow.
@does
- Tag the role (or session) with `team=payments` and the resources with `team=payments`.
- Policy allows actions where `aws:ResourceTag/team` equals `${aws:PrincipalTag/team}`.
- Control tagging itself: restrict `ec2:CreateTags` and `iam:TagRole` so nobody can retag into another team.
- Not all services or actions support tag-based conditions; check each service's documentation.
@diagram flow
caption: One policy, many teams
nodes:
  - "Role tag team=payments|principal|app"
  - "Policy compares tags|ResourceTag equals PrincipalTag|cp"
  - "Instance tag team=payments|resource|env"
  - "Allowed|same team|ok"
@h ABAC policy
```json title="abac-ec2.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:StartInstances", "ec2:StopInstances", "ec2:RebootInstances"],
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {"StringEquals": {"aws:ResourceTag/team": "${aws:PrincipalTag/team}"}}
    },
    {
      "Effect": "Allow",
      "Action": "ec2:RunInstances",
      "Resource": "arn:aws:ec2:*:*:instance/*",
      "Condition": {"StringEquals": {"aws:RequestTag/team": "${aws:PrincipalTag/team}"}}
    }
  ]
}
```
@end

@concept Permission boundaries
@plain
A **permission boundary** is a managed policy set on a user or role as a maximum. The identity gets only what its own policies allow AND the boundary allows.
@problem
You want developers to create roles for their apps without letting them create a role stronger than themselves (privilege escalation).
@does
- Boundary alone grants nothing, like an SCP scoped to one identity.
- Delegation pattern: allow `iam:CreateRole` only when the request sets the approved boundary (`iam:PermissionsBoundary` condition), and deny removing it.
- Deny actions that would let the creator widen the boundary itself.
@diagram layers
caption: Effective permissions are the overlap
layers:
  - {label: "Ceilings", nodes: ["SCP|organization|cp", "Boundary|per identity|cp"]}
  - {label: "Grants", nodes: ["Identity policy|what the role asks for|app"]}
  - {label: "Result", nodes: ["Intersection|only what all allow|ok"]}
@h Force a boundary on created roles
```json title="delegated-role-creation.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "CreateRolesOnlyWithBoundary",
      "Effect": "Allow",
      "Action": ["iam:CreateRole", "iam:PutRolePolicy", "iam:AttachRolePolicy"],
      "Resource": "arn:aws:iam::111122223333:role/app-*",
      "Condition": {"StringEquals": {"iam:PermissionsBoundary": "arn:aws:iam::111122223333:policy/app-boundary"}}
    },
    {
      "Sid": "NeverRemoveBoundary",
      "Effect": "Deny",
      "Action": ["iam:DeleteRolePermissionsBoundary", "iam:PutRolePermissionsBoundary"],
      "Resource": "*"
    }
  ]
}
```
:::note
The Allow above uses the boundary condition on `CreateRole`. For attach actions the condition key is not always available, so test with the policy simulator and rely on the deny statements.
:::
@check
Does a permission boundary give permissions? || No. It only limits what the identity policies can grant.
@end

@concept Session policies and privilege escalation paths
@plain
A **session policy** is passed when assuming a role and further restricts that one session. Escalation paths are combinations of permissions that let an identity gain more power.
@problem
A broker service should hand out narrower credentials than its own role. And permissions such as `iam:PassRole` or `iam:CreatePolicyVersion` quietly allow admin takeover.
@does
- `sts:AssumeRole --policy` or `--policy-arns` yields a session with the intersection of role policy and session policy.
- `iam:PassRole` lets a principal give a role to a service (EC2, Lambda, ECS). Restrict which roles and which services (`iam:PassedToService`).
- Risky permissions: `iam:*` on policies, `iam:AttachUserPolicy`, `iam:CreateAccessKey` on other users, `iam:UpdateAssumeRolePolicy`, `lambda:UpdateFunctionCode` on privileged functions.
@diagram cmp
caption: Dangerous permission combinations
cards:
  - {h: "PassRole plus RunInstances", kind: bad, items: ["Launch with a powerful role", "Read its credentials"]}
  - {h: "UpdateAssumeRolePolicy", kind: bad, items: ["Rewrite who may assume", "Take over a role"]}
  - {h: "Constrained PassRole", kind: ok, items: ["Specific role ARNs", "iam:PassedToService condition"]}
@h Narrowing a session
```bash title="Assume with a session policy" lab
aws sts assume-role --role-arn arn:aws:iam::111122223333:role/broker \
  --role-session-name tenant-a \
  --policy '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"s3:GetObject","Resource":"arn:aws:s3:::acme-data/tenant-a/*"}]}' \
  --duration-seconds 900
```
@end
