---
title: Custom providers, import and migration
minutes: 55
objectives:
  - Explain how a provider works and when writing one is justified
  - Build the outline of a provider with the plugin framework
  - Bring existing cloud resources under Terraform with import blocks and generated config
  - Plan a migration from the console or CloudFormation
---
Most teams never write a provider, but many must adopt infrastructure that already exists. This section covers both ends.

@concept What a provider is
@plain
A provider is a separate program that Terraform starts and talks to over gRPC. It translates resource blocks into API calls for one service.
@problem
Terraform core knows nothing about AWS, GitHub or your internal platform. Providers keep that knowledge outside core and allow anyone to extend it.
@does
- `terraform init` downloads providers from a registry and records versions and hashes in `.terraform.lock.hcl`.
- Each provider declares resource types, data sources, and optionally functions, with schemas.
- Core calls it to validate, plan (diff), apply (create, read, update, delete) and read.
- Providers are written in Go. The recommended library today is the Terraform Plugin Framework; the older SDKv2 still exists.
@diagram flow
caption: Core talks to a provider process
nodes:
  - "terraform core|graph and state|cp"
  - "gRPC|plugin protocol|info"
  - "Provider binary|schema and CRUD|app"
  - "Target API|AWS, GitHub, internal|ext"
@h Pinning providers
```hcl title="versions.tf"
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}
```
@end

@concept When to write a provider
@plain
Write one only when no existing provider or simpler path covers your API.
@problem
Providers are real software: Go code, tests, releases, documentation and upgrades. A provider written for one small script becomes a burden.
@does
- First look for an existing one on the registry, or for a generic option: the `http` data source, `restapi` community providers, or `terraform_data` with a local script.
- Justified when: an internal platform API is used by many teams, you want drift detection and plan output for it, or a vendor has no provider.
- Cost estimate: schema design, CRUD functions, acceptance tests, signed releases and docs.
- OpenTofu and Terraform share the plugin protocol, so one provider usually works with both.
@diagram flow
caption: Decision path
nodes:
  - "Provider exists?|search the registry|info"
  - "Generic provider?|http or restapi|warn"
  - "Few users?|use a script|plain"
  - "Many users, stable API|write a provider|ok"
@choose Approach for an internal API
Existing provider | One exists and is maintained | It lacks resources you need and is abandoned
Script with terraform_data | One or two simple calls, one team | You need drift detection or imports
Custom provider | Many teams, stable API, long life | A single use that a pipeline step could cover
@end

@concept Provider anatomy with the plugin framework
@plain
A framework provider has a provider type, resource types and a small main that serves them.
@problem
Without a pattern, every provider invents its own structure and its schema mistakes show up as confusing plans.
@does
- `main.go` calls `providerserver.Serve` with a factory for your provider.
- The provider type implements `Metadata`, `Schema`, `Configure` and lists its `Resources` and `DataSources`.
- Schemas describe attributes with types and flags: `Required`, `Optional`, `Computed`, `Sensitive`.
- Start from the HashiCorp scaffolding repository for the framework and check the current docs for exact package paths.
@diagram layers
caption: Pieces of a provider
layers:
  - {label: "Entry", nodes: ["main.go|providerserver.Serve|app"]}
  - {label: "Provider", nodes: ["Schema|connection settings|info", "Configure|builds API client|cp"]}
  - {label: "Resources", nodes: ["Create|call API|ok", "Read|refresh state|ok", "Update|diff to API|ok", "Delete|remove|ok"]}
@h Skeleton
```go title="main.go" nocheck
package main

import (
	"context"
	"log"

	"github.com/hashicorp/terraform-plugin-framework/providerserver"
	"example.com/acme/terraform-provider-platform/internal/provider"
)

func main() {
	err := providerserver.Serve(context.Background(), provider.New("dev"), providerserver.ServeOpts{
		Address: "registry.terraform.io/acme/platform",
	})
	if err != nil {
		log.Fatal(err)
	}
}
```
@end

@concept Writing a resource
@plain
A resource implements four methods that map to the API, plus a schema that describes its fields.
@problem
Terraform only works well if Read returns exactly what the API holds, so drift is visible, and if Create stores computed IDs in state.
@does
- Schema: `name` Required, `id` Computed, optional settings with defaults using plan modifiers.
- Create: read the plan into a model, call the API, write the result (including generated ID) to state.
- Read: fetch by ID; if the API says not found, remove the resource from state so Terraform recreates it.
- Update and Delete follow the same pattern. Add `ImportState` so `terraform import` works.
- Return errors as diagnostics with clear text; never panic.
@diagram seq
caption: Create then plan again
actors: ["Terraform|core|cp", "Resource|your Go code|app", "API|platform service|ext"]
steps:
  - "0>1: Create with plan | req"
  - "1>2: POST item | req"
  - "2>1: id and fields | resp"
  - "1>0: state saved | resp"
  - "0>1: Read on next plan | req"
  - "1>2: GET by id | req"
@h Method outline
```go title="resource_item.go" nocheck
func (r *itemResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	var plan itemModel
	resp.Diagnostics.Append(req.Plan.Get(ctx, &plan)...)
	if resp.Diagnostics.HasError() {
		return
	}

	created, err := r.client.CreateItem(ctx, plan.Name.ValueString())
	if err != nil {
		resp.Diagnostics.AddError("Cannot create item", err.Error())
		return
	}

	plan.ID = types.StringValue(created.ID)
	resp.Diagnostics.Append(resp.State.Set(ctx, plan)...)
}
```
@end

