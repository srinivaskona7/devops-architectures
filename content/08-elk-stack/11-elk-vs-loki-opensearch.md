---
title: ELK versus Loki, OpenSearch and CloudWatch Logs
minutes: 45
objectives:
  - Compare Elasticsearch, Loki, OpenSearch and CloudWatch Logs on index model, cost and query power
  - Choose a log backend for a given workload
  - Plan a migration or a hybrid setup
---
There is no best log store, only a best fit. The key differences are what gets indexed, where the data lives, and who runs the thing.

@concept Two indexing philosophies
@plain
Elasticsearch builds a **full-text inverted index** over the contents of every log line. Loki indexes only **labels** (like pod, namespace, app) and keeps the log text compressed in chunks, scanning it at query time.
@problem
Indexing every word gives fast arbitrary search, but the index can be as large as the data. Indexing only labels is cheap, but searching for a word in a large time range scans a lot of data.
@does
- Elasticsearch: higher CPU, RAM and disk per GB ingested; very fast text search, aggregations and analytics on fields.
- Loki: low index cost and S3 storage; cheap ingest; queries select streams by labels first, then filter lines (`|= "error"`).
- Rule of thumb: Elasticsearch storage is roughly the size of raw data or more; Loki's compressed chunks are often several times smaller than raw. Measure with your data.
@diagram cmp
caption: What is indexed
cards:
  - {h: "Elasticsearch", kind: info, items: ["Every term in every field", "Large index", "Fast arbitrary search"]}
  - {h: "Loki", kind: ok, items: ["Labels only", "Small index, chunks on S3", "Fast when labels narrow it down"]}
@end

@concept Elasticsearch strengths
@plain
Elasticsearch is a general search and analytics engine. Logs are one use; it also serves security analytics (SIEM), application search and metrics.
@problem
Some teams need rich queries on log fields, such as top 10 users by error count with percentile latency, joined across large datasets.
@does
- Powerful aggregations, ES|QL, machine learning anomaly detection (licence dependent), SIEM and APM in the same product.
- Mature lifecycle tooling: ILM, tiers, searchable snapshots, cross-cluster search.
- Costs: operating a stateful cluster, shard planning, licence considerations (Elastic licence and SSPL/AGPL options in recent versions; check the current licence terms).
@diagram layers
caption: One platform, several uses
layers:
  - {label: "Use cases", nodes: ["Log search|Discover|info", "Security SIEM|detections|bad", "APM and traces|Elastic APM|app"]}
  - {label: "Engine", nodes: ["Elasticsearch|search and analytics|cp"]}
@end

@concept Loki strengths
@plain
Loki is a log system from Grafana Labs designed like Prometheus: labels as identity, simple operations, object storage.
@problem
Many teams want logs next to metrics in Grafana at a fraction of the price, and mostly search by service and time.
@does
- Same label model as Prometheus, so switching from a metric to the logs of that pod is one click.
- Stores chunks in S3, GCS or Azure Blob, so retention is cheap; operation is simpler (single binary mode to microservices mode).
- LogQL supports line filters, parsers (`| json`, `| logfmt`) and metric queries (`rate`, `count_over_time`).
- Weak spots: high-cardinality labels destroy performance (do not label by user ID), and heavy full-text over long ranges is slow.
@diagram flow
caption: Loki in a Grafana stack
nodes:
  - "Promtail, Alloy, Fluent Bit|labels pods|env"
  - "Loki|index of labels, chunks|cp"
  - "S3|cheap long retention|ext"
  - "Grafana|LogQL and links to metrics|info"
@h LogQL versus KQL
```text title="Same question in LogQL" nocheck
{namespace="shop", app="checkout"} |= "timeout" | json | level="error"
sum by (pod) (rate({namespace="shop"} |= "error" [5m]))
```
:::note
Promtail has reached end of life in favour of Grafana Alloy; check the current Grafana documentation for the recommended agent.
:::
@end

@concept OpenSearch
@plain
OpenSearch is a community-driven fork of Elasticsearch 7.10 and Kibana, created by AWS and others under the Apache 2.0 licence. **Amazon OpenSearch Service** is the managed AWS offering.
@problem
After Elastic changed its licence in 2021, AWS and others wanted a permissively licensed engine; AWS customers also wanted a managed service integrated with IAM and VPC.
@does
- API and concepts are similar to older Elasticsearch: indices, shards, query DSL, aggregations. Dashboards replaces Kibana.
- Built-in plugins for security, alerting, anomaly detection, ISM (Index State Management, similar to ILM) and SQL/PPL queries.
- Managed service: domains with data nodes, dedicated masters, UltraWarm and cold storage tiers, Serverless option; integrates with IAM, CloudWatch Logs subscription and Firehose.
- Divergence: newer Elasticsearch features (ES|QL, Elastic Agent, newer Lens) are not in OpenSearch, and client libraries are separate.
@diagram cmp
caption: Elastic Stack or OpenSearch
cards:
  - {h: "Elastic Stack", kind: info, items: ["Newest features", "Elastic Agent, Fleet, ECK", "Self-managed or Elastic Cloud"]}
  - {h: "OpenSearch", kind: app, items: ["Apache 2.0 licence", "Amazon OpenSearch Service", "IAM and VPC integration on AWS"]}
