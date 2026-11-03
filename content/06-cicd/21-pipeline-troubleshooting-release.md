---
title: Pipeline troubleshooting and release engineering
minutes: 60
objectives:
  - Diagnose common pipeline failures systematically
  - Version, tag and sign releases so they can be trusted and traced
  - Generate changelogs automatically from commit history
---
Pipelines fail in a few repeating ways. Knowing them turns a stuck afternoon into a five minute fix. The second half covers how a release becomes a trustworthy, traceable artifact.

@concept Method for debugging a failing pipeline
@plain
Treat the failure like any incident: find what changed, reproduce it, then fix the cause rather than rerunning.
@problem
Rerunning until green hides flaky tests, races and drifting dependencies, and trains the team to ignore red builds.
@does
- Read the first error, not the last; later errors are usually consequences.
- Ask what changed: code, workflow, runner image, dependency, secret, external service.
- Reproduce locally or in the same container image the job uses.
- GitHub Actions: enable step debug logging by setting the secret `ACTIONS_STEP_DEBUG` to `true`; re-run with the debug option.
- Record the root cause in the pull request or an issue.
@diagram flow
caption: Debugging loop
numbered: true
nodes:
  - "First error|read from the top|info"
  - "What changed?|code, image, dependency|warn"
  - "Reproduce|same container|app"
  - "Fix and note|root cause|ok"
@end

@concept Failure class, flaky tests
@plain
A flaky test passes and fails on the same code. Typical causes are timing, shared state, ordering and external services.
@problem
Flakiness destroys trust in CI and wastes reruns, and it multiplies: ten tests with 2 percent flake rate each fail about 18 percent of runs.
@does
- Arithmetic: probability that at least one of 10 independent tests flakes is 1 minus 0.98 to the 10th power, about 0.183.
- Quarantine: move a flaky test to a non-blocking job with a ticket and a deadline.
- Fix causes: replace sleeps with waits on conditions, isolate data per test, mock the network, fix random seeds.
- Track flake rate per test from JUnit results; many CI systems and tools report it.
@diagram cmp
caption: Handling a flaky test
cards:
  - {h: "Rerun until green", kind: bad, items: ["Hides the bug", "Wastes minutes", "Loses trust"]}
  - {h: "Quarantine and fix", kind: ok, items: ["Non-blocking job", "Ticket with owner", "Removed when fixed"]}
@check
Pass rate of a suite with 20 tests that each flake 1 percent of the time? || 0.99 to the 20th is about 0.818, so roughly 18 percent of runs fail.
@end

@concept Failure class, cache, dependency and runner problems
@plain
Many failures come from the environment around the code: stale caches, unpinned dependencies, full disks and rate limits.
@problem
The error message points at your code but the cause is elsewhere, so engineers debug the wrong layer.
@does
- Stale or corrupt cache: change the cache key, or run once without cache.
- Unpinned dependencies: a new upstream release breaks the build; commit lock files and pin base images by digest.
- Docker Hub pull rate limits: authenticate pulls or use an ECR pull-through cache.
- Runner out of disk or memory: look for `No space left on device` or killed processes (exit code 137); clean images or use a larger runner.
- Self-hosted runner offline: check the runner pod or service and its registration token.
@diagram flow
caption: Clues to causes
nodes:
  - "No space left|disk|bad"
  - "Exit 137|out of memory|bad"
  - "429 on pull|rate limit|warn"
  - "Works locally|image or cache differs|info"
@h Quick checks
```bash title="On a runner or in a job" lab
df -h
docker system df
free -m
docker run --rm -it ubuntu:22.04 bash   # reproduce in a clean image
```
@end

@concept Failure class, permissions, OIDC and secrets
@plain
Authentication failures are the most common reason a deploy job fails on first use.
@problem
Cloud errors are terse (`Not authorized to perform sts:AssumeRoleWithWebIdentity`) and the cause may be a single character in a trust policy.
@does
- OIDC: the job needs `permissions: id-token: write`. Without it no token is issued.
- The IAM trust policy `sub` condition must match the repository, branch or environment of the run, for example `repo:acme/shop:environment:production`.
- Secrets are not available to pull requests from forks, and environment secrets only to jobs that declare the environment.
- `GITHUB_TOKEN` permissions default can be read only; set `permissions:` per job explicitly.
@diagram flow
caption: Match the claim to the trust policy
nodes:
  - "Job token|sub claim from run|app"
  - "Trust policy|StringLike on sub|cp"
  - "Mismatch|AssumeRole denied|bad"
  - "Align both|role assumed|ok"
@check
Which permission makes a job able to request an OIDC token? || id-token: write
@end

