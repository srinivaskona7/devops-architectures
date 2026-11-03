---
title: Helm fundamentals
minutes: 45
objectives:
  - Explain charts, releases and repositories and how Helm stores release state
  - Lay out a chart and read the values precedence rules
  - Install, upgrade, roll back and inspect a release from the command line
---
Raw manifests repeat themselves across environments. **Helm** is the package manager for Kubernetes. It bundles manifests as a templated **chart**, fills them with **values**, and tracks every install as a **release** you can upgrade and roll back.

@concept Charts, releases and repositories
@plain
A **chart** is a folder of templated Kubernetes YAML plus default settings. A **release** is one installed copy of a chart in a cluster, with a name you choose. A **repository** is a place that serves charts, either a classic HTTP index or an OCI registry.
@problem
Installing a database, an ingress controller or your own service by hand means dozens of YAML files that differ slightly per environment. Copying and editing them leads to drift, and there is no single command to undo a bad change.
@does
- The same chart can be installed many times under different release names and namespaces.
- Helm 3 and later has no server component. The `helm` client talks to the API server using your kubeconfig, so it has exactly your RBAC permissions.
- Each upgrade creates a new numbered **revision**, which is what makes rollback possible.
@diagram flow
caption: From chart to running objects
numbered: true
nodes:
  - "Chart|templates and defaults|info"
  - "Values|your overrides|env"
  - "Helm client|renders YAML|app"
  - "API server|applies objects|cp"
  - "Release|revision 1, 2, 3|ok"
@h Finding and using a chart
```bash title="Repositories and search" lab
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update                                  # refresh the local index cache
helm search repo ingress-nginx --versions | head  # available chart versions
helm show chart ingress-nginx/ingress-nginx | head -20
helm show values ingress-nginx/ingress-nginx > default-values.yaml   # every knob and its default
```
@check
Does Helm need a controller running in the cluster? || No. Helm 3 and later is client-only and stores release state in the cluster as Secrets.
What is the difference between a chart and a release? || A chart is the package; a release is one named installation of it with a specific values set.
@end

@concept Anatomy of a chart
@plain
A chart is a directory with a fixed layout. `Chart.yaml` describes it, `values.yaml` holds defaults, and `templates/` holds the YAML with placeholders.
@problem
Without a convention every team would organise packages differently, and tooling such as linting, packaging and dependency resolution could not work.
@does
- `Chart.yaml` has `version` (the chart version) and `appVersion` (the version of the software inside). They are independent.
- `templates/_helpers.tpl` holds reusable named templates. Files starting with an underscore render no object.
- `templates/NOTES.txt` is printed after install. `charts/` holds dependencies. `values.schema.json` can validate input.
- `crds/` holds CRDs that are installed once and never upgraded or deleted by Helm.
@diagram layers
caption: Layout of the chart directory
layers:
  - {label: "Metadata", nodes: ["Chart.yaml|name, version, dependencies|info", "values.yaml|defaults|env", "values.schema.json|input validation|warn"]}
  - {label: "templates/", nodes: ["deployment.yaml|Go templated YAML|app", "service.yaml|app|app", "_helpers.tpl|named templates|plain", "NOTES.txt|post install message|plain"]}
  - {label: "Other", nodes: ["charts/|packaged dependencies|ok", "crds/|installed once|cp"]}
@h A minimal Chart.yaml and values.yaml
```yaml title="Chart.yaml"
apiVersion: v2
name: shop-api
description: Shop API service
type: application
version: 0.3.0          # chart version, bump on every chart change
appVersion: "1.8.2"     # application image version
kubeVersion: ">=1.28.0-0"
```
```yaml title="values.yaml"
replicaCount: 2
image:
  repository: registry.example.com/shop/api
  tag: ""               # empty means use Chart.appVersion
  pullPolicy: IfNotPresent
service:
  port: 80
resources:
  requests: {cpu: 100m, memory: 128Mi}
  limits: {memory: 256Mi}
ingress:
  enabled: false
  host: shop.example.com
```
```bash title="Scaffold a new chart" lab
helm create shop-api        # generates a working example chart
helm lint shop-api --strict # warnings become errors
helm package shop-api       # produces shop-api-0.3.0.tgz
```
@end

@concept Values and their precedence
@plain
Values are the inputs to a chart. The chart ships defaults; you override them with files or command-line flags. Later sources win over earlier ones.
@problem
One chart must serve dev, staging and production with different replica counts, hostnames and sizes, without editing the chart.
@does
- Lowest to highest priority is the chart's `values.yaml`, then parent chart values, then each `-f file` in order, then `--set` flags.
- Maps merge key by key. **Lists are replaced whole**, not merged, which surprises people.
- `--set a.b=c` sets nested keys, `--set-string` forces a string, `--set-file` reads a value from a file.
- Keep one values file per environment in version control and avoid long `--set` chains.
@diagram flow
caption: Later sources override earlier ones
nodes:
  - "values.yaml|chart defaults|plain"
  - "-f base.yaml|shared settings|info"
  - "-f prod.yaml|environment|env"
  - "--set|last word|warn"
  - "Final values|used to render|ok"
@h Per environment files
```yaml title="values-prod.yaml"
replicaCount: 4
image:
  tag: "1.8.2"
ingress:
  enabled: true
  host: shop.prod.example.com
resources:
  requests: {cpu: 500m, memory: 512Mi}
  limits: {memory: 512Mi}
```
```bash title="Apply layered values" lab
helm upgrade --install shop ./shop-api -n shop --create-namespace \
  -f values.yaml -f values-prod.yaml --set image.tag=1.8.3
helm get values shop -n shop            # only what you overrode
helm get values shop -n shop --all      # computed values including defaults
```
:::warn
`--reuse-values` keeps the previous release's overrides but ignores new chart defaults, so a chart upgrade can silently miss new settings. Prefer passing the same `-f` files every time.
:::
@end

