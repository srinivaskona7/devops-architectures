---
title: GitLab CI and other CI systems
minutes: 45
objectives:
  - Write a GitLab CI pipeline with stages, rules, caching and environments
  - Reuse configuration with include and templates
  - Recognise how CircleCI, Tekton and Argo Workflows model pipelines
---
GitHub Actions and Jenkins are not the only choices. This section shows GitLab CI in practical depth and then surveys the others so you can read their configuration.

@concept GitLab CI pipeline basics
@plain
GitLab CI reads `.gitlab-ci.yml` at the repository root. The file defines **stages** (ordered phases) and **jobs** (units of work that belong to a stage). Jobs in the same stage run in parallel.
@problem
You want pipelines integrated with the same platform that holds the code, merge requests, container registry and environments.
@does
- `stages:` sets order. Each job picks one with `stage:` and runs its `script:` lines.
- `image:` sets the container image the job runs in on a Docker or Kubernetes executor.
- `needs:` builds a directed graph so a job can start as soon as its dependencies finish, without waiting for the whole previous stage.
- `artifacts:` passes files to later jobs and keeps reports. `variables:` defines environment variables.
@diagram flow
caption: Stages run in order, jobs inside a stage in parallel
nodes:
  - "build|compile and package|app"
  - "test unit|parallel job|info"
  - "test lint|parallel job|info"
  - "package|container image|env"
  - "deploy|environment|ok"
@h A basic pipeline
```yaml title=".gitlab-ci.yml"
stages: [build, test, package]
default:
  image: golang:1.23
build:
  stage: build
  script:
    - go build -o shop ./cmd/shop
  artifacts:
    paths: [shop]
    expire_in: 1 day
unit:
  stage: test
  script: [go test ./...]
lint:
  stage: test
  needs: []
  script: [go vet ./...]
package:
  stage: package
  needs: [build, unit]
  image: docker:27
  script:
    - docker build -t "$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA" .
```
@check
What does needs: [] do? || The job has no dependencies and starts immediately, ignoring stage order.
@end

@concept Rules, workflow and conditions
@plain
`rules:` decides whether a job is added to the pipeline, using conditions on variables, changed files and the pipeline source. `workflow:rules` does the same for the whole pipeline.
@problem
Without rules, every push creates duplicate branch and merge request pipelines and every job runs everywhere.
@does
- `if: $CI_PIPELINE_SOURCE == "merge_request_event"` matches merge request pipelines.
- `if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH` matches the default branch. `changes:` matches paths.
- `when: manual` makes a job a button. `allow_failure: true` lets the pipeline pass anyway.
- Rules are evaluated top to bottom, first match wins, and a job with no match is not created.
@diagram cmp
caption: Typical rule sets
cards:
  - {h: "Merge request", kind: info, items: ["lint, unit, scan", "No deploy"]}
  - {h: "Default branch", kind: ok, items: ["Build image", "Deploy staging automatically"]}
  - {h: "Tag", kind: app, items: ["Release build", "Manual production deploy"]}
@h Rules in use
```yaml title="Avoiding duplicate pipelines"
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH && $CI_OPEN_MERGE_REQUESTS
      when: never
    - if: $CI_COMMIT_BRANCH
    - if: $CI_COMMIT_TAG
unit:
  script: [make test]
  rules:
    - changes: ["**/*.go", "go.mod"]
deploy-prod:
  script: [./deploy.sh production]
  rules:
    - if: $CI_COMMIT_TAG
      when: manual
```
@check
What happens to a job when no rule matches? || It is not added to the pipeline.
@end

