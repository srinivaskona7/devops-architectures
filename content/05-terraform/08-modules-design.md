---
title: Modules and their design
minutes: 45
objectives:
  - Explain what a module is and structure one with inputs, outputs and files
  - Decide what belongs in a module and what interface it should expose
  - Avoid common module mistakes such as thin wrappers and hidden provider configuration
---
A module is a folder of Terraform files used as a unit. Every configuration is already one (the **root module**). Good modules make a team faster; bad ones add a layer of confusion.

@concept What a module is
@plain
A module is a directory of `.tf` files that takes inputs (variables), creates resources, and returns outputs. You call it from another configuration with a `module` block.
@problem
Without modules, every team copies and pastes the same 200 lines of VPC code and fixes bugs in only some of the copies.
@does
- The **root module** is the directory where you run Terraform. Modules it calls are **child modules**.
- A call looks like `module "network" { source = "./modules/network" ... }`.
- Resources inside get addresses prefixed with `module.network.`.
- Each module call is a separate instance with its own inputs.
@diagram flow
caption: Root calls child modules
nodes:
  - "Root module|environments/prod|cp"
  - "module network|VPC and subnets|app"
  - "module eks|cluster|app"
  - "module rds|database|app"
@h Calling a module
```hcl title="main.tf"
module "network" {
  source = "./modules/network"

  name       = "shop-prod"
  cidr_block = "10.0.0.0/16"
}

output "vpc_id" {
  value = module.network.vpc_id
}
```
@end

@concept Standard module layout
@plain
By convention a module has `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf` and a `README.md`, plus an `examples/` folder and `tests/`.
@problem
When every module is laid out differently, people cannot find things, and registries and documentation tools cannot parse them.
@does
- Required providers and versions go in `versions.tf`, but **no `provider` blocks** in reusable modules (the caller configures them).
- Every variable has a `type` and `description`; every output has a `description`.
- `examples/` contains runnable calls that double as documentation and test fixtures.
- `terraform-docs` generates the input and output tables for the README.
@diagram layers
caption: Files in a well-formed module
layers:
  - {label: "Interface", nodes: ["variables.tf|inputs|app", "outputs.tf|results|ok"]}
  - {label: "Implementation", nodes: ["main.tf|resources|cp", "locals.tf|derived values|info", "versions.tf|requirements|plain"]}
  - {label: "Support", nodes: ["README.md|usage|plain", "examples/|runnable calls|env", "tests/|terraform test|env"]}
@h Layout on disk
```text title="modules/network" nocheck
modules/network/
  main.tf
  variables.tf
  outputs.tf
  versions.tf
  README.md
  examples/basic/main.tf
  tests/basic.tftest.hcl
```
```bash title="Generate docs" lab
terraform-docs markdown table modules/network > modules/network/README.md
```
@end

@concept Inputs: the module's interface
@plain
Variables are the public interface. Design them like a function signature: few, clearly named, typed and validated.
@problem
Modules with 80 pass-through arguments are as hard to use as the raw resources, and every change to the interface breaks callers.
@does
- Expose business concepts (`private_subnet_cidrs`, `enable_nat`), not every attribute of every resource.
- Give sensible defaults so the simple case needs few inputs.
- Use `object` types with `optional()` for grouped settings.
- Add validation to catch bad input early; prefer secure defaults such as encryption on.
@diagram cmp
caption: Good and poor interfaces
cards:
  - {h: "Good", kind: ok, items: ["8 to 15 typed inputs", "Secure defaults", "Validation messages"]}
  - {h: "Poor", kind: bad, items: ["Dozens of pass-through flags", "Untyped any maps", "No defaults"]}
@h Example
```hcl title="variables.tf"
variable "name" {
  type        = string
  description = "Name prefix for all resources"
}

variable "cidr_block" {
  type        = string
  description = "VPC CIDR range"
  default     = "10.0.0.0/16"

  validation {
    condition     = can(cidrnetmask(var.cidr_block))
    error_message = "cidr_block must be a valid IPv4 CIDR."
  }
}

variable "azs" {
  type        = list(string)
  description = "Availability zones to spread subnets over"
}

variable "single_nat_gateway" {
  type        = bool
  description = "Use one NAT gateway instead of one per zone"
  default     = false
}
```
@check
Why should reusable modules not contain provider blocks? || The caller must choose credentials, regions and aliases; embedded providers also block deleting the module cleanly.
@end

@concept Outputs: what a module returns
@plain
Outputs are the only values a caller can read from a module. Return IDs, ARNs and endpoints that other code needs.
@problem
If a module returns nothing useful, callers must look up resources with data sources or copy IDs, undoing the benefit of reuse.
@does
- Return whole objects sparingly; stable, small outputs are easier to keep backward compatible.
- Output lists of IDs for things made with `count` or `for_each`.
- Mark sensitive outputs.
- Changing or removing an output is a breaking change for callers.
@diagram flow
caption: Inside values leave through outputs
nodes:
  - "aws_subnet.private|inside the module|app"
  - "output private_subnet_ids|public contract|cp"
  - "module.network.private_subnet_ids|caller reads|ok"
