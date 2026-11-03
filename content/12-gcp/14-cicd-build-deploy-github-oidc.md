---
title: Cloud Build, Cloud Deploy and GitHub Actions with OIDC
minutes: 65
objectives:
  - Build and push images with Cloud Build using least-privilege service accounts
  - Promote releases through targets with Cloud Deploy and Skaffold
  - Authenticate GitHub Actions to Google Cloud with Workload Identity Federation and no keys
---
Google Cloud offers a native pipeline (Cloud Build and Cloud Deploy), and it also works well with external CI. Whichever you pick, the principle is the same: short-lived identities and immutable image digests.

@concept Cloud Build
@plain
**Cloud Build** runs build steps as containers in a managed environment, triggered manually, by a repository event or by a schedule.
@problem
Build servers need patching, scaling and secure access to registries and clusters.
@does
- A `cloudbuild.yaml` has `steps` (each with a builder image and args), `substitutions`, `artifacts`, `images` and `options`.
- Builds run as a service account. Use a **user-specified service account** with only the roles it needs, not the legacy default.
- Private pools provide VPC access and fixed machine types; the default pool is shared.
- Triggers connect GitHub, GitLab, Bitbucket and Cloud Source Repositories alternatives (check the current connection options).
- **AWS equivalent**: CodeBuild. Main difference: each step is a container, and the workspace `/workspace` is shared between steps.
@diagram flow
caption: Build pipeline
nodes:
  - "Trigger|push to main|ext"
  - "Cloud Build|steps in containers|cp"
  - "Test and build|docker build|app"
  - "Artifact Registry|image digest|db"
@h cloudbuild.yaml
```yaml title="cloudbuild.yaml"
steps:
  - id: test
    name: python:3.12-slim
    entrypoint: bash
    args: ["-c", "pip install -r requirements.txt && pytest -q"]
  - id: build
    name: gcr.io/cloud-builders/docker
    args: ["build", "-t", "${_REPO}/api:${SHORT_SHA}", "."]
  - id: push
    name: gcr.io/cloud-builders/docker
    args: ["push", "${_REPO}/api:${SHORT_SHA}"]
substitutions:
  _REPO: europe-west1-docker.pkg.dev/shop-dev-123456/shop
options:
  logging: CLOUD_LOGGING_ONLY
```
```bash title="Submit" lab
gcloud builds submit --config=cloudbuild.yaml --substitutions=SHORT_SHA=$(git rev-parse --short HEAD) \
  --service-account=projects/shop-dev-123456/serviceAccounts/builder@shop-dev-123456.iam.gserviceaccount.com .
```
@check
Where do steps share files? || In the /workspace directory.
@end

@concept Build triggers and security
@plain
Triggers start builds automatically. Build provenance and policy features add supply chain security.
@problem
Manual builds are inconsistent, and unsigned artifacts cannot be trusted.
@does
- Create triggers for push, pull request, tag, manual approval or Pub/Sub. Add `requireApproval` for production builds.
- Builds can generate **SLSA provenance** attestations for images, which Binary Authorization can verify.
- Use Secret Manager values in steps via `availableSecrets` rather than substitutions.
- Restrict who can create triggers and which service account they use.
- **AWS equivalent**: CodePipeline triggers with CodeBuild. Main difference: provenance generation is built into Cloud Build for supported builds.
@diagram flow
caption: Trusted build
nodes:
  - "Pull request|run tests|ext"
  - "Main branch|build and push|app"
  - "Attestation|signed provenance|ok"
  - "Binary Authorization|checks at deploy|cp"
@h Trigger
```bash title="GitHub trigger" lab
gcloud builds triggers create github --name=shop-main --repo-name=shop --repo-owner=example-org \
  --branch-pattern='^main$' --build-config=cloudbuild.yaml \
  --service-account=projects/shop-dev-123456/serviceAccounts/builder@shop-dev-123456.iam.gserviceaccount.com
```
:::note
Newer connection types (2nd generation repositories) use different flags. Check the current docs.
:::
@end

