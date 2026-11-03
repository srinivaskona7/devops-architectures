---
title: Kustomize overlays for dev, staging and prod
minutes: 50
objectives:
  - Write overlays that change only images, replicas, resources and hostnames
  - Patch the HPA, PDB and secret paths per environment
  - Render and compare the overlays to prove that only allowed fields differ
---
The base is shared. Each overlay is a short file that points at the base and applies patches. Overlays are what Argo CD syncs for a given cluster.

@concept The dev overlay
@plain
Dev runs one replica of everything, small resources, the mock gateway, debug logging and automatic updates from `main`.
@problem
Running dev at prod size wastes money, and prod-only settings (multi-AZ spread, big limits) make local debugging harder.
@does
- `images` rewrites `shop/catalog` to the ECR URL and the commit tag. CI updates only this block (see the pipeline file).
- Patches reduce replicas to 1 and the HPA to 1 to 2, and make the PDB allow zero unavailable.
- `configMapGenerator` with `behavior: merge` sets `LOG_LEVEL=DEBUG`.
- The placeholder `ENV` in every ExternalSecret key becomes `dev` through one `replacements` block that reads `ENVIRONMENT` from the generated ConfigMap.
@diagram flow
caption: Dev overlay on top of base
nodes:
  - "base|shared manifests|plain"
  - "images block|ECR URL and sha tag|app"
  - "patches|replicas 1, PDB relaxed|info"
  - "Rendered dev|for Argo CD|ok"
@h deploy/overlays/dev/kustomization.yaml
```yaml title="deploy/overlays/dev/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
components:
  - ../../components/upi-mock
images:
  - name: shop/catalog
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/catalog
    newTag: sha-0000000
  - name: shop/cart
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/cart
    newTag: sha-0000000
  - name: shop/orders
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/orders
    newTag: sha-0000000
  - name: shop/payments
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/payments
    newTag: sha-0000000
  - name: shop/web
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/web
    newTag: sha-0000000
configMapGenerator:
  - name: shop-config
    behavior: merge
    literals:
      - LOG_LEVEL=DEBUG
      - ENVIRONMENT=dev
patches:
  - target: {kind: Deployment}
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 1
  - target: {kind: HorizontalPodAutoscaler}
    patch: |-
      - op: replace
        path: /spec/minReplicas
        value: 1
      - op: replace
        path: /spec/maxReplicas
        value: 2
  - target: {kind: PodDisruptionBudget}
    patch: |-
      - op: remove
        path: /spec/minAvailable
      - op: add
        path: /spec/maxUnavailable
        value: 1
replacements:
  - source:
      kind: ConfigMap
      name: shop-config
      fieldPath: data.ENVIRONMENT
    targets:
      - select:
          kind: ExternalSecret
        fieldPaths:
          - spec.data.*.remoteRef.key
        options:
          delimiter: /
          index: 1
```
:::note
The `replacements` block copies `ENVIRONMENT` from the generated ConfigMap into the middle segment of every Secrets Manager key, so `shop/ENV/orders-db` becomes `shop/dev/orders-db` for all four ExternalSecrets at once. An index patch such as `/spec/data/0/...` would hit only the first entry of each secret and point every secret at the same key. Render the overlay and read the output.
:::
@end

@concept The mock gateway in dev and staging only
@plain
The `upi-mock` Deployment exists only in the non-production overlays. Prod has no such resource, so it cannot be called by accident.
@problem
A test gateway that approves every payment must never exist in production, even disabled.
@does
- The mock lives in a Kustomize component, `deploy/components/upi-mock`, which only the dev and staging overlays include. A component is used because an overlay may not point at a file inside another overlay's folder, which Kustomize rejects.
- The mock signs webhooks with the same `WEBHOOK_SECRET` that payments reads from the `payments-db` Secret.
- Payments in prod gets `GATEWAY_URL` pointing to the real provider through the prod overlay config.
- A CI rule greps the rendered prod overlay and fails if `upi-mock` appears.
- The webhook secret differs per environment and comes from Secrets Manager.
@diagram cmp
caption: Where the mock exists
cards:
  - {h: "dev and staging", kind: info, items: ["upi-mock Deployment and Service", "GATEWAY_URL is http://upi-mock:8000", "Test secret"]}
  - {h: "prod", kind: ok, items: ["No mock resource", "GATEWAY_URL is the provider HTTPS URL", "Real webhook secret in Secrets Manager", "CI check fails on the word upi-mock"]}
@h deploy/components/upi-mock/
```yaml title="deploy/components/upi-mock/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1alpha1
kind: Component
resources:
  - upi-mock.yaml
```
```yaml title="deploy/components/upi-mock/upi-mock.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: upi-mock
  labels: {app: upi-mock}
spec:
  replicas: 1
  selector:
    matchLabels: {app: upi-mock}
  template:
    metadata:
      labels: {app: upi-mock}
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        seccompProfile: {type: RuntimeDefault}
      containers:
        - name: upi-mock
          image: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/upi-mock:sha-0000000
          ports:
            - {name: http, containerPort: 8000}
          env:
            - name: WEBHOOK_SECRET
              valueFrom:
                secretKeyRef: {name: payments-db, key: WEBHOOK_SECRET}
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {cpu: 200m, memory: 128Mi}
          readinessProbe:
            httpGet: {path: /healthz, port: http}
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities: {drop: ["ALL"]}
---
apiVersion: v1
kind: Service
metadata:
  name: upi-mock
spec:
  selector: {app: upi-mock}
  ports:
    - {name: http, port: 8000, targetPort: http}
```
@end

