---
title: Runbooks, disaster recovery, handover and the Shop on Azure and GCP
minutes: 65
objectives:
  - Write runbooks and rehearse incidents so on-call can act without the author
  - Test database recovery against the stated RPO and RTO
  - Hand the system over with a documentation pack and map the design to AKS and GKE
---
The last file turns the project into something a team can own. Operations documents are only trustworthy if they were exercised, so each section ends with a drill. Cloud-specific service names and limits change; check the current docs of each provider.

@concept Runbook format and the checkout errors runbook
@plain
A runbook is a page that tells a tired person at 3 am what to look at, in what order, and what to do. It is linked from the alert.
@problem
Without runbooks only the author can respond, and the author is on holiday.
@does
- Fixed headings: symptom, impact, first checks (3 minutes), likely causes, fixes, escalation, how to verify recovery.
- Each check is a command or a dashboard link, never "look into it".
- Checkout errors: 1) is it all errors or only payments (dashboard), 2) recent deploy (Argo CD history; roll back if the burn started right after), 3) dependency health (`/readyz` of catalog and payments, RDS CPU and connections, Redis), 4) gateway status, 5) node or zone problems.
- Keep runbooks in Git, reviewed like code; update them in the pull request that changes behaviour.
@diagram flow
caption: First ten minutes of a checkout page
nodes:
  - "Alert fires|burn rate fast|bad"
  - "Recent deploy?|Argo CD history|warn"
  - "Dependency check|readyz, RDS, Redis|info"
  - "Mitigate|rollback or scale|ok"
@h docs/runbooks/checkout-errors.md
```markdown title="docs/runbooks/checkout-errors.md" nocheck
# Runbook Checkout errors
Alert: CheckoutBudgetBurnFast, CheckoutBudgetBurnSlow
Impact: customers cannot place orders. Budget 43.2 min per 30 days.

## First checks (3 minutes)
1. Dashboard Shop overview: all services or one?
2. `argocd app history shop-prod` - deploy in the last 30 minutes? If yes, roll back (see Rollback).
3. `kubectl -n shop get pods` - restarts, Pending, NotReady?
4. `kubectl -n shop logs deploy/orders --since=10m | grep '"status": 5'`

## Likely causes
- Bad release: roll back via Git revert.
- Database: RDS CPU or connections high, see runbook rds-saturation.
- Payments gateway slow: orders stay pending, check gateway status page; raise nothing, wait for webhooks.
- Node or AZ loss: pods rescheduling, check PDB and HPA.

## Verify recovery
Error ratio below 0.1 percent for 15 minutes; smoke script passes.
Escalate to the SRE lead if not mitigated in 20 minutes.
```
@end

@concept Database and stuck-payment runbooks
@plain
Two more pages for the failures that are specific to the Shop: a saturated database and payments that stay PENDING.
@problem
Database trouble and payment inconsistencies are rare, high-impact and unfamiliar to most responders.
@does
- RDS saturation: check `DatabaseConnections` against the limit, top queries in Performance Insights, long transactions; mitigate by reducing HPA max (fewer connections), killing a runaway query, or scaling the instance class (a short failover in multi-AZ). Total connections = pods x pool size (up to 10), for example 9 pods x 10 = 90 per service.
- Stuck PENDING: a CronJob or the runbook query lists payments older than 15 minutes and asks the gateway for the status by reference, then calls the same settlement code path as the webhook.
- Stock leak: reservations with no order after 15 minutes are released by a reconciliation query (see the orders chapter).
- Every manual data change is done by a second person watching, inside a transaction, with the SQL saved in the incident ticket.
@diagram flow
caption: Stuck payment reconciliation
nodes:
  - "PENDING over 15 min|query|warn"
  - "Ask gateway by reference|status API|ext"
  - "Settle via webhook path|idempotent|app"
  - "Order paid or failed|stock released|ok"
@h Reconciliation query
```sql title="docs/runbooks/stuck-payments.sql" nocheck
-- run read-only first, then settle each row through the service, not by UPDATE
SELECT p.id, p.order_id, p.amount_paise, p.gateway_ref, p.status
FROM payments p
WHERE p.status = 'PENDING'
  AND p.id IN (SELECT id FROM payments ORDER BY id DESC LIMIT 5000)
ORDER BY p.id;
```
:::note
The sample table has no timestamp column. Add `created_at` in a migration (expand step) before the 15 minute filter can be written. This is a good first exercise.
:::
@end

@concept Incident drills (game days)
@plain
A drill breaks something on purpose in staging and the on-call person fixes it using only the runbooks.
@problem
The first time you use a runbook should not be during a real incident. Untested runbooks have wrong commands.
@does
- Schedule one drill per month, 60 minutes, in staging, with a facilitator who knows the answer and a person who does not.
- Scenarios: bad release (rollback), gateway down (mock returns 500, expect PENDING and an alert), database failover (RDS reboot with failover), node loss (terminate an instance, watch PDB and HPA), expired certificate or secret rotation.
- Record time to detect, time to mitigate, and every unclear step; fix the runbook the same day.
- After a real incident write a blameless post-mortem: timeline, impact in budget minutes, causes, actions with owners.
@diagram flow
caption: Drill loop
nodes:
  - "Inject failure|staging|bad"
  - "Alert and respond|runbook only|app"
  - "Measure times|detect, mitigate|info"
  - "Fix runbook|same day|ok"
