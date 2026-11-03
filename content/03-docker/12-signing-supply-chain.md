---
title: Signing images and the supply chain
minutes: 40
objectives:
  - Describe the main supply chain threats to container images
  - Sign and verify images with cosign using keyless OIDC signing
  - Attach SBOMs and provenance and enforce verification at deploy time
---
Pulling an image is running someone else's code on your node. Signatures, SBOMs and provenance let you prove who built an image and from what.

@concept Supply chain threats
@plain
The supply chain is everything between source code and the running container: dependencies, base image, build system, registry and deploy tooling.
@problem
An attacker needs only one weak link: a typosquatted dependency, a poisoned base image, a stolen registry token, or a tag overwritten with a malicious build.
@does
- Dependency confusion and typosquatting in npm and PyPI.
- Compromised or stale base images with known CVEs.
- Compromised CI (stolen secrets, malicious pull request workflows).
- Registry tampering: pushing a different image under a trusted tag.
- Frameworks: SLSA levels for build provenance, NIST SSDF, CIS Docker Benchmark.
@diagram flow
caption: Where each defence applies
nodes:
  - "Source and deps|lockfiles, review|plain"
  - "Build|isolated CI, provenance|app"
  - "Registry|immutable tags, signing|cp"
  - "Deploy|verify signature and digest|ok"
@h Pin and verify inputs
```bash title="Lockfile habits" lab
npm ci --ignore-scripts                    # exact versions from package-lock.json
pip install --require-hashes -r requirements.txt  # every wheel hash must match
docker buildx imagetools inspect python:3.12-slim --format '{{.Manifest.Digest}}'   # digest to pin FROM
```
@end

@concept Signing with cosign
@plain
`cosign` (Sigstore) signs an image digest and stores the signature as another artifact in the same registry. Anyone can verify it against your identity or key.
@problem
Registry permissions say who can push, not who built the image. A signature binds the digest to a verified identity.
@does
- **Keyless**: in CI the OIDC token (GitHub Actions identity) gets a short lived certificate from Fulcio, and the signature is logged in the Rekor transparency log. No long lived private key to leak.
- **Key based**: `cosign generate-key-pair`, store the key in KMS (`awskms://`).
- Sign the digest, never a tag.
- Verification checks the certificate identity and issuer, not just that some signature exists.
@diagram seq
caption: Keyless signing in GitHub Actions
actors: ["Workflow|GitHub OIDC token|app", "Fulcio|certificate authority|cp", "Registry|stores signature|env", "Rekor|transparency log|ext"]
steps:
  - "0>1: OIDC token requests certificate | tls"
  - "1>0: short lived certificate | resp"
  - "0>2: push signature next to image | req"
  - "0>3: record entry | req"
@h Sign and verify
```yaml title="Signing step in the workflow" nocheck
permissions:
  id-token: write
  packages: write
  contents: read
steps:
  - uses: sigstore/cosign-installer@v3
  - name: Sign the pushed digest
    run: cosign sign --yes ghcr.io/${{ github.repository }}@${{ steps.build.outputs.digest }}
```
```bash title="Verify against the expected identity" lab
cosign verify ghcr.io/acme/shop-api@sha256:REPLACE_WITH_DIGEST \
  --certificate-identity-regexp '^https://github.com/acme/shop-api/.github/workflows/build.yml@refs/heads/main$' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```
@check
What does keyless signing remove from your operations? || The long lived private key that must be stored, rotated and protected.
@end

@concept SBOMs and attestations
@plain
An SBOM (software bill of materials) lists every package inside an image. An attestation is a signed statement about an image, such as its SBOM or build provenance.
@problem
When a new CVE like Log4Shell appears, you need to find every image that contains the affected library in minutes, not days.
@does
- Formats: SPDX and CycloneDX.
- Generate with `syft` or BuildKit: `docker buildx build --sbom=true --provenance=mode=max`.
- Attach as a signed attestation: `cosign attest --predicate sbom.spdx.json --type spdxjson IMAGE@DIGEST`.
- Scan the SBOM later with `grype` or `trivy sbom` without pulling the image again.
@diagram flow
caption: Generate once, reuse for scanning and audit
nodes:
  - "Image digest|built in CI|app"
  - "syft|lists packages|info"
  - "SBOM file|spdx json|env"
  - "cosign attest|signed and attached|ok"
  - "grype or trivy|scan on schedule|warn"
