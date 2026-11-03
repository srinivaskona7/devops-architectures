---
title: Roles, STS and Identity Center
minutes: 45
objectives:
  - Explain how AssumeRole and STS temporary credentials work
  - Set up cross-account access and role chaining with the right limits
  - Give people single sign-on with IAM Identity Center and permission sets
---
Roles and temporary credentials are the centre of modern AWS access. People sign in once and receive short-lived role sessions; workloads never store keys.

@concept IAM roles and trust
@plain
A role is an identity with permissions but no password or keys. Anyone allowed by its **trust policy** can ask STS for temporary credentials for it.
@problem
Giving each person or service its own long-lived key multiplies secrets. A role lets many callers share one permission set with credentials that expire.
@does
- Two policies matter: the **trust policy** (who may assume) and the **permission policies** (what the session can do).
- Callers can be IAM principals, other accounts, AWS services (EC2, Lambda), SAML or OIDC identities.
- `sts:AssumeRole` returns an access key, secret key and session token.
@diagram seq
caption: Assuming a role
actors: ["Caller|user or workload|app", "STS|token service|cp", "AWS API|target service|env"]
steps:
  - "0>1: AssumeRole(role arn) | req"
  - "note 1..1: check trust policy and caller permission"
  - "1>0: temporary key, secret, token | resp"
  - "0>2: API call signed with temporary credentials | req"
  - "2>0: allowed per role policies | resp"
@h Role with a trust policy in Terraform
```hcl title="role.tf"
data "aws_iam_policy_document" "trust" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::111111111111:role/ci-runner"]
    }
    condition {
      test     = "StringEquals"
      variable = "sts:ExternalId"
      values   = ["acme-build-2026"]
    }
  }
}

resource "aws_iam_role" "deployer" {
  name                 = "deployer"
  assume_role_policy   = data.aws_iam_policy_document.trust.json
  max_session_duration = 3600
}
```
@check
What two kinds of policy define a role? || A trust policy (who can assume it) and permission policies (what the session may do).
@end

@concept STS and temporary credentials
@plain
**AWS STS** issues temporary credentials. They consist of an access key ID, a secret and a session token, and they expire.
@problem
You need credentials that become useless on their own, so a leak does not need manual cleanup.
@does
- `AssumeRole` (roles), `AssumeRoleWithWebIdentity` (OIDC), `AssumeRoleWithSAML`, `GetSessionToken` (MFA for users), `GetCallerIdentity` (who am I).
- Role session duration defaults to one hour; the role's maximum can be raised up to twelve hours. Check the current limits.
- **Role chaining** (a role assumes another role) caps the session at one hour.
- Regional STS endpoints are recommended over the global one for latency and resilience.
@diagram flow
caption: Credential sources in the CLI and SDK default chain
numbered: true
nodes:
  - "Environment|AWS_ACCESS_KEY_ID and token|info"
  - "Web identity|AWS_WEB_IDENTITY_TOKEN_FILE|app"
  - "Shared config|profiles, SSO, assume role|cp"
  - "Container creds|ECS or Pod Identity|env"
  - "Instance metadata|EC2 role via IMDSv2|ok"
@h Profiles that assume roles
```ini title="~/.aws/config"
[profile base]
region = eu-west-1
sso_session = corp
sso_account_id = 111122223333
sso_role_name = Developer

[profile prod-deployer]
role_arn = arn:aws:iam::444455556666:role/deployer
source_profile = base
role_session_name = srinivas
duration_seconds = 3600

[sso-session corp]
sso_start_url = https://example.awsapps.com/start
sso_region = eu-west-1
sso_registration_scopes = sso:account:access
```
```bash title="Use them" lab
aws sso login --sso-session corp
aws sts get-caller-identity --profile prod-deployer
aws sts assume-role --role-arn arn:aws:iam::444455556666:role/deployer --role-session-name test \
  --query 'Credentials.Expiration'
```
:::tip
Always set `--role-session-name`. It appears in CloudTrail and is how you tell who did what behind a shared role.
:::
@end

@concept Cross-account access and the confused deputy
@plain
To reach resources in another account you assume a role there. When a third party does it on your behalf, add an **external ID** so they cannot be tricked into acting for the wrong customer.
@problem
A SaaS vendor assumes roles in many customers' accounts. Without a unique secret, customer B could name customer A's role ARN and the vendor would use its own trust to access A (confused deputy).
@does
- `sts:ExternalId` condition in the trust policy for third parties.
- For AWS services acting on your resources use `aws:SourceArn` and `aws:SourceAccount` conditions.
- Keep trusts to specific role ARNs rather than whole accounts where possible.
@diagram cmp
caption: Trusting an account root versus a role ARN
cards:
  - {h: "Trust account root", kind: warn, items: ["Any principal there with permission", "Broader than needed"]}
  - {h: "Trust one role ARN", kind: ok, items: ["Only that role", "Role must exist", "Easier to audit"]}
  - {h: "Third party", kind: info, items: ["Specific role plus ExternalId", "Vendor supplies the ID"]}
