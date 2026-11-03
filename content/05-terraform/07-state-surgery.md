---
title: State surgery with mv, rm and import
minutes: 45
objectives:
  - Rename, move and forget resources in state without destroying them
  - Import existing infrastructure with the CLI and with import blocks
  - Back up state and verify with a plan after every manual change
---
Sometimes the code and the state disagree about a name or about what exists. State commands fix that without touching real infrastructure, but a mistake can orphan resources, so each is used with care.
@concept When state must be changed by hand
@plain
Normal changes go through plan and apply. State surgery is for the cases where the code changed shape but the real object did not: renamed resources, moved modules, adopted resources, or abandoned ones.
@problem
If you rename `aws_s3_bucket.logs` to `aws_s3_bucket.audit` in code, Terraform sees one resource missing and one new: it plans to destroy the bucket and create another.
@does
- Prefer declarative blocks (`moved`, `import`, `removed`) because they are reviewed in a plan and repeatable in every environment.
- Use CLI `terraform state` commands for one-off repairs.
- Always back up first and run plan afterwards; the expected result is "No changes".
@diagram flow
caption: A safe surgery routine
numbered: true
nodes:
  - "Back up state|state pull > backup|warn"
  - "Change state|mv, rm, import|cp"
  - "Run plan|expect no changes|info"
  - "Commit code|matches state|ok"
@h Back up first
```bash title="Always" lab
terraform state pull > state-backup-$(date +%Y%m%d%H%M).json
terraform state list | head
```
@end

@concept terraform state mv
@plain
`terraform state mv SOURCE DEST` renames or relocates a resource inside state. The real object is untouched.
@problem
Refactoring names or moving a resource into a module otherwise causes destroy and recreate.
@does
- Rename: `terraform state mv aws_s3_bucket.logs aws_s3_bucket.audit`.
- Into a module: `terraform state mv aws_vpc.main module.network.aws_vpc.this`.
- Between state files with `-state` and `-state-out`, or between backends by pulling and pushing; be careful and check the current docs.
- After the move, update the code to match, then plan.
@diagram flow
caption: Only the address changes
nodes:
  - "aws_s3_bucket.logs|old address|warn"
  - "state mv|rewrites the address|cp"
  - "aws_s3_bucket.audit|same real bucket|ok"
@h Example
```bash title="Rename and move" lab
terraform state mv aws_s3_bucket.logs aws_s3_bucket.audit
terraform state mv 'aws_subnet.private[0]' 'aws_subnet.private["a"]'
terraform plan
```
:::tip
Quote addresses containing brackets or quotes so the shell does not interpret them.
:::
@check
What should the plan show after a correct mv and matching code change? || No changes.
@end

@concept terraform state rm
@plain
`terraform state rm ADDRESS` makes Terraform forget a resource without deleting it in the cloud.
@problem
You want another stack to take ownership, or a resource should no longer be managed (or it was deleted outside and state is stuck).
@does
- The real object stays; state entry disappears.
- If the code block remains, the next plan wants to create it again, so remove or move the code too.
- Declarative alternative: a `removed` block with `lifecycle { destroy = false }` (Terraform 1.7 and later).
@diagram flow
caption: Forget, not destroy
nodes:
  - "Resource in state|managed|app"
  - "state rm|entry deleted|cp"
  - "Real object|still exists, unmanaged|warn"
@h Both ways
```bash title="CLI" lab
terraform state rm aws_instance.legacy
```
```hcl title="removed block"
removed {
  from = aws_instance.legacy

  lifecycle {
    destroy = false
  }
}
```
@end

@concept Importing existing resources
@plain
**Import** brings a resource that already exists under Terraform's management by attaching it to a resource block.
@problem
Real estates start with console-built resources. Recreating them would cause downtime or data loss.
@does
- You write the resource block first, then tell Terraform which real ID belongs to it.
- Each resource type documents its import ID format (name, ARN or a composite) at the bottom of its docs page.
- The CLI form `terraform import aws_s3_bucket.logs my-bucket` changes state immediately.
- Import fills state only; your code must match the real settings or the next plan shows differences to resolve.
@diagram seq
caption: Import links a block to a real object
actors: ["Engineer|writes block|app", "Terraform|import|cp", "Cloud|existing bucket|ext"]
steps:
  - "0>1: import address and ID | req"
  - "1>2: read the object | req"
  - "2>1: attributes | resp"
  - "1>0: state updated | resp"
