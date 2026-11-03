---
title: Artifacts, registries and supply chain security
minutes: 55
objectives:
  - Store and version artifacts in ECR with immutable tags and lifecycle rules
  - Generate SBOMs and sign images and attestations with cosign
  - Understand SLSA provenance and enforce verification at admission
---
Whatever your pipeline produces becomes the thing you run. Knowing where it came from and proving it was not altered is the heart of supply chain security.

@concept Artifacts and registries
@plain
An **artifact** is any output you deploy or depend on: container images, Helm charts, language packages, binaries. A **registry** is the versioned store where they live.
@problem
Artifacts kept on build agents or developer laptops cannot be reproduced, shared, scanned or traced, and disappear when the machine does.
@does
- OCI registries (ECR, GHCR, Harbor, Artifactory) store images and also Helm charts, SBOMs and signatures as OCI artifacts.
- Package registries (npm, PyPI, Maven, Go modules) are often proxied through one internal repository to cache and control what is allowed.
- Every artifact is addressed by name plus a tag (mutable label) or digest (immutable content hash).
@diagram flow
caption: Where artifacts go
nodes:
  - "CI build|image, chart, binary|app"
  - "Registry|ECR or GHCR|env"
  - "Scanner and signer|attach evidence|warn"
  - "Cluster|pulls by digest|ok"
@h See digest and artifacts
```bash title="Inspect an image in ECR" lab
aws ecr describe-images --repository-name shop --region eu-west-1 \
  --query 'sort_by(imageDetails,&imagePushedAt)[-3:].[imageTags,imageDigest,imagePushedAt]'
```
@check
What is the difference between a tag and a digest? || A tag is a movable label. A digest is the hash of the content and cannot change.
@end

@concept ECR configuration for CI
@plain
Amazon ECR is the registry you will usually use on EKS. A few settings make it safe: immutable tags, scan on push, encryption and lifecycle policies.
@problem
Default repositories allow overwriting tags and keep every image forever, which weakens traceability and increases cost.
@does
- **Tag immutability** prevents pushing a different image under an existing tag.
- **Lifecycle policies** expire untagged images and keep the last N tagged ones.
- **Enhanced scanning** (Amazon Inspector) scans continuously. Basic scanning scans on push.
- **Pull through cache** mirrors upstream registries such as Docker Hub into ECR to avoid rate limits.
- Repository policies and IAM limit who can push (the CI role) and pull (node roles).
@diagram layers
caption: Controls on a repository
layers:
  - {label: "Write path", nodes: ["CI role|ecr:PutImage only|warn", "Immutable tags|no overwrite|ok"]}
  - {label: "Hygiene", nodes: ["Lifecycle policy|expire old images|info", "Scan|on push or continuous|info"]}
  - {label: "Read path", nodes: ["Node role|pull only|app"]}
@h Create a hardened repository
```bash title="Repository with immutable tags and scanning" lab
aws ecr create-repository --repository-name shop --region eu-west-1 \
  --image-tag-mutability IMMUTABLE \
  --image-scanning-configuration scanOnPush=true \
  --encryption-configuration encryptionType=KMS
aws ecr put-lifecycle-policy --repository-name shop --region eu-west-1 \
  --lifecycle-policy-text file://lifecycle.json
```
```json title="lifecycle.json"
{
  "rules": [
    {
      "rulePriority": 1,
      "description": "Expire untagged after 7 days",
      "selection": {"tagStatus": "untagged", "countType": "sinceImagePushed", "countUnit": "days", "countNumber": 7},
      "action": {"type": "expire"}
    },
    {
      "rulePriority": 2,
      "description": "Keep last 50 tagged",
      "selection": {"tagStatus": "any", "countType": "imageCountMoreThan", "countNumber": 50},
      "action": {"type": "expire"}
    }
  ]
}
```
:::warn
With immutable tags, a pipeline that re-pushes `latest` or a fixed tag will fail. Use unique tags such as the commit SHA.
:::
@end

@concept Software bill of materials
@plain
An SBOM is a machine-readable list of everything inside an artifact: packages, versions and licences. The two common formats are SPDX and CycloneDX.
@problem
When a new vulnerability is announced, you need to know within minutes which images contain the affected library.
@does
- Tools such as **Syft** or **Trivy** generate an SBOM from an image or source tree.
- Store the SBOM next to the image in the registry as an attestation, so it travels with the digest.
- Scanners (Grype, Trivy) can scan the SBOM later without pulling the image again.
- BuildKit can also produce an SBOM and provenance during `docker buildx build --sbom=true --provenance=mode=max`.
@diagram flow
caption: SBOM lifecycle
nodes:
  - "Build image|digest known|app"
  - "Generate SBOM|Syft or BuildKit|info"
  - "Attach to image|signed attestation|cp"
  - "Query later|which images use log4j|ok"
