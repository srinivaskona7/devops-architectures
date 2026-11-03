---
title: GitHub Actions fundamentals
minutes: 45
objectives:
  - Read a workflow file and explain events, jobs, steps and runners
  - Use contexts, expressions and conditions to control what runs
  - Speed up jobs with matrix builds, caching and artifacts
---
GitHub Actions runs workflows defined in YAML files under `.github/workflows/`. This section covers the building blocks you will use in every pipeline.

@concept Workflows, jobs and steps
@plain
A **workflow** is one YAML file. It contains **jobs**, and each job contains **steps**. Jobs run on separate machines at the same time unless you order them. Steps inside a job run in sequence on the same machine and share its filesystem.
@problem
You need a way to describe automation that is versioned with the code, runs on clean machines, and can be split into independent parts for speed.
@does
- A step either runs a shell command (`run`) or an action (`uses`), a reusable unit published as a repository.
- `needs` creates order between jobs. Without it, jobs run in parallel.
- Each job starts on a fresh runner, so files do not carry between jobs unless you upload them as artifacts or cache them.
@diagram layers
caption: How a workflow is organised
layers:
  - {label: "Workflow file", nodes: ["ci.yml|on push and pull_request|cp"]}
  - {label: "Jobs on separate runners", nodes: ["test|runs first|app", "build|needs test|app", "deploy|needs build|env"]}
  - {label: "Steps inside one job", nodes: ["checkout|uses an action|info", "setup|uses an action|info", "make test|run a command|ok"]}
@h A first workflow
```yaml title=".github/workflows/ci.yml"
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: "1.23"
      - run: go test ./...
  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t shop:${{ github.sha }} .
```
:::note
Action major versions change over time. Check the current docs for the latest tag of each action you use.
:::
@check
Do two jobs share files? || No. Each job gets a clean runner. Use artifacts or caches to pass data.
@end

@concept Events and triggers
@plain
The `on:` key says what starts a workflow: a push, a pull request, a schedule, a manual click, a call from another workflow, or an external webhook.
@problem
Running everything on every event wastes minutes and can expose secrets to code that should not have them. Different events need different behaviour.
@does
- `push` and `pull_request` with branch, tag and path filters.
- `workflow_dispatch` adds a manual run button with typed inputs.
- `schedule` uses cron syntax in UTC and runs on the default branch.
- `workflow_call` makes the workflow reusable. `repository_dispatch` lets an outside system trigger it.
- `release`, `merge_group`, `workflow_run` and `issue_comment` cover other cases.
@diagram cmp
caption: Common triggers and their use
cards:
  - {h: "pull_request", kind: info, items: ["Validate proposed changes", "Limited secrets for forks"]}
  - {h: "push to main or tag", kind: ok, items: ["Build and publish", "Deploy after merge"]}
  - {h: "schedule", kind: warn, items: ["Nightly scans", "Runs on default branch only"]}
  - {h: "workflow_dispatch", kind: app, items: ["Manual deploy or rollback", "Takes inputs"]}
@h Several triggers together
```yaml title="Triggers with filters and inputs"
name: deploy
on:
  push:
    branches: [main]
    paths-ignore: ["docs/**"]
  schedule:
    - cron: "17 2 * * 1-5"
  workflow_dispatch:
    inputs:
      environment:
        description: Target environment
        type: choice
        options: [staging, production]
        default: staging
jobs:
  show:
    runs-on: ubuntu-latest
    steps:
      - run: echo "target=${{ inputs.environment || 'staging' }}"
```
@check
Which branch does a schedule trigger run on? || The default branch.
@end

@concept Runners
@plain
A **runner** is the machine that executes a job. GitHub-hosted runners are fresh virtual machines (Ubuntu, Windows, macOS) created for each job. Self-hosted runners are machines you operate yourself.
@problem
You need clean, reproducible build environments without maintaining servers, and sometimes access to private networks, special hardware or large caches.
@does
- `runs-on: ubuntu-latest` picks a hosted runner. Pin a specific image label if you need stability, for example `ubuntu-24.04`.
- Larger hosted runners and arm64 runners are available on supported plans. Check the current docs for labels and pricing.
- `runs-on: [self-hosted, linux, x64]` matches labels on your own runners.
- Hosted runners are discarded after one job, which removes leftover state and secrets.
@diagram cmp
caption: Hosted versus self-hosted runners
cards:
  - {h: "GitHub-hosted", kind: ok, items: ["Fresh VM per job", "No servers to patch", "Public internet only unless extra setup"]}
  - {h: "Self-hosted", kind: warn, items: ["Reach private VPC and clusters", "You patch and secure them", "Needs isolation per job"]}
@h Choosing labels
```yaml title="Runner selection"
jobs:
  unit:
    runs-on: ubuntu-24.04
    steps:
      - run: uname -a
  arm-build:
    runs-on: ubuntu-24.04-arm
    steps:
      - run: uname -m
  private-deploy:
    runs-on: [self-hosted, linux, vpc-prod]
    steps:
      - run: kubectl version --client
```
@check
Why prefer ephemeral runners? || Each job starts clean, so one job cannot leave files or credentials for the next.
@end

