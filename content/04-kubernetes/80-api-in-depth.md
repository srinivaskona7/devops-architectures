---
title: The Kubernetes API in depth
minutes: 60
objectives:
  - Read API groups, versions and discovery documents with confidence
  - Use server-side apply and field managers to share ownership of objects
  - Explain watch, resourceVersion, API priority and fairness and aggregated APIs
---
Every kubectl command, controller and operator is a client of one REST API. Knowing how that API is organised, versioned and protected under load makes upgrades, controllers and incidents far easier to reason about.

@concept API groups, versions and resources
@plain
Resources are organised into groups such as `apps`, `batch` and `networking.k8s.io`. Each group has one or more versions such as `v1`. The old core group has no name and is written `v1`.
@problem
A single flat list of all object types could not evolve. Groups let teams ship and version their types independently, and let CRDs add their own.
@does
- A full path looks like `/apis/apps/v1/namespaces/shop/deployments`. The core group lives under `/api/v1`.
- `apiVersion` in a manifest is `group/version`, and `kind` names the type.
- A resource also has subresources such as `pods/log`, `deployments/scale` and `pods/eviction`, which RBAC treats separately.
- `kubectl api-resources` lists resources, `kubectl explain` shows schemas.
@diagram flow
caption: From a manifest to a REST path
nodes:
  - "apiVersion|apps/v1|info"
  - "kind|Deployment|info"
  - "Resource|deployments|app"
  - "REST path|/apis/apps/v1/namespaces/shop/deployments|ok"
@h Explore the API from kubectl
```bash title="Discover groups, resources and schemas" lab
kubectl api-resources --api-group=apps -o wide
kubectl api-versions | sort | head -20
kubectl explain deployment.spec.strategy --api-version=apps/v1
kubectl get --raw /apis/apps/v1 | head -c 400
```
@check
What is the group of Pods and Services? || The core group, which has no name. Its apiVersion is just v1 and its path starts with /api/v1.
@end

@concept Versions, stability levels and deprecation
@plain
A version suffix tells you how stable an API is. `v1` is stable, `v1beta1` is a beta that may change, and `v1alpha1` is experimental and off by default.
@problem
Without clear levels, clusters would break on every upgrade and teams would not know which APIs are safe to depend on.
@does
- Stable APIs follow a deprecation policy. A GA API is supported for at least 12 months or 3 releases after it is deprecated, whichever is longer. Check the current policy page for the exact numbers.
- Beta APIs are usually no longer enabled by default for new beta features since 1.24, though existing ones continue until removed.
- Removed versions return `404`. Stored objects are migrated by the API server, but your manifests and Helm charts are not.
- The metric `apiserver_requested_deprecated_apis` shows who still calls deprecated endpoints.
@diagram flow
caption: Life of an API version
nodes:
  - "alpha|off by default|warn"
  - "beta|may change|info"
  - "GA v1|stable|ok"
  - "Deprecated|warnings in responses|warn"
  - "Removed|404 in a later release|bad"
@h Find deprecated usage before upgrading
```bash title="Deprecated API usage" lab
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis | head
kubectl get events -A --field-selector reason=FailedCreate | head
kubectl convert --help | head -3   # kubectl-convert is a separate plugin
```
:::tip
Tools such as `kubent` or `pluto` scan manifests and Helm releases for removed APIs. Run one in CI before every minor upgrade. See the upgrade page in this track.
:::
@end

@concept Discovery and OpenAPI
@plain
The API server publishes what it serves. Clients read this at runtime so that kubectl can work with CRDs it has never seen.
@problem
Hard-coding resource lists into clients would break whenever a cluster adds a CRD or aggregated API.
@does
- `/api` and `/apis` list groups and versions. Aggregated discovery (stable in recent releases) returns this in one or two calls instead of dozens.
- `/openapi/v3` serves schemas per group version. `kubectl explain` and IDE validation use it.
- kubectl caches discovery in `~/.kube/cache/discovery`. A stale cache can show missing resources after a CRD install.
- `kubectl get --raw` reads any path directly, including `/healthz`, `/readyz` and `/livez`.
@diagram seq
caption: kubectl learns about a CRD
actors: ["kubectl|client|app", "API server|discovery|cp", "CRD|installed earlier|info"]
steps:
  - "0>1: GET /apis | req"
  - "1>2: includes new group | resp"
  - "1>0: group list | resp"
  - "0>1: GET custom resource | req"
@h Reading discovery
```bash title="Discovery and health endpoints" lab
kubectl get --raw /readyz?verbose | head -20
kubectl get --raw /openapi/v3 | head -c 300
rm -rf ~/.kube/cache/discovery   # force a refresh if resources look missing
```
@end

