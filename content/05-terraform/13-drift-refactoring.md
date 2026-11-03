---
title: Drift, moved blocks, refactoring and safe destroys
minutes: 45
objectives:
  - Detect and resolve configuration drift
  - Refactor with moved blocks without destroying resources
  - Plan safe destroys and recover from common failures
---
Real infrastructure changes outside Terraform, and code needs reshaping over time. This section covers noticing drift, refactoring safely and removing things on purpose.
@concept What drift is
@plain
Drift is when real infrastructure no longer matches the code and state, usually because someone changed it in the console, a script ran, or another tool modified it.
@problem
The next apply will either undo the change silently or fail. Drift in security groups or IAM can also be a security incident.
@does
- Common sources: emergency console fixes, autoscaling, operators and controllers editing AWS resources, expired or rotated values.
- Terraform detects drift during every plan, since it refreshes state from the API.
- Resolve by either updating the code to match reality, or applying to revert reality.
@diagram flow
caption: Code and reality diverge
nodes:
  - "Code and state|desired|app"
  - "Console edit|manual change|warn"
  - "plan|shows the difference|info"
  - "Decide|accept or revert|cp"
@end

@concept Detecting drift on a schedule
@plain
A scheduled pipeline runs `terraform plan -detailed-exitcode` regularly and alerts when it returns exit code 2.
@problem
Without checks, drift is found only when someone makes an unrelated change and a surprising plan appears.
@does
- Exit codes: 0 no changes, 1 error, 2 changes pending.
- Run nightly per stack using a read-only role, and send findings to Slack or open an issue.
- `terraform apply -refresh-only` records accepted drift in state without changing infrastructure.
- Commercial tools (HCP Terraform health checks, Spacelift, env0) offer drift detection too.
@diagram flow
caption: Nightly drift check
numbered: true
nodes:
  - "Schedule|cron in GitHub Actions|app"
  - "plan -detailed-exitcode|read-only role|cp"
  - "Exit code 2|drift found|warn"
  - "Alert|issue or chat message|info"
@h Workflow sketch
```yaml title=".github/workflows/drift.yml"
name: drift
on:
  schedule:
    - cron: "0 3 * * *"

permissions:
  id-token: write
  contents: read

jobs:
  plan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111122223333:role/terraform-readonly
          aws-region: eu-west-1
      - run: terraform -chdir=infra/envs/prod init -input=false
      - run: terraform -chdir=infra/envs/prod plan -detailed-exitcode -input=false -lock=false
```
@check
What does exit code 2 mean? || The plan succeeded and contains changes, which in a drift job means something differs.
@end

@concept The moved block
@plain
A `moved` block tells Terraform that a resource has a new address, so it updates state instead of destroying and recreating.
@problem
Renaming a resource, adding `count` or `for_each`, or moving it into a module changes its address, which looks like delete plus create.
@does
- Syntax: `moved { from = old_address  to = new_address }`.
- Appears in the plan as "has moved to"; apply updates the state entry.
- Works for resources, modules and changes between single, `count` and `for_each` instances.
- Keep the block in the code for as long as any state might still hold the old address; for shared modules, keep it indefinitely.
- Preferred over `terraform state mv` because it is reviewed and applies in every environment.
@diagram flow
caption: Address changes, object stays
nodes:
  - "aws_s3_bucket.logs|old address|warn"
  - "moved block|from and to|cp"
  - "aws_s3_bucket.audit|new address, same bucket|ok"
@h Examples
```hcl title="moved.tf"
moved {
  from = aws_s3_bucket.logs
  to   = aws_s3_bucket.audit
}

moved {
  from = aws_vpc.main
  to   = module.network.aws_vpc.this
}

moved {
  from = aws_subnet.private
  to   = aws_subnet.private["a"]
}
```
@end

@concept Refactoring workflow
@plain
Refactoring means changing code structure without changing infrastructure. The test of success is a plan that shows no changes (apart from moves).
@problem
Reshaping a large configuration can accidentally recreate production resources.
@does
- Make small steps: one rename or extraction per pull request.
- Add `moved` blocks first, then run `plan` and read for any `destroy` or `replace`.
- Extracting a module: create the module, add moved blocks from root addresses to `module.x.address`, plan, apply.
- Splitting a state: use `removed` and `import` blocks, or `state mv` between states, with backups.
@diagram flow
caption: Refactor in small checked steps
numbered: true
nodes:
  - "Edit code|rename or extract|app"
  - "Add moved blocks|map old to new|cp"
  - "Plan|only moves, no destroys|info"
  - "Apply|state rewritten|ok"