@concept Testing, local use and releasing a provider
@plain
Providers are tested with unit tests and with **acceptance tests** that create real objects. For local trials you point Terraform at your build with a development override.
@problem
A provider that mis-reports state causes endless diffs or deleted resources in other people's pipelines.
@does
- Acceptance tests use the `terraform-plugin-testing` module and run real applies when `TF_ACC=1` is set.
- `dev_overrides` in `~/.terraformrc` lets you run your local binary without publishing.
- Release: build for each OS and architecture with GoReleaser, sign checksums with GPG, publish to the public registry or a private registry.
- Follow semantic versioning; schema changes that force replacement are breaking.
@diagram flow
caption: From code to registry
numbered: true
nodes:
  - "Unit tests|schema and mapping|app"
  - "Acceptance tests|TF_ACC=1|warn"
  - "dev_overrides|try locally|info"
  - "Signed release|registry|ok"
@h Development override
```hcl title="~/.terraformrc" nocheck
provider_installation {
  dev_overrides {
    "acme/platform" = "/home/me/go/bin"
  }
  direct {}
}
```
```bash title="Run acceptance tests" lab
TF_ACC=1 go test ./... -v -timeout 30m
```
:::warn
Acceptance tests create real resources and can cost money. Run them in a sandbox account.
:::
@end

@concept Import blocks and generated configuration
@plain
An `import` block tells Terraform that an existing object should become a given resource address. With `-generate-config-out`, Terraform writes the matching HCL for you.
@problem
Hand-writing code for 200 existing resources and running `terraform import` one at a time is slow and not reviewable.
@does
- The `import` block holds `to` (address) and `id` (provider-specific import ID, found in the resource docs).
- `terraform plan -generate-config-out=generated.tf` writes a draft resource block. Clean it up: remove defaults and computed attributes, replace literals with variables.
- Import blocks are planned like any change, so the pull request shows exactly what will be adopted. Remove the blocks after apply.
- A clean follow-up plan with zero changes proves the code matches reality.
@diagram flow
caption: Import workflow
numbered: true
nodes:
  - "Write import block|address and id|app"
  - "Plan with generate config|draft HCL|info"
  - "Clean the code|variables, tags|warn"
  - "Plan shows no diff|adopted|ok"
@h Example
```hcl title="import.tf"
import {
  to = aws_s3_bucket.logs
  id = "acme-central-logs"
}

import {
  for_each = toset(["sg-0123456789abcdef0", "sg-0fedcba9876543210"])
  to       = aws_security_group.legacy[each.key]
  id       = each.key
}
```
```bash title="Generate code" lab
terraform plan -generate-config-out=generated.tf
terraform apply
```
:::note
`for_each` in import blocks needs a recent Terraform release; check the current docs for your version.
:::
@check
How do you know an import is complete? || A plan after the import shows no changes, meaning the code matches the real object.
@end

@concept Migrating console-built infrastructure
@plain
Moving to Terraform is a programme, not a command. Work in slices and keep production running throughout.
@problem
Big-bang rewrites stall, and half-imported estates are worse than none because nobody trusts either source.
@does
- Inventory first: tag or list resources by owner and layer. Tools such as `terraformer` or the AWS Resource Explorer can help; always review output.
- Import foundations first (network, IAM), then data, then compute. Each slice gets its own state.
- Freeze console changes for the slice being imported, and enable drift checks afterwards.
- Add a service control policy or IAM boundary later that blocks console writes in production.
@diagram flow
caption: Migrate in slices
numbered: true
nodes:
  - "Inventory|owners and layers|info"
  - "Import slice|one stack at a time|app"
  - "Verify|plan is clean|ok"
  - "Lock the console|policy blocks manual edits|cp"
@end

@concept CloudFormation to Terraform
@plain
Existing CloudFormation stacks can be replaced with Terraform without deleting resources, if you retire the stack carefully.
@problem
Deleting a stack deletes its resources. Importing them while the stack still owns them leaves two owners.
@does
- Step 1: set `DeletionPolicy: Retain` on every resource in the template and update the stack.
- Step 2: import the resources into Terraform and reach a clean plan.
- Step 3: delete the CloudFormation stack. Retained resources stay.
- Alternatively, keep CloudFormation for what AWS manages best (for example StackSets and Control Tower) and use Terraform for the rest.
- Resources with generated names cannot always be imported by name; look up the ID in the stack outputs or `aws cloudformation list-stack-resources`.
@diagram flow
caption: Handing resources over safely
numbered: true
nodes:
  - "Retain policy|update the stack|warn"
  - "Import into Terraform|clean plan|app"
  - "Delete the stack|resources stay|ok"
@h Commands
```bash title="Find physical IDs" lab
aws cloudformation list-stack-resources --stack-name shop-network \
  --query 'StackResourceSummaries[].[LogicalResourceId,PhysicalResourceId,ResourceType]' --output table
```
:::danger
Never delete the stack before every resource is retained. A stack delete removes anything without the Retain policy.
:::
@check
What must be set before deleting a CloudFormation stack you are migrating? || DeletionPolicy Retain on each resource, applied through a stack update.
@end
