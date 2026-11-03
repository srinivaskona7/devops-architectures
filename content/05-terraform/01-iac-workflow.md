---
title: Infrastructure as code and the Terraform workflow
minutes: 45
objectives:
  - Explain why infrastructure is described in files and reviewed like application code
  - Run the init, plan, apply and destroy cycle and read a plan correctly
  - Pin Terraform and understand how the dependency graph orders changes
---
Clicking through a console is fast once and impossible to repeat, review or audit. **Infrastructure as code (IaC)** moves that knowledge into text files so that VPCs, clusters and databases are created the same way every time. Terraform is the most widely used tool for this.

@concept What infrastructure as code means
@plain
You write files that describe the infrastructure you want. A tool reads them, compares them with what exists, and makes the real world match. The files live in Git, so every change has an author, a review and a history.
@problem
Hand-built environments drift apart. Nobody remembers which checkbox made staging differ from production, a lost engineer takes the knowledge with them, and rebuilding after a disaster takes weeks.
@does
- Gives a reviewable pull request for every infrastructure change.
- Makes environments reproducible: the same code can build dev, staging and production.
- Acts as documentation that cannot go stale, because it is what actually runs.
- Enables automation, such as a pipeline that plans on every pull request.
@diagram flow
caption: From a text file to real infrastructure
numbered: true
nodes:
  - "Code|.tf files in Git|app"
  - "Review|pull request and plan|info"
  - "Tool|Terraform compares and acts|cp"
  - "Cloud API|AWS, Azure, GCP|ext"
  - "Real resources|VPC, EKS, RDS|ok"
@check
Why is a pull request for infrastructure better than a console change? || It gives review, history, and a repeatable result instead of an undocumented one-off action.
@end

@concept Declarative versus imperative
@plain
An imperative script says how to do things step by step: create this, then attach that. A declarative file says what the end result must be, and the tool works out the steps.
@problem
Imperative scripts break when run twice or from a different starting point: "create bucket" fails if the bucket exists. Engineers end up writing endless existence checks.
@does
- Terraform is declarative: you state that a bucket named X with versioning exists.
- It computes the difference between desired and actual state and only performs the needed actions.
- Running it again with no change does nothing. This property is called **idempotence**.
- The trade-off is that some procedural tasks (ordered, one-off migrations) fit badly and need other tools.
@diagram cmp
caption: Two ways to get a bucket
cards:
  - {h: "Imperative script", kind: warn, items: ["aws s3 mb then aws s3api put-bucket-versioning", "Fails or duplicates on re-run", "You handle ordering and checks"]}
  - {h: "Declarative Terraform", kind: ok, items: ["Describe the final bucket", "Re-run is safe and shows no change", "Tool plans the minimum steps"]}
@h The same intent in HCL
```hcl title="main.tf"
resource "aws_s3_bucket" "logs" {
  bucket = "acme-prod-logs-eu-west-1"
}

resource "aws_s3_bucket_versioning" "logs" {
  bucket = aws_s3_bucket.logs.id

  versioning_configuration {
    status = "Enabled"
  }
}
```
@end

@concept Terraform in the tool landscape
@plain
Terraform is one of several IaC tools. Some are cloud specific, some use general programming languages, and some run inside Kubernetes.
@problem
Choosing a tool by habit leads to rewrites later. You need to know what each is good at.
@does
- **Terraform and OpenTofu**: one language (HCL) and thousands of providers, so one workflow covers AWS, Azure, GCP, Kubernetes and SaaS.
- **CloudFormation, ARM/Bicep, Deployment Manager**: native to one cloud, with deep coverage but no cross-cloud reuse.
- **Pulumi and AWS CDK**: general languages such as TypeScript or Python; powerful loops and tests, but more room for complex code.
- **Crossplane**: manages cloud resources through Kubernetes custom resources, useful when the cluster is already your control plane.
- **Ansible**: configuration of machines, a different job from provisioning.
@diagram layers
caption: Which layer each tool mostly works on
layers:
  - {label: "Provision cloud resources", nodes: ["Terraform / OpenTofu|HCL, many providers|cp", "CloudFormation / Bicep|one cloud|info", "Pulumi / CDK|general languages|info"]}
  - {label: "Configure machines", nodes: ["Ansible|SSH based|env", "cloud-init|first boot|env"]}
  - {label: "Run workloads", nodes: ["Kubernetes|Helm, Kustomize, Argo CD|app"]}
@choose Picking an IaC tool
Terraform or OpenTofu | multi-cloud or many SaaS providers, large community | your team only wants a native single-cloud tool
CloudFormation | AWS only and tight console integration | you also manage Azure, GCP or Datadog
Pulumi / CDK | the team prefers real programming languages | you want a small, constrained and easily reviewed language
Crossplane | platform teams exposing infrastructure as Kubernetes APIs | you have no running control cluster yet
@end

@concept Installing and pinning Terraform
@plain
Terraform is a single binary. Different versions behave differently and can write state that older versions cannot read, so teams pin the version.
@problem
If one engineer upgrades locally and applies, the state format may move forward and teammates and CI suddenly fail with version errors.
@does
- Install with a version manager such as `tfenv`, `tfswitch` or `mise`, or from the vendor package repository.
- Declare the allowed range with `required_version` in the `terraform` block.
- Commit a file such as `.terraform-version` so tools and CI choose the same release.
- Upgrade deliberately in a pull request, never by accident.
@diagram flow
caption: One pinned version for laptop and pipeline
nodes:
  - ".terraform-version|1.x pinned|app"
  - "tfenv or mise|installs that binary|info"
  - "required_version|code refuses others|cp"
  - "CI job|reads the same file|ok"
