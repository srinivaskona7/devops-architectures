---
title: Pipeline performance, DORA metrics and a worked EKS pipeline
minutes: 55
objectives:
  - Reduce pipeline time and cost with caching, parallelism and cancellation
  - Measure delivery performance with the four DORA metrics taken from pipeline data
  - Read a complete pipeline that builds, scans, signs and deploys a service to EKS
---
This closing section measures what the pipeline delivers and puts every earlier idea into one working example.

@concept Where pipeline time goes
@plain
Before optimising, measure. Split the total time into queue wait, setup, dependency download, build, test and publish. One or two of these usually dominate.
@problem
Teams guess and tune the wrong part, for example buying bigger runners when the real delay is a ten-minute queue or an uncached download.
@does
- Record per-step durations. GitHub shows them in the run view and the API gives timings. Jenkins and GitLab show stage times.
- Track the median and the 90th percentile of the pull request pipeline. Set a budget, for example ten minutes.
- Track queue time separately, since it signals capacity problems rather than slow jobs.
@diagram flow
caption: Pieces of one pipeline run
nodes:
  - "Queue wait|runner capacity|warn"
  - "Setup and checkout|cacheable|info"
  - "Dependencies|cacheable|info"
  - "Build and test|parallelisable|app"
  - "Publish|registry upload|env"
@h Pull run timings
```bash title="Median duration of recent successful runs" lab
gh run list --workflow ci.yml --status success --limit 50 --json createdAt,updatedAt \
  --jq '[.[] | ((.updatedAt|fromdate) - (.createdAt|fromdate))] | sort | .[length/2|floor]'
```
@check
Why track queue time separately? || It points at runner capacity, which needs a different fix than slow steps.
@end

@concept Caching and incremental work
@plain
Reuse work between runs: dependency caches, build caches, Docker layer caches and test result caches. Skip work when nothing relevant changed.
@problem
Fresh runners start empty, so every run repeats downloads and compilation.
@does
- Dependency caches keyed by lock file hash (see the GitHub Actions cache concept).
- Docker layer cache: registry cache (`type=registry`) or GitHub cache backend (`type=gha`) with `cache-to ... mode=max`.
- Order Dockerfile instructions so dependencies install before source is copied.
- Path filters and affected-target tools skip unrelated work. Remote build caches (Bazel, Gradle) share results between runs.
@diagram cmp
caption: Cache types
cards:
  - {h: "Dependency cache", kind: info, items: ["npm, pip, go mod", "Key from lock file"]}
  - {h: "Layer cache", kind: app, items: ["Docker build steps", "Registry or gha backend"]}
  - {h: "Remote build cache", kind: ok, items: ["Compiled outputs", "Shared across runs and people"]}
@h BuildKit cache in a workflow
```yaml title="Docker layer cache with the GitHub backend" nocheck
- uses: docker/setup-buildx-action@v3
- uses: docker/build-push-action@v6
  with:
    context: .
    push: false
    tags: shop:test
    cache-from: type=gha
    cache-to: type=gha,mode=max
```
@end

@concept Parallelism, sharding and cancellation
@plain
Run independent work at the same time, split big test suites into shards, and cancel runs nobody needs any more.
@problem
A single serial job of 40 minutes delays every change, and obsolete runs consume capacity.
@does
- Separate jobs for lint, unit tests and image build can run in parallel. Use `needs` only where truly needed.
- Shard tests with a matrix, giving each job a slice, then add a final job that checks all shards.
- Use `concurrency` with `cancel-in-progress` for pull request runs, and skip documentation-only changes with path filters.
- Balance by timing data when the tool supports it, so shards finish together.
@diagram flow
caption: Sharded tests
nodes:
  - "Prepare|build test binary|app"
  - "Shard 1 of 4|parallel|info"
  - "Shard 2 of 4|parallel|info"
  - "Shard 3 of 4|parallel|info"
  - "Shard 4 of 4|parallel|info"
  - "Gate|all shards green|ok"
@h Matrix shards
```yaml title="Four shards and an aggregate check"
name: sharded
on: [pull_request]
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true
jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        shard: [1, 2, 3, 4]
    steps:
      - uses: actions/checkout@v4
      - run: make test SHARD=${{ matrix.shard }} SHARDS=4
  tests-passed:
    needs: test
    if: always()
    runs-on: ubuntu-latest
    steps:
      - run: test "${{ needs.test.result }}" = "success"
```
@check
Why have a final aggregate job? || Branch protection can require one stable check name instead of every shard.
@end