@concept Aggregated APIs and APIService
@plain
An aggregated API lets another server join the main API under a group such as `metrics.k8s.io`. The kube-apiserver proxies matching requests to it.
@problem
CRDs store plain data in etcd. Some features need custom logic, other storage or live data, such as metrics that are never stored in etcd.
@does
- You register an `APIService` object that names a group, a version and the Service that hosts the extension server.
- The metrics-server uses this for `kubectl top`. If it is down, `kubectl get apiservices` shows `False (MissingEndpoints)` and namespace deletion can hang, since discovery fails.
- Authentication is delegated: the aggregator authenticates the user and forwards identity in headers.
- Prefer CRDs unless you need custom storage, subresource logic or non-etcd data.
@diagram flow
caption: Request routing with an aggregated API
nodes:
  - "kubectl top|client|plain"
  - "kube-apiserver|aggregator|cp"
  - "APIService|v1beta1.metrics.k8s.io|info"
  - "metrics-server|Service in kube-system|app"
@h Check APIService health
```bash title="APIService status" lab
kubectl get apiservices | grep -v 'Local'
kubectl describe apiservice v1beta1.metrics.k8s.io | tail -15
```
```yaml title="APIService registration (shape)" nocheck
apiVersion: apiregistration.k8s.io/v1
kind: APIService
metadata:
  name: v1beta1.metrics.k8s.io
spec:
  group: metrics.k8s.io
  version: v1beta1
  groupPriorityMinimum: 100
  versionPriority: 100
  service:
    name: metrics-server
    namespace: kube-system
```
@check
Why can a broken metrics-server block namespace deletion? || The namespace controller discovers all APIs. An unavailable aggregated API makes discovery fail, so it cannot confirm that the namespace is empty.
@end

@concept Server-side apply
@plain
With server-side apply (SSA) you send your desired fields and the API server merges them into the live object and records who owns each field.
@problem
Client-side `kubectl apply` stores the last config in an annotation and computes a patch on your laptop. Two writers such as a controller and a pipeline easily overwrite each other without noticing.
@does
- `kubectl apply --server-side` sends a PATCH of type `application/apply-patch+yaml`.
- The server tracks ownership in `metadata.managedFields`. If another manager owns a field you set to a different value, you get a conflict `409`.
- `--force-conflicts` takes ownership. Use it deliberately, since the other manager may then fight back.
- Fields you omit are left alone unless you previously owned them, in which case they are removed. This makes it safe to share objects.
- Flux and Argo CD both support server-side apply, which also avoids the 262144 byte annotation limit hit by large CRDs.
@diagram seq
caption: Conflict on a shared field
actors: ["Pipeline|manager kubectl|app", "API server|merge and track|cp", "HPA|manager hpa|info"]
steps:
  - "2>1: sets spec.replicas 5 | req"
  - "0>1: apply replicas 3 | req"
  - "1>0: 409 conflict | bad"
  - "0>1: apply without replicas | req"
  - "1>0: accepted | resp"
@h Try SSA
```bash title="Server-side apply with a dry run" lab
cat > /tmp/cm.yaml <<'EOF'
apiVersion: v1
kind: ConfigMap
metadata:
  name: ssa-demo
data:
  mode: blue
EOF
kubectl apply --server-side --field-manager=team-a -f /tmp/cm.yaml --dry-run=server -o yaml | head -20
```
:::warn
Do not set `spec.replicas` in a manifest that an HPA also manages. Remove the field from Git so that the HPA keeps ownership.
:::
@end

@concept Field managers and managedFields
@plain
Each writer has a manager name. `managedFields` lists which manager set which fields, with the operation (`Apply` or `Update`) and a timestamp.
@problem
When a value keeps changing back, you need to know which tool is changing it.
@does
- kubectl sets the manager from the command: `kubectl-client-side-apply`, `kubectl-edit`, and so on. Use `--field-manager` to name your pipeline.
- Controllers usually write as `Update` with their own names, for example `kube-controller-manager` or `cluster-autoscaler`.
- `kubectl get -o yaml --show-managed-fields` prints the data; by default kubectl hides it.
- Moving a field between managers: apply with the new manager and `--force-conflicts`, then stop the old one.
@diagram layers
caption: Who owns what in one Deployment
layers:
  - {label: "spec.template", nodes: ["Owner|argocd-controller|app", "Operation|Apply|info"]}
  - {label: "spec.replicas", nodes: ["Owner|hpa controller|ok", "Operation|Update|info"]}
  - {label: "metadata.annotations", nodes: ["Owner|kubectl-annotate|warn", "Operation|Update|info"]}
