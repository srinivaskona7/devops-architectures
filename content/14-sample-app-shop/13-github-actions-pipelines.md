---
title: GitHub Actions pipelines for the Shop
minutes: 60
objectives:
  - Build a pull request pipeline that tests, lints and validates manifests
  - Build, scan and push images to ECR with OIDC and no stored keys
  - Update the deploy folder so Argo CD promotes a version through environments
---
The CI/CD folder covers workflow syntax, reuse and runner security. This file assembles the actual Shop pipelines. Action versions change often; check the current releases and pin by commit SHA in production (the checkout action is `{{v.action_checkout}}` at the time of writing).

@concept Pipeline overview
@plain
Three workflows: `ci.yml` on pull requests, `build.yml` on merges to `main`, and `promote.yml` for staging and prod.
@problem
One giant workflow mixes untrusted pull request code with push credentials, which is both slow and unsafe.
@does
- `ci.yml`: unit tests per service, lint, manifest render and validation, Terraform fmt and validate. No cloud credentials.
- `build.yml`: runs only on `main`; assumes the OIDC role, builds, scans, pushes, commits the new tag to the dev overlay.
- `promote.yml`: runs on a version tag or manual dispatch with an environment approval.
- Argo CD does the actual deploy (ADR 3).
@diagram flow
caption: From pull request to cluster
nodes:
  - "Pull request|ci.yml, no secrets|plain"
  - "Merge to main|build.yml, OIDC push|app"
  - "Dev overlay commit|new sha tag|info"
  - "Argo CD sync|cluster|ok"
@end

@concept The pull request workflow
@plain
Fast checks that need no credentials: run each service's tests in a matrix, lint, render the overlays.
@problem
Slow or flaky checks make people merge without waiting; checks with secrets let a forked pull request steal them.
@does
- A matrix runs the four services and the mock gateway in parallel (about 30 to 60 seconds each).
- Uses `pip` caching through `actions/setup-python` and `cache: pip`.
- `concurrency` cancels older runs of the same branch.
- Permissions default to `contents: read`.
@diagram layers
caption: Jobs in ci.yml
layers:
  - {label: "Parallel jobs", nodes: ["test matrix|5 services|app", "lint|ruff|info", "manifests|kustomize and kubeconform|info", "terraform|fmt and validate|info"]}
  - {label: "Gate", nodes: ["Required checks|branch protection|ok"]}
@h .github/workflows/ci.yml
```yaml title=".github/workflows/ci.yml"
name: ci
on:
  pull_request:
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
permissions:
  contents: read
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        service: [services/catalog, services/cart, services/orders, services/payments, upi-mock]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: ${{ matrix.service }}/requirements.txt
      - run: pip install -r ${{ matrix.service }}/requirements.txt
      - run: python -m pytest -q
        working-directory: ${{ matrix.service }}
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install ruff
      - run: ruff check services upi-mock
  manifests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Render and validate
        run: |
          set -e
          for env in dev staging prod; do
            kubectl kustomize deploy/overlays/$env > /tmp/$env.yaml
          done
          if grep -q upi-mock /tmp/prod.yaml; then echo "mock in prod"; exit 1; fi
  terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
      - run: terraform fmt -check -recursive infra
```
@end

@concept Build, scan and push with OIDC
@plain
On a merge to `main`, the workflow asks GitHub for an ID token, exchanges it for temporary AWS credentials and pushes images tagged with the commit SHA.
@problem
Long-lived access keys in repository secrets are the most common cloud credential leak from CI.
@does
- `permissions: id-token: write` lets the job request the token. `aws-actions/configure-aws-credentials` with `role-to-assume` does the exchange.
- Build uses Buildx with GitHub cache (`cache-from: type=gha`).
- Trivy scans each image and fails on HIGH or CRITICAL fixed vulnerabilities, before push.
- The image tag is `sha-` plus the full commit SHA. ECR tags are immutable, so re-running the push for the same commit fails with a tag-exists error; make the push step skip when `aws ecr describe-images` already finds the tag.
@diagram flow
caption: Build job steps
nodes:
  - "Checkout|source|plain"
  - "OIDC login|temporary credentials|ext"
  - "Build then scan|Buildx, Trivy|warn"
  - "Push to ECR|sha tag|ok"
