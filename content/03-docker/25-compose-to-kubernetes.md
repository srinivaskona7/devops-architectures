---
title: Compose to Kubernetes migration
minutes: 55
objectives:
  - Map Compose concepts to Kubernetes objects
  - Use kompose, Skaffold and Tilt to move and iterate
  - Avoid the usual pitfalls with volumes, networks, secrets and health checks
---
Compose is excellent for local development. Production on Kubernetes needs more objects and more explicit decisions. This page covers the translation and the tools that help.

@concept Mapping Compose to Kubernetes
@plain
Each Compose idea has a Kubernetes counterpart, but often several objects instead of one.
@problem
A mechanical conversion produces YAML that runs but ignores health, security, scaling and storage.
@does
- `services` become Deployments (or StatefulSets) plus Services.
- `ports` become Service ports and Ingress or Gateway routes; `expose` is a ClusterIP Service.
- `environment` and `env_file` become ConfigMaps and Secrets.
- `volumes`: named volumes become PVCs; bind mounts need rethinking (ConfigMap, emptyDir, or image content).
- `depends_on` has no direct equivalent: use readiness probes, init containers and retries.
- `deploy.resources` becomes `requests` and `limits`; `restart` becomes controller behaviour.
@diagram layers
caption: One Compose service, many objects
layers:
  - {label: "Compose", nodes: ["service web|image, ports, env|app"]}
  - {label: "Kubernetes", nodes: ["Deployment|replicas, probes|cp", "Service|stable address|info", "ConfigMap and Secret|configuration|warn", "Ingress or HTTPRoute|external access|ext"]}
@h Side by side
```yaml title="compose.yaml"
services:
  web:
    image: registry.example.com/shop/web:1.4
    ports: ["8080:80"]
    environment:
      API_URL: http://api:8080
    depends_on: [api]
  api:
    image: registry.example.com/shop/api:1.8.3
    environment:
      DB_HOST: db
  db:
    image: postgres:16
    volumes: [dbdata:/var/lib/postgresql/data]
volumes:
  dbdata: {}
```
@check
What replaces depends_on in Kubernetes? || Readiness probes, init containers and client retries. Kubernetes starts Pods independently.
@end

@concept kompose
@plain
kompose converts a Compose file into Kubernetes manifests. It is a starting point, not a finished deployment.
@problem
Writing the first set of manifests by hand for a large Compose project is slow.
@does
- `kompose convert -f compose.yaml -o k8s/` writes Deployments, Services and PVCs. `--chart` produces a Helm chart; `-c` is the short form.
- Labels like `kompose.service.type: LoadBalancer` on a service control the generated Service type.
- Review what it misses: probes, securityContext, resource requests, PodDisruptionBudgets, NetworkPolicy, Ingress details, StatefulSet for databases.
- Run `kubectl apply --dry-run=server` and `kubeconform` on the output.
@diagram flow
caption: Conversion workflow
numbered: true
nodes:
  - "compose.yaml|source|plain"
  - "kompose convert|generate|info"
  - "Hand review|add probes, limits, security|warn"
  - "Apply to dev cluster|test|ok"
@h Run it
```bash title="Convert and validate" lab
kompose convert -f compose.yaml -o k8s/
ls k8s/
kubectl apply --dry-run=server -f k8s/
kubeconform -strict -summary k8s/
```
@end

@concept What kompose output needs added
@plain
Generated manifests are minimal. Production needs explicit decisions in a checklist.
@problem
Teams ship the converted YAML as is and discover missing health checks and limits during an incident.
@does
- Readiness and liveness probes (and a startup probe for slow apps).
- Resource requests and limits based on measurement.
- `securityContext`: non-root, read-only filesystem, dropped capabilities, seccomp.
- Replace Compose database containers with a managed service or an operator; do not run a bare Deployment with a PVC for production data.
- Secrets from a secret manager (External Secrets) rather than literal environment values.
- NetworkPolicy, PodDisruptionBudget, topology spread and an HPA where needed.
@diagram cmp
caption: Generated versus production-ready
cards:
  - {h: "Generated", kind: warn, items: ["Deployment and Service", "Env as literals", "No probes", "No limits"]}
  - {h: "Production-ready", kind: ok, items: ["Probes and limits", "Secrets managed", "securityContext", "Policy and PDB"]}
@h Hardened Deployment skeleton
```yaml title="Deployment after review"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 2
  selector:
    matchLabels: {app: api}
  template:
    metadata:
      labels: {app: api}
    spec:
      securityContext:
        runAsNonRoot: true
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: api
          image: registry.example.com/shop/api:1.8.3
          ports:
            - {containerPort: 8080, name: http}
          readinessProbe:
            httpGet: {path: /ready, port: http}
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            initialDelaySeconds: 15
          resources:
            requests: {cpu: 200m, memory: 256Mi}
            limits: {memory: 256Mi}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
```
@end

