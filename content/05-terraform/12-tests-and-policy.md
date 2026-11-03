---
title: Module tests and policy as code
minutes: 50
objectives:
  - Write terraform test files with run blocks, assertions and mocked providers
  - Know when Terratest is the right tool and what it costs
  - Enforce organisation rules with OPA or Sentinel against plan output
---
Static checks cannot prove a module behaves correctly. Tests create or plan the module with sample inputs and assert on the result. Policy as code enforces rules that apply to every change.
@concept terraform test
@plain
`terraform test` runs files named `*.tftest.hcl`. Each `run` block executes a plan or apply of your module with given variables, then evaluates `assert` conditions.
@problem
Before native tests, module authors used external languages for even simple checks like "the VPC has three subnets".
@does
- Test files live in `tests/` or next to the module.
- `command = plan` is fast and creates nothing; `command = apply` (default) creates real resources and destroys them after the test.
- `variables` blocks set inputs; `assert` blocks check outputs and resource attributes.
- `expect_failures` verifies that bad input is correctly rejected by a validation.
@diagram flow
caption: A test run
nodes:
  - "tests/basic.tftest.hcl|run blocks|app"
  - "terraform test|plan or apply|cp"
  - "Assertions|conditions on values|info"
  - "Result|pass or fail with messages|ok"
@h A plan-based test
```hcl title="tests/network.tftest.hcl" nocheck
variables {
  name = "test"
  azs  = ["eu-west-1a", "eu-west-1b"]
}

run "creates_private_subnets" {
  command = plan

  assert {
    condition     = length(output.private_subnet_ids) == 2
    error_message = "Expected one private subnet per AZ."
  }
}

run "rejects_bad_cidr" {
  command = plan

  variables {
    cidr_block = "not-a-cidr"
  }

  expect_failures = [var.cidr_block]
}
```
```bash title="Run" lab
terraform test
terraform test -verbose
```
@check
When would you choose command = plan over apply? || When you only need to check computed configuration; it is fast, free and needs no real resources.
@end

@concept Mocked providers
@plain
`mock_provider` replaces a real provider with a fake one for the test, returning generated values. The module can then be applied in a test without cloud credentials.
@problem
Real applies are slow, cost money and need credentials. Many module behaviours (conditions, for_each, outputs) do not need a real cloud.
@does
- Introduced in Terraform 1.7. OpenTofu has a comparable mocking feature; check its current docs.
- `mock_provider "aws" {}` generates random values for computed attributes. `override_data` and `mock_resource` fix specific values when needed.
- Mocks cannot find provider-side validation failures, so keep some real tests.
@diagram cmp
caption: Mock or real
cards:
  - {h: "Mocked", kind: ok, items: ["No credentials", "Seconds", "Tests your logic"]}
  - {h: "Real apply", kind: warn, items: ["Finds provider errors", "Costs time and money", "Needs cleanup"]}
@h Example
```hcl title="tests/mocked.tftest.hcl" nocheck
mock_provider "aws" {}

run "apply_with_mocks" {
  command = apply

  variables {
    name = "mock"
    azs  = ["eu-west-1a", "eu-west-1b"]
  }

  assert {
    condition     = output.vpc_id != ""
    error_message = "vpc_id should be set."
  }
}
```
@end

@concept Terratest
@plain
Terratest is a Go library that deploys real infrastructure with Terraform, runs checks against it (HTTP calls, AWS SDK queries, SSH) and destroys it.
@problem
Some questions need the real thing: "does the load balancer answer?" or "can the pod reach the database?"
@does
- Tests are Go functions: `terraform.InitAndApply`, then assertions, then `defer terraform.Destroy`.
- Gives the full flexibility of a programming language, including retries and parallel stacks.
- Needs Go skills, a sandbox account, unique names per run and cleanup of leaked resources.
- Use sparingly for critical modules; use `terraform test` for the rest.
@diagram flow
caption: Terratest lifecycle
numbered: true
nodes:
  - "InitAndApply|real resources|cp"
  - "Check|HTTP, SDK, kubectl|info"
  - "Destroy|deferred cleanup|ok"
@h A sketch
```go title="network_test.go" nocheck
func TestNetwork(t *testing.T) {
    t.Parallel()
    opts := &terraform.Options{
        TerraformDir: "../examples/basic",
        Vars: map[string]interface{}{"name": "tt-" + random.UniqueId()},
    }
    defer terraform.Destroy(t, opts)
    terraform.InitAndApply(t, opts)
    vpcID := terraform.Output(t, opts, "vpc_id")
    assert.NotEmpty(t, vpcID)
}
```
@choose Picking a test approach
terraform test (plan) | logic, conditions and outputs | you need to verify real cloud behaviour
terraform test (mock) | fast offline CI for modules | provider-side validation matters
terraform test (apply) | simple end-to-end checks in a sandbox account | the module is huge and slow to create
Terratest | complex integration checks in Go | the team does not use Go and checks are simple
@end