@concept Cloud Deploy
@plain
**Cloud Deploy** is managed continuous delivery. A delivery pipeline promotes a release through ordered targets such as dev, staging and prod, using Skaffold to render and deploy.
@problem
Promotion between environments is often scripts with no approval, history or rollback.
@does
- Resources: **delivery pipeline** (stages), **targets** (GKE, Cloud Run, GKE Enterprise fleets), **release** (a snapshot of manifests and images), **rollout** (a release applied to a target).
- Features: approvals, rollbacks, canary and blue-green deployment strategies, deploy verification, automation rules, and parallel deployment.
- Config is in `clouddeploy.yaml` and `skaffold.yaml`.
- **AWS equivalent**: CodeDeploy and CodePipeline stages. Main difference: it is Kubernetes and Cloud Run centred, with first-class promotion and approvals.
@diagram flow
caption: Promotion pipeline
nodes:
  - "Release|image digests|app"
  - "Dev target|automatic|ok"
  - "Staging target|verify|info"
  - "Prod target|approval needed|warn"
@h Pipeline definition
```yaml title="clouddeploy.yaml"
apiVersion: deploy.cloud.google.com/v1
kind: DeliveryPipeline
metadata:
  name: shop-pipeline
serialPipeline:
  stages:
    - targetId: dev
    - targetId: staging
    - targetId: prod
---
apiVersion: deploy.cloud.google.com/v1
kind: Target
metadata:
  name: prod
requireApproval: true
gke:
  cluster: projects/shop-prod-123456/locations/europe-west1/clusters/shop-prod
```
```bash title="Apply and release" lab
gcloud deploy apply --file=clouddeploy.yaml --region=europe-west1
gcloud deploy releases create rel-$(date +%Y%m%d-%H%M) --delivery-pipeline=shop-pipeline \
  --region=europe-west1 --images=api=europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:1.0.0
```
@check
What does a release snapshot contain? || The rendered manifests and image references that will be promoted unchanged.
@end

@concept Skaffold and deploy strategies
@plain
**Skaffold** renders and applies manifests. Cloud Deploy uses a `skaffold.yaml` to run these steps, and supports standard, canary and blue-green strategies on GKE.
@problem
You want the same render and deploy logic locally and in the pipeline.
@does
- `skaffold.yaml` lists manifests (raw, Kustomize or Helm), profiles per target, and verify actions.
- Canary for GKE uses Gateway API or Service networking to shift traffic gradually (`percentages: [25, 50]`).
- Verify runs a container test after deploy; failure triggers rollback or stops promotion.
- **AWS equivalent**: CodeDeploy hooks. Main difference: the manifest rendering is standard open-source Skaffold.
@diagram flow
caption: Render and deploy
nodes:
  - "skaffold render|expand Kustomize|info"
  - "Apply|to target cluster|app"
  - "Verify|test container|warn"
  - "Promote|next stage|ok"
@h skaffold.yaml
```yaml title="skaffold.yaml"
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: shop
manifests:
  kustomize:
    paths: ["k8s/overlays/dev"]
deploy:
  kubectl: {}
profiles:
  - name: prod
    manifests:
      kustomize:
        paths: ["k8s/overlays/prod"]
verify:
  - name: smoke
    container:
      name: smoke
      image: europe-west1-docker.pkg.dev/shop-dev-123456/shop/smoke:1.0.0
```
@end

@concept GitHub Actions to Google Cloud with OIDC
@plain
GitHub Actions can prove its identity with a short-lived OIDC token and exchange it for Google credentials through **Workload Identity Federation**, so no JSON key is stored in GitHub.
@problem
Long-lived keys in repository secrets leak and must be rotated.
@does
- Create a workload identity pool and an OIDC provider for `https://token.actions.githubusercontent.com` with an attribute condition on the repository (and ideally branch or environment).
- Let the federated identity impersonate a service account through `roles/iam.workloadIdentityUser` on that account, scoped to `principalSet://.../attribute.repository/ORG/REPO`.
- In the workflow, request `permissions: id-token: write` and use `google-github-actions/auth`.
- **AWS equivalent**: GitHub OIDC with `AssumeRoleWithWebIdentity`. Main difference: the mapping and condition live in the provider and in the principal set binding.
@diagram seq
caption: Keyless login
actors: ["GitHub job|OIDC token|ext", "Google STS|federation|cp", "Service account|deployer|info", "Google API|Artifact Registry, GKE|app"]
steps:
  - "0>1: exchange OIDC token | tls"
  - "note 1..1: check provider condition"
  - "1>0: federated token | resp"
  - "0>2: impersonate deployer | req"
  - "0>3: push image, deploy | tls"
