---
title: Controllers and the operator pattern
minutes: 45
objectives:
  - Describe the reconcile loop and why controllers are level triggered
  - Explain the operator pattern and when to use or avoid it
  - Read the anatomy of a controller built with controller-runtime
---
A CRD is only data. A **controller** watches that data and makes the world match it. A controller that encodes the operational knowledge of a specific application is called an **operator**.
@concept The reconcile loop
@plain
A controller repeatedly compares **desired state** (spec) with **observed state** (the real world) and takes actions to reduce the difference. It does not react to events as commands; it re-evaluates the whole situation.
@problem
Systems fail partway, events get lost, controllers restart. A design based on "do exactly what this event says" breaks. You need something that converges to the right state from any starting point.
@does
- **Level triggered, not edge triggered**: events only say "look at object X again". The reconciler reads current state and decides what to do, so missing an event is harmless.
- Reconcile must be **idempotent**: running it ten times gives the same result as once.
- Work arrives through a **work queue** with rate limiting and retries with backoff. Failed reconciles are requeued.
- Built-in controllers (Deployment, ReplicaSet, Job) work exactly this way.
@diagram flow
caption: Control loop
numbered: true
nodes:
  - "Watch|object changed|info"
  - "Queue|key namespace/name|plain"
  - "Reconcile|read spec and world|app"
  - "Act|create, update, delete|cp"
  - "Update status|report result|ok"
@h See controllers at work
```bash title="Observe a built-in controller" lab
kubectl create deploy demo --image=nginx:1.27 --replicas=3
kubectl delete pod -l app=demo --wait=false      # the controller notices the difference
kubectl get pods -l app=demo -w
kubectl get events --field-selector involvedObject.kind=ReplicaSet | tail -5
kubectl delete deploy demo
```
@check
Why should a reconciler not assume it sees every event? || Controllers are level triggered: events can be coalesced, dropped or replayed after restart. The reconciler must derive its actions from current state.
@end

@concept Informers, caches and the work queue
@plain
Controllers do not poll the API server. An **informer** opens a watch, keeps a local cache of objects, and notifies handlers when something changes.
@problem
Hundreds of controllers each listing all Pods every second would overwhelm the API server.
@does
- The first step is a **list** (initial sync), then a **watch** stream of changes, resumed by `resourceVersion`.
- Reads in the reconciler come from the local cache (cheap, slightly stale); writes go to the API server.
- Handlers enqueue object keys; duplicates collapse, so a burst of 50 changes causes one reconcile.
- Because the cache can be stale, writes use `resourceVersion` for optimistic concurrency. A conflict error means: re-read and retry.
@diagram layers
caption: Inside a controller process
layers:
  - {label: "API server", nodes: ["list and watch|one stream per type|cp"]}
  - {label: "Controller process", nodes: ["Informer cache|local copy of objects|db", "Work queue|deduplicated keys, backoff|plain", "Reconciler|your logic|app"]}
  - {label: "Writes", nodes: ["Client|create, update, patch|ext"]}
@h Cost on the API server
```bash title="Watch API traffic" lab
kubectl get --raw /metrics | grep '^apiserver_registered_watchers' | head
kubectl get --raw /metrics | grep 'apiserver_request_total' | grep 'verb="WATCH"' | head -5
kubectl get --raw '/apis/data.example.com/v1/namespaces/shop/databases?watch=1&timeoutSeconds=5'
```
@end

@concept The operator pattern
@plain
An **operator** is a CRD plus a controller that automates the operational tasks a skilled human would do for a particular application: install, configure, back up, upgrade, fail over.
@problem
Stateful software (databases, message brokers, search clusters) needs more than a Deployment. Someone must initialise replicas, promote a new primary, resize volumes and run upgrades in the right order.
@does
- You declare `kind: PostgresCluster` with instances and backup schedule; the operator creates StatefulSets, Services, Secrets and CronJobs and keeps them healthy.
- Examples: cert-manager, Prometheus Operator, CloudNativePG, Strimzi (Kafka), Argo CD, Crossplane, Istio operator.
- Capability levels range from basic install through upgrades, lifecycle and backup, up to auto-tuning.
- Operators are powerful but are privileged software: review their RBAC and treat their upgrades as platform changes.
@diagram flow
caption: Operator replaces a runbook
nodes:
  - "Custom resource|3 instances, backups nightly|info"
  - "Operator|encodes the runbook|app"
  - "Child objects|StatefulSet, Service, CronJob|cp"
  - "Healthy database|operator keeps it so|ok"
@choose Operator or something simpler
Operator | stateful or complex software with ordered lifecycle steps | a stateless app a Deployment and Helm chart can run
Helm chart only | static installs and upgrades with no runtime logic | day-2 tasks such as failover must be automated
Managed service | an RDS, Cloud SQL or HANA Cloud instance meets the need | you must stay in the cluster or avoid vendor lock-in
Custom operator | no operator exists and the logic is truly specific to you | an existing, well maintained operator already does it
@end

