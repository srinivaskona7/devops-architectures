---
title: DevSecOps in the pipeline
minutes: 45
objectives:
  - Place security checks at each stage of the pipeline and choose the right scanner type
  - Handle vulnerability findings with sensible triage and thresholds
  - Model threats early and enforce policy as code in Kubernetes and Terraform
---
DevSecOps makes security a shared, automated part of delivery. Instead of one late review, small checks run on every change, giving developers fast and specific feedback.

@concept Security checks along the pipeline
@plain
Each stage of the pipeline can run a different kind of check. Together they catch problems from the editor to production.
@problem
A single penetration test before release finds many issues at once, too late and too expensive to fix, so risks are accepted or the release slips.
@does
- **Pre-commit**: secret detection (gitleaks), lint.
- **Pull request**: SAST (static analysis, for example Semgrep, CodeQL), dependency scan (SCA), IaC scan (Checkov, tfsec/Trivy).
- **Build**: container image scan (Trivy, Grype), SBOM generation, image signing.
- **Deploy**: admission policy (Kyverno, OPA Gatekeeper), signature verification.
- **Run**: runtime detection (Falco), cloud posture and audit logs.
- **DAST** tests the running app from outside, usually in staging.
@diagram flow
caption: Security checks by stage
nodes:
  - "Commit|secrets scan|app"
  - "Pull request|SAST, SCA, IaC|info"
  - "Build|image scan, SBOM, sign|warn"
  - "Deploy|admission policy|env"
  - "Run|runtime detection|ok"
@h Pipeline fragment
```yaml title="CI security steps" nocheck
jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Secrets
        uses: gitleaks/gitleaks-action@v2
      - name: Dependencies and IaC
        run: trivy fs --scanners vuln,misconfig --severity HIGH,CRITICAL --exit-code 1 .
      - name: Image
        run: trivy image --severity HIGH,CRITICAL --exit-code 1 $IMAGE
```
@check
What does SAST analyse? || Source code, without running it, to find insecure patterns.
@end

@concept SAST, SCA and DAST
@plain
Three families of tests: SAST reads your code, SCA checks the third-party libraries you use, and DAST attacks the running application.
@problem
Each finds different problems. Relying on one leaves gaps: your code may be safe while a dependency is not.
@does
- **SAST**: injection flaws, hard-coded secrets, unsafe functions. Fast, in the PR, some false positives.
- **SCA**: known vulnerabilities (CVEs) and licences in dependencies. Most real-world risk is here.
- **DAST**: runtime issues such as missing headers, authentication flaws. Slower, needs a deployed app.
- **IAST** and **fuzzing** add instrumented or random-input testing for deeper coverage.
@diagram cmp
caption: What each test sees
cards:
  - {h: "SAST", kind: app, items: ["Your source code", "Early and quick", "Some noise"]}
  - {h: "SCA", kind: warn, items: ["Third-party packages", "CVE and licence data", "Highest practical value"]}
  - {h: "DAST", kind: env, items: ["Running application", "Black-box attacks", "Later and slower"]}
@h Try scanners locally
```bash title="Local scans" lab
trivy fs --scanners vuln --severity HIGH,CRITICAL . 2>/dev/null | head -20
semgrep --config auto --error . 2>/dev/null | head -20
gitleaks detect --no-banner 2>/dev/null | head -10
```
@check
Why is SCA often the highest value scan? || Most of the code in an application is third-party, and known CVEs in it are the most commonly exploited weaknesses.
@end

@concept Triage: severity, exploitability and thresholds
@plain
Scanners report thousands of findings. Triage decides which ones matter now, which can wait and which are not real.
@problem
A pipeline that fails on every finding is switched off. One that ignores them is useless.
@does
- Use severity (CVSS) together with **exploitability**: is it in the EPSS or CISA KEV list, reachable, internet-facing?
- Fail builds on new HIGH or CRITICAL findings with a fix available; allow exceptions with an owner and expiry date.
- **VEX** statements record that a CVE does not affect your product ("not_affected").
- Fix by updating base images and dependencies regularly; automate with Dependabot or Renovate.
@diagram flow
caption: Triage decision
numbered: true
nodes:
  - "Finding|CVE in a package|info"
  - "Reachable and exposed?|context matters|warn"
  - "Fix available?|upgrade or patch|app"
  - "Fix, accept with expiry, or mark not affected|record it|ok"
@h Ignore with an expiry
```text title=".trivyignore.yaml"
vulnerabilities:
  - id: CVE-2025-12345
    statement: Vulnerable function is not called; confirmed by code search.
    expired_at: 2027-01-31
```
:::tip
Time-limit every exception. Permanent ignores turn into forgotten risk.
:::
@check
Why combine severity with exploitability? || A critical CVE in unreachable code is less urgent than a medium one that is actively exploited and exposed.
@end

