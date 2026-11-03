---
title: CI/CD to Azure with OIDC, Bicep and Terraform
minutes: 60
objectives:
  - Deploy from GitHub Actions and Azure DevOps without stored secrets using OIDC
  - Write and deploy Bicep with modules, parameters and what-if
  - Manage Azure with Terraform azurerm including remote state
---
Pipelines should authenticate with federation and infrastructure should be code. These pages give working building blocks for both.

@concept GitHub Actions to Azure with OIDC
@plain
GitHub issues a short-lived OIDC token for each workflow run. `azure/login` exchanges it for an Entra token through a federated credential.
@problem
Storing a service principal secret in GitHub means a long-lived credential that can leak.
@does
- **AWS equivalent**: `aws-actions/configure-aws-credentials` with an IAM OIDC provider and role.
- **Main difference**: you create an app registration or user-assigned identity, add a federated credential with subject such as `repo:org/repo:environment:prod`, then give the identity roles. The workflow needs `permissions: id-token: write`. Client ID, tenant ID and subscription ID are not secrets.
- Use GitHub **environments** for approvals and to scope the subject claim.
@diagram seq
caption: Login without secrets
actors: ["Workflow|GitHub runner|app", "GitHub OIDC|issues JWT|ext", "Entra ID|federated credential|cp", "Azure|ARM|env"]
steps:
  - "0>1: request OIDC token | req"
  - "1>0: JWT subject repo and env | resp"
  - "0>2: exchange token | tls"
  - "2>0: access token | resp"
  - "0>3: az and kubectl calls | req"
@h Workflow
```yaml title=".github/workflows/deploy.yml"
name: deploy
on:
  push:
    branches: [main]
permissions:
  id-token: write
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: prod
    steps:
      - uses: actions/checkout@v4
      - uses: azure/login@v2
        with:
          client-id: ${{ vars.AZURE_CLIENT_ID }}
          tenant-id: ${{ vars.AZURE_TENANT_ID }}
          subscription-id: ${{ vars.AZURE_SUBSCRIPTION_ID }}
      - name: Build and push image
        run: |
          az acr login -n acrshopexample
          az acr build -r acrshopexample -t shop/api:${{ github.sha }} ./api
      - uses: azure/aks-set-context@v4
        with:
          resource-group: rg-shop-prod
          cluster-name: aks-shop-prod
      - run: kubectl -n shop set image deploy/api api=acrshopexample.azurecr.io/shop/api:${{ github.sha }}
```
@check
Which workflow permission is required for OIDC? || id-token: write.
@end

@concept Azure DevOps pipelines and service connections
@plain
**Azure DevOps** offers Repos, Boards, Pipelines and Artifacts. Pipelines reach Azure through a **service connection**, which can use workload identity federation.
@problem
Teams that already live in Azure DevOps need secure access to Azure with no stored secrets.
@does
- **AWS equivalent**: CodePipeline and CodeBuild.
- **Main difference**: YAML pipelines with stages, jobs and steps; environments with approvals and checks; Microsoft-hosted or self-hosted agents (self-hosted agents in your VNet reach private clusters). A service connection of type Azure Resource Manager with *workload identity federation* creates the federated credential for you.
- Use variable groups linked to Key Vault for any unavoidable secret.
- Microsoft-hosted agent images change; check the current labels.
@diagram flow
caption: Pipeline structure
nodes:
  - "Trigger|branch or PR|ext"
  - "Stage build|test and image|app"
  - "Environment check|approval|warn"
  - "Stage deploy|AzureCLI task|ok"
@h Pipeline
```yaml title="azure-pipelines.yml"
trigger:
  branches:
    include: [main]
pool:
  vmImage: ubuntu-latest
variables:
  acr: acrshopexample
stages:
  - stage: Build
    jobs:
      - job: image
        steps:
          - task: AzureCLI@2
            displayName: ACR build
            inputs:
              azureSubscription: sc-shop-prod
              scriptType: bash
              scriptLocation: inlineScript
              inlineScript: |
                az acr build -r $(acr) -t shop/api:$(Build.BuildId) ./api
  - stage: Deploy
    dependsOn: Build
    jobs:
      - deployment: aks
        environment: shop-prod
        strategy:
          runOnce:
            deploy:
              steps:
                - task: AzureCLI@2
                  inputs:
                    azureSubscription: sc-shop-prod
                    scriptType: bash
                    scriptLocation: inlineScript
                    inlineScript: |
                      az aks get-credentials -g rg-shop-prod -n aks-shop-prod --overwrite-existing
                      kubectl -n shop set image deploy/api api=$(acr).azurecr.io/shop/api:$(Build.BuildId)
```
@end

