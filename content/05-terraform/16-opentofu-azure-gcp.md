---
title: OpenTofu, Azure and Google Cloud basics
minutes: 50
objectives:
  - Explain how OpenTofu relates to Terraform and where they differ
  - Choose between the two for a new or existing project
  - Write basic Azure and Google Cloud resources and authenticate from CI
---
The Terraform workflow is the same on every cloud. This section covers the open-source fork and shows how little changes when the provider changes.

@concept OpenTofu: what and why
@plain
OpenTofu is an open-source fork of Terraform, hosted by the Linux Foundation. It was created after HashiCorp changed Terraform's licence from MPL to the Business Source License in August 2023 (starting from version 1.6).
@problem
Companies and vendors that build products around Terraform needed a guarantee that the core tool stays open source and governed by a community.
@does
- Forked from the last MPL release, Terraform 1.5.x; its first stable release was 1.6.
- Command is `tofu` (`tofu init`, `tofu plan`, `tofu apply`); configuration files are the same HCL.
- Uses its own registry at registry.opentofu.org, which mirrors most providers.
- HashiCorp is now part of IBM; keep an eye on licensing and roadmaps and check current terms.
@diagram flow
caption: Where the fork happened
nodes:
  - "Terraform 1.5|last MPL release|plain"
  - "Licence change|BSL from 1.6|warn"
  - "OpenTofu 1.6|Linux Foundation project|ok"
@end

@concept Compatibility and differences
@plain
For most configurations, `tofu` and `terraform` are interchangeable. The two have diverged and each has features the other lacks.
@problem
A team must know whether they can move, and what they would lose or gain.
@does
- OpenTofu features include native **state encryption**, early evaluation of variables in backend and module `source`, `for_each` on providers, and a `-exclude` flag; check the current release notes for the full list.
- Terraform features include HCP Terraform integration, Sentinel, and its own newer features such as ephemeral values and stacks; availability in OpenTofu varies.
- State files are compatible up to the fork point. Later Terraform versions may write state that OpenTofu cannot read; always test first.
- The `terraform` block works in both; use `required_version` consistently.
@diagram cmp
caption: Not identical any more
cards:
  - {h: "Shared", kind: ok, items: ["HCL syntax and core workflow", "Most providers and modules", "S3 and other backends"]}
  - {h: "OpenTofu extras", kind: info, items: ["State encryption", "Early variable evaluation", "Provider for_each"]}
  - {h: "Terraform extras", kind: info, items: ["HCP Terraform and Sentinel", "Vendor support contracts", "Own newer features"]}
@h State encryption sketch
```hcl title="OpenTofu only" nocheck
terraform {
  encryption {
    key_provider "pbkdf2" "main" {
      passphrase = var.state_passphrase
    }

    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.main
    }

    state {
      method = method.aes_gcm.main
    }
  }
}
```
:::note
Prefer a KMS key provider over a passphrase in production. Check the OpenTofu documentation for current syntax.
:::
@end

@concept Choosing between them and migrating
@plain
The decision depends on licence needs, vendor tooling and features. Migration from Terraform 1.5 or compatible 1.6 to 1.x is usually small.
@problem
Switching blindly can leave you unable to run the other tool on the same state.
@does
- Check licence fit: BSL restricts offering a competing service, not internal use. Legal review decides.
- Check tool support: CI actions, Atlantis, Terragrunt, Spacelift and others support both.
- Migration: install `tofu`, run `tofu init` on a copy, run `tofu plan` and expect no changes, then switch the pipeline. Keep a state backup.
- Pin and document the choice; do not alternate tools on the same state.
@diagram flow
caption: Try on a copy first
numbered: true
nodes:
  - "Back up state|versioned bucket|warn"
  - "tofu init|on a copy|info"
  - "tofu plan|expect no changes|cp"
  - "Switch pipeline|one tool only|ok"
@h Trial commands
```bash title="Try OpenTofu" lab
tofu version
tofu init -reconfigure
tofu plan
```
@choose Terraform or OpenTofu
Terraform | you use HCP Terraform or Sentinel, or want vendor support | your licence review rejects the BSL
OpenTofu | open-source governance matters or you need state encryption | you depend on HashiCorp-only features
Either | mainstream AWS, Azure or GCP resources | you plan to switch back and forth on one state
@end

