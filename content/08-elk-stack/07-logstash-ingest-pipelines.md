---
title: Logstash and ingest pipelines
minutes: 50
objectives:
  - Write a Logstash pipeline with input, filter and output
  - Use grok, dissect, date and mutate to parse text logs
  - Compare Logstash with Elasticsearch ingest pipelines
---
Raw logs often need parsing, cleaning and routing. Two tools do it: Logstash outside the cluster, and ingest pipelines inside it.

@concept Logstash pipelines
@plain
Logstash is a JVM service that runs pipelines of **inputs**, **filters** and **outputs**. Events flow through the stages in order.
@problem
Collectors are deliberately simple. Complex parsing, enrichment from other systems and routing to several destinations need a stronger engine.
@does
- Inputs: `beats`, `kafka`, `http`, `jdbc`, `s3`, `syslog`.
- Filters: `grok`, `dissect`, `json`, `date`, `mutate`, `geoip`, `translate`, `ruby`.
- Outputs: `elasticsearch`, `kafka`, `s3`, `file`.
- Several pipelines can run in one instance (`pipelines.yml`), each with its own workers and queue.
@diagram flow
caption: Logstash stages
nodes:
  - "Input|beats on 5044|ext"
  - "Filter|grok, date, mutate|warn"
  - "Output|elasticsearch|cp"
@h A complete pipeline
```text title="logstash/pipeline/nginx.conf" nocheck
input {
  beats { port => 5044 }
}
filter {
  grok {
    match => { "message" => '%{IPORHOST:client.ip} - %{DATA:user.name} \[%{HTTPDATE:ts}\] "%{WORD:http.request.method} %{DATA:url.path} HTTP/%{NUMBER:http.version}" %{NUMBER:http.response.status_code:int} %{NUMBER:http.response.bytes:int}' }
  }
  date {
    match => ["ts", "dd/MMM/yyyy:HH:mm:ss Z"]
    target => "@timestamp"
  }
  mutate { remove_field => ["ts"] }
}
output {
  elasticsearch {
    hosts => ["https://es.example.internal:9200"]
    data_stream => true
    api_key => "${ES_API_KEY}"
  }
}
```
@end

@concept Grok and dissect
@plain
**Grok** parses text with named regular-expression patterns such as `%{IP:client.ip}`. **Dissect** splits text on fixed delimiters without regex.
@problem
Legacy applications write plain text. You need fields to query.
@does
- Grok is flexible but slower and can fail on unexpected input; failures add the tag `_grokparsefailure`.
- Dissect is faster and simpler when the format is rigid.
- Test patterns in Kibana's Grok Debugger before deploying.
- Better still: ask developers for JSON logs and skip parsing.
@diagram cmp
caption: Grok or dissect
cards:
  - {h: "Grok", kind: info, items: ["Regex patterns", "Handles variable text", "Slower, can fail"]}
  - {h: "Dissect", kind: ok, items: ["Delimiter based", "Fast", "Needs fixed layout"]}
  - {h: "JSON logs", kind: app, items: ["No parsing at all", "Best option", "Needs app change"]}
@h Dissect example
```text title="dissect filter" nocheck
filter {
  dissect {
    mapping => { "message" => "%{ts} %{+ts} %{level} [%{thread}] %{msg}" }
  }
}
```
@end

@concept Dates, types and conditionals
@plain
Two things go wrong most often in parsing: the event time (`@timestamp`) is the arrival time instead of the log time, and numbers stay strings.
@problem
Using ingest time puts old events in the wrong place on Kibana timelines, and string numbers cannot be summed or ranged.
@does
- `date` filter parses the log's own timestamp into `@timestamp`; give the format and time zone.
- Convert types in grok (`:int`) or `mutate { convert => ... }`.
- Conditionals `if [log][level] == "debug" { drop {} }` route or drop events.
- Use `tag_on_failure` and send failures to a separate index for review.
@diagram flow
caption: Fixing time and types
nodes:
  - "Raw line|time inside the text|plain"
  - "date filter|set @timestamp|warn"
  - "convert|strings to numbers|info"
  - "Correct document|ok|ok"
