---
title: Service discovery and relabeling
minutes: 45
objectives:
  - Explain why static target lists fail in dynamic environments
  - Configure Kubernetes and EC2 service discovery
  - Use relabeling to filter targets and shape labels safely
---
In Kubernetes and autoscaling groups, targets appear and vanish constantly. Prometheus finds them by asking the platform, then relabeling rules decide which to scrape and what labels they get.

@concept Why service discovery
@plain
Service discovery (SD) lets Prometheus ask Kubernetes, AWS, Consul or DNS for the current list of targets instead of reading a hand-edited file.
@problem
Pods are replaced every deploy. A static list is wrong within minutes and someone must edit it.
@does
- SD mechanisms refresh the target list continuously.
- Each discovered target arrives with metadata labels that start with `__meta_`.
- Relabeling turns this metadata into the final labels.
@diagram flow
caption: From platform API to scraped target
nodes:
  - "Platform API|Kubernetes, EC2, Consul|ext"
  - "SD plugin|lists targets with __meta labels|cp"
  - "Relabeling|keep, drop, rename|warn"
  - "Scrape|final targets|ok"
@end

@concept Kubernetes service discovery
@plain
`kubernetes_sd_configs` has roles: `node`, `pod`, `service`, `endpoints`, `endpointslice` and `ingress`. Each role yields targets of that object type.
@problem
You want every pod that opts in to be scraped without touching Prometheus config.
@does
- `pod` creates one target per container port, with labels such as `__meta_kubernetes_pod_name` and `__meta_kubernetes_namespace`.
- `endpoints` and `endpointslice` follow Services and keep pod and service labels.
- The Prometheus service account needs RBAC `get, list, watch` on those resources.
@diagram cmp
caption: Which role to use
cards:
  - {h: "node", kind: info, items: ["kubelet and cAdvisor", "node exporters"]}
  - {h: "pod", kind: app, items: ["Annotation based scraping", "Works without a Service"]}
  - {h: "endpointslice", kind: ok, items: ["Targets behind a Service", "Carries service labels"]}
  - {h: "ingress/service", kind: warn, items: ["Blackbox probing", "Not for metrics scraping"]}
@h Annotation based pod scraping
```yaml title="prometheus.yml pod job"
scrape_configs:
  - job_name: kubernetes-pods
    kubernetes_sd_configs:
      - role: pod
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: "true"
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_path]
        action: replace
        target_label: __metrics_path__
        regex: (.+)
      - source_labels: [__address__, __meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2
        target_label: __address__
      - source_labels: [__meta_kubernetes_namespace]
        target_label: namespace
      - source_labels: [__meta_kubernetes_pod_name]
        target_label: pod
```
:::note
The `prometheus.io/scrape` annotations are a convention of the config above, not a built-in feature. With the Prometheus Operator you use ServiceMonitor and PodMonitor instead.
:::
@end

@concept How relabeling works
@plain
A relabel rule reads a few labels, joins their values with a separator, tests the result against a regular expression, then applies an **action**.
@problem
Discovery gives you many targets and noisy metadata. You need to choose what to scrape and build clean, consistent labels.
@does
- `relabel_configs` run before the scrape, on target labels.
- `metric_relabel_configs` run after the scrape, on each sample.
- The regex is fully anchored. Default `regex` is `(.*)`, default `separator` is `;`.
- Labels starting with `__` are dropped after relabeling.
@diagram flow
caption: Two relabeling stages
nodes:
  - "Discovered target|__meta labels|ext"
  - "relabel_configs|choose target and labels|warn"
  - "Scrape|samples received|app"
  - "metric_relabel_configs|filter samples|warn"
  - "TSDB|stored|ok"
@end

@concept Relabel actions
@plain
The `action` field decides what happens when a rule matches. The common ones are `keep`, `drop`, `replace`, `labelmap`, `labeldrop` and `labelkeep`.
@problem
Without actions you could not remove a target, rename a label or strip a high-cardinality one.
@does
- `keep` and `drop` filter targets or series by regex.
- `replace` writes a new value into `target_label` using capture groups.
- `labelmap` copies labels whose names match a regex, for example all pod labels.
- `labeldrop` and `labelkeep` remove or retain labels by name.
- Newer versions add more actions such as `keepequal`, `lowercase`; check the current docs.
@diagram cmp
caption: Targets versus samples
cards:
  - {h: "Target level", kind: info, items: ["keep or drop a pod", "Set job and namespace", "Change __address__"]}
  - {h: "Sample level", kind: warn, items: ["Drop go_* metrics", "Remove a label", "Rename metric"]}
