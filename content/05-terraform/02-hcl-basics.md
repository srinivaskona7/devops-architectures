---
title: HCL basics, types and variables
minutes: 45
objectives:
  - Read and write HCL blocks, arguments and references
  - Choose the right type for a variable and validate its value
  - Use locals and outputs, and keep sensitive values out of logs
---
**HCL** (HashiCorp Configuration Language) is the language of Terraform files. It is declarative and small: blocks, arguments and expressions. Learning its few building blocks well makes every module readable.

@concept Blocks, arguments and files
@plain
HCL is made of **blocks** (`resource "aws_vpc" "main" { ... }`) that contain **arguments** (`cidr_block = "10.0.0.0/16"`). A block has a type, optional labels, and a body.
@problem
Without a clear structure, large configurations become unreadable. HCL gives a uniform shape so every resource, variable and output looks alike.
@does
- Terraform loads every `*.tf` file in a directory as one configuration; file names are only a convention.
- Common blocks are `terraform`, `provider`, `resource`, `data`, `variable`, `output`, `locals` and `module`.
- Comments use `#`, `//` or `/* */`.
- Common layout: `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`.
@diagram layers
caption: One directory, one configuration
layers:
  - {label: "Inputs", nodes: ["variables.tf|variable blocks|app", "terraform.tfvars|values|env"]}
  - {label: "Logic", nodes: ["main.tf|resources and data|cp", "locals.tf|computed names|info"]}
  - {label: "Outputs", nodes: ["outputs.tf|values for others|ok", "versions.tf|providers and version|plain"]}
@h Anatomy of a resource
```hcl title="main.tf"
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_hostnames = true

  tags = {
    Name = "shop-prod"
  }
}
```
:::note
The first label is the resource type (decided by the provider), the second is a local name. The address `aws_vpc.main` is how other code refers to it.
:::
@end

@concept Primitive types
@plain
Every value has a type. The simple ones are `string`, `number` and `bool`.
@problem
Cloud APIs are strict. A port passed as a string or a flag spelled "yes" causes confusing errors. Types catch mistakes early.
@does
- Strings use double quotes; `"${var.name}-db"` interpolates a value.
- Numbers can be integers or decimals; Terraform converts between string and number where it can.
- Booleans are `true` and `false` (no quotes).
- `null` means "no value", and tells a provider to use its default for that argument.
@diagram cmp
caption: Primitive values
cards:
  - {h: "string", kind: app, items: ["\"eu-west-1\"", "Heredoc for multi-line"]}
  - {h: "number", kind: info, items: ["5432, 0.5", "Strings like \"5\" convert"]}
  - {h: "bool", kind: ok, items: ["true or false", "Not \"true\" in quotes"]}
  - {h: "null", kind: warn, items: ["Absent value", "Use provider default"]}
@h Examples
```hcl title="Primitive values in locals"
locals {
  region   = "eu-west-1"
  port     = 5432
  multi_az = true
  note     = null
  banner   = <<-EOT
    Managed by Terraform.
    Do not edit in the console.
  EOT
}
```
@end

@concept Collection and structural types
@plain
Collections hold many values: `list(...)` is ordered, `set(...)` is unordered and unique, `map(...)` is key to value pairs of one type. **Structural** types, `object({...})` and `tuple([...])`, mix types.
@problem
Real configuration has shapes such as "a list of subnet definitions, each with a CIDR and a zone". You need a way to describe that shape so Terraform can check it.
@does
- `list(string)` is written `["a", "b"]`; index with `list[0]`.
- `map(string)` is written `{ env = "prod" }`; index with `map["env"]`.
- `set(string)` removes duplicates and has no index. `for_each` requires a set or map.
- `object({ name = string, size = number })` fixes the keys and the type of each.
- `any` accepts anything, but loses validation, so use sparingly.
@diagram cmp
caption: Which collection to use
cards:
  - {h: "list", kind: app, items: ["Ordered, can repeat", "Access by position"]}
  - {h: "set", kind: info, items: ["Unique, unordered", "Good for for_each"]}
  - {h: "map", kind: ok, items: ["Key to value, one type", "Tags, settings"]}
  - {h: "object", kind: cp, items: ["Named fields, mixed types", "Structured settings"]}
@h A typed variable
```hcl title="variables.tf"
variable "subnets" {
  description = "Private subnets to create"
  type = list(object({
    name = string
    cidr = string
    az   = string
  }))
  default = [
    { name = "a", cidr = "10.0.1.0/24", az = "eu-west-1a" },
    { name = "b", cidr = "10.0.2.0/24", az = "eu-west-1b" },
  ]
}
```
@check
Which type does `for_each` accept? || A map or a set of strings (a list must be converted with toset).
@end

