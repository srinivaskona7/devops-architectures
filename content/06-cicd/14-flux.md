---
title: GitOps with Flux
minutes: 45
objectives:
  - Describe the Flux controllers and bootstrap a cluster from Git
  - Define GitRepository, Kustomization and HelmRelease resources
  - Automate image updates and compare Flux with Argo CD
---
Flux is the CNCF GitOps toolkit. It is a set of small controllers, each with its own custom resources, rather than one application with a UI.

@concept Flux architecture and bootstrap
@plain
Flux runs in the `flux-system` namespace as separate controllers: source, kustomize, helm and notification, plus optional image automation. `flux bootstrap` installs them and commits their own manifests to Git.
@problem
You want GitOps without a central server, with every part of Flux itself managed from Git too.
@does
- **source-controller** fetches Git, Helm, OCI and bucket sources. **kustomize-controller** applies Kustomizations. **helm-controller** manages Helm releases. **notification-controller** sends and receives events.
- `flux bootstrap github` creates the repository content, installs the controllers and sets up a deploy key.
- Everything is a Kubernetes custom resource, so `kubectl` and `flux` CLI both work.
@diagram layers
caption: Flux controllers
layers:
  - {label: "Sources", nodes: ["source-controller|Git, Helm, OCI, S3|cp"]}
  - {label: "Appliers", nodes: ["kustomize-controller|Kustomization|app", "helm-controller|HelmRelease|app"]}
  - {label: "Extras", nodes: ["notification-controller|alerts and webhooks|info", "image-reflector and automation|tag scanning and commits|info"]}
@h Bootstrap
```bash title="Bootstrap Flux against a GitHub repository" lab
flux check --pre
export GITHUB_TOKEN=<your-token>
flux bootstrap github \
  --owner=my-org --repository=fleet --branch=main \
  --path=clusters/prod --personal=false
flux get all -A
```
@check
Where does flux bootstrap put Flux's own manifests? || In the Git repository at the path you gave, so Flux manages itself from Git.
@end

@concept GitRepository and sources
@plain
A `GitRepository` object tells source-controller which repository and branch to fetch and how often. Other resources then refer to it as their source.
@problem
Applying manifests needs a reliable, verified copy of the repository inside the cluster.
@does
- `url`, `ref` (branch, tag, semver or commit) and `interval` set what to track.
- `secretRef` supplies a deploy key or token for private repositories.
- Verification of signed commits or tags can be enabled. Check the current docs for the fields.
- `OCIRepository` fetches manifests packaged as OCI artifacts, which avoids Git credentials in the cluster.
@diagram flow
caption: Source to cluster
nodes:
  - "GitRepository|fetch every interval|info"
  - "Artifact|tarball in the cluster|cp"
  - "Kustomization|builds and applies|app"
  - "Resources|live|ok"
@h A source
```yaml title="gitrepository.yaml"
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: shop-config
  namespace: flux-system
spec:
  interval: 1m
  url: https://github.com/my-org/shop-config.git
  ref:
    branch: main
  secretRef:
    name: shop-config-auth
```
@end

@concept Flux Kustomization
@plain
A Flux `Kustomization` points at a path inside a source and applies it, like an Argo CD Application. It adds pruning, health checks, dependencies and variable substitution.
@problem
You need ordered, pruned, health-checked application of manifests from Git.
@does
- Not to be confused with the Kustomize `kustomization.yaml`. Flux builds Kustomize overlays itself and also plain YAML.
- `prune: true` deletes what was removed from Git. `wait: true` and `healthChecks` wait for readiness.
- `dependsOn` orders Kustomizations, for example infrastructure before apps.
- `postBuild.substituteFrom` injects cluster-specific values from ConfigMaps and Secrets.
@diagram flow
caption: Dependencies between Kustomizations
nodes:
  - "infrastructure|cert-manager, ingress|cp"
  - "apps-staging|dependsOn infrastructure|app"
  - "apps-prod|dependsOn infrastructure|env"
@h Two linked Kustomizations
```yaml title="kustomizations.yaml"
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: infrastructure
  namespace: flux-system
spec:
  interval: 10m
  path: ./infrastructure
  prune: true
  wait: true
  sourceRef:
    kind: GitRepository
    name: shop-config
---
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: apps
  namespace: flux-system
spec:
  interval: 5m
  dependsOn:
    - name: infrastructure
  path: ./apps/prod
  prune: true
  sourceRef:
    kind: GitRepository
    name: shop-config
  postBuild:
    substitute:
      CLUSTER_NAME: prod-eu
```
@check
What does dependsOn guarantee? || The dependency is applied and ready before this Kustomization is reconciled.
@end

@concept HelmRelease
@plain
A `HelmRelease` installs and upgrades a Helm chart declaratively. Charts come from a `HelmRepository`, a `GitRepository` or an `OCIRepository`.
@problem
Running `helm upgrade` by hand or in a pipeline leaves no record of what is installed and cannot self-correct.
@does
- Values go in `spec.values` or `valuesFrom` ConfigMaps and Secrets.
- Install and upgrade remediation can retry and roll back on failure.
- helm-controller does not use Helm hooks differently from Helm itself, but it tracks drift on the release, with options to correct it. Check the current docs for the drift detection settings.
- Charts versions can use semver ranges, but production usually pins an exact version.
@diagram flow
caption: Chart to release
nodes:
  - "HelmRepository|chart index|ext"
  - "HelmRelease|version and values|cp"
  - "helm-controller|install or upgrade|app"
  - "Release|rollback on failure|ok"
