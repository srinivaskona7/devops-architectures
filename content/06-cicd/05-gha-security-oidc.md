---
title: GitHub Actions security and OIDC to AWS
minutes: 50
objectives:
  - Restrict the token with permissions and avoid long-lived cloud keys
  - Configure OIDC federation so a workflow assumes an AWS role
  - Pin and vet third-party actions and avoid script injection and pull_request_target mistakes
---
A workflow runs code with access to your repository and often your cloud. Treat it as production infrastructure.

@concept The GITHUB_TOKEN and permissions
@plain
Every run gets an automatic token called `GITHUB_TOKEN`. The `permissions:` key sets exactly what that token may do, such as read contents or write packages.
@problem
A token with broad write access lets a compromised step push code, change releases or edit other workflows.
@does
- Set `permissions: {}` or `contents: read` at the top, then grant more per job.
- Common scopes are `contents`, `packages`, `pull-requests`, `id-token` and `attestations`.
- Once you set any permission, all unspecified ones become `none`.
- The default for new repositories and organisations should be set to read-only in settings.
@diagram layers
caption: Least privilege per job
layers:
  - {label: "Workflow default", nodes: ["contents read|safe baseline|ok"]}
  - {label: "Build job", nodes: ["contents read|checkout only|ok"]}
  - {label: "Publish job", nodes: ["packages write|push image|warn", "id-token write|OIDC|warn"]}
@h Minimal permissions
```yaml title="Deny by default, grant per job"
name: secure
on: [push]
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make test
  publish:
    needs: build
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
      id-token: write
    steps:
      - run: echo "publish"
```
@check
What happens to unlisted permissions when you set some? || They become none.
@end

@concept OIDC federation to AWS
@plain
Instead of storing an AWS access key in GitHub, the workflow asks GitHub for a short-lived signed identity token (a JWT). AWS verifies it and hands back temporary credentials for an IAM role.
@problem
Stored access keys are long-lived, can leak through logs or forks, and need manual rotation. Nobody knows which workflow used them.
@does
- AWS trusts GitHub as an **OIDC identity provider** at `token.actions.githubusercontent.com`.
- The role trust policy checks the `sub` claim (repository, branch or environment) and `aud` so only specific workflows can assume it.
- Credentials last about an hour and are never stored.
- The workflow needs `permissions: id-token: write`.
@diagram seq
caption: Keyless login from a workflow to AWS
actors: ["Workflow|runner|app", "GitHub OIDC|token issuer|cp", "AWS STS|identity check|ext"]
steps:
  - "0>1: request ID token | req"
  - "1>0: signed JWT with sub claim | resp"
  - "0>2: AssumeRoleWithWebIdentity | tls"
  - "note 2..2: verify sub and aud"
  - "2>0: temporary credentials | resp"
@h Trust policy and workflow
```json title="IAM role trust policy"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::111122223333:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:my-org/shop:environment:production"
      }
    }
  }]
}
```
```yaml title="Workflow assuming the role"
name: deploy
on:
  push:
    branches: [main]
permissions:
  id-token: write
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111122223333:role/gha-shop-deploy
          aws-region: eu-west-1
      - run: aws sts get-caller-identity
```
:::danger
A trust policy without a `sub` condition lets any repository on GitHub that knows the role ARN try to assume it. Always pin `sub` to your organisation and repository at least.
:::
@end

@concept Choosing the sub claim
@plain
The `sub` claim describes which workflow context is asking. Its format depends on the trigger: branch, tag, pull request or environment. The trust policy matches on it.
@problem
Too loose a match lets pull request code assume a production role. Too tight a match breaks legitimate runs.
@does
- Branch push: `repo:ORG/REPO:ref:refs/heads/main`.
- Environment job: `repo:ORG/REPO:environment:production`. With an environment, the claim uses the environment name instead of the branch.
- Pull request: `repo:ORG/REPO:pull_request`.
- Use `StringEquals` for an exact value and `StringLike` with a wildcard only where needed.
- Custom claim templates exist at organisation or repository level. Check the current docs.
@diagram cmp
caption: Which sub for which role
cards:
  - {h: "Plan role", kind: info, items: ["Read-only Terraform plan", "Allow pull_request sub", "No write actions"]}
  - {h: "Deploy staging", kind: app, items: ["Branch main or env staging", "Namespace scoped access"]}
  - {h: "Deploy production", kind: ok, items: ["Only environment production", "Reviewers required"]}
@h Different roles, different conditions
```json title="Allow either of two exact subs"
{
  "StringEquals": {
    "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
  },
  "StringLike": {
    "token.actions.githubusercontent.com:sub": [
      "repo:my-org/shop:ref:refs/heads/main",
      "repo:my-org/shop:environment:staging"
    ]
  }
}
```
@check
Which sub form do you use to bind a role to an approval gate? || The environment form, repo:ORG/REPO:environment:NAME.
@end