@concept Cost control
@plain
Pipeline cost is minutes times price, plus storage for artifacts and caches. The largest savings come from running less, not from cheaper machines.
@problem
Unmanaged pipelines accumulate scheduled jobs, large retained artifacts and oversized runners.
@does
- Cancel superseded runs, filter by paths, and run expensive suites on merge or nightly rather than every push.
- Right-size runners: measure CPU and memory use, and pick the smallest size that keeps time within budget.
- Set artifact `retention-days`, prune old caches, and expire registry images with lifecycle rules.
- For self-hosted, use spot nodes and scale to zero outside working hours.
- Review the top ten most expensive workflows monthly.
@diagram cmp
caption: Savings ordered by effort
cards:
  - {h: "No effort", kind: ok, items: ["Cancel old runs", "Short retention", "Path filters"]}
  - {h: "Some effort", kind: info, items: ["Caching", "Test sharding", "Right-size runners"]}
  - {h: "More effort", kind: warn, items: ["Self-hosted on spot", "Remote build cache"]}
@h Estimate savings
```python title="What cancelling superseded runs could save" lab
pushes_per_pr = 4          # average pushes per pull request
cancelled_share = 0.5      # share of runs cancelled early
minutes_per_run = 12
prs_per_month = 600
saved = pushes_per_pr * cancelled_share * minutes_per_run * prs_per_month * 0.5
print("minutes saved per month about", int(saved))
```
:::note
The inputs are made-up. Replace them with your own measured numbers before reporting savings.
:::
@end

@concept The four DORA metrics
@plain
DORA research identifies four measures of software delivery performance: **deployment frequency**, **lead time for changes**, **change failure rate** and **time to restore service**. The last two measure stability, the first two measure throughput.
@problem
Without shared measures, teams argue about whether delivery is improving, and local optimisation (speed with no stability) goes unnoticed.
@does
- **Deployment frequency**: how often you deploy to production.
- **Lead time for changes**: from commit (or merge) to running in production.
- **Change failure rate**: the share of deployments causing a failure that needs a fix, rollback or hotfix.
- **Time to restore**: how long to recover from a failed production change or incident. Newer DORA reports also use a rework-related measure; check the current report for definitions.
- Use them to find constraints for a team, not to rank people or teams against each other.
@diagram layers
caption: Throughput and stability
layers:
  - {label: "Throughput", nodes: ["Deployment frequency|how often|app", "Lead time for changes|commit to production|app"]}
  - {label: "Stability", nodes: ["Change failure rate|share that fail|warn", "Time to restore|minutes to recover|warn"]}
@h Define the events you need
```yaml title="Minimal event model"
events:
  - {type: commit_merged, fields: [sha, merged_at]}
  - {type: deployment, fields: [sha, environment, finished_at, status]}
  - {type: incident, fields: [started_at, resolved_at, caused_by_sha]}
```
@check
Which two metrics measure stability? || Change failure rate and time to restore service.
@end

@concept Measuring DORA from the pipeline
@plain
The pipeline and Git already hold most of the data: merge time, deploy time, deploy result and rollback events. A small job or a tool joins them.
@problem
Manual surveys are inaccurate and nobody updates spreadsheets. Automatic collection gives trustworthy trends.
@does
- Emit a deployment event from the deploy job with commit SHA, environment, time and result. GitHub deployments, Argo CD notifications or a webhook to a metrics store all work.
- Lead time = deploy time minus the first commit time or merge time of each commit in the release. State your choice and keep it constant.
- Change failure: mark deployments linked to a rollback, hotfix or incident.
- Open source tools such as Apache DevLake, or Four Keys, or platform products compute these. Check which are maintained today.
@diagram flow
caption: From events to dashboard
nodes:
  - "Git and PR data|merge times|info"
  - "Deploy events|from CD tool|app"
  - "Incidents|from on-call tool|warn"
  - "Metrics store|Prometheus or warehouse|db"
  - "Dashboard|four numbers|ok"
@h Compute from a list of deployments
```python title="Frequency, lead time and failure rate" lab
from datetime import datetime as dt
from statistics import median

deploys = [  # (merged_at, deployed_at, failed)
    ("2026-10-01T09:00", "2026-10-01T09:40", False),
    ("2026-10-02T14:10", "2026-10-02T15:00", True),
    ("2026-10-05T10:00", "2026-10-05T10:30", False),
    ("2026-10-06T11:00", "2026-10-06T11:20", False),
]
lead = [(dt.fromisoformat(d) - dt.fromisoformat(m)).total_seconds() / 60 for m, d, _ in deploys]
print("deployments", len(deploys))
print("median lead time minutes", median(lead))
print("change failure rate", sum(f for *_, f in deploys) / len(deploys))
```
```bash title="Count production deployments with the GitHub API" lab
gh api "repos/my-org/shop/deployments?environment=production&per_page=100" --jq 'length'
```
@check
Where do you take change failure data from? || Deployments linked to rollbacks, hotfixes or incidents.
@end

