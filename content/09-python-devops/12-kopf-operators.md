---
title: Writing operators with kopf
minutes: 50
objectives:
  - Explain the operator pattern and the reconcile loop
  - Write kopf handlers for create, update and delete events
  - Create child resources idempotently and report status
  - Deploy an operator with minimal RBAC
---
An operator is a controller that manages an application through a custom resource. Kopf lets you write one in plain Python functions, with the watch loop, retries and state tracking handled for you.

@concept The operator pattern
@plain
You describe what you want in a **custom resource** (for example `kind: Database`). A controller watches those objects and keeps reality equal to the description. This comparison and correction is called **reconciliation**.
@problem
Running a stateful application by hand needs runbooks: create the volume, the secret, the service, then do it again after failure. Humans forget steps and cannot react at 3 a.m.
@does
- Declarative: you state the desired state; the controller makes it so, repeatedly.
- Level triggered: it should work out what to do from the current state, not from the event alone.
- Reconciliation must be idempotent because it may run many times.
@diagram flow
caption: The reconcile loop
nodes:
  - "Custom resource|desired state|app"
  - "Controller|watches changes|cp"
  - "Compare|desired versus actual|info"
  - "Act|create or patch children|env"
  - "Status|report what happened|ok"
@h Use operators sparingly
:::tip
Write an operator only when you have domain logic that must run continuously. For a one off job a CronJob or script is simpler and safer.
:::
@check
Why must reconciliation be idempotent? || It runs repeatedly for the same object, and running it twice must give the same result as once.
@end

@concept A custom resource definition
@plain
A **CRD** teaches the Kubernetes API a new kind with a schema. After applying it, `kubectl get databases` works like any built in resource.
@problem
Without a schema, users can put anything in your objects and the operator only finds out when it fails. The API server can reject bad input for you.
@does
- `group`, `names` (kind, plural, singular), `scope` (Namespaced or Cluster) and versions.
- `openAPIV3Schema` validates `spec` types and required fields; `subresources.status` separates user input from controller output.
- `additionalPrinterColumns` shapes `kubectl get`.
@diagram layers
caption: Parts of a CRD
layers:
  - {label: "Identity", nodes: ["group|ops.example.com|cp", "kind|Database|app", "scope|Namespaced|info"]}
  - {label: "Schema", nodes: ["spec|user input|env", "status|controller output|env"]}
  - {label: "Behaviour", nodes: ["subresources status|separate writes|ok", "printer columns|kubectl get output|ok"]}
@h Example
```yaml title="database-crd.yaml"
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: databases.ops.example.com
spec:
  group: ops.example.com
  scope: Namespaced
  names: {kind: Database, plural: databases, singular: database, shortNames: [db]}
  versions:
    - name: v1
      served: true
      storage: true
      subresources: {status: {}}
      additionalPrinterColumns:
        - {name: Size, type: integer, jsonPath: .spec.sizeGb}
        - {name: Phase, type: string, jsonPath: .status.phase}
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              required: [sizeGb]
              properties:
                sizeGb: {type: integer, minimum: 1, maximum: 1000}
                engine: {type: string, enum: [postgres, mysql], default: postgres}
            status:
              type: object
              x-kubernetes-preserve-unknown-fields: true
```
@check
Why enable the status subresource? || It lets the controller write status without touching spec, and users cannot overwrite status through spec edits.
@end

@concept kopf handlers
@plain
You decorate ordinary functions. `@kopf.on.create` runs when an object appears, `@kopf.on.update` when it changes, `@kopf.on.delete` when it is removed, and `@kopf.on.resume` after the operator restarts.
@problem
Writing watch loops by hand means handling reconnects, resource versions, retries and remembering what was already done.
@does
- Handlers receive arguments by name: `spec`, `meta`, `status`, `name`, `namespace`, `logger`, `patch`, `body`.
- Whatever a handler returns is stored in `status.<handler name>`.
- Raising `kopf.TemporaryError("wait", delay=30)` retries later; `kopf.PermanentError` stops retrying.
- Kopf stores progress in annotations, so a restart continues where it left off.
@diagram seq
caption: An event reaches your function
actors: ["User|kubectl apply|ext", "API server|stores object|cp", "kopf|framework|app", "Handler|your function|ok"]
steps:
  - "0>1: create Database | req"
  - "2>1: watch stream | req"
  - "1>2: ADDED event | resp"
  - "2>3: call on.create | req"
  - "3>2: result or error | resp"
  - "note 2..2: retry on TemporaryError"