@concept The staging overlay
@plain
Staging has the same shape as prod at a smaller size and uses the mock gateway, so load tests and upgrade rehearsals are safe.
@problem
A staging that differs wildly from prod gives false confidence about rollouts and capacity.
@does
- 2 replicas, HPA 2 to 4, same probes, same limits as prod.
- Same Ingress class and NetworkPolicies, different hostname `shop-staging.example.com`.
- Image tags are promoted from the dev tag when a release candidate tag is pushed.
- Staging receives the load test and the Kubernetes version upgrade first (rehearsal).
@diagram flow
caption: Staging as the proving ground
nodes:
  - "Release candidate|tag v1.4.0-rc1|plain"
  - "Staging sync|Argo CD|cp"
  - "Smoke and k6|automatic|warn"
  - "Promote to prod|approval|ok"
@h deploy/overlays/staging/kustomization.yaml
```yaml title="deploy/overlays/staging/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
components:
  - ../../components/upi-mock
images:
  - name: shop/catalog
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/catalog
    newTag: sha-0000000
  - name: shop/cart
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/cart
    newTag: sha-0000000
  - name: shop/orders
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/orders
    newTag: sha-0000000
  - name: shop/payments
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/payments
    newTag: sha-0000000
  - name: shop/web
    newName: 111111111111.dkr.ecr.ap-south-1.amazonaws.com/shop/web
    newTag: sha-0000000
configMapGenerator:
  - name: shop-config
    behavior: merge
    literals:
      - ENVIRONMENT=staging
patches:
  - target: {kind: Deployment}
    patch: |-
      - op: replace
        path: /spec/replicas
        value: 2
  - target: {kind: HorizontalPodAutoscaler}
    patch: |-
      - op: replace
        path: /spec/minReplicas
        value: 2
      - op: replace
        path: /spec/maxReplicas
        value: 4
  - target: {kind: PodDisruptionBudget}
    patch: |-
      - op: replace
        path: /spec/minAvailable
        value: 1
  - target: {kind: Ingress, name: shop}
    patch: |-
      - op: replace
        path: /spec/rules/0/host
        value: shop-staging.example.com
replacements:
  - source:
      kind: ConfigMap
      name: shop-config
      fieldPath: data.ENVIRONMENT
    targets:
      - select:
          kind: ExternalSecret
        fieldPaths:
          - spec.data.*.remoteRef.key
        options:
          delimiter: /
          index: 1
```
@end

@concept The prod overlay
@plain
Prod has 3 replicas minimum, bigger limits for orders and payments, the real certificate and hostname, and no mock.
@problem
Prod-specific values scattered across ad hoc `kubectl` edits are not reviewable or repeatable.
@does
- HPA 3 to 9 comes from the base, so only the images, hostname and certificate differ in the kustomization.
- A separate resource patch raises orders and payments to requests 200m CPU and 256Mi, limits 1 CPU and 512Mi.
- CODEOWNERS requires `@shop/platform` and `@shop/sre` approval for this folder.
- Argo CD syncs prod manually (a person clicks sync or merges a promotion pull request, depending on policy).
@diagram flow
caption: Prod changes need owners
nodes:
  - "Promotion PR|new image tags|plain"
  - "CODEOWNERS|platform and SRE|warn"
  - "Merge|main|info"
  - "Argo CD sync|manual|ok"
@h deploy/overlays/prod/kustomization.yaml
```yaml title="deploy/overlays/prod/kustomization.yaml"
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
images:
  - name: shop/catalog
    newName: 222222222222.dkr.ecr.ap-south-1.amazonaws.com/shop/catalog
    newTag: sha-0000000
  - name: shop/cart
    newName: 222222222222.dkr.ecr.ap-south-1.amazonaws.com/shop/cart
    newTag: sha-0000000
  - name: shop/orders
    newName: 222222222222.dkr.ecr.ap-south-1.amazonaws.com/shop/orders
    newTag: sha-0000000
  - name: shop/payments
    newName: 222222222222.dkr.ecr.ap-south-1.amazonaws.com/shop/payments
    newTag: sha-0000000
  - name: shop/web
    newName: 222222222222.dkr.ecr.ap-south-1.amazonaws.com/shop/web
    newTag: sha-0000000
configMapGenerator:
  - name: shop-config
    behavior: merge
    literals:
      - GATEWAY_URL=https://upi.provider.example/v1
      - ENVIRONMENT=prod
patches:
  - path: patch-resources.yaml
  - target: {kind: Ingress, name: shop}
    patch: |-
      - op: replace
        path: /spec/rules/0/host
        value: shop.example.com
replacements:
  - source:
      kind: ConfigMap
      name: shop-config
      fieldPath: data.ENVIRONMENT
    targets:
      - select:
          kind: ExternalSecret
        fieldPaths:
          - spec.data.*.remoteRef.key
        options:
          delimiter: /
          index: 1
```
```yaml title="deploy/overlays/prod/patch-resources.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: orders
spec:
  template:
    spec:
      containers:
        - name: orders
          resources:
            requests: {cpu: 200m, memory: 256Mi}
            limits: {cpu: "1", memory: 512Mi}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payments
spec:
  template:
    spec:
      containers:
        - name: payments
          resources:
            requests: {cpu: 200m, memory: 256Mi}
            limits: {cpu: "1", memory: 512Mi}
```
@end

