---
title: Kustomize patches, components and Helm together
minutes: 40
objectives:
  - Write strategic merge and JSON 6902 patches with targets
  - Package optional features as components
  - Choose between Helm and Kustomize and combine them
---
Patching is where Kustomize earns its keep. This section covers the two patch styles, reusable components, inflating Helm charts, and how to decide between the tools.

@concept Strategic merge patches
@plain
A strategic merge patch is a partial manifest. You write only the fields you want to change, with enough identity (kind and name) to find the target, and Kustomize merges it in.
@problem
You need to change one field, such as a memory limit, in the base without copying the whole Deployment.
@does
- Lists of containers merge by the `name` key, so a patch naming container `api` updates just that container.
- Setting a value to `null` deletes a field; `$patch: delete` removes a whole object.
- `patches:` with `path` or inline `patch` and an optional `target` selector is the current syntax. `patchesStrategicMerge` is deprecated.
@diagram flow
caption: Patch merges into the matching object
nodes:
  - "Base Deployment|api, 256Mi limit|plain"
  - "Patch|api, 1Gi limit|warn"
  - "Merge by name|container api|info"
  - "Result|only the limit changed|ok"
@h Patch file
```yaml title="overlays/prod/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
patches:
  - path: resources-patch.yaml
    target:
      kind: Deployment
      name: api
```
```yaml title="overlays/prod/resources-patch.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
        - name: api
          resources:
            requests: {cpu: 500m, memory: 1Gi}
            limits: {memory: 1Gi}
```
@end

@concept JSON 6902 patches
@plain
A JSON patch is an explicit list of operations (`add`, `remove`, `replace`) on paths in the document. It is precise and works on any object, including custom resources.
@problem
Strategic merge relies on schema knowledge. For CRDs, or when you must change one list item by index or remove a field, you need exact control.
@does
- Each operation has `op`, `path` and for add or replace a `value`.
- List items are addressed by index (`/spec/template/spec/containers/0/args/-` appends).
- Inline patches in `kustomization.yaml` keep small changes next to the target selection.
- Selectors can match by `kind`, `name`, `labelSelector` or `annotationSelector`, including regular expressions for names.
@diagram cmp
caption: Which patch style to use
cards:
  - {h: "Strategic merge", kind: ok, items: ["Readable partial manifest", "Lists merge by name", "Built-in kinds"]}
  - {h: "JSON 6902", kind: info, items: ["Exact operations", "Works on CRDs", "Index based lists are brittle"]}
@h Inline JSON patch
```yaml title="kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
patches:
  - target:
      kind: Deployment
      name: api
    patch: |-
      - op: add
        path: /spec/template/spec/containers/0/args/-
        value: --log-format=json
      - op: replace
        path: /spec/replicas
        value: 4
      - op: remove
        path: /spec/template/spec/containers/0/ports/0
```
@end

@concept Components
@plain
A **component** is a reusable bundle of resources and patches for an optional feature. Overlays opt in by listing it under `components:`.
@problem
Several overlays need the same optional feature, such as a monitoring sidecar or a PodDisruptionBudget, but not all of them. Copying patches between overlays repeats work.
@does
- A component's `kustomization.yaml` has `kind: Component` and `apiVersion: kustomize.config.k8s.io/v1alpha1`.
- It is applied after the resources of the overlay, so it can patch them.
- Overlays then differ only by which components they include.
@diagram layers
caption: Mix and match features
layers:
  - {label: "Overlay", nodes: ["prod|includes components|env"]}
  - {label: "Components", nodes: ["pdb|PodDisruptionBudget|ok", "hpa|autoscaling|ok", "tls|certificate and Ingress TLS|ok"]}
  - {label: "Base", nodes: ["api|Deployment and Service|app"]}
@h A component
```yaml title="components/pdb/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
resources:
  - pdb.yaml
```
```yaml title="overlays/prod/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
components:
  - ../../components/pdb
  - ../../components/hpa
```
@end