@h Skeleton
```python title="operator.py" nocheck
import kopf


@kopf.on.create("ops.example.com", "v1", "databases")
def created(spec, name, namespace, logger, **_):
    logger.info("creating database %s with %s GB", name, spec["sizeGb"])
    return {"created": True}


@kopf.on.update("ops.example.com", "v1", "databases", field="spec.sizeGb")
def resized(old, new, name, logger, **_):
    logger.info("resizing %s from %s to %s", name, old, new)


@kopf.on.delete("ops.example.com", "v1", "databases")
def deleted(name, logger, **_):
    logger.info("cleaning up %s", name)
```
```bash title="Run it against your current context" nocheck
kopf run operator.py --namespace=default --verbose
```
@check
How do you retry a handler later? || Raise kopf.TemporaryError with a delay.
@end

@concept Creating child resources idempotently
@plain
The operator creates a StatefulSet, Service or Secret for each custom object. Children carry an **owner reference**, so deleting the parent deletes them, and creation must tolerate "already exists".
@problem
If a handler creates a Service and then crashes, the retry creates it again and fails with 409, or leaves duplicates after a restart.
@does
- `kopf.adopt(obj)` adds ownerReferences and labels to a child dictionary.
- Create with the Kubernetes client and treat `409 AlreadyExists` as success, or patch instead.
- Name children deterministically from the parent (`f"{name}-svc"`), never randomly.
- Garbage collection removes children when the owner is deleted, so a delete handler is often unnecessary.
@diagram flow
caption: Safe child creation
numbered: true
nodes:
  - "Build child dict|name from parent|app"
  - "kopf.adopt|owner reference|info"
  - "create|API call|env"
  - "409 exists|treat as success or patch|warn"
@h Example
```python title="children.py" nocheck
import kopf
import kubernetes
from kubernetes.client.exceptions import ApiException


@kopf.on.create("ops.example.com", "v1", "databases")
def create_children(spec, name, namespace, body, logger, **_):
    svc = {
        "apiVersion": "v1", "kind": "Service",
        "metadata": {"name": f"{name}-svc"},
        "spec": {"selector": {"db": name}, "ports": [{"port": 5432}]},
    }
    kopf.adopt(svc)                                   # sets ownerReferences from the current object
    api = kubernetes.client.CoreV1Api()
    try:
        api.create_namespaced_service(namespace, svc)
    except ApiException as exc:
        if exc.status != 409:
            raise
        logger.info("service already exists, leaving it")
```
@check
Why name children from the parent name? || A retry then targets the same object instead of creating a second one.
@end

@concept Status, events and finalizers
@plain
Status tells users what the operator did. Events appear in `kubectl describe`. A **finalizer** blocks deletion until cleanup of things outside Kubernetes (such as a cloud disk) has finished.
@problem
Owner references clean up Kubernetes objects only. External resources would leak, and users get no feedback about progress or failure.
@does
- Writing `patch.status["phase"] = "Ready"` in a handler updates the status subresource.
- `kopf.info(body, reason="Created", message="...")` posts an Event; `kopf.warn` and `kopf.exception` for problems.
- Kopf adds its own finalizer to objects with a delete handler, so the delete handler runs before removal.
- Make external cleanup idempotent: tolerate "already gone".
@diagram seq
caption: Delete with a finalizer
actors: ["User|kubectl delete|ext", "API server|sets deletionTimestamp|cp", "kopf|delete handler|app", "Cloud|external disk|ext"]
steps:
  - "0>1: delete Database | req"
  - "2>3: delete disk, ignore missing | req"
  - "3>2: done | resp"
  - "2>1: remove finalizer | req"
  - "note 1..1: object now disappears"
@h Example
```python title="status_events.py" nocheck
import kopf


@kopf.on.create("ops.example.com", "v1", "databases")
def create(spec, patch, body, **_):
    patch.status["phase"] = "Provisioning"
    kopf.info(body, reason="Provisioning", message=f"{spec['sizeGb']} GB requested")


@kopf.on.delete("ops.example.com", "v1", "databases")
def delete(name, logger, **_):
    logger.info("releasing external disk for %s (missing is fine)", name)
```
@check
What is a finalizer for? || It keeps the object in place until cleanup of external resources has completed.
@end