@concept Contexts, expressions and conditions
@plain
Inside `${{ }}` you can read data about the run (contexts such as `github`, `env`, `secrets`, `matrix`, `needs`) and use functions and operators to decide what happens.
@problem
Static YAML cannot adapt to the branch, the event, the result of earlier jobs or inputs. Without expressions you would duplicate workflows.
@does
- `if:` skips a job or step. Status functions are `success()`, `failure()`, `always()` and `cancelled()`.
- `github.ref`, `github.event_name`, `github.actor` and `github.sha` describe the trigger.
- `needs.<job>.outputs.<name>` passes small values between jobs.
- Write step outputs to the file named by `$GITHUB_OUTPUT`.
@diagram flow
caption: Passing a value from one job to the next
nodes:
  - "Step writes|echo name=value to GITHUB_OUTPUT|app"
  - "Job outputs|mapped under outputs|info"
  - "needs context|read by later job|cp"
  - "Later job uses it|if or run|ok"
@h Outputs and conditions
```yaml title="Job output and if conditions"
name: outputs
on: [push]
jobs:
  prepare:
    runs-on: ubuntu-latest
    outputs:
      tag: ${{ steps.meta.outputs.tag }}
    steps:
      - id: meta
        run: echo "tag=sha-${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"
  publish:
    needs: prepare
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - run: echo "publishing ${{ needs.prepare.outputs.tag }}"
      - if: failure()
        run: echo "something earlier failed"
```
:::warn
Never put untrusted values such as a pull request title directly inside a `run:` line through `${{ }}`. Pass them in `env:` and quote the shell variable. This avoids script injection.
:::
@end

@concept Matrix builds
@plain
A matrix runs the same job many times with different values, such as several language versions or operating systems. GitHub creates one job per combination.
@problem
Testing against three runtime versions on two operating systems would otherwise mean six copied jobs that drift apart.
@does
- `strategy.matrix` lists values. `include` adds extra combinations and `exclude` removes some.
- `fail-fast: false` lets other combinations finish when one fails.
- `max-parallel` limits concurrency. A matrix can be generated from JSON by an earlier job with `fromJSON`.
@diagram flow
caption: One definition fans out into many jobs
nodes:
  - "Matrix|go 1.22, 1.23 x os|cp"
  - "Job 1|1.22 linux|app"
  - "Job 2|1.23 linux|app"
  - "Job 3|1.23 windows|app"
  - "Required check|all must pass|ok"
@h Matrix example
```yaml title="Test several versions"
name: matrix
on: [pull_request]
jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
        go: ["1.22", "1.23"]
        exclude:
          - os: windows-latest
            go: "1.22"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: ${{ matrix.go }}
      - run: go test ./...
```
@check
How do you stop one failure from cancelling the others? || Set fail-fast to false under strategy.
@end

@concept Dependency caching
@plain
The cache action stores files such as downloaded packages under a key, and restores them in a later run when the key matches.
@problem
Downloading the same dependencies on every run adds minutes and depends on external registries.
@does
- `actions/cache` takes a `path`, a `key` and optional `restore-keys` for partial matches.
- Build the key from a hash of the lock file, for example `hashFiles('**/go.sum')`. A changed lock file makes a new cache.
- Many setup actions (`setup-node`, `setup-go`, `setup-python`) have a built-in `cache` option.
- Caches are scoped by branch. A pull request can read the default branch cache but not the reverse. Old caches are evicted when the repository passes its size limit.
@diagram seq
caption: Cache hit and cache save
actors: ["Job|runner|app", "Cache|GitHub storage|ext"]
steps:
  - "0>1: restore key hash of lockfile | req"
  - "1>0: hit or miss | resp"
  - "note 0..0: build and test"
  - "0>1: save on miss | req"
@h Manual cache step
```yaml title="Cache the Go module directory"
name: cache
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/cache@v4
        with:
          path: ~/go/pkg/mod
          key: gomod-${{ runner.os }}-${{ hashFiles('**/go.sum') }}
          restore-keys: |
            gomod-${{ runner.os }}-
      - run: go build ./...
```
:::warn
A cache is not a trusted artifact. Never cache build outputs you will deploy, and do not let untrusted pull requests write caches that a release job restores.
:::
@end

@concept Artifacts
@plain
An artifact is a file or folder that a job uploads to the workflow run so that later jobs, or people, can download it. Examples are test reports, binaries and coverage files.
@problem
Jobs run on different machines, so a binary built in one job is not available in the next. Test reports also need to be readable after the runner is gone.
@does
- `actions/upload-artifact` and `actions/download-artifact` move data between jobs of one run.
- Artifacts have a retention period, 90 days by default and configurable. Set a shorter value to save storage.
- Use artifacts for outputs of a run, caches for inputs that speed it up.
- For container images, push to a registry instead.
@diagram flow
caption: Passing a build output to a test job
nodes:
  - "Build job|compiles binary|app"
  - "upload-artifact|stores the file|info"
  - "Run storage|kept N days|ext"
  - "Smoke job|download-artifact|ok"
@h Upload then download
```yaml title="Share a binary between jobs"
name: artifacts
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: go build -o shop ./cmd/shop
      - uses: actions/upload-artifact@v4
        with:
          name: shop-binary
          path: shop
          retention-days: 7
  smoke:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: shop-binary
      - run: chmod +x shop && ./shop --version
```
@check
When do you use cache and when artifact? || Cache speeds up inputs like dependencies. Artifacts carry outputs of the run between jobs or to people.
@end