@concept Skaffold
@plain
Skaffold automates the inner loop: build the image, push or load it, deploy the manifests and stream logs, rebuilding on file changes.
@problem
Without automation, each code change needs build, tag, edit YAML, apply, wait and port-forward by hand.
@does
- `skaffold.yaml` lists artifacts (images and builders) and a deploy method (kubectl, Helm, Kustomize).
- `skaffold dev` watches files, rebuilds, redeploys and tails logs; `skaffold run` is a one-off deploy; `skaffold render` outputs manifests for GitOps.
- Builders: Docker, Buildpacks, Jib, Bazel, custom scripts, Cloud Build. Profiles switch dev, staging.
- File sync can copy changed files into a running container without a rebuild for interpreted languages.
- Check the current schema version with `skaffold fix`.
@diagram flow
caption: Skaffold inner loop
nodes:
  - "Edit code|save|plain"
  - "Build image|per artifact|app"
  - "Deploy|kubectl or Helm|cp"
  - "Logs and port-forward|feedback|ok"
@h Config
```yaml title="skaffold.yaml" nocheck
apiVersion: skaffold/v4beta11
kind: Config
metadata:
  name: shop
build:
  artifacts:
    - image: registry.example.com/shop/api
      docker:
        dockerfile: Dockerfile
      sync:
        manual:
          - src: "src/**/*.py"
            dest: /app
manifests:
  rawYaml:
    - k8s/*.yaml
deploy:
  kubectl: {}
portForward:
  - resourceType: service
    resourceName: api
    port: 8080
    localPort: 8080
```
@check
When is file sync useful? || For interpreted languages, where changed files can be copied into the running container instead of rebuilding the image.
@end

@concept Tilt
@plain
Tilt is another inner-loop tool with a web dashboard. It is configured with a Tiltfile written in Starlark, a Python-like language.
@problem
Microservice projects with many components need to see build and runtime status at once and update only what changed.
@does
- `docker_build`, `k8s_yaml`, `k8s_resource` define images, manifests and port-forwards.
- `live_update` syncs files and runs commands in a running container, giving second-level feedback.
- `local_resource` runs local commands (generators, tests) as part of the graph; `tilt ci` runs non-interactively.
- Compared with Skaffold: richer UI and live update, more scripting; Skaffold has a simpler declarative file and CI-friendly rendering.
- A safe default: allow only your dev context with `allow_k8s_contexts` to avoid deploying to the wrong cluster.
@diagram cmp
caption: Skaffold versus Tilt
cards:
  - {h: "Skaffold", kind: info, items: ["Declarative YAML", "Great for CI render", "Simple loop"]}
  - {h: "Tilt", kind: ok, items: ["Starlark Tiltfile", "Web dashboard", "Live update"]}
@h Tiltfile
```python title="Tiltfile" nocheck
allow_k8s_contexts('kind-dev')
docker_build('registry.example.com/shop/api', '.',
    live_update=[sync('./src', '/app/src')])
k8s_yaml('k8s/api.yaml')
k8s_resource('api', port_forwards='8080:8080')
```
@end

@concept Migration plan and pitfalls
@plain
Move one service at a time, keep Compose for local development, and run both until the Kubernetes path is proven.
@problem
A big-bang migration mixes tool problems with application problems and makes rollback hard.
@does
- Pitfalls: services assuming localhost/hostnames, bind-mounted config, root-owned volume paths, missing `terminationGracePeriod` handling (SIGTERM), ports under 1024, absolute paths, and hardcoded `depends_on` ordering.
- Use the same image in Compose and Kubernetes; only configuration differs.
- Plan data: export from the Compose database and import into the managed service or operator-managed database.
- Dev clusters: kind, k3d, minikube or Colima's Kubernetes for local; Kyma or EKS namespaces for shared dev.
- Test: smoke test script that runs against both environments.
@diagram flow
caption: Incremental migration
numbered: true
nodes:
  - "Stateless service first|api, web|app"
  - "Config and secrets|ConfigMap, External Secrets|info"
  - "Data services|managed or operator|warn"
  - "Cut over|DNS or route weight|ok"
@h Local cluster with Compose images
```bash title="Try on kind" lab
kind create cluster --name dev
kind load docker-image registry.example.com/shop/api:1.8.3 --name dev
kubectl apply -f k8s/
kubectl port-forward svc/api 8080:8080
```
@check
Why keep Compose during migration? || It remains the quickest local environment and gives a baseline to compare behaviour against.
@end