@h Gateway failure drill
```bash title="Drill 1 mock gateway returns errors" lab
# staging only
kubectl -n shop set env deploy/upi-mock SLOW_DELAY_SECONDS=30
kubectl -n shop scale deploy/upi-mock --replicas=0
bash scripts/smoke.sh || echo "expected failure, now follow the checkout runbook"
kubectl -n shop scale deploy/upi-mock --replicas=1
```
@check
Which numbers do you record for each drill? || Time to detect, time to mitigate, and each step in the runbook that was unclear or wrong.
@end

@concept Disaster recovery targets and test
@plain
Disaster recovery (DR) is getting the Shop back after losing a database, a zone or a whole region. RPO is how much data you can lose; RTO is how long you can be down.
@problem
Backups that were never restored are hopes, not backups.
@does
- Targets: RPO 5 minutes, RTO 60 minutes (stated in the requirements).
- Layers: multi-AZ RDS covers an instance or zone failure in about 1 to 2 minutes without data loss. Automated backups and point-in-time restore cover bad data or deletion: RPO about 5 minutes. A cross-region copy of snapshots (and a Terraform-ready second region) covers a region loss: RPO is then the snapshot interval, which is larger than 5 minutes; accept it or add a cross-region read replica.
- Quarterly restore test: restore the prod database to a new instance at a point in time, run the smoke checks against it, record the time.
- Time budget for a point-in-time restore: decision 5, restore 15 to 30, repoint secrets 5, restart 5, verify 10 = about 40 to 55 minutes against the 60 minute RTO; there is little slack.
- Everything else is rebuilt from Git: Terraform for infrastructure, Argo CD for workloads. Redis carts are disposable.
@diagram layers
caption: Failure and recovery
layers:
  - {label: "Instance or AZ", nodes: ["Multi-AZ failover|1 to 2 min|ok"]}
  - {label: "Bad data or delete", nodes: ["Point-in-time restore|RPO about 5 min|warn"]}
  - {label: "Region loss", nodes: ["Snapshot copy and Terraform|hours|bad"]}
@h Restore test
```bash title="Point-in-time restore" lab
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier shop-prod \
  --target-db-instance-identifier shop-prod-restore-test \
  --use-latest-restorable-time \
  --db-subnet-group-name shop-prod \
  --no-multi-az
aws rds wait db-instance-available --db-instance-identifier shop-prod-restore-test
aws rds describe-db-instances --db-instance-identifier shop-prod-restore-test --query 'DBInstances[0].Endpoint.Address'
# run checks, then delete the test instance
aws rds delete-db-instance --db-instance-identifier shop-prod-restore-test --skip-final-snapshot
```
```python title="rto_budget.py" lab
steps = {"decide": 5, "restore": 30, "repoint secrets": 5, "restart pods": 5, "verify": 10}
print("worst case minutes:", sum(steps.values()), "of 60")
print("slack:", 60 - sum(steps.values()))
```
@end

@concept The handover pack
@plain
A set of documents and access that lets the receiving team run the Shop without the builders.
@problem
Systems handed over by a meeting and a chat export fail on the first unusual night.
@does
- Architecture: context and container diagrams, the ADRs, data flow of a checkout.
- Operations: runbooks, dashboards and alert list with owners, on-call rota and escalation contacts, the SLO and error budget policy.
- Delivery: how to build, release, roll back; how to upgrade EKS (the runbook from the deploy file); how to rotate secrets and certificates.
- Governance: access list, cost report and budget alerts, risk register, open issues and known gaps.
- Acceptance: the new team performs a release, a rollback, a restore test and one drill without help.
@diagram layers
caption: Handover pack contents
layers:
  - {label: "Understand", nodes: ["Architecture and ADRs|why|info", "Data flows|how|info"]}
  - {label: "Operate", nodes: ["Runbooks|what to do|ok", "Dashboards and alerts|what to watch|ok", "SLO policy|when to stop|ok"]}
  - {label: "Change", nodes: ["Release and rollback|how|app", "EKS upgrade|how|app", "Secret rotation|how|app"]}
  - {label: "Govern", nodes: ["Access and cost|who and how much|warn", "Risks and gaps|open items|warn"]}
@h Handover checklist
```yaml title="docs/handover.yaml"
accepted_when:
  - release performed by receiving team without help
  - rollback performed in staging
  - restore test completed within RTO
  - one incident drill run from runbooks only
documents:
  - docs/adr/
  - docs/runbooks/
  - docs/environments.yaml
  - docs/risks.yaml
  - dashboards/shop-overview.json
access:
  review: quarterly
  break_glass: documented, audited, expires in 4 hours
```
@end