@end

@concept CloudWatch Logs
@plain
CloudWatch Logs is AWS's native log service. Services like Lambda, ECS, RDS and EKS control plane write to it with no setup.
@problem
Running your own log cluster for a handful of AWS-managed services is overkill.
@does
- Pay per GB ingested and stored, plus queries (Logs Insights) per GB scanned. Check the current pricing page for your region.
- Logs Insights has a pipe query language with `fields`, `filter`, `stats`; Live Tail for real-time view.
- Subscription filters stream to Lambda, Kinesis, Firehose or OpenSearch.
- Metric filters turn log patterns into CloudWatch metrics for alarms.
- Ingestion cost can dominate at high volume, which is when teams move bulk logs elsewhere.
@diagram flow
caption: AWS-native log paths
nodes:
  - "Lambda, RDS, EKS control plane|write automatically|ext"
  - "CloudWatch Logs|store and Insights|warn"
  - "Subscription filter|stream out|info"
  - "OpenSearch or Elastic|long-term search|cp"
@h Logs Insights query
```text title="CloudWatch Logs Insights" nocheck
fields @timestamp, @message
| filter @message like /timeout/
| stats count() as errors by bin(5m)
| sort @timestamp desc
```
@end

@concept Cost comparison with numbers
@plain
Rough cost modelling shows why architecture choice matters at volume. All prices below are illustrative inputs, not quotes; use your region's current prices.
@problem
Gut feeling about "Loki is cheaper" needs numbers before a migration.
@does
- Assume 200 GB/day raw, 30 days retention.
- Elasticsearch: 15 529 GB provisioned disk (from the sizing section) at an illustrative gp3 price of 0.08 USD per GB-month gives about 1 242 USD per month for disk alone, plus compute for roughly 6 data nodes.
- Loki on S3: assume compressed to about 20 percent of raw: 200 × 0.2 × 30 = 1 200 GB in S3 at an illustrative 0.023 USD per GB-month, about 28 USD per month, plus ingesters, queriers and cache.
- CloudWatch Logs: ingestion price per GB multiplied by 6 000 GB per month (200 × 30) often dominates; check current pricing.
- Compute and operations time are large parts of the real cost; the point is the ratio of disk, not the total.
@diagram flow
caption: Where each option spends money
nodes:
  - "Elasticsearch|disk and RAM for index|warn"
  - "Loki|ingester CPU, S3 is small|ok"
  - "CloudWatch Logs|per GB ingested|bad"
@h Check the arithmetic
```python title="log_cost.py" lab
raw_gb_day, days = 200, 30
es_disk_gb = raw_gb_day * 1.1 * 2 * days / 0.85
loki_gb = raw_gb_day * 0.2 * days
gp3, s3 = 0.08, 0.023   # illustrative USD per GB-month
print("ES disk GB", round(es_disk_gb), "USD", round(es_disk_gb * gp3))
print("Loki S3 GB", round(loki_gb), "USD", round(loki_gb * s3))
print("monthly ingest GB", raw_gb_day * days)
```
@end

@concept Choosing and migrating
@plain
Pick by questions you need to answer, team skills, and cost at your volume. Hybrid setups are common.
@problem
Moving everything to one tool for fashion's sake risks losing capability or money.
@does
- Choose Elastic Stack when you need rich search and analytics, SIEM, or a single platform for logs, APM and security.
- Choose Loki when logs mainly support debugging next to Prometheus metrics in Grafana, and cost matters.
- Choose OpenSearch Service when you want managed search on AWS with IAM, or need Apache 2.0.
- Choose CloudWatch Logs for AWS-managed sources, low volume and short retention.
- Hybrid: application logs to Loki; audit and security to Elasticsearch; AWS service logs to CloudWatch with a subscription filter for key streams.
- Migrate by running both in parallel through the collector (Fluent Bit or OpenTelemetry Collector can fan out), comparing queries, then cutting over per team.
@diagram flow
caption: A safe migration
numbered: true
nodes:
  - "Dual write|collector sends to both|info"
  - "Re-create key queries and alerts|in the new tool|app"
  - "Compare results|for two weeks|warn"
  - "Cut over and retire old|per team|ok"
@choose Pick a log backend
Elastic Stack | complex search, SIEM, analytics | your team cannot run stateful search clusters
Loki | debugging logs next to Prometheus, low cost | you need rich field analytics on all logs
OpenSearch Service | AWS managed, IAM, Apache 2.0 | you need the newest Elastic features
CloudWatch Logs | AWS-managed sources, small volume | volume is high and retention is long
@end