@h Chart from an OCI registry
```yaml title="helmrelease.yaml"
apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: ingress-nginx
  namespace: flux-system
spec:
  interval: 1h
  url: https://kubernetes.github.io/ingress-nginx
---
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: ingress-nginx
  namespace: ingress-nginx
spec:
  interval: 10m
  chart:
    spec:
      chart: ingress-nginx
      version: "4.11.x"
      sourceRef:
        kind: HelmRepository
        name: ingress-nginx
        namespace: flux-system
  install:
    remediation: {retries: 3}
  upgrade:
    remediation: {retries: 3, remediateLastFailure: true}
  values:
    controller:
      replicaCount: 2
```
:::note
The chart version above is an example range. Pin the exact version you have tested.
:::
@end

@concept Image automation
@plain
Flux can watch a container registry for new tags, choose the newest that matches a policy, and commit the new tag back to Git. Three resources do this: ImageRepository, ImagePolicy and ImageUpdateAutomation.
@problem
Someone or something must update the image tag in Git after each build. Doing it from CI means CI needs write access to the config repository.
@does
- `ImageRepository` scans a registry for tags. `ImagePolicy` selects one, using semver, numeric or alphabetical rules.
- Markers like `# {"$imagepolicy": "flux-system:shop"}` in YAML tell `ImageUpdateAutomation` which line to rewrite.
- The automation commits to a branch you choose, optionally a separate one for pull request review.
- Check the current docs; the image automation APIs have been through version changes.
@diagram flow
caption: From registry to Git
numbered: true
nodes:
  - "New tag pushed|CI to ECR|app"
  - "ImageRepository|scans tags|info"
  - "ImagePolicy|picks the latest semver|cp"
  - "ImageUpdateAutomation|commits to Git|warn"
  - "Kustomization|rolls out|ok"
@h Policy and marker
```yaml title="Image policy"
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: shop
  namespace: flux-system
spec:
  imageRepositoryRef:
    name: shop
  policy:
    semver:
      range: ">=1.0.0 <2.0.0"
```
```yaml title="Marker in a manifest" nocheck
image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:1.4.2 # {"$imagepolicy": "flux-system:shop"}
```
@check
Which resource decides which tag is newest? || The ImagePolicy.
@end

@concept Flux operations and troubleshooting
@plain
The `flux` CLI shows the state of every object, forces a reconcile, suspends changes and traces which object created a resource.
@problem
When a deploy does not appear, you need to find which link failed: fetching the source, building the manifests or applying them.
@does
- `flux get kustomizations -A` and `flux get helmreleases -A` show Ready status and the last message.
- `flux reconcile source git NAME` fetches immediately.
- `flux suspend` and `flux resume` stop and start reconciliation, the equivalent of pausing auto-sync.
- `flux trace` follows a resource back to its source. `flux events` and controller logs show details.
@diagram flow
caption: Debugging order
nodes:
  - "Source ready?|flux get sources|info"
  - "Kustomization ready?|flux get kustomizations|app"
  - "HelmRelease ready?|flux get helmreleases|app"
  - "Controller logs|kubectl logs|warn"
@h Daily commands
```bash title="Inspect and force" lab
flux get sources git -A
flux get kustomizations -A
flux reconcile kustomization apps --with-source
flux suspend kustomization apps       # freeze during an incident
flux resume kustomization apps
flux trace deployment shop -n shop
```
@check
How do you pause Flux for one Kustomization? || flux suspend kustomization NAME, then flux resume when done.
@end

@concept Flux versus Argo CD
@plain
Both implement GitOps well. Argo CD gives a rich UI and an application model. Flux gives composable controllers and tight Helm and Kustomize integration, without a central UI by default.
@problem
Teams pick one by reputation and later find it does not match their operating model.
@does
- Argo CD: strong UI, ApplicationSets, SSO and RBAC built in, central multi-cluster control.
- Flux: lightweight, per-cluster agents, native image automation, OCI sources, multi-tenancy through Kubernetes RBAC and impersonation.
- Either can run on EKS and either works with Helm, Kustomize and plain YAML.
- Both work with Argo Rollouts or Flagger for progressive delivery. Flagger is from the Flux project.
@diagram cmp
caption: Which fits
cards:
  - {h: "Argo CD", kind: app, items: ["Visual app health", "Central control of many clusters", "Built-in SSO and RBAC", "Needs a more guarded hub"]}
  - {h: "Flux", kind: info, items: ["Per-cluster, no hub", "Built-in image automation", "Plain Kubernetes RBAC", "No full UI by default"]}
@h Same intent, two shapes
```yaml title="Flux Kustomization is roughly an Argo CD Application"
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata: {name: shop, namespace: flux-system}
spec:
  interval: 5m
  path: ./apps/shop/overlays/prod
  prune: true
  sourceRef: {kind: GitRepository, name: shop-config}
  targetNamespace: shop
```
:::tip
A frequent split is Flux or Argo CD for GitOps delivery, and a separate progressive delivery tool for canaries.
:::
@end
