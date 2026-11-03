---
title: Core services 31 to 35, audit, governance and observability
minutes: 60
objectives:
  - Compare audit logs, policy, metrics, logs and tracing
  - State when to choose each service
  - List the limits to verify in the current docs
---
Audit and policy explain and constrain what happens, and observability shows how it behaves. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
Guardrails before, signals during, evidence after. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Control and visibility
layers:
  - {label: "Services on this page", nodes: ["Audit logs|CloudTrail|app", "Policy and governance|Organizations SCPs and Config|info", "Metrics and alarms|CloudWatch|env", "Logs|CloudWatch Logs|ok", "Tracing|X-Ray|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 31 | Audit logs | CloudTrail | Activity Log | Cloud Audit Logs |
| 32 | Policy and governance | Organizations SCPs and Config | Azure Policy | Organization Policy |
| 33 | Metrics and alarms | CloudWatch | Azure Monitor | Cloud Monitoring |
| 34 | Logs | CloudWatch Logs | Log Analytics | Cloud Logging |
| 35 | Tracing | X-Ray | Application Insights | Cloud Trace |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 31. Audit logs
@plain
A record of who did what to which cloud resource and when.
@problem
Without it you cannot investigate incidents or prove compliance.
@does
- **Names**: AWS CloudTrail; Azure Activity Log; GCP Cloud Audit Logs.
- **What it is**: Records management events and optionally data access, delivers them to storage, and supports queries and alerts.
- **Choose it when**: Security investigations; Compliance evidence; Change tracking.
- **Check in the current docs**: Data access logging is often optional and costly, so check the current docs; Logs need protection from tampering; Retention periods differ by service.
@diagram cmp
caption: Audit logs on the three clouds
cards:
  - {h: "CloudTrail", kind: warn, items: ["Trails, event history, organization trails"]}
  - {h: "Activity Log", kind: info, items: ["Activity Log with diagnostic settings"]}
  - {h: "Cloud Audit Logs", kind: ok, items: ["Admin Activity, Data Access, System Event logs"]}
@h Example
An organization trail writes to a locked bucket in a separate account with log file validation.
@h CLI on each cloud
```bash title="AWS CLI, Audit logs" nocheck
aws cloudtrail create-trail --name org-trail --s3-bucket-name audit-logs-123456 --is-multi-region-trail
```
```bash title="Azure CLI, Audit logs" nocheck
az monitor activity-log list --offset 7d --max-events 20
```
```bash title="gcloud, Audit logs" nocheck
gcloud logging read 'logName:cloudaudit.googleapis.com' --limit=20
```
@check
Where should audit logs be stored? || In a protected location, ideally another account.
@end

@concept 32. Policy and governance
@plain
Rules that apply across accounts or projects to forbid or flag configurations, such as public storage or unapproved regions.
@problem
Hand-reviewing every account does not scale and mistakes reach production.
@does
- **Names**: AWS Organizations SCPs and Config; Azure Azure Policy; GCP Organization Policy.
- **What it is**: Applies preventive guardrails and detective checks from a central point.
- **Choose it when**: Multi-account organizations; Regulated environments; Standard tagging and region rules.
- **Check in the current docs**: SCPs limit permissions but do not grant any; Test in audit mode before enforcing; Policy inheritance can surprise teams.
@diagram cmp
caption: Policy and governance on the three clouds
cards:
  - {h: "Organizations SCPs and Config", kind: warn, items: ["SCPs, Config rules, Control Tower"]}
  - {h: "Azure Policy", kind: info, items: ["Policy definitions, initiatives, assignments"]}
  - {h: "Organization Policy", kind: ok, items: ["Constraints and custom constraints"]}
@h Example
A guardrail denies resource creation outside two approved regions for all workload accounts.
@h CLI on each cloud
```bash title="AWS CLI, Policy and governance" nocheck
aws organizations list-policies --filter SERVICE_CONTROL_POLICY
```
```bash title="Azure CLI, Policy and governance" nocheck
az policy assignment list --query '[].displayName'
```
```bash title="gcloud, Policy and governance" nocheck
gcloud resource-manager org-policies list --organization=123456789
```
@check
Does an SCP grant permission? || No, it only limits what can be granted.
@end

@concept 33. Metrics and alarms
@plain
Numbers over time such as CPU or request count, with alerts when they cross a limit.
@problem
You find problems from customers instead of from your own signals.
@does
- **Names**: AWS CloudWatch; Azure Azure Monitor; GCP Cloud Monitoring.
- **What it is**: Collects, stores, graphs and alerts on metrics, including custom ones.
- **Choose it when**: Every production service; Autoscaling signals; SLO tracking.
- **Check in the current docs**: Custom metrics and high-cardinality labels raise cost; Default resolution and retention differ, so check the current docs; Alarms need actions and owners.
@diagram cmp
caption: Metrics and alarms on the three clouds
cards:
  - {h: "CloudWatch", kind: warn, items: ["Metrics, alarms, dashboards"]}
  - {h: "Azure Monitor", kind: info, items: ["Metrics, alert rules, action groups"]}
  - {h: "Cloud Monitoring", kind: ok, items: ["Metrics, alerting policies, dashboards"]}
@h Example
An alarm fires when the 5xx rate stays above 2 percent for five minutes and pages the on-call.
@h CLI on each cloud
```bash title="AWS CLI, Metrics and alarms" nocheck
aws cloudwatch put-metric-alarm --alarm-name high5xx --metric-name HTTPCode_Target_5XX_Count --namespace AWS/ApplicationELB --statistic Sum --period 300 --evaluation-periods 1 --threshold 50 --comparison-operator GreaterThanThreshold
```
```bash title="Azure CLI, Metrics and alarms" nocheck
az monitor metrics alert create --name high-cpu --resource-group rg-demo --scopes /subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-demo/providers/Microsoft.Compute/virtualMachines/web1 --condition "avg Percentage CPU > 80"
```
```bash title="gcloud, Metrics and alarms" nocheck
gcloud alpha monitoring policies list
```
@check
Why must alarms have owners? || An alert nobody handles is noise.
@end

@concept 34. Logs
@plain
Central storage and search for text records produced by applications and platforms.
@problem
Logs scattered across machines vanish with the machine and are slow to search.
@does
- **Names**: AWS CloudWatch Logs; Azure Log Analytics; GCP Cloud Logging.
- **What it is**: Ingests, retains, queries and exports logs, with retention settings and filters.
- **Choose it when**: Troubleshooting; Audit and security analysis; Metrics derived from logs.
- **Check in the current docs**: Ingestion is the main cost, so filter and sample; Set retention explicitly; Query languages differ per cloud.
@diagram cmp
caption: Logs on the three clouds
cards:
  - {h: "CloudWatch Logs", kind: warn, items: ["Log groups, Logs Insights"]}
  - {h: "Log Analytics", kind: info, items: ["Workspaces, KQL queries"]}
  - {h: "Cloud Logging", kind: ok, items: ["Log buckets, Logs Explorer"]}
@h Example
Debug logs are kept 7 days and error logs 90 days to balance cost and need.
@h CLI on each cloud
```bash title="AWS CLI, Logs" nocheck
aws logs create-log-group --log-group-name /shop/app
aws logs put-retention-policy --log-group-name /shop/app --retention-in-days 30
```
```bash title="Azure CLI, Logs" nocheck
az monitor log-analytics workspace create --resource-group rg-demo --workspace-name demo-logs --retention-time 30
```
```bash title="gcloud, Logs" nocheck
gcloud logging buckets update _Default --location=global --retention-days=30
```
@check
What drives log cost most? || Volume ingested, so filter noise at the source.
@end

@concept 35. Tracing
@plain
A view of one request as it passes through many services, showing time spent in each.
@problem
In microservices, slow requests are hard to locate from metrics alone.
@does
- **Names**: AWS X-Ray; Azure Application Insights; GCP Cloud Trace.
- **What it is**: Collects spans with trace IDs, builds service maps and supports sampling.
- **Choose it when**: Microservices latency analysis; Dependency maps; Error correlation.
- **Check in the current docs**: Sampling choices decide cost and visibility; OpenTelemetry is the portable instrumentation, so check each backend's current support; Trace IDs must propagate through every hop.
@diagram cmp
caption: Tracing on the three clouds
cards:
  - {h: "X-Ray", kind: warn, items: ["Segments, service map, OpenTelemetry collector"]}
  - {h: "Application Insights", kind: info, items: ["Application Insights with OpenTelemetry"]}
  - {h: "Cloud Trace", kind: ok, items: ["Traces and Trace Explorer"]}
@h Example
A trace shows 800 ms of a 1 s request was one database call.
@h CLI on each cloud
```bash title="AWS CLI, Tracing" nocheck
aws xray get-service-graph --start-time 2026-10-31T00:00:00Z --end-time 2026-10-31T01:00:00Z
```
```bash title="Azure CLI, Tracing" nocheck
az monitor app-insights component create --app demo-ai --location westeurope --resource-group rg-demo --workspace demo-logs
```
```bash title="gcloud, Tracing" nocheck
gcloud services enable cloudtrace.googleapis.com
```
@check
What must happen at every hop for tracing? || The trace context must be propagated.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Audit logs in the same account they audit.
- Enforcing policy without audit mode first.
- Unlimited log retention by default.
- Always confirm limits, prices and regional availability in the current documentation before committing.
@diagram flow
caption: A safe habit before adopting any service
nodes:
  - "Define need|workload, size, latency|plain"
  - "Map services|three cloud names|info"
  - "Check docs|limits, price, regions|warn"
  - "Prototype|measure on real data|app"
  - "Decide|record in an ADR|ok"
@h Habit as a checklist
```yaml title="service-evaluation.yaml" nocheck
service: Audit logs
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

