---
title: Entra ID identities, apps and managed identities
minutes: 55
objectives:
  - Choose between user, service principal, managed identity and federated credential
  - Create app registrations and service principals from the CLI
  - Remove stored secrets using managed identities and workload identity federation
---
Everything in Azure starts with a token issued by Microsoft Entra ID. This page covers the identity types you will meet and when to pick each.

@concept Users and groups
@plain
Users are people (or guests from other tenants). Groups bundle users, devices and other principals so you assign access once.
@problem
Granting roles to individuals does not scale and leaves orphaned access when people move teams.
@does
- **AWS equivalent**: IAM Identity Center users and groups.
- **Main difference**: Entra users are tenant-wide and authenticate to Azure, Microsoft 365 and your own apps with the same account. Always assign RBAC to groups, not users.
- Security groups can be assigned roles; Microsoft 365 groups are for collaboration. Role-assignable groups need to be created as such.
- Guests (B2B) are external users invited into your tenant.
@diagram flow
caption: Assign access through groups
nodes:
  - "User|alice|plain"
  - "Group|sg-shop-operators|info"
  - "Role assignment|AKS Cluster User|cp"
  - "Resource|AKS cluster|app"
@h Create a group and add a member
```bash title="Groups" lab
GID=$(az ad group create --display-name sg-shop-operators --mail-nickname sg-shop-operators --query id -o tsv)
az ad group member add --group "$GID" --member-id $(az ad user show --id alice@contoso.com --query id -o tsv)
az ad group member list --group "$GID" --query '[].userPrincipalName' -o tsv
```
@end

@concept App registrations and service principals
@plain
An **app registration** is the definition of an application in your tenant. A **service principal** is its identity inside a tenant, the thing that receives roles.
@problem
Pipelines and services need an identity that is not a person.
@does
- **AWS equivalent**: an IAM role or IAM user used by automation. A service principal is closest to a role with credentials.
- **Main difference**: two objects exist. The registration (global definition, holds redirect URIs and credentials) and the service principal (per tenant, holds role assignments). `az ad sp create-for-rbac` makes both.
- Credentials are a client secret or certificate that expire. Avoid them when you can; see federation and managed identity.
@diagram flow
caption: Registration and service principal
nodes:
  - "App registration|definition and credentials|cp"
  - "Service principal|identity in the tenant|info"
  - "Role assignment|scope plus role|env"
  - "Azure resources|what it may touch|app"
@h Create without a secret printed to history
```bash title="Service principal" lab
az ad sp create-for-rbac --name sp-shop-deploy --role Contributor \
  --scopes /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-shop-prod
az ad sp list --display-name sp-shop-deploy --query '[].{appId:appId,id:id}' -o table
```
:::warn
The output holds a client secret that is shown once. Prefer federated credentials for CI so there is nothing to leak.
:::
@check
Which object receives the role assignment, the registration or the service principal? || The service principal.
@end

@concept Managed identities
@plain
A **managed identity** is a service principal whose credentials Azure creates, rotates and hands only to the resource that owns it.
@problem
Applications on Azure need to call other services without any password in config.
@does
- **AWS equivalent**: IAM role for EC2 or task role (instance profile).
- **Main difference**: two flavours. **System-assigned** lives and dies with one resource. **User-assigned** is its own resource that you attach to many resources and is the better default for AKS, since it survives recreation.
- Code asks the IMDS endpoint or uses `DefaultAzureCredential` in an SDK; no secret is involved.
- You give it roles like any principal.
@diagram seq
caption: Managed identity token flow
actors: ["App on VM or pod|workload|app", "IMDS|169.254.169.254|cp", "Entra ID|issues token|ext", "Storage|target service|env"]
steps:
  - "0>1: request token for storage | req"
  - "1>2: authenticate identity | tls"
  - "2>1: access token | resp"
  - "1>0: access token | resp"
  - "0>3: call with bearer token | req"
@h Create and use
```bash title="User-assigned identity" lab
az identity create -g rg-shop-prod -n id-shop-api
PID=$(az identity show -g rg-shop-prod -n id-shop-api --query principalId -o tsv)
az role assignment create --assignee-object-id "$PID" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" --scope $(az storage account show -n stshopprod -g rg-shop-prod --query id -o tsv)
```
@end

@concept Workload identity federation
@plain
**Federated identity credentials** let an external token (from GitHub, a Kubernetes cluster, Google) be exchanged for an Entra token with no secret.
@problem
CI systems and non-Azure clusters used to hold long-lived client secrets that leak and expire.
@does
- **AWS equivalent**: IAM OIDC identity provider plus `AssumeRoleWithWebIdentity` (IRSA, GitHub OIDC).
- **Main difference**: the trust is configured on the app registration or user-assigned identity by issuer, subject and audience, not in a role trust policy.
- Subject must match exactly, for example `repo:org/repo:ref:refs/heads/main` or `system:serviceaccount:shop:api`.
- Used by GitHub Actions, AKS Workload Identity and Azure DevOps service connections.
@diagram seq
caption: Token exchange
actors: ["Workload|GitHub job or pod|app", "OIDC issuer|signs its own JWT|ext", "Entra ID|checks federated credential|cp", "Azure|ARM or service|env"]
steps:
  - "0>1: ask for signed JWT | req"
  - "1>0: JWT with subject | resp"
  - "0>2: exchange JWT | tls"
  - "2>0: Entra access token | resp"
  - "0>3: call Azure | req"