@h Generate and scan
```bash title="SBOM with Syft, scan with Grype" lab
IMAGE=111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop@sha256:4f3a9c1d2b7e8a0c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4
syft "$IMAGE" -o spdx-json=sbom.spdx.json
grype sbom:sbom.spdx.json --fail-on high
```
@check
Why keep the SBOM instead of regenerating it? || It records exactly what shipped at build time and can be queried when new vulnerabilities appear, without access to the image.
@end

@concept Signing images with cosign
@plain
Signing attaches a cryptographic proof that a specific digest was published by a specific identity. **cosign** from the Sigstore project signs and verifies OCI artifacts.
@problem
Anyone with registry write access, or an attacker who gets it, can replace an image. Without signatures the cluster has no way to tell the legitimate image from a tampered one.
@does
- **Keyless signing**: the CI job gets an OIDC token, Sigstore's Fulcio issues a short-lived certificate tied to the workflow identity, and the signature is logged in the Rekor transparency log. No long-lived private key to protect.
- **Key-based signing**: a key pair, with the private key in AWS KMS (`awskms://` URIs).
- Always sign the **digest**, never a tag.
- Verification checks the certificate identity and issuer, not just that some signature exists.
@diagram seq
caption: Keyless signing in a workflow
actors: ["Workflow|CI job|app", "Fulcio|certificate authority|cp", "Rekor|transparency log|ext"]
steps:
  - "0>1: OIDC token, request certificate | tls"
  - "1>0: short-lived certificate | resp"
  - "note 0..0: sign image digest"
  - "0>2: record signature entry | req"
@h Sign and verify
```bash title="Keyless sign and verify" lab
cosign sign --yes "$IMAGE"      # in CI with id-token write permission
cosign verify "$IMAGE" \
  --certificate-identity "https://github.com/my-org/shop/.github/workflows/release.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```
```yaml title="Workflow step" nocheck
- uses: sigstore/cosign-installer@v3
- name: Sign by digest
  run: cosign sign --yes "${IMAGE}@${DIGEST}"
```
:::note
Check the current Sigstore docs, since cosign 2.x and 3.x changed some defaults for storing signatures and bundles.
:::
@end

@concept Provenance and SLSA
@plain
**Provenance** is a signed record of how an artifact was built: which source commit, which builder, which inputs. **SLSA** (Supply-chain Levels for Software Artifacts) defines levels of assurance for that process.
@problem
A signature proves who published an image, but not that the build ran from the expected source in a trustworthy environment. An attacker with a compromised build could sign a malicious image.
@does
- SLSA build track levels, in general terms: Build L1, provenance exists. Build L2, provenance is signed by a hosted build platform. Build L3, the build is hardened so the signing material is not accessible to the build steps. Check the current spec for exact wording.
- GitHub provides artifact attestations (`actions/attest-build-provenance`) and the SLSA generator reusable workflows run builds in isolated jobs.
- Provenance uses the in-toto attestation format with the SLSA predicate.
@diagram layers
caption: Rising assurance
layers:
  - {label: "Build L3", nodes: ["Hardened build|signing keys unreachable by steps|ok"]}
  - {label: "Build L2", nodes: ["Hosted build|platform signs provenance|info"]}
  - {label: "Build L1", nodes: ["Provenance exists|unsigned is acceptable|warn"]}
  - {label: "None", nodes: ["No record|trust the filename|bad"]}
@h Attest build provenance
```yaml title="GitHub provenance attestation"
name: release
on:
  push:
    tags: ["v*"]
permissions:
  contents: read
  id-token: write
  attestations: write
  packages: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: push
        uses: docker/build-push-action@v6
        with:
          push: true
          tags: ghcr.io/my-org/shop:${{ github.ref_name }}
      - uses: actions/attest-build-provenance@v2
        with:
          subject-name: ghcr.io/my-org/shop
          subject-digest: ${{ steps.push.outputs.digest }}
          push-to-registry: true
```
@check
What does provenance prove that a signature alone does not? || How and from which source the artifact was built, not only who published it.
@end

