---
title: GitHub Actions advanced recipes
minutes: 55
objectives:
  - Run only the jobs a change needs in a monorepo
  - Build matrices dynamically from repository content
  - Automate releases with semantic versioning and generated notes
---
These recipes solve the problems that appear once a repository has many services and many releases.

@concept Path filters for monorepos
@plain
A workflow can run only when certain files change, using `paths` on the trigger or a filter step inside the job.
@problem
In a repository with ten services, building everything on each commit wastes minutes and hides the real failure.
@does
- `on.pull_request.paths` skips the whole workflow when no listed file changed.
- Caveat: a skipped required check stays pending and blocks merging. Use a filter job instead when the check is required.
- `dorny/paths-filter` outputs one boolean per area; later jobs use `if: needs.changes.outputs.api == 'true'`.
- Always include shared paths (libraries, the workflow file itself) in each filter.
@diagram flow
caption: Detect changes then run only what is needed
nodes:
  - "changes job|paths-filter outputs|info"
  - "api filter true|build api|app"
  - "web filter false|job skipped|plain"
  - "gate job|required check passes|ok"
@h Workflow
```yaml title=".github/workflows/ci.yml"
name: ci
on:
  pull_request:
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      api: ${{ steps.f.outputs.api }}
      web: ${{ steps.f.outputs.web }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v3
        id: f
        with:
          filters: |
            api:
              - 'services/api/**'
              - 'libs/**'
            web:
              - 'services/web/**'
              - 'libs/**'
  api:
    needs: changes
    if: needs.changes.outputs.api == 'true'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make -C services/api test
  gate:
    if: always()
    needs: [changes, api]
    runs-on: ubuntu-latest
    steps:
      - run: test "${{ contains(needs.*.result, 'failure') }}" = "false"
```
:::tip
Make only the `gate` job a required check. It always runs and reports success when skipped jobs are fine.
:::
@check
Why can a path-filtered required check block merging? || When the workflow is skipped the check never reports, so branch protection waits for it forever.
@end

@concept Dynamic matrices
@plain
A job can output JSON that a later job uses as its matrix, so the list of things to build comes from the repository rather than the workflow file.
@problem
Hard-coded matrices go stale when a service is added, and teams forget to update them.
@does
- A first job computes a JSON array, for example the directories under `services/` that changed.
- The second job uses `strategy.matrix.service: ${{ fromJSON(needs.plan.outputs.services) }}`.
- Set `fail-fast: false` so one failing service does not hide the others, and `max-parallel` to protect shared resources.
- A matrix is limited to 256 jobs per run; check the current limits in the docs.
@diagram flow
caption: Plan job feeds a matrix
nodes:
  - "plan job|lists services as JSON|info"
  - "output|services array|cp"
  - "matrix job|one run per service|app"
@h Example
```yaml title="dynamic matrix"
jobs:
  plan:
    runs-on: ubuntu-latest
    outputs:
      services: ${{ steps.list.outputs.services }}
    steps:
      - uses: actions/checkout@v4
      - id: list
        run: |
          services=$(ls -d services/*/ | xargs -n1 basename | jq -R . | jq -sc .)
          echo "services=$services" >> "$GITHUB_OUTPUT"
  build:
    needs: plan
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        service: ${{ fromJSON(needs.plan.outputs.services) }}
    steps:
      - uses: actions/checkout@v4
      - run: make -C services/${{ matrix.service }} build
```
@end

@concept Caching and concurrency
@plain
Caches keep downloaded dependencies between runs. Concurrency groups stop duplicate runs from piling up.
@problem
Rebuilding dependencies on every run wastes minutes, and pushing three commits quickly starts three full pipelines.
@does
- Setup actions such as `actions/setup-node` and `actions/setup-go` have a built-in `cache` option keyed on the lock file.
- `actions/cache` takes a `key` and fallback `restore-keys`. Caches are scoped by branch, with the default branch as a shared fallback; unused caches are evicted (check the current size limits).
- `concurrency: group: ci-${{ github.ref }}` with `cancel-in-progress: true` cancels older runs of the same branch.
- Never cancel deploy jobs mid-run; use a separate group with `cancel-in-progress: false`.
@diagram cmp
caption: Cancel builds, queue deploys
cards:
  - {h: "CI group", kind: ok, items: ["cancel-in-progress true", "Newest commit wins"]}
  - {h: "Deploy group", kind: warn, items: ["cancel-in-progress false", "Runs one at a time"]}
@h Snippet
```yaml title="concurrency"
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```
@end

@concept Release automation with release-please or semantic-release
@plain
These tools read commit messages and decide the next version, write the changelog and create the GitHub release without human steps.
@problem
Manual version bumps and release notes are forgotten, inconsistent, and slow.
@does
- Commits follow Conventional Commits: `fix:` gives a patch, `feat:` a minor, and `feat!:` or a `BREAKING CHANGE:` footer a major release.
- **semantic-release** runs on each merge to main and publishes straight away.
- **release-please** opens a release pull request that accumulates changes; merging it tags and releases. It gives a human checkpoint.
- Both need a token that can push tags; the default `GITHUB_TOKEN` events do not trigger other workflows, so use a GitHub App token or PAT if a tag must start a build.
@diagram flow
caption: Commits to release
numbered: true
nodes:
  - "Conventional commits|feat and fix|app"
  - "Release PR or run|version computed|info"
  - "Tag and notes|v1.4.0|cp"
  - "Publish|image and artifacts|ok"
