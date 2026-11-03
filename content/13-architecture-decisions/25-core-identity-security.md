---
title: Core services 26 to 30, identity and security
minutes: 60
objectives:
  - Compare identity, workload identity, keys, secrets and threat detection
  - State when to choose each service
  - List the limits to verify in the current docs
---
Identity decides who may act, keys and secrets protect data, and detection watches for abuse. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
People and workloads get identity, then keys and secrets, then detection. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Security chain
layers:
  - {label: "Services on this page", nodes: ["Identity and access|IAM|app", "Workload identity|IRSA or EKS Pod Identity|info", "Key management|KMS|env", "Secrets|Secrets Manager|ok", "Threat detection|GuardDuty|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 26 | Identity and access | IAM | Entra ID and Azure RBAC | Cloud IAM |
| 27 | Workload identity | IRSA or EKS Pod Identity | Workload Identity | Workload Identity Federation |
| 28 | Key management | KMS | Key Vault keys | Cloud KMS |
| 29 | Secrets | Secrets Manager | Key Vault secrets | Secret Manager |
| 30 | Threat detection | GuardDuty | Defender for Cloud | Security Command Center |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 26. Identity and access
@plain
The system that decides who or what you are, and what you may do.
@problem
Shared passwords and broad permissions lead to breaches and unclear audit trails.
@does
- **Names**: AWS IAM; Azure Entra ID and Azure RBAC; GCP Cloud IAM.
- **What it is**: Stores users, groups and roles, evaluates policies, and grants least-privilege access with MFA and temporary credentials.
- **Choose it when**: Every environment; Single sign-on for people; Role-based access for teams and automation.
- **Check in the current docs**: Models differ, with AWS policies attached to identities, Azure roles at scopes, and GCP roles bound to resources; Prefer groups and roles to individual grants; Review unused permissions regularly.
@diagram cmp
caption: Identity and access on the three clouds
cards:
  - {h: "IAM", kind: warn, items: ["Users, roles, policies, SCP boundaries"]}
  - {h: "Entra ID and Azure RBAC", kind: info, items: ["Entra users, groups, role assignments at scopes"]}
  - {h: "Cloud IAM", kind: ok, items: ["Principals, roles, bindings, conditions"]}
@h Example
Engineers sign in through single sign-on and assume a read-only role by default, with an approved elevated role for changes.
@h CLI on each cloud
```bash title="AWS CLI, Identity and access" nocheck
aws iam list-roles --query 'Roles[].RoleName'
```
```bash title="Azure CLI, Identity and access" nocheck
az role assignment create --assignee 00000000-0000-0000-0000-000000000000 --role Reader --scope /subscriptions/00000000-0000-0000-0000-000000000000
```
```bash title="gcloud, Identity and access" nocheck
gcloud projects add-iam-policy-binding demo-project --member=group:devs@example.com --role=roles/viewer
```
@check
What is least privilege? || Grant only the permissions needed for the task.
@end

@concept 27. Workload identity
@plain
A way for applications to get short-lived cloud credentials from their runtime identity, without stored keys.
@problem
Static access keys in config files leak and rarely rotate.
@does
- **Names**: AWS IRSA or EKS Pod Identity; Azure Workload Identity; GCP Workload Identity Federation.
- **What it is**: Trusts a token from Kubernetes, CI or another provider and exchanges it for temporary cloud credentials.
- **Choose it when**: Pods calling cloud APIs; CI pipelines deploying to the cloud; Cross-cloud access without keys.
- **Check in the current docs**: Trust conditions must name the exact subject and audience; Token lifetimes and setup steps differ, so check the current docs; Misconfigured trust can allow other workloads to assume the role.
@diagram cmp
caption: Workload identity on the three clouds
cards:
  - {h: "IRSA or EKS Pod Identity", kind: warn, items: ["OIDC provider, IRSA, Pod Identity associations"]}
  - {h: "Workload Identity", kind: info, items: ["Federated credentials, workload identity for AKS"]}
  - {h: "Workload Identity Federation", kind: ok, items: ["Pools and providers, GKE workload identity"]}
@h Example
A GitHub Actions job assumes a role through OIDC for 15 minutes and no secret is stored in the repository.
@h CLI on each cloud
```bash title="AWS CLI, Workload identity" nocheck
aws eks create-pod-identity-association --cluster-name demo --namespace shop --service-account orders --role-arn arn:aws:iam::111122223333:role/orders-role
```
```bash title="Azure CLI, Workload identity" nocheck
az identity federated-credential create --name gh --identity-name app-id --resource-group rg-demo --issuer https://token.actions.githubusercontent.com --subject repo:acme/shop:ref:refs/heads/main
```
```bash title="gcloud, Workload identity" nocheck
gcloud iam workload-identity-pools create gh-pool --location=global --display-name=github
```
@check
Why prefer workload identity to access keys? || Credentials are short-lived and never stored.
@end

@concept 28. Key management
@plain
A service that creates and guards encryption keys and performs cryptographic operations without exposing the key.
@problem
Keys stored beside data defeat encryption, and manual rotation is error-prone.
@does
- **Names**: AWS KMS; Azure Key Vault keys; GCP Cloud KMS.
- **What it is**: Holds keys in managed or hardware-backed stores, controls use by policy, logs every use, and supports rotation.
- **Choose it when**: Customer-managed encryption for storage and databases; Signing and envelope encryption; Compliance requiring key control.
- **Check in the current docs**: Deleting a key makes data unrecoverable, so use deletion waiting periods; Request quotas and per-key costs apply, so check the current docs; Key location must match the data region.
@diagram cmp
caption: Key management on the three clouds
cards:
  - {h: "KMS", kind: warn, items: ["KMS keys, aliases, grants, rotation"]}
  - {h: "Key Vault keys", kind: info, items: ["Key Vault and Managed HSM keys"]}
  - {h: "Cloud KMS", kind: ok, items: ["Key rings and keys, rotation schedules"]}
@h Example
A bucket is encrypted with a customer-managed key rotated each year, and a deletion waiting period protects against mistakes.
@h CLI on each cloud
```bash title="AWS CLI, Key management" nocheck
aws kms create-key --description demo
aws kms create-alias --alias-name alias/demo --target-key-id 1234abcd-12ab-34cd-56ef-1234567890ab
```
```bash title="Azure CLI, Key management" nocheck
az keyvault key create --vault-name demo-kv-123 --name demo-key --kty RSA
```
```bash title="gcloud, Key management" nocheck
gcloud kms keyrings create demo-ring --location=europe-west1
gcloud kms keys create demo-key --keyring=demo-ring --location=europe-west1 --purpose=encryption
```
@check
Why use deletion waiting periods? || A deleted key makes data unrecoverable, so the delay allows recovery.
@end

@concept 29. Secrets
@plain
A safe store for passwords, tokens and certificates that applications fetch at run time.
@problem
Secrets in code, images or environment files leak and are hard to rotate.
@does
- **Names**: AWS Secrets Manager; Azure Key Vault secrets; GCP Secret Manager.
- **What it is**: Stores encrypted versions, controls access by identity, audits reads and can rotate automatically.
- **Choose it when**: Database passwords and API tokens; Rotation workflows; Injecting secrets into pods.
- **Check in the current docs**: Per-secret and per-call costs, so cache values and check the current docs; Rotation needs support in the target system; Secret values must not be printed in logs.
@diagram cmp
caption: Secrets on the three clouds
cards:
  - {h: "Secrets Manager", kind: warn, items: ["Secrets with rotation Lambda, resource policies"]}
  - {h: "Key Vault secrets", kind: info, items: ["Key Vault with RBAC, references"]}
  - {h: "Secret Manager", kind: ok, items: ["Secrets with versions and IAM"]}
@h Example
An app reads its database password at start through its workload identity, and rotation changes it every 30 days.
@h CLI on each cloud
```bash title="AWS CLI, Secrets" nocheck
aws secretsmanager create-secret --name prod/db --secret-string 'change-me'
```
```bash title="Azure CLI, Secrets" nocheck
az keyvault secret set --vault-name demo-kv-123 --name db-password --value change-me
```
```bash title="gcloud, Secrets" nocheck
printf 'change-me' | gcloud secrets create db-password --data-file=-
```
@check
Where should an app get its database password? || From the secret store using its workload identity.
@end

@concept 30. Threat detection
@plain
A service that watches logs and activity for signs of attack and misconfiguration and raises findings.
@problem
Humans cannot read every log line to spot a stolen credential or crypto-mining.
@does
- **Names**: AWS GuardDuty; Azure Defender for Cloud; GCP Security Command Center.
- **What it is**: Analyses audit logs, network and DNS data with threat intelligence, and ranks findings, often with posture checks.
- **Choose it when**: Baseline detection in every account; Compliance posture reports; Central security dashboards.
- **Check in the current docs**: Findings need an owner and a response process; Tiers and plans have separate pricing, so check the current docs; Enable across all accounts and regions.
@diagram cmp
caption: Threat detection on the three clouds
cards:
  - {h: "GuardDuty", kind: warn, items: ["GuardDuty detectors, Security Hub"]}
  - {h: "Defender for Cloud", kind: info, items: ["Defender plans, secure score"]}
  - {h: "Security Command Center", kind: ok, items: ["Security Command Center tiers, findings"]}
@h Example
All accounts send findings to one security account where high severity items page the on-call.
@h CLI on each cloud
```bash title="AWS CLI, Threat detection" nocheck
aws guardduty create-detector --enable
```
```bash title="Azure CLI, Threat detection" nocheck
az security pricing create --name VirtualMachines --tier Standard
```
```bash title="gcloud, Threat detection" nocheck
gcloud scc findings list organizations/123456789 --source=-
```
@check
What makes detection useful? || An owner and a response process for each finding.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Long-lived access keys instead of workload identity.
- Deleting keys without a waiting period.
- Findings with no owner.
- Always confirm limits, prices and regional availability in the current documentation before committing.
@diagram flow
caption: A safe habit before adopting any service
nodes:
  - "Define need|workload, size, latency|plain"
  - "Map services|three cloud names|info"
  - "Check docs|limits, price, regions|warn"
  - "Prototype|measure on real data|app"
  - "Decide|record in an ADR|ok"
@h Habit as a checklist
```yaml title="service-evaluation.yaml" nocheck
service: Identity and access
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

