---
title: IAM, service accounts and workload identity
minutes: 55
objectives:
  - Grant access with principals, roles and allow policies at the right level of the hierarchy
  - Replace service account keys with impersonation and workload identity federation
  - Restrict access further with IAM conditions, deny policies and the IAM recommender
---
Google Cloud IAM answers who can do what on which resource. The policy is attached to a resource and inherited downward, which differs from the per-account model in AWS.

@concept Principals, roles and allow policies
@plain
An **allow policy** is a list of bindings. Each binding gives a **role** (a set of permissions) to one or more **principals** on one resource.
@problem
You need to grant people and workloads just enough access, and manage it at scale without per-user policies everywhere.
@does
- Principals: Google accounts, groups, Cloud Identity domains, service accounts, workforce and workload identity pool identities, and `allUsers` (public).
- Roles come as basic (`owner`, `editor`, `viewer`, avoid these), predefined (`roles/storage.objectViewer`) and custom.
- A policy on a folder applies to all projects below it. Effective access is the union of inherited and local bindings, then reduced by deny policies.
- **AWS equivalent**: identity and resource policies attached to users, roles and resources. Main difference: in Google Cloud you attach roles to the resource, and groups are the preferred way to give people access.
@diagram flow
caption: A binding
nodes:
  - "Principal|group or service account|ext"
  - "Role|set of permissions|info"
  - "Resource|project, folder or bucket|app"
  - "Allow policy|binding list|cp"
@h Grant and read a policy
```bash title="Bindings" lab
gcloud projects add-iam-policy-binding shop-dev-123456 \
  --member="group:shop-devs@example.com" --role="roles/container.developer"
gcloud projects get-iam-policy shop-dev-123456 --format=json
gcloud iam roles describe roles/container.developer --format="value(includedPermissions)" | head
```
:::danger
Do not use `roles/owner` or `roles/editor` for workloads. Editor alone allows changes to nearly every service.
:::
@check
Where should you grant a role that every project in a folder needs? || On the folder, to a group.
@end

@concept Predefined and custom roles
@plain
A predefined role is maintained by Google. A **custom role** is a list of permissions you define yourself at the project or organization level.
@problem
Predefined roles are sometimes too broad, yet writing exact permission lists for everything is tedious to maintain.
@does
- Prefer predefined roles first; look at `gcloud iam roles list` and the permissions reference.
- Custom roles need maintenance because new permissions are not added automatically. Check each permission's launch stage.
- Permissions name pattern: `service.resource.verb`, for example `storage.objects.get`.
- **AWS equivalent**: managed policies versus customer managed policies. Main difference: roles are named permission sets that you bind, not documents containing resources and conditions.
@diagram layers
caption: Role types
layers:
  - {label: "Basic", nodes: ["owner, editor, viewer|too broad|bad"]}
  - {label: "Predefined", nodes: ["roles/storage.objectViewer|Google maintained|ok", "roles/container.admin|Google maintained|ok"]}
  - {label: "Custom", nodes: ["Org or project level|you maintain|warn"]}
@h Create a custom role
```bash title="Custom role" lab
gcloud iam roles create shopDeployer --project=shop-dev-123456 \
  --title="Shop deployer" \
  --permissions=container.deployments.update,container.pods.list,container.pods.get \
  --stage=GA
gcloud iam roles list --project=shop-dev-123456 --format="table(name,title)"
```
@end

@concept Service accounts
@plain
A **service account** is an identity for software. It is also a resource, so you can grant roles to it and grant others the ability to use it.
@problem
Applications need an identity that is not a person, with limited permissions and no password.
@does
- Email form: `name@PROJECT_ID.iam.gserviceaccount.com`.
- Attached to a VM, Cloud Run service or build, it supplies tokens through the metadata server.
- Using one needs `iam.serviceAccounts.actAs` (via `roles/iam.serviceAccountUser`). Treat that as a powerful permission, since it lets someone run code as the account.
- Create one per workload. The default Compute Engine service account carries the editor role in old projects; avoid it.
- **AWS equivalent**: an IAM role with an instance profile. Main difference: a service account is a principal that exists permanently, while an AWS role is assumed and gives temporary credentials.
@diagram flow
caption: Using a service account
nodes:
  - "Workload|VM, pod, Cloud Run|app"
  - "Metadata server|token endpoint|cp"
  - "Service account|roles granted|info"
  - "Google API|call allowed|ok"
