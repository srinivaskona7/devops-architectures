---
title: CI/CD concepts and pipeline design
minutes: 45
objectives:
  - Distinguish continuous integration, continuous delivery and continuous deployment
  - Design a pipeline with fast feedback and a build once deploy many artifact flow
  - Place tests, scans and approvals at the right stage of a pipeline
---
A pipeline is the automated path from a commit to a running service. Good pipeline design makes shipping boring, fast and safe, and it is the backbone of every other practice in this folder.

@concept Continuous integration
@plain
Continuous integration (CI) means every developer merges small changes into the shared branch often, and every change is built and tested automatically by a server within minutes.
@problem
When people work for weeks on private branches, merging becomes a painful event full of conflicts and surprises. Bugs are found long after the change that caused them, so they are expensive to trace.
@does
- Triggers a build and test run on each push and each pull request.
- Gives a pass or fail signal that blocks merging when it fails.
- Keeps the main branch always in a releasable state.
- Produces the first trusted artifact, for example a container image, from a known commit.
@diagram flow
caption: The CI loop for one change
numbered: true
nodes:
  - "Commit|small change pushed|plain"
  - "Build|compile and package|app"
  - "Test|unit and integration|info"
  - "Scan|lint and dependencies|warn"
  - "Verdict|green allows merge|ok"
@h What a minimal CI trigger looks like
```yaml title=".github/workflows/ci.yml (minimal)"
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make test
```
@check
What is the one rule that makes CI work? || The shared branch is merged into often and every merge is verified automatically, so it never stays broken for long.
@end

@concept Continuous delivery versus continuous deployment
@plain
Continuous delivery means every change that passes the pipeline is ready to release at the push of a button. Continuous deployment goes one step further and releases it automatically with no human click.
@problem
Teams confuse the two terms and either ship too slowly because of manual gates, or ship automatically without the tests and monitoring that make that safe.
@does
- **Delivery**: the artifact is built, tested and deployable to production, but a person approves the release.
- **Deployment**: passing the pipeline is the approval. Needs strong tests, canary checks and fast rollback.
- Both rely on the same pipeline. The difference is a single approval gate.
@diagram cmp
caption: Same pipeline, different last step
cards:
  - {h: "Continuous delivery", kind: info, items: ["Always releasable", "Human approves production", "Common in regulated teams"]}
  - {h: "Continuous deployment", kind: ok, items: ["No manual step", "Needs canary and auto rollback", "Common for web services"]}
  - {h: "Neither", kind: bad, items: ["Manual builds", "Releases by ticket and hand work", "Slow and risky"]}
@h A manual gate is one setting
```yaml title="Delivery adds an approval, deployment removes it" nocheck
deploy-prod:
  needs: deploy-staging
  environment: production   # required reviewers configured on this environment means delivery
  # remove the reviewers rule and the job runs by itself, which is deployment
```
:::note
Many organisations use deployment for staging and delivery for production. That is a normal middle path.
:::
@end

@concept Stages of a pipeline
@plain
A pipeline is a list of stages, and each stage is a group of jobs that must pass before the next group starts. A common order is build, test, scan, package, deploy and verify.
@problem
Without a clear order, expensive or risky steps run too early or too late. Slow end to end tests block quick feedback, and deployments may run on code that was never scanned.
@does
- Cheap checks run first (lint, unit tests) so failures show in seconds.
- Expensive checks (integration, end to end, load) run later or in parallel.
- Only a build that passed all earlier stages is allowed to reach a deploy stage.
- Every stage has a clear input and output, so a failure points to one place.
@diagram flow
caption: A typical service pipeline
nodes:
  - "Lint and unit|seconds to minutes|ok"
  - "Build image|one artifact|app"
  - "Scan and test|SCA, integration|info"
  - "Push|registry by digest|env"
  - "Deploy staging|automatic|cp"
  - "Deploy prod|gated or automatic|warn"
@h Stages as GitLab CI shows them
```yaml title=".gitlab-ci.yml (stage order)"
stages: [lint, build, test, publish, deploy]
unit:
  stage: test
  script: [make test]
build-image:
  stage: build
  script: [docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHA" .]
```
@check
Why run lint before integration tests? || It fails in seconds, so developers learn about trivial problems without waiting for slow stages.
@end

