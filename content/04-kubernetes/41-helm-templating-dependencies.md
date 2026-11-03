---
title: Helm templating in depth and dependencies
minutes: 45
objectives:
  - Use conditionals, loops, named templates and validation helpers in templates
  - Compose charts with dependencies, subcharts and library charts
  - Validate input with a values schema and test a release
---
Basic substitution gets you far, but real charts need optional objects, repeated blocks and shared helpers. This section covers the template features you meet in production charts.

@concept Conditionals, with and range
@plain
Templates can include a block only when a condition holds (`if`), loop over a list or map (`range`), and change the current scope (`with`).
@problem
Not every install wants an Ingress, a HorizontalPodAutoscaler or a ServiceMonitor. One chart has to switch parts on and off and render a variable number of items.
@does
- `{{- if .Values.ingress.enabled }} ... {{- end }}` wraps a whole object so it is skipped when disabled.
- `range` repeats a block for every item. Inside it `.` is the current item, so use `$` to reach the root context.
- `with` runs the block only if the value is non-empty and rebinds `.` to it.
- Empty string, `0`, `false`, empty list and empty map are all false.
@diagram flow
caption: A template deciding what to emit
nodes:
  - "Values|ingress.enabled and hosts|env"
  - "if|skip the file when false|warn"
  - "range hosts|one rule per host|info"
  - "Manifest|only needed objects|ok"
@h Optional Ingress with a loop
```yaml nocheck title="templates/ingress.yaml"
{{- if .Values.ingress.enabled }}
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: {{ .Release.Name }}
spec:
  ingressClassName: {{ .Values.ingress.className }}
  rules:
    {{- range .Values.ingress.hosts }}
    - host: {{ .name | quote }}
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: {{ $.Release.Name }}
                port:
                  number: {{ $.Values.service.port }}
    {{- end }}
{{- end }}
```
@end

@concept Named templates and _helpers.tpl
@plain
A named template is a reusable snippet defined with `define` and called with `include`. The convention is to keep them in `templates/_helpers.tpl`.
@problem
Names, labels and selectors must be identical across a Deployment, a Service and a PodDisruptionBudget. Copying them invites a typo that breaks a selector.
@does
- `{{ define "shop.labels" }} ... {{ end }}` declares it; `{{ include "shop.labels" . | nindent 4 }}` uses it and lets you pipe the result.
- Prefix names with the chart name, because template names are global across a chart and its subcharts.
- Prefer `include` over `template`, since only `include` returns a string that can be piped.
- `helm create` generates `fullname`, `labels` and `selectorLabels` helpers you can keep.
@diagram flow
caption: One definition, many uses
nodes:
  - "_helpers.tpl|define shop.labels|info"
  - "deployment.yaml|include|app"
  - "service.yaml|include|app"
  - "pdb.yaml|include|app"
@h Helpers
```yaml nocheck title="templates/_helpers.tpl"
{{- define "shop.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end }}

{{- define "shop.selectorLabels" -}}
app.kubernetes.io/name: {{ include "shop.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "shop.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version }}
{{ include "shop.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}
```
:::note
The 63 character truncation matters. Many Kubernetes names and all label values are limited to 63 characters, so long release names fail at install time without it.
:::
@end

@concept Validation with required, fail and schema
@plain
You can make a chart refuse bad input early: `required` stops rendering when a value is missing, `fail` stops with your message, and `values.schema.json` validates the whole values tree.
@problem
Without validation, a missing hostname renders an empty string, the install succeeds, and the failure appears later as a confusing runtime error.
@does
- `{{ required "image.repository is required" .Values.image.repository }}` aborts with that message.
- `values.schema.json` is JSON Schema. Helm checks it on `install`, `upgrade`, `lint` and `template`.
- `additionalProperties: false` catches misspelled keys, which otherwise are silently ignored.
@diagram flow
caption: Failing before anything reaches the cluster
nodes:
  - "helm upgrade|with your values|app"
  - "Schema check|types, enums, required|warn"
  - "Render|required and fail|info"
  - "Apply|only valid input gets here|ok"
@h A small schema
```json title="values.schema.json"
{
  "$schema": "https://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["image"],
  "properties": {
    "replicaCount": {"type": "integer", "minimum": 1},
    "image": {
      "type": "object",
      "required": ["repository"],
      "properties": {
        "repository": {"type": "string", "minLength": 1},
        "tag": {"type": "string"}
      }
    }
  }
}
```
@end

