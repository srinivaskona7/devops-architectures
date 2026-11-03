---
title: Environment strategy
minutes: 50
objectives:
  - Compare directories, workspaces and Terragrunt for separating dev, staging and production
  - Explain why account-per-environment is the strongest isolation
  - Lay out a repository so environments differ only in inputs
---
The same infrastructure usually exists in several environments. The question is how to keep them alike where they should be and different where they must be, without one mistake reaching production.

@concept What an environment strategy must give you
@plain
You want identical structure across environments, different sizes and settings, separate state, and permissions that stop a dev pipeline touching production.
@problem
Copying folders drifts apart, and a single shared state turns every change into a production risk.
@does
- Separate **state** per environment so a mistake or lock in dev never blocks prod.
- Shared **code** (modules) so a fix lands everywhere.
- Different **inputs** (CIDR, instance size, replica count).
- Different **credentials**, ideally different cloud accounts.
@diagram flow
caption: Shared code, separate state and inputs
nodes:
  - "Modules|one code base|app"
  - "dev inputs and state|small, cheap|info"
  - "stage inputs and state|like prod|info"
  - "prod inputs and state|HA, protected|warn"
@end

@concept Directory per environment
@plain
Each environment has its own folder containing a small root module that calls shared modules with its own values and has its own backend key.
@problem
You need clear separation, readable code and no hidden switching mechanism.
@does
- Layout: `modules/` for shared code and `envs/dev`, `envs/stage`, `envs/prod` for roots.
- You can see exactly what prod runs by reading its folder; a plan only touches the folder you run it in.
- Cost: some duplication of the module calls; changes to the shape must be made in each folder.
- This is the most widely recommended approach for most teams.
@diagram layers
caption: Repository layout
layers:
  - {label: "Environments", nodes: ["envs/dev|own state|info", "envs/stage|own state|info", "envs/prod|own state|warn"]}
  - {label: "Shared", nodes: ["modules/network|VPC|app", "modules/eks|cluster|app", "modules/database|RDS|app"]}
@h Folder example
```text title="Layout" nocheck
infra/
  modules/
    network/  eks/  database/
  envs/
    dev/   main.tf backend.tf terraform.tfvars
    stage/ main.tf backend.tf terraform.tfvars
    prod/  main.tf backend.tf terraform.tfvars
```
```hcl title="envs/prod/main.tf"
module "network" {
  source = "../../modules/network"

  name = "shop-prod"
  azs  = ["eu-west-1a", "eu-west-1b", "eu-west-1c"]
}
```
@end

@concept Workspaces
@plain
A **workspace** is a named state inside the same backend and directory. `terraform workspace new prod` creates another state for the same code. Inside code, `terraform.workspace` returns the name.
@problem
You want several copies of one configuration (feature branches, per-customer stacks) without copying folders.
@does
- The default workspace is called `default`. The S3 backend stores others under `env:/<name>/<key>`.
- Same code, same backend, same credentials: nothing stops a mistaken `apply` in the wrong workspace.
- The current workspace is invisible in the code and easy to forget.
- Good for short-lived copies of a stack such as preview environments; poor as the main way to separate dev from prod.
@diagram cmp
caption: Workspaces are states, not isolation
cards:
  - {h: "Good for", kind: ok, items: ["Ephemeral preview stacks", "Many identical tenants", "Quick experiments"]}
  - {h: "Risky for", kind: bad, items: ["dev versus prod", "Same credentials for both", "Hidden current workspace"]}
@h Using workspaces
```bash title="Workspace commands" lab
terraform workspace list
terraform workspace new preview-123
terraform workspace select default
terraform workspace show
```
```hcl title="Per-workspace values"
locals {
  size = terraform.workspace == "prod" ? "db.r6g.large" : "db.t4g.micro"
}
```
@check
Why do many teams avoid workspaces for prod versus dev? || They share code, backend and credentials, and the active workspace is easy to forget, so a wrong apply is likely.
@end