@concept The Azure provider
@plain
The `azurerm` provider manages Azure resources. Everything lives in a **resource group** inside a subscription, and the provider needs a `features {}` block.
@problem
Azure resources need a consistent model of subscription, tenant and group before anything is created.
@does
- Provider source `hashicorp/azurerm`; a newer `azapi` provider reaches API features not yet in `azurerm`.
- Authentication in CI: OIDC with a federated credential on an app registration or managed identity (variables `ARM_USE_OIDC`, `ARM_CLIENT_ID`, `ARM_TENANT_ID`, `ARM_SUBSCRIPTION_ID`); locally `az login`.
- State backend: `azurerm` backend using a storage account container with blob lease locking.
- Newer provider versions require `subscription_id` to be set; check the current docs.
@diagram flow
caption: Azure hierarchy
nodes:
  - "Tenant|Entra ID|ext"
  - "Subscription|billing and boundary|cp"
  - "Resource group|lifecycle container|info"
  - "Resources|VNet, AKS, SQL|app"
@h Resource group and VNet
```hcl title="azure.tf"
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

resource "azurerm_resource_group" "main" {
  name     = "rg-shop-prod"
  location = "westeurope"
}

resource "azurerm_virtual_network" "main" {
  name                = "vnet-shop-prod"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  address_space       = ["10.30.0.0/16"]
}
```
```hcl title="Azure backend" nocheck
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "acmetfstate"
    container_name       = "tfstate"
    key                  = "prod.tfstate"
    use_oidc             = true
  }
}
```
@check
What organises Azure resources for a shared lifecycle? || A resource group, which is created first and referenced by the resources inside it.
@end

@concept The Google Cloud provider
@plain
The `google` provider manages Google Cloud. Everything belongs to a **project**, and most APIs must be enabled in the project before use.
@problem
Terraform fails with "API not enabled" until `google_project_service` turns on the service, a Google-specific step.
@does
- Provider sources `hashicorp/google` and `hashicorp/google-beta` (preview features).
- Authentication: Application Default Credentials locally (`gcloud auth application-default login`), and **Workload Identity Federation** from GitHub Actions (no key files).
- State backend: `gcs` bucket with built-in locking.
- Networks are global VPCs with regional subnets, unlike AWS where VPCs are regional.
@diagram flow
caption: GCP hierarchy
nodes:
  - "Organisation|policies|ext"
  - "Folder|team grouping|cp"
  - "Project|APIs and billing|info"
  - "Resources|VPC, GKE, Cloud SQL|app"
@h Project service and network
```hcl title="gcp.tf"
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = "europe-west1"
}

resource "google_project_service" "compute" {
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_network" "main" {
  name                    = "shop-prod"
  auto_create_subnetworks = false

  depends_on = [google_project_service.compute]
}

resource "google_compute_subnetwork" "nodes" {
  name          = "nodes-ew1"
  region        = "europe-west1"
  network       = google_compute_network.main.id
  ip_cidr_range = "10.40.0.0/20"
}
```
@end

@concept Cross-cloud concept map
@plain
The same ideas appear on each cloud under different names. Knowing the map lets you reuse module designs.
@problem
Engineers who know one cloud often relearn everything for the next; a map shortens that.
@does
- Account boundary: AWS account, Azure subscription, GCP project.
- Network: VPC (regional), VNet, VPC (global) with subnets.
- Managed Kubernetes: EKS, AKS, GKE; managed Postgres: RDS, Azure Database for PostgreSQL, Cloud SQL.
- Pipeline identity: GitHub OIDC with IAM role, federated credential, Workload Identity Federation.
- State backend: S3, Azure Blob, GCS.
@diagram cmp
caption: Same ideas, different names
cards:
  - {h: "AWS", kind: app, items: ["Account, VPC, EKS, RDS", "S3 state", "IAM role via OIDC"]}
  - {h: "Azure", kind: info, items: ["Subscription, VNet, AKS", "Blob state", "Federated credential"]}
  - {h: "Google Cloud", kind: ok, items: ["Project, VPC, GKE, Cloud SQL", "GCS state", "Workload Identity Federation"]}
@end

@concept Multi-cloud Terraform in practice
@plain
Terraform can manage several clouds in one repository, but one state and one module rarely span clouds well.
@problem
Teams hoping for portability write abstract "cloud-agnostic" modules that hide everything useful and are hard to maintain.
@does
- Keep modules per cloud (`modules/aws/network`, `modules/azure/network`) behind similar input shapes only where it helps.
- One state per cloud and per environment limits blast radius and credentials.
- Use the common layer for what is truly shared: DNS, monitoring SaaS, GitHub, Kubernetes add-ons.
- Cost and skills usually matter more than portability; adopt a second cloud for a reason.
@diagram layers
caption: Shared tools, separate clouds
layers:
  - {label: "Shared services", nodes: ["Cloudflare / DNS|providers|ext", "Datadog / Grafana|providers|ext", "GitHub|repos and teams|ext"]}
  - {label: "Per-cloud stacks", nodes: ["aws/prod|own state|app", "azure/prod|own state|info", "gcp/prod|own state|ok"]}
@check
Why is one big cross-cloud state a bad idea? || A failure or credential issue in one cloud blocks all, and the blast radius and run time grow.
@end
