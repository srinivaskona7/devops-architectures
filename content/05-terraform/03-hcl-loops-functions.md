---
title: HCL expressions, loops and functions
minutes: 50
objectives:
  - Create many resources with count and for_each and know which to prefer
  - Transform data with for expressions, splats and built-in functions
  - Generate repeated nested blocks with dynamic blocks and write safe conditionals
---
Infrastructure is repetitive: three subnets, ten security group rules, five buckets. HCL has expressions to avoid copy and paste while keeping plans readable.

@concept References and string templates
@plain
An expression is anything that produces a value: a literal, a reference like `aws_vpc.main.id`, a function call, or a template such as `"${var.name}-db"`.
@problem
You need values from one resource inside another, and names built from parts.
@does
- Prefixes: `var.`, `local.`, `module.`, `data.` and a resource type for resources.
- `"${...}"` inserts a value into a string; `%{ if ... }` adds directives in templates.
- Attribute access with a dot and indexing with brackets: `aws_subnet.private[0].id`.
- Unknown values (not available until apply) show as `(known after apply)`.
@diagram flow
caption: A reference is also a dependency
nodes:
  - "aws_vpc.main|resource|app"
  - ".id|attribute reference|info"
  - "aws_subnet.a|uses it|cp"
  - "Order|VPC first, then subnet|ok"
@h Examples
```hcl title="References"
resource "aws_subnet" "a" {
  vpc_id     = aws_vpc.main.id
  cidr_block = "10.0.1.0/24"

  tags = {
    Name = "${local.name}-private-a"
  }
}
```
@end

@concept Conditionals
@plain
The ternary expression `condition ? true_value : false_value` chooses between two values. Combined with `count`, it can switch a resource on or off.
@problem
Some resources only exist in some environments, for example a NAT gateway per zone in production but a single one in dev.
@does
- The two result values must be of compatible types.
- `count = var.enabled ? 1 : 0` creates zero or one copy of a resource.
- Refer to an optional resource safely with `one(aws_x.y[*].id)` or `try(aws_x.y[0].id, null)`.
- Keep conditions simple. If a module is full of them, split it in two.
@diagram flow
caption: A flag toggles a resource
nodes:
  - "var.enable_nat|true or false|plain"
  - "count expression|1 or 0|cp"
  - "Resource|created or skipped|ok"
@h Switching a resource
```hcl title="nat.tf"
resource "aws_eip" "nat" {
  count  = var.enable_nat ? 1 : 0
  domain = "vpc"
}

output "nat_ip" {
  value = one(aws_eip.nat[*].public_ip)
}
```
@end

@concept count
@plain
`count = N` creates N copies of a resource, addressed as `resource.name[0]`, `[1]` and so on.
@problem
You need several identical resources without repeating the block.
@does
- `count.index` gives the position.
- Instances are tracked **by index**. Removing the first item of a list shifts the others, so Terraform plans to destroy and recreate resources after it.
- Good for "zero or one" toggles. Poor for lists of things that can change in the middle.
@diagram flow
caption: Removing item 0 shifts everything
nodes:
  - "[0] a|removed|bad"
  - "[1] b becomes [0]|replaced|warn"
  - "[2] c becomes [1]|replaced|warn"
@h Example and the trap
```hcl title="count example"
variable "names" {
  type    = list(string)
  default = ["a", "b", "c"]
}

resource "aws_s3_bucket" "logs" {
  count  = length(var.names)
  bucket = "acme-logs-${var.names[count.index]}"
}
```
:::warn
If `names` loses `"a"`, Terraform sees index 0 now holding "b" and plans to change or replace several buckets. Use `for_each` for lists that evolve.
:::
@check
When is count the right choice? || For a simple on/off toggle (0 or 1) or a fixed number of truly identical items.
@end

@concept for_each
@plain
`for_each` creates one instance per key of a map or per element of a set. Instances are addressed by key: `aws_s3_bucket.logs["audit"]`.
@problem
`count` identifies things by position, so edits in the middle cause churn. Keys are stable.
@does
- `each.key` and `each.value` are available inside the block.
- Removing one key only destroys that instance.
- Keys must be known at plan time (not derived from resource IDs not yet created).
- Convert a list with `toset(list)`, or build a map with a `for` expression.
@diagram cmp
caption: count versus for_each
cards:
  - {h: "count", kind: warn, items: ["Identified by index", "Middle removal reshuffles", "Best for 0 or 1"]}
  - {h: "for_each", kind: ok, items: ["Identified by key", "Stable under edits", "Best for collections"]}
@h Example
```hcl title="for_each over a map"
variable "buckets" {
  type = map(object({ versioning = bool }))
  default = {
    audit  = { versioning = true }
    assets = { versioning = false }
  }
}

resource "aws_s3_bucket" "this" {
  for_each = var.buckets
  bucket   = "acme-${each.key}"
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = { for k, v in var.buckets : k => v if v.versioning }
  bucket   = aws_s3_bucket.this[each.key].id

  versioning_configuration {
    status = "Enabled"
  }
}
```
@check
Why can for_each not use keys that depend on a resource's generated ID? || Keys must be known at plan time, and generated IDs are only known after apply.
@end