@concept Capacity arithmetic for the prod nodes
@plain
Check that the requests of all pods fit on three nodes with room for a node loss and for the platform pods.
@problem
Requests that add up to more than the nodes can offer leave pods Pending; requests that are far too small waste nothing but hide risk.
@does
- An `m6i.large` has 2 vCPU and 8 GiB; allocatable for pods is lower (system reservations, around 1.9 vCPU and about 7 GiB; check `kubectl describe node`).
- Assume each service has an HPA with the same bounds (the base file shows two; the rest follow the same pattern). Prod requests per replica set: catalog 3 x 100m, cart 3 x 100m, orders 3 x 200m, payments 3 x 200m, web 3 x 50m = 3 x 650m = 1,950m CPU in total at minimum replicas. If every service scaled to its HPA maximum of 9: 9 x 650m = 5,850m.
- Three nodes provide about 3 x 1,900m = 5,700m allocatable, and platform pods (CoreDNS, Argo CD, Prometheus, External Secrets) take roughly 1,500m. At the HPA maximum the total is 5,850m + 1,500m = 7,350m, which needs ceil(7,350 / 1,900) = 4 nodes, so the autoscaler must add one (node group max is 6).
- Losing one node (N+1): 1,950m + 1,500m = 3,450m of requests on 2 nodes (3,800m) still fits, which is why the minimum node count is 3.
@diagram flow
caption: Does it fit
nodes:
  - "Min replicas|1,950m requests|plain"
  - "Platform pods|about 1,500m|info"
  - "Total 3,450m|of 5,700m on 3 nodes|ok"
  - "One node lost|3,450m of 3,800m|warn"
@h Verify the numbers
```python title="capacity_check.py" lab
requests_m = {"catalog": 100, "cart": 100, "orders": 200, "payments": 200, "web": 50}
min_pods, max_pods = 3, 9
platform_m = 1500
node_alloc_m = 1900

minimum = sum(requests_m.values()) * min_pods
maximum = sum(requests_m.values()) * max_pods
print("minimum requests (m):", minimum)
print("maximum requests (m):", maximum)
print("3 nodes allocatable (m):", 3 * node_alloc_m)
print("minimum + platform (m):", minimum + platform_m)
print("fits after losing 1 node:", minimum + platform_m <= 2 * node_alloc_m)
print("nodes needed at HPA max:", -(-(maximum + platform_m) // node_alloc_m))
```
@end

@concept Prove that overlays differ only where allowed
@plain
Render all three overlays and compare them with a script that lists the fields that differ.
@problem
Silent drift, such as a probe removed only in prod, is the cause of many "works in staging" incidents.
@does
- The script loads each rendered YAML, strips allowed fields (replicas, image, resources, host, labels) and compares what remains.
- Any difference outside the allowed list fails the build.
- Run it on every pull request that touches `deploy/`.
@diagram flow
caption: Drift test
nodes:
  - "Render dev|kustomize|app"
  - "Render staging|kustomize|app"
  - "Render prod|kustomize|app"
  - "Compare minus allowed|script|warn"
@h drift_check.py
```python title="scripts/drift_check.py"
import subprocess
import sys

import yaml

ALLOWED = {"replicas", "image", "resources", "host", "minReplicas", "maxReplicas",
           "minAvailable", "maxUnavailable", "value", "key", "name"}


def render(env: str) -> dict:
    out = subprocess.run(["kubectl", "kustomize", f"deploy/overlays/{env}"],
                         check=True, capture_output=True, text=True).stdout
    return {(d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(out) if d}


def strip(node):
    if isinstance(node, dict):
        return {k: strip(v) for k, v in node.items() if k not in ALLOWED}
    if isinstance(node, list):
        return [strip(v) for v in node]
    return node


def main() -> int:
    envs = {e: render(e) for e in ("staging", "prod")}
    bad = []
    for key, prod_doc in envs["prod"].items():
        stage_doc = envs["staging"].get(key)
        if stage_doc is None:
            bad.append(f"{key} exists only in prod")
        elif strip(prod_doc) != strip(stage_doc):
            bad.append(f"{key} differs outside allowed fields")
    if any(k[1] == "upi-mock" for k in envs["prod"]):
        bad.append("upi-mock must not exist in prod")
    for line in bad:
        print("DRIFT:", line)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
```
:::note
The metadata hash of the ConfigMap name differs between environments; the allowed set includes `name` for that reason. Tighten the script in your own repository.
:::
@end