@h Check for surprises
```bash title="Block destructive refactors" lab
terraform plan -out=tfplan
terraform show -json tfplan | jq -r '.resource_changes[] | select(.change.actions != ["no-op"]) | "\(.change.actions|join(",")) \(.address)"'
```
:::tip
In CI, fail the refactor job if the plan contains any `delete` action unless the pull request is labelled as intentional.
:::
@check
What is the success criterion of a refactor? || The plan shows only moves and no create, update or destroy of real resources.
@end

@concept Splitting a big state
@plain
Over time one state grows to hundreds of resources: plans become slow, locks collide and every change risks everything.
@problem
Blast radius and run time grow with the size of a state.
@does
- Split along change frequency and ownership: network (rare), cluster (occasional), application infrastructure (often).
- Procedure: back up, move resources with `terraform state mv -state-out`, or `removed` plus `import` blocks in the new stack; plan both stacks until clean.
- Connect stacks afterwards with data sources or published parameters instead of shared state.
- Avoid splitting too finely, which makes ordering and sharing harder.
@diagram layers
caption: Stacks by rate of change
layers:
  - {label: "Rarely changes", nodes: ["network|VPC, subnets|app", "accounts and IAM base|roles|app"]}
  - {label: "Sometimes", nodes: ["eks|cluster and node groups|info", "data|RDS, S3|info"]}
  - {label: "Often", nodes: ["apps|IAM roles, queues, DNS per service|ok"]}
@h State mv between files
```bash title="Move resources into a new state" lab
terraform state pull > backup.tfstate
terraform state mv -state-out=../data/terraform.tfstate aws_db_instance.main aws_db_instance.main
```
:::warn
This is for local state files. With remote backends, prefer `removed` and `import` blocks or pull, edit with the `state` commands, and push after checking the current docs.
:::
@end

@concept Safe destroys
@plain
Destroying infrastructure deliberately is routine in dev and rare in production. The process must show exactly what will go.
@problem
`terraform destroy` in the wrong directory or workspace deletes the wrong environment.
@does
- `terraform plan -destroy` shows the full destroy plan without acting.
- Confirm the account, region and workspace first (`aws sts get-caller-identity`, `terraform workspace show`).
- Protect stateful resources: `prevent_destroy`, RDS `deletion_protection`, S3 versioning and `force_destroy = false`, final snapshots.
- Destroy a single resource by removing it from code and applying, rather than `-target`.
- In pipelines, require approval for any plan containing a delete.
@diagram flow
caption: Check before you destroy
numbered: true
nodes:
  - "Who and where|account, region, workspace|info"
  - "plan -destroy|review list|cp"
  - "Protections|snapshots, deletion protection|warn"
  - "Approve and destroy|two people|ok"
@h Pre-flight
```bash title="Before any destroy" lab
aws sts get-caller-identity
terraform workspace show
terraform plan -destroy -out=destroy.plan
terraform show destroy.plan | tail -20
```
@check
Why prefer removing code to using -target for deleting one resource? || It keeps code, state and reality in agreement and goes through review; -target skips the rest of the graph.
@end

@concept Common failures and fixes
@plain
Some errors appear again and again. Recognising them saves hours.
@problem
Under pressure people reach for state edits or force flags that make things worse.
@does
- **Error acquiring the state lock**: someone else is running, or a crash left a lock. Wait, then `force-unlock` only if sure.
- **Resource already exists**: created outside; import it.
- **Cycle**: two resources depend on each other; break with a separate rule resource (for security groups, use standalone rule resources).
- **Provider produced inconsistent result**: usually a provider bug or eventual consistency; re-run plan, check issues for the provider version.
- **Value depends on resource attributes that cannot be determined**: a `for_each` key is unknown; use static keys.
@diagram cmp
caption: Error to action
cards:
  - {h: "State lock", kind: warn, items: ["Check who holds it", "force-unlock last"]}
  - {h: "Already exists", kind: info, items: ["Import block", "Then plan again"]}
  - {h: "Cycle", kind: bad, items: ["Split resources", "Use standalone rules"]}
  - {h: "Unknown for_each key", kind: warn, items: ["Use static keys", "Or apply in two steps"]}
@end
