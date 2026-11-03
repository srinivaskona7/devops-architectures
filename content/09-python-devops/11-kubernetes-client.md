---
title: The Kubernetes Python client
minutes: 50
objectives:
  - Load kubeconfig or in-cluster credentials from the same code
  - List, page through and watch Kubernetes objects
  - Patch objects and run commands in pods
  - Build a resource report from live cluster data
---
The official `kubernetes` package is a generated client for the Kubernetes API. If you know `kubectl get`, `patch`, `exec` and `logs`, you already know what to call; this section shows the Python names.

@concept Loading configuration and in-cluster auth
@plain
On a laptop the client reads your kubeconfig file. Inside a pod it reads the service account token and CA certificate that Kubernetes mounts automatically. One function call picks the right one.
@problem
A tool that works on your laptop but needs different code when running as a pod or CronJob doubles the maintenance and tempts people to bake kubeconfigs into images.
@does
- `config.load_kube_config(context="platformsbx")` reads `~/.kube/config` (or `KUBECONFIG`) and can select a context.
- `config.load_incluster_config()` uses `/var/run/secrets/kubernetes.io/serviceaccount/`; it raises `ConfigException` outside a cluster.
- Permissions come from RBAC bound to the service account, so grant only what the tool needs.
@diagram flow
caption: Choosing credentials
nodes:
  - "Try in-cluster|token and CA from the pod|app"
  - "Fallback kubeconfig|your context|info"
  - "ApiClient|authenticated|env"
  - "CoreV1Api and others|typed calls|ok"
@h A loader that works in both places
```python title="k8s_config.py" nocheck
from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException


def load(context: str | None = None) -> None:
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config(context=context)


load()
v1 = client.CoreV1Api()
print([ns.metadata.name for ns in v1.list_namespace().items][:5])
```
:::note
Select the context explicitly in tools that change things. Acting on whichever context happens to be current is how the wrong cluster gets modified.
:::
@check
Which call works inside a pod? || config.load_incluster_config().
@end

@concept Listing and filtering objects
@plain
The API classes group endpoints: `CoreV1Api` (pods, services, nodes, namespaces), `AppsV1Api` (deployments, statefulsets), `BatchV1Api` (jobs), `NetworkingV1Api`, and `CustomObjectsApi` for CRDs.
@problem
Fetching everything with `kubectl get -A -o json` and filtering client side is heavy; the API can filter by label and field for you.
@does
- `list_namespaced_pod(ns, label_selector="app=web", field_selector="status.phase=Running")`.
- `list_pod_for_all_namespaces()` is the cluster wide form.
- Results are model objects: `pod.metadata.name`, `pod.status.phase`, `pod.spec.containers[0].resources`.
- `_preload_content=False` returns the raw response if you prefer dictionaries.
@diagram layers
caption: Where each resource lives
layers:
  - {label: "core v1", nodes: ["Pod|CoreV1Api|app", "Service|CoreV1Api|app", "Node|CoreV1Api|app", "Namespace|CoreV1Api|app"]}
  - {label: "apps and batch", nodes: ["Deployment|AppsV1Api|env", "StatefulSet|AppsV1Api|env", "Job and CronJob|BatchV1Api|env"]}
  - {label: "custom", nodes: ["Your CRD|CustomObjectsApi|cp"]}
@h Example
```python title="list_pods.py" nocheck
from kubernetes import client, config

config.load_kube_config()
v1 = client.CoreV1Api()
pods = v1.list_namespaced_pod("default", label_selector="app=web", field_selector="status.phase=Running")
for p in pods.items:
    restarts = sum(cs.restart_count for cs in (p.status.container_statuses or []))
    print(p.metadata.name, p.spec.node_name, "restarts", restarts)
```
@check
Where should filtering by label happen? || In the API call with label_selector, so only matching objects are sent.
@end

@concept Pagination with limit and continue
@plain
Large clusters can have tens of thousands of objects. The API supports `limit` and returns a `_continue` token so you fetch them in chunks.
@problem
A single huge list uses lots of memory on both sides and can time out or load the API server.
@does
- Pass `limit=500` and loop while the response's `metadata._continue` is set.
- Keep the same selectors on every call.
- If the token expires (HTTP 410) restart the listing.
@diagram flow
caption: Chunked listing
nodes:
  - "list limit 500|first chunk|app"
  - "metadata._continue|token to fetch more|info"
  - "list with token|next chunk|app"
  - "No token|finished|ok"