@concept Failure class, deployment and timeout problems
@plain
A deploy job can pass its commands and still leave a broken release, or hang until the timeout.
@problem
`kubectl apply` returning success does not mean pods are healthy.
@does
- Wait for rollout: `kubectl rollout status deploy/api --timeout=180s`; fail the job and roll back on timeout.
- Common causes: image pull error, failing readiness probe, quota exceeded, missing secret.
- Set `timeout-minutes` on every job so a hang does not run for six hours (the default job limit).
- Print `kubectl describe` and recent events on failure, so the log has the answer.
@diagram flow
caption: Deploy with verification
numbered: true
nodes:
  - "kubectl apply|desired state|app"
  - "rollout status|waits for pods|info"
  - "Failure|print events|bad"
  - "Rollback|previous revision|warn"
@h Safe deploy step
```bash title="deploy.sh" lab
kubectl apply -f k8s/
if ! kubectl rollout status deploy/api --timeout=180s; then
  kubectl describe deploy/api | tail -30
  kubectl get events --sort-by=.lastTimestamp | tail -20
  kubectl rollout undo deploy/api
  exit 1
fi
```
@end

@concept Versioning schemes
@plain
A version is a promise about what changed. Semantic Versioning writes it as MAJOR.MINOR.PATCH.
@problem
Without a rule, consumers cannot tell if upgrading is safe, and operators cannot tell what is running.
@does
- **SemVer**: MAJOR for breaking changes, MINOR for compatible features, PATCH for compatible fixes. Good for libraries and APIs.
- **CalVer** (for example 2026.10.3): good for applications released on a schedule.
- Container images: tag with the version and the git SHA, and deploy by digest. Never deploy `latest`.
- Pre-releases: `1.4.0-rc.1`; build metadata after `+` does not affect precedence.
@diagram cmp
caption: Choosing a scheme
cards:
  - {h: "SemVer", kind: ok, items: ["Libraries and APIs", "Signals breaking changes"]}
  - {h: "CalVer", kind: info, items: ["Apps on a schedule", "Shows age at a glance"]}
  - {h: "Git SHA", kind: ok, items: ["Exact traceability", "Always add to images"]}
@h Image tags
```bash title="Tag and push" lab
VERSION=1.4.0
SHA=$(git rev-parse --short HEAD)
docker build -t registry.example.com/shop/api:${VERSION} -t registry.example.com/shop/api:${VERSION}-${SHA} .
```
@end

@concept Changelogs and release notes
@plain
A changelog tells users what changed between versions. It can be generated from Conventional Commit messages.
@problem
Hand-written release notes are skipped under time pressure, so users and support find out about changes from incidents.
@does
- Follow the Keep a Changelog layout: Added, Changed, Fixed, Removed, Security.
- Tools: release-please, semantic-release, git-cliff and GitHub's generated release notes read commit or PR titles.
- Quality depends on commit titles; enforce the format with commitlint or a PR title check.
- Link each entry to the pull request and mention migrations or breaking changes prominently.
@diagram flow
caption: From commits to notes
nodes:
  - "Commit titles|feat, fix, chore|app"
  - "Generator|git-cliff or release-please|cp"
  - "CHANGELOG.md|and release page|ok"
@h git-cliff run
```bash title="Generate" lab
git cliff --unreleased --tag v1.4.0 --prepend CHANGELOG.md
```
:::note
Check the current git-cliff documentation for configuration and flags.
:::
@end

@concept Signing releases and provenance
@plain
Signing proves who built an artifact. Provenance records how. Together they let a cluster refuse anything not built by your pipeline.
@problem
A registry compromise or a stolen credential could replace an image with a malicious one that has the same tag.
@does
- **cosign** signs container images. Keyless signing uses the CI job's OIDC identity and records the signature in the public Rekor transparency log.
- Generate an SBOM (Syft or Trivy) and attach it; produce SLSA provenance with the GitHub attestation or slsa-github-generator workflows.
- Verify at admission with a policy controller (Kyverno, Sigstore policy-controller or Connaisseur) that checks the signer identity.
- Sign the digest, not the tag, as tags move.
@diagram seq
caption: Keyless signing and verification
actors: ["CI job|OIDC identity|app", "Sigstore|Fulcio and Rekor|ext", "Cluster|admission policy|cp"]
steps:
  - "0>1: request certificate | req"
  - "1>0: short-lived cert | resp"
  - "0>1: log signature | req"
  - "2>1: check signer and log | req"
  - "2>2: allow only matching identity | tls"
@h Commands
```bash title="Sign and verify" lab
cosign sign --yes registry.example.com/shop/api@sha256:DIGEST
cosign verify registry.example.com/shop/api@sha256:DIGEST \
  --certificate-identity-regexp 'https://github.com/acme/shop/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```
@check
Why sign the digest and not the tag? || Tags can be moved to different content; a digest names exactly one image.
@end
