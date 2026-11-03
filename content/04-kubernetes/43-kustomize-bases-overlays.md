---
title: Kustomize bases and overlays
minutes: 40
objectives:
  - Explain how Kustomize customises plain YAML without templates
  - Build a base and per environment overlays
  - Use generators, name prefixes, images and replacements
---
**Kustomize** is built into `kubectl` (`kubectl apply -k`). Instead of templating, it takes valid YAML as a **base** and applies declared changes on top in **overlays**. Every input and output is plain Kubernetes YAML.

@concept What Kustomize is
@plain
Kustomize reads a `kustomization.yaml` that lists resources and the changes to apply to them, then prints the final manifests. The original files are never modified.
@problem
Helm templates are powerful but hide the YAML behind logic. Teams that only need "same app, different replicas and image per environment" want to keep readable YAML and avoid a template language.
@does
- `kubectl kustomize DIR` (or `kustomize build DIR`) renders; `kubectl apply -k DIR` renders and applies.
- No variables or loops. Changes are expressed as patches, transformers and generators.
- The standalone `kustomize` binary is often newer than the version embedded in `kubectl`.
@diagram flow
caption: Rendering a kustomization
nodes:
  - "Resources|plain YAML files|plain"
  - "kustomization.yaml|list of changes|info"
  - "kustomize build|applies transformers|app"
  - "Final YAML|to stdout or kubectl|ok"
@h Smallest example
```yaml title="kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: shop
resources:
  - deployment.yaml
  - service.yaml
commonLabels:
  app.kubernetes.io/part-of: shop
```
```bash title="Render and apply" lab
kubectl kustomize . | head -30       # preview the output
kubectl apply -k . --dry-run=server  # validate against the API server
kubectl diff -k .                    # what would change
kubectl apply -k .
```
:::note
`commonLabels` also rewrites selectors, and selectors of a Deployment are immutable. For labels on metadata only, use the newer `labels:` field with `includeSelectors: false`.
:::
@end

@concept Bases and overlays
@plain
A **base** holds the shared manifests. An **overlay** is another directory whose `kustomization.yaml` points at the base and adds environment-specific changes.
@problem
Copying the whole manifest set per environment duplicates everything and the copies drift. You want one source and small differences.
@does
- Overlays reference a base in `resources:` by relative path or a remote Git URL pinned to a tag.
- Overlays can stack: `base`, then `overlays/prod`, then `overlays/prod-eu`.
- The directory structure is the convention, not a requirement.
@diagram layers
caption: Directory layout
layers:
  - {label: "Base", nodes: ["base/deployment.yaml|shared|app", "base/service.yaml|shared|app", "base/kustomization.yaml|lists them|info"]}
  - {label: "Overlays", nodes: ["overlays/dev|1 replica, small|env", "overlays/staging|2 replicas|env", "overlays/prod|5 replicas, HPA|env"]}
@h An overlay
```yaml title="overlays/prod/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: shop-prod
namePrefix: prod-
resources:
  - ../../base
  - hpa.yaml
images:
  - name: registry.example.com/shop/api
    newTag: "1.8.3"
replicas:
  - name: api
    count: 5
```
```bash title="Build each environment" lab
kubectl kustomize overlays/dev
kubectl kustomize overlays/prod | grep -E 'kind:|replicas:|image:'
```
@end

@concept The base manifests
@plain
The base is ordinary, valid YAML that could be applied by itself. It uses no placeholders.
@problem
A base that only works after substitution cannot be validated, linted or tested on its own.
@does
- The base lists its files in its own `kustomization.yaml`.
- Keep names generic (`api`) and let overlays add prefixes, namespaces and labels.
- Defaults in the base should be safe for the smallest environment.
@diagram flow
caption: The base stays valid on its own
nodes:
  - "base/|api Deployment and Service|app"
  - "kubectl apply -k base|works as is|ok"
  - "overlay/|adds only the differences|env"
@h Base files
```yaml title="base/deployment.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 1
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      containers:
        - name: api
          image: registry.example.com/shop/api:latest
          ports:
            - containerPort: 8080
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {memory: 256Mi}
```
```yaml title="base/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
  - service.yaml
```
@end