@concept Anatomy of a controller-runtime reconciler
@plain
**controller-runtime** is the Go library behind Kubebuilder and Operator SDK. You write one `Reconcile` function that receives a name and namespace and returns whether to requeue.
@problem
Writing informers, caches, leader election, metrics and webhooks from scratch is a lot of error-prone plumbing.
@does
- `Reconcile(ctx, req)`: fetch the object by `req.NamespacedName`; if not found, return (it was deleted). Compare to desired child objects, create or update them, update status.
- `ctrl.NewControllerManagedBy(mgr).For(&Database{}).Owns(&appsv1.StatefulSet{})` makes changes to owned children trigger a reconcile of the parent.
- The **manager** provides the cache, clients, leader election (only one active replica), health probes and metrics.
- `controllerutil.CreateOrUpdate` and `SetControllerReference` make child management concise.
- Return `ctrl.Result{RequeueAfter: d}` for periodic checks, or an error for retry with backoff.
@diagram seq
caption: One reconcile
actors: ["Manager|queue and cache|cp", "Reconciler|your code|app", "API server|cluster|cp"]
steps:
  - "0>1: Reconcile shop/orders | req"
  - "1>0: read Database from cache | req"
  - "1>2: create or update StatefulSet | req"
  - "1>2: patch status.phase | req"
  - "1>0: Result with RequeueAfter 60s | resp"
@h A trimmed reconciler in Go
```go title="database_controller.go" nocheck
func (r *DatabaseReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	var db datav1.Database
	if err := r.Get(ctx, req.NamespacedName, &db); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err) // deleted, nothing to do
	}

	sts := &appsv1.StatefulSet{ObjectMeta: metav1.ObjectMeta{Name: db.Name, Namespace: db.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, sts, func() error {
		sts.Spec = buildStatefulSetSpec(&db)                  // desired state from spec
		return controllerutil.SetControllerReference(&db, sts, r.Scheme)
	})
	if err != nil {
		return ctrl.Result{}, err                             // retried with backoff
	}

	db.Status.Phase = "Ready"
	db.Status.ObservedGeneration = db.Generation
	if err := r.Status().Update(ctx, &db); err != nil {
		return ctrl.Result{}, err
	}
	return ctrl.Result{RequeueAfter: time.Minute}, nil
}

func (r *DatabaseReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&datav1.Database{}).
		Owns(&appsv1.StatefulSet{}).
		Complete(r)
}
```
@end

@concept Status, conditions and generations
@plain
A controller reports progress in `status`, using standard **conditions**, and records which version of the spec it has processed in `observedGeneration`.
@problem
Users and automation need to know whether a custom resource is ready, stuck or failed, and whether the status reflects their latest change.
@does
- `metadata.generation` increases on every spec change; `status.observedGeneration` equals it once the controller has handled that change. If they differ, status is stale.
- Conditions follow a standard shape: `type` (Ready), `status` (True/False/Unknown), `reason` (CamelCase), `message`, `lastTransitionTime`.
- `kubectl wait --for=condition=Ready` and GitOps health checks depend on this convention.
- Keep status derived and rebuildable; never store the only copy of important data there.
@diagram flow
caption: Generation tracking
nodes:
  - "User edits spec|generation 4|env"
  - "Controller reconciles|works on generation 4|app"
  - "observedGeneration 4|status current|info"
  - "Ready True|safe to depend on|ok"
@h A status with conditions
```yaml title="status-example.yaml"
apiVersion: data.example.com/v1
kind: Database
metadata:
  name: orders
  namespace: shop
  generation: 4
status:
  observedGeneration: 4
  phase: Ready
  conditions:
    - type: Ready
      status: "True"
      reason: AllReplicasAvailable
      message: 3 of 3 instances are ready
      lastTransitionTime: "2026-10-31T10:15:00Z"
```
```bash title="Wait on conditions" lab
kubectl wait --for=condition=Ready database/orders -n shop --timeout=300s
kubectl get database orders -n shop -o jsonpath='{.metadata.generation} {.status.observedGeneration}{"\n"}'
```
@end

@concept Building operators and RBAC
@plain
Frameworks scaffold the project: **Kubebuilder** and **Operator SDK** (Go), Kopf (Python), and Java Operator SDK. Whatever the language, the operator runs as a Deployment with a ServiceAccount and RBAC.
@problem
Teams build operators with far too broad permissions, no leader election, and no metrics, then run them as cluster-admin.
@does
- Kubebuilder generates CRD manifests from Go type markers (`make manifests`), and RBAC rules from `//+kubebuilder:rbac` comments.
- Run **two replicas with leader election** for availability; only the leader reconciles.
- Give least-privilege RBAC: only the verbs and resources needed, namespaced where possible.
- Expose metrics and health endpoints, and set resource requests. Test with envtest (a real API server and etcd binaries) before shipping.
@diagram layers
caption: Pieces of an operator project
layers:
  - {label: "API types", nodes: ["Go structs|Database spec and status|info", "CRD YAML|generated|ok"]}
  - {label: "Logic", nodes: ["Reconciler|idempotent|app", "Webhooks|defaulting and validation|warn"]}
  - {label: "Packaging", nodes: ["Deployment and RBAC|least privilege|cp", "Helm chart or kustomize|distribution|ext"]}
@h Least privilege RBAC for the operator
```yaml title="operator-rbac.yaml"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: database-operator
rules:
  - apiGroups: ["data.example.com"]
    resources: ["databases", "databases/status", "databases/finalizers"]
    verbs: ["get", "list", "watch", "update", "patch"]
  - apiGroups: ["apps"]
    resources: ["statefulsets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["services", "secrets", "events"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
  - apiGroups: ["coordination.k8s.io"]
    resources: ["leases"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
```
@end