@h Generator
```python title="paged_pods.py" nocheck
from kubernetes import client, config

config.load_kube_config()
v1 = client.CoreV1Api()


def all_pods(limit: int = 500):
    token = None
    while True:
        resp = v1.list_pod_for_all_namespaces(limit=limit, _continue=token)
        yield from resp.items
        token = resp.metadata._continue
        if not token:
            return


print(sum(1 for _ in all_pods()), "pods")
```
@check
What does a 410 response during paging mean? || The continue token expired, so start the listing again.
@end

@concept Watching for changes
@plain
A **watch** keeps a connection open and streams events (ADDED, MODIFIED, DELETED) as objects change. Controllers and notifiers use it instead of polling.
@problem
Polling every few seconds wastes API calls and still misses short lived changes between polls.
@does
- `watch.Watch().stream(v1.list_namespaced_pod, "default", timeout_seconds=60)` yields dicts with `type` and `object`.
- Streams end after the timeout or when the server closes; wrap the call in a loop.
- Track `resource_version` to resume without missing events; on 410 Gone, list again and restart.
- For serious controllers prefer a framework (kopf) that handles this.
@diagram seq
caption: A watch stream
actors: ["Your tool|watch.stream|app", "API server|events|cp"]
steps:
  - "0>1: list + watch from version 100 | req"
  - "1>0: ADDED pod web-1 | resp"
  - "1>0: MODIFIED pod web-1 | resp"
  - "1>0: DELETED pod web-1 | resp"
  - "note 0..1: timeout, then reconnect"
@h Example
```python title="watch_pods.py" nocheck
from kubernetes import client, config, watch
from kubernetes.client.exceptions import ApiException

config.load_kube_config()
v1 = client.CoreV1Api()
rv = None
while True:
    try:
        w = watch.Watch()
        for ev in w.stream(v1.list_namespaced_pod, "default", resource_version=rv, timeout_seconds=300):
            pod = ev["object"]
            rv = pod.metadata.resource_version
            print(ev["type"], pod.metadata.name, pod.status.phase)
    except ApiException as exc:
        if exc.status == 410:           # resource version too old
            rv = None
            continue
        raise
```
@check
Why wrap the stream in a loop? || Watches end after a timeout or on connection loss, so the tool must reconnect and resume.
@end

@concept Creating and patching objects
@plain
`patch_*` changes selected fields. `replace_*` swaps the whole object. For idempotent updates prefer a patch, or server side apply, over read, modify and replace.
@problem
Read-modify-write races: if someone else changes the object between your read and your write, you overwrite their change or get a conflict.
@does
- Strategic merge patch (default for built in types): `v1.patch_namespaced_...(name, ns, {"spec": {"replicas": 3}})` merges lists by key.
- Merge patch (JSON merge patch) replaces lists as a whole; select with a content type.
- Server side apply sends a full desired state with a field manager and handles ownership of fields.
- Always check `ApiException.status`: 404 missing, 409 conflict, 403 RBAC, 422 invalid.
@diagram cmp
caption: Update styles
cards:
  - {h: "replace", kind: warn, items: ["Whole object swapped", "Needs resourceVersion", "Conflicts with other writers"]}
  - {h: "patch", kind: ok, items: ["Only named fields change", "Safe when others edit other fields", "Good for scale and labels"]}
  - {h: "server side apply", kind: info, items: ["Declare desired state", "Field ownership tracked", "Idempotent by design"]}
@h Scaling and annotating
```python title="patch.py" nocheck
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

config.load_kube_config()
apps = client.AppsV1Api()

try:
    apps.patch_namespaced_deployment_scale("web", "default", {"spec": {"replicas": 3}})
    apps.patch_namespaced_deployment(
        "web", "default",
        {"metadata": {"annotations": {"ops/last-touched-by": "opskit"}}},
    )
except ApiException as exc:
    print("failed", exc.status, exc.reason)
```
:::warn
Restarting a deployment is a patch of an annotation on the pod template (`kubectl.kubernetes.io/restartedAt`). Do not delete pods by hand to fake a rollout.
:::
@check
Why is patch safer than replace? || It changes only the fields you name, so concurrent edits to other fields are kept.
@end

