---
title: kube-prometheus-stack and the Prometheus Operator
minutes: 55
objectives:
  - Explain what the Operator and its custom resources do
  - Write a ServiceMonitor, PodMonitor and PrometheusRule
  - Install and tune the Helm chart for a production cluster
---
On Kubernetes you rarely edit prometheus.yml. You declare monitoring with custom resources and an operator turns them into configuration.

@concept What kube-prometheus-stack contains
@plain
`kube-prometheus-stack` is a Helm chart that installs the Prometheus Operator, a Prometheus, Alertmanager, Grafana, node-exporter, kube-state-metrics, and a large set of default dashboards and alert rules for Kubernetes.
@problem
Assembling all these parts and the Kubernetes-specific scrape jobs by hand takes days and is easy to get wrong.
@does
- One `helm install` gives a working cluster monitoring setup.
- Default rules cover node pressure, pod crash loops, API server health, etcd, and more (from the kubernetes-mixin project).
- Everything is configured through Helm values and custom resources.
@diagram layers
caption: Pieces of the chart
layers:
  - {label: "Control", nodes: ["Prometheus Operator|reconciles CRDs|cp"]}
  - {label: "Workloads", nodes: ["Prometheus|StatefulSet|app", "Alertmanager|StatefulSet|app", "Grafana|Deployment|app"]}
  - {label: "Exporters", nodes: ["node-exporter|DaemonSet|env", "kube-state-metrics|Deployment|env"]}
@h Install
```bash title="Install with Helm" lab
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
helm upgrade --install kps prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace -f values.yaml
kubectl -n monitoring get pods
```
@end

@concept The Operator pattern
@plain
The Operator is a controller. It watches custom resources such as `Prometheus`, `ServiceMonitor` and `PrometheusRule`, and generates the real Prometheus config, Secrets and StatefulSets.
@problem
Changing a scrape target should be a normal Kubernetes change reviewed in Git, not an SSH session.
@does
- `Prometheus` and `Alertmanager` CRDs describe the servers (replicas, retention, storage).
- `ServiceMonitor`, `PodMonitor`, `Probe` and `ScrapeConfig` describe what to scrape.
- `PrometheusRule` holds recording and alert rules; `AlertmanagerConfig` holds routing for teams.
- A config reloader sidecar applies changes without a restart.
@diagram flow
caption: CRDs to running config
nodes:
  - "ServiceMonitor, PrometheusRule|in any namespace|ext"
  - "Operator|watches and renders|cp"
  - "Secret with config|prometheus.yaml.gz|env"
  - "Prometheus pod|reloaded|ok"
@end

@concept ServiceMonitor
@plain
A ServiceMonitor tells Prometheus to scrape the endpoints behind Kubernetes Services that match a label selector.
@problem
Each team needs to publish its own metrics endpoint without editing central Prometheus config.
@does
- `selector.matchLabels` chooses Services; `namespaceSelector` chooses namespaces.
- `endpoints[].port` is the **name** of the Service port, not the number.
- Prometheus selects ServiceMonitors by its own `serviceMonitorSelector`. In the chart the default requires the label `release` set to the Helm release name. Setting `serviceMonitorSelectorNilUsesHelmValues: false` selects all.
@diagram flow
caption: ServiceMonitor finds targets
nodes:
  - "ServiceMonitor|selector app=checkout|app"
  - "Service|port named metrics|env"
  - "Endpoints|pod IPs|info"
  - "Prometheus|scrapes each pod|cp"
@h Example
```yaml title="servicemonitor.yaml"
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: checkout
  namespace: shop
  labels:
    release: kps
spec:
  selector:
    matchLabels:
      app: checkout
  namespaceSelector:
    matchNames: [shop]
  endpoints:
    - port: metrics
      path: /metrics
      interval: 30s
      scrapeTimeout: 10s
---
apiVersion: v1
kind: Service
metadata:
  name: checkout
  namespace: shop
  labels:
    app: checkout
spec:
  selector:
    app: checkout
  ports:
    - name: metrics
      port: 8000
      targetPort: 8000
```
@check
Target missing though the ServiceMonitor exists, first two checks? || The release label matches the Prometheus selector, and the Service port name matches the endpoint port.
@end

@concept PodMonitor
@plain
A PodMonitor scrapes pods directly by label, without needing a Service.
@problem
Some workloads (DaemonSets, batch pods, sidecars) have no Service.
@does
- Uses `selector` on pod labels and `podMetricsEndpoints[].port` with a container port name.
- Otherwise behaves like a ServiceMonitor.
- Good for Envoy sidecars or exporters running as DaemonSets.
@diagram cmp
caption: ServiceMonitor or PodMonitor
cards:
  - {h: "ServiceMonitor", kind: info, items: ["Needs a Service", "Follows Endpoints", "Most application cases"]}
  - {h: "PodMonitor", kind: ok, items: ["Pods by label", "No Service needed", "DaemonSets and sidecars"]}
@h Example
```yaml title="podmonitor.yaml"
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: envoy-sidecars
  namespace: shop
  labels:
    release: kps
spec:
  selector:
    matchLabels:
      sidecar: envoy
  podMetricsEndpoints:
    - port: envoy-admin
      path: /stats/prometheus
      interval: 30s
```
@end

