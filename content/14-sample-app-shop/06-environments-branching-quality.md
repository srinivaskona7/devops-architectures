---
title: Environments, branching and quality gates
minutes: 50
objectives:
  - Define dev, staging and prod and what is allowed to differ between them
  - Choose a branching and promotion flow that fits GitOps
  - Run the same quality checks locally, in pre-commit and in CI
---
The code exists; now decide where it runs and how a change travels from a laptop to production. The general theory is in the CI/CD folder (branching and release flows) and the SDLC folder. This file applies it to the Shop.

@concept The four environments
@plain
Local runs on a laptop with Docker Compose. Dev is a shared cluster for integration. Staging copies production closely. Prod serves customers.
@problem
Testing only on laptops hides configuration, network and scale problems. Testing directly in prod hurts customers.
@does
- Local: Compose, mock gateway, SQLite or a Postgres container.
- Dev: small EKS namespace, mock gateway, automatically updated from `main`.
- Staging: same node types and manifests shape as prod, mock gateway, used for load tests and the upgrade rehearsal.
- Prod: multi-AZ, real gateway, manual approval for promotion.
- Rule: the image is identical everywhere; only configuration (overlays) differs.
@diagram flow
caption: One artifact, four places
nodes:
  - "Local|Compose|plain"
  - "Dev|auto from main|info"
  - "Staging|release candidate|warn"
  - "Prod|approved|ok"
@end

@concept What may differ between environments
@plain
A written list of the knobs that change per environment, so nobody is surprised.
@problem
"It works in staging" is worthless if staging has a different replica count, database size and gateway.
@does
- Allowed to differ: replica counts, resource sizes, hostnames, gateway URL and secrets, log level, HPA limits, DB instance class.
- Must not differ: container image bytes, base manifests, probe paths, security context, NetworkPolicy shape.
- A drift test in CI renders all three overlays and compares the allowed fields (see the Kustomize files).
@diagram cmp
caption: Differ versus same
cards:
  - {h: "May differ", kind: warn, items: ["Replicas and HPA bounds", "CPU and memory sizes", "Hostnames and gateway URL", "Secrets and log level"]}
  - {h: "Must stay the same", kind: ok, items: ["Image digest", "Probes and security context", "NetworkPolicy shape", "Service ports"]}
@h Configuration table
```yaml title="docs/environments.yaml"
dev:
  cluster: shop-dev
  replicas: 1
  database: db.t4g.micro single-AZ
  gateway: upi-mock
  deploy: automatic on merge to main
staging:
  cluster: shop-staging
  replicas: 2
  database: db.t4g.medium multi-AZ
  gateway: upi-mock
  deploy: automatic on release tag candidate
prod:
  cluster: shop-prod
  replicas: 3
  database: db.t4g.medium multi-AZ
  gateway: real provider
  deploy: manual approval
```
@end

@concept Account and cluster separation
@plain
Production lives in its own AWS account; dev and staging share a second one. Each environment has its own cluster, database and state file.
@problem
A mistake or a leaked credential in dev must not reach production data.
@does
- AWS Organizations with two accounts: `shop-nonprod` (dev, staging) and `shop-prod`.
- Separate Terraform state per environment (see the Terraform folder on remote state).
- The CI role for non-prod cannot assume anything in the prod account; prod deploy uses a different OIDC role guarded by a GitHub environment.
- Namespaces `shop` in each cluster; do not share clusters between prod and anything else.
@diagram layers
caption: Blast-radius boundaries
layers:
  - {label: "Account shop-nonprod", nodes: ["EKS shop-dev|namespace shop|info", "EKS shop-staging|namespace shop|warn", "State bucket|per env key|plain"]}
  - {label: "Account shop-prod", nodes: ["EKS shop-prod|namespace shop|ok", "RDS prod|multi-AZ|cp", "State bucket|separate|plain"]}
@end

@concept Branching model for GitOps
@plain
Trunk-based development: short-lived branches merge to `main` through pull requests. Releases are tags. Environments are folders, not branches.
@problem
Long-lived environment branches (dev, staging, prod) drift, and merging between them is painful and error-prone.
@does
- Feature branches live under two days and need review and green CI.
- `main` is always deployable; every merge builds an image tagged with the commit SHA and updates the dev overlay.
- A tag like `v1.4.0` promotes the same SHA to staging; a manual approval then promotes to prod.
- A hotfix is a branch from the tag, merged to `main` and tagged again; no special environment branches exist.
@diagram flow
caption: Promotion path
nodes:
  - "Feature branch|pull request|plain"
  - "main|image abc1234, dev|info"
  - "Tag v1.4.0|staging|warn"
  - "Approval|prod|ok"
