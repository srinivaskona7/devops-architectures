---
title: Collectors - Beats, Filebeat, Elastic Agent and Fluent Bit
minutes: 50
objectives:
  - Choose between Filebeat, Elastic Agent and Fluent Bit
  - Configure Filebeat inputs, processors and output
  - Understand Fleet policies and how backpressure is handled
---
The collector is the part of the pipeline that runs on every host. It must be small, reliable and polite to the application it sits beside.

@concept Beats family
@plain
Beats are small single-purpose shippers written in Go: **Filebeat** (log files), **Metricbeat** (metrics), **Packetbeat** (network), **Auditbeat** (audit and file integrity), **Heartbeat** (uptime probes).
@problem
Running Logstash or a JVM on every server is too heavy. You need a tiny agent that reads data and forwards it.
@does
- Each Beat reads data, adds metadata, and sends to Elasticsearch or Logstash.
- They remember where they stopped (a registry), so a restart does not lose or repeat data.
- Beats apply back-pressure: if the output is slow, they slow down reading instead of dropping data.
@diagram flow
caption: A Beat in the pipeline
nodes:
  - "Source|log files, metrics|plain"
  - "Beat|read, enrich, batch|env"
  - "Output|Elasticsearch or Logstash|cp"
@end

@concept Filebeat inputs and registry
@plain
Filebeat watches files, tracks the read offset of each in a registry, and sends new lines as events. Inputs define which files and how to split lines.
@problem
Files rotate, grow and are truncated. A naive `tail -f` loses lines or repeats them.
@does
- Input types: `filestream` (recommended for files, replaces the older `log` input), `container`, `syslog`, `tcp`, `aws-s3`, and more.
- Multi-line settings (parsers) join stack traces to one event.
- `ndjson` parser decodes JSON lines into fields.
- The registry holds the offset and file identity, so rotation is followed correctly.
@diagram flow
caption: Reading a rotating file
nodes:
  - "app.log|active file|app"
  - "Registry|offset per file identity|warn"
  - "Rotated app.log.1|finish reading, then close|info"
  - "Events|batched and sent|ok"
@h Config
```yaml title="filebeat.yml"
filebeat.inputs:
  - type: filestream
    id: checkout-json
    paths:
      - /var/log/checkout/*.log
    parsers:
      - ndjson:
          target: ""
          add_error_key: true
    fields:
      env: prod
    fields_under_root: true

processors:
  - drop_event:
      when:
        equals:
          url.path: /health

output.elasticsearch:
  hosts: ["https://es.example.internal:9200"]
  api_key: "${ES_API_KEY}"
  ssl.certificate_authorities: ["/etc/filebeat/ca.crt"]
```
```bash title="Test before running" lab
filebeat test config -c filebeat.yml
filebeat test output -c filebeat.yml
```
@end

@concept Processors in the agent
@plain
Processors change events before they leave the host: add metadata, drop fields or events, rename, decode JSON, or redact.
@problem
Cleaning at the edge reduces network and storage cost, and keeps secrets from ever leaving the node.
@does
- `add_host_metadata`, `add_cloud_metadata`, `add_kubernetes_metadata` enrich events.
- `drop_event` / `drop_fields` remove noise and sensitive fields.
- `dissect` splits delimited text cheaply; `script` runs JavaScript for special cases.
- Conditions (`equals`, `contains`, `regexp`, `and`, `or`) control when a processor runs.
@diagram cmp
caption: Edge or central processing
cards:
  - {h: "At the agent", kind: ok, items: ["Drop noise and secrets", "Add host and pod metadata", "Cheap and parallel"]}
  - {h: "In Logstash or ingest", kind: info, items: ["Heavy parsing, grok", "Enrich from other sources", "One place to change"]}
@h Drop and redact
```yaml title="processors"
processors:
  - drop_fields:
      fields: ["http.request.headers.authorization", "http.request.headers.cookie"]
      ignore_missing: true
  - drop_event:
      when:
        regexp:
          message: "^GET /(health|ready) "
```
@end

@concept Elastic Agent and Fleet
@plain
**Elastic Agent** is one agent that can collect logs, metrics and security data using **integrations** (packaged settings, mappings and dashboards). **Fleet** in Kibana manages many agents centrally through **agent policies**.
@problem
Managing hundreds of separate Beat config files on every host is slow and error-prone.
@does
- Agents enrol with a Fleet Server using an enrolment token and fetch their policy.
- A policy lists integrations (Nginx, Kubernetes, AWS, System). Changing the policy updates all agents.
- Data goes to data streams named `logs-<dataset>-<namespace>` with ECS fields.
- Under the hood Elastic Agent runs Beats and other components. Standalone mode is also available using a YAML file.
@diagram flow
caption: Fleet-managed agents
nodes:
  - "Kibana Fleet|policies and integrations|info"
  - "Fleet Server|serves policy|cp"
  - "Elastic Agents|on each host or node|env"
  - "Elasticsearch|data streams|cp"
