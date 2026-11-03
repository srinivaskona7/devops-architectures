---
title: GitHub Actions reuse and flow control
minutes: 45
objectives:
  - Share pipeline logic with reusable workflows and composite actions
  - Protect deployments with environments and approvals
  - Control parallel runs with concurrency and keep configuration in variables and secrets
---
Once you have more than a few repositories, copying YAML becomes the main source of drift. This section covers sharing logic and controlling when and where jobs run.

@concept Reusable workflows
@plain
A reusable workflow is a complete workflow that other workflows call as a job, using `on: workflow_call`. It can take inputs and secrets and return outputs.
@problem
Fifty repositories each with their own slightly different build and deploy workflow mean fifty places to fix a security issue.
@does
- The caller uses `uses: org/repo/.github/workflows/file.yml@ref` at job level.
- Inputs are typed. Secrets can be passed one by one or with `secrets: inherit` inside the same organisation.
- A reusable workflow can call others, up to a nesting limit documented by GitHub.
- Pin the ref to a tag or commit SHA so a change in the shared repository does not break everyone at once.
@diagram flow
caption: Many repositories, one shared workflow
nodes:
  - "Repo A|calls build.yml|app"
  - "Repo B|calls build.yml|app"
  - "platform-workflows|build.yml at a tag|cp"
  - "Job runs|in the caller context|ok"
@h Definition and caller
```yaml title="platform-workflows/.github/workflows/build.yml"
name: build
on:
  workflow_call:
    inputs:
      image-name:
        type: string
        required: true
    outputs:
      tag:
        value: ${{ jobs.build.outputs.tag }}
jobs:
  build:
    runs-on: ubuntu-latest
    outputs:
      tag: ${{ steps.t.outputs.tag }}
    steps:
      - uses: actions/checkout@v4
      - id: t
        run: echo "tag=${GITHUB_SHA::7}" >> "$GITHUB_OUTPUT"
      - run: docker build -t ${{ inputs.image-name }}:${GITHUB_SHA::7} .
```
```yaml title="Caller in an application repository"
name: ci
on: [push]
jobs:
  build:
    uses: my-org/platform-workflows/.github/workflows/build.yml@v1
    with:
      image-name: shop
```
@check
Where do you write `uses` for a reusable workflow? || At job level, in place of `runs-on` and `steps`.
@end

@concept Composite actions
@plain
A composite action bundles several steps into one reusable step. It lives in a folder with an `action.yml` file and is called with `uses:` inside a job.
@problem
Several workflows repeat the same four setup steps (checkout, set up tool, restore cache, login). You want one name for them without a whole separate job.
@does
- Declared with `runs: using: composite` and a list of `steps`.
- Every `run` step must say which `shell` to use.
- Runs inside the caller job on the same runner, so files are shared. A reusable workflow runs as its own jobs.
@diagram cmp
caption: Reusable workflow versus composite action
cards:
  - {h: "Reusable workflow", kind: app, items: ["Whole jobs, own runners", "Called at job level", "Good for full pipelines"]}
  - {h: "Composite action", kind: info, items: ["A group of steps", "Called as a step", "Good for setup snippets"]}
@h A composite action
```yaml title=".github/actions/setup-ecr/action.yml"
name: Setup ECR login
description: Log in to Amazon ECR
inputs:
  region:
    description: AWS region
    default: eu-west-1
runs:
  using: composite
  steps:
    - uses: aws-actions/amazon-ecr-login@v2
      id: login
    - shell: bash
      run: echo "Registry is ${{ steps.login.outputs.registry }}"
```
```yaml title="Using it from the same repository" nocheck
steps:
  - uses: actions/checkout@v4
  - uses: ./.github/actions/setup-ecr
```
@check
What must every run step in a composite action declare? || The shell.
@end

@concept Environments and approvals
@plain
A GitHub **environment** such as `production` is a named target with its own rules, secrets and variables. A job with `environment: production` waits for those rules.
@problem
Production credentials in repository-wide secrets can be used by any branch or workflow. You need a gate that a person or policy must pass first.
@does
- Required reviewers pause the job until one approves in the UI.
- Deployment branch rules limit which branches can deploy, for example only `main`.
- Wait timers add a delay. Environment secrets are only released after the rules pass.
- The environment appears in the deployments view, giving a history of what ran where.
- Availability of some protection features depends on plan and repository visibility. Check the current docs.
@diagram seq
caption: A production deploy waits for approval
actors: ["Workflow|deploy job|app", "Environment|production rules|cp", "Reviewer|human|ext"]
steps:
  - "0>1: job requests production | req"
  - "1>2: review requested | req"
  - "2>1: approved | resp"
  - "1>0: secrets released, job runs | resp"
@h Using an environment
```yaml title="Deploy job bound to an environment"
name: deploy
on:
  push:
    branches: [main]
jobs:
  staging:
    runs-on: ubuntu-latest
    environment: staging
    steps:
      - run: echo "deploy to staging"
  production:
    needs: staging
    runs-on: ubuntu-latest
    environment:
      name: production
      url: https://shop.example.com
    steps:
      - run: echo "deploy to production"
```
:::tip
Use OIDC with a trust policy bound to the environment name (see the OIDC concept) so only approved jobs can assume the production role.
:::
@end