@h .github/workflows/build.yml
```yaml title=".github/workflows/build.yml"
name: build
on:
  push:
    branches: [main]
    paths: ["services/**", "web/**", "upi-mock/**"]
permissions:
  contents: write
  id-token: write
env:
  AWS_REGION: ap-south-1
  REGISTRY: 111111111111.dkr.ecr.ap-south-1.amazonaws.com
jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        include:
          - {name: catalog, path: services/catalog}
          - {name: cart, path: services/cart}
          - {name: orders, path: services/orders}
          - {name: payments, path: services/payments}
          - {name: web, path: web}
          - {name: upi-mock, path: upi-mock}
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111111111111:role/shop-ci-ecr-push
          aws-region: ${{ env.AWS_REGION }}
      - id: ecr
        uses: aws-actions/amazon-ecr-login@v2
      - uses: docker/setup-buildx-action@v3
      - name: Build (load locally for scanning)
        uses: docker/build-push-action@v6
        with:
          context: ${{ matrix.path }}
          load: true
          tags: ${{ env.REGISTRY }}/shop/${{ matrix.name }}:sha-${{ github.sha }}
          cache-from: type=gha,scope=${{ matrix.name }}
          cache-to: type=gha,mode=max,scope=${{ matrix.name }}
      - name: Scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: ${{ env.REGISTRY }}/shop/${{ matrix.name }}:sha-${{ github.sha }}
          severity: HIGH,CRITICAL
          ignore-unfixed: true
          exit-code: "1"
      - name: Push
        run: docker push ${{ env.REGISTRY }}/shop/${{ matrix.name }}:sha-${{ github.sha }}
```
:::warn
`@master` for the Trivy action is shown to keep the page short. Pin every third-party action to a full commit SHA and let Dependabot update it.
:::
@end

@concept Tags: full SHA versus short SHA
@plain
A tag must be unique and traceable to a commit. The full 40 character SHA is unambiguous; the short form is easier to read.
@problem
Short SHAs can collide in large repositories, and an ambiguous tag makes the audit trail unclear.
@does
- The workflow above uses the full SHA in the tag. For humans, dashboards and release notes show the first 7 characters.
- A release tag such as `v1.4.0` is a Git tag only; images are never re-tagged. This keeps the digest the same from dev to prod.
- Argo CD shows the tag per Deployment, so any pod can be traced back to a commit in one lookup.
- For stricter pinning use the digest (`@sha256:...`) in the overlay; the build job can output it.
@diagram flow
caption: Traceability
nodes:
  - "Pod image tag|sha-40chars|app"
  - "ECR|immutable|cp"
  - "Commit|git show|plain"
  - "Pull request|reviewer, tests|ok"
@end

@concept Updating the deploy folder
@plain
After the image is pushed, a job edits the image tags in the dev overlay and commits to the repository. Argo CD sees the commit and syncs.
@problem
If CI applied manifests with `kubectl`, it would need cluster credentials, and the cluster state would not be in Git.
@does
- `kustomize edit set image shop/catalog=<registry>/shop/catalog:sha-...` rewrites the `images` block.
- The commit is made by a bot with a token limited to the `deploy/` path; the commit message links the source commit.
- A second `build` can start while the first commit is pending; the job rebases and retries once.
- The loop-prevention rule: `build.yml` ignores changes under `deploy/` through the `paths` filter shown above.
@diagram seq
caption: GitOps update after a build
actors: ["build job|Actions|app", "Git|main branch|plain", "Argo CD|controller|cp", "EKS dev|cluster|ok"]
steps:
  - "0>1: commit new image tags | req"
  - "2>1: poll or webhook | req"
  - "1>2: new revision | resp"
  - "2>3: apply rendered manifests | tls"
  - "3>2: health status | resp"
@h Job to append to build.yml
```yaml title=".github/workflows/bump-dev.yml"
name: bump-dev
on:
  workflow_run:
    workflows: [build]
    types: [completed]
    branches: [main]
permissions:
  contents: write
jobs:
  bump:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
      - name: Set image tags
        working-directory: deploy/overlays/dev
        run: |
          set -e
          TAG="sha-${{ github.event.workflow_run.head_sha }}"
          for svc in catalog cart orders payments web; do
            kustomize edit set image shop/$svc=111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/$svc:$TAG
          done
      - name: Commit
        run: |
          git config user.name "shop-bot"
          git config user.email "shop-bot@users.noreply.github.com"
          git commit -am "deploy dev ${{ github.event.workflow_run.head_sha }}"
          git pull --rebase origin main
          git push origin main
```
@end

@concept Promotion to staging and prod
@plain
A version tag runs a workflow that copies the dev tags into the staging overlay. Prod is a second job that waits for a GitHub environment approval.
@problem
Rebuilding for each environment changes the bytes; manual promotion by editing YAML is error-prone.
@does
- Trigger `on: push: tags: ["v*"]` or `workflow_dispatch`.
- Job `staging` uses `environment: staging`; job `prod` uses `environment: production` with required reviewers and a wait timer.
- Both jobs open or push a change to their overlay with the same tags; the image digest does not change.
- Optionally the prod job uses a different OIDC role (prod account) for any AWS call.
@diagram flow
caption: Promotion with approval
nodes:
  - "Tag v1.4.0|push|plain"
  - "staging job|copy tags, sync, smoke|info"
  - "Approval|required reviewers|warn"
  - "prod job|copy tags|ok"
