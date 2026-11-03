---
title: GitOps with Argo CD
minutes: 50
objectives:
  - Explain the GitOps model and how Argo CD reconciles a cluster with Git
  - Write Applications with sync policies, waves, hooks and health checks
  - Detect and handle drift safely
---
GitOps means the desired state of the cluster lives in Git, and an in-cluster controller makes reality match it. CI builds artifacts, Git records intent, and the controller deploys.

@concept The GitOps model
@plain
In GitOps, a Git repository describes what should run. An agent inside the cluster pulls that description and applies it continuously, instead of a pipeline pushing changes from outside.
@problem
Push-based pipelines need cluster credentials stored in the CI system, cannot detect manual changes made later, and leave no single record of what the cluster should look like.
@does
- Git is the source of truth with history, review and rollback by revert.
- The controller compares live state with Git and reports or corrects differences.
- Cluster credentials stay inside the cluster. CI needs only write access to Git.
- Four commonly cited principles are declarative, versioned and immutable, pulled automatically, and continuously reconciled.
@diagram flow
caption: Pull-based delivery
nodes:
  - "CI|builds image, bumps tag in Git|app"
  - "Config repo|desired state|info"
  - "Argo CD|in the cluster, pulls|cp"
  - "Cluster|live state matches Git|ok"
@h Push versus pull
```yaml title="CI's whole deploy job becomes a Git commit" nocheck
- name: Bump image tag in the config repository
  run: |
    git clone https://x-access-token:${TOKEN}@github.com/my-org/shop-config.git
    cd shop-config/apps/shop/overlays/staging
    kustomize edit set image shop=111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop@${DIGEST}
    git commit -am "shop ${DIGEST:0:19}" && git push
```
@check
Where do cluster credentials live in pull-based GitOps? || Inside the cluster. CI never holds them.
@end

@concept Argo CD architecture and install
@plain
Argo CD runs as a set of components in the `argocd` namespace: an API server (UI and CLI), a repo server that renders manifests, an application controller that compares and syncs, and Redis for caching.
@problem
You need a controller that can render Helm, Kustomize and plain YAML from Git and compare it to the cluster at scale.
@does
- The **repo server** clones repositories and renders manifests, so give it limited resources and trusted sources.
- The **application controller** watches live resources and Git state and computes the diff.
- Argo CD can manage the cluster it runs in or remote clusters that you register.
- Install with the official manifests or the Helm chart. Check the current docs for versions.
@diagram layers
caption: Argo CD components
layers:
  - {label: "Users", nodes: ["Web UI and argocd CLI|human access|ext", "Git webhooks|fast refresh|ext"]}
  - {label: "argocd namespace", nodes: ["API server|auth and RBAC|cp", "Repo server|renders manifests|cp", "Application controller|diff and sync|cp", "Redis|cache|db"]}
  - {label: "Targets", nodes: ["In-cluster|kubernetes.default.svc|env", "Remote clusters|registered with credentials|env"]}
@h Install and log in
```bash title="Install Argo CD" lab
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
argocd login localhost:8080 --username admin   # after: kubectl -n argocd port-forward svc/argocd-server 8080:443
```
:::tip
Pin to a release tag in production instead of the stable branch, and change the initial admin password or disable the admin user once SSO works.
:::
@end

@concept The Application resource
@plain
An `Application` custom resource links one source (a path in a Git repository, or a Helm chart) to one destination (a cluster and namespace).
@problem
You need a declarative object that says what to deploy where, so even the deployments are stored as code.
@does
- `spec.source` has `repoURL`, `targetRevision` (branch, tag or commit) and `path` or `chart`.
- `spec.destination` has `server` or `name` and `namespace`.
- `spec.project` assigns it to an AppProject that limits what it may do.
- Helm values, Kustomize options or plain directories are detected from the path.
@diagram flow
caption: What an Application ties together
nodes:
  - "Source|repo, revision, path|info"
  - "Application|desired state object|cp"
  - "Destination|cluster and namespace|env"
  - "Project|allowed repos and clusters|warn"