@concept Concurrency control
@plain
The `concurrency` key gives runs a group name. Only one run per group is active at a time, and you choose whether the older run is cancelled or the new one waits.
@problem
Two deploys to the same environment at once can overwrite each other. Ten quick pushes to a pull request waste minutes on runs nobody will look at.
@does
- For pull request CI, use `cancel-in-progress: true` so only the latest push is tested.
- For deployments, keep `cancel-in-progress: false` so a running deploy is never cut in half. Newer runs queue, and pending ones in the same group are replaced by the newest.
- Group names can use expressions such as the ref or environment name.
@diagram flow
caption: Concurrency group serialises deploys
nodes:
  - "Run 1|deploying|warn"
  - "Run 2|pending|plain"
  - "Run 3|replaces run 2|plain"
  - "Group production|one at a time|cp"
@h Two common patterns
```yaml title="CI cancels old runs, deploy does not"
name: patterns
on:
  pull_request:
  push:
    branches: [main]
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
jobs:
  deploy:
    if: github.event_name == 'push'
    runs-on: ubuntu-latest
    concurrency:
      group: deploy-production
      cancel-in-progress: false
    steps:
      - run: echo "deploying"
```
@check
Why not cancel an in-progress deployment? || It could stop halfway and leave the environment in a mixed state.
@end

@concept Variables, secrets and configuration
@plain
Variables (`vars`) hold plain configuration. Secrets hold sensitive values and are masked in logs. Both can be set per repository, per environment or per organisation.
@problem
Hard-coding account IDs, regions and passwords into YAML makes workflows unshareable and leaks credentials into Git history.
@does
- Read them as `${{ vars.NAME }}` and `${{ secrets.NAME }}`. Environment-level values override repository ones.
- Secrets are not passed to workflows triggered from forks (except through special events), and are masked only when the exact value appears.
- Prefer short-lived credentials from OIDC over long-lived stored secrets wherever the target supports it.
- Registered secrets cannot be read back through the UI, only replaced.
@diagram layers
caption: Where a value can be defined, most specific wins
layers:
  - {label: "Environment", nodes: ["production vars and secrets|only after approval|ok"]}
  - {label: "Repository", nodes: ["repo vars and secrets|this repository only|app"]}
  - {label: "Organisation", nodes: ["org vars and secrets|shared by policy|cp"]}
@h Setting and using them
```bash title="GitHub CLI" lab
gh variable set AWS_REGION --body eu-west-1 --env production
gh secret set SLACK_WEBHOOK --env production    # prompts for the value
gh variable list --env production
```
```yaml title="Reading them" nocheck
env:
  AWS_REGION: ${{ vars.AWS_REGION }}
  SLACK: ${{ secrets.SLACK_WEBHOOK }}
```
:::warn
Secrets printed after transformation (base64, split strings) are not masked. Never echo them, and avoid passing them as command-line arguments where process listings could show them.
:::
@end

@concept Workflow templates and organisation defaults
@plain
A repository named `.github` in your organisation can hold starter workflows and default community files, so new repositories begin from approved patterns.
@problem
Each team invents its own pipeline from search results. Quality and security vary, and the platform team cannot enforce a baseline.
@does
- Starter workflows appear in the "New workflow" screen under `workflow-templates/` with a properties JSON file.
- Organisation rulesets can require specific workflows to pass on selected repositories. Check the current docs for availability on your plan.
- Dependabot can keep action versions in workflows up to date with an `github-actions` ecosystem entry.
@diagram flow
caption: A baseline distributed from one place
nodes:
  - "org .github repo|templates and rules|cp"
  - "New repository|starts from template|app"
  - "Dependabot|bumps action versions|info"
  - "Required workflow|baseline checks|ok"
@h Keep action versions fresh
```yaml title=".github/dependabot.yml"
version: 2
updates:
  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    groups:
      actions:
        patterns: ["*"]
```
@check
How do actions pinned by SHA stay current? || A tool such as Dependabot opens pull requests that update the pinned SHA and its version comment.
@end

@concept Debugging workflows
@plain
Most failures are YAML mistakes, wrong expressions, missing permissions or environment differences. A short set of habits finds them quickly.
@problem
Waiting several minutes per push to try a fix makes a broken pipeline an afternoon of work.
@does
- Read the first red step, then expand the "Set up job" section to see the token permissions and runner image.
- Enable step debug logging by setting the secret or variable `ACTIONS_STEP_DEBUG` to `true`.
- Lint locally with `actionlint`, and run jobs locally with `act` for simple cases. `act` does not match GitHub exactly.
- Use `workflow_dispatch` so you can rerun without a dummy commit, and re-run failed jobs only.
@diagram flow
caption: A faster debug loop
nodes:
  - "actionlint|catches syntax and expression errors|ok"
  - "Dispatch run|no dummy commit|info"
  - "Debug logging|ACTIONS_STEP_DEBUG|warn"
  - "Fix and re-run failed jobs|plain"
@h Local checks
```bash title="Lint and trigger" lab
actionlint                                  # static check of all workflows
gh workflow run deploy.yml -f environment=staging
gh run list --workflow deploy.yml --limit 5
gh run view --log-failed                    # only the failing step output
```
@check
Which tool checks workflow syntax before pushing? || actionlint.
@end