@concept Image, replica, namespace and name transformers
@plain
Built-in transformers change common fields everywhere they appear: image tags, replica counts, namespace, name prefix and suffix, labels and annotations.
@problem
CI needs to set a new image tag after every build. Editing YAML with `sed` is fragile; Kustomize does it structurally.
@does
- `images:` replaces `name` with `newName` or `newTag` or `digest` in Pod specs of all workload kinds.
- `replicas:` sets the count for named Deployments or StatefulSets.
- `namespace:` sets the namespace on all namespaced objects; `namePrefix` and `nameSuffix` rename and also fix up references (for example a ConfigMap name used by a Deployment).
- `kustomize edit set image NAME=NAME:TAG` updates the file for you.
@diagram flow
caption: A CI step that bumps the image
numbered: true
nodes:
  - "Build image|digest sha256|app"
  - "kustomize edit set image|updates overlay|info"
  - "Commit|to the config repo|plain"
  - "Apply|by GitOps or pipeline|ok"
@h Commands
```bash title="Set a tag from CI" lab
cd overlays/prod
kustomize edit set image registry.example.com/shop/api=registry.example.com/shop/api:1.8.4
kustomize edit set namespace shop-prod
git diff --stat
```
@check
Why not change the image with sed? || sed matches text; Kustomize edits the right field in every workload structurally and keeps the YAML valid.
@end

@concept ConfigMap and Secret generators
@plain
A **generator** creates a ConfigMap or Secret from files or literals and adds a hash of the content to its name. When the content changes, the name changes, and every workload that references it is updated and rolled.
@problem
Pods do not restart when a ConfigMap changes. People add manual annotations or restart by hand to pick up new config.
@does
- `configMapGenerator` and `secretGenerator` accept `files`, `literals` and `envs`.
- The generated name is suffixed such as `app-config-7g8d5k2b9f`. References in the same kustomization are rewritten.
- `behavior: merge` or `replace` lets an overlay change a generated map from the base.
- `generatorOptions.disableNameSuffixHash: true` turns hashing off if something outside needs the plain name.
@diagram flow
caption: Config change leads to a rollout
nodes:
  - "Edit config file|app.properties|plain"
  - "New hash suffix|new ConfigMap name|info"
  - "Deployment reference changes|Pod template differs|warn"
  - "Rolling update|new config live|ok"
@h Generators
```yaml title="kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - deployment.yaml
configMapGenerator:
  - name: app-config
    literals:
      - LOG_LEVEL=info
      - FEATURE_X=false
  - name: nginx-conf
    files:
      - nginx.conf
generatorOptions:
  labels:
    generated: "true"
```
:::warn
Do not put real secrets in a `secretGenerator` committed to Git. Use External Secrets, Sealed Secrets or SOPS, and let Kustomize only reference the resulting Secret name.
:::
@end

@concept Replacements and vars
@plain
`replacements` copy a value from one field of one object into fields of other objects, for example a hostname defined once and used in an Ingress and a ConfigMap.
@problem
Kustomize has no variables, but the same value (a domain, a service name) often has to appear in several places and must stay consistent.
@does
- A replacement has a `source` (object, fieldPath) and `targets` (select objects, list fieldPaths).
- It replaces the deprecated `vars` feature, which should not be used for new work.
- `options.delimiter` and `index` replace a part of a string such as one segment of a hostname.
@diagram flow
caption: One source value, several targets
nodes:
  - "ConfigMap domain|shop.example.com|env"
  - "replacements|copies the value|info"
  - "Ingress host|updated|app"
  - "Deployment env|updated|app"
@h Example
```yaml title="kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - configmap.yaml
  - ingress.yaml
  - deployment.yaml
replacements:
  - source:
      kind: ConfigMap
      name: site
      fieldPath: data.domain
    targets:
      - select:
          kind: Ingress
          name: shop
        fieldPaths:
          - spec.rules.0.host
      - select:
          kind: Deployment
          name: api
        fieldPaths:
          - spec.template.spec.containers.[name=api].env.[name=PUBLIC_HOST].value
```
@end