@h A complete Application
```yaml title="application.yaml"
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shop-staging
  namespace: argocd
spec:
  project: shop
  source:
    repoURL: https://github.com/my-org/shop-config.git
    targetRevision: main
    path: apps/shop/overlays/staging
  destination:
    server: https://kubernetes.default.svc
    namespace: shop-staging
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - CreateNamespace=true
```
@check
What does targetRevision control? || Which branch, tag or commit of the repository Argo CD tracks.
@end

@concept Sync policies and options
@plain
Sync means applying the Git state to the cluster. It can be manual (someone clicks sync) or automated, with extra switches that decide how aggressive it is.
@problem
Automatic deletion or overwriting can surprise teams, while manual sync leaves clusters out of date.
@does
- `automated` syncs when Git changes. `prune: true` deletes resources removed from Git. `selfHeal: true` reverts manual changes in the cluster.
- `syncOptions` such as `CreateNamespace=true`, `ServerSideApply=true`, `PruneLast=true`, `Replace=true`. Check the docs for the full list.
- `retry` with back-off helps with ordering problems. `ignoreDifferences` skips fields set by other controllers, for example replica counts managed by an HPA.
@diagram cmp
caption: Suggested policy by environment
cards:
  - {h: "Development", kind: ok, items: ["automated", "prune and selfHeal on"]}
  - {h: "Staging", kind: info, items: ["automated", "prune on, watch for surprises"]}
  - {h: "Production", kind: warn, items: ["Automated or manual by policy", "Sync windows for change control"]}
@h Ignore HPA-managed fields
```yaml title="Policy fragment"
syncPolicy:
  automated:
    prune: true
    selfHeal: true
  syncOptions:
    - ServerSideApply=true
    - PruneLast=true
  retry:
    limit: 5
    backoff: {duration: 10s, factor: 2, maxDuration: 3m}
ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers: [/spec/replicas]
```
@check
What does selfHeal do? || It reverts changes made directly in the cluster so it matches Git again.
@end

@concept Sync waves and hooks
@plain
Resources can be given an order with a **sync wave** annotation, and jobs can run at specific moments with **hooks** such as PreSync and PostSync.
@problem
Some resources must exist before others: a namespace before workloads, a CRD before its custom resources, a database migration before the new application version.
@does
- `argocd.argoproj.io/sync-wave: "-1"` runs earlier. Lower numbers first, default 0. Argo CD waits for each wave to be healthy before the next.
- `argocd.argoproj.io/hook: PreSync` runs a Job before the sync, `PostSync` after, `SyncFail` on failure.
- `hook-delete-policy: HookSucceeded` cleans up finished hook jobs.
@diagram flow
caption: Ordered rollout
numbered: true
nodes:
  - "PreSync hook|database migration job|warn"
  - "Wave -1|namespace and CRDs|info"
  - "Wave 0|deployments and services|app"
  - "Wave 1|ingress|env"
  - "PostSync hook|smoke test|ok"
@h Migration hook and wave annotations
```yaml title="Migration as a PreSync hook"
apiVersion: batch/v1
kind: Job
metadata:
  name: shop-migrate
  annotations:
    argocd.argoproj.io/hook: PreSync
    argocd.argoproj.io/hook-delete-policy: HookSucceeded
spec:
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop-migrate:1.4.2
          args: ["up"]
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: shop-config
  annotations:
    argocd.argoproj.io/sync-wave: "-1"
data:
  LOG_LEVEL: info
```
@check
Which number runs first, wave 2 or wave -1? || -1. Lower numbers run first.
@end