@h CLI import
```bash title="One-off import" lab
terraform import aws_s3_bucket.logs acme-prod-logs-eu-west-1
terraform plan      # resolve any differences by editing code
```
@check
Does import write your configuration for you? || The classic CLI does not; you write the block. Import blocks can generate a draft with -generate-config-out.
@end

@concept Import blocks
@plain
An `import` block declares the import in code, so it appears in the plan, can be reviewed in a pull request, and is applied by the pipeline.
@problem
CLI imports are manual, invisible to reviewers and cannot be repeated for several environments.
@does
- Syntax: `import { to = aws_s3_bucket.logs  id = "acme-prod-logs-eu-west-1" }`.
- `terraform plan` shows "will be imported"; apply performs it. The block can be removed afterwards.
- `for_each` works in import blocks in recent versions, which helps with bulk adoption; check the current docs.
- `terraform plan -generate-config-out=generated.tf` drafts resource code for imports. Treat it as a starting point and tidy it.
@diagram flow
caption: Import as a reviewed change
numbered: true
nodes:
  - "Write import block|to and id|app"
  - "plan -generate-config-out|draft resource code|info"
  - "Review and clean|remove noise|warn"
  - "apply|resource under management|ok"
@h Example
```hcl title="import.tf"
import {
  to = aws_s3_bucket.logs
  id = "acme-prod-logs-eu-west-1"
}

resource "aws_s3_bucket" "logs" {
  bucket = "acme-prod-logs-eu-west-1"
}
```
```bash title="Generate a draft" lab
terraform plan -generate-config-out=generated.tf
```
@end

@concept Importing at scale and tooling
@plain
Large estates need more than one-by-one imports. Tools can discover resources and emit HCL.
@problem
Hundreds of hand-built resources would take weeks to write by hand.
@does
- Terraformer and `aztfexport` (Azure) can export resources to HCL and state; AWS has Cloud Control based generation in some providers. Check each tool's current status.
- Generated code is verbose and flat. Refactor into modules after importing.
- Import in dependency order and in small batches, planning after each one.
- Keep a spreadsheet or issue of what is adopted and what remains.
@diagram flow
caption: Adopt gradually
nodes:
  - "Inventory|list existing|plain"
  - "Generate|draft HCL|info"
  - "Import batch|small groups|cp"
  - "Refactor|into modules|ok"
@h Check progress
```bash title="What is managed" lab
terraform state list | wc -l
aws ec2 describe-vpcs --query 'Vpcs[].VpcId' --output text
```
@end

@concept Recovering from broken state
@plain
Some failures leave state wrong: a crashed apply, a deleted object, or a resource that exists but is not recorded.
@problem
You need a calm routine, not guesses, when a plan refuses to run or wants to destroy something it should not.
@does
- Stop all other runs and take a backup of the current state and bucket version.
- Resource deleted outside Terraform: `terraform plan` notices and plans to recreate; use `state rm` if it should not exist.
- Resource created but not recorded after a crash: `import` it.
- Corrupt or wrong state: restore the previous S3 version.
- `terraform refresh` / `apply -refresh-only` updates state from reality without changing infrastructure.
@diagram cmp
caption: Symptom to fix
cards:
  - {h: "Deleted outside", kind: info, items: ["Plan wants to recreate", "Accept or state rm"]}
  - {h: "Exists, not in state", kind: warn, items: ["Plan wants to create, API says exists", "Import it"]}
  - {h: "Renamed in code", kind: warn, items: ["Destroy and create planned", "moved block or state mv"]}
  - {h: "State corrupt", kind: bad, items: ["Errors at init or plan", "Restore S3 object version"]}
@h Refresh-only
```bash title="Update state from reality" lab
terraform apply -refresh-only
```
:::danger
Never run `terraform destroy` to clean up confusion before you understand what the state contains.
:::
@check
How is a refresh-only apply different from a normal apply? || It only updates state to match reality and never changes infrastructure.
@end