@concept Attestations
@plain
An attestation is a signed statement about an artifact, such as "this image was scanned and had no critical findings", "this is its SBOM", or "this is its provenance". It is attached to the image digest.
@problem
You want policies that say "only deploy images that passed tests and scans", and need evidence the cluster can check automatically.
@does
- `cosign attest --predicate sbom.json --type spdxjson IMAGE` attaches an SBOM. Other types: `slsaprovenance`, `vuln`, or custom.
- `cosign verify-attestation` retrieves and checks them, and can evaluate a policy with `--type` and CUE or Rego.
- The pipeline generates attestations at the stage that knows the fact: test results after tests, scan results after scan.
@diagram flow
caption: Evidence collected along the pipeline
nodes:
  - "Build|provenance|app"
  - "Scan|vulnerability attestation|warn"
  - "SBOM|spdx attestation|info"
  - "Registry|all bound to digest|env"
  - "Policy|checks before deploy|ok"
@h Attest and verify
```bash title="Attach and read an SBOM attestation" lab
cosign attest --yes --type spdxjson --predicate sbom.spdx.json "$IMAGE"
cosign verify-attestation --type spdxjson "$IMAGE" \
  --certificate-identity-regexp 'https://github.com/my-org/shop/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  | jq -r '.payload' | base64 -d | jq '.predicateType'
```
@end

@concept Admission verification in the cluster
@plain
A policy engine running as an admission controller can refuse to create pods whose images are not signed by your CI identity, or lack required attestations.
@problem
Signing is useless if the cluster accepts unsigned images anyway. The check must happen where workloads are admitted.
@does
- **Kyverno** `verifyImages` rules, **Sigstore policy-controller**, and **Ratify** with Gatekeeper can verify cosign signatures and attestations.
- Start in audit mode to see what would be blocked, then switch to enforce.
- Match by registry and repository, and require the exact certificate identity and issuer.
- The check can also convert tags to digests (mutation) so the pod runs what was verified.
@diagram seq
caption: Admission-time image verification
actors: ["Argo CD or kubectl|deploy|ext", "API server|admission|cp", "Kyverno|verifyImages|app"]
steps:
  - "0>1: create pod with image | req"
  - "1>2: admission review | req"
  - "note 2..2: fetch and check signature"
  - "2>1: allow or deny | resp"
@h Kyverno policy
```yaml title="Require signatures from the release workflow"
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
              kinds: [Pod]
      verifyImages:
        - imageReferences:
            - "111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop*"
          mutateDigest: true
          attestors:
            - entries:
                - keyless:
                    issuer: https://token.actions.githubusercontent.com
                    subject: https://github.com/my-org/shop/.github/workflows/release.yml@refs/heads/main
                    rekor:
                      url: https://rekor.sigstore.dev
```
:::warn
Switch from Audit to Enforce only after you checked every namespace, including system add-ons, or you may block essential pods. The Kyverno API changes between releases, so check the current docs.
:::
@check
Why start in audit mode? || It shows which existing workloads would be blocked, avoiding outages when enforcement begins.
@end

@concept Dependency and base image hygiene
@plain
Most vulnerabilities in your service arrive through dependencies and the base image. Pinning, updating and minimising them reduces what you must patch.
@problem
Unpinned dependencies make builds non-reproducible and let an upstream compromise reach production. Neglected base images accumulate known vulnerabilities.
@does
- Commit lock files, install from them (`npm ci`, `pip install --require-hashes`, `go mod verify`).
- Use minimal bases (distroless, Alpine, Chainguard-style images) and pin them by digest.
- Run Dependabot or Renovate for automatic update pull requests, and rebuild images on a schedule to pick up OS fixes.
- Prefer an internal proxy registry that can block known-malicious packages and new releases younger than a few days, where supported.
@diagram flow
caption: Keeping inputs healthy
nodes:
  - "Lock files|exact versions|ok"
  - "Pinned base digest|reproducible|info"
  - "Renovate PRs|small updates|app"
  - "Scheduled rebuild|OS patches|warn"
@h Renovate rule to pin digests
```json title="renovate.json"
{
  "extends": ["config:recommended", "docker:pinDigests", "helpers:pinGitHubActionDigests"],
  "schedule": ["before 6am on monday"],
  "packageRules": [
    {"matchUpdateTypes": ["minor", "patch"], "groupName": "non-major"}
  ]
}
```
@end