@concept Dependencies and subcharts
@plain
A chart can depend on other charts, such as PostgreSQL or Redis. They are declared in `Chart.yaml`, downloaded into `charts/`, and configured through a section of your values named after the dependency.
@problem
An application usually needs supporting services. Re-implementing them in your own chart is wasteful, and installing them separately breaks the "one command" promise.
@does
- `helm dependency update` resolves versions, writes `Chart.lock` and downloads archives; `helm dependency build` restores exactly what the lock says.
- `condition: postgresql.enabled` lets users turn a dependency off, for example when they use a managed database.
- Values under the key `postgresql:` go to the subchart; values under `global:` reach every chart.
- `alias` lets you include the same chart twice under different names.
@diagram layers
caption: A parent chart with two subcharts
layers:
  - {label: "Parent", nodes: ["shop|your application chart|app"]}
  - {label: "Dependencies", nodes: ["postgresql|condition postgresql.enabled|db", "redis|condition redis.enabled|db"]}
  - {label: "Shared", nodes: ["global values|visible to all|info"]}
@h Declaring a dependency
```yaml title="Chart.yaml"
apiVersion: v2
name: shop
version: 1.2.0
appVersion: "2.0.0"
dependencies:
  - name: postgresql
    version: "15.x.x"
    repository: oci://registry-1.docker.io/bitnamicharts
    condition: postgresql.enabled
  - name: redis
    version: "19.x.x"
    repository: oci://registry-1.docker.io/bitnamicharts
    condition: redis.enabled
```
```bash title="Resolve and build" lab
helm dependency update ./shop     # writes Chart.lock and fills charts/
helm dependency build ./shop      # reproducible, uses Chart.lock
helm template shop ./shop --set postgresql.enabled=false | grep -c '^kind:'
```
@end

@concept Library charts and chart tests
@plain
A **library chart** (`type: library`) contains only named templates and renders nothing by itself. Other charts depend on it to share conventions. **Chart tests** are Pods marked as tests that `helm test` runs against an installed release.
@problem
Fifty microservices each carrying a copy of the same Deployment template drift apart. And a successful install says only that objects were created, not that the service works.
@does
- A library chart exposes helpers such as `mylib.deployment`; consumers call them with `include`.
- A test is a template in `templates/tests/` with the annotation `helm.sh/hook: test`. It passes when the Pod exits 0.
- `helm test RELEASE` runs them and reports; keep them small, such as one HTTP call to the Service.
@diagram flow
caption: Shared templates and a post install check
nodes:
  - "Library chart|common templates|info"
  - "Service charts|50 apps use it|app"
  - "helm install|release created|cp"
  - "helm test|Pod calls the Service|ok"
@h A smoke test
```yaml title="templates/tests/test-connection.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: shop-test-connection
  annotations:
    "helm.sh/hook": test
    "helm.sh/hook-delete-policy": hook-succeeded
spec:
  restartPolicy: Never
  containers:
    - name: wget
      image: busybox:1.36
      command: ["wget", "-qO-", "http://shop:80/healthz"]
```
```bash title="Run it" lab
helm test shop -n shop --logs
```
@end

@concept Debugging a template
@plain
When rendering fails or produces odd YAML, you inspect the rendered output instead of guessing. `helm template` and `--debug` show what Helm would send.
@problem
Template errors mention line numbers in generated text, and indentation mistakes produce valid-looking YAML that means something different.
@does
- `helm template NAME CHART -f values.yaml` renders locally without a cluster. `--show-only templates/ingress.yaml` renders one file.
- `helm install --dry-run=server --debug` renders and validates against the API server, including admission webhooks.
- `helm lint --strict` catches common mistakes. `toYaml` plus `nindent` mismatches are the most frequent cause of errors.
- `--validate` on `helm template` checks the output against cluster API versions.
@diagram flow
caption: Debug loop for a template
nodes:
  - "Edit template|change one thing|plain"
  - "helm lint|static checks|info"
  - "helm template|read the output|app"
  - "dry-run=server|API validation|cp"
  - "Install|confident|ok"
@h Commands
```bash title="Render and validate" lab
helm lint ./shop --strict -f values-prod.yaml
helm template shop ./shop -f values-prod.yaml --show-only templates/ingress.yaml
helm template shop ./shop -f values-prod.yaml | kubectl apply --dry-run=server -f -
helm install shop ./shop -n shop --dry-run=server --debug 2>&1 | tail -30
```
@check
Why use include instead of template for a labels helper? || include returns a string, so you can pipe it to nindent; template writes directly and cannot be piped.
Where do subchart values go in the parent values file? || Under a key with the subchart name, for example postgresql, or under global to reach all charts.
@end
