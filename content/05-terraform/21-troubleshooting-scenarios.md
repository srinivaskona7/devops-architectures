---
title: Ten Terraform troubleshooting scenarios
minutes: 55
objectives:
  - Diagnose the ten most common Terraform failures from their symptoms
  - Apply the safest fix for each and avoid making state worse
  - Build a habit of reading the error and the plan before acting
---
Each scenario gives the symptom, the cause, the fix and how to prevent it. Before changing anything: read the full error, take a copy of the state, and make sure nobody else is applying.

@concept Scenario 1, state lock held by a dead run
@plain
Plan fails with "Error acquiring the state lock" and shows a lock ID, owner and time.
@problem
A CI job was cancelled mid-apply or a laptop lost power, and the lock was never released.
@does
- First confirm the owner and time. If the run is still going, wait; do not unlock.
- With S3 native locking, the lock is a `.tflock` object beside the state. With DynamoDB it is a row keyed by `LockID`.
- Remove it with `terraform force-unlock <ID>` once you are sure nothing runs.
- Prevent repeats: use `-lock-timeout`, and make CI jobs non-cancellable during apply.
@diagram flow
caption: Safe unlock path
numbered: true
nodes:
  - "Read lock info|who and when|info"
  - "Confirm no run|CI and teammates|warn"
  - "force-unlock ID|release|app"
  - "Plan again|check state|ok"
@h Commands
```bash title="Unlock" lab
terraform plan -lock-timeout=2m
terraform force-unlock LOCK_ID
terraform plan
```
@end

@concept Scenario 2, plan wants to replace a resource
@plain
Plan shows `-/+ destroy and then create replacement` for a database or load balancer after a harmless edit.
@problem
Some attributes cannot change in place. Changing them forces replacement, which for a database means data loss.
@does
- Read the line marked `# forces replacement` to see the exact attribute.
- Revert the change or find an in-place alternative (for example a separate resource for the setting).
- If a rename caused it, use a `moved` block so the address changes without recreation.
- Protect important resources with `prevent_destroy = true` so the plan errors instead.
@diagram flow
caption: Reading a replacement
nodes:
  - "Plan output|-/+ marker|warn"
  - "forces replacement|which attribute|bad"
  - "Revert or moved block|avoid recreation|app"
  - "Safe plan|in-place update|ok"
@h Rename without recreation
```hcl title="moved block"
moved {
  from = aws_db_instance.main
  to   = aws_db_instance.primary
}
```
@check
Which block renames an address with no recreation? || A moved block with from and to.
@end

@concept Scenario 3, AccessDenied and expired credentials
@plain
Errors like `AccessDenied`, `ExpiredToken` or `no valid credential sources` appear during plan or apply.
@problem
The identity used by Terraform lacks permission, or its token expired during a long apply.
@does
- Run `aws sts get-caller-identity` in the same environment to see who you really are.
- OIDC role sessions have a maximum duration (default one hour); a slow EKS plus RDS apply can exceed it. Raise the role session duration or split the stack.
- The error text names the missing action, for example `rds:CreateDBInstance`. Add the least privilege needed, not `*`.
- Assume-role chains and `AWS_PROFILE` in the shell can silently point to another account; print the account ID before apply.
@diagram flow
caption: Find the identity first
nodes:
  - "Error|AccessDenied action|bad"
  - "sts get-caller-identity|who am I|info"
  - "Policy or session|missing action or expired|warn"
  - "Fix role|least privilege|ok"
@h Check
```bash title="Identity" lab
aws sts get-caller-identity
aws configure list
```
@end

@concept Scenario 4, drift after a manual console change
@plain
A plan shows changes nobody wrote, for example a security group rule reverting, or tags being removed.
@problem
Someone edited the resource by hand, or another controller (autoscaler, Kubernetes controller) modifies it.
@does
- Decide who is right. If the console change should stay, update the code. If not, apply to revert it.
- For attributes managed by something else, use `lifecycle { ignore_changes = [...] }`.
- Detect drift early: scheduled `terraform plan -detailed-exitcode` (exit code 2 means changes) in CI that alerts.
- Reduce root causes with IAM policies denying console writes in production.
@diagram flow
caption: Drift handling
nodes:
  - "Scheduled plan|exit code 2|info"
  - "Diff found|manual change|warn"
  - "Decide|keep or revert|cp"
  - "Code or apply|converged|ok"
@h Scheduled check
```bash title="Drift detection" lab
terraform plan -detailed-exitcode -lock=false
echo "exit code $?"
```
@check
What exit code means changes are pending? || 2 with detailed-exitcode; 0 is no changes and 1 is an error.
@end

@concept Scenario 5, dependency cycle
@plain
`Error: Cycle: aws_security_group.a, aws_security_group.b` appears during plan.
@problem
Two resources reference each other, so there is no order in which to create them.
@does
- Classic case: two security groups with inline rules that name each other.
- Fix: create both groups empty, then add the rules as separate `aws_vpc_security_group_ingress_rule` resources.
- Use `terraform graph | dot -Tsvg > graph.svg` to see the loop.
- Avoid `depends_on` in modules unless needed, as it can add accidental edges.
@diagram flow
caption: Break the loop with separate rule resources
nodes:
  - "SG A|empty|app"
  - "SG B|empty|app"
  - "Rule A to B|separate resource|info"
  - "Rule B to A|separate resource|info"