@h Pin in code
```hcl title="versions.tf"
terraform {
  required_version = ">= 1.9.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}
```
```bash title="Check what you run" lab
terraform version
terraform -help | head -20
```
:::note
Terraform 1.5 and earlier are MPL licensed. Later releases use the Business Source License; OpenTofu is the open-source fork. A later concept compares them.
:::
@end

@concept The core workflow: init, plan, apply
@plain
Every change follows the same loop. **init** prepares the folder, **plan** shows what would change, **apply** makes the change, and **destroy** removes everything.
@problem
Changing real infrastructure blindly is dangerous. The loop forces you to see the effect before it happens.
@does
- `terraform init` downloads providers and modules and configures the backend. Run it after cloning or changing providers.
- `terraform plan` reads state, refreshes from the cloud, and prints a diff. It changes nothing.
- `terraform apply` shows a plan, asks for confirmation, then performs it and updates the state.
- `terraform destroy` plans and applies the deletion of everything the configuration manages.
@diagram seq
caption: What happens during a plan and apply
actors: ["You|terminal|app", "Terraform|CLI|cp", "State|file or bucket|info", "Cloud|provider API|ext"]
steps:
  - "0>1: terraform plan | req"
  - "1>2: read state | req"
  - "1>3: read real resources | req"
  - "3>1: current values | resp"
  - "1>0: diff to review | resp"
  - "0>1: terraform apply | req"
  - "1>3: create or change | req"
  - "1>2: write new state | req"
@h Day-to-day commands
```bash title="The loop" lab
terraform init
terraform fmt -recursive
terraform validate
terraform plan -out=tfplan
terraform apply tfplan
terraform output
```
@check
What does init do that plan does not? || It installs providers and modules and sets up the backend; plan assumes init already ran.
@end

@concept Reading a plan
@plain
The plan lists each resource with a symbol: `+` create, `-` destroy, `~` update in place, `-/+` replace (destroy and create). The summary line counts them.
@problem
Most outages from Terraform come from approving a plan nobody read, for example a database being replaced when only a tag was meant to change.
@does
- Look first at the summary: "Plan: 2 to add, 1 to change, 1 to destroy".
- Every `-/+` or `must be replaced` line deserves attention. A comment says which attribute forces replacement.
- Values marked `(known after apply)` are decided by the cloud at creation time.
- `(sensitive value)` hides secrets in output; the real value is still in state.
@diagram cmp
caption: Symbols in a plan
cards:
  - {h: "+ create", kind: ok, items: ["New resource", "Low risk"]}
  - {h: "~ update in place", kind: info, items: ["Attribute changes", "Check what changes"]}
  - {h: "-/+ replace", kind: warn, items: ["Destroyed then created", "Data loss for stateful resources"]}
  - {h: "- destroy", kind: bad, items: ["Removed for good", "Confirm intent"]}
@h Plan output you should stop and read
```text title="A dangerous plan" nocheck
  # aws_db_instance.main must be replaced
-/+ resource "aws_db_instance" "main" {
      ~ identifier = "shop-db" -> "shop-database" # forces replacement
    }

Plan: 1 to add, 0 to change, 1 to destroy.
```
:::danger
A replaced database loses its data unless a snapshot or `prevent_destroy` protects it. Stop and rethink instead of applying.
:::
@check
What does `~` mean in a plan? || An in-place update; the resource is kept and only the listed attributes change.
@end

@concept Saved plans and exit codes
@plain
`terraform plan -out=file` stores the exact plan. `terraform apply file` runs precisely that plan, without recomputing it.
@problem
Between plan and apply, someone may change the code or the cloud. Without a saved plan, what you approved is not necessarily what runs.
@does
- A saved plan applies without a confirmation prompt, because it was already reviewed.
- `-detailed-exitcode` makes plan return 0 for no changes, 1 for an error, and 2 when changes are present, which pipelines use for drift checks.
- `terraform show tfplan` prints it again; `terraform show -json tfplan` gives machine-readable output for policy tools.
- Saved plans can contain secrets in plain form, so store them as protected artifacts.
@diagram flow
caption: Review once, apply exactly that
numbered: true
nodes:
  - "plan -out=tfplan|binary plan file|app"
  - "Review|human or policy check|info"
  - "apply tfplan|no recompute|ok"
@h Pipeline friendly flags
```bash title="Non-interactive usage" lab
terraform plan -input=false -lock-timeout=5m -out=tfplan
terraform show -json tfplan > plan.json
terraform plan -detailed-exitcode >/dev/null; echo "exit=$?"
terraform apply -input=false tfplan
```
:::warn
`-auto-approve` on a fresh plan skips review. Use it only after a separate approval step, never as a habit on a laptop.
:::
@end

@concept The dependency graph and -target
@plain
Terraform builds a graph from references between resources. If a subnet uses a VPC's ID, the VPC comes first. Independent resources are created in parallel (10 at a time by default).
@problem
Doing ordering by hand is error prone, and serial creation is slow.
@does
- Any reference such as `aws_vpc.main.id` creates an edge in the graph.
- Destroy runs in reverse order.
- `terraform graph` outputs the graph in DOT format for visualisation.
- `-target` restricts a run to one resource and its dependencies. It is an emergency tool: it skips the rest of the configuration and can leave state inconsistent with code.
@diagram flow
caption: Parallel where possible, ordered where referenced
nodes:
  - "VPC|created first|app"
  - "Subnets and security group|created in parallel|info"
  - "Instance or cluster|needs both|ok"
@h Looking at the graph
```bash title="Graph and parallelism" lab
terraform graph | head -20
terraform apply -parallelism=5
```
:::warn
Habitual use of `-target` hides broken dependencies. If you need it often, split the configuration into smaller states instead.
:::
@check
How does Terraform know to create the VPC before the subnet? || The subnet references the VPC's attribute, creating a dependency edge in the graph.
@end