@concept Worked example, the CI half
@plain
The service is a containerised Go API deployed to EKS. CI runs on pull request and on merge: test, build, scan, push to ECR by digest, sign, and open a change in the config repository.
@problem
Earlier concepts are separate. This example shows how they fit into one reviewable workflow with least privilege.
@does
- OIDC role for ECR push only. `permissions` set per job. Actions pinned by version here for readability; pin by SHA in production.
- Image tagged with the commit SHA (immutable repository), referenced by digest.
- Trivy fails the build on fixable high or critical findings. cosign signs the digest keylessly.
- Pull requests run test and build without push; merges to main push.
@diagram flow
caption: CI pipeline for the service
numbered: true
nodes:
  - "Test|unit tests|ok"
  - "Build|buildx with cache|app"
  - "Scan|Trivy fails on fixable high|warn"
  - "Push|ECR by digest|env"
  - "Sign|cosign keyless|cp"
@h ci.yml
```yaml title=".github/workflows/ci.yml"
name: ci
on:
  pull_request:
  push:
    branches: [main]
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
permissions:
  contents: read
env:
  AWS_REGION: eu-west-1
  REPO: shop
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version-file: go.mod
      - run: go vet ./... && go test -race ./...
  image:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      id-token: write
    outputs:
      digest: ${{ steps.push.outputs.digest }}
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: aws-actions/configure-aws-credentials@v4
        if: github.event_name == 'push'
        with:
          role-to-assume: arn:aws:iam::111122223333:role/gha-shop-build
          aws-region: ${{ env.AWS_REGION }}
      - id: ecr
        if: github.event_name == 'push'
        uses: aws-actions/amazon-ecr-login@v2
      - name: Build for scanning
        uses: docker/build-push-action@v6
        with:
          context: .
          load: true
          tags: shop:scan
          cache-from: type=gha
          cache-to: type=gha,mode=max
      - name: Scan
        uses: aquasecurity/trivy-action@0.28.0
        with:
          image-ref: shop:scan
          severity: HIGH,CRITICAL
          ignore-unfixed: true
          exit-code: "1"
      - id: push
        if: github.event_name == 'push'
        uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: ${{ steps.ecr.outputs.registry }}/shop:${{ github.sha }}
          cache-from: type=gha
      - if: github.event_name == 'push'
        uses: sigstore/cosign-installer@v3
      - if: github.event_name == 'push'
        run: cosign sign --yes "${{ steps.ecr.outputs.registry }}/shop@${{ steps.push.outputs.digest }}"
```
@check
Why does the pull request run skip the push and sign steps? || Untrusted branches should not get registry credentials or produce signed artifacts.
@end

@concept Worked example, the CD half
@plain
Deployment is separate: a second workflow updates the image digest in the config repository through a pull request for staging (auto-merged after checks) and production (needs approval). Argo CD then syncs.
@problem
CI must never hold cluster credentials, and production changes must be reviewed and recorded.
@does
- The workflow runs only after CI succeeded on main, using the digest output.
- It clones the config repository with a GitHub App token, edits the overlay with `kustomize edit set image`, and opens a pull request.
- Argo CD syncs after merge, uses a PreSync migration Job, Rollouts canary with analysis, and Kyverno verifies the signature at admission.
- Rollback is a revert pull request in the config repository.
@diagram seq
caption: From merge to production
actors: ["CI|workflow|app", "Config repo|Git|info", "Argo CD|sync|cp", "EKS|cluster|env"]
steps:
  - "0>1: PR with new digest | req"
  - "note 1..1: checks, review, merge"
  - "2>1: pull merged commit | req"
  - "2>3: apply, canary, verify | req"
  - "3>2: healthy | resp"
@h promote.yml and verification
```yaml title=".github/workflows/promote.yml"
name: promote
on:
  workflow_run:
    workflows: [ci]
    types: [completed]
    branches: [main]
permissions:
  contents: read
jobs:
  open-pr:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/create-github-app-token@v1
        id: app
        with:
          app-id: ${{ vars.CONFIG_APP_ID }}
          private-key: ${{ secrets.CONFIG_APP_KEY }}
          repositories: shop-config
      - uses: actions/checkout@v4
        with:
          repository: my-org/shop-config
          token: ${{ steps.app.outputs.token }}
      - name: Update the staging overlay
        working-directory: apps/shop/overlays/staging
        env:
          SHA: ${{ github.event.workflow_run.head_sha }}
        run: |
          kustomize edit set image "shop=111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:${SHA}"
      - uses: peter-evans/create-pull-request@v7
        with:
          token: ${{ steps.app.outputs.token }}
          branch: bump-shop-staging
          title: "shop staging ${{ github.event.workflow_run.head_sha }}"
```
```bash title="Verify the result" lab
argocd app wait shop-staging --health --timeout 300
kubectl -n shop-staging argo rollouts get rollout shop
cosign verify 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:SHA \
  --certificate-identity-regexp 'https://github.com/my-org/shop/.*' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```
:::tip
For a stricter chain, replace the tag with the digest from the ci workflow outputs, and let Kyverno `mutateDigest` pin pods to what was verified.
:::
@end
