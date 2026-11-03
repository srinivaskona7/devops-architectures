---
title: Cost estimation and security scanning
minutes: 50
objectives:
  - Estimate cost changes in pull requests with Infracost
  - Set budgets and guardrails from the estimate
  - Combine scanners and policy into a layered security gate
---
A plan tells you what changes. Two more questions belong in the same review: what will it cost, and is it safe.

@concept Infracost in a pull request
@plain
Infracost reads Terraform code or a plan and prices the resources from cloud price lists. It posts the monthly cost difference on the pull request.
@problem
A one-line change such as an instance type or an extra NAT gateway can add hundreds of dollars a month, and nobody notices until the bill.
@does
- `infracost breakdown --path .` prints the monthly estimate. `infracost diff` compares against a baseline.
- Run with a plan JSON for the most accurate result, since counts and conditionals are resolved.
- Usage-based items such as data transfer or requests need a usage file; without it they show zero or defaults.
- Check the current Infracost docs for CLI flags, pricing API keys and the GitHub integration.
@diagram flow
caption: Cost shown at review time
numbered: true
nodes:
  - "terraform plan|saved as JSON|app"
  - "infracost diff|prices the change|info"
  - "PR comment|plus 340 dollars per month|warn"
  - "Review|accept or change|ok"
@h Local run
```bash title="Breakdown and diff" lab
terraform plan -out tfplan
terraform show -json tfplan > plan.json
infracost breakdown --path plan.json
infracost diff --path plan.json --compare-to baseline.json
```
@end

@concept Reading estimates and the arithmetic behind them
@plain
Most estimates are hours in the month multiplied by an hourly price, plus storage and usage.
@problem
Numbers without a feel for the arithmetic are either trusted blindly or ignored.
@does
- A month has about 730 hours (8 760 hours per year divided by 12).
- NAT gateway at an example rate of 0.045 dollars per hour: 0.045 × 730 = 32.85 dollars per month before data processing charges. Three of them: 98.55.
- Moving prod from one NAT to three adds 65.70 per month in hourly charges alone.
- Prices differ by region and change over time; use the tool, not these example rates.
@diagram cmp
caption: Example NAT arithmetic with an assumed rate
cards:
  - {h: "One NAT", kind: ok, items: ["32.85 per month", "Single AZ risk"]}
  - {h: "Three NATs", kind: warn, items: ["98.55 per month", "One per AZ, resilient"]}
  - {h: "Difference", kind: info, items: ["65.70 per month", "Hourly charge only"]}
@check
Cost of two NAT gateways at 0.045 per hour for 730 hours? || 2 × 0.045 × 730 = 65.70 dollars per month.
@end

@concept Cost guardrails and budgets
@plain
Estimates become useful when a threshold turns them into a rule.
@problem
Comments are ignored under deadline pressure. Without a rule, cost review depends on someone caring.
@does
- Infracost policies (OPA or its own checks) can fail the pipeline when a pull request adds more than a set amount, or when a tag such as `cost-center` is missing.
- Cloud-side: AWS Budgets with alerts per account, and cost allocation tags activated in billing.
- Consistent tags (`team`, `env`, `service`) via the provider `default_tags` block make cost reports usable.
- Review the largest line items monthly: NAT, load balancers, idle volumes, over-sized instances.
@diagram layers
caption: Guardrails at several levels
layers:
  - {label: "Before merge", nodes: ["Infracost threshold|fail above limit|warn", "Tag policy|required tags|warn"]}
  - {label: "After apply", nodes: ["AWS Budgets|alerts on actual spend|info", "Cost Explorer by tag|owner reports|info"]}
@h Default tags
```hcl title="provider tags"
provider "aws" {
  region = "eu-west-1"

  default_tags {
    tags = {
      team = "platform"
      env  = "prod"
    }
  }
}
```
@end

@concept Security scanning layers
@plain
No single tool finds everything. Combine static checks on code, checks on the plan, and runtime posture checks.
@problem
Scanning only the code misses values known only at plan time. Scanning only runtime finds problems after they are live.
@does
- **Code**: Trivy (config scanning, which absorbed tfsec), Checkov, and `tflint` with the AWS ruleset for provider-specific errors.
- **Plan**: Checkov and OPA (Conftest) can evaluate the JSON plan, so computed and module values are visible.
- **Policy**: organisation rules such as no public S3 buckets, encryption required, approved regions.
- **Runtime**: AWS Config, Security Hub and Prowler find what slipped through or was changed by hand.
@diagram layers
caption: Defence in layers
layers:
  - {label: "Code", nodes: ["tflint|provider mistakes|app", "Trivy and Checkov|misconfiguration|app"]}
  - {label: "Plan", nodes: ["Conftest and OPA|policy on plan JSON|cp"]}
  - {label: "Runtime", nodes: ["AWS Config|rules|ok", "Security Hub|findings|ok"]}
@h Commands
```bash title="Scanners" lab
tflint --init && tflint
trivy config .
checkov -d . --framework terraform
terraform show -json tfplan > plan.json
checkov -f plan.json --framework terraform_plan
```
@end

@concept Triage: severities, suppressions and false positives
@plain
Scanners produce many findings. Triage decides which block the pipeline, which become tickets and which are accepted with a reason.
@problem
If every finding fails the build, teams disable the scanner. If none do, it is theatre.
@does
- Start in report-only mode, fix the critical ones, then fail on HIGH and CRITICAL only.
- Suppress with an inline comment that carries a reason, for example `#checkov:skip=CKV_AWS_18:access logs bucket itself` , so exceptions are visible in review.
- Keep a baseline file for old findings so only new ones block.
- Review suppressions quarterly; expired reasons are risk.
@diagram flow
caption: From finding to decision
nodes:
  - "Finding|scanner output|warn"
  - "Severity|critical, high, medium|info"
  - "Fix or suppress|reason in code|app"
  - "Gate|block on high and above|ok"
@h Inline suppression
```hcl title="suppression example" nocheck
resource "aws_s3_bucket" "access_logs" {
  #checkov:skip=CKV_AWS_18:This is the access log destination itself
  bucket = "acme-access-logs"
}
```
@check
Why require a reason in each suppression? || It makes the exception reviewable and lets later audits decide whether it still applies.
@end

@concept Secrets, state and supply chain risks
@plain
Terraform code and state are part of your attack surface. Credentials, modules and providers all come from somewhere.
@problem
A leaked state file exposes secrets. A tampered module or provider runs with your cloud credentials.
@does
- Do not put secrets in `.tf` or `.tfvars`. Use Secrets Manager or SSM, ephemeral values and write-only attributes where your provider and Terraform version support them (check the current docs).
- Mark outputs and variables `sensitive = true`; this only hides them in CLI output, state still holds them.
- Commit `.terraform.lock.hcl`, pin module versions to tags or digests, and review upgrades via Renovate or Dependabot.
- Scan for committed secrets with gitleaks or the GitHub secret scanning feature.
- CI uses OIDC with a role limited to what that stack needs.
@diagram flow
caption: Where secrets can leak
nodes:
  - "Code and tfvars|committed secrets|bad"
  - "Plan output|logs in CI|warn"
  - "State file|plain text values|warn"
  - "Safe path|secret manager reference|ok"
@h Reading a secret at runtime
```hcl title="secret reference"
data "aws_secretsmanager_secret_version" "api" {
  secret_id = "prod/api/key"
}
```
:::warn
Data sources still write the value into state. Prefer letting the application read the secret itself, and give Terraform only the ARN.
:::
@end