@concept Account-per-environment
@plain
Each environment lives in its own cloud account (AWS account, Azure subscription, GCP project). Terraform assumes a role in the target account.
@problem
IAM mistakes, quotas and noisy neighbours cross environments inside one account; a compromised dev credential could reach production data.
@does
- Accounts are the hardest security and billing boundary the cloud offers.
- Use AWS Organizations (and Control Tower or a landing zone) to create accounts and apply guardrails.
- The pipeline authenticates once (OIDC) and then assumes `terraform-deploy` in the right account per environment.
- State may live in a central tooling account or in each account; either way restrict access.
@diagram flow
caption: One pipeline, a role per account
nodes:
  - "CI job|OIDC identity|app"
  - "Assume role|chosen by environment|cp"
  - "dev account|111111111111|info"
  - "prod account|333333333333|warn"
@h Provider with an assumed role
```hcl title="provider.tf"
variable "account_id" {
  type = string
}

provider "aws" {
  region = "eu-west-1"

  assume_role {
    role_arn = "arn:aws:iam::${var.account_id}:role/terraform-deploy"
  }
}
```
@end

@concept Terragrunt
@plain
Terragrunt is a thin wrapper around Terraform (and OpenTofu) that removes repetition: it generates backend and provider blocks, passes inputs, and runs many stacks in dependency order.
@problem
With directories per environment you repeat backend configuration and module calls in every folder, which grows to hundreds of near-identical files.
@does
- A `terragrunt.hcl` per stack points to a module source and gives inputs.
- A parent file defines `remote_state` and `generate` once; children `include` it.
- `dependency` blocks read outputs from other stacks; `run-all` (or newer `run --all` forms, check the current docs) applies stacks in order.
- Added tool, added learning curve; weigh against plain Terraform with a good layout and CI.
@diagram flow
caption: DRY configuration generated per stack
nodes:
  - "root terragrunt.hcl|backend and provider rules|cp"
  - "prod/network/terragrunt.hcl|inputs|app"
  - "Generated backend.tf|per stack key|info"
  - "terraform apply|runs underneath|ok"
@h Example
```hcl title="live/prod/network/terragrunt.hcl" nocheck
include "root" {
  path = find_in_parent_folders()
}

terraform {
  source = "git::https://github.com/acme/tf-modules.git//network?ref=v1.4.0"
}

inputs = {
  name = "shop-prod"
  azs  = ["eu-west-1a", "eu-west-1b"]
}
```
@end

@concept Tfvars per environment and a shared root
@plain
A hybrid layout keeps one root module and supplies different `.tfvars` files and backend configs per environment.
@problem
You want little duplication and still separate state per environment.
@does
- Run `terraform init -backend-config=envs/prod.tfbackend -reconfigure` and `terraform plan -var-file=envs/prod.tfvars`.
- One root means one set of code reviewed once. Differences are limited to the variable files, which are easy to diff.
- Weakness: every environment must use the same code version at the same time, so you cannot promote a change gradually through the code (only through inputs). Use feature flags with care.
- Easily automated in CI with an environment matrix.
@diagram flow
caption: One root, per-environment files
nodes:
  - "Root module|same code|app"
  - "envs/prod.tfvars|values|info"
  - "envs/prod.tfbackend|state location|info"
  - "plan and apply|prod state|ok"
@h Running it
```bash title="Per-environment commands" lab
ENV=prod
terraform init -reconfigure -backend-config="envs/${ENV}.tfbackend"
terraform plan -var-file="envs/${ENV}.tfvars" -out=tfplan
```
@check
What is the main limitation of a single shared root with tfvars? || All environments run the same code version, so a code change reaches every environment together.
@end

@concept Promotion, drift between environments and guardrails
@plain
Promotion means moving a tested change from dev to stage to prod. Guardrails make sure that prod cannot be changed by accident.
@problem
Changes that skip dev, or prod settings that nobody can explain, cause outages.
@does
- Promote by merging the same change through environments, each with its own plan and approval.
- Use GitHub environments with required reviewers for production applies.
- Keep prod-only differences small, listed in tfvars, and commented.
- Protect with `prevent_destroy`, deletion protection on databases, and SCPs that block dangerous API calls.
@diagram flow
caption: Gradual rollout
numbered: true
nodes:
  - "Merge to main|reviewed code|app"
  - "Apply to dev|automatic|ok"
  - "Apply to stage|automatic after dev|info"
  - "Apply to prod|manual approval|warn"
@choose Environment separation
Directory per environment | most teams, clear and explicit | you have hundreds of near-identical stacks
Workspaces | short-lived copies of one stack | separating dev from production
Terragrunt | very many stacks with repeated boilerplate | a small team with three environments
Account per environment | any production workload | a toy project with one account
@end
