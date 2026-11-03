---
title: Pipeline security and secrets
minutes: 50
objectives:
  - Apply least privilege to pipeline identities and keep long-lived secrets out of CI
  - Place SAST, SCA, secret detection, container scanning and DAST in the pipeline
  - Protect the pipeline itself from poisoned inputs and unreviewed changes
---
The pipeline can change production, so it is a prime attack target. Secure it as you would a production system.

@concept Threats to a pipeline
@plain
Attackers target pipelines to steal secrets, push malicious code to artifacts, or use the runner as a foothold in your network.
@problem
Pipelines combine untrusted input (pull requests, dependencies) with trusted power (credentials, deploy rights). That mix is the weakness.
@does
- Common routes: injected commands from PR titles or branch names, poisoned third-party actions or dependencies, leaked secrets in logs, over-privileged tokens, shared persistent runners.
- Defence is layered: least privilege, isolation, pinning, review of pipeline changes, scanning and audit logs.
- Think in trust levels: code from forks is untrusted, code on a protected branch is trusted.
@diagram layers
caption: Trust boundaries in CI
layers:
  - {label: "Untrusted inputs", nodes: ["Fork PRs|no secrets|bad", "Third-party actions|pin and review|warn", "Dependencies|lockfiles, scanning|warn"]}
  - {label: "Pipeline", nodes: ["Runner|ephemeral, isolated|info", "Token|least privilege|info"]}
  - {label: "Trusted targets", nodes: ["Registry|signed pushes only|ok", "Cluster|GitOps or scoped role|ok"]}
@h Review checklist for any pipeline
```text title="Ask these questions"
1. Which events trigger it, and can a stranger trigger it?
2. What can the token and the cloud role do?
3. Which third-party code runs, and is it pinned?
4. Where do secrets appear, and could they reach logs?
5. Is the runner shared with less trusted jobs?
```
@check
What mix makes pipelines attractive targets? || Untrusted input combined with powerful credentials.
@end

@concept Least privilege for pipeline identities
@plain
Give each pipeline job only the permissions it needs, for as short a time as possible, using separate identities for separate stages.
@problem
One admin credential shared by every job means a compromise of the weakest job owns everything.
@does
- Separate roles: a read-only plan role, a build role that can push to one ECR repository, a deploy role limited to a namespace.
- Condition roles on branch, environment and repository through OIDC `sub` claims.
- Use IAM permission boundaries and short session durations. Review with IAM Access Analyzer and CloudTrail.
- Inside Kubernetes, bind CI to namespace-scoped Roles rather than ClusterRoles.
@diagram cmp
caption: One role per job type
cards:
  - {h: "Build role", kind: info, items: ["ecr push to shop repository", "No cluster access"]}
  - {h: "Deploy role", kind: app, items: ["EKS access to shop namespace", "No registry write"]}
  - {h: "Terraform plan role", kind: ok, items: ["Read-only", "Allowed on pull requests"]}
@h Scoped ECR push policy
```json title="IAM policy for the build role"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "ecr:GetAuthorizationToken",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ecr:BatchCheckLayerAvailability",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "arn:aws:ecr:eu-west-1:111122223333:repository/shop"
    }
  ]
}
```
@check
Why split the build and deploy roles? || A compromised build then cannot touch the cluster, and a deploy job cannot rewrite images.
@end

@concept Secrets management in CI
@plain
The best secret is the one you do not have. Prefer short-lived identity (OIDC) over stored keys. Where a secret is required, keep it in a dedicated store and fetch it at the moment of use.
@problem
Secrets pasted in CI variables are copied around, never rotated, and visible to anyone who can edit a workflow.
@does
- OIDC for AWS, GCP, Azure, Vault and many registries removes stored cloud keys.
- AWS Secrets Manager or HashiCorp Vault hold the rest. The job fetches them with its short-lived role.
- Scope secrets to environments and protected branches. Rotate on a schedule and after suspected exposure.
- Masking helps but is not a guarantee. Do not print, base64 or write secrets to artifacts.
@diagram flow
caption: Fetch at use time
nodes:
  - "Job|has OIDC identity|app"
  - "Assume role|temporary credentials|cp"
  - "Secrets Manager|read one secret|db"
  - "Use then discard|not stored|ok"