@concept Timers, daemons and deploying the operator
@plain
`@kopf.timer` runs a function at an interval for each object, ideal for drift checks. Deploy the operator as a Deployment with a service account and only the RBAC it needs.
@problem
Events alone cannot detect drift in external systems. An operator with cluster admin rights is a large attack surface.
@does
- `@kopf.timer("ops.example.com", "v1", "databases", interval=60, idle=30)` runs per object.
- Run one replica, or enable peering so only one instance is active and the standby takes over.
- Grant `get/list/watch/patch` on your CRD and its status, plus create on the children kinds, and `events` create.
- Include health with `@kopf.on.probe`, and use `--liveness=http://0.0.0.0:8080/healthz`.
@diagram layers
caption: Operator deployment
layers:
  - {label: "Kubernetes API", nodes: ["Database CRD|your kind|cp", "Children|Service, StatefulSet|cp"]}
  - {label: "Operator pod", nodes: ["kopf run|handlers|app", "ServiceAccount|identity|env"]}
  - {label: "RBAC", nodes: ["ClusterRole|least privilege|warn", "Binding|to the service account|ok"]}
@h RBAC and timer
```yaml title="operator-rbac.yaml"
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: database-operator
rules:
  - apiGroups: ["ops.example.com"]
    resources: ["databases", "databases/status"]
    verbs: ["get", "list", "watch", "patch", "update"]
  - apiGroups: [""]
    resources: ["services", "secrets"]
    verbs: ["get", "list", "watch", "create", "patch"]
  - apiGroups: [""]
    resources: ["events"]
    verbs: ["create"]
  - apiGroups: ["apiextensions.k8s.io"]
    resources: ["customresourcedefinitions"]
    verbs: ["list", "watch"]
```
```python title="drift_timer.py" nocheck
import kopf


@kopf.timer("ops.example.com", "v1", "databases", interval=60, idle=30)
def check_drift(name, patch, logger, **_):
    healthy = True            # call your real health check here
    patch.status["healthy"] = healthy
    if not healthy:
        raise kopf.TemporaryError("database unhealthy", delay=30)
```
@check
Why run a single active replica? || Two active controllers would act on the same objects at once and fight each other.
@end

@concept Tool: a crash loop notifier
@plain
A small watcher that prints a line when a container enters `CrashLoopBackOff`, with its restart count and last exit code. It shows the watch API at work without needing a CRD.
@problem
Teams discover restart loops from a user complaint rather than from the cluster. A watcher turns the state into an early signal.
@does
- Streams pod events and checks `container_statuses[].state.waiting.reason`.
- Deduplicates alerts per pod and container until the restart count changes.
- The decision function is pure, so it can be tested without a cluster.
@diagram flow
caption: From event to alert
nodes:
  - "Pod event|watch stream|app"
  - "Check waiting reason|CrashLoopBackOff|info"
  - "Deduplicate|per pod and restart count|env"
  - "Notify|log or webhook|ok"
@h Decision logic offline
```python title="crashloop.py" lab
from __future__ import annotations

from types import SimpleNamespace as NS

seen: dict[tuple[str, str], int] = {}


def crashloops(pod) -> list[str]:
    alerts = []
    for cs in pod.status.container_statuses or []:
        waiting = cs.state.waiting if cs.state else None
        if waiting and waiting.reason == "CrashLoopBackOff":
            key = (pod.metadata.name, cs.name)
            if seen.get(key) != cs.restart_count:
                seen[key] = cs.restart_count
                last = cs.last_state.terminated.exit_code if cs.last_state and cs.last_state.terminated else "?"
                alerts.append(f"{pod.metadata.namespace}/{pod.metadata.name}/{cs.name} restarts={cs.restart_count} lastExit={last}")
    return alerts


pod = NS(metadata=NS(name="web-1", namespace="shop"), status=NS(container_statuses=[
    NS(name="app", restart_count=5, state=NS(waiting=NS(reason="CrashLoopBackOff")),
       last_state=NS(terminated=NS(exit_code=137)))]))
print(crashloops(pod))
print(crashloops(pod))      # same restart count, so no duplicate alert
```
```python title="Wire it to a watch" nocheck
from kubernetes import client, config, watch

config.load_kube_config()
v1 = client.CoreV1Api()
for ev in watch.Watch().stream(v1.list_pod_for_all_namespaces, timeout_seconds=600):
    for line in crashloops(ev["object"]):
        print("ALERT", line)
```
@check
Why deduplicate by restart count? || Each event repeats the same state; alerting only when the count changes avoids floods.
@end