@h Commands
```bash title="Release a version" lab
git checkout main && git pull --ff-only
git tag -a v1.4.0 -m "Shop release 1.4.0"
git push origin v1.4.0
```
@check
Why use folders for environments instead of branches? || Folders keep one history, make diffs between environments visible in one tree and avoid merge drift.
@end

@concept Pull request rules and CODEOWNERS
@plain
Protect `main` so that a change needs a review from the owning team and passing checks.
@problem
Without rules, anyone can push a change that bypasses tests, or alter the payments code without its owners knowing.
@does
- Branch protection: required status checks (test, lint, scan), one approval, linear history, no force push.
- CODEOWNERS maps paths to teams: payments and `infra/` and `deploy/overlays/prod` need extra approvers.
- Squash merge keeps one commit per change, which makes rollback by revert simple.
@diagram flow
caption: Gates on a pull request
nodes:
  - "Push branch|developer|plain"
  - "CI checks|tests, lint, scan|info"
  - "Owner review|CODEOWNERS|warn"
  - "Squash merge|main|ok"
@h CODEOWNERS
```text title=".github/CODEOWNERS" nocheck
*                          @shop/developers
/services/payments/        @shop/payments @shop/security
/infra/                    @shop/platform
/deploy/overlays/prod/     @shop/platform @shop/sre
/docs/runbooks/            @shop/sre
```
@end

@concept Versioning and image tags
@plain
Every image is tagged with the short commit SHA. Releases add a semantic version tag that points at the same image.
@problem
The tag `latest` changes silently, so two pods of one Deployment can run different code, and rollback becomes guesswork.
@does
- ECR repositories use immutable tags, so a tag cannot be overwritten.
- Deployments reference the SHA (or better, the digest) in the Kustomize `images` block.
- The semantic version goes in a Git tag and an OCI label, not in the deployment.
- Pair this with the artifacts and supply chain chapter of the CI/CD folder.
@diagram flow
caption: One build, several names
nodes:
  - "Commit|abc1234|plain"
  - "Image|sha-abc1234|app"
  - "Git tag|v1.4.0 points here|info"
  - "Deployment|uses the SHA|ok"
@end

@concept Makefile as the one entry point
@plain
A Makefile gives short names to the common commands so developers, CI and Jenkins call the same thing.
@problem
Commands copied into pipeline YAML drift from what developers run locally, so CI fails for reasons nobody can reproduce.
@does
- `make test` runs pytest in every service. `make lint` runs ruff. `make up` starts Compose. `make render` renders all overlays.
- CI jobs call `make` targets, so a local failure equals a CI failure.
- Targets are phony and use a loop over the service folders.
@diagram flow
caption: Same targets everywhere
nodes:
  - "make test|developer laptop|plain"
  - "make test|pre-commit|info"
  - "make test|GitHub Actions|app"
  - "make test|Jenkins|app"
@h Makefile
```makefile title="Makefile" nocheck
SERVICES := catalog cart orders payments
.PHONY: test lint up down render

test:
	@for s in $(SERVICES); do (cd services/$$s && python -m pytest -q) || exit 1; done
	cd upi-mock && python -m pytest -q

lint:
	ruff check services upi-mock

up:
	docker compose up --build -d

down:
	docker compose down -v

render:
	@for e in dev staging prod; do kubectl kustomize deploy/overlays/$$e > /tmp/shop-$$e.yaml || exit 1; done
```
:::note
Makefile recipes need real tab characters. If you copy the text and your editor converts tabs to spaces, make reports "missing separator".
:::
@end

@concept Pre-commit and lint checks
@plain
Small automatic checks run before each commit: formatting, lint, YAML validity and secret detection.
@problem
Style arguments and accidental secrets cost review time; finding a leaked key after a push is expensive.
@does
- `ruff` lints and formats Python. `check-yaml` catches broken manifests. `detect-secrets` or `gitleaks` blocks credentials.
- The same hooks run in CI so they cannot be skipped with `--no-verify`.
- `terraform fmt -check` and `tflint` apply to `infra/`.
- Check the current hook repositories and their revisions before pinning.
@diagram flow
caption: Checks before code leaves the laptop
nodes:
  - "git commit|developer|plain"
  - "ruff and yaml|format and syntax|info"
  - "gitleaks|secret scan|warn"
  - "Commit allowed|clean|ok"
@h .pre-commit-config.yaml
```yaml title=".pre-commit-config.yaml"
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v5.0.0
    hooks:
      - id: check-yaml
        args: [--allow-multiple-documents]
      - id: end-of-file-fixer
      - id: trailing-whitespace
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.2
    hooks:
      - id: gitleaks
```
@end