@h Commands
```bash title="Create and attach an SBOM" lab
syft ghcr.io/acme/shop-api@sha256:REPLACE_WITH_DIGEST -o spdx-json > sbom.spdx.json
cosign attest --yes --predicate sbom.spdx.json --type spdxjson ghcr.io/acme/shop-api@sha256:REPLACE_WITH_DIGEST
trivy sbom sbom.spdx.json --severity HIGH,CRITICAL
jq '.packages | length' sbom.spdx.json
```
@end

@concept Provenance and SLSA
@plain
Provenance is a signed record of how an image was built: which repository, commit, workflow and builder. SLSA is a graded framework (levels 1 to 3 for builds) for how trustworthy that record is.
@problem
A signature proves who signed, but not that the build used the claimed source. Provenance links image to commit.
@does
- BuildKit can emit SLSA provenance attestations automatically (`--provenance=mode=max`).
- GitHub offers `actions/attest-build-provenance` and the reusable `slsa-github-generator`.
- Verify with `cosign verify-attestation --type slsaprovenance` or `gh attestation verify`.
@diagram layers
caption: Increasing assurance
layers:
  - {label: "SLSA 3", nodes: ["Hardened, isolated builder|provenance cannot be forged by the build|ok"]}
  - {label: "SLSA 2", nodes: ["Hosted build service|signed provenance|info"]}
  - {label: "SLSA 1", nodes: ["Provenance exists|documented build|warn"]}
@h Verify with GitHub CLI
```bash title="Check an image attestation" lab
gh attestation verify oci://ghcr.io/acme/shop-api:sha-3f9c2ab --owner acme
```
@end

@concept Enforcing verification in Kubernetes
@plain
Signing only helps if the cluster refuses unsigned or unknown images. An admission controller checks the signature when a pod is created.
@problem
Without enforcement, anyone with `kubectl` access can run an arbitrary public image in your namespace.
@does
- Policy engines: **Kyverno** `verifyImages`, **Sigstore policy-controller**, OPA Gatekeeper with external data, or Ratify.
- Start in `Audit` mode, review violations, then switch to `Enforce`.
- Also restrict allowed registries and require digests.
- Combine with Pod Security and NetworkPolicy; admission is one control among several.
@diagram flow
caption: Admission checks the signature before scheduling
numbered: true
nodes:
  - "kubectl apply|pod with image digest|ext"
  - "API server|calls admission webhook|cp"
  - "Kyverno|verifies cosign signature|app"
  - "Allowed or denied|pod created or rejected|ok"
@h Kyverno policy
```yaml title="Require a signature from our workflow"
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-shop-images
spec:
  validationFailureAction: Audit
  webhookTimeoutSeconds: 30
  rules:
    - name: verify-signature
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["ghcr.io/acme/shop-*"]
          mutateDigest: true
          attestors:
            - entries:
                - keyless:
                    issuer: https://token.actions.githubusercontent.com
                    subject: https://github.com/acme/shop-api/.github/workflows/build.yml@refs/heads/main
                    rekor:
                      url: https://rekor.sigstore.dev
```
:::tip
Set `validationFailureAction: Audit` first. Switching straight to `Enforce` can block system pods and your own rollouts.
:::
@end

@concept Base image updates and dependency automation
@plain
Most vulnerabilities in a container arrive through the base image and dependencies, so keeping them current is the cheapest control available.
@problem
An image built once and never rebuilt gains new CVEs every week, while rebuilding by hand is forgotten.
@does
- Renovate or Dependabot open pull requests that bump `FROM` tags, digests and lock files.
- Rebuild on a schedule (weekly) even without code changes, so base image patches are picked up.
- Pin by tag and digest: `FROM python:3.12-slim@sha256:...`, and let the bot update both.
- Track end of life dates: Python minor versions and Node LTS lines are supported for a limited period.
@diagram flow
caption: Automated update loop
nodes:
  - "Renovate|detects a new digest|ext"
  - "Pull request|bumps FROM line|info"
  - "CI|build, test, scan|app"
  - "Merge and deploy|new signed image|ok"
@h Renovate configuration
```json title="renovate.json"
{
  "$schema": "https://docs.renovatebot.com/renovate-schema.json",
  "extends": ["config:recommended", "docker:pinDigests"],
  "schedule": ["before 6am on monday"],
  "packageRules": [
    {"matchDatasources": ["docker"], "matchUpdateTypes": ["minor", "patch", "digest"], "automerge": false}
  ]
}
```
@end
