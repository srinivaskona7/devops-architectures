---
title: Owner references, finalizers and garbage collection
minutes: 40
objectives:
  - Use owner references so child objects are cleaned up automatically
  - Use finalizers to run cleanup for external resources before deletion
  - Unstick objects that stay Terminating without causing damage
---
Deleting an object is a process, not an instant. Kubernetes tracks who owns what and lets controllers block deletion until they have cleaned up. Understanding this is the key to fixing everything that is stuck in `Terminating`.
@concept Owner references
@plain
An object can list its **owner** in `metadata.ownerReferences`. When the owner is deleted, the garbage collector deletes the dependants.
@problem
A controller that creates child objects must clean them up when the parent goes away, even if the controller was down at that moment.
@does
- A ReplicaSet owns its Pods, a Deployment owns its ReplicaSets, a Job owns its Pods. Operators set the same for their children.
- `controller: true` marks the managing owner; `blockOwnerDeletion: true` makes foreground deletion wait for the child.
- Owner and dependant must be in the same namespace (or the owner cluster-scoped). Cross-namespace owners are not allowed.
- `kubectl get pod POD -o jsonpath='{.metadata.ownerReferences}'` shows the chain.
@diagram flow
caption: An ownership chain
nodes:
  - "Database orders|custom resource|info"
  - "StatefulSet orders|owned by Database|cp"
  - "Pod orders-0|owned by StatefulSet|app"
  - "PVC data-orders-0|kept by default|warn"
@h Inspect owners
```bash title="Who owns this" lab
kubectl get pod web-7d9f8c-x2k4p -n shop -o jsonpath='{range .metadata.ownerReferences[*]}{.kind}{"/"}{.name}{" controller="}{.controller}{"\n"}{end}'
kubectl get rs -n shop -o custom-columns=NAME:.metadata.name,OWNER:.metadata.ownerReferences[0].name
kubectl tree deployment web -n shop        # needs the kubectl-tree plugin (krew)
```
@end

@concept Garbage collection and deletion propagation
@plain
When you delete an object you choose what happens to its dependants: delete them in the background, wait for them first (foreground), or leave them behind (orphan).
@problem
Sometimes you want to remove a Deployment but keep its Pods running while you replace it. Other times deletion must not return until everything is gone.
@does
- **Background** (default): the owner disappears at once; the garbage collector removes dependants afterwards.
- **Foreground**: the owner gets a `foregroundDeletion` finalizer and stays visible until all dependants with `blockOwnerDeletion` are gone.
- **Orphan**: dependants are kept and their owner reference is removed (`--cascade=orphan`).
- Set with `kubectl delete --cascade=background|foreground|orphan`, or `propagationPolicy` in the API.
@diagram cmp
caption: Deletion policies
cards:
  - {h: "Background", kind: ok, items: ["Default", "Owner vanishes immediately", "Children removed after"]}
  - {h: "Foreground", kind: info, items: ["Owner waits for children", "Good for ordered teardown"]}
  - {h: "Orphan", kind: warn, items: ["Children survive", "Owner reference dropped", "Handy for migrations"]}
@h Commands
```bash title="Choose how deletion cascades" lab
kubectl delete deploy web -n shop --cascade=orphan          # Pods keep running without owner
kubectl delete deploy web -n shop --cascade=foreground      # wait for ReplicaSets and Pods
kubectl get rs,pods -n shop
```
@end

@concept Finalizers
@plain
A **finalizer** is a string in `metadata.finalizers` that tells the API server "do not remove this object yet". Deletion sets `deletionTimestamp`, and the object stays until every finalizer has been removed by its controller.
@problem
Some deletions need cleanup the API server cannot do: removing a cloud load balancer, deregistering from DNS, deleting a database in an external system. If the object vanished immediately, the cleanup would be lost.
@does
- The controller adds its finalizer when it first reconciles the object. On deletion, it sees `deletionTimestamp`, performs cleanup, removes its finalizer, and the API server then deletes the object.
- Built-in examples: `kubernetes.io/pvc-protection`, `foregroundDeletion`, and namespace finalizers.
- If the controller is gone, broken or cannot reach the external system, the object stays `Terminating` forever.
- Always make cleanup idempotent, and remove the finalizer even when the external resource is already gone.
@diagram seq
caption: Deletion with a finalizer
actors: ["User|kubectl delete|ext", "API server|object store|cp", "Controller|owns the finalizer|app"]
steps:
  - "0>1: delete Database | req"
  - "1>1: set deletionTimestamp, keep object | warn"
  - "1>2: watch event | req"
  - "2>2: delete cloud database | warn"
  - "2>1: remove finalizer | req"
  - "1>1: object removed | resp"
