---
title: Jenkins to GitHub Actions and a pipeline template library
minutes: 60
objectives:
  - Plan and execute a Jenkins to GitHub Actions migration in stages
  - Translate common Jenkinsfile constructs to workflow syntax
  - Design a versioned template library so teams get a golden path
---
Migration is mostly inventory and habit change; the syntax translation is the easy part.

@concept Inventory and migration plan
@plain
Before converting anything, list every job, what it does, who owns it and what it needs.
@problem
Jenkins instances accumulate hundreds of jobs, plugins and hidden credentials. Converting blindly moves the mess.
@does
- Export a list of jobs with last build date; retire anything unused for six months.
- Group jobs by pattern (build, test, deploy, cron) and migrate one pattern as a template.
- Record credentials, plugins, agents and webhooks per job.
- Pilot with two friendly teams, then migrate in waves with a firm shutdown date. Run both systems side by side during a wave only.
@diagram flow
caption: Waves of migration
numbered: true
nodes:
  - "Inventory|jobs, plugins, secrets|info"
  - "Pattern templates|build, deploy|app"
  - "Pilot teams|two services|warn"
  - "Waves and shutdown|retire Jenkins|ok"
@h Listing jobs
```bash title="Jenkins job list" lab
curl -s -u "$USER:$TOKEN" "$JENKINS_URL/api/json?tree=jobs[name,lastBuild[timestamp]]" | jq -r '.jobs[] | [.name, (.lastBuild.timestamp // 0)] | @tsv'
```
@end

@concept Translating a Jenkinsfile
@plain
Most declarative constructs have a direct equivalent: stages become jobs, steps become steps, agents become `runs-on`.
@problem
Without a map, each person invents their own translation and results differ.
@does
- `agent { label 'linux' }` becomes `runs-on: [self-hosted, linux]` or a hosted runner.
- `stage` becomes a job; `parallel` becomes jobs with no `needs`.
- `when { branch 'main' }` becomes `if: github.ref == 'refs/heads/main'`.
- `environment { }` becomes `env:`; `post { always { } }` becomes a step with `if: always()`.
- `input` (manual approval) becomes an environment with required reviewers.
@diagram cmp
caption: Jenkins to Actions
cards:
  - {h: "Jenkinsfile", kind: info, items: ["agent label", "stage and steps", "when branch", "post always"]}
  - {h: "Workflow", kind: ok, items: ["runs-on", "job and steps", "if on ref", "if always()"]}
@h Side by side
```groovy title="Jenkinsfile" nocheck
pipeline {
  agent { label 'linux' }
  stages {
    stage('Test')  { steps { sh 'make test' } }
    stage('Deploy') {
      when { branch 'main' }
      steps { sh './deploy.sh' }
    }
  }
  post { always { junit 'reports/*.xml' } }
}
```
```yaml title="Equivalent workflow"
name: ci
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make test
  deploy:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: ./deploy.sh
```
@end

@concept Credentials, agents and plugins
@plain
The hard parts of migration are secrets, build machines and plugin behaviour.
@problem
Jenkins credentials are stored centrally and often long-lived. Plugins quietly provide features no one documented.
@does
- Replace stored cloud keys with OIDC roles. Move remaining secrets into GitHub environment secrets or an external secret store.
- Static Jenkins agents become runners: hosted ones, or Actions Runner Controller pods in your Kubernetes cluster.
- For each plugin find the Actions equivalent, a CLI call, or drop the feature (for example Blue Ocean has no equivalent need).
- Rotate every credential that was copied or ever visible in logs.
@diagram flow
caption: Modernise identity while migrating
nodes:
  - "Jenkins credential|static AWS key|bad"
  - "OIDC role|short-lived|ok"
  - "ARC runner pod|ephemeral|app"
@check
Why rotate credentials during migration? || Copying secrets between systems widens exposure and old values may have appeared in logs.
@end

@concept Shared libraries to reusable workflows
@plain
Jenkins shared libraries hold common pipeline code. In Actions, reusable workflows and composite actions fill that role.
@problem
Hundreds of Jenkinsfiles call `buildJavaApp(...)`. You need the same one-line experience.
@does
- A function with parameters becomes a reusable workflow with inputs.
- Helper steps become composite actions.
- Keep a thin caller workflow per repository so teams still own triggers and settings.
- Provide a migration script or template repository that creates the caller file.
@diagram flow
caption: Library function to workflow
nodes:
  - "buildJavaApp()|shared library|info"
  - "java-build.yml|reusable workflow|cp"
  - "Caller|10 lines per repo|app"
@h Thin caller
```yaml title=".github/workflows/ci.yml"
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  build:
    uses: acme/platform-workflows/.github/workflows/java-build.yml@v3
    with:
      java-version: "21"
    secrets: inherit
```
@end

@concept Platform template library design
@plain
A template library is a set of versioned reusable workflows and actions that encode the organisation's standard pipeline: build, test, scan, sign, deploy.
@problem
Without it every team builds a slightly different, slightly insecure pipeline.
@does
- One repository, semantic version tags, a changelog, and a `v3` moving major tag for consumers.
- Templates per language and per deploy target; each includes the security steps by default (scan, SBOM, provenance).
- Inputs for what varies; opinion for the rest. Provide escape hatches without forking.
- Test templates with sample repositories in CI, and use Dependabot or Renovate to move consumers between versions.
@diagram layers
caption: Library layers
layers:
  - {label: "Caller", nodes: ["Service repo|10 line workflow|app"]}
  - {label: "Templates", nodes: ["build-image|container build|cp", "deploy-eks|rollout|cp", "scan|SAST and images|cp"]}
  - {label: "Primitives", nodes: ["setup actions|toolchains|info", "sign and attest|cosign|info"]}
@end

@concept Versioning and governing the library
@plain
Consumers need stability. Maintainers need to ship fixes everywhere quickly.
@problem
A breaking change in a shared template can break hundreds of pipelines at once.
@does
- Patch and minor releases move the `v3` tag; breaking changes create `v4` and need a migration note.
- Security fixes may be forced centrally using organisation required workflows or rulesets; check the current availability for your plan.
- Track adoption: which repositories use which version (code search in the organisation).
- Deprecate with warnings in the workflow log, then remove after a published date.
@diagram flow
caption: Release path for a template change
numbered: true
nodes:
  - "Change + tests|sample repos|app"
  - "Release v3.2.0|moves v3|cp"
  - "Consumers update|automatically|info"
  - "Breaking change|v4 and guide|warn"
@check
How does a consumer get a template bug fix without editing files? || They reference a moving major tag such as v3, which maintainers advance for compatible releases.
@end

@concept Cutover and rollback checklist
@plain
A cutover moves the trigger from Jenkins to Actions for one service and keeps a way back.
@problem
A missed webhook or a different artifact name can break deployments on the day you switch.
@does
- Run both systems in parallel and compare artifacts and test counts.
- Switch the deploy trigger last; disable the Jenkins job rather than deleting it for one release cycle.
- Check: artifact names, version numbers, notifications, branch protection checks, and scheduled jobs.
- Archive Jenkins build history (or export logs) for compliance before decommissioning.
@diagram flow
caption: Cutover per service
numbered: true
nodes:
  - "Parallel run|compare outputs|info"
  - "Switch deploy|Actions deploys|cp"
  - "Disable Jenkins job|keep for one cycle|warn"
  - "Delete|after sign-off|ok"
@end
