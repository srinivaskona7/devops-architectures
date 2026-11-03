---
title: Tenants, management groups, subscriptions and resource groups
minutes: 50
objectives:
  - Map the Azure resource hierarchy onto AWS Organizations and accounts
  - Choose the right scope for policy, RBAC and billing
  - Use resource groups, regions, zones and tags to organise and govern resources
---
Azure organises everything in a tree. Knowing where each level sits tells you where to attach access, rules and cost, and it is the first thing to map when you come from AWS.

@concept The Azure hierarchy at a glance
@plain
Azure has four nesting levels: a **tenant** at the root, **management groups** below it, **subscriptions** inside those, and **resource groups** holding the actual resources.
@problem
Without a hierarchy you cannot apply one rule or one permission to hundreds of environments at once.
@does
- **AWS equivalent**: Organization root, OUs, accounts. Azure has an extra layer, the resource group, which has no AWS twin.
- **Main difference**: the Azure subscription is the billing and quota boundary but not as hard an isolation wall as an AWS account. Identity lives in the tenant, not in the subscription.
- Permissions and policy set on a level are inherited by everything beneath it.
@diagram layers
caption: Scopes from top to bottom
layers:
  - {label: "Identity", nodes: ["Entra tenant|directory of users and apps|cp"]}
  - {label: "Governance", nodes: ["Management groups|up to six levels below root|info"]}
  - {label: "Billing and quota", nodes: ["Subscriptions|prod, nonprod, shared|env"]}
  - {label: "Grouping", nodes: ["Resource groups|lifecycle container|app"]}
  - {label: "Resources", nodes: ["VMs, AKS, storage|the actual services|plain"]}
@h List your own tree
```bash title="Where am I" lab
az account show --query '{sub:name,id:id,tenant:tenantId}' -o json
az account list --query '[].{name:name,state:state}' -o table
az account management-group list --query '[].{name:name,display:displayName}' -o table
```
@check
Which Azure level is the closest to an AWS account? || The subscription.
@end

@concept Tenants and Microsoft Entra ID
@plain
A **tenant** is a dedicated instance of Microsoft Entra ID (formerly Azure Active Directory). It holds users, groups and applications and is trusted by your subscriptions.
@problem
Someone has to answer "who are you" for every subscription. Doing it per subscription would mean duplicated users everywhere.
@does
- **AWS equivalent**: IAM Identity Center plus the Organization, roughly. Plain AWS IAM users live per account.
- **Main difference**: one tenant holds all identities, and many subscriptions trust it. A subscription belongs to exactly one tenant at a time, but can be moved.
- Every tenant has an ID (a GUID) and a default `*.onmicrosoft.com` domain.
- Most companies run one production tenant. Separate tenants are used for strict isolation or acquisitions.
@diagram flow
caption: One tenant, many subscriptions
nodes:
  - "Entra tenant|users, groups, apps|cp"
  - "Subscription prod|trusts the tenant|env"
  - "Subscription dev|trusts the tenant|env"
  - "Subscription shared|trusts the tenant|env"
@h Find the tenant
```bash title="Tenant details" lab
az account show --query tenantId -o tsv
az rest --method get --url https://graph.microsoft.com/v1.0/organization --query 'value[0].{name:displayName,id:id}' -o json
```
:::note
Tenant ID appears in every token's `tid` claim and in login URLs. It is not a secret.
:::
@end

@concept Management groups
@plain
A **management group** is a folder for subscriptions. You attach policy and role assignments to it and every subscription below inherits them.
@problem
Applying "only EU regions" to forty subscriptions one by one is slow and error prone.
@does
- **AWS equivalent**: Organizational Units with SCPs.
- **Main difference**: Azure Policy and RBAC are inherited down the tree, but there is no deny-everything SCP that overrides even owners. Deny effects in Policy and `denyAssignments` come close.
- Up to six levels deep below the tenant root group (check the current limits).
- Typical design from the Cloud Adoption Framework: Platform (Identity, Connectivity, Management) and Landing zones (Corp, Online), plus Sandbox and Decommissioned.
@diagram flow
caption: A common management group layout
nodes:
  - "Tenant root group|top|cp"
  - "Contoso|company root|info"
  - "Platform|identity, connectivity|env"
  - "Landing zones|workload subscriptions|app"
@h Create and move
```bash title="Management group commands" lab
az account management-group create --name mg-landingzones --display-name "Landing Zones" --parent mg-contoso
az account management-group subscription add --name mg-landingzones --subscription 00000000-0000-0000-0000-000000000000
```
@check
What gets inherited by subscriptions placed in a management group? || Azure Policy assignments and RBAC role assignments made on that group.
@end

@concept Subscriptions
@plain
A **subscription** is the container that gets billed, has quotas and holds resource groups. Most workloads get one subscription per environment or per team.
@problem
You need a boundary for cost reporting, service limits and blast radius.
@does
- **AWS equivalent**: AWS account.
- **Main difference**: quotas (vCPU per region and family, public IPs) are per subscription per region, and you ask for more with a support request. There is no separate root user; access is through Entra and RBAC only.
- Subscriptions can be created through an enrolment (EA, MCA) with the `Microsoft.Subscription` APIs, which allows subscription vending automation.
- Resource providers such as `Microsoft.ContainerService` must be registered in a subscription before first use.
@diagram cmp
caption: Subscription strategy
cards:
  - {h: "One per environment", kind: app, items: ["prod, staging, dev", "Clean cost reports", "Easy RBAC split"]}
  - {h: "One per team and environment", kind: info, items: ["Strong isolation", "More hubs to connect", "Needs vending automation"]}
  - {h: "One big subscription", kind: bad, items: ["Shared quotas", "Noisy neighbours", "Hard to untangle later"]}
