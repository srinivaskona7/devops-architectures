---
title: Data sources, lifecycle rules and provisioners
minutes: 45
objectives:
  - Read existing infrastructure with data sources without managing it
  - Protect critical resources with lifecycle rules and checks
  - Explain why provisioners are a last resort and name the better alternatives
---
Not everything is created by your code. Data sources read what exists, lifecycle rules change how Terraform treats a resource, and provisioners are an escape hatch to avoid.

@concept Data sources
@plain
A `data` block reads information from the provider without creating anything: the latest AMI, an existing VPC, the current account ID, a Route 53 zone.
@problem
Infrastructure is shared. Your stack needs facts about things that another team or an earlier stack created, without copying IDs into code.
@does
- Evaluated during plan when arguments are known; otherwise deferred to apply.
- Referenced as `data.aws_vpc.shared.id`.
- Read-only: removing the block does not delete anything.
- Failed lookups (zero or two matches) produce an error, which is useful as a safety check.
@diagram flow
caption: Read, do not manage
nodes:
  - "Existing VPC|created by network team|ext"
  - "data aws_vpc|lookup by tag|info"
  - "Your resources|use vpc id|ok"
@h Common lookups
```hcl title="data.tf"
data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

data "aws_vpc" "shared" {
  tags = {
    Name = "shared-prod"
  }
}

data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

output "account_id" {
  value = data.aws_caller_identity.current.account_id
}
```
@check
Does deleting a data block delete the real object? || No. Data sources only read; they never create or destroy.
@end

@concept The lifecycle block
@plain
`lifecycle` changes the default behaviour of one resource: block deletion, create the replacement first, or ignore some changes.
@problem
Default behaviour is unsafe for certain resources. Replacing a database destroys data; replacing a load balancer in the wrong order causes downtime; autoscaling changes a count that Terraform keeps reverting.
@does
- `prevent_destroy = true` makes any plan that would destroy it fail.
- `create_before_destroy = true` builds the new one, then deletes the old.
- `ignore_changes = [attr]` stops Terraform diffing attributes changed by something else.
- `replace_triggered_by` forces replacement when another resource changes.
- Lifecycle arguments must be literal values, not variables.
@diagram cmp
caption: Four common lifecycle controls
cards:
  - {h: "prevent_destroy", kind: bad, items: ["Plan fails if destroy needed", "Databases, state buckets"]}
  - {h: "create_before_destroy", kind: ok, items: ["New first, then old", "Avoids downtime"]}
  - {h: "ignore_changes", kind: warn, items: ["Skip drift on listed attributes", "desired_count with autoscaling"]}
  - {h: "replace_triggered_by", kind: info, items: ["Replace when other thing changes", "Rotate with config"]}
@h Example
```hcl title="lifecycle.tf"
resource "aws_db_instance" "main" {
  identifier     = "shop-prod"
  engine         = "postgres"
  instance_class = "db.t4g.medium"

  allocated_storage           = 50
  username                    = "shopadmin"
  manage_master_user_password = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "shop-prod-final"

  lifecycle {
    prevent_destroy = true
    ignore_changes  = [allocated_storage]
  }
}
```
:::note
`prevent_destroy` only protects against Terraform. Someone deleting the resource in the console, or removing the whole block from code, still removes it (the latter fails only while the block remains).
:::
@end

@concept Preconditions, postconditions and check blocks
@plain
These are assertions in code. A `precondition` tests an assumption before a resource is created, a `postcondition` tests the result afterwards, and a `check` block runs independent health assertions.
@problem
Silent wrong assumptions, such as picking an AMI of the wrong architecture, show up later as confusing failures.
@does
- `precondition` and `postcondition` live inside `lifecycle`, and fail the run with your message.
- `check "name" { assert { ... } }` produces warnings, not errors, and can contain a scoped data source such as an HTTP probe.
- Variable `validation` checks inputs; these check the world.
@diagram flow
caption: Assert around a resource
nodes:
  - "precondition|before create|info"
  - "Resource|created or read|app"
  - "postcondition|after create|info"
  - "check block|continuous warning|warn"
