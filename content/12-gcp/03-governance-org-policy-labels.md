---
title: Governance, organization policies, labels and audit
minutes: 45
objectives:
  - Apply organization policy constraints to enforce guardrails across folders
  - Use labels and tags for cost allocation and conditional policy
  - Enable and query audit logs and Cloud Asset Inventory
---
Governance in Google Cloud is built on the hierarchy. Policy set high up applies everywhere below, which gives you a landing zone with few moving parts.

@concept Organization Policy Service
@plain
An **organization policy** applies a **constraint** to a node in the hierarchy. It limits what configurations are allowed, regardless of who has IAM permissions.
@problem
IAM controls who can act, but not which choices are acceptable, for example creating a VM with a public IP.
@does
- Boolean constraints (on or off) and list constraints (allowed or denied values) are inherited and can be overridden unless you block that.
- Examples: `compute.vmExternalIpAccess`, `iam.disableServiceAccountKeyCreation`, `gcp.resourceLocations`, `storage.uniformBucketLevelAccess`.
- Dry-run mode logs violations without enforcing, useful when rolling out.
- **AWS equivalent**: Service Control Policies. Main difference: constraints are a catalogue of service-specific settings, not free-form allow or deny of API actions.
@diagram flow
caption: Constraint inheritance
nodes:
  - "Organization|baseline constraints|cp"
  - "Folder|may override|env"
  - "Project|inherits|app"
  - "Resource creation|checked against policy|warn"
@h Set constraints
```bash title="Enforce guardrails" lab
gcloud resource-manager org-policies enable-enforce iam.disableServiceAccountKeyCreation --organization=123456789012
gcloud resource-manager org-policies enable-enforce compute.requireOsLogin --organization=123456789012
gcloud resource-manager org-policies list --organization=123456789012
```
:::note
Newer `gcloud org-policies` commands with YAML files are also available. Check the current docs for your version.
:::
@check
IAM allows a user to create a VM, but an org policy forbids external IPs. Result? || The org policy wins and the VM with an external IP is rejected.
@end

@concept Common guardrail set
@plain
A small set of constraints gives most of the safety for a new organization.
@problem
Teams starting from nothing do not know which settings matter most.
@does
- `iam.disableServiceAccountKeyCreation` and `iam.disableServiceAccountKeyUpload`: no long-lived keys.
- `compute.vmExternalIpAccess`: deny public IPs; use IAP and NAT.
- `gcp.resourceLocations`: restrict regions for data residency.
- `storage.publicAccessPrevention` and `storage.uniformBucketLevelAccess`: no public buckets, simple ACL model.
- `compute.requireShieldedVm` and `compute.requireOsLogin`: hardened VMs, IAM-based SSH.
- `iam.allowedPolicyMemberDomains`: only your domain in IAM bindings.
- **AWS equivalent**: a standard SCP baseline plus Control Tower guardrails. Main difference: there is no separate service to turn on; constraints are available on day one.
@diagram layers
caption: Baseline guardrails
layers:
  - {label: "Identity", nodes: ["No SA keys|iam.disableServiceAccountKeyCreation|ok", "Domain restricted sharing|iam.allowedPolicyMemberDomains|ok"]}
  - {label: "Network", nodes: ["No external IPs|compute.vmExternalIpAccess|ok"]}
  - {label: "Data", nodes: ["No public buckets|storage.publicAccessPrevention|ok", "Regions|gcp.resourceLocations|ok"]}
@h As Terraform
```hcl title="org-policy.tf"
resource "google_organization_policy" "no_sa_keys" {
  org_id     = "123456789012"
  constraint = "iam.disableServiceAccountKeyCreation"
  boolean_policy {
    enforced = true
  }
}

resource "google_folder_organization_policy" "regions" {
  folder     = "folders/111122223333"
  constraint = "gcp.resourceLocations"
  list_policy {
    allow {
      values = ["in:eu-locations"]
    }
  }
}
```
@end

@concept Custom organization policies
@plain
Custom constraints let you write your own rule using CEL for supported resource types.
@problem
Built-in constraints do not cover every company standard, such as requiring a naming prefix or a label.
@does
- You define a constraint (resource type, methods CREATE and UPDATE, CEL condition, action ALLOW or DENY) and then an org policy that enforces it.
- Supported resources and fields vary by service; check the current list.
- Test first with dry-run.
- **AWS equivalent**: custom AWS Config rules or SCP conditions. Main difference: it blocks at request time like SCPs, but works on resource fields.
@diagram flow
caption: Custom constraint
nodes:
  - "Constraint YAML|CEL condition|info"
  - "Policy|enforce on folder|cp"
  - "Create request|e.g. bucket|app"
  - "Allow or deny|decision|warn"
@h Constraint definition
```yaml title="constraint.yaml"
name: organizations/123456789012/customConstraints/custom.bucketNamePrefix
resourceTypes:
  - storage.googleapis.com/Bucket
methodTypes:
  - CREATE
condition: resource.name.startsWith("shop-")
actionType: ALLOW
displayName: Buckets must start with shop-
description: Bucket names must carry the team prefix.
```
```bash title="Register it" lab
gcloud org-policies set-custom-constraint constraint.yaml
```
@end

