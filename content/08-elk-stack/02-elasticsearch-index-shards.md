---
title: Elasticsearch core - index, shards and mappings
minutes: 55
objectives:
  - Explain the inverted index and why search is fast
  - Choose primary and replica shard counts
  - Define mappings and avoid mapping explosions
---
Elasticsearch is a distributed document store that is built for search. This section covers how it stores and spreads your data.

@concept Documents and indices
@plain
A **document** is a JSON object. An **index** is a named collection of documents, similar to a table. A log event is one document.
@problem
You need to find a few events among billions by any field or by words in the text.
@does
- Each document gets an `_id` and is stored in one index.
- Fields have types (keyword, text, date, long, ip and so on).
- Queries are sent over a REST API in JSON.
@diagram flow
caption: Cluster vocabulary
nodes:
  - "Cluster|set of nodes|cp"
  - "Index|named collection|info"
  - "Shard|slice of an index|env"
  - "Document|one JSON event|app"
@h Index and search a document
```text title="Dev Tools console" nocheck
PUT logs-demo/_doc/1
{ "@timestamp": "2026-10-31T12:00:00Z", "service.name": "checkout", "log.level": "error", "message": "payment timeout after 3000 ms" }

GET logs-demo/_search
{ "query": { "match": { "message": "timeout" } } }
```
@end

@concept The inverted index
@plain
For each word, Lucene stores the list of documents that contain it. Looking up a word is a quick dictionary lookup, not a scan of every document.
@problem
Searching text by reading every document is far too slow for large data.
@does
- Text is cut into **terms** by an analyzer, then each term points to a **postings list** of document IDs.
- Multiple terms are combined by intersecting their lists.
- Fields also get **doc values**, a column-oriented store used for sorting and aggregations.
- Segments are immutable files; deletes are marks that are removed during merges.
@diagram layers
caption: Inverted index for two documents
layers:
  - {label: "Documents", nodes: ["Doc 1|payment timeout|plain", "Doc 2|payment ok|plain"]}
  - {label: "Terms to postings", nodes: ["payment|docs 1, 2|info", "timeout|doc 1|warn", "ok|doc 2|ok"]}
@check
Query for payment and timeout returns which docs? || Intersect lists for payment (1, 2) and timeout (1), giving doc 1 only.
@end

@concept Segments, refresh and near real-time
@plain
New documents go to an in-memory buffer and the translog. A **refresh** (default every second) makes them searchable by writing a new small segment. A **flush** later persists segments to disk.
@problem
Writing each event straight into an optimised on-disk structure would be very slow.
@does
- Search is **near real-time**: a new document is visible within about a second.
- The **translog** guarantees durability after a crash.
- Background merges combine small segments into larger ones.
- For bulk loading set a longer `refresh_interval` (for example 30s) to reduce overhead.
@diagram flow
caption: Life of an indexed document
nodes:
  - "Index request|document arrives|app"
  - "Buffer and translog|memory plus log|warn"
  - "Refresh|searchable segment|info"
  - "Flush and merge|durable on disk|ok"
@end

@concept Shards and replicas
@plain
An index is split into **primary shards**, each a complete Lucene index. Each primary can have **replica shards**, copies on other nodes.
@problem
One machine cannot hold or search all your data, and one disk failure must not lose it.
@does
- Primaries spread data and indexing work across nodes. Replicas give high availability and extra read capacity.
- A replica is never on the same node as its primary. With 1 replica you can lose one node without losing data.
- Primary count is fixed when an index is created (changing it needs split, shrink or reindex). Replica count can change any time.
- Each document goes to a shard by hash of its routing value (default the `_id`).
@diagram flow
caption: Three primaries with one replica on three nodes
nodes:
  - "Node 1|P0 and R2|env"
  - "Node 2|P1 and R0|env"
  - "Node 3|P2 and R1|env"
@h Settings and checks
```json
{
  "settings": {
    "number_of_shards": 3,
    "number_of_replicas": 1
  }
}
```
```text title="Health commands" nocheck
GET _cluster/health
GET _cat/shards/logs-*?v&s=store:desc
GET _cluster/allocation/explain
```
@end

