---
title: Helm hooks, diff, OCI charts and delivery
minutes: 45
objectives:
  - Run migrations and checks with hooks and know their deletion policies
  - Preview changes with helm diff and publish charts to an OCI registry
  - Choose between pipeline driven Helm and GitOps controllers
---
A release is more than apply. Databases must migrate, changes should be reviewed before they land, and charts need a trusted home. This section covers hooks, previewing, OCI registries and how Helm fits into delivery.

@concept Hooks
@plain
A **hook** is a manifest in a chart that Helm runs at a chosen moment of the release lifecycle, such as before an upgrade, instead of treating it as a normal part of the release.
@problem
A database migration must finish before the new Pods start, and a cleanup Job must run after an uninstall. Plain manifests are applied together with no ordering.
@does
- Marked by the annotation `helm.sh/hook` with values such as `pre-install`, `post-install`, `pre-upgrade`, `post-upgrade`, `pre-delete`, `post-delete`, `pre-rollback`, `post-rollback` and `test`.
- Helm waits for hook Jobs and Pods to complete; a failed `pre-upgrade` hook stops the upgrade.
- `helm.sh/hook-weight` orders hooks of the same kind (lower first, as strings of integers).
- Hook objects are not part of the release, so `helm uninstall` does not remove them unless you set a delete policy.
@diagram seq
caption: A pre-upgrade migration gates the rollout
actors: ["Helm|client|app", "Migration Job|pre-upgrade|env", "Deployment|new version|app"]
steps:
  - "0>1: create Job | req"
  - "note 1..1: runs schema migration"
  - "1>0: Job completed | resp"
  - "0>2: apply new manifests | req"
  - "1>0: Job failed, abort upgrade | bad"
@h A migration hook
```yaml title="templates/migrate-job.yaml"
apiVersion: batch/v1
kind: Job
metadata:
  name: shop-migrate
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "0"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 1
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: registry.example.com/shop/api:1.8.3
          command: ["./migrate", "up"]
```
@end

@concept Hook delete policies and pitfalls
@plain
Delete policies decide when Helm removes a hook object. Without one, a completed Job from the last run remains and the next run fails with "already exists".
@problem
Hooks are the most common source of stuck pipelines: leftover Jobs, hooks waiting on resources that do not exist yet, and migrations that are not safe to run twice.
@does
- `before-hook-creation` (default) deletes the old object before a new one is made. `hook-succeeded` and `hook-failed` delete after the outcome.
- Keep failed hooks (omit `hook-failed`) so you can read the Pod logs.
- A `pre-install` hook runs before the release's other resources exist, so it cannot use a ServiceAccount or ConfigMap from the same chart unless that is also a hook with a lower weight.
- Make migrations idempotent and backwards compatible, because a rollback does not undo them.
@diagram cmp
caption: Delete policy choices
cards:
  - {h: "before-hook-creation", kind: ok, items: ["Default", "Clears the previous run", "Leaves last run for logs"]}
  - {h: "hook-succeeded", kind: info, items: ["Tidy after success", "Nothing left behind"]}
  - {h: "hook-failed", kind: warn, items: ["Removes evidence", "Use rarely"]}
@h Diagnosing a stuck hook
```bash title="Find the hook Job and its logs" lab
helm get hooks shop -n shop | head -30
kubectl get jobs,pods -n shop -l job-name=shop-migrate
kubectl logs -n shop job/shop-migrate --tail=50
kubectl delete job shop-migrate -n shop     # remove a leftover before retrying
```
:::warn
Hooks run in a `helm upgrade --wait` pipeline with the pipeline's timeout. A migration that takes 20 minutes needs a matching `--timeout`, or Helm marks the release failed while the Job continues.
:::
@end

@concept helm diff and safe upgrades
@plain
`helm diff` is a plugin that renders the new revision and shows what would change compared with the live release, in the same style as `kubectl diff`.
@problem
Reading a values file tells you what you intended, not what will change in the cluster. A chart bump can alter dozens of objects you never mentioned.
@does
- Install with `helm plugin install https://github.com/databus23/helm-diff`.
- `helm diff upgrade RELEASE CHART -f values.yaml` prints a coloured diff; `--detailed-exitcode` returns 2 when there are changes, which is useful in CI.
- `--suppress-secrets` hides Secret content from logs.
- Pair it with `helm template | kubectl diff -f -` to also compare against edits made outside Helm.
@diagram flow
caption: A review gate in the pipeline
nodes:
  - "Pull request|values or chart change|plain"
  - "helm diff upgrade|posted as comment|info"
  - "Human review|approve|warn"
  - "helm upgrade --atomic|apply|ok"