@concept The same Shop on Azure (AKS)
@plain
The design does not change; each AWS piece has an Azure counterpart. Containers, Kustomize overlays, probes, policies and metrics stay identical.
@problem
Customers and acquisitions bring a second cloud. Knowing which parts are portable shows how much really has to change.
@does
- Compute: AKS replaces EKS; node pools replace managed node groups; the upgrade flow is the same idea (control plane, then node pools), with surge upgrades on pools.
- Data: Azure Database for PostgreSQL flexible server with zone-redundant HA; Azure Cache for Redis (check the current product and naming).
- Registry: Azure Container Registry. CI auth: GitHub OIDC federated credential on a Microsoft Entra application, no secrets; AKS pulls from ACR with its managed identity.
- Secrets: Key Vault with the External Secrets operator and Azure Workload Identity (the AKS counterpart of IRSA).
- Ingress: Application Gateway for Containers or the NGINX ingress with a managed certificate; check which your platform standard is.
- Terraform uses the azurerm provider (version `{{v.azurerm_provider}}` at the time of writing) with the same module split: network, aks, database, cache, registry, identity. See the Azure folder (11) for details.
@diagram cmp
caption: AWS to Azure mapping
cards:
  - {h: "AWS", kind: info, items: ["EKS managed node groups", "RDS PostgreSQL multi-AZ", "ECR", "Secrets Manager and IRSA", "ALB controller"]}
  - {h: "Azure", kind: ok, items: ["AKS node pools", "PostgreSQL flexible server HA", "ACR", "Key Vault and Workload Identity", "Application Gateway for Containers"]}
@h Overlay for Azure
```yaml title="deploy/overlays/prod-azure/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../prod
images:
  - name: shop/catalog
    newName: shopprod.azurecr.io/shop/catalog
    newTag: sha-0000000
  - name: shop/cart
    newName: shopprod.azurecr.io/shop/cart
    newTag: sha-0000000
  - name: shop/orders
    newName: shopprod.azurecr.io/shop/orders
    newTag: sha-0000000
  - name: shop/payments
    newName: shopprod.azurecr.io/shop/payments
    newTag: sha-0000000
  - name: shop/web
    newName: shopprod.azurecr.io/shop/web
    newTag: sha-0000000
patches:
  - target: {kind: Ingress, name: shop}
    patch: |-
      - op: replace
        path: /metadata/annotations
        value:
          kubernetes.io/ingress.class: nginx
  - target: {kind: ExternalSecret}
    patch: |-
      - op: replace
        path: /spec/secretStoreRef/name
        value: azure-keyvault
```
@end

@concept The same Shop on GCP (GKE)
@plain
Again the application and Kustomize base are unchanged; the infrastructure modules and identity wiring change.
@problem
Moving clouds should mean rewriting modules and overlays, not the application.
@does
- Compute: GKE (Standard with node pools, or Autopilot where you pay per pod request; the HPA and PDB behave the same, but Autopilot enforces its own resource rules, check the current docs).
- Data: Cloud SQL for PostgreSQL with high availability; Memorystore for Redis.
- Registry: Artifact Registry. CI auth: GitHub OIDC to Workload Identity Federation with a service account limited to Artifact Registry writer.
- Secrets: Secret Manager through the External Secrets operator and GKE Workload Identity.
- Ingress: the GKE Gateway or Ingress controller creates a Google Cloud load balancer; managed certificates for HTTPS.
- Terraform uses the google provider (`{{v.google_provider}}` at the time of writing). See the GCP folder (12). NetworkPolicy is enforced on GKE when network policy or Dataplane V2 is enabled.
- Portable pieces: containers, probes, HPA, PDB, Prometheus rules, Grafana JSON, the k6 test. Cloud-specific: Terraform modules, ingress annotations, identity wiring, the secret store object.
@diagram flow
caption: What changes when moving cloud
nodes:
  - "Application and tests|unchanged|ok"
  - "Kustomize base|unchanged|ok"
  - "Overlay|registry, ingress, secrets|warn"
  - "Terraform modules|rewritten|bad"
@h Terraform sketch for GKE (module outline)
```hcl title="infra/gcp/main.tf"
module "network" {
  source = "./modules/network"
}

module "gke" {
  source = "./modules/gke"
  subnet = module.network.subnet
}

module "sql" {
  source  = "./modules/cloudsql"
  network = module.network.id
}

module "redis" {
  source  = "./modules/memorystore"
  network = module.network.id
}

module "registry" {
  source = "./modules/artifact_registry"
}

module "wif" {
  source = "./modules/github_wif"
  repo   = "acme/shop"
}
```
:::note
This outline lists module boundaries only; it is not applied as-is. The portability lesson is the point: about 80 percent of the repository (services, tests, base manifests, dashboards, runbooks) does not change.
:::
@end