@h Service confused deputy protection
```json title="sns-topic-policy-fragment.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "events.amazonaws.com"},
      "Action": "sns:Publish",
      "Resource": "arn:aws:sns:eu-west-1:111122223333:alerts",
      "Condition": {
        "ArnEquals": {"aws:SourceArn": "arn:aws:events:eu-west-1:111122223333:rule/cpu-high"},
        "StringEquals": {"aws:SourceAccount": "111122223333"}
      }
    }
  ]
}
```
@check
Which condition protects against the confused deputy for a third party? || sts:ExternalId in the role trust policy.
@end

@concept Instance profiles and service roles
@plain
An **instance profile** is the wrapper that attaches a role to an EC2 instance. Other services (Lambda, ECS tasks, CodeBuild) have service roles with their own trust.
@problem
Applications on an instance need AWS credentials without baking keys into images.
@does
- The instance reads temporary credentials from the **instance metadata service** (IMDS) at `169.254.169.254` and the SDK refreshes them automatically.
- Require **IMDSv2** (session tokens) and a hop limit of 1 so containers or SSRF bugs cannot easily steal them. On EKS nodes, a hop limit of 2 may be needed for pods that use node credentials, which is better avoided with Pod Identity.
- A role can be attached or replaced on a running instance with `associate-iam-instance-profile`.
@diagram flow
caption: How the SDK gets credentials on EC2
nodes:
  - "SDK on instance|no keys configured|app"
  - "IMDSv2 token|PUT with TTL header|info"
  - "Role credentials|GET security-credentials|cp"
  - "Signed request|to AWS APIs|ok"
@h IMDSv2 by hand and enforcement
```bash title="Read and enforce IMDSv2" lab
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/
aws ec2 modify-instance-metadata-options --instance-id i-0123456789abcdef0 \
  --http-tokens required --http-put-response-hop-limit 1 --http-endpoint enabled
```
:::warn
Setting hop limit 1 breaks pods that read node credentials through the IMDS. Move them to IRSA or Pod Identity first.
:::
@end

@concept Federation with OIDC for CI systems
@plain
Instead of storing AWS keys in CI, the CI system presents a signed **OIDC token** and AWS exchanges it for role credentials.
@problem
Keys in GitHub or GitLab secrets leak and never rotate.
@does
- Create an IAM **OIDC identity provider** for the issuer (for example `token.actions.githubusercontent.com`).
- Role trust uses `sts:AssumeRoleWithWebIdentity` and conditions on `sub` and `aud` claims to restrict by repository and branch.
- The same mechanism underlies IRSA for Kubernetes service accounts.
@diagram seq
caption: CI job obtains credentials without a stored key
actors: ["CI job|pipeline run|app", "OIDC issuer|signs a token|ext", "STS|validates token|cp"]
steps:
  - "0>1: request ID token for aud sts.amazonaws.com | req"
  - "1>0: signed JWT with sub repo and ref | resp"
  - "0>2: AssumeRoleWithWebIdentity(JWT) | req"
  - "note 2..2: verify signature, aud, sub condition"
  - "2>0: temporary credentials | resp"
@h Trust policy restricting a repository
```json title="github-oidc-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Federated": "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"},
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
        "StringLike": {"token.actions.githubusercontent.com:sub": "repo:acme/platform:ref:refs/heads/main"}
      }
    }
  ]
}
```
:::danger
A trust policy with no `sub` condition lets any repository on that issuer assume your role.
:::
@check
Which claim restricts which repo may assume the role? || The sub claim, matched in the trust policy condition.
@end

@concept IAM Identity Center
@plain
**IAM Identity Center** is single sign-on for your AWS accounts. People log in once with your company identity provider and pick an account and role.
@problem
Managing IAM users in every account does not scale and leaves orphan users when people leave.
@does
- Identity source can be the built-in directory, Active Directory, or an external IdP via SAML and SCIM (for example Entra ID, Okta).
- **Permission sets** are templates (managed and inline policies, boundary, session duration). Assigning a permission set to a user or group in an account creates a role named `AWSReservedSSO_<name>_<hash>` there.
- Enable at the organization level and delegate administration to a member account.
- The CLI uses `aws configure sso` and `aws sso login`; access tokens are cached locally.
@diagram flow
caption: From corporate login to a role session
numbered: true
nodes:
  - "Corporate IdP|MFA, groups|ext"
  - "Identity Center|portal and assignments|cp"
  - "Permission set|policy template|info"
  - "Role in account|AWSReservedSSO role|app"
  - "Session|1 to 12 hours|ok"
@h Permission set in Terraform
```hcl title="sso.tf"
data "aws_ssoadmin_instances" "this" {}

resource "aws_ssoadmin_permission_set" "readonly" {
  name             = "ReadOnly"
  instance_arn     = tolist(data.aws_ssoadmin_instances.this.arns)[0]
  session_duration = "PT4H"
}

resource "aws_ssoadmin_managed_policy_attachment" "readonly" {
  instance_arn       = aws_ssoadmin_permission_set.readonly.instance_arn
  managed_policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
  permission_set_arn = aws_ssoadmin_permission_set.readonly.arn
}
```
```bash title="Developer login flow" lab
aws configure sso
aws sso login --profile dev
aws sts get-caller-identity --profile dev
```
@choose Human access
Identity Center | any multi-account organization | a single tiny account with one admin
IAM users | break-glass emergency only | everyday human access
SAML federation per account | legacy IdP integrations | you can use Identity Center instead
@end