@concept Remote bases and the helmCharts generator
@plain
A kustomization can use a Git repository as a base, and can inflate a Helm chart into plain YAML so you can patch it.
@problem
Third-party software ships as a Helm chart or a Git repository, and you need to adjust it without forking.
@does
- Remote base: `github.com/org/repo//path?ref=v1.2.3`. Always pin `ref` to a tag or commit.
- `helmCharts:` renders a chart (`name`, `repo`, `version`, `releaseName`, `namespace`, `valuesInline`) during build. Run with `kustomize build --enable-helm`.
- Patches then apply to the rendered output, which is the same bridge a Helm post-renderer provides.
- Helm hooks and release tracking are lost; Kustomize only emits YAML.
@diagram flow
caption: Third party chart patched in Git
nodes:
  - "Public chart|pinned version|ext"
  - "helmCharts|rendered at build|info"
  - "Your patches|labels, limits|warn"
  - "Plain YAML|applied by kubectl or GitOps|ok"
@h Example
```yaml title="kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
helmCharts:
  - name: ingress-nginx
    repo: https://kubernetes.github.io/ingress-nginx
    version: 4.11.3
    releaseName: ingress
    namespace: ingress
    valuesInline:
      controller:
        replicaCount: 3
patches:
  - target:
      kind: Deployment
      name: ingress-ingress-nginx-controller
    patch: |-
      - op: add
        path: /spec/template/spec/priorityClassName
        value: system-cluster-critical
```
```bash title="Build" lab
kustomize build --enable-helm . | kubectl apply --server-side -f -
```
@end

@concept Helm or Kustomize
@plain
They solve different problems. Helm packages and distributes software with logic and a release lifecycle. Kustomize adapts YAML you own for several environments without logic.
@problem
Teams pick one tool for everything, then fight it: complicated templates for simple overlays, or large patch sets for software that is really configurable.
@does
- Use Helm to consume third-party software and to publish software to others.
- Use Kustomize for your own apps across dev, staging and prod when differences are small.
- Combine them: Helm for the vendor chart, Kustomize for last-mile patches, a GitOps tool to apply.
- Both must be reviewed as rendered output; render in CI and diff.
@diagram cmp
caption: Strengths side by side
cards:
  - {h: "Helm", kind: app, items: ["Templates, hooks, tests", "Versioned packages in OCI", "Release history and rollback"]}
  - {h: "Kustomize", kind: env, items: ["Plain YAML in and out", "Patches and components", "Built into kubectl"]}
@choose Picking a tool
Helm | you install vendor software or ship your app to many users | the only difference is replicas and image tag per environment
Kustomize | you own the YAML and need per environment overlays | you need hooks, conditionals or a distributable package
Helm plus Kustomize | you must patch a chart you cannot change | a plain values override already does the job
@end

@concept Validating rendered output
@plain
Whatever generates your YAML, the final result should be checked before it reaches the cluster: schema validity, policy rules and live diff.
@problem
A typo in a patch path may still render valid YAML that is silently wrong, such as a limit that was not applied.
@does
- `kubectl apply --dry-run=server` checks against the real API, including admission webhooks.
- `kubeconform` validates against Kubernetes JSON schemas offline and can include CRD schemas.
- `kubectl diff` shows the effect on live objects. Policy tools such as Kyverno CLI or conftest can enforce rules in CI.
- Check that your patch really landed by grepping the rendered output for the changed value.
@diagram flow
caption: A render and validate stage in CI
numbered: true
nodes:
  - "kustomize build|per overlay|app"
  - "kubeconform|schema check|info"
  - "Policy check|Kyverno or conftest|warn"
  - "kubectl diff|against the cluster|cp"
@h Commands
```bash title="CI validation" lab
for env in dev staging prod; do
  kustomize build overlays/$env > /tmp/$env.yaml
  kubeconform -strict -summary -ignore-missing-schemas /tmp/$env.yaml
done
kubectl diff -f /tmp/prod.yaml || test $? -eq 1   # diff exits 1 when differences exist
```
@check
How do overlays opt in to optional features? || By listing components in the components field of their kustomization.
Which patch style works well on a custom resource? || A JSON 6902 patch, because it needs no schema knowledge.
@end