@h In CI
```bash title="Diff gate" lab
helm plugin install https://github.com/databus23/helm-diff
helm diff upgrade shop ./shop -n shop -f values-prod.yaml --suppress-secrets --detailed-exitcode
echo "exit=$?"     # 0 no change, 1 error, 2 changes found
```
@end

@concept OCI charts and registries
@plain
Helm can store charts in any OCI registry (ECR, Harbor, GHCR, Artifact Registry), the same place you keep container images. A chart is addressed as `oci://registry/path/name`.
@problem
Classic HTTP chart repositories need an `index.yaml` to be rebuilt and hosted. Teams already operate an image registry with auth, replication and retention, and want one system for both.
@does
- `helm push chart.tgz oci://REGISTRY/PATH` publishes; the chart name and version become the repository and tag.
- `helm install shop oci://REGISTRY/PATH/shop --version 1.2.0` pulls and installs. There is no `helm repo add` step.
- `helm registry login` stores credentials. For Amazon ECR, pipe `aws ecr get-login-password` into it.
- Pin the exact `--version`; OCI charts also support pulling by digest.
@diagram flow
caption: Publishing and consuming a chart
numbered: true
nodes:
  - "helm package|shop-1.2.0.tgz|app"
  - "helm push|to the OCI registry|info"
  - "Registry|stores chart as artifact|db"
  - "helm install|oci URL and version|ok"
@h Amazon ECR example
```bash title="Push and install from ECR" lab
REG=123456789012.dkr.ecr.eu-west-1.amazonaws.com
aws ecr get-login-password --region eu-west-1 | helm registry login --username AWS --password-stdin "$REG"
aws ecr create-repository --repository-name charts/shop     # ECR needs the repo first
helm package ./shop                                           # shop-1.2.0.tgz
helm push shop-1.2.0.tgz oci://$REG/charts
helm install shop oci://$REG/charts/shop --version 1.2.0 -n shop
```
@end

@concept Signing, provenance and post-renderers
@plain
You can sign a chart so consumers verify it was not altered, and you can pipe Helm's rendered output through a program (a **post-renderer**) before it is applied.
@problem
Charts from third parties can change underneath you, and sometimes you must patch a chart you do not own, for example to add a label or a securityContext it does not expose.
@does
- `helm package --sign` creates a `.prov` file with a PGP signature; `helm verify` and `--verify` check it. Many teams instead sign OCI artifacts with cosign.
- `--post-renderer ./script` receives rendered YAML on standard input and returns changed YAML on standard output. A common script runs `kustomize build`.
- This is a clean bridge between Helm and Kustomize for charts you cannot modify.
@diagram flow
caption: Patching a third party chart without forking it
nodes:
  - "helm template|rendered YAML|info"
  - "Post-renderer|kustomize build|env"
  - "Patched YAML|extra labels and limits|app"
  - "Cluster|applied by Helm|cp"
@h A kustomize post-renderer
```bash title="post-render.sh" lab
#!/usr/bin/env bash
set -euo pipefail
cat > all.yaml                      # rendered chart arrives on stdin
kustomize build .                   # kustomization.yaml lists all.yaml plus patches
```
```bash title="Use it" lab
chmod +x post-render.sh
helm upgrade --install ingress ingress-nginx/ingress-nginx -n ingress --post-renderer ./post-render.sh
```
@end

@concept Helm in pipelines and GitOps
@plain
Two common models exist. In **pipeline driven** delivery your CI runs `helm upgrade`. In **GitOps** a controller in the cluster (Argo CD or Flux) watches Git and applies the chart itself.
@problem
Credentials for the cluster should not live in a CI system forever, and the live state should always match a reviewed source.
@does
- Pipeline model is simple and gives you hooks, `--atomic` and test steps natively; the pipeline needs cluster credentials, ideally short lived through OIDC.
- Argo CD renders charts with `helm template` and applies the result itself. Helm hooks are mapped onto Argo sync hooks, and there is no Helm release object. Flux's helm-controller does keep a real Helm release.
- Either way, pin chart versions and keep values in Git.
@diagram cmp
caption: Two delivery models
cards:
  - {h: "Pipeline push", kind: app, items: ["CI runs helm upgrade", "Needs cluster credentials", "Easy to start"]}
  - {h: "GitOps pull", kind: ok, items: ["Controller in the cluster", "Git is the source of truth", "Drift is reverted"]}
@choose Choosing a delivery model
Pipeline helm upgrade | a small number of clusters and a team new to GitOps | many clusters or a need for continuous drift correction
Flux HelmRelease | you want real Helm releases with GitOps pull | you need rich UI and app of apps views
Argo CD Application | you want a UI, multi cluster and sync waves | you rely on helm test or helm list showing the release
@check
Why add before-hook-creation to a migration Job? || Otherwise the Job from the previous run still exists and the next hook fails with already exists.
What does helm diff --detailed-exitcode return when changes exist? || Exit code 2.
@end
