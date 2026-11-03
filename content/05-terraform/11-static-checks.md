---
title: Static checks, linting and security scanning
minutes: 45
objectives:
  - Run fmt and validate and know what each does and does not catch
  - Use tflint and checkov to find provider mistakes and insecure settings
  - Wire the checks into pre-commit so problems stop before review
---
The cheapest bugs to fix are the ones found before anything is applied. Terraform has built-in checks, and a few well-known tools add provider-aware and security-aware rules.

@concept The testing pyramid for infrastructure
@plain
Checks range from instant and free (formatting, syntax) to slow and real (creating infrastructure and testing it). Run the cheap ones often, the expensive ones rarely.
@problem
Teams either test nothing and discover errors in production, or run slow full deployments for every typo.
@does
- Level 1: `fmt`, `validate`, linters. Seconds, no cloud access.
- Level 2: security and policy scans on code or on the plan JSON. Seconds.
- Level 3: `terraform test` and plan-based tests, possibly with mocked providers.
- Level 4: real deployments tested with Terratest or similar. Minutes, costs money.
@diagram layers
caption: Cheap checks at the bottom, run most often
layers:
  - {label: "Real deployment", nodes: ["Terratest|create, test, destroy|bad"]}
  - {label: "Module tests", nodes: ["terraform test|plan or apply based|warn"]}
  - {label: "Scans and policy", nodes: ["checkov / trivy|security rules|info", "OPA / Sentinel|organisation rules|info"]}
  - {label: "Static checks", nodes: ["fmt|style|ok", "validate|syntax and types|ok", "tflint|provider rules|ok"]}
@end

@concept terraform fmt
@plain
`terraform fmt` rewrites files to the canonical style: indentation, alignment of `=`, spacing.
@problem
Style arguments in code review waste time, and inconsistent formatting hides real changes in diffs.
@does
- `terraform fmt -recursive` formats the tree; `-check` returns a non-zero exit code without changing files (for CI); `-diff` shows what would change.
- Formatting never changes meaning.
- Run it in an editor on save and in CI.
@diagram flow
caption: Fail the build on unformatted code
nodes:
  - "Commit|any style|plain"
  - "fmt -check|compare to canonical|cp"
  - "Pass|merge continues|ok"
  - "Fail|run fmt and push|bad"
@h Usage
```bash title="fmt in practice" lab
terraform fmt -recursive
terraform fmt -check -recursive -diff
```
@end

@concept terraform validate
@plain
`terraform validate` checks that the configuration is internally consistent: valid syntax, known resource types and arguments, correct types, references to things that exist.
@problem
A typo in an argument name would otherwise fail halfway through an apply.
@does
- Needs `terraform init` first (providers provide the schemas) but no credentials, state or network calls to the cloud.
- Does not know whether your values are valid in the real world: a bad AMI ID or CIDR clash passes.
- `-json` produces machine readable output.
- Run in every module and root directory.
@diagram cmp
caption: What validate can and cannot see
cards:
  - {h: "Catches", kind: ok, items: ["Unknown argument names", "Wrong types", "Missing variables", "Bad references"]}
  - {h: "Misses", kind: warn, items: ["Nonexistent AMI or IAM role", "Quota and permission issues", "Overlapping CIDRs"]}
@h Run offline
```bash title="Validate without a backend" lab
terraform init -backend=false
terraform validate
terraform validate -json | head -20
```
@check
Does validate talk to AWS? || No. It uses provider schemas only, so it cannot detect real world problems like missing resources.
@end

@concept tflint
@plain
TFLint is a linter with provider-specific rules. It knows, for example, that `t2.nanoo` is not an EC2 instance type, or that a module uses a deprecated syntax.
@problem
`validate` accepts any string for `instance_type`. TFLint checks the value against the cloud's known list and enforces conventions.
@does
- Configured by `.tflint.hcl` with plugins for AWS, Azure or Google.
- Rules cover invalid values, deprecated features, unused declarations, naming conventions and module pinning.
- `tflint --init` downloads plugins; `tflint --recursive` scans all directories.
- Check the current docs for plugin versions.
@diagram flow
caption: Beyond validate
nodes:
  - "Terraform code|instance_type typo|plain"
  - "tflint|AWS ruleset|cp"
  - "Finding|invalid instance type|bad"
@h Configuration
```hcl title=".tflint.hcl"
plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

plugin "aws" {
  enabled = true
  version = "0.38.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
```
```bash title="Run it" lab
tflint --init
tflint --recursive
```
:::note
The plugin version above is an example. Check the plugin's releases for the current one.
:::
@end