@concept GitLab runners and executors
@plain
A GitLab Runner is the agent that runs jobs. The **executor** decides how: shell, Docker, or Kubernetes (a pod per job). Runners are shared across a group or dedicated to a project, and are selected by **tags**.
@problem
Jobs need a clean, scalable environment close to your network, and you must control which jobs reach which machines.
@does
- Register a runner with a token from the project, group or instance. Check the current docs, since the registration flow changed to authentication tokens.
- The Kubernetes executor creates a pod per job with a helper container for cloning and artifacts.
- Job `tags:` must match runner tags. Protected runners only run protected branches and tags, which suits production deploys.
- GitLab.com also offers hosted runners for several platforms.
@diagram flow
caption: Job to runner to pod
nodes:
  - "Pipeline job|tags k8s|app"
  - "GitLab server|matches runner by tag|cp"
  - "Runner manager|in your cluster|env"
  - "Job pod|build and helper containers|ok"
@h Runner on Kubernetes
```bash title="Install with the GitLab Runner Helm chart" lab nocheck
helm repo add gitlab https://charts.gitlab.io
helm install gitlab-runner gitlab/gitlab-runner --namespace gitlab-runner --create-namespace \
  --set gitlabUrl=https://gitlab.example.com \
  --set runnerToken="$RUNNER_AUTH_TOKEN"
```
:::tip
Use protected runners and protected variables for production. A feature branch pipeline then cannot reach production credentials.
:::
@end

@concept Includes, templates and components
@plain
`include:` pulls configuration from other files, another project, a remote URL or a template. `extends:` and YAML anchors reuse job fragments. **CI/CD components** are versioned, parameterised building blocks published in a catalog.
@problem
Copying the same Docker build job into every project guarantees drift.
@does
- `include: project:` with `ref:` pins a shared pipeline repository to a tag.
- Hidden jobs (names starting with a dot) act as templates that real jobs `extends`.
- Components take typed `inputs`. Check the current docs for component syntax and catalog features.
- Parent-child and multi-project pipelines trigger other pipelines for monorepos.
@diagram flow
caption: Shared config pulled into a project
nodes:
  - "ci-templates project|tagged v3|cp"
  - "include project ref v3|in .gitlab-ci.yml|app"
  - "Merged config|jobs and rules|info"
  - "Pipeline|runs|ok"
@h Include and extend
```yaml title="Reusing shared jobs"
include:
  - project: platform/ci-templates
    ref: v3.2.0
    file: /templates/docker-build.yml
.deploy-base:
  image: bitnami/kubectl:latest
  before_script:
    - kubectl version --client
deploy-staging:
  extends: .deploy-base
  stage: deploy
  script:
    - kubectl -n shop-staging set image deploy/shop shop="$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA"
  environment:
    name: staging
```
@check
What does the leading dot in a job name mean? || The job is hidden and never runs on its own, so it can serve as a template.
@end

@concept GitLab environments, review apps and deployments
@plain
An `environment:` on a job records deployments in GitLab with a URL, history and optional rollback. Review apps deploy every merge request to a temporary environment.
@problem
Reviewers want to see a change running, and teams want a record of what is deployed where.
@does
- `environment: name: review/$CI_COMMIT_REF_SLUG` with `on_stop:` and `auto_stop_in:` creates and cleans review environments.
- Protected environments limit who may deploy and can require approvals.
- Deployment history and rollbacks appear in the environments page.
- For Kubernetes, GitLab recommends its agent for Kubernetes or a GitOps tool instead of storing kubeconfigs. Check the current docs.
@diagram seq
caption: Review app lifecycle
actors: ["Merge request|branch|app", "Pipeline|deploy job|cp", "Cluster|review namespace|env"]
steps:
  - "0>1: pipeline runs | req"
  - "1>2: deploy review app | req"
  - "note 2..2: URL posted on the MR"
  - "0>1: MR merged | req"
  - "1>2: stop and delete | req"
@h Review environment
```yaml title="Stop job and review app"
review:
  stage: deploy
  script:
    - helm upgrade --install "shop-$CI_COMMIT_REF_SLUG" ./chart --namespace review
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com
    on_stop: stop-review
    auto_stop_in: 3 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
stop-review:
  stage: deploy
  script:
    - helm uninstall "shop-$CI_COMMIT_REF_SLUG" --namespace review
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    action: stop
  when: manual
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      when: manual
```
@end

