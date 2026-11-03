---
title: Azure RBAC, Entra roles and Azure Policy
minutes: 50
objectives:
  - Explain how Azure RBAC differs from Entra roles and from AWS IAM policies
  - Assign built-in and custom roles at the correct scope
  - Enforce guardrails with Azure Policy and resource locks
---
Azure separates who can change the directory, who can change resources and what is allowed to exist at all. Three systems, three jobs.

@concept RBAC role assignments
@plain
An Azure RBAC assignment is three things: a **principal**, a **role definition** and a **scope**.
@problem
You need permissions that follow the resource tree and are easy to audit.
@does
- **AWS equivalent**: IAM policy attached to a principal.
- **Main difference**: AWS evaluates JSON policies with allow and deny. Azure RBAC is additive allow only: you get the union of all assignments at the scope and above. Deny exists only via deny assignments (managed by Blueprints and deployment stacks) and Policy.
- Core built-in roles: Owner, Contributor, Reader, User Access Administrator. Contributor cannot grant access.
- Assignments take up to a few minutes to apply.
@diagram flow
caption: Anatomy of an assignment
nodes:
  - "Principal|user, group, identity|plain"
  - "Role definition|set of actions|info"
  - "Scope|management group to resource|env"
  - "Effective access|union of all assignments|ok"
@h Assign and list
```bash title="Assignments" lab
az role assignment create --assignee-object-id "$GID" --assignee-principal-type Group \
  --role "Azure Kubernetes Service Cluster User Role" \
  --scope $(az aks show -g rg-shop-prod -n aks-shop-prod --query id -o tsv)
az role assignment list --scope /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-shop-prod -o table
```
@check
Can an Azure RBAC assignment deny access? || No. RBAC is additive. Denies come from deny assignments or Policy.
@end

@concept Management plane versus data plane roles
@plain
Roles contain `actions` for the management plane and `dataActions` for the data inside a service.
@problem
Being Owner of a storage account does not automatically allow reading its blobs, which surprises people.
@does
- **AWS equivalent**: IAM actions such as `s3:GetObject` are all in one namespace. Azure splits them.
- **Main difference**: Contributor can change the storage account and list keys, but reading blob data through Entra needs `Storage Blob Data Reader`. Key Vault, Service Bus and Cosmos DB have similar split roles.
- Inspect any role definition to see both lists.
- Key access (shared keys, SAS) bypasses this model, so disable it where you can.
@diagram layers
caption: Two planes
layers:
  - {label: "Management plane", nodes: ["Create account|actions|cp", "Change settings|actions|cp"]}
  - {label: "Data plane", nodes: ["Read blob|dataActions|app", "Get secret|dataActions|app", "Send message|dataActions|app"]}
@h Look inside a role
```bash title="Role definition" lab
az role definition list --name "Storage Blob Data Reader" --query '[0].permissions[0]' -o json
az role definition list --name "Contributor" --query '[0].permissions[0].{actions:actions,not:notActions}' -o json
```
@end

@concept Custom roles
@plain
A custom role is your own list of actions, with assignable scopes.
@problem
Built-in roles are sometimes too broad, for example Contributor lets people delete production.
@does
- **AWS equivalent**: customer managed IAM policy.
- **Main difference**: only allow lists with optional `notActions` subtraction; wildcards allowed. Created as JSON and assignable at chosen scopes.
- Use sparingly. Look for a narrow built-in first, for example `Azure Kubernetes Service RBAC Writer`.
- Check the current quota on custom roles per tenant.
@diagram flow
caption: Custom role lifecycle
nodes:
  - "Find actions|az provider operation|info"
  - "Write JSON|actions, assignableScopes|plain"
  - "Create role|at management group|cp"
  - "Assign|to a group|ok"
@h Define one
```json title="role-vm-restarter.json"
{
  "Name": "VM Restarter",
  "Description": "Start, restart and view virtual machines",
  "Actions": [
    "Microsoft.Compute/virtualMachines/read",
    "Microsoft.Compute/virtualMachines/start/action",
    "Microsoft.Compute/virtualMachines/restart/action"
  ],
  "NotActions": [],
  "AssignableScopes": ["/subscriptions/00000000-0000-0000-0000-000000000000"]
}
```
```bash title="Create" lab
az role definition create --role-definition @role-vm-restarter.json
```
@end

@concept Entra roles versus Azure roles
@plain
Entra roles control the directory (users, apps, Conditional Access). Azure roles control resources. They are separate systems.
@problem
People ask "I am Global Administrator, why can I not see the subscription?" and the opposite.
@does
- **AWS equivalent**: no split. IAM covers both the directory (IAM users) and resources.
- **Main difference**: Global Administrator has no Azure resource access by default, but it can use "elevate access" to become User Access Administrator at the root scope. Use it rarely and audit it.
- Examples of Entra roles: Application Administrator, Groups Administrator, Conditional Access Administrator.
- Creating app registrations is governed by Entra roles; assigning Azure roles to that app needs RBAC rights.
@diagram cmp
caption: Two role systems
cards:
  - {h: "Entra roles", kind: cp, items: ["Users, groups, apps", "Conditional Access", "Scope is directory or admin unit", "Managed in Entra"]}
  - {h: "Azure RBAC roles", kind: app, items: ["VMs, AKS, storage", "Scope is a resource tree level", "Managed in ARM", "Inherited downwards"]}