@h Find the owner of a field
```bash title="Who changed it" lab
kubectl get deploy api -n shop -o yaml --show-managed-fields | grep -E 'manager:|operation:|f:replicas' | head -20
kubectl get deploy api -n shop --show-managed-fields -o jsonpath='{range .metadata.managedFields[*]}{.manager}{" "}{.operation}{"\n"}{end}'
```
@check
What does a 409 conflict on apply tell you? || Another field manager owns a field you tried to set to a different value. Decide who should own it, then drop the field or force.
@end

@concept Watch, resourceVersion and informers
@plain
A watch is a long-lived HTTP stream of changes. Every object carries a `resourceVersion` that marks its place in etcd history, so a client can resume from a known point.
@problem
Polling the API for changes would overload it. Controllers need cheap, ordered and resumable notifications.
@does
- `GET ...?watch=true&resourceVersion=N` streams `ADDED`, `MODIFIED`, `DELETED` and `BOOKMARK` events after N.
- If N is too old (etcd compacted it) the server returns `410 Gone`, and the client must list again. This is called a relist.
- Treat `resourceVersion` as opaque. Never compare numbers; only pass them back.
- Informers in client-go list once, then watch, and keep a local cache. Controllers read the cache and use work queues, so they rarely call the API directly.
- Optimistic concurrency: an update with an old `resourceVersion` fails with `409`, and the client retries.
- Streaming list (`sendInitialEvents`) in recent versions reduces list memory on the API server. Check the current docs for your version.
@diagram seq
caption: Informer lifecycle
actors: ["Controller|informer|app", "API server|watch cache|cp", "etcd|history|db"]
steps:
  - "0>1: LIST all pods | req"
  - "1>0: items and rv 900 | resp"
  - "0>1: WATCH from rv 900 | req"
  - "1>2: serve from cache | req"
  - "1>0: MODIFIED events | resp"
  - "1>0: 410 Gone if too old | bad"
@h Watch from the command line
```bash title="See raw watch events" lab
kubectl get pods -n shop --watch-only -o name &
sleep 5; kill %1
kubectl get --raw "/api/v1/namespaces/shop/pods?watch=true&timeoutSeconds=5" | head -c 600
```
@check
What should a client do after 410 Gone? || Perform a new LIST to obtain a fresh resourceVersion and then start a new watch.
@end

@concept API priority and fairness
@plain
API Priority and Fairness (APF) is the API server's queueing system. It sorts requests into priority levels and flows so that one noisy client cannot starve the rest.
@problem
A buggy controller listing all pods in a loop can make the API server slow for everyone, including the kubelets and the scheduler.
@does
- A `FlowSchema` matches requests by user, group, verb and resource, and assigns them to a `PriorityLevelConfiguration`.
- Each level has concurrency shares and queues. Requests are spread by flow (typically per user and namespace) using shuffle sharding.
- Overloaded levels return `429 Too Many Requests` with `Retry-After`. Exempt and system levels protect leader election and node traffic.
- Metrics: `apiserver_flowcontrol_rejected_requests_total` and `apiserver_flowcontrol_current_inqueue_requests`.
- Managed control planes such as EKS and Gardener shoots may restrict what you can change, so check which objects are writable.
@diagram flow
caption: A request through APF
nodes:
  - "Request|user and verb|plain"
  - "FlowSchema|first match wins|info"
  - "Priority level|shares and queues|cp"
  - "Queue by flow|fair dequeue|app"
  - "Handled or 429|reject when full|ok"
@h Inspect and add a schema
```bash title="Look at APF objects" lab
kubectl get flowschemas
kubectl get prioritylevelconfigurations
kubectl get --raw /debug/api_priority_and_fairness/dump_priority_levels | head -20
```
```yaml title="Give a batch controller its own flow"
apiVersion: flowcontrol.apiserver.k8s.io/v1
kind: FlowSchema
metadata:
  name: batch-controller
spec:
  matchingPrecedence: 800
  priorityLevelConfiguration:
    name: workload-low
  distinguisherMethod:
    type: ByUser
  rules:
    - subjects:
        - kind: ServiceAccount
          serviceAccount:
            name: batch-controller
            namespace: batch
      resourceRules:
        - verbs: ["list", "watch"]
          apiGroups: ["*"]
          resources: ["*"]
          namespaces: ["*"]
```
:::note
`flowcontrol.apiserver.k8s.io/v1` is GA from 1.29. On older clusters use `v1beta3`. Check your version first.
:::
@end