@h Finalizer handling in a reconciler
```go title="finalizer.go" nocheck
const dbFinalizer = "data.example.com/cleanup"

if db.DeletionTimestamp.IsZero() {
	// object is live: make sure our finalizer is present
	if controllerutil.AddFinalizer(&db, dbFinalizer) {
		if err := r.Update(ctx, &db); err != nil {
			return ctrl.Result{}, err
		}
	}
} else if controllerutil.ContainsFinalizer(&db, dbFinalizer) {
	// object is being deleted: clean up, then release it
	if err := r.deleteExternalDatabase(ctx, &db); err != nil {
		return ctrl.Result{}, err // retry; the object stays Terminating
	}
	controllerutil.RemoveFinalizer(&db, dbFinalizer)
	if err := r.Update(ctx, &db); err != nil {
		return ctrl.Result{}, err
	}
	return ctrl.Result{}, nil
}
```
@end

@concept Objects stuck in Terminating
@plain
An object with a `deletionTimestamp` that never disappears is waiting for a finalizer. Find out which one before you remove it.
@problem
A namespace cannot be deleted, a PVC stays Terminating, or a custom resource blocks a Helm uninstall. Pipelines hang.
@does
- Look at `metadata.finalizers` and the owning controller. Is the controller running? Does its log show errors?
- **Namespaces**: check `kubectl get ns NAME -o yaml` conditions (`NamespaceContentRemaining`, `NamespaceFinalizersRemaining`, `NamespaceDeletionDiscoveryFailure`). Typical cause: a CRD was removed first, leaving CRs without a controller, or an unavailable aggregated API (metrics-server).
- **Fix the cause first**: restore the controller or the CRD, or fix the external dependency, and the object will finish itself.
- **Last resort**: patch the finalizer away. This skips the cleanup, and can leave cloud resources (disks, load balancers) behind that cost money.
@diagram flow
caption: Stuck deletion decision path
nodes:
  - "deletionTimestamp set|object Terminating|warn"
  - "Which finalizer|read metadata.finalizers|info"
  - "Is the controller healthy|fix it first|cp"
  - "Remove finalizer|last resort, manual cleanup|bad"
@h Commands
```bash title="Diagnose before forcing" lab
kubectl get ns shop -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.message}{"\n"}{end}'
kubectl api-resources --verbs=list --namespaced -o name | xargs -n1 kubectl get --show-kind --ignore-not-found -n shop
kubectl get database orders -n shop -o jsonpath='{.metadata.finalizers}{" "}{.metadata.deletionTimestamp}{"\n"}'
kubectl logs -n database-system deploy/database-operator --tail=30
# last resort, accepting that cleanup will be skipped
kubectl patch database orders -n shop --type=merge -p '{"metadata":{"finalizers":null}}'
```
:::danger
Never "finalize" a namespace through `/finalize` or strip finalizers in bulk as a routine fix. It leaves orphaned external resources and hides the real fault. Record what you skipped and clean it up by hand.
:::
@check
What does the API server do when you delete an object that has a finalizer? || It sets deletionTimestamp and keeps the object until every finalizer is removed by its controller.
Name a safer first step than removing a finalizer. || Find the controller that owns the finalizer and restore it (or its CRD or dependency) so it can finish cleanup.
@end

@concept Server-side apply and field ownership
@plain
With **server-side apply (SSA)**, the API server tracks which manager owns each field (`metadata.managedFields`) and reports conflicts when two managers change the same field.
@problem
GitOps, an operator, an HPA and a human may all edit the same object. With client-side apply, they overwrite each other silently or produce confusing diffs.
@does
- `kubectl apply --server-side --field-manager=NAME` claims fields your manifest sets. Fields you omit are left to other managers.
- A conflict is returned when another manager owns a field you try to change; `--force-conflicts` takes ownership.
- Example: the HPA owns `spec.replicas`, so your manifest should omit replicas for HPA-managed Deployments.
- Operators should use SSA (`client.Apply` patches) to own only their fields.
@diagram flow
caption: Who owns which field
nodes:
  - "GitOps manager|image, labels|app"
  - "HPA|replicas|info"
  - "Operator|status, finalizers|cp"
  - "Conflict|two managers, same field|bad"
@h Commands
```bash title="See and resolve ownership" lab
kubectl get deploy web -n shop -o yaml --show-managed-fields | sed -n '/managedFields/,$p' | head -30
kubectl apply --server-side --field-manager=gitops -f deploy.yaml
kubectl apply --server-side --field-manager=gitops --force-conflicts -f deploy.yaml
kubectl diff --server-side -f deploy.yaml
```
@end
