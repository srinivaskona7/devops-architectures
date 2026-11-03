---
title: Kustomize base - workloads, probes and resources
minutes: 55
objectives:
  - Lay out a Kustomize base with one Deployment and Service per component
  - Set probes, resource requests, limits and a hardened security context
  - Render and validate the manifests before Argo CD sees them
---
The Kubernetes folder explains Deployments, Services and Kustomize itself. This file writes the Shop base: the part that is identical in every environment. The next files add policies and overlays.

@concept Deploy folder layout
@plain
`deploy/base` holds the shared manifests. `deploy/overlays/<env>` holds a small `kustomization.yaml` and patches per environment.
@problem
Copying whole manifest sets per environment makes every fix a four-place edit, and the copies drift.
@does
- Base: one file per component (`catalog.yaml` and so on), plus `namespace.yaml`, `network-policies.yaml`, `hpa.yaml`, `pdb.yaml`.
- Overlay: sets image tags with the `images` field, replica counts, resources, hostnames and secret paths.
- `kubectl kustomize deploy/overlays/prod` renders the final YAML; Argo CD does the same on its side.
@diagram layers
caption: Kustomize layout
layers:
  - {label: "base (same everywhere)", nodes: ["Deployments|five components|app", "Services|ClusterIP|app", "HPA and PDB|scaling and safety|info", "NetworkPolicy|default deny|warn"]}
  - {label: "overlays (differ)", nodes: ["dev|1 replica|info", "staging|2 replicas|warn", "prod|3 replicas|ok"]}
@h Tree
```text title="deploy tree" nocheck
deploy/
  base/
    kustomization.yaml namespace.yaml
    catalog.yaml cart.yaml orders.yaml payments.yaml web.yaml
    hpa.yaml pdb.yaml network-policies.yaml ingress.yaml external-secrets.yaml
  overlays/
    dev/      kustomization.yaml
    staging/  kustomization.yaml
    prod/     kustomization.yaml patch-resources.yaml
```
@end

@concept Namespace and kustomization root
@plain
The base kustomization lists all resources, applies common labels and sets the namespace.
@problem
Missing labels make it impossible to select Shop objects in dashboards or cost reports.
@does
- `namespace: shop` places every namespaced object there.
- `labels` with `includeSelectors: false` adds `app.kubernetes.io/part-of: shop` without changing immutable selectors.
- The Pod Security Admission label `pod-security.kubernetes.io/enforce: restricted` on the namespace rejects pods that run as root or request privileges.
@diagram flow
caption: What Kustomize adds
nodes:
  - "resources list|files in base|plain"
  - "namespace shop|every object|info"
  - "common labels|part-of shop|info"
  - "Rendered YAML|to Argo CD|ok"
@h base/namespace.yaml and kustomization.yaml
```yaml title="deploy/base/namespace.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
```
```yaml title="deploy/base/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: shop
resources:
  - namespace.yaml
  - catalog.yaml
  - cart.yaml
  - orders.yaml
  - payments.yaml
  - web.yaml
  - hpa.yaml
  - pdb.yaml
  - network-policies.yaml
  - ingress.yaml
  - external-secrets.yaml
labels:
  - pairs:
      app.kubernetes.io/part-of: shop
    includeSelectors: false
configMapGenerator:
  - name: shop-config
    literals:
      - LOG_LEVEL=INFO
      - CALL_TIMEOUT_SECONDS=3
      - CATALOG_URL=http://catalog:8000
      - PAYMENTS_URL=http://payments:8000
      - ORDERS_URL=http://orders:8000
```
@end