@h Sample
```hcl title="no cycle"
resource "aws_security_group" "a" {
  name   = "a"
  vpc_id = var.vpc_id
}

resource "aws_security_group" "b" {
  name   = "b"
  vpc_id = var.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "a_from_b" {
  security_group_id            = aws_security_group.a.id
  referenced_security_group_id = aws_security_group.b.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}

resource "aws_vpc_security_group_ingress_rule" "b_from_a" {
  security_group_id            = aws_security_group.b.id
  referenced_security_group_id = aws_security_group.a.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
```
@end

@concept Scenario 6, count or for_each value known only after apply
@plain
`The "for_each" set includes values derived from resource attributes that cannot be determined until apply`.
@problem
Terraform must know how many instances exist at plan time, but your keys depend on a resource not yet created.
@does
- Use keys known in advance (names from a static list or variable) and values that are computed.
- Bad: `for_each = toset(aws_subnet.x[*].id)`. Better: `for_each = aws_subnet.x` keyed by AZ.
- Last resort: apply in two steps with `-target`, then fix the design so it is not needed.
- Do not use `count` with a list that changes order; it reshuffles resources.
@diagram cmp
caption: Keys versus computed values
cards:
  - {h: "Bad key", kind: bad, items: ["Subnet IDs as set", "Unknown at plan"]}
  - {h: "Good key", kind: ok, items: ["AZ names as map keys", "Known at plan"]}
@h Fix
```hcl title="stable keys" nocheck
resource "aws_route_table_association" "private" {
  for_each       = aws_subnet.private     # keyed by AZ
  subnet_id      = each.value.id
  route_table_id = aws_route_table.private[each.key].id
}
```
@end

@concept Scenario 7, provider version or lock file mismatch
@plain
`Error: Failed to query available provider packages` or `the cached package does not match` after switching machines or CI images.
@problem
`.terraform.lock.hcl` has hashes for one platform only, or a required version is not available.
@does
- Add hashes for all platforms used: `terraform providers lock -platform=linux_amd64 -platform=darwin_arm64`.
- Commit the lock file; upgrade deliberately with `terraform init -upgrade` in a pull request.
- Behind a proxy or registry mirror, check the CLI configuration for `provider_installation`.
- Pin ranges with `~>` and keep one version across stacks where possible.
@diagram flow
caption: Lock file for every platform
nodes:
  - "Laptop arm64|macOS|app"
  - "CI amd64|Linux|app"
  - "providers lock|hashes for both|cp"
  - "Reproducible init|ok|ok"
@h Command
```bash title="Lock for platforms" lab
terraform providers lock -platform=linux_amd64 -platform=darwin_arm64
```
@end

@concept Scenario 8, resource already exists
@plain
Apply fails with `EntityAlreadyExists`, `BucketAlreadyOwnedByYou` or `already exists`.
@problem
The object is in the cloud but not in state, usually after a failed apply, a state loss, or manual creation.
@does
- Import it with an `import` block, then plan to see differences.
- If it is leftover from a failed apply you do not need, delete it and apply again.
- If state was lost, restore the previous version from S3 versioning before trying to rebuild by imports.
- Prevent: do not run partial applies by hand; keep a single pipeline owning the stack.
@diagram flow
caption: Reconcile an orphan
nodes:
  - "Apply fails|already exists|bad"
  - "Is it needed?|inspect the object|info"
  - "Import or delete|choose one|app"
  - "Apply|completes|ok"
@h Import
```hcl title="adopt the bucket"
import {
  to = aws_s3_bucket.assets
  id = "acme-shop-assets"
}
```
@end

@concept Scenario 9, slow plan and API throttling
@plain
Plans take 15 minutes, or fail with `Throttling` or `RequestLimitExceeded`.
@problem
The state has thousands of resources, and every plan refreshes each one with API calls.
@does
- Split the state into smaller stacks (the long-term fix).
- Lower parallelism with `-parallelism=5` if throttled; the default is 10.
- Use `-refresh=false` only for quick local checks.
- Provider settings for retries (for example `max_retries` in the AWS provider) can help; check the provider docs.
- Find slow items with `TF_LOG=debug` timing, or by looking at which resource types dominate state.
@diagram flow
caption: Why large states are slow
nodes:
  - "5000 resources|one state|warn"
  - "Refresh calls|one or more each|info"
  - "Throttling|API limits|bad"
  - "Split stacks|smaller plans|ok"
@h Commands
```bash title="Tame parallelism" lab
terraform plan -parallelism=5
terraform state list | cut -d. -f1-2 | sort | uniq -c | sort -rn | head
```
@end

@concept Scenario 10, sensitive value in a plan or log, and a broken module upgrade
@plain
Two common review failures: a secret appears in CI logs, and a module version bump produces a surprising plan.
@problem
Logs are widely readable. Module upgrades silently change defaults and addresses.
@does
- Secrets: mark variables `sensitive`, avoid `terraform output` of secrets in CI logs, and never run with `TF_LOG=trace` in shared logs. If a secret leaked, rotate it; deleting the log is not enough.
- Upgrades: pin module versions, bump one at a time, read the changelog and the plan. Renamed resources need `moved` blocks which good modules ship.
- Use `terraform plan -out` and apply the saved plan, so what was reviewed is exactly what runs.
- Run upgrades in staging first.
@diagram flow
caption: Reviewed plan is the applied plan
numbered: true
nodes:
  - "plan -out|saved file|app"
  - "Review|diff and cost|info"
  - "apply tfplan|same plan|ok"
@h Saved plan
```bash title="Apply what was reviewed" lab
terraform plan -out=tfplan
terraform show tfplan
terraform apply tfplan
```
@check
Why apply a saved plan? || It guarantees the reviewed changes are exactly what runs, even if the code or cloud changed in between.
@end
