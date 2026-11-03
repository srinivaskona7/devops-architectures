---
title: Terraform on Google Cloud, cost control and BigQuery for operations
minutes: 65
objectives:
  - Configure the Terraform google provider with impersonation and a Cloud Storage backend
  - Create budgets, use the recommender and export billing data to BigQuery
  - Query logs and billing data in BigQuery with partition-aware SQL
---
Infrastructure as code and cost data close the loop on everything in this folder. Terraform builds it, budgets watch it and BigQuery explains it.

@concept The google provider and authentication
@plain
The **google** and **google-beta** providers manage Google Cloud resources. They authenticate through Application Default Credentials, and can impersonate a service account.
@problem
Terraform runs on laptops and in CI, and must not rely on downloaded keys.
@does
- Set `project`, `region` and `zone` defaults in the provider block. Resources can override them.
- Use `impersonate_service_account` so engineers act through a deployer account with an audit trail, and use Workload Identity Federation in CI.
- `google-beta` exposes features that are not yet GA; mix both with care and pin versions.
- Set `user_project_override = true` and `billing_project` when you use APIs that bill the caller's quota project.
- **AWS equivalent**: the aws provider with `assume_role`. Main difference: enabling APIs is a Terraform resource of its own.
@diagram flow
caption: Terraform identity
nodes:
  - "Engineer or CI|ADC or OIDC|ext"
  - "Impersonation|tf-deployer account|cp"
  - "google provider|API calls|app"
  - "Resources|created in project|ok"
@h Provider setup
```hcl title="providers.tf"
terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project                     = var.project_id
  region                      = "europe-west1"
  impersonate_service_account = "tf-deployer@shop-dev-123456.iam.gserviceaccount.com"
  user_project_override       = true
  billing_project             = var.project_id
}

variable "project_id" {
  type = string
}
```
@check
How do you avoid service account key files with Terraform? || Use impersonation locally and Workload Identity Federation in CI.
@end

@concept State in a Cloud Storage backend
@plain
Terraform state can live in a **Cloud Storage bucket** with built-in locking. No separate lock table is needed.
@problem
Local state is lost and cannot be shared, and parallel runs corrupt it.
@does
- Use a dedicated project and bucket with versioning, uniform access, public access prevention and a lifecycle rule to expire old versions.
- The `gcs` backend locks with a lock file object. Set `prefix` per environment.
- Grant `roles/storage.objectAdmin` on that bucket to the deployer only.
- Encrypt with CMEK via `encryption_key` if required.
- **AWS equivalent**: S3 backend with DynamoDB locking. Main difference: locking is native; no second service to manage.
@diagram flow
caption: Remote state
nodes:
  - "terraform apply|CI job|app"
  - "Lock object|prevents parallel runs|warn"
  - "State bucket|versioned|db"
  - "Next run|reads latest|ok"
@h Bootstrap and use
```bash title="Create the state bucket" lab
gcloud storage buckets create gs://shop-tfstate-123 --project=shop-admin-123456 --location=europe-west1 \
  --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update gs://shop-tfstate-123 --versioning
```
```hcl title="backend.tf"
terraform {
  backend "gcs" {
    bucket = "shop-tfstate-123"
    prefix = "envs/dev"
  }
}
```
@end

@concept A project and network with Terraform
@plain
Create projects, enable APIs and build the network in code, in an order Terraform can resolve.
@problem
Clicking through the console cannot be reviewed or repeated for staging and production.
@does
- `google_project` creates the project with `billing_account`, `folder_id` and labels. Set `deletion_policy` as needed.
- `google_project_service` enables APIs; use `disable_on_destroy = false` to avoid surprises.
- Network resources follow: VPC, subnet with secondary ranges, router, NAT.
- Use `depends_on` or resource references so APIs exist before dependent resources.
- **AWS equivalent**: Control Tower account factory plus VPC modules. Main difference: projects are ordinary Terraform resources.
@diagram flow
caption: Order of creation
numbered: true
nodes:
  - "Project|folder and billing|cp"
  - "APIs|google_project_service|info"
  - "VPC and subnet|ranges for GKE|app"
  - "NAT|private egress|ok"
