---
title: Jenkins pipeline and Argo CD applications
minutes: 55
objectives:
  - Write a declarative Jenkinsfile that matches the GitHub Actions stages
  - Run build agents as Kubernetes pods with a least-privilege AWS role
  - Define Argo CD applications for dev, staging and prod with the right sync policy
---
Some organisations run Jenkins. The Shop ships a Jenkinsfile with the same stages as GitHub Actions so the choice of CI system does not change the rest of the design. Jenkins internals are in the CI/CD folder (Jenkins architecture, Jenkinsfile, libraries and Kubernetes agents).

@concept Mapping GitHub Actions stages to Jenkins
@plain
Each GitHub Actions job has a Jenkins stage with the same job: test, build, scan, push, bump the deploy folder.
@problem
Teams that run two CI systems often let them diverge, so a build passes in one and fails in the other.
@does
- Both call the same `make` targets and the same scripts in `scripts/`.
- Credentials: Actions uses OIDC. Jenkins on EKS uses an IAM role for the agent service account (IRSA), so no AWS keys are stored in Jenkins credentials.
- Triggers: a webhook on push and pull request via the multibranch pipeline.
- Approval for prod: Jenkins `input` step restricted to a group, versus GitHub environments.
@diagram cmp
caption: Same stages, different engine
cards:
  - {h: "GitHub Actions", kind: info, items: ["OIDC token to AWS", "Matrix jobs", "Environments approve prod", "Hosted or ARC runners"]}
  - {h: "Jenkins", kind: warn, items: ["IRSA role on agent pod", "Parallel stage block", "input step approves prod", "Kubernetes plugin pods"]}
@end

@concept Kubernetes agent pods for Jenkins
@plain
Each build runs in a fresh pod with the containers it needs: Python for tests, Kaniko or BuildKit for images, Trivy for scanning.
@problem
Long-lived agents accumulate state and tool versions, and building images with a mounted Docker socket gives the build root on the node.
@does
- The Kubernetes plugin creates a pod from YAML for every build and deletes it afterwards.
- Image builds use rootless BuildKit or Kaniko, no `docker.sock`.
- The pod's service account has the IRSA annotation for the ECR push role (same permissions as the GitHub OIDC role).
- Resource requests keep builds from starving the Jenkins controller.
@diagram flow
caption: Build pod per run
nodes:
  - "Webhook|push to main|ext"
  - "Jenkins controller|schedules|cp"
  - "Agent pod|python, kaniko, trivy|app"
  - "ECR|via IRSA|ok"
@h agent pod template
```yaml title="ci/jenkins-agent.yaml"
apiVersion: v1
kind: Pod
spec:
  serviceAccountName: jenkins-agent
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
  containers:
    - name: python
      image: python:3.12-slim
      command: ["sleep", "infinity"]
      resources:
        requests: {cpu: 500m, memory: 512Mi}
    - name: kaniko
      image: gcr.io/kaniko-project/executor:debug
      command: ["sleep", "infinity"]
      resources:
        requests: {cpu: "1", memory: 1Gi}
    - name: trivy
      image: aquasec/trivy:latest
      command: ["sleep", "infinity"]
      resources:
        requests: {cpu: 250m, memory: 512Mi}
```
:::note
Kaniko runs as root inside its container by default. Pin tags, review the current project status, and consider BuildKit rootless as an alternative. The `latest` tags above are for brevity only.
:::
@end

@concept The declarative Jenkinsfile
@plain
A Jenkinsfile in the repository root defines the stages. Parallel stages run the service tests together.
@problem
Pipelines configured in the Jenkins UI cannot be reviewed, versioned or recovered.
@does
- `parallel` runs the test stage for each service.
- `when { branch 'main' }` limits build and push to the main branch; pull requests stop after tests and manifest checks.
- `options { timeout, disableConcurrentBuilds, buildDiscarder }` keep the controller healthy.
- `post { always { junit ... } }` publishes test results (add `--junitxml` to pytest).
@diagram flow
caption: Pipeline stages
nodes:
  - "Checkout|multibranch|plain"
  - "Test in parallel|5 services|app"
  - "Build and scan|main only|warn"
  - "Push and bump|ECR, deploy folder|ok"
@h Jenkinsfile
```groovy title="Jenkinsfile" nocheck
pipeline {
  agent {
    kubernetes {
      yamlFile 'ci/jenkins-agent.yaml'
      defaultContainer 'python'
    }
  }
  options {
    timeout(time: 30, unit: 'MINUTES')
    disableConcurrentBuilds(abortPrevious: true)
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }
  environment {
    REGISTRY = '111111111111.dkr.ecr.ap-south-1.amazonaws.com'
    TAG      = "sha-${env.GIT_COMMIT}"
  }
  stages {
    stage('Test') {
      parallel {
        stage('catalog')  { steps { sh 'pip install -r services/catalog/requirements.txt  && cd services/catalog  && python -m pytest -q' } }
        stage('cart')     { steps { sh 'pip install -r services/cart/requirements.txt     && cd services/cart     && python -m pytest -q' } }
        stage('orders')   { steps { sh 'pip install -r services/orders/requirements.txt   && cd services/orders   && python -m pytest -q' } }
        stage('payments') { steps { sh 'pip install -r services/payments/requirements.txt && cd services/payments && python -m pytest -q' } }
      }
    }
    stage('Build and push') {
      when { branch 'main' }
      steps {
        container('kaniko') {
          sh '''
            for svc in catalog cart orders payments; do
              /kaniko/executor --context services/$svc --dockerfile services/$svc/Dockerfile \
                --destination $REGISTRY/shop/$svc:$TAG --no-push-metadata=false
            done
          '''
        }
      }
    }
    stage('Scan') {
      when { branch 'main' }
      steps {
        container('trivy') {
          sh 'for svc in catalog cart orders payments; do trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 $REGISTRY/shop/$svc:$TAG; done'
        }
      }
    }
    stage('Bump dev overlay') {
      when { branch 'main' }
      steps { sh 'python scripts/bump_overlay.py dev $TAG' }
    }
    stage('Approve prod') {
      when { tag 'v*' }
      steps { input message: 'Promote to production?', submitter: 'shop-release' }
    }
  }
}
```
:::warn
This ordering pushes before scanning, which would leave unscanned images in ECR. Safer: build to a tarball (`--no-push --tar-path`), scan the tarball, then push only on a clean result. Choose your order deliberately and write it in the ADR.
:::
@check
Why should the Jenkins agent not mount the Docker socket? || Anyone who can run a build could control the node's container runtime and gain root on the host.
@end