@concept Choosing the number of shards
@plain
Shards are the unit of scaling, but each one has overhead. The aim is a moderate number of shards, each between roughly 10 GB and 50 GB.
@problem
Too many small shards waste memory and slow the cluster. A few huge shards are slow to recover and move.
@does
- Rule of thumb from Elastic: aim for shard size of 10 to 50 GB, and keep fewer than about 20 shards per GB of heap on a node; check the current docs for updated guidance.
- Worked example: 220 GB of primary data a day and a 50 GB target gives 220 ÷ 50 = 4.4, so use 4 or 5 primaries, or let ILM roll over at 50 GB.
- A node with a 30 GB heap should hold at most 30 × 20 = 600 shards.
- Use data streams with rollover instead of picking a shard count per day.
@diagram cmp
caption: Shard size trade-offs
cards:
  - {h: "Too small", kind: bad, items: ["Heap per shard overhead", "Many tiny segments", "Slow cluster state"]}
  - {h: "Right size", kind: ok, items: ["10 to 50 GB", "Even spread", "Fast recovery"]}
  - {h: "Too large", kind: warn, items: ["Slow recovery and moves", "Hard to rebalance"]}
@h Check the arithmetic
```python title="shards.py" lab
daily_primary_gb = 200 * 1.1          # 200 GB raw, about 10 percent index overhead
target_gb = 50
print("primaries per day", round(daily_primary_gb / target_gb, 1))
heap_gb = 30
print("max shards per node", heap_gb * 20)
```
@end

@concept Mappings and field types
@plain
A mapping says what type each field is. `text` is analysed for full-text search; `keyword` is stored whole for exact match, sorting and aggregations.
@problem
If Elasticsearch guesses wrong, you cannot aggregate on a field or you waste space indexing it twice.
@does
- `keyword`: IDs, status, service names, hostnames. `text`: free messages. `date`, `long`, `double`, `boolean`, `ip` for the rest.
- Dynamic mapping creates fields from the first document; it often maps strings as `text` plus a `.keyword` subfield.
- A field type cannot be changed in place; you must reindex.
- Setting `dynamic: strict` rejects unknown fields, while `dynamic: false` keeps them in `_source` but does not index them.
@diagram cmp
caption: text or keyword
cards:
  - {h: "text", kind: info, items: ["Analysed into terms", "Full-text search", "No aggregations by default"]}
  - {h: "keyword", kind: ok, items: ["Exact value", "Filters, sorts, aggregations", "Use for IDs and enums"]}
@h Explicit mapping
```json
{
  "mappings": {
    "dynamic": "strict",
    "properties": {
      "@timestamp": { "type": "date" },
      "service": { "properties": { "name": { "type": "keyword" } } },
      "log": { "properties": { "level": { "type": "keyword" } } },
      "message": { "type": "text" },
      "client": { "properties": { "ip": { "type": "ip" } } },
      "http": { "properties": { "response": { "properties": { "status_code": { "type": "short" } } } } },
      "trace": { "properties": { "id": { "type": "keyword" } } }
    }
  }
}
```
@end

@concept Mapping explosion and index templates
@plain
A **mapping explosion** is when a huge number of different field names (for example one per user ID) makes the cluster state enormous. **Index templates** apply settings and mappings to new indices automatically.
@problem
Dynamic mapping of unbounded keys can bring a cluster down, and hand-creating each daily index is error-prone.
@does
- The limit `index.mapping.total_fields.limit` defaults to 1000 and protects you; do not simply raise it.
- Model variable keys as values: `{"attribute": "plan", "value": "gold"}` instead of `{"plan": "gold"}` for thousands of keys.
- Use `flattened` type for arbitrary key-value maps.
- Composable templates combine component templates and match index patterns.
@diagram flow
caption: Template applied at creation
nodes:
  - "New index logs-app-000001|created by rollover|info"
  - "Index template|pattern logs-app-*|warn"
  - "Component templates|settings and mappings|app"
  - "Index with mapping|ready|ok"
@h Component and index template
```json
{
  "index_patterns": ["logs-app-*"],
  "data_stream": {},
  "priority": 200,
  "template": {
    "settings": { "number_of_shards": 1, "number_of_replicas": 1 },
    "mappings": {
      "properties": {
        "@timestamp": { "type": "date" },
        "message": { "type": "text" },
        "labels": { "type": "flattened" }
      }
    }
  }
}
```
:::note
Send this body with `PUT _index_template/logs-app` in Dev Tools.
:::
@end