@concept Bicep fundamentals
@plain
**Bicep** is a declarative language that compiles to ARM JSON. It describes Azure resources with less noise and day-zero support for new APIs.
@problem
Raw ARM JSON is verbose and hard to review.
@does
- **AWS equivalent**: CloudFormation (and CDK as a higher level layer).
- **Main difference**: no state file; ARM itself is the state. Deployments are incremental by default. Resource symbolic names, `param`, `var`, `output`, `existing` references and string interpolation. Scope with `targetScope`.
- `az bicep build` compiles; `az deployment group what-if` previews changes.
- Use the VS Code extension for IntelliSense against the resource schema.
@diagram flow
caption: From file to resources
nodes:
  - "main.bicep|source|plain"
  - "Compile|ARM JSON|info"
  - "what-if|preview diff|warn"
  - "Deployment|incremental apply|ok"
@h A storage account
```bicep title="storage.bicep" nocheck
@description('Environment short name')
param env string = 'dev'
param location string = resourceGroup().location

var name = 'stshop${env}${uniqueString(resourceGroup().id)}'

resource st 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  sku: { name: 'Standard_ZRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowSharedKeyAccess: false
  }
}

output storageId string = st.id
```
```bash title="Preview and deploy" lab
az deployment group what-if -g rg-shop-dev --template-file storage.bicep --parameters env=dev
az deployment group create -g rg-shop-dev --template-file storage.bicep --parameters env=dev
```
:::note
API versions in the example may be old by the time you read it. Check the current version in the Bicep resource reference.
:::
@check
Where does Bicep keep deployment state? || In Azure Resource Manager itself. There is no separate state file.
@end

@concept Bicep modules and parameters
@plain
Modules are Bicep files called from other Bicep files. A parameter file supplies per environment values.
@problem
One large file per environment duplicates code and drifts.
@does
- **AWS equivalent**: nested stacks and CloudFormation modules.
- **Main difference**: modules can come from local paths or a registry (`br:acrshopexample.azurecr.io/bicep/aks:1.0`). Use `.bicepparam` files for typed parameters. Outputs of one module feed another, forming dependency order automatically.
- Azure Verified Modules (AVM) provide maintained modules; check the current catalogue.
- **Deployment stacks** manage the lifecycle of resources as a unit and can deny deletion; check the current docs.
@diagram layers
caption: Bicep layout
layers:
  - {label: "Entry", nodes: ["main.bicep|orchestrates|cp", "prod.bicepparam|values|info"]}
  - {label: "Modules", nodes: ["network.bicep|VNet and subnets|app", "aks.bicep|cluster|app", "data.bicep|Postgres and Redis|app"]}
@h Calling a module
```bicep title="main.bicep" nocheck
targetScope = 'resourceGroup'
param location string = resourceGroup().location
param env string

module net 'modules/network.bicep' = {
  name: 'network'
  params: {
    location: location
    addressSpace: '10.20.0.0/16'
  }
}

module aks 'modules/aks.bicep' = {
  name: 'aks'
  params: {
    location: location
    subnetId: net.outputs.aksSubnetId
    env: env
  }
}
```
```text title="prod.bicepparam" nocheck
using './main.bicep'
param env = 'prod'
```
@end

@concept Terraform azurerm provider and state
@plain
The **azurerm** provider manages Azure resources with Terraform. State lives in a remote backend, usually an Azure Storage blob container.
@problem
Teams already using Terraform on AWS want one workflow for both clouds, with locking and shared state.
@does
- **AWS equivalent**: the aws provider with S3 backend and DynamoDB locking.
- **Main difference**: the Azure Storage backend locks with blob leases, so no extra lock table. Authenticate with `use_oidc = true` in CI or `use_azuread_auth = true` for the backend to avoid access keys. The provider needs `features {}` and `subscription_id` set explicitly.
- Another provider, **azapi**, covers new Azure features before azurerm does.
- Pin provider versions and run `terraform plan` in pull requests.
@diagram flow
caption: Terraform workflow
nodes:
  - "Pull request|terraform plan|ext"
  - "Remote state|blob container with lease lock|env"
  - "Merge to main|terraform apply|cp"
  - "Azure|ARM API|ok"
@h Provider and backend
```hcl title="versions.tf"
terraform {
  required_version = ">= 1.6"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
  backend "azurerm" {
    resource_group_name  = "rg-tfstate"
    storage_account_name = "sttfstateshop"
    container_name       = "tfstate"
    key                  = "shop-prod.tfstate"
    use_azuread_auth     = true
    use_oidc             = true
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
  use_oidc        = true
}

variable "subscription_id" {
  type = string
}
```
@check
How does the azurerm backend lock state? || With an Azure Blob lease on the state blob.
@end

@concept Terraform for AKS and networking
@plain
A realistic Terraform stack creates a resource group, VNet, AKS, ACR and the role assignment between them.
@problem
Clicking resources together does not repeat across environments.
@does
- **AWS equivalent**: Terraform EKS module with VPC module.
- **Main difference**: `azurerm_kubernetes_cluster` has blocks for `default_node_pool`, `identity`, `network_profile`, `oidc_issuer_enabled` and `workload_identity_enabled`. Extra pools are separate `azurerm_kubernetes_cluster_node_pool` resources. Argument names change between provider major versions; check the current provider docs.
- Output `kube_config` is sensitive.
- Use the Entra provider `azuread` for groups and app registrations.
@diagram flow
caption: Resource graph
nodes:
  - "Resource group|rg-shop-prod|env"
  - "VNet and subnets|10.20.0.0/16|info"
  - "AKS cluster|overlay, OIDC, workload identity|app"
  - "ACR + AcrPull|kubelet identity|ok"