@concept Templates and built-in objects
@plain
Templates are YAML files with Go template expressions in double braces. Helm gives them objects such as `.Values`, `.Release` and `.Chart` to read.
@problem
Plain YAML cannot change a name, a replica count or an image tag from one install to the next. Templates make one file produce many correct variants.
@does
- `.Values` holds merged input. `.Release.Name`, `.Release.Namespace`, `.Release.IsInstall` and `.Release.IsUpgrade` describe the install.
- `.Chart.Name`, `.Chart.AppVersion` come from `Chart.yaml`. `.Capabilities.KubeVersion` shows the cluster version.
- `{{ .Values.x | quote }}` pipes a value through a function. `{{- ... -}}` trims surrounding whitespace.
- `nindent` and `toYaml` are the usual way to insert a block with the right indentation.
@diagram flow
caption: Rendering one template
nodes:
  - "deployment.yaml|with placeholders|plain"
  - "Values and Release|data|env"
  - "Template engine|Go text/template plus Sprig|app"
  - "Plain manifest|valid Kubernetes YAML|ok"
@h A Deployment template
```yaml nocheck title="templates/deployment.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-api
  labels:
    app.kubernetes.io/name: shop-api
    app.kubernetes.io/instance: {{ .Release.Name }}
    app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
spec:
  replicas: {{ .Values.replicaCount }}
  selector:
    matchLabels:
      app.kubernetes.io/instance: {{ .Release.Name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/instance: {{ .Release.Name }}
    spec:
      containers:
        - name: api
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag | default .Chart.AppVersion }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
          ports:
            - containerPort: 8080
          resources:
            {{- toYaml .Values.resources | nindent 12 }}
```
:::tip
Always render before you install. `helm template shop ./shop-api -f values-prod.yaml | kubectl apply --dry-run=server -f -` validates the output against the real API server.
:::
@end

@concept Install, upgrade, rollback
@plain
`helm upgrade --install` is the one idempotent command for CI: it installs if the release is missing and upgrades otherwise. Every change makes a new revision, and `helm rollback` returns to an earlier one.
@problem
A failed deployment must not leave the application half updated with no way back, and pipelines need a single repeatable command.
@does
- `--wait` blocks until Pods and Deployments are ready; `--timeout` bounds it. `--atomic` rolls back automatically if the wait fails, and implies `--wait`.
- `helm history` lists revisions with status such as `deployed`, `failed` or `superseded`.
- `helm rollback NAME REVISION` creates a new revision that reapplies an old manifest.
- `helm uninstall` removes the objects; `--keep-history` retains the release record.
@diagram seq
caption: A pipeline upgrade that fails and rolls back
actors: ["CI|pipeline|ext", "Helm|client|app", "API server|cluster|cp"]
steps:
  - "0>1: upgrade --install --atomic | req"
  - "1>2: apply revision 5 | req"
  - "2>1: new Pods not ready | bad"
  - "note 1..2: timeout reached"
  - "1>2: reapply revision 4 | req"
  - "1>0: exit code 1, rolled back | bad"
@h Commands
```bash title="Release lifecycle" lab
helm upgrade --install shop ./shop-api -n shop --create-namespace \
  -f values-prod.yaml --atomic --timeout 5m
helm list -n shop                          # releases and their status
helm history shop -n shop                  # revisions
helm rollback shop 3 -n shop --wait        # go back to revision 3
helm uninstall shop -n shop
```
@check
What does --atomic do on failure? || It rolls the release back to the previous revision and returns a non-zero exit code.
Why can a rollback of a Helm release not undo a database migration? || Helm only reapplies old manifests; it knows nothing about data changes made by the application.
@end

@concept Where release state lives and how to inspect it
@plain
Helm stores each revision as a Secret in the release namespace, named `sh.helm.release.v1.NAME.vN`. It contains the chart, the values and the rendered manifest, compressed.
@problem
When a release is stuck in `pending-upgrade` or the live cluster differs from what you think you deployed, you need to see what Helm believes.
@does
- `helm get manifest` shows what Helm applied; compare it with `kubectl get -o yaml` to find manual edits.
- `helm get hooks`, `helm get notes` and `helm status` show the rest of the record.
- A release stuck in a `pending-*` state (for example after a killed CI job) blocks further upgrades with "another operation is in progress". Roll back or delete the stuck revision Secret.
- Old revisions are pruned according to `--history-max`, which defaults to 10.
@diagram flow
caption: What Helm keeps per revision
nodes:
  - "Revision Secret|sh.helm.release.v1.shop.v4|db"
  - "Chart and values|stored inside|info"
  - "Rendered manifest|what was applied|app"
  - "Status|deployed or failed|warn"
@h Inspecting
```bash title="See what Helm knows" lab
kubectl get secret -n shop -l owner=helm        # one Secret per revision
helm status shop -n shop
helm get manifest shop -n shop | head -40
helm get manifest shop -n shop | kubectl diff -f -   # drift between Helm and the cluster
helm rollback shop 4 -n shop                    # recover a release stuck in pending-upgrade
```
:::note
Do not edit Helm-owned objects by hand. The next upgrade may overwrite the edit, or fail on a conflict. Change the values and upgrade instead.
:::
@end
