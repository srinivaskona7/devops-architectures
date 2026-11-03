---
title: Exporters and probing
minutes: 50
objectives:
  - Choose the right exporter for hosts, Kubernetes objects and containers
  - Configure the blackbox exporter for synthetic checks
  - Pull AWS metrics with the CloudWatch exporter or YACE and know the cost
---
Most software does not speak Prometheus. Exporters translate other systems into the `/metrics` format.

@concept What an exporter is
@plain
An exporter is a small program that reads the state of something (a kernel, a database, a cloud API) and serves it at `/metrics`.
@problem
You cannot add instrumentation to Linux, MySQL or a managed service, but you still need their numbers.
@does
- Run beside the thing (sidecar or DaemonSet) or as a standalone service that queries it remotely.
- Official and community exporters exist for most databases, message queues and hardware.
- Prefer exporters that expose few, useful metrics and are actively maintained.
@diagram flow
caption: Exporter as a translator
nodes:
  - "System|kernel, MySQL, Redis|ext"
  - "Exporter|reads and converts|app"
  - "/metrics|text format|info"
  - "Prometheus|scrapes|cp"
@end

@concept node_exporter
@plain
`node_exporter` exposes host metrics on port 9100: CPU, memory, disk, filesystem, network and load. On Kubernetes it runs as a DaemonSet with host access.
@problem
You need USE metrics for each machine.
@does
- Key metrics: `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`, `node_filesystem_avail_bytes`, `node_disk_io_time_seconds_total`, `node_network_receive_bytes_total`.
- Collectors can be enabled or disabled with flags such as `--collector.systemd`.
- The textfile collector reads `.prom` files, perfect for cron-job results.
@diagram cmp
caption: Common node metrics
cards:
  - {h: "CPU", kind: info, items: ["node_cpu_seconds_total by mode", "Idle gives utilization"]}
  - {h: "Memory", kind: ok, items: ["MemAvailable, not MemFree"]}
  - {h: "Disk", kind: warn, items: ["filesystem avail", "io_time for saturation"]}
@h Run it and query
```bash title="Try node_exporter" lab
docker run -d --name node --net=host --pid=host -v /:/host:ro,rslave \
  quay.io/prometheus/node-exporter:latest --path.rootfs=/host
curl -s localhost:9100/metrics | grep -E '^node_(load1|memory_MemAvailable_bytes)'
```
```promql title="Filesystem used percent" nocheck
100 * (1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}
        / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"})
```
@end

@concept kube-state-metrics
@plain
`kube-state-metrics` (KSM) listens to the Kubernetes API and turns object state into metrics: Deployments, Pods, Nodes, Jobs, PVCs.
@problem
cAdvisor tells you what a container uses; nothing tells you that a Deployment wants 5 replicas and has 3 until you ask the API.
@does
- Examples: `kube_deployment_status_replicas_available`, `kube_pod_status_phase`, `kube_node_status_condition`, `kube_pod_container_status_waiting_reason`.
- Does not measure resource use; that is cAdvisor and metrics-server.
- Labels of Kubernetes objects are exposed only if allowed in its configuration.
@diagram flow
caption: KSM reads the API, not the nodes
nodes:
  - "API server|object state|cp"
  - "kube-state-metrics|watch and convert|app"
  - "Prometheus|scrapes|cp"
@h Useful alerts
```promql title="Deployment health" nocheck
kube_deployment_spec_replicas != kube_deployment_status_replicas_available
sum by (namespace, pod, reason) (kube_pod_container_status_waiting_reason{reason=~"CrashLoopBackOff|ImagePullBackOff"}) > 0
kube_node_status_condition{condition="Ready",status="true"} == 0
```
@end

@concept cAdvisor and the kubelet
@plain
cAdvisor is built into the kubelet. It reports per-container CPU, memory, network and filesystem use at `/metrics/cadvisor`.
@problem
You need to know how much each pod really uses and whether limits are hit.
@does
- `container_cpu_usage_seconds_total` is a counter in CPU seconds; rate gives cores used.
- `container_memory_working_set_bytes` is the figure the OOM killer and kubelet eviction consider; use it, not `container_memory_usage_bytes`.
- Throttling: `container_cpu_cfs_throttled_periods_total`.
- Filter `container!=""` to skip pod-level cgroup aggregates.
@diagram flow
caption: Container metrics path
nodes:
  - "Container cgroup|kernel counters|env"
  - "cAdvisor in kubelet|port 10250 /metrics/cadvisor|app"
  - "Prometheus|HTTPS scrape with token|cp"