@h .github/workflows/promote.yml
```yaml title=".github/workflows/promote.yml"
name: promote
on:
  push:
    tags: ["v*"]
permissions:
  contents: write
jobs:
  staging:
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
      - name: Copy tags from dev to staging
        run: python scripts/promote.py dev staging
      - run: |
          git config user.name "shop-bot"
          git config user.email "shop-bot@users.noreply.github.com"
          git commit -am "promote ${{ github.ref_name }} to staging"
          git push origin HEAD:main
  prod:
    needs: staging
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: actions/checkout@v4
        with:
          ref: main
      - run: git pull --ff-only
      - name: Copy tags from staging to prod
        run: python scripts/promote.py staging prod
      - run: |
          git config user.name "shop-bot"
          git config user.email "shop-bot@users.noreply.github.com"
          git commit -am "promote ${{ github.ref_name }} to prod"
          git push origin HEAD:main
```
```python title="scripts/promote.py"
import re
import sys
from pathlib import Path

src, dst = sys.argv[1], sys.argv[2]
registry_dst = {"staging": "111111111111", "prod": "222222222222"}.get(dst, "111111111111")

src_text = Path(f"deploy/overlays/{src}/kustomization.yaml").read_text()
tags = dict(re.findall(r"name: shop/(\w+)\n\s+newName: \S+\n\s+newTag: (\S+)", src_text))

path = Path(f"deploy/overlays/{dst}/kustomization.yaml")
text = path.read_text()
for svc, tag in tags.items():
    pattern = rf"(name: shop/{svc}\n\s+newName: \S+\n\s+newTag: )\S+"
    text, n = re.subn(pattern, rf"\g<1>{tag}", text)
    if n != 1:
        sys.exit(f"could not update {svc} in {dst}")
path.write_text(text)
print(f"{dst} now uses {tags} (registry account {registry_dst})")
```
:::note
A prod account cannot pull from the non-prod ECR unless a repository policy allows it. Either replicate images to the prod account (ECR replication) or let the prod account own its repositories and push there from the release job. Decide this in an ADR.
:::
@end

@concept Terraform workflow
@plain
Plan on pull requests, apply on merge with approval, one job per environment, never from laptops.
@problem
Infrastructure changes applied from a laptop have no review, no history and may use stale code.
@does
- PR job: `terraform init`, `fmt -check`, `validate`, `plan`, then upload the plan summary as a comment.
- Apply job: environment-protected, downloads the saved plan artifact and runs `terraform apply tfplan` so what was reviewed is what runs.
- A separate OIDC role per environment with permissions for Terraform (broad, so guard it: only the `infra` workflow on `main` may assume it).
- Concurrency group per environment so two applies never overlap.
@diagram flow
caption: Reviewed plan equals applied plan
nodes:
  - "Pull request|terraform plan|plain"
  - "Plan artifact|tfplan|info"
  - "Approval|environment|warn"
  - "terraform apply tfplan|exact plan|ok"
@h .github/workflows/infra.yml
```yaml title=".github/workflows/infra.yml"
name: infra
on:
  pull_request:
    paths: ["infra/**"]
  push:
    branches: [main]
    paths: ["infra/**"]
permissions:
  contents: read
  id-token: write
  pull-requests: write
concurrency:
  group: infra-prod
jobs:
  plan:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: infra/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::222222222222:role/shop-terraform-plan
          aws-region: ap-south-1
      - uses: hashicorp/setup-terraform@v3
      - run: terraform init -input=false
      - run: terraform validate
      - run: terraform plan -input=false -out=tfplan
      - uses: actions/upload-artifact@v4
        with:
          name: tfplan
          path: infra/envs/prod/tfplan
  apply:
    if: github.ref == 'refs/heads/main'
    needs: plan
    runs-on: ubuntu-latest
    environment: production
    defaults:
      run:
        working-directory: infra/envs/prod
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::222222222222:role/shop-terraform-apply
          aws-region: ap-south-1
      - uses: hashicorp/setup-terraform@v3
      - uses: actions/download-artifact@v4
        with:
          name: tfplan
          path: infra/envs/prod
      - run: terraform init -input=false
      - run: terraform apply -input=false tfplan
```
@end

@concept Pipeline timing and cost
@plain
A quick calculation of how long a build takes and what the minutes cost, so the pipeline stays fast.
@problem
A pipeline that grows to 20 minutes makes people batch changes, which makes releases riskier.
@does
- Targets: pull request feedback under 5 minutes; merge to dev deployed under 10 minutes.
- Example on public hosted runners: 6 build jobs in parallel x 3 minutes = 18 runner minutes per merge. At 20 merges a day and 22 working days: 18 x 20 x 22 = 7,920 minutes a month.
- Compare with the plan's included minutes and price (check current GitHub pricing); self-hosted runners on EKS (ARC, see CI/CD folder) become cheaper at high volume.
- Cache hits cut the build step from about 2 minutes to under 30 seconds.
@diagram flow
caption: Where the time goes
nodes:
  - "Checkout and login|20 s|plain"
  - "Build|60 to 120 s, cache|app"
  - "Scan|30 s|warn"
  - "Push and bump|20 s|ok"
@h Check the minutes
```python title="minutes.py" lab
jobs, minutes_each, merges_per_day, days = 6, 3, 20, 22
per_merge = jobs * minutes_each
print("runner minutes per merge:", per_merge)
print("runner minutes per month:", per_merge * merges_per_day * days)
```
@end
