---
title: Observability signals in Kubernetes
minutes: 45
objectives:
  - Read status, conditions and events to learn why an object is unhealthy
  - Use metrics-server and kubectl top and know what they do not show
  - Collect container logs and know the logging architecture options
---
Troubleshooting starts with signals the cluster already produces. This section covers where Kubernetes records state, events, resource usage and logs before you add any extra tooling.

@concept Status, conditions and describe
@plain
Every object has a `spec` (what you asked for) and a `status` (what the controller observed). Conditions are named true or false facts inside status, such as `Ready` or `PodScheduled`, each with a reason and message.
@problem
"It does not work" is not actionable. You need the controller's own explanation, which is almost always written into status.
@does
- `kubectl describe` shows status, conditions and the related events in one view.
- `kubectl get -o yaml` shows the raw status, including `containerStatuses` with `lastState` (why the previous container died).
- `kubectl get -o jsonpath` or `custom-columns` extracts one field across many objects.
- `kubectl wait --for=condition=Ready` blocks until a condition is met, useful in scripts.
@diagram flow
caption: From desired to observed state
nodes:
  - "spec|what you asked|env"
  - "Controller|reconcile loop|cp"
  - "status.conditions|what is true now|info"
  - "describe and events|human readable|ok"
@h Reading status
```bash title="Where to look first" lab
kubectl describe pod api-7d9f8c-x2k4p -n shop | sed -n '/Conditions/,$p'
kubectl get pod api-7d9f8c-x2k4p -n shop -o jsonpath='{.status.containerStatuses[0].lastState}{"\n"}'
kubectl get pods -n shop -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,NODE:.spec.nodeName,RESTARTS:.status.containerStatuses[0].restartCount
kubectl wait --for=condition=Ready pod -l app=api -n shop --timeout=120s
```
@check
Where do you find why the previous container instance died? || In status.containerStatuses[].lastState.terminated, which shows reason, exit code and timestamps.
@end

@concept Events
@plain
Events are short records created by the scheduler, kubelet and controllers: "Scheduled", "Pulling image", "FailedMount", "BackOff". They explain what happened to an object.
@problem
Status says the state, but not the sequence. A Pod that is Pending was refused for a specific reason, and that reason is only in an event.
@does
- Events are namespaced objects with a **short retention, about one hour by default**. Look early or ship them to storage.
- `kubectl events` (stable since 1.26) sorts and filters better than `kubectl get events`.
- Types are `Normal` and `Warning`. Filter on warnings first.
- Tools such as the kubernetes-event-exporter forward events to logs or alerting.
@diagram seq
caption: Who writes events about a Pod
actors: ["Scheduler|kube-scheduler|cp", "Kubelet|on the node|app", "API server|stores events|cp"]
steps:
  - "0>2: Scheduled to node-3 | req"
  - "1>2: Pulling image | req"
  - "1>2: Failed to pull image | bad"
  - "1>2: Back-off pulling image | bad"
  - "note 2..2: kept about one hour"
@h Querying events
```bash title="Events that matter" lab
kubectl events -n shop --types=Warning                       # warnings only
kubectl events -n shop --for pod/api-7d9f8c-x2k4p            # one object
kubectl events -A --types=Warning --watch                    # live view across the cluster
kubectl get events -n shop --sort-by=.lastTimestamp | tail -20
```
@end

@concept metrics-server and kubectl top
@plain
**metrics-server** is a small add-on that collects current CPU and memory use from each kubelet and exposes it through the Metrics API. `kubectl top` and the HorizontalPodAutoscaler read it.
@problem
You need a quick answer to "which Pod or node is using the most CPU or memory right now" without installing a full monitoring stack.
@does
- Provides only the latest sample (about 15 to 60 seconds old), not history. For history use Prometheus.
- Memory shown is the **working set**, which is what the kernel considers for OOM kills.
- Required for HPA on CPU and memory. EKS does not install it by default; Gardener-managed clusters such as Kyma commonly provide it.
- If `kubectl top` says "Metrics API not available", check the metrics-server Deployment and the APIService.
@diagram flow
caption: Path of a metric to kubectl top
nodes:
  - "Kubelet|cAdvisor stats|app"
  - "metrics-server|scrapes every node|info"
  - "Metrics API|metrics.k8s.io|cp"
  - "kubectl top and HPA|consumers|ok"
@h Commands
```bash title="Resource usage now" lab
kubectl top nodes
kubectl top pods -n shop --sort-by=memory
kubectl top pod api-7d9f8c-x2k4p -n shop --containers
kubectl get apiservice v1beta1.metrics.k8s.io           # Available must be True
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes | head -c 400
```
@end

@concept Container logs
@plain
Containers write to standard output and standard error. The container runtime stores those streams as files on the node, and `kubectl logs` reads them through the kubelet.
@problem
When a Pod misbehaves you need its output, including from the instance that just crashed, without logging into the node.
@does
- `kubectl logs POD -c CONTAINER` reads the current instance, `--previous` reads the last terminated one, `-f` follows, `--since=10m` and `--tail=100` limit output.
- `-l app=api --all-containers --prefix` reads many Pods at once; add `--max-log-requests` if you exceed the default of 5.
- The kubelet rotates files (`containerLogMaxSize` 10Mi and `containerLogMaxFiles` 5 by default), so old logs vanish with the Pod or the node.
- Logs of a deleted Pod are gone unless a collector shipped them.
@diagram flow
caption: How a log line travels
nodes:
  - "App writes stdout|JSON lines|app"
  - "Runtime file|/var/log/pods|plain"
  - "kubectl logs|via kubelet|info"
  - "Log agent|ships off node|ok"