@h Example
```hcl title="assertions.tf"
data "aws_ami" "app" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  lifecycle {
    postcondition {
      condition     = self.architecture == "x86_64"
      error_message = "The AMI must be x86_64."
    }
  }
}

check "site_up" {
  data "http" "home" {
    url = "https://shop.example.com/healthz"
  }

  assert {
    condition     = data.http.home.status_code == 200
    error_message = "Health endpoint did not return 200."
  }
}
```
@end

@concept Tainting and forced replacement
@plain
Sometimes a resource is broken and you want Terraform to recreate it. You can ask for replacement of one address on the next apply.
@problem
Deleting by hand in the console leaves state confused, and the old `terraform taint` command mutated state before anyone reviewed the plan.
@does
- `terraform apply -replace="aws_instance.web"` plans a destroy-and-create of that resource and shows it for approval.
- `terraform taint` still exists but is deprecated in favour of `-replace`.
- Works with indexed addresses such as `aws_instance.web["a"]`.
@diagram flow
caption: Replace as part of a normal plan
nodes:
  - "plan -replace=addr|marks one resource|app"
  - "Review|sees -/+ for it|info"
  - "Apply|destroy then create|ok"
@h Usage
```bash title="Replace one resource" lab
terraform plan  -replace="aws_instance.web"
terraform apply -replace="aws_instance.web"
```
@check
Why is -replace better than taint? || It is part of a normal reviewed plan instead of editing state immediately.
@end

@concept The null_resource, terraform_data and external data
@plain
`terraform_data` is a built-in resource that holds a value and can trigger actions; it replaces the older `null_resource` from the `null` provider. The `external` data source runs a script and reads JSON.
@problem
Occasionally you need to re-run something when an input changes, or fetch a value no provider offers.
@does
- `terraform_data` with `triggers_replace` re-creates itself when inputs change, so other resources can use `replace_triggered_by`.
- `external` data runs on every plan, so it must be fast, free of side effects and deterministic.
- Both create hidden dependencies on local tools being installed on whoever runs Terraform.
@diagram flow
caption: A trigger without a real resource
nodes:
  - "Input changes|image tag, config hash|plain"
  - "terraform_data|triggers_replace|cp"
  - "Dependent resource|replaced|ok"
@h Example
```hcl title="terraform_data"
resource "terraform_data" "config_version" {
  triggers_replace = [var.config_hash]
}

resource "aws_instance" "web" {
  ami           = var.ami_id
  instance_type = "t3.small"

  lifecycle {
    replace_triggered_by = [terraform_data.config_version]
  }
}
```
@end

@concept Provisioners and why to avoid them
@plain
Provisioners (`local-exec`, `remote-exec`, `file`) run scripts after a resource is created. HashiCorp documents them as a last resort.
@problem
People use them to configure servers or call APIs when no resource exists. But Terraform cannot model what a script does.
@does
- Not tracked in the plan: you cannot see what they will do, and they do not run again unless the resource is recreated.
- A failed provisioner marks the resource **tainted**, forcing recreation next time.
- They need network access (SSH) from the machine running Terraform and credentials in code.
- `when = destroy` provisioners fail destroy runs when the script breaks.
- Better options: AMI baking with Packer, `user_data` or cloud-init, EKS add-ons and Helm releases, configuration tools, or a dedicated provider.
@diagram cmp
caption: Replace provisioners with something visible
cards:
  - {h: "Provisioner", kind: bad, items: ["Hidden from plan", "Fails leave tainted resources", "Needs SSH from runner"]}
  - {h: "user_data / cloud-init", kind: ok, items: ["Runs at first boot", "Part of the resource definition"]}
  - {h: "Packer image", kind: ok, items: ["Configure at build time", "Immutable and testable"]}
  - {h: "Provider or Helm", kind: ok, items: ["Modelled in state", "Shows in plan"]}
@h If you must
```hcl title="local-exec as a last resort"
resource "terraform_data" "notify" {
  triggers_replace = [aws_ecr_repository.shop.arn]

  provisioner "local-exec" {
    command = "echo created ${aws_ecr_repository.shop.name} >> changes.log"
  }
}
```
:::warn
If you find yourself writing `remote-exec` to install software, stop: use an image or user data.
:::
@check
Name two reasons provisioners are discouraged. || They are invisible in plans and cause tainted resources when they fail; they also require access and tooling on the runner.
@end