@h Core resources
```hcl title="aks.tf"
resource "azurerm_resource_group" "shop" {
  name     = "rg-shop-prod"
  location = "westeurope"
  tags     = { app = "shop", env = "prod" }
}

resource "azurerm_virtual_network" "shop" {
  name                = "vnet-shop"
  location            = azurerm_resource_group.shop.location
  resource_group_name = azurerm_resource_group.shop.name
  address_space       = ["10.20.0.0/16"]
}

resource "azurerm_subnet" "aks" {
  name                 = "snet-aks"
  resource_group_name  = azurerm_resource_group.shop.name
  virtual_network_name = azurerm_virtual_network.shop.name
  address_prefixes     = ["10.20.0.0/20"]
}

resource "azurerm_kubernetes_cluster" "shop" {
  name                      = "aks-shop-prod"
  location                  = azurerm_resource_group.shop.location
  resource_group_name       = azurerm_resource_group.shop.name
  dns_prefix                = "shopprod"
  sku_tier                  = "Standard"
  oidc_issuer_enabled       = true
  workload_identity_enabled = true
  automatic_upgrade_channel = "patch"

  default_node_pool {
    name                 = "system"
    vm_size              = "Standard_D4s_v5"
    vnet_subnet_id       = azurerm_subnet.aks.id
    zones                = ["1", "2", "3"]
    auto_scaling_enabled = true
    min_count            = 3
    max_count            = 5
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin      = "azure"
    network_plugin_mode = "overlay"
    network_data_plane  = "cilium"
    pod_cidr            = "192.168.0.0/16"
  }
}

resource "azurerm_role_assignment" "acr_pull" {
  scope                = var.acr_id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_kubernetes_cluster.shop.kubelet_identity[0].object_id
}

variable "acr_id" {
  type = string
}
```
@end

@concept Choosing Bicep or Terraform
@plain
Both are good. The decision is mostly about your team and your multi-cloud needs.
@problem
Teams switch tools mid-way and end up with two states of truth.
@does
- **AWS equivalent**: CloudFormation or CDK compared with Terraform.
- **Main difference**: Bicep has same-day support for new Azure features and no state to manage, but covers only Azure and ARM. Terraform spans AWS, Azure, Kubernetes and SaaS with a plan and state, and a larger ecosystem of modules and policy tools.
- Do not manage the same resource with both tools.
- Policy as code: Azure Policy for Azure, Checkov, tfsec and OPA for Terraform plans.
@diagram cmp
caption: Trade-offs
cards:
  - {h: "Bicep", kind: info, items: ["Azure only", "No state file", "Immediate API coverage", "what-if preview"]}
  - {h: "Terraform", kind: app, items: ["Multi cloud", "State and plan", "Large module ecosystem", "Drift detection with plan"]}
@choose Pick the tool
Bicep | Azure-only estate, platform team close to Microsoft tooling | you manage Kubernetes objects and SaaS in the same code
Terraform | you already run Terraform on AWS or other clouds | you want zero state handling
@h Drift check
```bash title="Detect drift" lab
terraform plan -detailed-exitcode -out=tfplan; echo "exit code $? (0 none, 2 changes)"
az deployment group what-if -g rg-shop-prod --template-file main.bicep --parameters prod.bicepparam
```
@check
Which tool needs a state backend, Bicep or Terraform? || Terraform.
@end

@concept Image build and promotion flow
@plain
A good pipeline builds once, scans, signs and promotes the same image digest through environments.
@problem
Rebuilding for each environment makes production run something nobody tested.
@does
- **AWS equivalent**: CodePipeline with ECR image promotion.
- **Main difference**: ACR import copies an image between registries or repositories by digest (`az acr import`), and ACR supports Notation signing with Key Vault keys. Deploy using the digest, not a mutable tag.
- GitOps is an alternative: the AKS **Flux extension** (GitOps) or Argo CD syncs manifests from Git.
- Gate promotion on Defender scan results and tests.
@diagram flow
caption: Promotion by digest
nodes:
  - "Build|image with sha tag|app"
  - "Scan and sign|Defender, Notation|warn"
  - "Import to prod ACR|same digest|info"
  - "Deploy|GitOps or kubectl|ok"
@h Import and pin the digest
```bash title="Promote" lab
az acr import -n acrshopprod --source acrshopdev.azurecr.io/shop/api:1.4.0 --image shop/api:1.4.0
DIGEST=$(az acr repository show -n acrshopprod --image shop/api:1.4.0 --query digest -o tsv)
echo "deploy acrshopprod.azurecr.io/shop/api@${DIGEST}"
```
@end