@h Bind the repository
```bash title="Allow the repository" lab
PROJECT_NUMBER=$(gcloud projects describe shop-dev-123456 --format="value(projectNumber)")
gcloud iam service-accounts add-iam-policy-binding deployer@shop-dev-123456.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github/attribute.repository/example-org/shop"
```
@check
Which permission must the workflow request from GitHub? || id-token: write.
@end

@concept A GitHub Actions workflow for GKE
@plain
A complete workflow authenticates, builds and pushes to Artifact Registry, and deploys to GKE with a pinned image digest.
@problem
Pipelines drift when each team writes its own steps.
@does
- `google-github-actions/auth` with `workload_identity_provider` and `service_account` sets credentials.
- `google-github-actions/setup-gcloud` installs gcloud; `get-gke-credentials` configures kubectl.
- Use `environment: production` with required reviewers for the deploy job.
- Pin third-party actions by commit SHA for supply chain safety.
- **AWS equivalent**: `aws-actions/configure-aws-credentials` with `role-to-assume`. Main difference: you set the provider resource name and service account email.
@diagram flow
caption: Workflow jobs
nodes:
  - "Test|pull request|ok"
  - "Build and push|digest output|app"
  - "Approve|environment gate|warn"
  - "Deploy|kubectl set image|cp"
@h Workflow
```yaml title=".github/workflows/deploy.yaml"
name: deploy
on:
  push:
    branches: [main]
permissions:
  contents: read
  id-token: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: projects/123456789/locations/global/workloadIdentityPools/github/providers/github-oidc
          service_account: deployer@shop-dev-123456.iam.gserviceaccount.com
      - uses: google-github-actions/setup-gcloud@v2
      - run: gcloud auth configure-docker europe-west1-docker.pkg.dev --quiet
      - run: |
          docker build -t europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:${GITHUB_SHA} .
          docker push europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:${GITHUB_SHA}
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment: production
    steps:
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: projects/123456789/locations/global/workloadIdentityPools/github/providers/github-oidc
          service_account: deployer@shop-dev-123456.iam.gserviceaccount.com
      - uses: google-github-actions/get-gke-credentials@v2
        with:
          cluster_name: shop-std
          location: europe-west1
      - run: kubectl -n shop set image deployment/api api=europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:${GITHUB_SHA}
```
:::tip
Check the current major versions of these actions before copying.
:::
@end

@concept Choosing a delivery approach
@plain
Cloud Build with Cloud Deploy, GitHub Actions, or a GitOps controller such as Config Sync or Argo CD are all valid.
@problem
Too many overlapping tools make ownership unclear.
@does
- Cloud Build + Cloud Deploy: all-Google, strong promotion and audit, less flexible for non-Google code hosts.
- GitHub Actions + OIDC: best developer experience when code is on GitHub; combine with kubectl, Helm or Argo CD.
- GitOps (Config Sync, Argo CD, Flux): pull-based drift correction; CI only builds and updates the manifest repository.
- **AWS equivalent**: CodePipeline versus GitHub Actions versus Argo CD. Main difference: Cloud Deploy gives managed promotion, which AWS lacks outside ECS CodeDeploy.
@diagram cmp
caption: Three approaches
cards:
  - {h: "Cloud Build and Deploy", kind: info, items: ["Managed, audit built in", "Promotion and approvals"]}
  - {h: "GitHub Actions", kind: app, items: ["Keyless with OIDC", "Wide ecosystem"]}
  - {h: "GitOps", kind: ok, items: ["Pull based", "Drift correction", "Git is the record"]}
@choose Pick one primary path
Cloud Build + Cloud Deploy | Google-centric teams needing approvals and rollouts | your code and tooling live on GitHub already
GitHub Actions + OIDC | GitHub-hosted code and mixed clouds | you need managed promotion history
GitOps | many clusters and drift concerns | you need push-based one-off jobs
@end