@concept Reaching Kubernetes on EKS from a workflow
@plain
After the workflow assumes an AWS role, it can ask EKS for a cluster token. The IAM role is mapped to Kubernetes RBAC with EKS access entries (or the older aws-auth ConfigMap).
@problem
You want deployments to the cluster without storing a kubeconfig with a long-lived token in secrets.
@does
- `aws eks update-kubeconfig` writes a kubeconfig that calls `aws eks get-token` for each request.
- An EKS **access entry** links the role ARN to an access policy or Kubernetes group.
- Bind the role to a namespace-level Role, not cluster-admin.
- The runner must reach the API endpoint. A private endpoint needs a self-hosted runner in the VPC or a network path.
@diagram flow
caption: Role to cluster permissions
nodes:
  - "OIDC role|gha-shop-deploy|ext"
  - "EKS access entry|maps role to group|cp"
  - "RBAC Role|deploy in namespace shop|env"
  - "kubectl apply|allowed in shop only|ok"
@h Grant and use
```bash title="Access entry for the role" lab
aws eks create-access-entry --cluster-name prod \
  --principal-arn arn:aws:iam::111122223333:role/gha-shop-deploy \
  --kubernetes-groups shop-deployers
aws eks update-kubeconfig --name prod --region eu-west-1
kubectl auth can-i create deployments -n shop
```
```yaml title="RBAC for the group" nocheck
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata: {name: shop-deployers, namespace: shop}
subjects: [{kind: Group, name: shop-deployers, apiGroup: rbac.authorization.k8s.io}]
roleRef: {kind: ClusterRole, name: edit, apiGroup: rbac.authorization.k8s.io}
```
@end

@concept Third-party actions and supply chain risk
@plain
An action is code that runs inside your job with your token and secrets. Using `uses: someone/action@v1` means trusting that person, and everyone who can move the `v1` tag.
@problem
Tags are mutable. If an action repository is compromised, an attacker can repoint a tag and steal secrets from every workflow that uses it. This has happened in real incidents.
@does
- Prefer actions from GitHub (`actions/*`), cloud vendors and verified creators, and review the source of small ones.
- Pin to a full commit SHA, with a comment showing the version.
- Allow-list actions at the organisation level (settings let you restrict to selected actions).
- Keep dependencies updated with Dependabot or Renovate so pinned SHAs do not rot.
@diagram flow
caption: From risky tag to pinned SHA
nodes:
  - "uses tag v1|mutable pointer|bad"
  - "Review source|read the action code|info"
  - "Pin full SHA|immutable|ok"
  - "Dependabot|proposes updates|app"
@h Pinning
```yaml title="Pin by commit SHA with a version comment" nocheck
steps:
  - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683  # v4.2.2
  - uses: aws-actions/configure-aws-credentials@e3dd6a429d7300a6a4c196c26e071d42e0343502  # v4.0.2
```
:::note
The SHAs above are examples of the format. Look up the real SHA for the release you want from the action repository before you use it.
:::
@check
Why is a tag not safe for third-party code? || Tags can be moved to different code by whoever controls the repository.
@end

@concept Script injection and pull_request_target
@plain
Expressions are replaced by text before the shell runs. If the text comes from an attacker (a branch name, issue title or PR body), it becomes shell code. `pull_request_target` runs with secrets in the context of the base branch, so checking out fork code there is dangerous.
@problem
A public repository accepts pull requests from strangers. A careless workflow can hand them your secrets or write token.
@does
- Pass untrusted values through `env:` and use `"$VAR"` in the script.
- Use `pull_request` for untrusted code. It runs without secrets for forks.
- Use `pull_request_target` only for tasks like labelling, and never check out and run the PR head code there.
- Split into two workflows with `workflow_run` when a privileged follow-up (comment with results) is needed.
@diagram cmp
caption: Unsafe versus safe handling
cards:
  - {h: "Unsafe", kind: bad, items: ["run uses title in the command line", "pull_request_target runs PR code", "Secrets exposed to forks"]}
  - {h: "Safe", kind: ok, items: ["Value passed as env variable", "Untrusted code runs without secrets", "Privileged step does not run PR code"]}
@h Safe pattern
```yaml title="Treat the title as data"
name: label
on:
  pull_request_target:
    types: [opened]
permissions:
  pull-requests: write
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - name: Show title safely
        env:
          TITLE: ${{ github.event.pull_request.title }}
        run: echo "Title is $TITLE"
```
@check
Why does env: protect against injection? || The value is set as a variable, not pasted into the script text, so the shell treats it as data.
@end

@concept Auditing workflows
@plain
Static analysis tools read your workflow files and report dangerous patterns, such as unpinned actions, excessive permissions and injectable expressions.
@problem
Reviewers cannot spot every risky pattern in hundreds of YAML files, and new patterns appear over time.
@does
- **zizmor** and **actionlint** find injection and misconfiguration problems. **OpenSSF Scorecard** scores repository practices including pinned dependencies and token permissions. Check each project docs for current checks.
- Run them as a workflow on pull requests that change `.github/workflows/`.
- Review the audit log for new secrets, runners and workflow changes.
@diagram flow
caption: Linting the pipeline itself
nodes:
  - "PR changes workflow|paths filter|plain"
  - "actionlint|syntax|info"
  - "zizmor|security findings|warn"
  - "Required check|blocks risky merge|ok"
@h Run the auditors
```bash title="Local audit" lab
actionlint
zizmor .github/workflows/
```
```yaml title="Run on workflow changes"
name: workflow-lint
on:
  pull_request:
    paths: [".github/workflows/**"]
permissions:
  contents: read
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: |
          bash <(curl -s https://raw.githubusercontent.com/rhysd/actionlint/main/scripts/download-actionlint.bash)
          ./actionlint
```
@end