@concept Threat modelling
@plain
Threat modelling is a structured conversation: what are we building, what can go wrong, what will we do about it, and did we do a good job.
@problem
Scanners find implementation bugs, but not design flaws such as missing authorisation between services or an over-privileged role.
@does
- Draw a data flow diagram with trust boundaries (internet, cluster, database, third-party).
- Walk through **STRIDE**: spoofing, tampering, repudiation, information disclosure, denial of service, elevation of privilege.
- Record mitigations as backlog items with owners; revisit when the architecture changes.
- Takes an hour for a feature; far cheaper than fixing a design later.
@diagram flow
caption: Four questions of threat modelling
numbered: true
nodes:
  - "What are we building|data flow diagram|info"
  - "What can go wrong|STRIDE|warn"
  - "What will we do|mitigations|app"
  - "Did we do well|review and test|ok"
@h STRIDE table
```text title="STRIDE with a Kubernetes example"
Spoofing                 Pod impersonates another service        -> mTLS and service accounts
Tampering                Image altered in registry               -> signed images, digest pinning
Repudiation              No record of who changed a deployment   -> audit logs, GitOps history
Information disclosure   Secrets in env and logs                 -> secret manager, log scrubbing
Denial of service        Unbounded requests                      -> rate limits, resource limits
Elevation of privilege   Privileged pod or wide RBAC role        -> Pod Security restricted, least-privilege RBAC
```
@check
Where do you draw trust boundaries? || Wherever data crosses between zones of different trust, such as internet to cluster or service to database.
@end

@concept Policy as code
@plain
Security and compliance rules are written as code and enforced automatically at pull request time and at deploy time.
@problem
Written policies are not read, and manual reviews do not scale. Misconfigurations such as public buckets or privileged pods slip through.
@does
- Kubernetes admission control: **Pod Security Admission** (built in), **Kyverno** or **OPA Gatekeeper** for custom rules.
- Terraform and IaC: Checkov, Trivy, OPA/Conftest in CI.
- Start in audit mode, fix violations, then enforce.
- Exceptions are explicit in code and reviewed.
@diagram flow
caption: Where policy applies
nodes:
  - "PR|IaC and manifest scan|info"
  - "Admission|reject non-compliant objects|cp"
  - "Cluster|audit for drift|ok"
@h A Kyverno policy
```yaml title="Disallow privileged containers"
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-privileged
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: no-privileged
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        message: "Privileged containers are not allowed."
        pattern:
          spec:
            containers:
              - =(securityContext):
                  =(privileged): "false"
```
```bash title="Pod Security Admission labels" lab
kubectl label namespace shop pod-security.kubernetes.io/enforce=baseline pod-security.kubernetes.io/warn=restricted --dry-run=server -o yaml 2>/dev/null | head -12
```
@check
Why start policies in audit mode? || To find existing violations without breaking running workloads, then enforce once they are fixed.
@end

@concept Secrets and identity in the pipeline
@plain
The CI system holds the keys to production, so it is a prime target. Give each job short-lived, narrowly scoped credentials.
@problem
Long-lived cloud keys stored in CI settings are copied, leaked in logs and never rotated. A compromised pipeline then owns the cloud account.
@does
- Use OIDC federation: CI presents a signed token and assumes an AWS role with a trust policy limited to the repository and branch.
- Separate roles per environment; production deploy role usable only from protected branches and environments.
- Pin third-party actions to commit SHAs; restrict who can modify pipeline definitions.
- Mask secrets in logs and avoid passing them as command-line arguments.
@diagram seq
caption: GitHub Actions to AWS without stored keys
actors: ["Workflow|GitHub Actions job|app", "GitHub OIDC|token issuer|cp", "AWS STS|role assumption|ext"]
steps:
  - "0>1: request ID token | req"
  - "1>0: signed JWT with repo and ref | resp"
  - "0>2: AssumeRoleWithWebIdentity | tls"
  - "note 2..2: trust policy checks repo, branch and audience"
  - "2>0: temporary credentials | resp"
@h Trust policy and workflow
```json title="IAM trust policy condition"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::123456789012:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
      "StringLike": {"token.actions.githubusercontent.com:sub": "repo:example-org/shop:ref:refs/heads/main"}
    }
  }]
}
```
@check
What is the benefit of OIDC federation over stored access keys? || Credentials are short-lived and tied to a specific repository and branch, so there is nothing long-lived to steal.
@end

@concept Security culture and champions
@plain
Tools find issues; people prevent them. A security champion in each team connects developers with the security group and spreads practice.
@problem
A small central security team cannot review everything, and developers see them as a blocker.
@does
- Champions are developers who spend part of their time on security topics, with training and a direct line to specialists.
- Provide secure defaults: templates, libraries and golden paths with security built in.
- Measure outcomes: time to fix vulnerabilities, share of services with scans, mean age of open findings.
- Run blameless reviews of security incidents and share the lessons.
@diagram layers
caption: How security scales
layers:
  - {label: "Central", nodes: ["Security team|standards and tooling|cp"]}
  - {label: "Teams", nodes: ["Champions|local expertise|app", "Developers|own their code|app"]}
  - {label: "Automation", nodes: ["Secure templates|defaults|ok", "Pipeline checks|feedback in PRs|ok"]}
@h Metrics
```python title="Mean time to remediate" lab
open_days = {"critical": [2, 3, 5], "high": [9, 14, 20, 11], "medium": [40, 60]}
for sev, days in open_days.items():
    print(f"{sev:<9} mean time to fix {sum(days) / len(days):.1f} days")
```
@check
What is a security champion? || A developer in a product team who acts as the local link to security practice.
@end
