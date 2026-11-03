---
title: Container Registry and Azure Monitor
minutes: 60
objectives:
  - Use ACR with AKS using managed identity and understand tiers and tasks
  - Query logs with KQL in Log Analytics
  - Collect metrics and logs for AKS with Container Insights and Managed Prometheus and Grafana
---
Images need a home and clusters need eyes. ACR and Azure Monitor are the Azure answers to ECR and CloudWatch.

@concept Azure Container Registry
@plain
**ACR** is a managed private registry for container images and OCI artifacts such as Helm charts.
@problem
You need a private, fast, scannable registry close to your clusters.
@does
- **AWS equivalent**: ECR.
- **Main difference**: one registry resource with its own DNS name (`<name>.azurecr.io`), not many repositories created individually. SKUs Basic, Standard and Premium; Premium adds geo-replication, private endpoints, zone redundancy and content trust features.
- Names are globally unique.
- Admin user exists but should stay disabled; use Entra identities.
@diagram layers
caption: Registry SKUs
layers:
  - {label: "Basic and Standard", nodes: ["Single region|storage and throughput limits|info"]}
  - {label: "Premium", nodes: ["Geo-replication|one registry, many regions|ok", "Private endpoint|no public access|ok", "Zone redundancy|resilience|ok"]}
@h Create and push
```bash title="ACR" lab
az acr create -g rg-shared -n acrshopexample --sku Premium --admin-enabled false --zone-redundancy Enabled
az acr login -n acrshopexample
docker tag shop-api:1.0.0 acrshopexample.azurecr.io/shop/api:1.0.0
docker push acrshopexample.azurecr.io/shop/api:1.0.0
az acr repository show-tags -n acrshopexample --repository shop/api -o tsv
```
@check
Which ACR SKU gives geo-replication and private endpoints? || Premium.
@end

@concept ACR authentication and AKS pull
@plain
The kubelet identity of the cluster needs the `AcrPull` role on the registry so nodes can pull images without passwords.
@problem
ImagePullBackOff with 401 errors is the most common first AKS failure.
@does
- **AWS equivalent**: node IAM role with ECR read permissions.
- **Main difference**: `az aks update --attach-acr` assigns `AcrPull` to the kubelet managed identity. For CI pushes use a federated identity with `AcrPush`. Repository-scoped tokens exist for external systems.
- With a private endpoint on ACR the VNet needs the `privatelink.azurecr.io` DNS zone.
- Anonymous pull can be enabled but is rarely wanted.
@diagram seq
caption: Image pull
actors: ["Kubelet|node identity|app", "Entra ID|token|ext", "ACR|registry|env"]
steps:
  - "0>1: token for ACR | req"
  - "1>0: access token | resp"
  - "0>2: pull manifest and layers | tls"
  - "2>0: image | resp"
@h Attach and verify
```bash title="Attach ACR" lab
az aks update -g rg-shop-prod -n aks-shop-prod --attach-acr acrshopexample
az aks check-acr -g rg-shop-prod -n aks-shop-prod --acr acrshopexample.azurecr.io
```
:::tip
`kubectl describe pod` shows the pull error. 401 means missing AcrPull, a timeout often means private endpoint or DNS issues.
:::
@end

@concept ACR Tasks, cache and retention
@plain
**ACR Tasks** build images in the cloud. **Artifact cache** mirrors upstream registries. **Retention and purge** tame growth.
@problem
Pulling from Docker Hub hits rate limits, and registries fill with old untagged images.
@does
- **AWS equivalent**: ECR pull-through cache and lifecycle policies, CodeBuild for image builds.
- **Main difference**: `az acr build` sends your context and builds remotely without a local daemon. Cache rules map prefixes like `docker.io/library/*` to local repositories. A purge task with `acr purge` removes by age and tag filter; Premium offers a retention policy for untagged manifests.
- Tasks can trigger on base image updates; check current docs.
@diagram flow
caption: Build and cache
nodes:
  - "az acr build|context uploaded|ext"
  - "ACR Tasks|builds remotely|cp"
  - "Registry|image stored|env"
  - "Cache rule|mirrors Docker Hub|info"