@h Read a secret in a job
```yaml title="Fetch from AWS Secrets Manager with the assumed role"
name: use-secret
on:
  workflow_dispatch:
permissions:
  id-token: write
  contents: read
jobs:
  run:
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111122223333:role/gha-shop-secrets
          aws-region: eu-west-1
      - name: Use the secret without printing it
        run: |
          TOKEN="$(aws secretsmanager get-secret-value --secret-id prod/shop/api --query SecretString --output text)"
          echo "::add-mask::$TOKEN"
          curl -fsS -H "Authorization: Bearer $TOKEN" https://api.example.com/health
```
:::warn
Prefer fetching secrets in the cluster through External Secrets, and do not give CI the ability to read production runtime secrets unless it truly deploys them.
:::
@end

@concept Secret detection
@plain
Secret scanners search code and Git history for keys, tokens and passwords. They run before commit, on pull requests and across history.
@problem
A key committed once stays in history forever, even after the file is edited. Attackers scan public and leaked repositories continuously.
@does
- Tools: **gitleaks**, **trufflehog**, GitHub secret scanning with push protection, GitLab secret detection.
- Pre-commit hooks stop leaks before they leave the laptop. Push protection blocks at the server.
- When a secret leaks, **revoke and rotate first**, then clean history. Rewriting history alone does not make the secret safe.
@diagram flow
caption: Layers of secret detection
nodes:
  - "Pre-commit hook|local|plain"
  - "Push protection|server blocks|info"
  - "CI scan|PR and history|warn"
  - "Revoke and rotate|if one leaks|bad"
@h Run gitleaks
```bash title="Scan the repository and its history" lab
gitleaks detect --source . --redact --verbose
gitleaks protect --staged --redact          # use as a pre-commit check
```
```yaml title=".pre-commit-config.yaml" nocheck
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2     # check the current release
    hooks:
      - id: gitleaks
```
@check
What is the first action after a secret leaks? || Revoke and rotate it. Cleaning history comes after.
@end

@concept SAST and SCA
@plain
**SAST** (static application security testing) analyses your source for insecure patterns. **SCA** (software composition analysis) checks your dependencies against vulnerability databases and licence rules.
@problem
Most code is written by others (libraries), and developers make common mistakes (injection, weak crypto). Humans miss both in review.
@does
- SAST: CodeQL, Semgrep, SonarQube, Bandit (Python), gosec (Go). Run on pull requests and report as SARIF into the code scanning view.
- SCA: Dependabot alerts, OSV-Scanner, Trivy, Snyk, Grype. Use lock files so results are exact.
- Tune thresholds: fail on high and critical with a fix available, report the rest. Too many findings train people to ignore the tool.
- Scans must have a path for documented exceptions, with an expiry date.
@diagram cmp
caption: What each scan finds
cards:
  - {h: "SAST", kind: info, items: ["Your code", "Injection, unsafe functions", "Fast, early"]}
  - {h: "SCA", kind: warn, items: ["Third-party packages", "Known CVEs and licences", "Needs lock files"]}
  - {h: "Secrets", kind: bad, items: ["Keys in code", "Entropy and patterns"]}
@h CodeQL in a workflow
```yaml title=".github/workflows/codeql.yml"
name: codeql
on:
  pull_request:
  schedule:
    - cron: "23 3 * * 1"
permissions:
  contents: read
  security-events: write
jobs:
  analyze:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: go
      - uses: github/codeql-action/analyze@v3
```
@end

