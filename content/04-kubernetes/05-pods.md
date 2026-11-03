---
title: Pods, containers and lifecycle
minutes: 50
objectives:
  - Write a complete Pod spec with init containers and sidecars
  - Trace a Pod from Pending to Terminated and explain graceful shutdown
  - Configure liveness, readiness and startup probes without causing outages
---
The Pod is the smallest unit you deploy. Almost every production incident involves a Pod that did not start, did not become ready, or did not stop cleanly.

@concept What a Pod is
@plain
A Pod is one or more containers that share a network identity (one IP), storage volumes and a lifecycle. They are scheduled together onto one node.
@problem
Some processes must run side by side, such as an app and a log shipper or proxy, sharing localhost and files. A Pod groups them as one unit.
@does
- Containers in a Pod share the network namespace, so they reach each other on `localhost` and must use different ports.
- They can share volumes, and optionally the process namespace (`shareProcessNamespace`).
- A Pod is ephemeral and never moves. When a node dies the Pod is replaced by a new one with a new name and IP.
- You rarely create bare Pods. A controller (Deployment, StatefulSet, Job) owns them.
@diagram layers
caption: Inside one Pod
layers:
  - {label: "Pod", nodes: ["app container|your code|app", "sidecar|proxy or log shipper|info", "init container|runs first|env"]}
  - {label: "Shared", nodes: ["network namespace|one IP|ok", "volumes|emptyDir, PVC, config|ok"]}
@h A complete Pod
```yaml title="pod.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: web
  labels:
    app.kubernetes.io/name: web
spec:
  containers:
    - name: app
      image: nginx:1.27
      ports:
        - containerPort: 80
      resources:
        requests: {cpu: 100m, memory: 128Mi}
        limits: {memory: 256Mi}
      volumeMounts:
        - {name: cache, mountPath: /var/cache/nginx}
  volumes:
    - name: cache
      emptyDir: {}
```
@end

@concept Init containers and sidecars
@plain
Init containers run one after another to completion before the app starts. Native sidecars are init containers marked `restartPolicy: Always` that keep running beside the app.
@problem
Apps often need setup first, such as waiting for a database, fetching config or running a migration. Mixed into the app image, that setup bloats it and cannot be reused.
@does
- Init containers run in order; if one fails the Pod restarts it (per restartPolicy) and the app never starts.
- A native sidecar (stable since 1.33) starts before the app, stays running, and is stopped after the app on shutdown. This fixes Job Pods that never finished because a sidecar kept running.
- Both have their own images, so tools like `curl` or `psql` stay out of the app image.
@diagram flow
caption: Start order in a Pod
numbered: true
nodes:
  - "init: migrate|runs to completion|env"
  - "sidecar: proxy|starts and keeps running|info"
  - "app|starts after both|app"
  - "Ready|all containers ready|ok"
@h Init container and sidecar
```yaml title="init-sidecar.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: api
spec:
  initContainers:
    - name: wait-db
      image: busybox:1.36
      command: ["sh", "-c", "until nc -z db 5432; do sleep 2; done"]
    - name: log-shipper
      image: fluent/fluent-bit:3.1
      restartPolicy: Always
  containers:
    - name: app
      image: ghcr.io/example/api:1.4.2
```
:::note
Native sidecars need Kubernetes 1.29 or later (beta, on by default) and are stable in 1.33. Check your Kyma or EKS version.
:::
@end

@concept Pod phases and container states
@plain
A Pod has a **phase** (Pending, Running, Succeeded, Failed, Unknown) and each container has a **state** (Waiting, Running, Terminated) with a reason.
@problem
`kubectl get pods` shows one word. Fixing a problem needs the reason underneath, such as ImagePullBackOff or OOMKilled.
@does
- **Pending**: accepted but not running; unscheduled, pulling images, or waiting for volumes.
- **Running**: bound to a node and at least one container is running or starting.
- **Succeeded or Failed**: all containers ended; typical for Jobs.
- Common waiting reasons: `ContainerCreating`, `ImagePullBackOff`, `CrashLoopBackOff`, `CreateContainerConfigError`.
- `Terminated` reasons include `Completed`, `Error` and `OOMKilled` (exit code 137 means SIGKILL).
@diagram flow
caption: Typical life of a Pod
nodes:
  - "Pending|schedule, pull, mount|warn"
  - "Running|containers started|ok"
  - "Terminating|SIGTERM sent|warn"
  - "Succeeded or Failed|ended|plain"
@h Find the real reason
```bash title="Why is the Pod not healthy" lab
kubectl get pod web -o jsonpath='{.status.phase}{"\n"}'
kubectl get pod web -o jsonpath='{range .status.containerStatuses[*]}{.name}{" "}{.state}{" last="}{.lastState}{"\n"}{end}'
kubectl describe pod web | sed -n '/Events/,$p'
kubectl logs web --previous            # logs of the crashed instance
```
@check
Exit code 137 means what? || The process was killed by SIGKILL, most often by the OOM killer (check for reason OOMKilled) or after the grace period ended.
@end

