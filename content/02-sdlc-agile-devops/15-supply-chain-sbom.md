---
title: Software supply chain, SBOM and quality gates
minutes: 40
objectives:
  - Explain what an SBOM is and generate one for an image
  - Describe provenance, signing and SLSA levels for a build
  - Define quality gates in CI that enforce standards without blocking flow
---
Modern applications are mostly assembled from other people's code. The software supply chain covers every step from a dependency download to the running container. Attacks such as SolarWinds, Log4Shell and compromised npm packages show why each link needs evidence.

@concept The supply chain and its attack points
@plain
Your product depends on source code, libraries, build tools, base images, the CI system and the registry. An attacker can compromise any link.
@problem
Code you never wrote runs with the same privileges as code you did. A poisoned dependency or build step ships to production with your signature on it.
@does
- Typical attacks: malicious or typosquatted packages, compromised maintainer accounts, tampered build systems, altered images in a registry, stolen CI credentials.
- Defences: pin versions and digests, use lock files, private mirrors, least-privilege CI, signed artifacts, provenance, verified at deploy.
- Know what you run: an inventory (SBOM) answers "are we affected" within minutes during the next big CVE.
@diagram flow
caption: Where attackers can interfere
nodes:
  - "Source|stolen commit rights|bad"
  - "Dependencies|malicious package|bad"
  - "Build|tampered CI|bad"
  - "Registry|swapped image|bad"
  - "Deploy|unverified artifact|warn"
@h Pin and lock
```bash title="Reproducible dependency installs" lab
pip install --require-hashes -r requirements.txt 2>/dev/null | head -3
npm ci 2>/dev/null | head -3          # installs exactly package-lock.json
docker pull alpine@sha256:0000000000000000000000000000000000000000000000000000000000000000 2>&1 | head -2
```
@check
Why use npm ci instead of npm install in CI? || It installs exactly what the lock file says and fails if it is out of sync.
@end

@concept SBOM - software bill of materials
@plain
An SBOM lists every component in a piece of software, with versions and licences, like an ingredients label.
@problem
When a new CVE appears, organisations spend days finding which of their hundreds of applications contain the affected library.
@does
- Formats: **SPDX** and **CycloneDX**; both are machine-readable (JSON).
- Generate during the build (Syft, Trivy, docker buildx `--sbom`) and store with the image in the registry.
- Scan the SBOM for vulnerabilities continuously, not only at build time, because new CVEs appear after release.
- Regulations such as US Executive Order 14028 and the EU Cyber Resilience Act push SBOM adoption.
@diagram flow
caption: SBOM lifecycle
numbered: true
nodes:
  - "Build|generate SBOM|app"
  - "Attach|store with the image|env"
  - "Scan continuously|new CVEs|warn"
  - "Query|who uses package X|ok"
@h Generate and query
```bash title="Create an SBOM and search it" lab
syft alpine:3.20 -o cyclonedx-json=/tmp/alpine.cdx.json 2>/dev/null
jq '.components | length' /tmp/alpine.cdx.json 2>/dev/null
jq -r '.components[] | select(.name=="busybox") | "\(.name) \(.version)"' /tmp/alpine.cdx.json 2>/dev/null
grype sbom:/tmp/alpine.cdx.json --fail-on high 2>/dev/null | head
```
@check
Why scan an SBOM again after release? || New vulnerabilities are published daily, so a component that was clean at build time may be vulnerable now.
@end

@concept Signing and verification
@plain
A digital signature proves who built an artifact and that it was not changed after signing. Verification checks that proof before use.
@problem
A tag like `v1.4.2` can be overwritten, and registries can be compromised. Without a signature, the cluster will run whatever it is told to.
@does
- **Cosign** (Sigstore) signs container images; keyless mode uses short-lived certificates tied to the CI identity (OIDC) and records the event in a public transparency log (Rekor).
- Attach signed attestations (SBOM, provenance, scan results) to the image digest.
- Enforce at admission: Kyverno `verifyImages`, Sigstore policy-controller, or Ratify.
- Always reference images by digest; signatures bind to the digest.
@diagram seq
caption: Keyless signing and verification
actors: ["CI job|build|app", "Fulcio and Rekor|Sigstore|cp", "Registry|stores image + signature|env", "Cluster|admission check|ok"]
steps:
  - "0>1: OIDC token, request certificate | tls"
  - "1>0: short-lived certificate | resp"
  - "0>2: push image and signature | req"
  - "3>2: fetch signature for digest | req"
  - "note 3..3: verify identity, issuer and transparency log"
  - "3>3: admit or reject | resp"