@concept Container and IaC scanning
@plain
Scan the built image for vulnerable OS packages and libraries, and scan Dockerfiles, Kubernetes manifests, Helm charts and Terraform for misconfiguration before they are applied.
@problem
A clean application dependency list does not cover the base image, and a manifest running as root with a host mount passes unit tests.
@does
- **Trivy** and **Grype** scan images. `trivy image --severity HIGH,CRITICAL --exit-code 1` fails the build.
- **Trivy config**, **Checkov**, **kube-linter** and **kubeconform** scan IaC and manifests. Kyverno or Gatekeeper enforce the same rules at admission.
- Scan the image by digest after it is pushed, and re-scan on a schedule, since new CVEs appear daily.
- Use `.trivyignore` with reasons and dates for accepted risks.
@diagram flow
caption: Scans along the pipeline
nodes:
  - "Manifests and IaC|checkov, kube-linter|info"
  - "Build image|digest|app"
  - "Image scan|Trivy|warn"
  - "Admission policy|Kyverno|ok"
@h Scan commands
```bash title="Typical scanning step" lab
trivy image --severity HIGH,CRITICAL --exit-code 1 --ignore-unfixed "$IMAGE"
trivy config --severity HIGH,CRITICAL --exit-code 1 deploy/
kubeconform -strict -summary deploy/rendered.yaml
```
@check
Why re-scan images that already passed? || New vulnerabilities are published after the build.
@end

@concept DAST and runtime checks
@plain
**DAST** (dynamic application security testing) attacks a running test deployment from outside, like a scanner or attacker would. It finds problems that only appear at runtime, such as missing headers or exposed endpoints.
@problem
Static tools cannot see misconfigured servers, authentication flaws or behaviour that depends on deployment.
@does
- OWASP ZAP baseline scans are quick and passive. Full scans are active and can modify data, so run them only against test environments.
- Run after deployment to staging and before promotion. Use authenticated scans with a test user.
- Feed the OpenAPI definition to the scanner for API coverage.
- Keep scope limited with an allow list so the scanner never touches production or third parties.
@diagram flow
caption: DAST after staging deploy
nodes:
  - "Deploy staging|new version|env"
  - "ZAP scan|baseline or API|warn"
  - "Report|SARIF or HTML|info"
  - "Gate|promote if clean|ok"
@h ZAP baseline
```bash title="Passive baseline scan" lab
docker run --rm -v "$PWD:/zap/wrk" -t ghcr.io/zaproxy/zaproxy:stable \
  zap-baseline.py -t https://shop.staging.example.com -r zap-report.html -m 5
```
:::danger
Never run active DAST scans against production or against systems you do not own. They send attack traffic and can change or delete data.
:::
@end

@concept Protecting the pipeline definition
@plain
Anyone who can change the pipeline file can run code with its permissions. Treat changes to workflows, Jenkinsfiles and deployment repositories as security-sensitive.
@problem
A pull request that edits a workflow can add a step that exfiltrates secrets. Without protection, such a change can run before anyone reviews it.
@does
- Require reviews from a trusted team for pipeline files (CODEOWNERS).
- Run pipeline definitions from the protected branch for privileged jobs, not from the PR branch (GitHub uses the base for `pull_request_target`, GitLab has protected CI configuration, Jenkins runs the trusted Jenkinsfile for untrusted PRs via trust settings).
- Enable audit logs and alert on changes to secrets, environments, runners and branch protection.
- Use signed commits and branch rulesets on deployment repositories. Limit who can approve production.
@diagram layers
caption: Controls around the pipeline definition
layers:
  - {label: "Change control", nodes: ["CODEOWNERS|security reviews workflow edits|ok", "Rulesets|no force push, required checks|ok"]}
  - {label: "Execution", nodes: ["Privileged jobs on protected refs|secrets only there|cp", "Environment approvals|human gate|warn"]}
  - {label: "Detection", nodes: ["Audit log alerts|secrets and runner changes|info", "Workflow lint in CI|zizmor|info"]}
@h Deployment repository ruleset
```bash title="Inspect protection on the config repository" lab
gh api repos/my-org/shop-config/branches/main/protection \
  --jq '{reviews: .required_pull_request_reviews.required_approving_review_count, checks: .required_status_checks.contexts, admins: .enforce_admins.enabled}'
```
@check
Why require review for workflow file changes specifically? || The workflow runs with the pipeline permissions, so editing it can reach secrets and deploy rights.
@end