@h Create and grant
```bash title="Service account for the Shop API" lab
gcloud iam service-accounts create shop-api --display-name="Shop API" --project=shop-dev-123456
gcloud projects add-iam-policy-binding shop-dev-123456 \
  --member="serviceAccount:shop-api@shop-dev-123456.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```
@check
What permission lets a user run a workload as a service account? || iam.serviceAccounts.actAs, included in roles/iam.serviceAccountUser.
@end

@concept Service account impersonation
@plain
**Impersonation** lets an authorised principal obtain short-lived credentials for a service account without ever holding a key.
@problem
Downloaded JSON keys leak, never expire by default and are hard to track.
@does
- Needs `roles/iam.serviceAccountTokenCreator` on the target service account.
- `gcloud --impersonate-service-account=SA` runs one command as that account; Terraform supports `impersonate_service_account`.
- Audit logs show both the caller and the service account.
- The organization policy `iam.disableServiceAccountKeyCreation` blocks keys entirely.
- **AWS equivalent**: `sts:AssumeRole`. Main difference: very similar idea; the call is `generateAccessToken` and the token lasts up to an hour by default.
@diagram seq
caption: Impersonation flow
actors: ["Engineer|user|ext", "IAM Credentials API|token service|cp", "Service account|target|info", "Google API|resource|app"]
steps:
  - "0>1: generateAccessToken for SA | req"
  - "note 1..2: check TokenCreator role"
  - "1>0: short-lived token | resp"
  - "0>3: call API with token | tls"
@h Use it
```bash title="Impersonation" lab
gcloud iam service-accounts add-iam-policy-binding \
  tf-deployer@shop-dev-123456.iam.gserviceaccount.com \
  --member="group:platform@example.com" --role="roles/iam.serviceAccountTokenCreator"
gcloud storage ls gs://shop-dev-state \
  --impersonate-service-account=tf-deployer@shop-dev-123456.iam.gserviceaccount.com
```
@end

@concept Workload identity federation for external workloads
@plain
**Workload Identity Federation** lets a workload outside Google Cloud (GitHub Actions, AWS, Azure, on-premises OIDC) exchange its own token for Google credentials.
@problem
CI systems and other clouds used to hold service account keys, which is a standing secret that can leak.
@does
- You create a **workload identity pool** and a **provider** (OIDC or AWS or SAML), with an attribute mapping and a condition.
- External token goes to the Security Token Service, and returns a federated token; it can be used directly or to impersonate a service account.
- Always set an attribute condition, otherwise any identity from that provider may match.
- **AWS equivalent**: an IAM OIDC identity provider with `AssumeRoleWithWebIdentity`. Main difference: since the pool is defined per provider with CEL mapping and conditions rather than a trust policy on the role.
@diagram seq
caption: Token exchange
actors: ["External job|GitHub Actions|ext", "STS|token exchange|cp", "Service account|impersonated|info", "Google API|target|app"]
steps:
  - "0>1: OIDC token | tls"
  - "note 1..1: map claims, check condition"
  - "1>0: federated token | resp"
  - "0>2: generateAccessToken | req"
  - "2>0: access token | resp"
  - "0>3: API call | tls"
@h Pool and provider for one repository
```bash title="Workload identity pool" lab
gcloud iam workload-identity-pools create github --location=global --project=shop-dev-123456
gcloud iam workload-identity-pools providers create-oidc github-oidc \
  --location=global --workload-identity-pool=github \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='example-org/shop'" \
  --project=shop-dev-123456
```
@check
Why must you set an attribute condition on a GitHub provider? || Otherwise any repository on GitHub could match the provider.
@end