@h Add a GitHub federated credential
```bash title="Federated credential" lab
APPID=$(az ad app create --display-name gh-shop --query appId -o tsv)
az ad app federated-credential create --id "$APPID" --parameters '{
  "name": "gh-main",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:contoso/shop:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'
```
@check
What must match exactly for the exchange to succeed? || The issuer, subject and audience configured on the federated credential.
@end

@concept Conditional Access
@plain
**Conditional Access** is an if-then policy engine: if a sign-in matches conditions (user, app, location, risk, device) then require controls (MFA, compliant device, block).
@problem
A password alone is not enough. You need stronger checks for risky sign-ins and admin actions.
@does
- **AWS equivalent**: IAM condition keys plus Identity Center MFA settings, though less central.
- **Main difference**: it is evaluated at sign-in for every Entra-integrated app, including the Azure portal and `az login`. It needs Entra ID P1 or higher; check licensing.
- Start in **report-only** mode and review sign-in logs before enforcing.
- Always exclude emergency break-glass accounts.
- Workload identities can also be covered, with limits; check current docs.
@diagram flow
caption: Policy evaluation at sign-in
nodes:
  - "Sign-in|user, app, location, risk|ext"
  - "Conditions|match policy|info"
  - "Grant controls|MFA, compliant device|cp"
  - "Token issued|or blocked|ok"
@h Review policies
```bash title="List policies via Graph" lab
az rest --method get --url https://graph.microsoft.com/v1.0/identity/conditionalAccess/policies \
  --query 'value[].{name:displayName,state:state}' -o table
```
:::warn
Test a policy in report-only mode first. A bad policy without a break-glass exclusion can lock every administrator out.
:::
@end

@concept Privileged Identity Management
@plain
**PIM** makes powerful roles eligible instead of permanent. A person activates a role for a limited time, with justification and sometimes approval.
@problem
Standing Owner or Global Administrator access is the biggest prize for an attacker.
@does
- **AWS equivalent**: no direct service. Closest is IAM Identity Center with short sessions or third-party just-in-time tools.
- **Main difference**: works for both Entra roles and Azure RBAC roles, and for group membership. Requires Entra ID P2 or Governance licences; check current docs.
- Settings per role: maximum duration, MFA on activation, approvers, notifications and access reviews.
- Audit history shows who activated what and why.
@diagram flow
caption: Just in time elevation
nodes:
  - "Eligible|no access yet|plain"
  - "Activate|MFA and reason|info"
  - "Active for 2 hours|role is usable|warn"
  - "Expires|back to no access|ok"
@h Inspect eligibility
```bash title="Eligible assignments" lab
az rest --method get --url "https://graph.microsoft.com/v1.0/roleManagement/directory/roleEligibilitySchedules" \
  --query 'value[].{principal:principalId,role:roleDefinitionId}' -o table
```
@end

@concept Choosing the right identity
@plain
Pick the identity type from where the code runs, not from habit.
@problem
Teams reuse one shared service principal secret everywhere, which spreads the blast radius.
@does
- **AWS equivalent**: choosing between IAM role, IRSA and access keys.
- **Main difference**: Azure has no access keys for identities; the closest to long-lived keys are client secrets, which should be the last resort.
- Rule of thumb: running on Azure means managed identity; in AKS means workload identity; in GitHub or Azure DevOps means federation; only else a certificate before a secret.
@diagram flow
caption: Decision path
nodes:
  - "Runs on Azure|VM, App Service, Function|app"
  - "Runs in AKS|pod service account|app"
  - "Runs in CI|GitHub or Azure DevOps|ext"
  - "Anything else|certificate, then secret|warn"
@choose Pick an identity type
Managed identity | code runs on an Azure resource | code runs outside Azure
Workload identity | pods in AKS need Azure access | you are not on Kubernetes
Federated credential | CI from GitHub or Azure DevOps | the issuer is not OIDC capable
Client secret or certificate | no federation is possible | any other option exists
@end

@concept Device and human sign-in from the CLI
@plain
`az login` has several modes and picking the right one avoids broken scripts and policy lockouts.
@problem
Automation using a personal login breaks when the person leaves or MFA expires.
@does
- **AWS equivalent**: `aws sso login`, `aws configure`.
- **Main difference**: tokens are cached under `~/.azure`; there is no config profile model, but `AZURE_CONFIG_DIR` gives you separate sessions.
- `az login` opens a browser; `--use-device-code` suits headless shells; `--service-principal` and `--federated-token` suit pipelines; `--identity` uses a managed identity.
- `az account set` picks the active subscription.
@diagram cmp
caption: Login modes
cards:
  - {h: "Humans", kind: app, items: ["az login", "--use-device-code", "MFA and Conditional Access apply"]}
  - {h: "Automation", kind: info, items: ["--identity on Azure", "--federated-token in CI", "--service-principal as last resort"]}
@h Examples
```bash title="Login variants" lab
az login --tenant 00000000-0000-0000-0000-000000000000
az account set --subscription "shop-prod"
az login --identity --client-id 00000000-0000-0000-0000-000000000001
az login --service-principal -u "$AZURE_CLIENT_ID" --tenant "$AZURE_TENANT_ID" --federated-token "$(cat token.jwt)"
```
@end