@concept Fast feedback and the test pyramid
@plain
The test pyramid says write many fast unit tests, fewer integration tests and very few end to end tests. Pipelines should be ordered the same way so the quickest signal arrives first.
@problem
Suites made mostly of slow browser tests take an hour, fail randomly, and teach people to ignore or retry red builds.
@does
- Aim for a pull request check under ten minutes. Many teams hold a budget and treat breaches as bugs.
- Unit tests: milliseconds each, no network. Integration tests: real database in a container. End to end: a handful covering critical journeys.
- Run the fast layer on every push and the slow layer on merge or on a schedule if needed.
@diagram layers
caption: Where to spend test effort
layers:
  - {label: "Few and slow", nodes: ["End to end|critical user journeys|bad"]}
  - {label: "Some", nodes: ["Integration|database, queue, API contract|warn"]}
  - {label: "Many and fast", nodes: ["Unit|pure logic|ok", "Static checks|lint, types, format|ok"]}
@h Splitting by speed
```yaml title="Fast job gates the slow job" nocheck
jobs:
  unit:
    runs-on: ubuntu-latest
    steps: [{uses: actions/checkout@v4}, {run: make unit}]
  integration:
    needs: unit          # only starts when the quick job is green
    runs-on: ubuntu-latest
    steps: [{uses: actions/checkout@v4}, {run: make integration}]
```
@check
What should you do about a flaky test? || Quarantine or fix it quickly. Retrying hides the problem and trains people to distrust the pipeline.
@end

@concept Build once, deploy many
@plain
Build the artifact a single time, give it an immutable identity such as a digest, and move that exact artifact through dev, staging and production. Only configuration differs between environments.
@problem
Rebuilding for each environment means production runs something that was never tested. A different base image or dependency version can slip in between the staging build and the production build.
@does
- Tag the image with the commit SHA and record the digest (`sha256:...`).
- Promotion means updating which digest an environment points at, not rebuilding.
- Environment settings come from ConfigMaps, Secrets or Helm values, never from build arguments.
@diagram flow
caption: One image, three environments
nodes:
  - "Build once|image digest sha256|app"
  - "Dev|values-dev|env"
  - "Staging|values-staging|env"
  - "Production|values-prod|ok"
@h Promote by digest
```bash title="Get the digest and deploy that, not a tag" lab
docker buildx imagetools inspect 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:abc1234 \
  --format '{{json .Manifest.Digest}}'
# deploy using the digest, which cannot change underneath you
helm upgrade shop ./chart --set image.digest=sha256:0123abcd --namespace shop
```
:::warn
A mutable tag such as `latest` can point at a different image tomorrow. Deploy by digest or by an immutable tag.
:::
@end

@concept Pipeline as code
@plain
The pipeline definition lives in the same repository as the application, in a text file such as `.github/workflows/*.yml`, `Jenkinsfile` or `.gitlab-ci.yml`, and is reviewed like any other code.
@problem
Pipelines configured by clicking in a web UI cannot be reviewed, rolled back, copied or recreated after a disaster. Nobody knows who changed what.
@does
- Changes to the pipeline go through pull requests, with history and blame.
- A branch can carry its own pipeline change and test it before merge.
- The same definition can be reused across repositories through templates, reusable workflows or shared libraries.
@diagram flow
caption: Pipeline definition travels with the code
nodes:
  - "Repository|code and pipeline file|app"
  - "Pull request|review of both|info"
  - "CI server|reads the file|cp"
  - "Run|reproducible|ok"
@h Keep pipeline logic thin
```bash title="Pipeline calls the same scripts a developer runs" lab
# Makefile targets are the single source of truth, CI only calls them
make lint
make test
make image TAG="$(git rev-parse --short HEAD)"
```
:::tip
If a developer cannot run the same steps locally, debugging becomes a cycle of push and wait. Put the logic in scripts or a Makefile and keep the YAML to orchestration.
:::
@check
Why keep pipeline files next to the code? || They are versioned, reviewed and branched together with the application they build.
@end

@concept Environments and promotion
@plain
An environment is a place where the service runs, such as dev, staging and production. Promotion is moving a tested artifact from one to the next, with rising confidence at each step.
@problem
Deploying straight to production is risky, but environments that differ greatly from production give false confidence.
@does
- Each environment has its own namespace or cluster, its own credentials and its own configuration.
- Gates between them can be automatic (tests pass) or manual (approval).
- Keep staging close to production in version and shape, even if smaller in size.
- Production credentials are only available to production jobs.
@diagram flow
caption: Promotion with growing confidence
numbered: true
nodes:
  - "Dev|every merge|env"
  - "Staging|integration and smoke tests|env"
  - "Approval|optional human|warn"
  - "Production|canary then full|ok"
@h Namespaces per environment on one cluster
```yaml title="Kustomize overlay chooses the environment" nocheck
# overlays/staging/kustomization.yaml
resources: [../../base]
namespace: shop-staging
images:
  - name: shop
    digest: sha256:0123abcd
```
@check
What should differ between staging and production? || Scale, secrets and endpoints. The image and the deployment method should be identical.
@end