@concept The catalog Deployment
@plain
A Deployment with three replicas spread over zones, probes, resource requests, limits and a locked-down container.
@problem
Defaults give you a pod that runs as root, has no memory limit, is declared ready before it can answer, and sits on one node with its replicas.
@does
- `readinessProbe` uses `/readyz` (dependency check). `livenessProbe` uses `/healthz` (process only). `startupProbe` gives slow starts 30 seconds before liveness applies.
- Requests 100m CPU and 128Mi memory; limits 500m CPU and 256Mi memory. Requests drive scheduling and HPA; the memory limit protects the node.
- `topologySpreadConstraints` spreads replicas across zones with `maxSkew: 1`.
- Security context: non-root UID 10001, read-only root filesystem, no privilege escalation, all capabilities dropped, seccomp `RuntimeDefault`.
- Configuration from a ConfigMap (plain values) and a Secret (database URL) through `envFrom`.
@diagram flow
caption: Pod startup and traffic
nodes:
  - "Container starts|uvicorn|app"
  - "startupProbe|healthz, up to 30 s|info"
  - "readinessProbe|readyz|warn"
  - "Receives traffic|in Service endpoints|ok"
@h base/catalog.yaml
```yaml title="deploy/base/catalog.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog
  labels: {app: catalog}
spec:
  replicas: 3
  revisionHistoryLimit: 5
  selector:
    matchLabels: {app: catalog}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  template:
    metadata:
      labels: {app: catalog}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
    spec:
      serviceAccountName: default
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile: {type: RuntimeDefault}
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: {app: catalog}
      containers:
        - name: catalog
          image: shop/catalog
          ports:
            - {name: http, containerPort: 8000}
          envFrom:
            - configMapRef: {name: shop-config}
            - secretRef: {name: catalog-db}
          env:
            - {name: SERVICE_NAME, value: catalog}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 256Mi}
          startupProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 3
            failureThreshold: 10
          readinessProbe:
            httpGet: {path: /readyz, port: http}
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 3
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          lifecycle:
            preStop:
              exec: {command: ["sleep", "5"]}
---
apiVersion: v1
kind: Service
metadata:
  name: catalog
  labels: {app: catalog}
spec:
  selector: {app: catalog}
  ports:
    - {name: http, port: 8000, targetPort: http}
```
:::note
The image name `shop/catalog` is a placeholder. Overlays replace it with the ECR URL and tag through the `images` field, so the base never contains an account ID.
:::
@end

@concept Why those probe choices matter
@plain
Readiness decides whether a pod receives traffic. Liveness decides whether it is restarted. They must check different things.
@problem
If liveness checks the database, a database outage restarts every pod at once, making recovery slower. If readiness checks nothing, pods receive traffic they cannot serve.
@does
- Readiness (`/readyz`) fails when the database or Redis is unreachable: pods leave the Service but keep running, then return by themselves.
- Liveness (`/healthz`) only proves the process answers; failure means restart.
- `maxUnavailable: 0` with `maxSurge: 1` keeps full capacity during a rollout.
- The `preStop` sleep of 5 seconds lets endpoint removal propagate before SIGTERM, avoiding dropped requests; uvicorn drains on SIGTERM within the 30 second grace.
@diagram cmp
caption: Two probes, two jobs
cards:
  - {h: "Readiness /readyz", kind: ok, items: ["Checks Postgres or Redis", "Failure removes from Service", "No restart", "Pod returns when healthy"]}
  - {h: "Liveness /healthz", kind: warn, items: ["Process only", "Failure restarts container", "Never checks dependencies", "Catches deadlocks"]}
@check
What happens to a pod when the database is down? || Readiness fails, so it stops receiving traffic; liveness still passes, so it is not restarted.
@end

@concept Remaining components from the same pattern
@plain
Cart, orders and payments differ from catalog only in name, environment and secret. The web tier and mock gateway are smaller.
@problem
Repeating 90 lines four times invites typo bugs.
@does
- Cart uses a Redis URL Secret instead of a database Secret.
- Payments adds the webhook secret and the gateway URL (from the overlay).
- Web runs on port 8080 with a small tmp `emptyDir` because the root filesystem is read-only; nginx unprivileged needs writable `/tmp`.
- To avoid repetition in a larger fleet, generate these with a Helm chart or Kustomize components; here explicit YAML keeps the teaching clear.
@diagram flow
caption: Differences from the catalog pattern
nodes:
  - "catalog|database secret|app"
  - "cart|Redis secret|app"
  - "orders|database secret and peer URLs|app"
  - "payments|database, gateway, webhook secret|warn"