@concept PrometheusRule
@plain
A PrometheusRule holds the same groups of recording and alert rules as a rules file, but as a Kubernetes object.
@problem
Rules in a ConfigMap mounted by hand are easy to break; the Operator validates CRD rules.
@does
- Put the rule next to the application it protects and deploy with the same Helm chart.
- Prometheus picks it up via `ruleSelector` (the chart default again uses the `release` label).
- Check status: `kubectl get prometheusrule -A` and the Prometheus UI Rules page.
@diagram flow
caption: Rules ship with the app
nodes:
  - "App Helm chart|includes PrometheusRule|app"
  - "Operator|validates and mounts|cp"
  - "Prometheus|evaluates|ok"
@h Example
```yaml title="prometheusrule.yaml"
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: checkout-alerts
  namespace: shop
  labels:
    release: kps
spec:
  groups:
    - name: checkout
      rules:
        - alert: CheckoutHighErrorRatio
          expr: |
            sum(rate(http_requests_total{service="checkout",code=~"5.."}[5m]))
              / sum(rate(http_requests_total{service="checkout"}[5m])) > 0.05
          for: 10m
          labels:
            severity: page
            team: payments
          annotations:
            summary: Checkout error ratio above 5 percent
            runbook_url: https://runbooks.example.com/high-error-ratio
```
@end

@concept Helm values worth setting
@plain
The default values give a demo. For production set storage, retention, resources, replicas and selectors.
@problem
Without persistent volumes, a Prometheus pod restart loses all history.
@does
- `prometheusSpec.retention` and `retentionSize` bound disk use; the PVC must be larger than retentionSize (leave room for the WAL).
- `replicas: 2` gives two independent Prometheus servers for HA; Alertmanager dedups; add `externalLabels.replica`.
- Set `resources` based on measured series.
- `*SelectorNilUsesHelmValues: false` lets teams create monitors without the `release` label.
@diagram flow
caption: Values to production
nodes:
  - "Defaults|demo grade|warn"
  - "Storage, retention, resources|sized from series count|info"
  - "Selectors, remote write|team self-service|app"
  - "Production|reviewed and load tested|ok"
@h Production-leaning values
```yaml title="values.yaml"
prometheus:
  prometheusSpec:
    replicas: 2
    retention: 15d
    retentionSize: 80GB
    serviceMonitorSelectorNilUsesHelmValues: false
    podMonitorSelectorNilUsesHelmValues: false
    ruleSelectorNilUsesHelmValues: false
    externalLabels:
      cluster: prod-mumbai
    resources:
      requests: {cpu: "1", memory: 4Gi}
      limits: {memory: 8Gi}
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: gp3
          accessModes: [ReadWriteOnce]
          resources:
            requests:
              storage: 100Gi
alertmanager:
  alertmanagerSpec:
    replicas: 3
grafana:
  admin:
    existingSecret: grafana-admin
```
:::warn
Do not keep passwords in values files in Git. Use an existing Secret or external secrets tooling.
:::
@end

@concept Alertmanager config per team
@plain
`AlertmanagerConfig` is a namespaced CRD that lets a team define its own route and receivers, which the Operator merges into the global configuration.
@problem
A central file edited by every team is a bottleneck and a source of outages.
@does
- Routes from an AlertmanagerConfig are automatically scoped with a matcher on its namespace.
- Secrets for receivers live in the same namespace.
- A platform team keeps global defaults and inhibitions.
@diagram flow
caption: Team-owned routing
nodes:
  - "Team namespace|AlertmanagerConfig and Secret|app"
  - "Operator|merges and namespaces|cp"
  - "Alertmanager|one config|warn"
@h Example
```yaml title="alertmanagerconfig.yaml"
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: payments
  namespace: shop
  labels:
    alertmanagerConfig: main
spec:
  route:
    receiver: payments-slack
    groupBy: [alertname]
  receivers:
    - name: payments-slack
      slackConfigs:
        - channel: "#payments-alerts"
          apiURL:
            name: slack-webhook
            key: url
```
:::note
This API is still at v1alpha1 in many versions. Check the current CRD version in your cluster.
:::
@end

@concept Operating and debugging the stack
@plain
Most issues come from selectors, RBAC and resources. Know the quick checks.
@problem
Silent misconfiguration leaves you with missing metrics and no alerts.
@does
- Port-forward Prometheus and open Status, then Targets, Rules and Configuration.
- Operator logs show rejected rules.
- `kubectl get servicemonitor,podmonitor,prometheusrule -A` lists what exists.
- Managed Kubernetes (EKS) hides some control plane components; disable default rules for kube-scheduler, controller-manager and etcd if they are not scrapable.
- Remember to uncordon nodes after maintenance; node drains can trigger and then resolve many alerts.
@diagram flow
caption: Debug sequence
numbered: true
nodes:
  - "Does the object exist|kubectl get|info"
  - "Labels match selectors|release label|warn"
  - "Target in UI|port name and namespace|app"
  - "Samples arrive|query up|ok"
@h Commands
```bash title="Debug the stack" lab
kubectl -n monitoring port-forward svc/kps-kube-prometheus-stack-prometheus 9090:9090 &
kubectl get servicemonitor,podmonitor,prometheusrule -A
kubectl -n monitoring logs deploy/kps-kube-prometheus-stack-operator --tail=50
kubectl -n monitoring get prometheus -o jsonpath='{.items[0].spec.serviceMonitorSelector}'
```
@end
