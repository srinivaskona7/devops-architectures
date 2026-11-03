---
title: Terraform in CI with GitHub Actions and OIDC
minutes: 55
objectives:
  - Replace long-lived AWS keys with GitHub OIDC and a scoped IAM role
  - Build a pipeline that plans on pull requests and applies on merge with approval
  - Compare GitHub Actions with Atlantis and other runners
---
Terraform run from laptops does not scale: nobody knows who applied what, and credentials sit on many machines. A pipeline gives one controlled place to plan and apply.

@concept Why run Terraform in CI
@plain
A pipeline runs plan on every pull request and apply after merge, using one identity with the right permissions.
@problem
Laptop applies have no review trail, depend on local versions and credentials, and let people apply code that was never merged.
@does
- The plan appears on the pull request so reviewers see the real effect.
- Apply runs only from the main branch, after approval, with a saved plan.
- Versions and credentials are controlled in one place.
- Humans keep read-only access; break-glass access is logged.
@diagram flow
caption: Plan on PR, apply on merge
numbered: true
nodes:
  - "Pull request|code change|app"
  - "Plan job|comment with diff|info"
  - "Review and merge|approved|cp"
  - "Apply job|saved plan, approval gate|ok"
@end

@concept GitHub OIDC to AWS
@plain
GitHub Actions can request a short-lived signed token (OIDC) that proves "this job runs in repo X on branch Y". AWS trusts that token and hands out temporary credentials. No secret is stored in GitHub.
@problem
Static IAM access keys stored as secrets leak, never expire and are shared. OIDC replaces them with credentials that last about an hour.
@does
- In AWS, create an IAM **OIDC identity provider** for `token.actions.githubusercontent.com`.
- Create a role whose trust policy allows `sts:AssumeRoleWithWebIdentity` only for matching claims (`sub`, `aud`).
- The workflow needs `permissions: id-token: write` and the `aws-actions/configure-aws-credentials` action.
- Restrict `sub` to the repo and the branch or environment, never a wildcard on the whole organisation.
@diagram seq
caption: Token exchange, no stored secret
actors: ["GitHub job|workflow run|app", "GitHub OIDC|token issuer|ext", "AWS STS|trust check|cp", "AWS API|Terraform calls|info"]
steps:
  - "0>1: request ID token | req"
  - "1>0: signed JWT | resp"
  - "0>2: AssumeRoleWithWebIdentity | req"
  - "note 2..2: check sub and aud"
  - "2>0: temporary credentials | resp"
  - "0>3: terraform plan or apply | req"
@h Trust relationship in Terraform
```hcl title="oidc.tf"
resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "trust_apply" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:acme/infra:environment:prod"]
    }
  }
}

resource "aws_iam_role" "tf_apply_prod" {
  name               = "tf-apply-prod"
  assume_role_policy = data.aws_iam_policy_document.trust_apply.json
}
```
:::note
AWS validates GitHub's certificate chain itself for this provider, so the old thumbprint step is no longer needed in current provider versions. Check the current AWS and provider docs.
:::
@check
Which claim restricts which repository and branch can assume the role? || The sub claim, for example repo:acme/infra:ref:refs/heads/main or an environment name.
@end

@concept Separate roles for plan and apply
@plain
Use two roles: a read-only role for pull request plans and a write role for apply that only the main branch or a protected environment can assume.
@problem
If pull requests can assume an admin role, anyone who can open a PR (or a malicious dependency in it) can change production.
@does
- `tf-plan` role: read access plus the ability to read and lock state; its trust allows `pull_request` subjects.
- `tf-apply` role: write permissions; trust allows only `environment:prod` or the main branch.
- A GitHub **environment** with required reviewers makes the apply job wait for approval, and gives a `sub` of `repo:org/repo:environment:prod`.
- Scope permissions to the resources managed; avoid `AdministratorAccess` where practical, but accept it initially for infrastructure bootstrap roles.
@diagram cmp
caption: Least privilege per stage
cards:
  - {h: "tf-plan (pull request)", kind: ok, items: ["Read only plus state lock", "Trust: pull_request", "No writes to AWS"]}
  - {h: "tf-apply (main, approved)", kind: warn, items: ["Write permissions", "Trust: environment prod", "Required reviewers"]}
@end

@concept Plan on pull request
@plain
The plan job checks out the proposed code, plans, and posts the output to the pull request.
@problem
Reviewers need to see what the change does, not only the diff of the code.
@does
- Run `fmt`, `validate`, then `plan -out` and upload the plan as an artifact for apply, or re-plan at apply time.
- Post a trimmed plan as a PR comment or job summary (`$GITHUB_STEP_SUMMARY`).
- Use `concurrency` so only one run per stack executes at a time.
- State locking protects against two jobs colliding; `-lock-timeout` helps.
@diagram flow
caption: Plan job
nodes:
  - "checkout|PR code|app"
  - "OIDC login|tf-plan role|cp"
  - "init and plan|-out=tfplan|info"
  - "Summary|plan in the PR|ok"
@h Workflow
```yaml title=".github/workflows/plan.yml"
name: plan
on:
  pull_request:
    paths: ["infra/envs/prod/**", "infra/modules/**"]

permissions:
  id-token: write
  contents: read
  pull-requests: write

concurrency:
  group: tf-prod
  cancel-in-progress: false

jobs:
  plan:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111122223333:role/tf-plan-prod
          aws-region: eu-west-1
      - run: terraform init -input=false
      - run: terraform plan -input=false -lock-timeout=5m -out=tfplan
      - run: terraform show -no-color tfplan >> "$GITHUB_STEP_SUMMARY"
```
@end