@concept checkov and other security scanners
@plain
Checkov (by Prisma Cloud) scans Terraform, Kubernetes manifests, Dockerfiles and more against hundreds of security policies: unencrypted buckets, open security groups, no logging.
@problem
Insecure defaults go unnoticed in review. A scanner turns best practice into automatic findings.
@does
- `checkov -d .` scans a directory; `checkov -f tfplan.json` scans a plan, which sees resolved values.
- Each finding has an ID such as `CKV_AWS_18` and a guideline link.
- Suppress a justified exception inline with a comment `#checkov:skip=CKV_AWS_18:reason` so it is reviewed.
- Alternatives: Trivy (which absorbed tfsec), KICS, Terrascan. Pick one and tune it.
@diagram flow
caption: Scan code and plan
nodes:
  - "Terraform code|or plan JSON|plain"
  - "checkov|policy library|cp"
  - "Findings|CKV ids with guidance|warn"
  - "CI gate|fail on high severity|bad"
@h Running and skipping
```bash title="Scans" lab
checkov -d . --framework terraform
terraform show -json tfplan > plan.json
checkov -f plan.json --framework terraform_plan
trivy config .
```
```hcl title="A documented exception"
resource "aws_s3_bucket" "public_assets" {
  #checkov:skip=CKV_AWS_18:Access logging is not required for public assets
  bucket = "acme-public-assets"
}
```
@check
Why scan the plan JSON as well as the code? || The plan has resolved values from variables and modules, so the scanner evaluates what will really be created.
@end

@concept Terraform docs and other helpers
@plain
Small tools keep modules maintainable: `terraform-docs` generates README tables, `terraform graph` visualises dependencies, and `infracost` estimates cost changes in pull requests.
@problem
Hand-written documentation goes out of date, and cost surprises appear on the invoice.
@does
- `terraform-docs` reads variables and outputs and writes a markdown table between markers in the README.
- `infracost breakdown --path .` and `infracost diff` show monthly cost impact; it can comment on pull requests.
- `terraform providers` lists provider requirements for the whole tree.
@diagram cmp
caption: Small helpers
cards:
  - {h: "terraform-docs", kind: info, items: ["README inputs and outputs", "Run in pre-commit"]}
  - {h: "infracost", kind: ok, items: ["Cost diff in the PR", "Needs usage assumptions"]}
  - {h: "graph", kind: plain, items: ["Dependency picture", "Pipe to Graphviz dot"]}
@h Commands
```bash title="Helpers" lab
terraform-docs markdown table --output-file README.md --output-mode inject modules/network
terraform graph | dot -Tsvg > graph.svg
infracost diff --path .
```
@end

@concept pre-commit hooks
@plain
`pre-commit` runs checks on your machine before each commit. The `pre-commit-terraform` collection provides hooks for fmt, validate, tflint, docs and checkov.
@problem
Finding a formatting failure ten minutes after pushing, in CI, slows everybody down.
@does
- Hooks are listed in `.pre-commit-config.yaml` and pinned to a tag.
- Install once with `pre-commit install`; run all with `pre-commit run -a`.
- CI should run the same checks, because hooks can be skipped locally.
@diagram flow
caption: Same checks, two places
nodes:
  - "git commit|developer|app"
  - "pre-commit hooks|fmt, validate, tflint|cp"
  - "Push|to GitHub|info"
  - "CI runs same checks|cannot be skipped|ok"
@h Configuration
```yaml title=".pre-commit-config.yaml"
repos:
  - repo: https://github.com/antonbabenko/pre-commit-terraform
    rev: v1.96.1
    hooks:
      - id: terraform_fmt
      - id: terraform_validate
      - id: terraform_tflint
      - id: terraform_docs
```
:::note
The `rev` is an example. Pin the latest release tag from the repository.
:::
@end

@concept A first CI check job
@plain
A pull request pipeline should run the static checks on every changed directory. These jobs need no cloud credentials, so they are safe on forks.
@problem
Without automatic checks, quality depends on reviewers noticing problems.
@does
- Use `hashicorp/setup-terraform` (or OpenTofu's action) to install a pinned version.
- Run `fmt -check`, `init -backend=false`, `validate`, `tflint` and a scanner.
- Make the job a required status check on the protected branch.
@diagram flow
caption: Credential-free checks on every pull request
nodes:
  - "Pull request|opened or updated|app"
  - "fmt and validate|no cloud access|cp"
  - "tflint and checkov|scan|info"
  - "Required check|blocks merge on failure|ok"
@h Workflow
```yaml title=".github/workflows/terraform-check.yml"
name: terraform-check
on:
  pull_request:
    paths: ["infra/**"]

jobs:
  check:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
      - run: terraform fmt -check -recursive
      - run: terraform init -backend=false
      - run: terraform validate
      - uses: terraform-linters/setup-tflint@v4
      - run: tflint --init && tflint
```
@end