@concept Exec, logs and port access
@plain
`stream()` runs a command in a container over a WebSocket, like `kubectl exec`. `read_namespaced_pod_log` fetches logs like `kubectl logs`.
@problem
Debug helpers and health checks often need a command run inside a pod or a log tail across many pods.
@does
- `stream(v1.connect_get_namespaced_pod_exec, name, ns, command=[...], stderr=True, stdin=False, stdout=True, tty=False)` returns the output text.
- `read_namespaced_pod_log(name, ns, container="app", tail_lines=100, since_seconds=3600)`.
- Exec needs the `pods/exec` RBAC permission; grant it sparingly because it is a powerful permission.
- Pass the command as a list, never one shell string built from user input.
@diagram flow
caption: Exec through the API server
nodes:
  - "Your tool|stream call|app"
  - "API server|authorises pods/exec|cp"
  - "kubelet|opens the session|env"
  - "Container|runs the command|ok"
@h Example
```python title="exec_logs.py" nocheck
from kubernetes import client, config
from kubernetes.stream import stream

config.load_kube_config()
v1 = client.CoreV1Api()

out = stream(
    v1.connect_get_namespaced_pod_exec, "web-6d5f7c9b8-abcde", "default",
    command=["cat", "/etc/os-release"], container="app",
    stderr=True, stdin=False, stdout=True, tty=False,
)
print(out)

print(v1.read_namespaced_pod_log("web-6d5f7c9b8-abcde", "default", container="app", tail_lines=20))
```
@check
Which RBAC resource authorises exec? || pods/exec with the create verb.
@end

@concept Tool: a cluster resource report
@plain
This tool sums CPU and memory requests per namespace and lists pods without requests or limits. It is read only and runs from a laptop or as a CronJob.
@problem
Capacity planning and cost allocation need numbers per team. Pods without requests break scheduling and make numbers meaningless.
@does
- Parses quantities like `250m` and `128Mi` into numbers.
- Sums requests per namespace across all containers.
- Flags containers with no requests or limits.
- The summing logic is pure, so it is easy to test.
@diagram flow
caption: Report pipeline
nodes:
  - "List pods|paged|app"
  - "Parse quantities|m and Mi to numbers|info"
  - "Sum per namespace|requests|env"
  - "Table and flags|missing limits|ok"
@h The pure part runs offline
```python title="k8s_report.py" lab
from __future__ import annotations

from collections import defaultdict

CPU_SUFFIX = {"m": 0.001}
MEM_SUFFIX = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "K": 1000, "M": 1000**2, "G": 1000**3}


def cpu_cores(q: str | None) -> float:
    if not q:
        return 0.0
    return float(q[:-1]) * CPU_SUFFIX["m"] if q.endswith("m") else float(q)


def mem_bytes(q: str | None) -> int:
    if not q:
        return 0
    for suf in sorted(MEM_SUFFIX, key=len, reverse=True):
        if q.endswith(suf):
            return int(float(q[: -len(suf)]) * MEM_SUFFIX[suf])
    return int(q)


def summarise(pods: list[dict]) -> tuple[dict[str, dict[str, float]], list[str]]:
    totals: dict[str, dict[str, float]] = defaultdict(lambda: {"cpu": 0.0, "mem": 0.0, "pods": 0})
    missing: list[str] = []
    for p in pods:
        ns = p["namespace"]
        totals[ns]["pods"] += 1
        for c in p["containers"]:
            req = c.get("requests", {})
            totals[ns]["cpu"] += cpu_cores(req.get("cpu"))
            totals[ns]["mem"] += mem_bytes(req.get("memory"))
            if not req or not c.get("limits"):
                missing.append(f"{ns}/{p['name']}/{c['name']}")
    return dict(totals), missing


sample = [
    {"namespace": "shop", "name": "web-1", "containers": [
        {"name": "app", "requests": {"cpu": "250m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}}]},
    {"namespace": "shop", "name": "job-1", "containers": [{"name": "run"}]},
]
totals, missing = summarise(sample)
for ns, t in totals.items():
    print(f"{ns:10} pods={int(t['pods'])} cpu={t['cpu']:.2f} mem={t['mem'] / 1024**2:.0f}Mi")
print("missing:", missing)
```
```python title="Feeding it from a cluster" nocheck
from kubernetes import client, config

config.load_kube_config()
v1 = client.CoreV1Api()
pods = []
token = None
while True:
    r = v1.list_pod_for_all_namespaces(limit=500, _continue=token)
    for p in r.items:
        pods.append({
            "namespace": p.metadata.namespace, "name": p.metadata.name,
            "containers": [{"name": c.name,
                            "requests": (c.resources.requests or {}) if c.resources else {},
                            "limits": (c.resources.limits or {}) if c.resources else {}}
                           for c in p.spec.containers],
        })
    token = r.metadata._continue
    if not token:
        break
```
@check
Why keep summarise a pure function? || It needs no cluster, so tests and offline runs are trivial.
@end
