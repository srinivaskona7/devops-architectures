---
title: Core services 36 to 40, Prometheus and messaging
minutes: 60
objectives:
  - Compare managed Prometheus, queues, pub/sub, streaming and workflows
  - State when to choose each service
  - List the limits to verify in the current docs
---
Messaging decouples services, and workflows coordinate multi-step processes. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
Queue for work, topic for fan-out, stream for replay, workflow for process. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Messaging styles
layers:
  - {label: "Services on this page", nodes: ["Managed Prometheus and Grafana|Amazon Managed Service for Prometheus and Managed Grafana|app", "Queues|SQS|info", "Publish and subscribe|SNS|env", "Streaming|Kinesis or MSK|ok", "Workflow orchestration|Step Functions|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 36 | Managed Prometheus and Grafana | Amazon Managed Service for Prometheus and Managed Grafana | Azure Monitor managed Prometheus and Managed Grafana | Google Cloud Managed Service for Prometheus |
| 37 | Queues | SQS | Queue Storage or Service Bus | Cloud Tasks or Pub/Sub |
| 38 | Publish and subscribe | SNS | Event Grid | Pub/Sub |
| 39 | Streaming | Kinesis or MSK | Event Hubs | Pub/Sub or Managed Service for Apache Kafka |
| 40 | Workflow orchestration | Step Functions | Logic Apps or Durable Functions | Workflows |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 36. Managed Prometheus and Grafana
@plain
Prometheus metrics storage and Grafana dashboards run by the cloud, so you keep open tooling without operating the servers.
@problem
Self-hosted Prometheus struggles with storage, high availability and long retention.
@does
- **Names**: AWS Amazon Managed Service for Prometheus and Managed Grafana; Azure Azure Monitor managed Prometheus and Managed Grafana; GCP Google Cloud Managed Service for Prometheus.
- **What it is**: Accepts Prometheus remote write or scraping, stores data, supports PromQL queries and dashboards.
- **Choose it when**: Kubernetes metrics with PromQL skills; Portable dashboards; Long retention without running storage.
- **Check in the current docs**: Cardinality and sample rates drive cost; Collection agents still run in your cluster; Feature gaps vs open source exist, so check the current docs.
@diagram cmp
caption: Managed Prometheus and Grafana on the three clouds
cards:
  - {h: "Amazon Managed Service for Prometheus and Managed Grafana", kind: warn, items: ["Workspaces, remote write, managed Grafana workspaces"]}
  - {h: "Azure Monitor managed Prometheus and Managed Grafana", kind: info, items: ["Azure Monitor workspace, managed Grafana"]}
  - {h: "Google Cloud Managed Service for Prometheus", kind: ok, items: ["Managed collection, PromQL in Cloud Monitoring"]}
@h Example
Clusters scrape metrics and write to a managed workspace, while teams share one Grafana.
@h CLI on each cloud
```bash title="AWS CLI, Managed Prometheus and Grafana" nocheck
aws amp create-workspace --alias demo
```
```bash title="Azure CLI, Managed Prometheus and Grafana" nocheck
az monitor account create --resource-group rg-demo --name demo-prom --location westeurope
az grafana create --resource-group rg-demo --name demo-grafana
```
```bash title="gcloud, Managed Prometheus and Grafana" nocheck
gcloud services enable monitoring.googleapis.com
```
@check
What query language is shared? || PromQL.
@end

@concept 37. Queues
@plain
A buffer where producers drop messages and consumers take them at their own speed.
@problem
Direct calls fail when the receiver is slow or down, and spikes overload it.
@does
- **Names**: AWS SQS; Azure Queue Storage or Service Bus; GCP Cloud Tasks or Pub/Sub.
- **What it is**: Stores messages durably, supports retries, visibility timeouts and dead-letter queues.
- **Choose it when**: Decoupling services; Smoothing spikes; Background jobs.
- **Check in the current docs**: Delivery is usually at-least-once, so consumers must be idempotent; Ordering and size limits differ, so check the current docs; Poison messages need a dead-letter queue.
@diagram cmp
caption: Queues on the three clouds
cards:
  - {h: "SQS", kind: warn, items: ["Standard and FIFO queues, dead-letter queues"]}
  - {h: "Queue Storage or Service Bus", kind: info, items: ["Queue Storage simple, Service Bus advanced"]}
  - {h: "Cloud Tasks or Pub/Sub", kind: ok, items: ["Cloud Tasks for targeted tasks, Pub/Sub pull subscriptions"]}
@h Example
Orders are queued so checkout returns fast while workers handle email and invoices.
@h CLI on each cloud
```bash title="AWS CLI, Queues" nocheck
aws sqs create-queue --queue-name orders
```
```bash title="Azure CLI, Queues" nocheck
az servicebus namespace create --resource-group rg-demo --name demo-sb-123 --sku Standard
az servicebus queue create --resource-group rg-demo --namespace-name demo-sb-123 --name orders
```
```bash title="gcloud, Queues" nocheck
gcloud tasks queues create orders --location=europe-west1
```
@check
Why make consumers idempotent? || Messages can be delivered more than once.
@end

@concept 38. Publish and subscribe
@plain
A topic where publishers send an event once and many subscribers each receive a copy.
@problem
Point-to-point calls make the sender know every receiver.
@does
- **Names**: AWS SNS; Azure Event Grid; GCP Pub/Sub.
- **What it is**: Fans events out to queues, functions and webhooks, with filters.
- **Choose it when**: Fan-out notifications; Event-driven integration; Reacting to cloud resource events.
- **Check in the current docs**: Retry and dead-letter settings differ; Subscriber endpoints must handle duplicates; Product roles overlap, so check the current docs.
@diagram cmp
caption: Publish and subscribe on the three clouds
cards:
  - {h: "SNS", kind: warn, items: ["Topics, subscriptions, filter policies"]}
  - {h: "Event Grid", kind: info, items: ["Topics, subscriptions, system topics"]}
  - {h: "Pub/Sub", kind: ok, items: ["Topics, subscriptions, push and pull"]}
@h Example
An OrderPlaced event goes to inventory, email and analytics subscribers independently.
@h CLI on each cloud
```bash title="AWS CLI, Publish and subscribe" nocheck
aws sns create-topic --name order-events
```
```bash title="Azure CLI, Publish and subscribe" nocheck
az eventgrid topic create --resource-group rg-demo --name order-events --location westeurope
```
```bash title="gcloud, Publish and subscribe" nocheck
gcloud pubsub topics create order-events
```
@check
What does fan-out mean? || One event is delivered to many subscribers.
@end

@concept 39. Streaming
@plain
An ordered, replayable log of events that many readers can consume at their own pace.
@problem
Queues delete messages once read, but analytics and replay need history.
@does
- **Names**: AWS Kinesis or MSK; Azure Event Hubs; GCP Pub/Sub or Managed Service for Apache Kafka.
- **What it is**: Stores events by partition for a retention period, and supports consumer groups and Kafka-compatible APIs in some products.
- **Choose it when**: High-volume telemetry and clickstreams; Replay and reprocessing; Kafka compatibility.
- **Check in the current docs**: Partition count limits parallelism and ordering; Throughput is billed by shard, unit or hour, so check the current docs; Kafka clusters need capacity planning.
@diagram cmp
caption: Streaming on the three clouds
cards:
  - {h: "Kinesis or MSK", kind: warn, items: ["Kinesis Data Streams, MSK"]}
  - {h: "Event Hubs", kind: info, items: ["Event Hubs with Kafka endpoint"]}
  - {h: "Pub/Sub or Managed Service for Apache Kafka", kind: ok, items: ["Pub/Sub, Managed Kafka"]}
@h Example
Click events are kept 7 days so a new analytics job can replay the last week.
@h CLI on each cloud
```bash title="AWS CLI, Streaming" nocheck
aws kinesis create-stream --stream-name clicks --shard-count 1
```
```bash title="Azure CLI, Streaming" nocheck
az eventhubs namespace create --resource-group rg-demo --name demo-eh-123 --sku Standard
az eventhubs eventhub create --resource-group rg-demo --namespace-name demo-eh-123 --name clicks
```
```bash title="gcloud, Streaming" nocheck
gcloud pubsub topics create clicks
```
@check
What does a stream offer that a queue lacks? || Replay of retained history.
@end

@concept 40. Workflow orchestration
@plain
A service that runs multi-step processes with retries, branching and waiting, and records each step.
@problem
Chaining functions by hand scatters error handling and state.
@does
- **Names**: AWS Step Functions; Azure Logic Apps or Durable Functions; GCP Workflows.
- **What it is**: Defines steps in a state machine or low-code designer, calls cloud services, retries, and keeps history.
- **Choose it when**: Order or onboarding processes; Long-running approvals; Saga patterns.
- **Check in the current docs**: Pricing per state transition or action, so check the current docs; Step input and output size limits apply; Definitions are code and need review and versioning.
@diagram cmp
caption: Workflow orchestration on the three clouds
cards:
  - {h: "Step Functions", kind: warn, items: ["State machines in Amazon States Language"]}
  - {h: "Logic Apps or Durable Functions", kind: info, items: ["Logic Apps designer, Durable Functions code"]}
  - {h: "Workflows", kind: ok, items: ["Workflows YAML or JSON"]}
@h Example
An order workflow charges payment, reserves stock, and refunds if shipping fails.
@h CLI on each cloud
```bash title="AWS CLI, Workflow orchestration" nocheck
aws stepfunctions create-state-machine --name order-flow --definition file://flow.json --role-arn arn:aws:iam::111122223333:role/sfn-role
```
```bash title="Azure CLI, Workflow orchestration" nocheck
az logic workflow create --resource-group rg-demo --name order-flow --location westeurope --definition @flow.json
```
```bash title="gcloud, Workflow orchestration" nocheck
gcloud workflows deploy order-flow --location=europe-west1 --source=flow.yaml
```
@check
What is a saga? || A series of steps with compensating actions if a later step fails.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Non-idempotent consumers.
- Using a queue when replay is needed.
- Hiding business logic in many small functions instead of a workflow.
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
service: Managed Prometheus and Grafana
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