@h release-please workflow
```yaml title=".github/workflows/release.yml"
name: release
on:
  push:
    branches: [main]
permissions:
  contents: write
  pull-requests: write
jobs:
  release-please:
    runs-on: ubuntu-latest
    steps:
      - uses: googleapis/release-please-action@v4
        with:
          release-type: simple
```
@check
Which commit prefix triggers a minor bump? || feat; fix gives a patch and a breaking change gives a major.
@end

@concept Reusable workflows with typed inputs and secrets
@plain
A reusable workflow is called by other workflows with `workflow_call`, so one definition serves every repository.
@problem
Copying a 200-line pipeline to 30 repositories means 30 places to patch.
@does
- Define inputs with types and defaults; pass secrets explicitly or with `secrets: inherit` inside an organisation.
- Pin callers to a tag or full commit SHA of the shared repository, never a moving branch for critical pipelines.
- Reusable workflows can be nested to a limited depth; check the current limits.
- Outputs let the caller use results such as the image digest.
@diagram flow
caption: Many repositories one definition
nodes:
  - "service repo A|calls @v2|app"
  - "service repo B|calls @v2|app"
  - "platform repo|build-image.yml|cp"
@h Caller and definition
```yaml title="caller"
jobs:
  image:
    uses: acme/platform-workflows/.github/workflows/build-image.yml@v2
    with:
      image-name: shop-api
    secrets: inherit
```
```yaml title="platform-workflows/.github/workflows/build-image.yml"
on:
  workflow_call:
    inputs:
      image-name:
        type: string
        required: true
    outputs:
      digest:
        value: ${{ jobs.build.outputs.digest }}
jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      digest: ${{ steps.b.outputs.digest }}
    steps:
      - uses: actions/checkout@v4
      - id: b
        run: echo "digest=sha256:example" >> "$GITHUB_OUTPUT"
```
@end

@concept Environments, approvals and deployment protection
@plain
A GitHub **environment** attaches approvals, wait timers and secrets to a deploy job.
@problem
Everyone with write access could otherwise deploy to production by editing a workflow.
@does
- `environment: production` pauses the job until required reviewers approve.
- Environment secrets and variables are only available to jobs that target it; OIDC subject claims can include the environment name, so the AWS trust policy can allow only that.
- Restrict which branches may deploy to the environment.
- Private repository support for some protection features depends on plan; check the current docs.
@diagram seq
caption: Approval before production
actors: ["Workflow|deploy job|app", "GitHub|environment rules|cp", "Reviewer|team lead|ext"]
steps:
  - "0>1: request production | req"
  - "1>2: ask for approval | req"
  - "2>1: approved | resp"
  - "1>0: job runs with secrets | resp"
@h Job fragment
```yaml title="deploy job"
jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: production
    permissions:
      id-token: write
      contents: read
    steps:
      - run: echo "deploying"
```
@end

@concept Workflow dispatch, scheduled jobs and manual operations
@plain
`workflow_dispatch` lets a person start a workflow from the UI or API with inputs. `schedule` runs cron jobs.
@problem
Operations such as rollbacks, data refreshes and drift checks need a safe, auditable button instead of a laptop script.
@does
- Inputs can be strings, booleans, choices and environments.
- `schedule` uses UTC cron; runs may be delayed under load and are disabled after 60 days of repository inactivity on public repos (check the current docs).
- Dispatch from another workflow or script with `gh workflow run`.
- Every run is logged with the actor, which gives you an audit trail.
@diagram flow
caption: Rollback button
nodes:
  - "Engineer|clicks run workflow|app"
  - "Input|version v1.3.2|info"
  - "Workflow|deploys that tag|cp"
  - "Audit log|who, when, what|ok"
@h Rollback workflow
```yaml title="rollback.yml"
on:
  workflow_dispatch:
    inputs:
      version:
        description: Tag to deploy
        required: true
        type: string
      environment:
        type: choice
        options: [staging, production]
        default: staging
jobs:
  rollback:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - run: echo "Rolling back to ${{ inputs.version }}"
```
```bash title="Trigger from CLI" lab
gh workflow run rollback.yml -f version=v1.3.2 -f environment=staging
```
@end

@concept Composite actions and custom actions
@plain
A **composite action** bundles several steps into one reusable step, defined in an `action.yml`.
@problem
The same five steps (checkout, setup, cache, login, build) appear in every job.
@does
- Use composite actions for step bundles inside a job, reusable workflows for whole jobs.
- Each `run` step in a composite must set `shell`.
- Version with tags, and keep inputs documented.
- For complex logic, write a JavaScript or container action instead.
@diagram cmp
caption: Which reuse tool
cards:
  - {h: "Composite action", kind: ok, items: ["Bundle of steps", "Runs inside caller job", "Light"]}
  - {h: "Reusable workflow", kind: info, items: ["Whole jobs", "Own runner", "Secrets control"]}
@h action.yml
```yaml title=".github/actions/setup-go-build/action.yml"
name: setup-go-build
description: Checkout, set up Go and restore the cache
runs:
  using: composite
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-go@v5
      with:
        go-version-file: go.mod
    - run: go version
      shell: bash
```
@end