@concept CircleCI
@plain
CircleCI is a hosted CI service configured in `.circleci/config.yml`. Work is organised as **jobs** that run in an executor (Docker image, machine or macOS) and **workflows** that order them. Reusable packages are called **orbs**.
@problem
Teams that want fast hosted CI independent of their Git host, with strong caching and parallel test splitting, choose a dedicated CI service.
@does
- `jobs` define steps. `workflows` define dependencies with `requires`.
- `save_cache` and `restore_cache` handle dependency caches. Test splitting spreads tests across parallel containers.
- Orbs bundle commands and jobs. Pin orb versions like any dependency.
- Contexts hold shared secrets, and OIDC tokens are available for cloud login.
@diagram flow
caption: CircleCI structure
nodes:
  - "config.yml|version 2.1|app"
  - "Jobs|executor and steps|info"
  - "Workflows|requires ordering|cp"
  - "Orbs|shared packages|ext"
@h A small config
```yaml title=".circleci/config.yml"
version: 2.1
jobs:
  test:
    docker:
      - image: cimg/go:1.23
    steps:
      - checkout
      - restore_cache:
          keys:
            - 'gomod-{{ checksum "go.sum" }}'
      - run: go test ./...
      - save_cache:
          key: 'gomod-{{ checksum "go.sum" }}'
          paths: [/home/circleci/go/pkg/mod]
workflows:
  main:
    jobs:
      - test
```
@check
What does a CircleCI workflow add on top of jobs? || The ordering and dependencies between jobs, using requires.
@end

@concept Tekton and Argo Workflows
@plain
Tekton and Argo Workflows are Kubernetes-native engines. Their pipelines are Kubernetes custom resources, and each step runs as a container in a pod on your cluster.
@problem
If you already run Kubernetes and want CI as code under the same API, RBAC and tooling, a cluster-native engine avoids a separate CI server.
@does
- **Tekton**: `Task` (steps in one pod), `Pipeline` (ordered tasks), `PipelineRun` (an execution). Triggers and a catalog of tasks exist as add-ons.
- **Argo Workflows**: `Workflow` with templates arranged as steps or a DAG. Strong for batch, data and ML jobs and for CI. `WorkflowTemplate` is the reusable form.
- No UI authors; you write YAML. Neither includes a Git host, so you add webhooks (Argo Events or Tekton Triggers).
- Cost: you operate them and their CRDs, and onboarding developers is slower than with a hosted CI.
@diagram layers
caption: Kubernetes-native CI building blocks
layers:
  - {label: "Definition", nodes: ["Tekton Task and Pipeline|CRDs|cp", "Argo WorkflowTemplate|CRD|cp"]}
  - {label: "Execution", nodes: ["PipelineRun or Workflow|one execution|app", "Pods per step|containers|app"]}
  - {label: "Events", nodes: ["Tekton Triggers|webhook to run|ext", "Argo Events|event sources|ext"]}
@h A tiny Argo Workflow
```yaml title="Argo Workflow with two steps"
apiVersion: argoproj.io/v1alpha1
kind: Workflow
metadata:
  generateName: build-test-
spec:
  entrypoint: main
  templates:
    - name: main
      steps:
        - - name: test
            template: run
            arguments:
              parameters: [{name: cmd, value: "make test"}]
        - - name: build
            template: run
            arguments:
              parameters: [{name: cmd, value: "make build"}]
    - name: run
      inputs:
        parameters: [{name: cmd}]
      container:
        image: golang:1.23
        command: [sh, -c]
        args: ["{{inputs.parameters.cmd}}"]
```
:::note
Argo Workflows and Argo CD are different projects. Workflows runs jobs, Argo CD syncs desired state from Git.
:::
@end