@concept Apply on merge with approval
@plain
After merge to main, an apply job runs inside a protected GitHub environment. A reviewer approves, and Terraform applies.
@problem
Production changes need a deliberate second step and an audit trail, and they must apply what was reviewed.
@does
- Environment `prod` with required reviewers pauses the job until approval.
- Re-run `plan` in the apply job and fail if it differs from what was approved, or apply a saved plan artifact produced from the same commit.
- Only the main branch can deploy; use branch protection and CODEOWNERS for the `infra/` folder.
- Report the result back (job summary, chat notification).
@diagram flow
caption: Gated apply
numbered: true
nodes:
  - "Merge to main|reviewed|app"
  - "Plan again|same commit|info"
  - "Environment approval|required reviewers|warn"
  - "Apply|tf-apply role|ok"
@h Workflow
```yaml title=".github/workflows/apply.yml"
name: apply
on:
  push:
    branches: [main]
    paths: ["infra/envs/prod/**", "infra/modules/**"]

permissions:
  id-token: write
  contents: read

concurrency:
  group: tf-prod
  cancel-in-progress: false

jobs:
  apply:
    runs-on: ubuntu-latest
    environment: prod
    defaults:
      run:
        working-directory: infra/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.10.5
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111122223333:role/tf-apply-prod
          aws-region: eu-west-1
      - run: terraform init -input=false
      - run: terraform plan -input=false -out=tfplan
      - run: terraform apply -input=false tfplan
```
@check
Why use concurrency groups? || To stop two workflow runs from planning or applying the same stack at the same time.
@end

@concept Atlantis
@plain
Atlantis is a self-hosted service that listens to pull request webhooks and runs Terraform for you. You comment `atlantis plan` and `atlantis apply` on the PR.
@problem
Teams want pull request automation without writing pipelines for many repositories and directories.
@does
- Runs as a container, often on Kubernetes (a Helm chart exists), with its own cloud role.
- `atlantis.yaml` maps directories to projects and workflows; it locks a directory per PR so changes do not collide.
- Applies are usually required to be approved and mergeable first.
- Needs hardening: it holds powerful credentials and executes code from PRs. Restrict who can trigger it and where it runs.
@diagram seq
caption: Atlantis flow
actors: ["Developer|opens PR|app", "GitHub|webhook|ext", "Atlantis|runs Terraform|cp"]
steps:
  - "0>1: push or comment | req"
  - "1>2: webhook event | req"
  - "2>1: plan as PR comment | resp"
  - "0>1: atlantis apply | req"
  - "2>1: apply result | resp"
@h Repo config
```yaml title="atlantis.yaml"
version: 3
projects:
  - name: prod-network
    dir: infra/envs/prod/network
    autoplan:
      when_modified: ["*.tf", "../../modules/network/**/*.tf"]
      enabled: true
    apply_requirements: [approved, mergeable]
```
@end

@concept Choosing a runner
@plain
Terraform can run in plain CI, in Atlantis, or in a managed platform.
@problem
Each option trades control, effort and features.
@does
- **GitHub Actions** (or GitLab CI): no extra servers, uses OIDC, you write the plan and apply logic.
- **Atlantis**: PR-centred workflows with locking, self-hosted.
- **HCP Terraform / Terraform Enterprise, Spacelift, env0, Scalr**: managed runs, state, policy, drift detection and RBAC, at a cost.
- **Terraform in Jenkins**: works the same way; use credentials plugins or OIDC alternatives.
@diagram cmp
caption: Trade-offs
cards:
  - {h: "GitHub Actions", kind: ok, items: ["Already in use", "OIDC to cloud", "You maintain logic"]}
  - {h: "Atlantis", kind: info, items: ["PR comments and locks", "Self hosted and secured by you"]}
  - {h: "Managed platform", kind: info, items: ["Policy, drift, RBAC built in", "Licence cost"]}
@choose Pick a runner
GitHub Actions | you want few moving parts and use GitHub | you need cross-repo orchestration and drift dashboards
Atlantis | many directories and PR-comment workflow | you cannot secure and operate another service
Managed platform | policy, audit and RBAC needs at scale | budget or data residency rules forbid it
@end

@concept Pipeline safety checklist
@plain
A short list of controls that stop most CI mistakes and compromises.
@problem
A pipeline with cloud admin rights is a high-value target.
@does
- Pin actions to a full commit SHA for third party actions, and Terraform to an exact version.
- Never echo plan output without checking for secrets; mark sensitive values.
- Limit `pull_request_target` and workflows that run untrusted fork code with credentials. Forks should only run credential-free checks.
- Protect the state bucket and the apply role; separate accounts for prod.
- Require policy checks (checkov, OPA) and a no-delete rule unless approved.
- Alert on `force-unlock` and on role assumption outside the pipeline.
@diagram layers
caption: Defence in depth for the pipeline
layers:
  - {label: "Identity", nodes: ["OIDC subject limits|repo, branch, environment|cp", "Separate plan and apply roles|least privilege|cp"]}
  - {label: "Process", nodes: ["Branch protection|reviews required|info", "Environment approval|prod gate|info"]}
  - {label: "Supply chain", nodes: ["Pinned actions and versions|no surprises|ok", "Checks and policy|checkov, OPA|ok"]}
@check
Why must fork pull requests not get cloud credentials? || Untrusted code in the PR could use them to read or change your infrastructure.
@end