@concept For expressions and splats
@plain
A `for` expression transforms a list or map into a new list or map. A **splat** `[*]` is a short form to collect one attribute from every item.
@problem
Cloud inputs rarely match the shape of your data. You need to filter, reshape and extract.
@does
- `[for s in var.list : upper(s)]` builds a list; `{for k, v in var.map : k => v.id}` builds a map.
- An `if` clause filters: `[for s in var.list : s if s != ""]`.
- `aws_subnet.private[*].id` returns a list of all IDs when `count` is used. For `for_each` use `values(aws_subnet.private)[*].id`.
- `flatten`, `merge`, `zipmap`, `setproduct` combine and reshape collections.
@diagram flow
caption: Reshaping data
nodes:
  - "map of subnets|key to object|plain"
  - "for expression|filter and project|cp"
  - "list of IDs|for the cluster|ok"
@h Examples
```hcl title="for expressions"
locals {
  subnet_ids = [for s in aws_subnet.private : s.id]
  az_by_name = { for k, s in aws_subnet.private : k => s.availability_zone }
  prod_only  = [for e in var.envs : e if e == "prod"]
}
```
@end

@concept Dynamic blocks
@plain
A `dynamic` block generates repeated **nested blocks** (like several `ingress` rules) from a collection.
@problem
`for_each` works on whole resources. Many resources have inner blocks that repeat, and you cannot loop those with `for_each` on the resource.
@does
- Syntax: `dynamic "ingress" { for_each = ... content { ... } }`.
- Inside, use `ingress.value` and `ingress.key` (named after the block label).
- Overuse makes code unreadable. Prefer separate rule resources, such as `aws_vpc_security_group_ingress_rule`, when the provider offers them.
@diagram flow
caption: A list of rules becomes repeated blocks
nodes:
  - "var.rules|list of ports|plain"
  - "dynamic ingress|loops over rules|cp"
  - "ingress blocks|one per rule|ok"
@h Example
```hcl title="dynamic block"
variable "ports" {
  type    = list(number)
  default = [80, 443]
}

resource "aws_security_group" "web" {
  name   = "web"
  vpc_id = aws_vpc.main.id

  dynamic "ingress" {
    for_each = var.ports
    content {
      from_port   = ingress.value
      to_port     = ingress.value
      protocol    = "tcp"
      cidr_blocks = ["0.0.0.0/0"]
    }
  }
}
```
@end

@concept Built-in functions
@plain
Terraform has about a hundred built-in functions for strings, numbers, collections, files, networking and encoding. You cannot define your own.
@problem
Config often needs derived values such as subnet CIDRs, merged tags, or JSON policies.
@does
- Strings and collections: `format`, `join`, `split`, `lower`, `length`, `merge`, `lookup`, `coalesce`, `try`, `toset`.
- Network: `cidrsubnet(prefix, newbits, netnum)` carves subnets from a VPC range.
- Files: `file`, `templatefile`, `jsonencode`, `yamlencode`.
- Test any of them interactively with `terraform console`.
@diagram cmp
caption: Handy groups
cards:
  - {h: "Collections", kind: app, items: ["merge, lookup, flatten", "toset, zipmap, distinct"]}
  - {h: "Network", kind: info, items: ["cidrsubnet, cidrhost", "Carve subnets"]}
  - {h: "Encoding", kind: ok, items: ["jsonencode, yamlencode", "IAM policies without quoting pain"]}
  - {h: "Safety", kind: warn, items: ["try, can, coalesce", "Handle missing values"]}
@h Try them
```bash title="Console experiments" lab
echo 'cidrsubnet("10.0.0.0/16", 8, 2)' | terraform console
echo 'merge({a=1}, {b=2})' | terraform console
echo 'format("%s-%03d", "web", 7)' | terraform console
```
```hcl title="IAM policy via jsonencode"
locals {
  read_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject"]
      Resource = ["arn:aws:s3:::acme-assets/*"]
    }]
  })
}
```
@check
What does cidrsubnet("10.0.0.0/16", 8, 2) return? || 10.0.2.0/24, the third /24 inside the /16.
@end

@concept templatefile, optional attributes and try
@plain
`templatefile` renders a text file with variables, such as a user-data script or a config. `optional()` in object types makes fields skippable, and `try()` falls back when an expression fails.
@problem
Real inputs are messy: some fields are absent, and generated files need values substituted.
@does
- `templatefile("${path.module}/init.sh.tftpl", { cluster = var.name })` returns the rendered string.
- `optional(type, default)` inside `object({...})` supplies defaults and makes module interfaces friendlier.
- `try(a, b)` returns the first expression that evaluates without error.
- `path.module` is the directory of the current module; use it instead of relative paths.
@diagram flow
caption: Template plus values gives a file
nodes:
  - "init.sh.tftpl|template|plain"
  - "templatefile()|inject variables|cp"
  - "user_data|rendered text|ok"
@h Example
```hcl title="optional attributes"
variable "node_group" {
  type = object({
    instance_type = string
    min_size      = optional(number, 1)
    max_size      = optional(number, 3)
    labels        = optional(map(string), {})
  })
}

locals {
  user_data = templatefile("${path.module}/init.sh.tftpl", {
    cluster = "shop-prod"
  })
}
```
@end