@concept Input variables and ways to set them
@plain
Variables are the parameters of a configuration or module. You declare them with `variable` blocks and provide values from outside.
@problem
Hard-coded values force you to copy code per environment. Variables let one codebase serve many.
@does
- Precedence from lowest to highest: default, environment `TF_VAR_name`, `terraform.tfvars`, `*.auto.tfvars`, then `-var-file` and `-var` on the command line (later ones win).
- A variable without a default is required; Terraform prompts or fails in non-interactive mode.
- `description` is documentation shown by tools; always set it.
- Variables cannot be changed during a run; use `locals` for computed values.
@diagram flow
caption: Later sources override earlier ones
nodes:
  - "default|in variable block|plain"
  - "TF_VAR_name|environment|info"
  - "terraform.tfvars|file|app"
  - "-var-file and -var|command line, wins|ok"
@h Providing values
```hcl title="prod.tfvars"
environment    = "prod"
instance_count = 3
```
```bash title="Using them" lab
terraform plan -var-file=prod.tfvars
terraform plan -var 'instance_count=5'
TF_VAR_environment=dev terraform plan
```
@end

@concept Validating variables
@plain
A `validation` block rejects bad input with your own message, before any plan is made.
@problem
A typo such as `environment = "porduction"` would create misnamed resources or fail deep inside a cloud call with a vague error.
@does
- `condition` is an expression that must be true; `error_message` explains the rule.
- You can use any function, such as `contains`, `regex`, `can` and `length`.
- Since Terraform 1.9 a validation may refer to other variables. Check the current docs for your version.
- `precondition` and `postcondition` blocks (in `lifecycle`) check assumptions about resources and data sources.
@diagram flow
caption: Fail early with a clear message
nodes:
  - "Value supplied|var.environment|plain"
  - "validation|condition is checked|cp"
  - "Pass|plan continues|ok"
  - "Fail|clear error message|bad"
@h Validation examples
```hcl title="variables.tf"
variable "environment" {
  type        = string
  description = "Deployment environment"

  validation {
    condition     = contains(["dev", "stage", "prod"], var.environment)
    error_message = "environment must be dev, stage or prod."
  }
}

variable "cidr" {
  type = string

  validation {
    condition     = can(cidrhost(var.cidr, 0))
    error_message = "cidr must be a valid CIDR block."
  }
}
```
@check
What does `can()` do? || It returns true if the expression evaluates without an error, which makes it handy in validations.
@end

@concept Locals and outputs
@plain
**Locals** are named expressions inside a module, like variables in a function body. **Outputs** are values a module or root configuration exposes to the outside.
@problem
Repeating `"${var.project}-${var.environment}"` in fifty places invites mistakes. And other configurations need IDs such as a VPC ID without looking in the console.
@does
- `locals { name = "..." }` is referenced as `local.name` (singular).
- Outputs are printed after apply and are readable with `terraform output`.
- In modules, outputs are the only way the caller sees inside values: `module.network.vpc_id`.
- Mark an output `sensitive = true` to hide it in the CLI output.
@diagram flow
caption: Compute once, reuse and expose
nodes:
  - "variables|inputs|app"
  - "locals|names, tags, derived values|info"
  - "resources|use local.x|cp"
  - "outputs|IDs and endpoints|ok"
@h Example
```hcl title="locals.tf and outputs.tf"
locals {
  name = "${var.project}-${var.environment}"
  tags = {
    Project     = var.project
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}
```
@end

@concept Sensitive values
@plain
Marking a variable or output `sensitive = true` hides its value from plan and apply output and from logs.
@problem
Passwords and tokens in CI logs are a common leak.
@does
- The value is redacted in the CLI as `(sensitive value)`.
- It is **still stored in plain text in the state file**, and any output derived from it must also be marked sensitive.
- Better: never let Terraform know the secret. Let the service generate it (for example RDS `manage_master_user_password`, which stores it in Secrets Manager).
- Ephemeral values and write-only arguments exist in recent Terraform and provider versions; check the current docs before relying on them.
@diagram cmp
caption: Hidden in the log, not hidden in state
cards:
  - {h: "sensitive = true", kind: ok, items: ["Redacted in plan and output", "Safe in CI logs"]}
  - {h: "State file", kind: bad, items: ["Value still stored in clear text", "Encrypt and restrict the bucket"]}
  - {h: "Best practice", kind: info, items: ["Avoid passing secrets at all", "Use managed secrets and IAM auth"]}
@h Declaring one
```hcl title="variables.tf"
variable "api_token" {
  type      = string
  sensitive = true
}

output "db_endpoint" {
  value = aws_db_instance.main.address
}
```
:::danger
Never commit `terraform.tfvars` containing secrets, and treat the state file like a credential store.
:::
@end