@h Build in the cloud and purge
```bash title="ACR build and purge" lab
az acr build -r acrshopexample -t shop/api:{{.Run.ID}} -t shop/api:latest ./api
az acr cache create -r acrshopexample -n dockerhub-lib --source-repo "docker.io/library/*" --target-repo "upstream/*"
az acr run -r acrshopexample --cmd "acr purge --filter 'shop/api:.*' --ago 30d --untagged --keep 10" /dev/null
```
@check
Why use an ACR cache rule? || To avoid upstream rate limits and keep a local copy of public images.
@end

@concept Azure Monitor overview
@plain
**Azure Monitor** is the umbrella for metrics, logs, traces, alerts and dashboards. Data goes to a metrics database, a **Log Analytics workspace** and Application Insights.
@problem
Without central telemetry you cannot see failures across dozens of resource types.
@does
- **AWS equivalent**: CloudWatch (Metrics, Logs, Alarms), X-Ray, CloudTrail.
- **Main difference**: platform metrics are collected automatically and free for most resources, but resource logs need a **diagnostic setting** to send them anywhere. The Activity Log (control plane) is separate from resource logs. Data collection rules (DCRs) define what agents collect.
- Alerts: metric, log search (KQL), activity log and Prometheus rule groups, routed through action groups (email, webhook, ITSM).
@diagram layers
caption: Azure Monitor
layers:
  - {label: "Sources", nodes: ["Platform metrics|automatic|info", "Resource logs|diagnostic settings|info", "Agents and DCRs|Azure Monitor Agent|info"]}
  - {label: "Stores", nodes: ["Metrics database|time series|env", "Log Analytics|KQL tables|env", "Managed Prometheus|workspace|env"]}
  - {label: "Actions", nodes: ["Alerts|action groups|warn", "Workbooks and Grafana|dashboards|ok"]}
@h Diagnostic setting
```bash title="Send logs to Log Analytics" lab
WS=$(az monitor log-analytics workspace show -g rg-shared -n law-shop --query id -o tsv)
az monitor diagnostic-settings create --name to-law --resource "$(az keyvault show -n kv-shop-prod-001 --query id -o tsv)" \
  --workspace "$WS" --logs '[{"categoryGroup":"audit","enabled":true}]' --metrics '[{"category":"AllMetrics","enabled":true}]'
```
@end

@concept Log Analytics workspaces
@plain
A **Log Analytics workspace** is the database for logs, queried with KQL, with its own retention, access control and pricing.
@problem
Log volume is the largest hidden cost in monitoring and access to logs is sensitive.
@does
- **AWS equivalent**: CloudWatch Logs log groups and Logs Insights.
- **Main difference**: one workspace holds many tables (`AzureDiagnostics`, `ContainerLogV2`, `Perf`). Pricing tiers: pay as you go, commitment tiers and table plans (Analytics, Basic, Auxiliary) with different cost and query abilities; check current pricing.
- Retention is per workspace with per-table overrides; long-term archive is available.
- Access mode: resource-context RBAC or workspace-context.
- Set a daily cap carefully, since it stops ingestion.
@diagram cmp
caption: Table plans
cards:
  - {h: "Analytics", kind: ok, items: ["Full KQL, alerts", "Highest ingestion price", "Operational data"]}
  - {h: "Basic", kind: info, items: ["Cheaper ingestion", "Limited query features", "Verbose logs"]}
  - {h: "Auxiliary", kind: warn, items: ["Lowest cost", "Slow search", "Compliance logs"]}
@h Create a workspace
```bash title="Workspace" lab
az monitor log-analytics workspace create -g rg-shared -n law-shop --location westeurope --retention-time 30 --sku PerGB2018
az monitor log-analytics workspace table update --workspace-name law-shop -g rg-shared -n ContainerLogV2 --plan Basic 2>/dev/null || echo "check table plan support"
```
@check
Where do diagnostic logs of a Key Vault go by default? || Nowhere. You must create a diagnostic setting.
@end

@concept KQL basics
@plain
**Kusto Query Language (KQL)** reads a table and pipes it through operators: filter, project, summarize, sort.
@problem
Finding the one failing pod among millions of log lines needs a fast, expressive query language.
@does
- **AWS equivalent**: CloudWatch Logs Insights query syntax, or Athena for logs.
- **Main difference**: KQL is a full pipeline language, closer to Splunk SPL than SQL. Core operators: `where`, `project`, `extend`, `summarize ... by`, `bin()`, `order by`, `top`, `join`, `render`.
- Time filters first: `where TimeGenerated > ago(1h)` makes queries cheap.
- Run it in the portal, with `az monitor log-analytics query` or from Grafana.
@diagram flow
caption: A KQL pipeline
nodes:
  - "Table|ContainerLogV2|env"
  - "where|time and namespace|info"
  - "summarize|count by pod|cp"
  - "render|chart or table|ok"