@h Requests versus use
```promql title="CPU use versus request" nocheck
sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{container!=""}[5m]))
  / sum by (namespace, pod) (kube_pod_container_resource_requests{resource="cpu"})
```
@end

@concept Blackbox exporter and synthetic monitoring
@plain
The blackbox exporter probes endpoints from the outside using HTTP, HTTPS, TCP, ICMP or DNS and reports success, latency and certificate expiry.
@problem
Internal metrics can be green while users cannot reach you because of DNS, an expired certificate or a broken load balancer.
@does
- Prometheus calls `/probe?target=URL&module=http_2xx`; the exporter runs the check.
- Key metrics: `probe_success`, `probe_duration_seconds`, `probe_http_status_code`, `probe_ssl_earliest_cert_expiry`.
- Run probes from several places (a second region) to separate your failure from a network failure.
@diagram seq
caption: A probe cycle
actors: ["Prometheus|scraper|cp", "Blackbox|exporter|app", "Website|target URL|ext"]
steps:
  - "0>1: /probe?target=site | req"
  - "1>2: HTTPS GET | tls"
  - "2>1: 200 and cert | resp"
  - "1>0: probe_success 1 | resp"
@h Configuration
```yaml title="blackbox.yml"
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      valid_status_codes: []
      method: GET
      follow_redirects: true
      fail_if_not_ssl: true
```
```yaml title="prometheus job for probes"
scrape_configs:
  - job_name: blackbox-http
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets: ["https://shop.example.com", "https://api.example.com/health"]
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox-exporter:9115
```
@end

@concept Alerting on probes and certificates
@plain
A probe is only useful with alerts on failure, slowness and approaching certificate expiry.
@problem
Expired certificates are a classic, fully preventable outage.
@does
- `probe_success == 0` for several minutes means the endpoint is down from the probe's view.
- Days left on a certificate: `(probe_ssl_earliest_cert_expiry - time()) / 86400`.
- Alert at 21 days as a ticket and 7 days as a page.
@diagram flow
caption: Certificate countdown
nodes:
  - "30 days|no action|ok"
  - "21 days|ticket|warn"
  - "7 days|page|bad"
@h Rules
```yaml title="rules/probes.yml"
groups:
  - name: probes
    rules:
      - alert: EndpointDown
        expr: probe_success{job="blackbox-http"} == 0
        for: 3m
        labels: {severity: page}
        annotations:
          summary: "{{ $labels.instance }} fails external checks"
      - alert: CertExpiresSoon
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 21
        for: 1h
        labels: {severity: ticket}
        annotations:
          summary: "Certificate for {{ $labels.instance }} expires in under 21 days"
```
@check
Why probe from outside the cluster? || An in-cluster probe cannot see failures of DNS, ingress or the internet path that users depend on.
@end

@concept AWS metrics via CloudWatch exporter or YACE
@plain
`cloudwatch_exporter` and `yet-another-cloudwatch-exporter` (YACE) call the CloudWatch API and republish the metrics for Prometheus.
@problem
RDS, ALB, SQS and other managed services only report to CloudWatch, but your alerts and dashboards live in Prometheus.
@does
- You choose namespaces, metrics, statistics and dimensions in config. Narrow lists keep API cost low.
- CloudWatch has a delay of 1 to 5 minutes, and `GetMetricData` requests are billed, so scrape every 5 minutes, not every 15 seconds.
- Alternative: CloudWatch Metric Streams to Firehose give lower latency at a different cost; check current pricing.
- Authenticate with IRSA (IAM role for the service account) and grant read-only CloudWatch permissions.
@diagram flow
caption: Bringing CloudWatch into Prometheus
nodes:
  - "RDS, ALB, SQS|publish to CloudWatch|ext"
  - "YACE exporter|GetMetricData with IRSA|app"
  - "Prometheus|scrape every 5 minutes|cp"
@h YACE config sketch
```yaml title="yace-config.yml" nocheck
apiVersion: v1alpha1
discovery:
  exportedTagsOnMetrics:
    AWS/RDS: [Environment]
  jobs:
    - type: AWS/RDS
      regions: [ap-south-1]
      period: 300
      length: 300
      metrics:
        - name: CPUUtilization
          statistics: [Average]
        - name: FreeStorageSpace
          statistics: [Minimum]
```
:::note
The configuration schema changes between releases. Check the current YACE documentation for your version.
:::
@end