@concept Testing plans with JSON
@plain
`terraform show -json tfplan` produces a stable machine-readable description of what will change. Tools, scripts and policies read it.
@problem
Reviewers cannot be expected to read every line of a long plan, and some rules such as "no public S3 bucket" are easy to automate.
@does
- Contains `resource_changes` with `before`, `after`, and an `actions` list such as `["create"]`, `["update"]` or `["delete","create"]`.
- Query with `jq`; the same file feeds checkov, OPA and Sentinel.
- Do not store it publicly: it can include sensitive values.
@diagram flow
caption: One plan file, many consumers
nodes:
  - "terraform plan -out|binary plan|app"
  - "show -json|plan.json|cp"
  - "jq, checkov, OPA|checks|info"
  - "Decision|allow or block|ok"
@h Example with jq
```bash title="Find deletions" lab
terraform show -json tfplan > plan.json
jq -r '.resource_changes[] | select(.change.actions | index("delete")) | .address' plan.json
jq '[.resource_changes[].change.actions[]] | group_by(.) | map({(.[0]): length}) | add' plan.json
```
@check
How does a replacement appear in the JSON actions list? || As two actions, delete and create (in either order).
@end

@concept Policy as code: what and why
@plain
Policy as code expresses organisational rules ("all buckets encrypted", "no 0.0.0.0/0 on port 22", "production changes need approval") as machine-checked programs.
@problem
Reviewers are inconsistent and tired. Rules in a wiki are ignored.
@does
- Policy runs after plan and before apply and can block or warn.
- Checks plan JSON, so it applies to modules and any code style.
- Two common engines: OPA (open source, Rego language) and Sentinel (HashiCorp, in HCP Terraform and Enterprise).
- Start with a few high value rules, as warnings, then enforce.
@diagram flow
caption: Gate between plan and apply
nodes:
  - "Plan|plan.json|app"
  - "Policy engine|OPA or Sentinel|cp"
  - "Allow|apply proceeds|ok"
  - "Deny|message to the author|bad"
@end

@concept OPA and Rego
@plain
Open Policy Agent evaluates policies written in **Rego** against JSON input. For Terraform the input is the plan JSON.
@problem
You need an open, vendor neutral way to enforce rules in any CI system.
@does
- Rules are small: `deny[msg] { ... }` produces messages when a condition holds.
- Run with `opa eval` or `conftest test plan.json -p policy/`; Conftest is common in CI.
- Policies are tested with `opa test`.
- Tools like checkov also support custom policies; pick one policy home to avoid confusion.
@diagram flow
caption: Conftest in a pipeline
nodes:
  - "plan.json|input|app"
  - "conftest + Rego|policy folder|cp"
  - "Violations|messages|warn"
  - "Exit code|fails the job|bad"
@h A Rego rule
```rego title="policy/s3.rego" nocheck
package main

deny[msg] {
  rc := input.resource_changes[_]
  rc.type == "aws_security_group_rule"
  rc.change.after.type == "ingress"
  rc.change.after.from_port <= 22
  rc.change.after.to_port >= 22
  rc.change.after.cidr_blocks[_] == "0.0.0.0/0"
  msg := sprintf("%s opens SSH to the world", [rc.address])
}
```
```bash title="Run" lab
conftest test plan.json -p policy/
```
@end

@concept Sentinel and HCP Terraform policies
@plain
Sentinel is HashiCorp's policy language, enforced inside HCP Terraform and Terraform Enterprise. It has three enforcement levels: advisory, soft mandatory (overridable) and hard mandatory.
@problem
Teams already using HCP Terraform want policies enforced centrally, without building their own pipeline gate.
@does
- Policies read the plan through imports such as `tfplan/v2`.
- Policy sets are attached to workspaces or projects.
- HCP Terraform also supports OPA policies; check the current docs for supported engines and tiers.
- Not available for plain open source CLI runs, and not for OpenTofu.
@diagram cmp
caption: Enforcement levels
cards:
  - {h: "advisory", kind: info, items: ["Logs a warning", "Run continues"]}
  - {h: "soft-mandatory", kind: warn, items: ["Blocks the run", "Authorised override possible"]}
  - {h: "hard-mandatory", kind: bad, items: ["Blocks the run", "No override"]}
@h Shape of a Sentinel policy
```text title="require-tags.sentinel" nocheck
import "tfplan/v2" as tfplan

main = rule {
  all tfplan.resource_changes as _, rc {
    rc.change.after.tags contains "Owner"
  }
}
```
@check
Which engine works for OpenTofu pipelines, OPA or Sentinel? || OPA, because it reads plain JSON in any CI. Sentinel is tied to HashiCorp's platforms.
@end