@h base/cart.yaml
The cart reads its Redis URL from a Secret named `cart-redis` instead of a database Secret. Everything else is the catalog pattern.
```yaml title="deploy/base/cart.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cart
  labels: {app: cart}
spec:
  replicas: 3
  revisionHistoryLimit: 5
  selector:
    matchLabels: {app: cart}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  template:
    metadata:
      labels: {app: cart}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
    spec:
      serviceAccountName: default
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile: {type: RuntimeDefault}
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: {app: cart}
      containers:
        - name: cart
          image: shop/cart
          ports:
            - {name: http, containerPort: 8000}
          envFrom:
            - configMapRef: {name: shop-config}
            - secretRef: {name: cart-redis}
          env:
            - {name: SERVICE_NAME, value: cart}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 256Mi}
          startupProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 3
            failureThreshold: 10
          readinessProbe:
            httpGet: {path: /readyz, port: http}
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 3
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          lifecycle:
            preStop:
              exec: {command: ["sleep", "5"]}
---
apiVersion: v1
kind: Service
metadata:
  name: cart
  labels: {app: cart}
spec:
  selector: {app: cart}
  ports:
    - {name: http, port: 8000, targetPort: http}
```
@h base/orders.yaml
Orders adds the peer service URLs and uses the `orders-db` Secret.
```yaml title="deploy/base/orders.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
  labels: {app: orders}
spec:
  replicas: 3
  revisionHistoryLimit: 5
  selector:
    matchLabels: {app: orders}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  template:
    metadata:
      labels: {app: orders}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
    spec:
      serviceAccountName: default
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile: {type: RuntimeDefault}
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: {app: orders}
      containers:
        - name: orders
          image: shop/orders
          ports:
            - {name: http, containerPort: 8000}
          envFrom:
            - configMapRef: {name: shop-config}
            - secretRef: {name: orders-db}
          env:
            - {name: SERVICE_NAME, value: orders}
            - {name: CATALOG_URL, value: http://catalog:8000}
            - {name: PAYMENTS_URL, value: http://payments:8000}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 256Mi}
          startupProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 3
            failureThreshold: 10
          readinessProbe:
            httpGet: {path: /readyz, port: http}
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 3
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          lifecycle:
            preStop:
              exec: {command: ["sleep", "5"]}
---
apiVersion: v1
kind: Service
metadata:
  name: orders
  labels: {app: orders}
spec:
  selector: {app: orders}
  ports:
    - {name: http, port: 8000, targetPort: http}
```
@h base/payments.yaml
Payments reads `DATABASE_URL` and `WEBHOOK_SECRET` from the `payments-db` Secret. `GATEWAY_URL` comes from the shop ConfigMap, and the overlay decides whether it points at the mock or the real provider.
```yaml title="deploy/base/payments.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payments
  labels: {app: payments}
spec:
  replicas: 3
  revisionHistoryLimit: 5
  selector:
    matchLabels: {app: payments}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  template:
    metadata:
      labels: {app: payments}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "8000"
    spec:
      serviceAccountName: default
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile: {type: RuntimeDefault}
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels: {app: payments}
      containers:
        - name: payments
          image: shop/payments
          ports:
            - {name: http, containerPort: 8000}
          envFrom:
            - configMapRef: {name: shop-config}
            - secretRef: {name: payments-db}
          env:
            - {name: SERVICE_NAME, value: payments}
            - {name: ORDERS_URL, value: http://orders:8000}
          resources:
            requests: {cpu: 100m, memory: 128Mi}
            limits: {cpu: 500m, memory: 256Mi}
          startupProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 3
            failureThreshold: 10
          readinessProbe:
            httpGet: {path: /readyz, port: http}
            periodSeconds: 5
            timeoutSeconds: 2
            failureThreshold: 3
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 10
            timeoutSeconds: 2
            failureThreshold: 3
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          lifecycle:
            preStop:
              exec: {command: ["sleep", "5"]}
---
apiVersion: v1
kind: Service
metadata:
  name: payments
  labels: {app: payments}
spec:
  selector: {app: payments}
  ports:
    - {name: http, port: 8000, targetPort: http}
```
@h base/web.yaml
```yaml title="deploy/base/web.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  labels: {app: web}
spec:
  replicas: 3
  selector:
    matchLabels: {app: web}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}
  template:
    metadata:
      labels: {app: web}
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: web
          image: shop/web
          ports:
            - {name: http, containerPort: 8080}
          resources:
            requests: {cpu: 50m, memory: 32Mi}
            limits: {cpu: 200m, memory: 64Mi}
          readinessProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 5
          livenessProbe:
            httpGet: {path: /healthz, port: http}
            periodSeconds: 10
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
          volumeMounts:
            - {name: tmp, mountPath: /tmp}
      volumes:
        - {name: tmp, emptyDir: {}}
---
apiVersion: v1
kind: Service
metadata:
  name: web
  labels: {app: web}
spec:
  selector: {app: web}
  ports:
    - {name: http, port: 80, targetPort: http}
```
@end