@h Conditionals
```text title="routing by condition" nocheck
filter {
  if [kubernetes][namespace] == "kube-system" and [log][level] == "debug" {
    drop {}
  }
  if "_grokparsefailure" in [tags] {
    mutate { add_field => { "[@metadata][target]" => "logs-parsefail-prod" } }
  }
}
```
@end

@concept Persistent queues and Kafka
@plain
Logstash can buffer events on disk in a **persistent queue**, and Kafka can sit before it as a durable log of events.
@problem
If Logstash restarts or Elasticsearch stalls, events in memory are lost, and bursts overwhelm downstream.
@does
- `queue.type: persisted` stores events on disk and gives at-least-once delivery.
- Kafka between collectors and Logstash absorbs spikes and allows several consumers (for example Elasticsearch plus S3 archive).
- On AWS, Amazon MSK or Kinesis can take that role.
- Add only when the loss risk or spike size justifies the extra system.
@diagram flow
caption: Buffering with Kafka
nodes:
  - "Filebeat or Fluent Bit|producers|env"
  - "Kafka|durable topic|warn"
  - "Logstash|consumer group|app"
  - "Elasticsearch|index|cp"
@h pipelines.yml and queue
```yaml title="config/pipelines.yml"
- pipeline.id: nginx
  path.config: "/usr/share/logstash/pipeline/nginx.conf"
  pipeline.workers: 4
  queue.type: persisted
  queue.max_bytes: 4gb
```
@end

@concept Elasticsearch ingest pipelines
@plain
An ingest pipeline is a list of **processors** that run inside Elasticsearch on each document before it is indexed.
@problem
Running a separate Logstash tier just to rename a field or parse one format is more to maintain.
@does
- Processors: `grok`, `dissect`, `json`, `date`, `rename`, `set`, `remove`, `geoip`, `script`, `drop`, `pipeline`, `fail`.
- Attach as the index setting `index.default_pipeline` or per request with `?pipeline=`.
- Test with the `_simulate` API before deploying.
- Runs on ingest-role nodes; heavy pipelines add CPU load to them.
@diagram flow
caption: Ingest pipeline on the way in
nodes:
  - "Bulk request|from Beats or Agent|ext"
  - "Ingest node|processors run|warn"
  - "Primary shard|document indexed|cp"
@h Define and test
```json
{
  "description": "Parse checkout logs",
  "processors": [
    { "json": { "field": "message", "target_field": "app" } },
    { "date": { "field": "app.ts", "formats": ["ISO8601"], "target_field": "@timestamp" } },
    { "rename": { "field": "app.level", "target_field": "log.level", "ignore_missing": true } },
    { "remove": { "field": ["app.ts"], "ignore_missing": true } }
  ],
  "on_failure": [
    { "set": { "field": "error.message", "value": "{{ _ingest.on_failure_message }}" } }
  ]
}
```
```json
{
  "docs": [
    { "_source": { "message": "{\"ts\":\"2026-10-31T12:00:00Z\",\"level\":\"error\"}" } }
  ]
}
```
:::note
Send the first body with `PUT _ingest/pipeline/checkout` and the second with `POST _ingest/pipeline/checkout/_simulate`.
:::
@end

@concept Logstash or ingest pipeline or agent
@plain
Where to parse is a design choice. Prefer the simplest place that works: the application first, then ingest pipelines, then Logstash.
@problem
Every extra moving part is something that can fail at 3 a.m.
@does
- App emits JSON: no parsing needed, just ship.
- Integrations (Elastic Agent) include ready-made ingest pipelines for known software.
- Ingest pipelines handle moderate transformation with no extra servers.
- Logstash for complex enrichment (DB lookups), fan-out to many outputs, Kafka consumers or when sources are unusual.
@diagram flow
caption: Escalating only when needed
nodes:
  - "JSON from the app|no parsing|ok"
  - "Agent integration|prebuilt pipeline|info"
  - "Ingest pipeline|custom processors|warn"
  - "Logstash|complex cases|bad"
@choose Where to parse
Application JSON | you own the code | the source is third-party software
Ingest pipeline | light parsing, few sources | pipeline CPU would hurt hot ingest nodes
Logstash | enrichment, fan-out, Kafka | a simple rename is all you need
@end