@h Example
```hcl title="outputs.tf"
output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "IDs of private subnets in AZ order"
  value       = [for k in sort(keys(aws_subnet.private)) : aws_subnet.private[k].id]
}
```
@end

@concept What belongs in a module
@plain
A module should represent one meaningful building block: a VPC, a database with its subnet group and security group, a cluster. It should be larger than one resource and smaller than a whole platform.
@problem
Modules that wrap a single resource add indirection without value. Modules that do everything cannot be reused or tested.
@does
- Good cohesion: resources that are created, changed and destroyed together.
- Avoid **thin wrappers** that only rename arguments of one resource.
- Avoid **god modules** that create network, cluster, database and DNS in one call.
- Rule of thumb: if you cannot describe the module in one sentence, split it.
@diagram cmp
caption: Size of a module
cards:
  - {h: "Too small", kind: warn, items: ["Wraps one resource", "Same arguments again"]}
  - {h: "Right size", kind: ok, items: ["One building block", "Clear inputs and outputs"]}
  - {h: "Too large", kind: bad, items: ["Whole platform in one call", "Cannot test or reuse parts"]}
@check
Give a good name and one sentence for a module. || network: creates a VPC with public and private subnets, route tables and NAT gateways.
@end

@concept Composition over nesting
@plain
Prefer a flat set of small modules that the root wires together to modules that call other modules several levels deep.
@problem
Deeply nested modules hide what is created, make provider passing painful and produce long addresses that are hard to refactor.
@does
- The root module passes outputs of one module as inputs to another: `vpc_id = module.network.vpc_id`.
- Keep nesting to one level where possible.
- Modules take dependencies as inputs (an ID) rather than creating or looking them up internally. This is **dependency inversion** for infrastructure.
@diagram flow
caption: Flat composition in the root
nodes:
  - "network|outputs vpc and subnets|app"
  - "eks|takes subnet ids|app"
  - "rds|takes vpc and subnet ids|app"
  - "Root|wires them together|cp"
@h Wiring modules
```hcl title="root main.tf"
module "network" {
  source = "./modules/network"
  name   = "shop-prod"
  azs    = ["eu-west-1a", "eu-west-1b"]
}

module "database" {
  source             = "./modules/database"
  name               = "shop-prod"
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids
}
```
@end

@concept Passing providers and count/for_each on modules
@plain
Modules can be repeated with `for_each` or `count`, and can receive non-default providers through a `providers` map.
@problem
You may need one module instance per team or per region, or a module that works in a second account.
@does
- `module "team" { for_each = var.teams ... }` creates one instance per key; access with `module.team["a"]`.
- `providers = { aws = aws.dr }` passes an aliased provider to the child.
- Modules with their own provider configuration cannot be used with `for_each`, another reason to keep providers in the root.
- Declare `configuration_aliases` in the child's `required_providers` when it needs more than one.
@diagram flow
caption: One module, many instances
nodes:
  - "var.teams|map of settings|plain"
  - "module team for_each|one per key|cp"
  - "Per-team resources|separate addresses|ok"
@h Example
```hcl title="for_each on a module"
variable "teams" {
  type = map(object({ cidr = string }))
}

module "team_vpc" {
  source   = "./modules/network"
  for_each = var.teams

  name       = "team-${each.key}"
  cidr_block = each.value.cidr
  azs        = ["eu-west-1a", "eu-west-1b"]
}
```
@end

@concept Anti-patterns to avoid
@plain
Some module habits look neat and cause pain later.
@problem
Teams hit these repeatedly: broken callers, giant plans, and impossible upgrades.
@does
- **Hidden provider config** inside modules.
- **Boolean explosion**: dozens of `enable_x` flags create combinations nobody tests.
- **Wrapping the community module** only to rename its inputs.
- **Hard-coded names** that prevent two instances in one account.
- **Reading remote state** inside a module, which couples it to a layout.
- **No versioning**: all callers use `main` and break together.
@diagram cmp
caption: Replace the habit
cards:
  - {h: "Hard-coded names", kind: bad, items: ["Second instance collides", "Use a name input"]}
  - {h: "Many boolean flags", kind: bad, items: ["Untested combinations", "Split into two modules"]}
  - {h: "Unversioned source", kind: bad, items: ["Surprise breakage", "Pin a tag"]}
  - {h: "Inputs for dependencies", kind: ok, items: ["Pass IDs in", "Easy to test and reuse"]}
@check
How do you let two instances of a module coexist? || Take a name or prefix input and use it in resource names and tags.
@end