@h Register providers and check quota
```bash title="Provider and usage checks" lab
az provider register --namespace Microsoft.ContainerService --wait
az provider show --namespace Microsoft.ContainerService --query registrationState -o tsv
az vm list-usage --location westeurope --query "[?contains(name.value,'standardDSv5Family')]" -o table
```
@end

@concept Resource groups
@plain
A **resource group** is a logical box for resources that share a lifecycle. Delete the box and everything inside goes with it.
@problem
Resources created for one application need to be deployed, permissioned, tagged and cleaned up together.
@does
- **AWS equivalent**: CloudFormation stack or a tag-based resource group, but mandatory. Every resource lives in exactly one group.
- **Main difference**: the group has a region, but that only stores metadata. Resources inside can be in other regions. RBAC and policy can be assigned at group scope.
- Moving resources between groups is possible for many types but not all; check the move support table.
- Pattern: one group per application per environment, plus separate groups for networking and shared items that live longer.
@diagram flow
caption: Group by lifecycle
nodes:
  - "rg-shop-prod|AKS, Postgres, Redis|app"
  - "rg-net-hub|VNet, firewall, DNS|env"
  - "rg-shared|ACR, Key Vault|info"
  - "Delete rg-shop-prod|removes only shop|warn"
@h Create and clean up
```bash title="Resource group lifecycle" lab
az group create --name rg-shop-dev --location westeurope --tags app=shop env=dev owner=platform
az resource list --resource-group rg-shop-dev -o table
az group delete --name rg-shop-dev --yes --no-wait
```
:::danger
`az group delete` removes every resource inside, including databases. Use resource locks on production groups.
:::
@check
Does the region of a resource group limit where its resources can be? || No. It only stores the group metadata.
@end

@concept Azure Resource Manager and resource IDs
@plain
**Azure Resource Manager (ARM)** is the single API front door. Portal, CLI, Bicep, Terraform all call it, and every resource has a path-like ID.
@problem
You need one consistent way to authenticate, authorise, log and deploy every service.
@does
- **AWS equivalent**: the AWS control plane APIs plus ARNs and CloudTrail. Azure has one shared layer, which is why RBAC, policy, tags and locks work the same on every resource type.
- A resource ID looks like `/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Storage/storageAccounts/<name>`.
- Templates (ARM JSON, Bicep) are declarative and idempotent; deployments run at tenant, management group, subscription or resource group scope.
- Every write is recorded in the Activity Log.
@diagram flow
caption: Every tool goes through ARM
nodes:
  - "Portal, CLI, Terraform|clients|ext"
  - "Entra token|identity proof|info"
  - "ARM|authorise, policy, route|cp"
  - "Resource provider|Microsoft.Compute and others|app"
@h Call ARM directly
```bash title="az rest" lab
az rest --method get --url "https://management.azure.com/subscriptions/$(az account show --query id -o tsv)/resourcegroups?api-version=2021-04-01" --query 'value[].name' -o tsv
```
@end

@concept Regions, region pairs and availability zones
@plain
A **region** is a set of datacentres in one area. Many regions have three **availability zones**, physically separate locations with independent power and network.
@problem
You must survive the loss of a datacentre or a whole area without losing the service.
@does
- **AWS equivalent**: Region and Availability Zone. Same idea.
- **Main difference**: zone names are logical per subscription, so zone 1 in your subscription may map to a different physical zone than in another subscription. Not every region has zones; check the list of regions with zones. Some services are zone-redundant by a flag, others you place per zone.
- **Region pairs** exist for geo-redundant storage and some platform failover. Pairs do not mean automatic failover for your apps.
- Prices and available SKUs differ per region.
@diagram layers
caption: Resilience levels
layers:
  - {label: "Region pair", nodes: ["West Europe|primary|env", "North Europe|paired|env"]}
  - {label: "Inside a region", nodes: ["Zone 1|separate datacentres|app", "Zone 2|separate datacentres|app", "Zone 3|separate datacentres|app"]}
@h Zones and SKUs
```bash title="Where can I run" lab
az account list-locations --query "[?metadata.regionType=='Physical'].{name:name,pair:metadata.pairedRegion[0].name}" -o table
az vm list-skus --location westeurope --size Standard_D4s_v5 --query '[0].locationInfo[0].zones' -o tsv
```
@check
Why is zone 1 not a fixed physical place across subscriptions? || Zone numbers are logical and mapped per subscription.
@end

@concept Tags
@plain
**Tags** are name and value pairs on resources, resource groups and subscriptions used for cost reports, ownership and automation.
@problem
A bill that says "compute 40 000" without owner information cannot be acted on.
@does
- **AWS equivalent**: resource tags and cost allocation tags.
- **Main difference**: tags are not inherited by default. Use Azure Policy (`modify` effect, or the built-in "Inherit a tag from the resource group") to copy them down. Also tags are not always shown in cost data for every resource type; check current docs.
- Up to 50 tags per resource; names are case-insensitive, values case-sensitive.
- Typical set: `app`, `env`, `owner`, `costcenter`.
@diagram flow
caption: Tags flow into cost reports
nodes:
  - "Policy requires tag|deny when missing|warn"
  - "Resource tagged|app=shop env=prod|ok"
  - "Cost Management|group by tag|info"
  - "Showback report|per team|app"
@h Tag and query
```bash title="Tagging" lab
az group update --name rg-shop-prod --set tags.costcenter=1234 tags.owner=shop-team
az resource list --tag app=shop --query '[].{name:name,type:type}' -o table
az tag update --resource-id /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-shop-prod --operation merge --tags env=prod
```
@end