@h Commands
```bash title="Sign and verify with cosign" lab
cosign sign --yes registry.example.com/shop/api@sha256:3f1c0e9d 2>/dev/null
cosign verify registry.example.com/shop/api@sha256:3f1c0e9d \
  --certificate-identity-regexp 'https://github.com/example-org/shop/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com 2>/dev/null | head -5
```
@check
Why sign a digest and not a tag? || Tags are mutable, so a signature on a tag could cover different content later.
@end

@concept Provenance and SLSA
@plain
**Provenance** is a signed record of how an artifact was built: source repository, commit, builder and build steps. **SLSA** ("salsa") is a framework that grades how trustworthy a build process is.
@problem
A signature says who signed, not whether the build process was safe. A compromised developer laptop could sign malicious output.
@does
- SLSA Build levels: Level 1 provenance exists; Level 2 hosted build platform signs provenance; Level 3 hardened, isolated builds where provenance is hard to forge.
- GitHub Actions can generate SLSA provenance with the official generator or artifact attestations.
- Consumers verify provenance matches the expected repository and workflow before deploying.
- Hermetic, reproducible builds make independent verification possible.
@diagram layers
caption: SLSA build levels in short
layers:
  - {label: "Level 3", nodes: ["Hardened builder|isolated, non-forgeable provenance|ok"]}
  - {label: "Level 2", nodes: ["Hosted build service|signs provenance|app"]}
  - {label: "Level 1", nodes: ["Provenance exists|documents the build|info"]}
  - {label: "Level 0", nodes: ["No guarantees|trust the developer|bad"]}
@h Verify attestation
```bash title="Check provenance before deploy" lab
gh attestation verify oci://registry.example.com/shop/api@sha256:3f1c0e9d --owner example-org 2>/dev/null | head
cosign verify-attestation --type slsaprovenance registry.example.com/shop/api@sha256:3f1c0e9d \
  --certificate-identity-regexp 'https://github.com/example-org/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com 2>/dev/null | head -3
```
@check
What does provenance prove that a signature alone does not? || How and where the artifact was built, from which source.
@end

@concept Quality gates
@plain
A quality gate is an automated rule in the pipeline that must pass before a change moves on: tests pass, no critical vulnerabilities, coverage not reduced, policy satisfied.
@problem
Manual checks are skipped under pressure. Without gates, quality depends on individual diligence.
@does
- Typical gates: tests green, lint clean, no new HIGH vulnerabilities, signed image, coverage on new code above a threshold, deploy only from main.
- Gate on **new** problems (diff-based), not the entire backlog, so teams are not blocked by old debt.
- Keep gates fast and reliable; slow or flaky gates are bypassed.
- Branch protection and required status checks enforce them in Git hosting.
@diagram flow
caption: Gates between stages
nodes:
  - "PR|tests, lint, SAST|info"
  - "Build|image scan, SBOM, sign|warn"
  - "Staging|smoke and load tests|env"
  - "Production|approval + verified signature|ok"
@h Required checks
```bash title="Protect main with required checks" lab
gh api -X PUT repos/example-org/shop/branches/main/protection \
  -f required_status_checks.strict=true \
  -f 'required_status_checks.contexts[]=ci/test' \
  -f 'required_status_checks.contexts[]=ci/security' \
  -F enforce_admins=true \
  -f required_pull_request_reviews.required_approving_review_count=1 \
  -F restrictions=null 2>/dev/null | head -5
```
@check
Why gate on new findings rather than all findings? || Old debt would block every change; gating on new problems stops things getting worse while allowing gradual cleanup.
@end

@concept Code quality and technical standards
@plain
Static analysis and review keep code understandable: consistent style, low complexity, and no obvious defects.
@problem
Style arguments waste review time, and complex code hides defects.
@does
- Autoformatters (Black, gofmt, Prettier) end style debates; linters catch bugs.
- Track complexity and duplication in tools such as SonarQube; focus on trends.
- Code review focuses on design, correctness and clarity; automation handles the rest.
- Coverage is an indicator of untested areas, not proof of quality; use mutation testing for stronger evidence.
@diagram cmp
caption: Who checks what
cards:
  - {h: "Automation", kind: ok, items: ["Formatting and lint", "Known vulnerabilities", "Tests and coverage trend"]}
  - {h: "Humans", kind: app, items: ["Design and naming", "Edge cases and risks", "Knowledge sharing"]}
@h Pre-commit configuration
```yaml title=".pre-commit-config.yaml"
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: end-of-file-fixer
      - id: detect-private-key
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
      - id: ruff-format
```
@check
Why automate formatting? || It removes style debates from review and keeps diffs focused on logic.
@end