@end

@concept Dropping noisy metrics
@plain
`metric_relabel_configs` can discard series you never use before they hit disk.
@problem
Some exporters emit thousands of series. Storing them costs memory and money and slows queries.
@does
- Drop whole metrics by name using `__name__`.
- Drop a label that has too many values, but make sure series stay unique afterwards.
- Always measure first: `topk(10, count by (__name__)({__name__=~".+"}))`.
@diagram flow
caption: Find, decide, drop
nodes:
  - "Find top series|by metric name|info"
  - "Decide|is it used in a rule or panel|warn"
  - "Drop|metric_relabel_configs|ok"
@h Example
```yaml title="Dropping unused series"
scrape_configs:
  - job_name: kubelet-cadvisor
    metrics_path: /metrics/cadvisor
    scheme: https
    kubernetes_sd_configs:
      - role: node
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: container_(tasks_state|memory_failures_total|blkio_.*)
        action: drop
      - regex: id|name
        action: labeldrop
```
:::warn
Dropping a label can merge two series into one with the same labels and cause duplicate sample errors. Test with a small change first.
:::
@end

@concept AWS EC2 and file based discovery
@plain
`ec2_sd_configs` lists EC2 instances through the AWS API; `file_sd_configs` reads JSON or YAML files that another tool writes.
@problem
Not everything runs in Kubernetes. VMs in an Auto Scaling group must be found automatically.
@does
- EC2 SD needs IAM permission `ec2:DescribeInstances` (use an instance role or IRSA).
- Instance tags become `__meta_ec2_tag_<name>` labels, ideal for `keep` rules.
- `file_sd_configs` is the universal adapter: any script can write targets to a file and Prometheus reloads it on change.
@diagram flow
caption: EC2 discovery with tag filter
nodes:
  - "EC2 API|DescribeInstances|ext"
  - "Tag filter|monitor=true|warn"
  - "Targets|port 9100|ok"
@h Example
```yaml title="EC2 and file discovery"
scrape_configs:
  - job_name: ec2-node
    ec2_sd_configs:
      - region: ap-south-1
        port: 9100
        filters:
          - name: tag:monitor
            values: ["true"]
    relabel_configs:
      - source_labels: [__meta_ec2_tag_Name]
        target_label: instance_name
  - job_name: custom
    file_sd_configs:
      - files: ["/etc/prometheus/targets/*.yml"]
        refresh_interval: 1m
```
```yaml title="/etc/prometheus/targets/db.yml"
- targets: ["db1.internal:9187", "db2.internal:9187"]
  labels:
    env: prod
    team: data
```
@end

@concept External labels and target labels
@plain
**Target labels** describe where a series came from. **External labels** are set globally and added when data leaves the server (federation, remote write, alerts).
@problem
With many clusters sending data to one place, series from different clusters must not collide.
@does
- Set `external_labels: {cluster: prod-eu, replica: a}` in `global`.
- Thanos and Mimir use these to identify the source and to deduplicate HA replicas.
- Keep label names stable: renaming later breaks dashboards.
@diagram flow
caption: External labels travel with exported data
nodes:
  - "Cluster A|cluster=a|app"
  - "Cluster B|cluster=b|app"
  - "Central store|distinguishes by cluster|cp"
@h Example
```yaml title="global block"
global:
  scrape_interval: 30s
  external_labels:
    cluster: prod-mumbai
    replica: "0"
```
@check
Do external labels appear in the local TSDB series? || No. They are attached only to alerts, remote write, federation and similar outbound paths.
@end

@concept Debugging targets
@plain
The Prometheus UI pages `Status > Targets` and `Status > Service Discovery` show what was found, what was dropped and why.
@problem
A missing target usually means a relabel rule dropped it or RBAC blocked discovery. Guessing is slow.
@does
- Service Discovery shows discovered labels before relabeling and the post-relabel result.
- Targets shows last error, last scrape time and duration.
- `promtool check config` finds syntax errors before reload.
@diagram flow
caption: Missing target checklist
numbered: true
nodes:
  - "In Service Discovery?|no means RBAC or selector|info"
  - "Dropped by relabel?|check keep rules|warn"
  - "Scrape error?|port, path, TLS, auth|bad"
  - "Healthy|up is 1|ok"
@h Commands
```bash title="Debug from the CLI" lab
curl -s localhost:9090/api/v1/targets?state=dropped | head -c 600
curl -s 'localhost:9090/api/v1/query?query=up' | head -c 300
kubectl auth can-i list pods --as=system:serviceaccount:monitoring:prometheus -A
```
@end