@h Compare
```bash title="Two commands, two systems" lab
az role assignment list --assignee alice@contoso.com --all -o table
az rest --method get --url "https://graph.microsoft.com/v1.0/users/alice@contoso.com/memberOf/microsoft.graph.directoryRole" --query 'value[].displayName'
```
@check
Does Global Administrator include permissions on Azure subscriptions? || No, but it can elevate access explicitly.
@end

@concept Azure Policy basics
@plain
**Azure Policy** evaluates resources against rules and can audit, deny, modify or deploy things when they do not comply.
@problem
RBAC says who can act. Nothing yet says that all storage accounts must disable public access or that only EU regions are allowed.
@does
- **AWS equivalent**: SCPs for deny and AWS Config rules for compliance, combined.
- **Main difference**: one service does both prevention (`deny`) and detection (`audit`), and also remediation (`modify`, `deployIfNotExists`). Applies even to Owners.
- Effects: `audit`, `deny`, `modify`, `append`, `deployIfNotExists`, `auditIfNotExists`, `disabled`.
- Built-in definitions cover most needs; assign them at management group scope.
@diagram flow
caption: A request meets a deny policy
nodes:
  - "Create resource|ARM request|ext"
  - "Policy evaluation|rules and parameters|cp"
  - "Deny|returns RequestDisallowedByPolicy|bad"
  - "Allow|resource created|ok"
@h Assign a built-in policy
```bash title="Allowed locations" lab
DEF=$(az policy definition list --query "[?displayName=='Allowed locations'].name | [0]" -o tsv)
az policy assignment create --name allowed-locations --display-name "Allowed locations" \
  --policy "$DEF" --scope /subscriptions/00000000-0000-0000-0000-000000000000 \
  --params '{"listOfAllowedLocations":{"value":["westeurope","northeurope"]}}'
az policy state summarize --query 'results.policyDetails[0]' -o json
```
@end

@concept Custom policy definitions and initiatives
@plain
A policy definition has an `if` condition and a `then` effect. An **initiative** bundles many definitions into one assignment.
@problem
Compliance baselines have dozens of rules, and assigning them one by one is unmanageable.
@does
- **AWS equivalent**: AWS Config conformance packs; custom rules map to custom Config rules or Guard.
- **Main difference**: policy rules are JSON over resource aliases (for example `Microsoft.Storage/storageAccounts/allowBlobPublicAccess`).
- Find aliases with `az provider show` or the Policy aliases reference.
- Remediation tasks fix existing resources for `modify` and `deployIfNotExists`.
@diagram layers
caption: Policy building blocks
layers:
  - {label: "Assignment", nodes: ["Scope, parameters, exemptions|where it applies|cp"]}
  - {label: "Initiative", nodes: ["Group of definitions|baseline|info"]}
  - {label: "Definition", nodes: ["if condition|alias and operator|app", "then effect|deny or audit|app"]}
@h Deny public blob access
```json title="deny-public-blob.json"
{
  "mode": "Indexed",
  "policyRule": {
    "if": {
      "allOf": [
        {"field": "type", "equals": "Microsoft.Storage/storageAccounts"},
        {"field": "Microsoft.Storage/storageAccounts/allowBlobPublicAccess", "notEquals": false}
      ]
    },
    "then": {"effect": "deny"}
  }
}
```
```bash title="Create" lab
az policy definition create --name deny-public-blob --display-name "Deny public blob access" \
  --rules deny-public-blob.json --mode Indexed
```
@end

@concept Resource locks and deny assignments
@plain
A **lock** blocks delete or modify on a resource regardless of role. A **deny assignment** is a managed deny that even owners cannot edit.
@problem
Accidents happen, including by Owners. Stronger protection than a role is needed for databases and networks.
@does
- **AWS equivalent**: termination protection, deletion protection flags and SCP denies.
- **Main difference**: locks are a generic ARM feature at subscription, group or resource scope. Two kinds: `CanNotDelete` and `ReadOnly`. ReadOnly can break things, for example listing storage keys or scaling.
- Locks are inherited by child resources.
- Only principals with `Microsoft.Authorization/locks/*` (Owner, User Access Administrator) can remove them.
@diagram flow
caption: A lock stops delete
nodes:
  - "Contributor|runs delete|plain"
  - "ARM|checks lock first|cp"
  - "CanNotDelete lock|found|warn"
  - "Request rejected|ScopeLocked|bad"
@h Lock the production group
```bash title="Locks" lab
az lock create --name nodelete --lock-type CanNotDelete --resource-group rg-shop-prod
az lock list --resource-group rg-shop-prod -o table
```
@check
Which lock type can break scaling or key listing operations? || ReadOnly.
@end