@end

@concept Beats versus Elastic Agent
@plain
Both ship data. Beats are simple and file-configured; Elastic Agent is centrally managed and the direction of travel for Elastic.
@problem
Picking the wrong one leads to rework when you grow.
@does
- Choose Elastic Agent and Fleet if you use Kibana for security, observability apps or need central policy for many hosts.
- Choose Filebeat when you want plain config in Git, a smaller footprint or a fixed single task, and you manage config with Helm or Ansible.
- Both can write directly to Elasticsearch or through Logstash.
- Check the current Elastic documentation for feature parity of the integration you need.
@diagram cmp
caption: Which collector
cards:
  - {h: "Filebeat", kind: info, items: ["Config as code in Git", "Light and simple", "You manage rollout"]}
  - {h: "Elastic Agent", kind: ok, items: ["Fleet central control", "Integrations with dashboards", "Needs Fleet Server"]}
@choose Pick one
Filebeat | Kubernetes DaemonSet with Helm, GitOps | you want a UI to roll policy to thousands of hosts
Elastic Agent | mixed estates, security use cases | you cannot run Fleet Server
Fluent Bit | multi-backend routing, very small memory | you want Elastic-specific integrations
@end

@concept Fluent Bit as an alternative
@plain
Fluent Bit is a very light C-based log processor and forwarder from the CNCF. It sends to Elasticsearch, OpenSearch, Loki, S3, CloudWatch, Kafka and more.
@problem
You may want one collector for several backends, or the lowest memory footprint, or an AWS-native option (EKS can run it for CloudWatch).
@does
- Pipeline: input, parser, filter, output. Kubernetes filter adds pod metadata.
- Memory is typically in the tens of MB.
- The Elasticsearch output works but you must set the index or data stream and mapping yourself; check current docs for data stream options.
- Good fit if you may switch from ELK to Loki or OpenSearch later.
@diagram flow
caption: Fluent Bit pipeline
nodes:
  - "tail input|container logs|plain"
  - "kubernetes filter|pod labels|warn"
  - "parser|JSON|info"
  - "es output|Elasticsearch|cp"
@h Fluent Bit configuration
```yaml title="fluent-bit.yaml" nocheck
service:
  flush: 5
  log_level: info
pipeline:
  inputs:
    - name: tail
      path: /var/log/containers/*.log
      multiline.parser: docker, cri
      tag: kube.*
      mem_buf_limit: 50MB
  filters:
    - name: kubernetes
      match: kube.*
      merge_log: on
  outputs:
    - name: es
      match: kube.*
      host: es.example.internal
      port: 9200
      tls: on
      http_user: ${ES_USER}
      http_passwd: ${ES_PASSWORD}
      logstash_format: on
      logstash_prefix: kube
```
:::note
Fluent Bit supports classic and YAML configuration. Option names may change between versions. Check the current documentation.
:::
@end

@concept Backpressure, buffering and delivery guarantees
@plain
When Elasticsearch is slow or down, the collector must buffer, slow down or drop. How it behaves decides whether you lose logs during an outage.
@problem
Logs are needed most during incidents, which are also when the logging cluster is under load.
@does
- Filebeat: at-least-once delivery. It stops reading and retries; duplicates are possible after retries (use document IDs or fingerprints for dedup if needed).
- Memory queue is default; a disk queue survives restarts.
- Source files act as a buffer only as long as they are not rotated away. Kubernetes rotates at 10 MiB x 5 by default, so a long outage can lose logs.
- A message queue (Kafka) between collectors and Logstash decouples ingest from search.
@diagram flow
caption: Where logs wait during an outage
nodes:
  - "Elasticsearch down|writes fail|bad"
  - "Collector retries|queue fills|warn"
  - "Node log file|kubelet rotation limits|info"
  - "Kafka option|durable buffer|ok"
@h Disk queue
```yaml title="Filebeat disk queue"
queue.disk:
  max_size: 5GB
output.elasticsearch:
  hosts: ["https://es.example.internal:9200"]
  bulk_max_size: 1600
  worker: 2
```
@end