@h Queries
```bash title="Run a query" lab
az monitor log-analytics query -w "$(az monitor log-analytics workspace show -g rg-shared -n law-shop --query customerId -o tsv)" \
  --analytics-query "ContainerLogV2 | where TimeGenerated > ago(1h) and PodNamespace == 'shop' | where LogMessage has 'error' | summarize errors=count() by PodName | top 10 by errors" -o table
```
```text title="More KQL patterns" nocheck
KubePodInventory
| where TimeGenerated > ago(30m) and Namespace == "shop"
| summarize arg_max(TimeGenerated, *) by Name
| where PodStatus != "Running"

InsightsMetrics
| where Name == "cpuUsageNanoCores"
| summarize avg(Val) by bin(TimeGenerated, 5m), Computer
| render timechart
```
@check
Why start a KQL query with a TimeGenerated filter? || It limits the data scanned, so it is faster and cheaper.
@end

@concept Container Insights
@plain
**Container Insights** collects node and container metrics, inventory and stdout and stderr logs from AKS into Log Analytics.
@problem
You need pod logs and cluster health without building a log pipeline.
@does
- **AWS equivalent**: CloudWatch Container Insights and Fluent Bit.
- **Main difference**: enabled by the `monitoring` add-on, which deploys Azure Monitor Agent as the `ama-logs` DaemonSet. Tables: `ContainerLogV2`, `KubePodInventory`, `KubeEvents`, `InsightsMetrics`. Use data collection rules to filter namespaces or switch to the Basic plan and cut cost.
- Logs are not metrics at scale; use Managed Prometheus for metrics.
- Cost control is the main tuning task.
@diagram flow
caption: Log path
nodes:
  - "Pod stdout|container runtime|app"
  - "ama-logs DaemonSet|Azure Monitor Agent|cp"
  - "Data collection rule|filters namespaces|info"
  - "Log Analytics|ContainerLogV2|env"
@h Enable
```bash title="Container Insights" lab
az aks enable-addons -g rg-shop-prod -n aks-shop-prod --addons monitoring \
  --workspace-resource-id "$(az monitor log-analytics workspace show -g rg-shared -n law-shop --query id -o tsv)"
kubectl get ds ama-logs -n kube-system
```
@end

@concept Managed Prometheus and Managed Grafana
@plain
**Azure Monitor managed service for Prometheus** is a hosted Prometheus-compatible store. **Azure Managed Grafana** is hosted Grafana with Entra login and prebuilt AKS dashboards.
@problem
Running Prometheus with long retention and high availability is a project in itself.
@does
- **AWS equivalent**: Amazon Managed Service for Prometheus and Amazon Managed Grafana.
- **Main difference**: metrics are scraped by a managed agent in the cluster (`ama-metrics`) and written to an **Azure Monitor workspace**. You query with PromQL; ServiceMonitor and PodMonitor CRDs are supported through custom resources of the Azure add-on (`azmonitoring.coreos.com`). Prometheus rule groups can raise Azure alerts.
- Managed Grafana links to the workspace as a data source.
- Check the current docs for retention and ingestion limits.
@diagram flow
caption: Metrics path
nodes:
  - "Pods and nodes|/metrics endpoints|app"
  - "ama-metrics|managed scrape agent|cp"
  - "Azure Monitor workspace|PromQL store|env"
  - "Managed Grafana|dashboards and alerts|ok"
@h Enable
```bash title="Prometheus and Grafana" lab
az monitor account create -g rg-shared -n amw-shop -l westeurope
az grafana create -g rg-shared -n grafana-shop -l westeurope
az aks update -g rg-shop-prod -n aks-shop-prod --enable-azure-monitor-metrics \
  --azure-monitor-workspace-resource-id "$(az monitor account show -g rg-shared -n amw-shop --query id -o tsv)" \
  --grafana-resource-id "$(az grafana show -g rg-shared -n grafana-shop --query id -o tsv)"
```
:::note
`az grafana` needs the `amg` CLI extension. The command is installed on first use or with `az extension add --name amg`.
:::
@check
Which query language does Managed Prometheus use? || PromQL.
@end
