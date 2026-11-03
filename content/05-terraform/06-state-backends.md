---
title: State, remote backends and locking
minutes: 50
objectives:
  - Explain what the state file holds and why it must be shared and protected
  - Configure an S3 backend with native locking or DynamoDB locking
  - Choose between terraform_remote_state and data sources for sharing values
---
State is Terraform's memory. Losing it, corrupting it or letting two people write at once are the most common ways to hurt a team, so this section is worth reading slowly.

@concept What state is
@plain
The state is a JSON file that maps each resource in your code to the real object in the cloud, with all its attributes. By default it is `terraform.tfstate` in the working directory.
@problem
Terraform cannot find "the bucket I created last week" by name alone. It needs a record of what it owns, plus metadata like dependencies, to plan correctly and to delete in the right order.
@does
- Plan compares three things: your code, the state, and the refreshed real infrastructure.
- State holds every attribute, including passwords and keys, in plain text.
- Never edit the JSON by hand; use `terraform state` subcommands.
- Never commit it to Git.
@diagram flow
caption: State links code to reality
nodes:
  - "Configuration|desired|app"
  - "State|recorded|info"
  - "Real cloud|actual|ext"
  - "Plan|difference of the three|cp"
@h Looking at state
```bash title="Inspect without editing" lab
terraform state list
terraform state show aws_vpc.main
terraform show -json | head -c 600
```
@check
Why is state sensitive? || It stores all resource attributes, including secrets such as passwords, in readable form.
@end

@concept Why local state fails for teams
@plain
A local file on one laptop works for learning. For a team it breaks immediately.
@problem
If two engineers run apply from separate copies, each overwrites the other's record, resources are duplicated or orphaned, and CI cannot see anything.
@does
- No sharing: CI and teammates have no state.
- No locking: concurrent runs corrupt the picture.
- No history or encryption: a deleted laptop is a lost infrastructure map.
- Remote backends fix all of these.
@diagram cmp
caption: Local versus remote state
cards:
  - {h: "Local file", kind: bad, items: ["One machine only", "No lock, no history", "Secrets on disk"]}
  - {h: "Remote backend", kind: ok, items: ["Shared by team and CI", "Locking prevents races", "Versioned and encrypted"]}
@end

@concept The S3 backend
@plain
The S3 backend stores state as an object in an S3 bucket. It is the standard choice on AWS.
@problem
You want durable, encrypted, versioned shared storage that costs almost nothing and uses IAM for access control.
@does
- Enable **bucket versioning** so a bad state can be rolled back, plus encryption and Block Public Access.
- `key` is the object path, so one bucket serves many stacks: `prod/network/terraform.tfstate`.
- The backend block cannot use variables. Pass values with `-backend-config` or a partial configuration.
- The bucket must exist before `init`; create it once manually or with a small bootstrap stack.
@diagram flow
caption: A shared, versioned object
nodes:
  - "terraform apply|on laptop or CI|app"
  - "S3 bucket|versioned, encrypted|info"
  - "state object|prod/network/terraform.tfstate|ok"
@h Configuring it
```hcl title="backend.tf"
terraform {
  backend "s3" {
    bucket       = "acme-tfstate-111122223333"
    key          = "prod/network/terraform.tfstate"
    region       = "eu-west-1"
    encrypt      = true
    use_lockfile = true
  }
}
```
```bash title="Migrating and reconfiguring" lab
terraform init                       # first time
terraform init -migrate-state        # move existing local state to the backend
terraform init -reconfigure          # change backend settings without migrating
```
@end

@concept State locking: S3 native lock and DynamoDB
@plain
A **lock** makes a second run wait or fail while the first is writing. The S3 backend supports two ways to do this.
@problem
Two applies at the same moment can write conflicting state. Locking turns that into a clear "state is locked" error.
@does
- **Native S3 locking** (`use_lockfile = true`) writes a `.tflock` object next to the state using S3 conditional writes. It needs no extra table. It arrived in Terraform 1.10 and became the recommended method; check the current docs for your version.
- **DynamoDB locking** (`dynamodb_table = "..."`) uses a table with partition key `LockID`. It is the older method and is deprecated in the S3 backend; plan a migration.
- A crashed run can leave a lock; `terraform force-unlock <ID>` removes it. Only do so when you are sure nobody is running.
- `-lock-timeout=5m` makes a run wait instead of failing.
@diagram seq
caption: Second apply waits on the lock
actors: ["Run A|CI job|app", "S3|state and lock|info", "Run B|laptop|app"]
steps:
  - "0>1: create .tflock | req"
  - "1>0: lock acquired | resp"
  - "2>1: create .tflock | req"
  - "1>2: already exists | bad"
  - "0>1: write state, delete lock | req"
@h DynamoDB variant for older versions
```hcl title="backend.tf (legacy locking)"
terraform {
  backend "s3" {
    bucket         = "acme-tfstate-111122223333"
    key            = "prod/network/terraform.tfstate"
    region         = "eu-west-1"
    encrypt        = true
    dynamodb_table = "acme-tflock"
  }
}
```
:::warn
Do not enable both methods during migration longer than necessary, and test the permission set. Native locking needs `s3:PutObject` and `s3:DeleteObject` on the `.tflock` object too.
:::
@check
What does force-unlock do? || Removes a stuck lock; use it only when no run is active, since it allows concurrent writes.
@end