@h Code
```hcl title="project.tf"
resource "google_project" "shop" {
  name            = "shop-dev"
  project_id      = "shop-dev-123456"
  folder_id       = "111122223333"
  billing_account = "0A1B2C-3D4E5F-6A7B8C"
  labels = {
    env = "dev"
    app = "shop"
  }
}

resource "google_project_service" "apis" {
  for_each = toset([
    "compute.googleapis.com",
    "container.googleapis.com",
    "artifactregistry.googleapis.com",
    "sqladmin.googleapis.com",
    "servicenetworking.googleapis.com",
  ])
  project            = google_project.shop.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_compute_router" "r" {
  name    = "shop-router"
  region  = "europe-west1"
  network = google_compute_network.shop.id
}

resource "google_compute_router_nat" "nat" {
  name                               = "shop-nat"
  router                             = google_compute_router.r.name
  region                             = "europe-west1"
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"
}
```
@check
Why set disable_on_destroy to false? || So destroying one Terraform stack does not disable APIs that other resources still need.
@end

@concept A GKE cluster with Terraform
@plain
`google_container_cluster` and `google_container_node_pool` define a cluster. Autopilot needs a single resource with `enable_autopilot = true`.
@problem
Cluster settings are numerous, and defaults differ from what a production cluster needs.
@does
- Remove the default node pool in Standard (`remove_default_node_pool = true`, `initial_node_count = 1`) and manage pools separately.
- Set `ip_allocation_policy` with the secondary range names, `release_channel`, `workload_identity_config`, `private_cluster_config`, `master_authorized_networks_config`, and `deletion_protection`.
- Use a dedicated node service account with minimal roles.
- **AWS equivalent**: the `terraform-aws-modules/eks` module. Main difference: Google's own `terraform-google-kubernetes-engine` modules exist; check their current versions.
@diagram layers
caption: Cluster resources
layers:
  - {label: "Cluster", nodes: ["google_container_cluster|control plane and options|cp"]}
  - {label: "Node pools", nodes: ["google_container_node_pool|per workload type|app"]}
  - {label: "Identity", nodes: ["Node service account|minimal roles|info", "Workload pool|PROJECT.svc.id.goog|info"]}
@h Autopilot cluster
```hcl title="gke.tf"
resource "google_container_cluster" "shop" {
  name                = "shop-auto"
  location            = "europe-west1"
  enable_autopilot    = true
  network             = google_compute_network.shop.id
  subnetwork          = google_compute_subnetwork.ew1.id
  deletion_protection = true

  release_channel {
    channel = "REGULAR"
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  private_cluster_config {
    enable_private_nodes = true
  }

  master_authorized_networks_config {
    cidr_blocks {
      cidr_block   = "203.0.113.0/24"
      display_name = "office"
    }
  }
}
```
@end

@concept Cost visibility with budgets
@plain
A **budget** watches spend on a billing account, a project or a label, and notifies at thresholds. It does not stop spending by itself.
@problem
A forgotten cluster or runaway query can cost a lot before anyone notices.
@does
- Thresholds on actual or forecasted spend (for example 50, 90, 100 percent). Notifications go to billing admins by email and optionally to a Pub/Sub topic.
- A Cloud Run function can listen to the topic and take action, such as scaling down or unlinking billing in a sandbox. That is destructive; use with care.
- Scope with `filter` on projects, services or labels.
- **AWS equivalent**: AWS Budgets with actions. Main difference: there is no built-in action type; use Pub/Sub automation.
@diagram flow
caption: Budget alert path
nodes:
  - "Spend|forecast above 90 percent|warn"
  - "Budget|thresholds|cp"
  - "Pub/Sub topic|programmatic|info"
  - "Handler|notify or scale down|app"
@h Create
```bash title="Budget" lab
gcloud billing budgets create --billing-account=0A1B2C-3D4E5F-6A7B8C --display-name="shop-dev monthly" \
  --budget-amount=500USD --filter-projects=projects/shop-dev-123456 \
  --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
  --threshold-rule=percent=1.0,basis=forecasted-spend \
  --notifications-rule-pubsub-topic=projects/shop-admin-123456/topics/budget-alerts
```
@check
Does a budget stop spending when exceeded? || No. It only notifies, and you must automate any action.
@end