@concept Argo CD installation and project
@plain
Argo CD runs in its own namespace. An AppProject limits what an application may deploy and where.
@problem
An Argo CD application that can deploy anything anywhere is a cluster-admin backdoor.
@does
- Install from the official manifests or Helm chart; check the current Argo CD docs for versions. High availability needs 3 replicas for the repo server and application controller sharding for large fleets (see the Argo CD at scale chapter).
- `AppProject shop` allows the source repository, destination namespace `shop` only, and a whitelist of cluster-scoped resources (`Namespace`).
- Users sign in through SSO; roles map groups to read-only, sync, or admin.
- Notifications send sync status to chat.
@diagram flow
caption: Least privilege for GitOps
nodes:
  - "AppProject shop|repo and namespace limits|warn"
  - "Application dev|auto sync|info"
  - "Application staging|auto sync|info"
  - "Application prod|manual sync|ok"
@h AppProject
```yaml title="gitops/project.yaml"
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: shop
  namespace: argocd
spec:
  description: Shop application
  sourceRepos:
    - https://github.com/acme/shop.git
  destinations:
    - namespace: shop
      server: https://kubernetes.default.svc
  clusterResourceWhitelist:
    - group: ""
      kind: Namespace
  roles:
    - name: release
      policies:
        - p, proj:shop:release, applications, sync, shop/*, allow
      groups:
        - shop-release
```
@end

@concept Argo CD applications per environment
@plain
One Application per environment points at an overlay folder. Dev and staging sync automatically; prod waits for a person.
@problem
Auto-sync everywhere is risky for prod; manual sync everywhere is slow for dev.
@does
- `source.path: deploy/overlays/<env>` and `targetRevision: main`.
- `syncPolicy.automated` with `prune: true` and `selfHeal: true` for dev and staging: manual edits are reverted.
- Prod has no `automated` block; the sync is a button press or a CLI command by the release group. Some teams enable auto-sync in prod only when promotion already needs approval.
- `CreateNamespace` is off because the base owns the namespace; `ServerSideApply` helps with big CRDs.
@diagram seq
caption: Prod sync with manual step
actors: ["Release engineer|person|ext", "Argo CD|controller|cp", "Git|main|plain", "EKS prod|cluster|ok"]
steps:
  - "0>1: review diff | req"
  - "1>2: render overlay prod | req"
  - "0>1: click sync | req"
  - "1>3: apply with hooks | tls"
  - "3>1: health | resp"
@h gitops/apps.yaml
```yaml title="gitops/apps.yaml"
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shop-dev
  namespace: argocd
spec:
  project: shop
  source:
    repoURL: https://github.com/acme/shop.git
    targetRevision: main
    path: deploy/overlays/dev
  destination:
    server: https://kubernetes.default.svc
    namespace: shop
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - ServerSideApply=true
---
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shop-prod
  namespace: argocd
spec:
  project: shop
  source:
    repoURL: https://github.com/acme/shop.git
    targetRevision: main
    path: deploy/overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: shop
  syncPolicy:
    syncOptions:
      - ServerSideApply=true
```
:::note
Dev, staging and prod are three different clusters. In real use each Application is registered in the Argo CD that manages its cluster, or one central Argo CD holds three cluster registrations. See the Argo CD at scale chapter.
:::
@end

@concept Database migrations as a pre-sync hook
@plain
A Kubernetes Job runs before the new pods start. It applies schema changes with a migration tool and exits.
@problem
Starting new code against an old schema (or the reverse) breaks requests during the rollout.
@does
- An Argo CD `PreSync` hook Job runs `alembic upgrade head` (or your tool) using the service's database secret.
- Migrations follow the expand/contract rule: first add columns or tables (old code still works), deploy code, later remove the old structure in a separate release.
- The Job has `backoffLimit: 0` so a failed migration stops the sync instead of retrying forever.
- Rolling back code is safe only if the schema change was backward compatible.
@diagram flow
caption: Expand, deploy, contract
nodes:
  - "Release N|add nullable column|info"
  - "Release N+1|code uses column|app"
  - "Release N+2|drop old column|warn"
  - "Rollback safe|between each step|ok"
@h Hook Job
```yaml title="deploy/base/migrate-orders.yaml"
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate-orders
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: BeforeHookCreation
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
      containers:
        - name: migrate
          image: shop/orders
          command: ["python", "-m", "app.migrate"]
          envFrom:
            - secretRef: {name: orders-db}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
```
:::tip
The sample services create their tables at startup with `create_all` for simplicity. In production replace that with real migrations and the hook above; `create_all` cannot alter existing tables.
:::
@end