@concept Health assessment and sync status
@plain
Argo CD shows two separate states. **Sync status** says whether live matches Git (Synced or OutOfSync). **Health** says whether the resources work (Healthy, Progressing, Degraded, Missing, Suspended).
@problem
A resource can match Git exactly and still be broken, such as a Deployment whose pods crash. You need both signals.
@does
- Built-in checks cover Deployments, StatefulSets, Services, Ingresses, PVCs and more.
- For custom resources you add a Lua health check in `argocd-cm`, or use the community-provided ones that ship with Argo CD.
- Waves wait on health, so a failing Deployment pauses later waves.
- Argo Rollouts resources are understood by Argo CD health checks.
@diagram cmp
caption: Reading the two statuses
cards:
  - {h: "Synced and Healthy", kind: ok, items: ["Desired state running", "Nothing to do"]}
  - {h: "Synced and Degraded", kind: bad, items: ["Git applied, pods failing", "Look at events and logs"]}
  - {h: "OutOfSync and Healthy", kind: warn, items: ["Live differs from Git", "Drift or pending commit"]}
@h Inspect from the CLI
```bash title="Check application state" lab
argocd app get shop-staging
argocd app diff shop-staging
argocd app history shop-staging
argocd app sync shop-staging --dry-run
```
:::note
Add Lua health checks for custom resources through `resource.customizations.health.<group>_<kind>` in the `argocd-cm` ConfigMap. Check the current docs for exact keys.
:::
@end

@concept Drift detection and self-heal
@plain
Drift is any difference between Git and the cluster, such as a manual `kubectl edit`. Argo CD compares continuously, marks the app OutOfSync, and can revert the change with self-heal.
@problem
Hotfixes made with `kubectl` and never committed disappear on the next deploy or create mysterious differences between environments.
@does
- The controller refreshes on a timer (three minutes by default) and on webhooks from Git.
- The diff ignores fields that controllers legitimately change when configured via `ignoreDifferences`.
- `selfHeal: true` reverts drift. Without it, the app stays OutOfSync until someone syncs.
- For emergencies, disable auto-sync on that app, apply the fix, then commit it to Git and re-enable.
@diagram seq
caption: Self-heal reverting a manual change
actors: ["Engineer|kubectl edit|ext", "Cluster|live resource|env", "Argo CD|controller|cp"]
steps:
  - "0>1: change replicas by hand | req"
  - "2>1: detect diff against Git | req"
  - "note 2..2: OutOfSync, selfHeal on"
  - "2>1: apply Git state | req"
@h Break glass procedure
```bash title="Pause auto-sync during an incident" lab
argocd app set shop-prod --sync-policy none     # stop reverting while you investigate
kubectl -n shop scale deploy/shop --replicas=10
# after the incident, commit the real fix to Git, then re-enable
argocd app set shop-prod --sync-policy automated --self-heal
```
@check
How do you do an emergency change without fighting self-heal? || Temporarily disable auto-sync, apply the change, commit it to Git and re-enable.
@end

@concept Repository layout and manifests
@plain
Keep application code and deployment configuration in separate repositories, or at least separate directories, with an overlay per environment.
@problem
Mixing source code and manifests means every image bump triggers code CI, and CI commits clutter application history. Separate access control is also hard.
@does
- A config repo holds `base/` plus `overlays/dev`, `staging`, `prod`, or Helm values files per environment.
- Promotion is a pull request that changes the image digest in the next environment's overlay.
- Rendering tools: Kustomize, Helm and plain YAML are built in. Others plug in as config management plugins.
- Protect the production path with CODEOWNERS and required reviews.
@diagram layers
caption: Config repository layout
layers:
  - {label: "base", nodes: ["deployment.yaml|common|app", "service.yaml|common|app", "kustomization.yaml|resource list|info"]}
  - {label: "overlays", nodes: ["dev|1 replica, latest digest|env", "staging|2 replicas|env", "prod|6 replicas, PDB|ok"]}
@h Kustomize overlay
```yaml title="apps/shop/overlays/prod/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: shop
resources:
  - ../../base
images:
  - name: shop
    newName: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop
    digest: sha256:4f3a9c1d2b7e8a0c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4
replicas:
  - name: shop
    count: 6
```
@end