@concept Recommender and committed use for cost
@plain
The **Recommender** service produces cost and security suggestions such as idle VMs, oversized machines, unattached disks and committed use purchases.
@problem
Waste hides across many projects.
@does
- Recommenders include `google.compute.instance.IdleResourceRecommender`, `google.compute.instance.MachineTypeRecommender`, `google.compute.disk.IdleResourceRecommender`, and `google.cloudbilling.commitment.SpendBasedCommitmentRecommender`. Check the full list.
- GKE: use the cost insights and workload rightsizing in the console, and Vertical Pod Autoscaler recommendations.
- Combine with Spot VMs for tolerant workloads, CUDs for the stable baseline and scheduling to stop dev resources.
- **AWS equivalent**: Cost Explorer rightsizing and Compute Optimizer. Main difference: recommendations are one API with a standard format.
@diagram cmp
caption: Cost levers
cards:
  - {h: "Reduce", kind: ok, items: ["Delete idle resources", "Rightsize machines", "Schedule dev shutdown"]}
  - {h: "Discount", kind: info, items: ["Spot for batch", "CUD for baseline", "SUD automatic"]}
  - {h: "Govern", kind: warn, items: ["Budgets", "Labels", "Quotas"]}
@h List recommendations
```bash title="Cost recommendations" lab
gcloud recommender recommendations list --project=shop-dev-123456 --location=europe-west1-b \
  --recommender=google.compute.instance.IdleResourceRecommender \
  --format="table(name.basename(),primaryImpact.costProjection.cost.units,description)"
gcloud recommender recommendations list --project=shop-dev-123456 --location=europe-west1-b \
  --recommender=google.compute.instance.MachineTypeRecommender --format=json | head -40
```
@end

@concept Billing export to BigQuery
@plain
Billing export writes detailed cost lines to BigQuery daily or continuously, so you can slice by project, service, SKU and label.
@problem
Invoices and the console show totals; you need line-level data to find which team or workload is expensive.
@does
- Export types: standard usage cost, detailed usage cost (resource level), and pricing data. Set up from the Billing console, to a dataset in a project you choose. Check current UI options, as it is not a gcloud command.
- Tables are named `gcp_billing_export_v1_BILLING_ACCOUNT_ID`. Data is partitioned by usage time.
- Join with labels (`labels`, `project.labels`) for cost allocation. Credits and discounts appear in a `credits` array.
- **AWS equivalent**: Cost and Usage Report with Athena. Main difference: it lands directly in BigQuery.
@diagram flow
caption: Cost analysis
nodes:
  - "Billing account|usage lines|warn"
  - "BigQuery dataset|billing export|db"
  - "SQL and labels|team, service|info"
  - "Dashboard|Looker Studio|ok"
@h Cost by service and label
```bash title="Top spend last 30 days" lab
bq query --use_legacy_sql=false '
SELECT service.description AS service,
       labels.value AS team,
       ROUND(SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)), 2) AS net_cost
FROM `shop-admin-123456.billing.gcp_billing_export_v1_0A1B2C_3D4E5F_6A7B8C`
LEFT JOIN UNNEST(labels) AS labels ON labels.key = "team"
WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
GROUP BY service, team
ORDER BY net_cost DESC
LIMIT 20'
```
@check
Why join on labels? || To attribute cost to teams or apps.
@end

@concept BigQuery basics for operations
@plain
**BigQuery** is a serverless data warehouse. Engineers use it for logs, billing, audit and metrics analysis rather than for building warehouses.
@problem
Grep over log files does not scale, and aggregations across projects need SQL.
@does
- Hierarchy: project, dataset (with a location), table. Standard SQL with nested and repeated fields.
- Pricing: on-demand (per bytes scanned) or capacity (slots). Always filter on the partition column and select only needed columns; use `--dry_run` to estimate bytes.
- Partition by time and cluster by commonly filtered columns. Set table or partition expiration to control storage.
- Log sinks to BigQuery with partitioned tables are the standard way to analyse logs and audit trails.
- **AWS equivalent**: Athena and Redshift Serverless. Main difference: storage and compute are decoupled with no cluster; cost control depends on query discipline.
@diagram flow
caption: Query cost control
nodes:
  - "Write SQL|select needed columns|app"
  - "Dry run|estimate bytes|info"
  - "Partition filter|prune data|ok"
  - "Run|billed by bytes scanned|warn"
@h Audit and logs
```bash title="Estimate and run" lab
bq query --use_legacy_sql=false --dry_run '
SELECT protopayload_auditlog.authenticationInfo.principalEmail AS who,
       protopayload_auditlog.methodName AS method,
       COUNT(*) AS n
FROM `shop-dev-123456.audit.cloudaudit_googleapis_com_activity`
WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 1 DAY)
GROUP BY who, method
ORDER BY n DESC
LIMIT 20'
bq mk --dataset --location=EU --default_table_expiration=2592000 shop-dev-123456:ops_logs
```
:::tip
Set a maximum bytes billed with `--maximum_bytes_billed` for ad hoc queries to prevent expensive mistakes.
:::
@end
