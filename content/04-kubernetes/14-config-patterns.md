---
title: Pod configuration patterns
minutes: 35
objectives:
  - Use the Downward API, projected volumes and service account tokens correctly
  - Apply namespace defaults and limits with LimitRange and ResourceQuota
  - Keep configuration declarative and reloadable
---
Beyond ConfigMaps and Secrets there are several ways to hand a Pod information and to set guard rails on how much a namespace may consume.

@concept The Downward API
@plain
The Downward API lets a container read facts about its own Pod, such as its name, namespace, IP, labels and resource limits, without calling the API server.
@problem
Apps often need their identity for logging, metrics labels or clustering, and giving them API access just for that is excessive.
@does
- `fieldRef` exposes `metadata.name`, `metadata.namespace`, `status.podIP`, `spec.nodeName`, labels and annotations.
- `resourceFieldRef` exposes requests and limits, useful for sizing JVM heaps or worker counts.
- Available as env vars or as files in a `downwardAPI` volume (labels update live in files).
@diagram flow
caption: Pod facts without API calls
nodes:
  - "Pod spec|name, labels, limits|info"
  - "kubelet|injects values|app"
  - "Container|env or files|ok"
@h Example
```yaml title="downward.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: whoami
  labels:
    app: whoami
spec:
  containers:
    - name: app
      image: busybox:1.36
      command: ["sh", "-c", "env | grep -E 'POD|NODE|MEM'; sleep 3600"]
      resources:
        limits: {memory: 256Mi}
      env:
        - name: POD_NAME
          valueFrom: {fieldRef: {fieldPath: metadata.name}}
        - name: POD_IP
          valueFrom: {fieldRef: {fieldPath: status.podIP}}
        - name: NODE_NAME
          valueFrom: {fieldRef: {fieldPath: spec.nodeName}}
        - name: MEM_LIMIT
          valueFrom: {resourceFieldRef: {containerName: app, resource: limits.memory}}
```
@end

@concept Projected volumes and service account tokens
@plain
A projected volume combines several sources (ServiceAccount token, ConfigMap, Secret, Downward API) into one directory. Bound service account tokens are short lived and audience scoped.
@problem
Old ServiceAccount token Secrets never expired, so a leaked one worked forever.
@does
- Since 1.24 Pods receive an automatically rotated token (about one hour, refreshed by the kubelet) tied to the Pod, valid only while the Pod exists.
- A projected token can have a custom `audience`, for example `sts.amazonaws.com` (IRSA) or a Vault audience.
- Set `automountServiceAccountToken: false` for Pods that never call the API.
- Tokens are JWTs: inspect the claims with any JWT decoder to see audience, subject and expiry.
@diagram layers
caption: One directory, several sources
layers:
  - {label: "Projected volume", nodes: ["serviceAccountToken|audience, expiry|cp", "configMap|CA bundle|info", "downwardAPI|labels|info"]}
  - {label: "Container", nodes: ["/var/run/secrets/tokens|read only|app"]}
@h Custom audience token
```yaml title="projected-token.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: api
spec:
  serviceAccountName: api
  automountServiceAccountToken: false
  containers:
    - name: app
      image: ghcr.io/example/api:1.4.2
      volumeMounts:
        - {name: aws-token, mountPath: /var/run/secrets/aws, readOnly: true}
  volumes:
    - name: aws-token
      projected:
        sources:
          - serviceAccountToken:
              audience: sts.amazonaws.com
              expirationSeconds: 3600
              path: token
```
@check
Why prefer a projected token to a token Secret? || It expires, is rotated automatically, is bound to the Pod and is scoped to an audience.
@end

@concept ResourceQuota
@plain
A ResourceQuota caps the total resources and object counts a namespace may use.
@problem
One team can consume the whole cluster or create a million ConfigMaps if nothing limits them.
@does
- Limits sums of `requests.cpu`, `requests.memory`, `limits.*`, storage per class, and counts such as `pods`, `services.loadbalancers`, `persistentvolumeclaims`.
- When a quota covers compute, every Pod must set those values (or get them from a LimitRange) or it is rejected.
- Exceeding the quota rejects creation at admission with a clear 403 message.
- `scopes` such as `PriorityClass` apply different quotas to different priorities.
@diagram flow
caption: Quota checked at admission
nodes:
  - "Create Pod|requests 2 CPU|ext"
  - "Quota check|used 9 of 10|warn"
  - "Rejected|forbidden exceeded quota|bad"
@h Namespace quota
```yaml title="quota.yaml"
apiVersion: v1
kind: ResourceQuota
metadata:
  name: team-a
  namespace: team-a
spec:
  hard:
    requests.cpu: "20"
    requests.memory: 64Gi
    limits.memory: 96Gi
    pods: "100"
    persistentvolumeclaims: "20"
    requests.storage: 500Gi
    services.loadbalancers: "2"
```
@end

@concept LimitRange
@plain
A LimitRange sets default, minimum and maximum resources for containers in a namespace.
@problem
Developers forget requests and limits, which breaks scheduling and quotas, or request absurd amounts.
@does
- `default` is applied as limit and `defaultRequest` as request when a container omits them.
- `min` and `max` reject outliers; `maxLimitRequestRatio` caps overcommit.
- Applies to containers, Pods and PVCs.
- Defaults are a safety net, not a substitute for sizing each service from measurements.
@diagram cmp
caption: LimitRange versus ResourceQuota
cards:
  - {h: "LimitRange", kind: info, items: ["Per container or Pod", "Defaults and bounds"]}
  - {h: "ResourceQuota", kind: warn, items: ["Whole namespace", "Totals and counts"]}
@h Defaults
```yaml title="limitrange.yaml"
apiVersion: v1
kind: LimitRange
metadata:
  name: defaults
  namespace: team-a
spec:
  limits:
    - type: Container
      defaultRequest: {cpu: 100m, memory: 128Mi}
      default: {memory: 512Mi}
      max: {cpu: "4", memory: 8Gi}
```
@check
A namespace has a CPU quota but a Pod without CPU requests is rejected. Fix? || Add requests to the Pod or a LimitRange with `defaultRequest`.
@end

@concept Declarative configuration and immutable infrastructure
@plain
Treat every manifest as code in Git, applied by a controller, and avoid hand edits to live objects.
@problem
`kubectl edit` in production causes drift that nobody can review, reproduce or roll back.
@does
- GitOps tools (Argo CD, Flux) compare Git with the cluster and reconcile; drift is shown or reverted.
- `kubectl diff -f` previews changes; `kubectl apply --server-side --dry-run=server` validates.
- `kubeconform` or `kubectl --dry-run=server` in CI catches schema errors; `kube-linter` and `kyverno test` catch policy errors.
- Use `kubectl get -o yaml` only to inspect; strip `status`, `managedFields` and `resourceVersion` before re-applying.
@diagram flow
caption: Change path
numbered: true
nodes:
  - "Pull request|manifest change|info"
  - "CI checks|schema, policy, diff|warn"
  - "Merge|reviewed|ok"
  - "GitOps controller|applies to cluster|cp"
@h CI validation
```bash title="Validate manifests before merge" lab
kubeconform -strict -summary -ignore-missing-schemas manifests/
kubectl diff -f manifests/ ; test $? -le 1       # 0 no diff, 1 diff found, >1 error
kubectl apply --server-side --dry-run=server -f manifests/
```
@end