@concept ConfigMap for non-secret settings
@plain
Plain settings that are the same across the namespace live in one ConfigMap generated by Kustomize.
@problem
Editing a ConfigMap in place does not restart pods, so a changed setting silently does not apply.
@does
- `configMapGenerator` appends a hash to the name, so any change creates a new ConfigMap and the Deployment rolls automatically.
- Holds `LOG_LEVEL`, `CALL_TIMEOUT_SECONDS`, peer service URLs.
- Secrets never go here; they come from External Secrets (next file).
@diagram flow
caption: Config change rolls pods
nodes:
  - "Edit literal|LOG_LEVEL=DEBUG|plain"
  - "New hash name|shop-config-8f2k|info"
  - "Deployment spec changes|template references new name|warn"
  - "Rolling update|safe|ok"
@h Generator in the base kustomization
```yaml title="the generator block (already in deploy/base/kustomization.yaml above)" nocheck
configMapGenerator:
  - name: shop-config
    literals:
      - LOG_LEVEL=INFO
      - CALL_TIMEOUT_SECONDS=3
      - CATALOG_URL=http://catalog:8000
      - PAYMENTS_URL=http://payments:8000
      - ORDERS_URL=http://orders:8000
```
@end

@concept Render, validate and diff before merging
@plain
Run the renderer and a schema validator in CI so broken YAML never reaches the cluster.
@problem
Argo CD would report the error only after merge, when the change is already on `main`.
@does
- `kubectl kustomize deploy/overlays/<env>` must succeed for all three overlays.
- `kubeconform -strict -summary` checks resources against the Kubernetes schemas (add `-ignore-missing-schemas` for CRDs such as ExternalSecret, or load the CRD schemas).
- `kubectl diff` or `argocd app diff` shows what will change in a live cluster.
- `kube-linter` or `kyverno` CLI can enforce rules such as "must have limits".
@diagram flow
caption: Static checks on manifests
nodes:
  - "kustomize build|renders|app"
  - "kubeconform|schema check|info"
  - "kube-linter|policy check|warn"
  - "Merge allowed|ok"
@h Commands
```bash title="Validate all overlays" lab
set -e
for env in dev staging prod; do
  kubectl kustomize deploy/overlays/$env > /tmp/shop-$env.yaml
  kubeconform -strict -ignore-missing-schemas -summary /tmp/shop-$env.yaml
done
```
@end