@concept IAM conditions
@plain
A **condition** is an expression that makes a role binding apply only in some circumstances.
@problem
You want time-boxed access, access limited to certain resource names, or access only until a date.
@does
- Written in Common Expression Language (CEL), for example `request.time < timestamp("2027-01-01T00:00:00Z")` or `resource.name.startsWith("projects/_/buckets/shop-")`.
- Attributes depend on the service; not every service supports every attribute. Check the current docs.
- Bindings with conditions require policy version 3.
- **AWS equivalent**: the `Condition` block in IAM policies. Main difference: the condition is attached to a single binding, not to a policy statement.
@diagram flow
caption: Conditional binding
nodes:
  - "Request|principal, time, resource|plain"
  - "Binding|role with condition|info"
  - "CEL expression|true or false|cp"
  - "Decision|grant or ignore|ok"
@h Temporary access
```bash title="Time limited binding" lab
gcloud projects add-iam-policy-binding shop-prod-123456 \
  --member="user:oncall@example.com" --role="roles/container.admin" \
  --condition='expression=request.time < timestamp("2027-02-01T00:00:00Z"),title=oncall-feb,description=Temporary access'
```
@end

@concept IAM deny policies
@plain
A **deny policy** blocks specific principals from specific permissions, regardless of what allow policies grant.
@problem
Allow policies are additive, so inherited grants are hard to take away at a lower level.
@does
- Deny is evaluated first and wins over allow. Attach to organization, folder or project.
- Rules list denied principals, optional exceptions and permissions in the form `service.googleapis.com/resource.verb`.
- Typical use: block deleting audit sinks or creating service account keys for all but a break-glass group.
- **AWS equivalent**: explicit `Deny` in SCPs or identity policies. Main difference: deny policies are a separate policy type, not statements inside the allow policy.
@diagram flow
caption: Evaluation order
nodes:
  - "Request|permission check|plain"
  - "Deny policies|explicit block|bad"
  - "Allow policies|inherited union|ok"
  - "Result|allowed or denied|cp"
@h Deny file
```json title="deny-sa-keys.json"
{
  "displayName": "Deny SA key creation",
  "rules": [
    {
      "denyRule": {
        "deniedPrincipals": ["principalSet://goog/public:all"],
        "exceptionPrincipals": ["principalSet://goog/group/breakglass@example.com"],
        "deniedPermissions": ["iam.googleapis.com/serviceAccountKeys.create"]
      }
    }
  ]
}
```
```bash title="Attach to the organization" lab
gcloud iam policies create deny-sa-keys --attachment-point="cloudresourcemanager.googleapis.com/organizations/123456789012" \
  --kind=denypolicies --policy-file=deny-sa-keys.json
```
@check
If an allow policy grants a permission and a deny policy denies it, what happens? || The request is denied.
@end

@concept IAM Recommender and Policy Troubleshooter
@plain
The **IAM Recommender** suggests removing roles that were not used, using about 90 days of activity. The **Policy Troubleshooter** explains why a principal can or cannot do something.
@problem
Permissions grow over time and nobody knows which are still needed. Debugging a "403" is slow without a tool.
@does
- Recommendations include role removal or replacement with a narrower role; review before applying.
- Policy Analyzer answers "who can access this resource" across the hierarchy.
- Troubleshooter evaluates allow, deny and conditions for one principal and permission.
- **AWS equivalent**: IAM Access Analyzer and last accessed information. Main difference: recommendations are generated natively per binding and can be applied directly.
@diagram flow
caption: Least privilege loop
nodes:
  - "Usage data|about 90 days|info"
  - "Recommender|suggests narrower role|cp"
  - "Review|human approves|warn"
  - "Apply|updated binding|ok"
@h Query them
```bash title="Recommender and troubleshooter" lab
gcloud recommender recommendations list --project=shop-dev-123456 \
  --location=global --recommender=google.iam.policy.Recommender --format="table(name,stateInfo.state,description)"
gcloud policy-troubleshooter iam //cloudresourcemanager.googleapis.com/projects/shop-dev-123456 \
  --principal-email=dev@example.com --permission=container.clusters.get
```
:::note
Some commands sit in beta groups in older gcloud versions. Check `gcloud help` for your version.
:::
@end