@concept Probes
@plain
Probes are health checks the kubelet runs against a container. **Startup** says it has booted, **readiness** says it can take traffic, **liveness** says it is not stuck.
@problem
A running process is not always a working one. Without probes, Kubernetes would send traffic to an app still warming up, or leave a deadlocked process running forever.
@does
- **Readiness** failure removes the Pod from Service endpoints but does not restart it.
- **Liveness** failure restarts the container. Keep it cheap and independent of dependencies.
- **Startup** disables the other two until it passes, which suits slow starting apps without a long `initialDelaySeconds`.
- Mechanisms: `httpGet`, `tcpSocket`, `exec` and `grpc`.
@diagram cmp
caption: Which probe for which question
cards:
  - {h: "Startup", kind: info, items: ["Has it finished booting", "Failure restarts the container", "Guards the other probes"]}
  - {h: "Readiness", kind: ok, items: ["Can it serve now", "Failure drops it from the Service", "May check dependencies"]}
  - {h: "Liveness", kind: warn, items: ["Is the process deadlocked", "Failure restarts the container", "Never check the database here"]}
@h Three probes together
```yaml title="probes.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: api
spec:
  containers:
    - name: app
      image: ghcr.io/example/api:1.4.2
      ports:
        - {name: http, containerPort: 8080}
      startupProbe:
        httpGet: {path: /healthz, port: http}
        periodSeconds: 5
        failureThreshold: 30
      readinessProbe:
        httpGet: {path: /ready, port: http}
        periodSeconds: 5
        failureThreshold: 3
      livenessProbe:
        httpGet: {path: /healthz, port: http}
        periodSeconds: 10
        timeoutSeconds: 2
        failureThreshold: 3
```
:::danger
A liveness probe that calls the database turns a database blip into a restart storm of every Pod. Liveness checks only the process itself.
:::
@check
The app needs 90 seconds to start. Which probe handles that? || A startup probe, for example periodSeconds 5 with failureThreshold 30 allows 150 seconds before liveness takes over.
@end

@concept Graceful termination
@plain
When a Pod is deleted, Kubernetes sends SIGTERM, waits up to `terminationGracePeriodSeconds` (default 30), then sends SIGKILL.
@problem
Dropping a Pod in the middle of requests causes errors during every rollout and scale-down.
@does
- Deletion sets `deletionTimestamp`. Two things happen in parallel: the Pod is removed from endpoints, and the kubelet runs the `preStop` hook then sends SIGTERM.
- Endpoint removal and SIGTERM race, so load balancers may still send traffic for a moment. A short `preStop` sleep covers that.
- The app should stop accepting new connections, finish in-flight work and exit before the grace period ends.
- PID 1 must forward or handle SIGTERM, otherwise the app is killed only at the deadline.
@diagram seq
caption: Deleting a Pod
actors: ["API server|cp|cp", "kubelet|node|app", "Endpoints|Service|info", "Container|app|ok"]
steps:
  - "0>1: delete, deletionTimestamp | req"
  - "0>2: remove Pod from endpoints | req"
  - "1>3: preStop hook | req"
  - "1>3: SIGTERM | req"
  - "note 3..3: drain and exit"
  - "1>3: SIGKILL after grace period | bad"
@h Drain-friendly container
```yaml title="graceful.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: web
spec:
  terminationGracePeriodSeconds: 45
  containers:
    - name: app
      image: nginx:1.27
      lifecycle:
        preStop:
          sleep:
            seconds: 10
```
@end

@concept Restart policy, CrashLoopBackOff and image pulls
@plain
`restartPolicy` decides what the kubelet does when a container exits. Repeated failures cause growing waits, shown as `CrashLoopBackOff`.
@problem
A broken container must not hammer the node, but a transient crash should recover on its own.
@does
- `Always` (default for Deployments), `OnFailure` and `Never` (used by Jobs).
- Backoff starts at 10 s and doubles to a 5 minute maximum, reset after 10 minutes of success.
- `ImagePullBackOff` comes from a wrong tag, missing registry credentials (`imagePullSecrets`) or rate limits.
- `imagePullPolicy` defaults to `IfNotPresent`, or `Always` when the tag is `latest` or missing. Prefer immutable tags or digests.
@diagram flow
caption: Debugging a crash loop
numbered: true
nodes:
  - "Pod restarts|CrashLoopBackOff|bad"
  - "logs --previous|read the last words|info"
  - "describe|exit code and reason|info"
  - "Fix cause|config, memory, probe|ok"
@h Debug helpers
```bash title="Ephemeral debug container" lab
kubectl logs web -c app --previous
kubectl debug -it web --image=busybox:1.36 --target=app    # shares the app process namespace
kubectl debug node/worker-1 -it --image=busybox:1.36        # shell on a node
kubectl get events --field-selector involvedObject.name=web
```
@end