@concept Labels
@plain
**Labels** are key-value pairs on resources. They flow into billing data and can be used in filters.
@problem
Without labels you cannot tell which team or app caused a cost.
@does
- Up to 64 labels per resource; keys and values are lowercase letters, digits, underscores and dashes with length limits.
- Labels on a project show up in the billing export. Many resources also carry their own labels.
- Labels are not used for IAM or network security.
- **AWS equivalent**: resource tags used for cost allocation. Main difference: Google separates cost-oriented labels from security-oriented tags.
@diagram flow
caption: Labels to cost report
nodes:
  - "Resource|env=prod, app=shop|app"
  - "Usage record|carries labels|info"
  - "Billing export|BigQuery|cp"
  - "Report|cost per team|ok"
@h Apply and filter
```bash title="Labels" lab
gcloud projects update shop-prod-123456 --update-labels=env=prod,team=payments,app=shop
gcloud compute instances list --filter="labels.env=prod" --format="table(name,zone,labels)"
gcloud compute instances add-labels shop-vm-1 --zone=europe-west1-b --labels=owner=sre
```
@check
Can you use labels to grant access? || No. Use IAM, and use tags for conditional policy.
@end

@concept Tags
@plain
**Tags** are resource-manager objects (key and value) that you bind to organization, folder, project or some resources. Policies can use them.
@problem
You need to mark all production projects and apply a firewall policy or IAM condition to only those.
@does
- Tag keys and values are created in the organization, with their own IAM.
- Used in IAM conditions, firewall policies (secure tags) and org policies.
- Inherited by children unless overridden.
- **AWS equivalent**: tag-based ABAC in IAM conditions. Main difference: tags are managed resources with access control, so people cannot invent tags to gain access.
@diagram flow
caption: Tag drives policy
nodes:
  - "Tag key env|created in org|cp"
  - "Value prod|bound to folder|env"
  - "Policy|conditional on tag|info"
  - "Projects below|inherit|app"
@h Create and bind
```bash title="Tags" lab
gcloud resource-manager tags keys create env --parent=organizations/123456789012
gcloud resource-manager tags values create prod --parent=123456789012/env
gcloud resource-manager tags bindings create \
  --tag-value=123456789012/env/prod \
  --parent=//cloudresourcemanager.googleapis.com/projects/shop-prod-123456
```
@end

@concept Cloud Audit Logs
@plain
Cloud Audit Logs record who did what. **Admin Activity** logs are always on and free, **Data Access** logs are optional and can be large, and **System Event** logs record Google actions.
@problem
You need a trail for investigations and compliance.
@does
- Admin Activity: configuration changes. Data Access: reads of data and metadata. Both are in Cloud Logging.
- Enable Data Access logs per service in the IAM audit config; BigQuery data access is on by default.
- Route to a locked bucket or BigQuery with an aggregated sink at the organization.
- **AWS equivalent**: CloudTrail. Main difference: management events are collected by default for every project with no trail setup.
@diagram flow
caption: Audit trail
nodes:
  - "API call|any principal|ext"
  - "Audit log entry|who, what, when|info"
  - "Log sink|org level|cp"
  - "Archive|bucket or BigQuery|db"
@h Read entries
```bash title="Who deleted it" lab
gcloud logging read 'logName:"cloudaudit.googleapis.com%2Factivity" AND protoPayload.methodName="v1.compute.instances.delete"' \
  --project=shop-prod-123456 --limit=5 --format="table(timestamp,protoPayload.authenticationInfo.principalEmail,protoPayload.resourceName)"
```
@end

@concept Cloud Asset Inventory and Security Command Center
@plain
**Cloud Asset Inventory** keeps a searchable record of resources and IAM policies. **Security Command Center** reports misconfigurations and threats.
@problem
Across hundreds of projects you cannot answer which buckets are public or who has owner.
@does
- `gcloud asset search-all-resources` finds resources by name, label or type across a scope.
- `gcloud asset search-all-iam-policies` answers who has a role. Export to BigQuery for analysis.
- Security Command Center (Standard and Premium tiers) lists findings; check the current tier features.
- **AWS equivalent**: AWS Config plus Security Hub. Main difference: Asset Inventory needs no recorder to switch on.
@diagram flow
caption: Visibility
nodes:
  - "All projects|resources and IAM|app"
  - "Asset Inventory|search and export|cp"
  - "Security Command Center|findings|warn"
  - "Dashboard or ticket|follow up|ok"
@h Search
```bash title="Asset queries" lab
gcloud asset search-all-resources --scope=organizations/123456789012 \
  --asset-types=storage.googleapis.com/Bucket --query="labels.env=prod" --format="table(name,location)"
gcloud asset search-all-iam-policies --scope=organizations/123456789012 --query="policy:roles/owner"
```
:::tip
Schedule an export of assets to BigQuery daily and write saved queries for public IPs, owner bindings and unlabelled projects.
:::
@end