@concept Bootstrapping the backend
@plain
The bucket for state must exist before a stack can use it. This is the classic chicken-and-egg problem.
@problem
You cannot store state in a bucket that Terraform itself has not yet created.
@does
- Create the bucket once with a small stack that uses local state, then migrate it into its own bucket with `init -migrate-state`; or create it with the CLI or CloudFormation.
- Set `prevent_destroy` on the bucket.
- Give state a dedicated account or at least tight IAM so only pipelines and a few admins can read it.
- Keep the bootstrap code in the repo and document it.
@diagram flow
caption: Bootstrap order
numbered: true
nodes:
  - "Local state|temporary|plain"
  - "Create bucket|versioned, encrypted|app"
  - "Add backend block|point to bucket|info"
  - "init -migrate-state|state moves in|ok"
@h Bootstrap stack
```hcl title="bootstrap/main.tf"
resource "aws_s3_bucket" "state" {
  bucket = "acme-tfstate-111122223333"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```
@end

@concept Partial backend configuration
@plain
The backend block cannot read variables. A **partial configuration** leaves values out and supplies them at `init` time.
@problem
The same code is used for dev, stage and prod, but each needs a different state key or bucket.
@does
- Put fixed values in `backend.tf` and the rest in a file such as `prod.s3.tfbackend`.
- Call `terraform init -backend-config=prod.s3.tfbackend`.
- Individual values: `-backend-config="key=prod/app.tfstate"`.
- Never put credentials in these files; use the environment.
@diagram flow
caption: Same code, different state location
nodes:
  - "backend.tf|bucket only|app"
  - "prod.s3.tfbackend|key and region|info"
  - "terraform init|merges both|cp"
  - "Prod state|separate object|ok"
@h Example
```hcl title="prod.s3.tfbackend" nocheck
bucket       = "acme-tfstate-111122223333"
key          = "prod/app/terraform.tfstate"
region       = "eu-west-1"
use_lockfile = true
```
```bash title="Init per environment" lab
terraform init -backend-config=prod.s3.tfbackend -reconfigure
```
@end

@concept Sharing outputs: remote state versus data sources
@plain
One stack often needs values from another, such as the VPC ID from the network stack. The two ways are reading its state with `terraform_remote_state`, or looking it up from the cloud with a normal data source.
@problem
Copying IDs by hand goes stale. But reading another stack's whole state gives the reader access to all its secrets.
@does
- `terraform_remote_state` reads only **outputs** of the other state, but needs read access to the whole state object.
- A data source (for example `aws_vpc` by tag) asks the cloud API and needs only normal read permissions; it also decouples stacks from each other's backend layout.
- Other options: publish values in SSM Parameter Store or a similar registry and read them with `aws_ssm_parameter`.
- Prefer data sources or a parameter store across team boundaries.
@diagram cmp
caption: Three ways to share a VPC ID
cards:
  - {h: "terraform_remote_state", kind: warn, items: ["Easy, reads outputs", "Needs read on whole state", "Couples stacks to backend"]}
  - {h: "Data source by tag", kind: ok, items: ["Uses normal cloud read", "Loose coupling", "Needs consistent tags"]}
  - {h: "SSM parameter", kind: ok, items: ["Explicit published contract", "Works across tools"]}
@h Example
```hcl title="remote state read"
data "terraform_remote_state" "network" {
  backend = "s3"

  config = {
    bucket = "acme-tfstate-111122223333"
    key    = "prod/network/terraform.tfstate"
    region = "eu-west-1"
  }
}

locals {
  vpc_id = data.terraform_remote_state.network.outputs.vpc_id
}
```
@check
What is the security downside of terraform_remote_state? || The reader needs permission to read the entire state object, which can contain secrets.
@end

@concept Protecting state
@plain
State is a secret store and the source of truth, so protect it like a production database.
@problem
Anyone who can write state can make Terraform delete or recreate things; anyone who can read it sees passwords.
@does
- Encrypt at rest (SSE-KMS) and in transit; restrict the bucket policy to the pipeline role and a break-glass admin role.
- Enable versioning and consider MFA delete or object lock for the state account.
- Avoid putting secrets in resources at all, so state holds fewer of them.
- Split state per stack and environment to limit blast radius, and keep a restore procedure: list versions, copy back an earlier one.
@diagram layers
caption: Layers of protection
layers:
  - {label: "Access", nodes: ["IAM least privilege|pipeline and break-glass only|cp", "Separate account|state not beside workloads|cp"]}
  - {label: "Data", nodes: ["KMS encryption|at rest|ok", "Versioning|rollback|ok"]}
  - {label: "Process", nodes: ["Locking|no concurrent writes|info", "Small stacks|limited blast radius|info"]}
@h Restoring an earlier version
```bash title="Roll state back" lab
aws s3api list-object-versions --bucket acme-tfstate-111122223333 --prefix prod/network/terraform.tfstate --max-items 5
aws s3api get-object --bucket acme-tfstate-111122223333 --key prod/network/terraform.tfstate --version-id <VERSION_ID> restored.tfstate
```
:::warn
Take a copy of the current state first and make sure no one is applying before restoring.
:::
@end