@h Commands
```bash title="Reading logs" lab
kubectl logs deploy/api -n shop --tail=100
kubectl logs api-7d9f8c-x2k4p -n shop --previous            # the crashed instance
kubectl logs -l app=api -n shop --all-containers --prefix --since=15m --max-log-requests=10
kubectl logs api-7d9f8c-x2k4p -n shop -c istio-proxy        # a sidecar
```
@check
Why does kubectl logs --previous matter for CrashLoopBackOff? || The current container may have just restarted and be empty; the useful error is in the previous instance.
@end

@concept Cluster-level logging architecture
@plain
Kubernetes itself does not store logs long term. A **log agent** runs on every node as a DaemonSet, reads the container log files, adds Pod labels and sends them to a backend.
@problem
Pods are disposable. When one is evicted or a node is replaced, its logs disappear exactly when you need them.
@does
- Node agents: Fluent Bit, Vector, Promtail or Grafana Alloy, Filebeat. A DaemonSet needs only read access to `/var/log`.
- Backends: Loki, Elasticsearch or OpenSearch, CloudWatch Logs (EKS with Fluent Bit or the CloudWatch Observability add-on), SAP Cloud Logging on BTP.
- Emit structured JSON logs with a request ID; metadata enrichment adds namespace, Pod and labels.
- Sidecar log agents are only needed when an app writes to files instead of stdout.
@diagram layers
caption: Node agent logging pipeline
layers:
  - {label: "Nodes", nodes: ["Pods|stdout and stderr|app", "Log agent DaemonSet|reads files, adds labels|info"]}
  - {label: "Transport", nodes: ["Buffer and retry|backpressure|warn"]}
  - {label: "Backend", nodes: ["Loki or OpenSearch|searchable|db", "Dashboards and alerts|Grafana or Kibana|ok"]}
@h A Fluent Bit DaemonSet skeleton
```yaml title="log-agent.yaml"
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: log-agent
  namespace: logging
spec:
  selector:
    matchLabels:
      app: log-agent
  template:
    metadata:
      labels:
        app: log-agent
    spec:
      serviceAccountName: log-agent
      tolerations:
        - operator: Exists
      containers:
        - name: fluent-bit
          image: cr.fluentbit.io/fluent/fluent-bit:3.1
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {memory: 128Mi}
          volumeMounts:
            - name: varlog
              mountPath: /var/log
              readOnly: true
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
```
@end

@concept Metrics and the Prometheus model
@plain
Prometheus pulls numeric time series from HTTP endpoints. In Kubernetes it discovers targets through the API, so new Pods are scraped automatically.
@problem
`kubectl top` shows now. Capacity planning, alerting and finding a slow leak need history.
@does
- Core sources: **kubelet and cAdvisor** (container CPU and memory), **kube-state-metrics** (object state such as restarts and Pod phase), node-exporter (host), and your own `/metrics`.
- The Prometheus Operator adds `ServiceMonitor` and `PodMonitor` CRDs that declare what to scrape. `kube-prometheus-stack` bundles all of this.
- Useful signals: `container_memory_working_set_bytes`, `kube_pod_container_status_restarts_total`, `kube_pod_status_phase`, `container_cpu_cfs_throttled_periods_total`.
- Managed options: Amazon Managed Service for Prometheus, Container Insights, SAP Cloud Logging and Dynatrace on BTP.
@diagram flow
caption: From Pod to alert
nodes:
  - "Targets|kubelet, kube-state-metrics, apps|app"
  - "Prometheus|scrape and store|db"
  - "Alertmanager|route and group|warn"
  - "Grafana|dashboards|ok"
@h Declaring a scrape
```yaml title="servicemonitor.yaml"
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: api
  namespace: shop
  labels:
    release: kube-prometheus-stack
spec:
  selector:
    matchLabels:
      app: api
  endpoints:
    - port: http
      path: /metrics
      interval: 30s
```
:::note
The `release` label must match what your Prometheus selects. A ServiceMonitor that never appears in targets is usually a label mismatch.
:::
@end

@concept Probes, API health and control plane signals
@plain
Readiness, liveness and startup probes tell the kubelet about application health. Separately, the API server exposes `/readyz` and `/livez`, and control plane components expose metrics.
@problem
A running process is not necessarily working. Traffic should only reach Pods that are ready, and hung processes should be restarted.
@does
- A failing **readiness** probe removes the Pod from Service endpoints without restarting it. A failing **liveness** probe restarts the container. **Startup** probe delays the other two for slow starters.
- Probe failures appear as events (`Unhealthy`) and show in `describe`.
- `kubectl get --raw='/readyz?verbose'` lists API server checks.
- On managed control planes (EKS, Gardener) you cannot reach the scheduler or controller manager directly; use the provider's control plane logging and API server metrics.
@diagram cmp
caption: Probe effects
cards:
  - {h: "Startup", kind: info, items: ["Runs first", "Holds off other probes", "Protects slow starts"]}
  - {h: "Readiness", kind: ok, items: ["Fails: removed from Service", "No restart"]}
  - {h: "Liveness", kind: warn, items: ["Fails: container restarted", "Keep it simple"]}
@h Commands
```bash title="Health endpoints" lab
kubectl get --raw='/readyz?verbose' | tail -15
kubectl get --raw='/livez'
kubectl get endpoints api -n shop -o wide            # only ready Pods are listed
kubectl get endpointslices -n shop -l kubernetes.io/service-name=api
```
@check
A Pod is Running but receives no traffic. Which probe is likely failing? || The readiness probe; the Pod is removed from the Service endpoints.
@end
