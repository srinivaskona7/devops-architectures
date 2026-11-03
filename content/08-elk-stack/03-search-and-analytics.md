---
title: Searching Elasticsearch - analyzers, Query DSL, aggregations and ES|QL
minutes: 55
objectives:
  - Explain how analyzers turn text into terms
  - Write bool queries with filters and time ranges
  - Build aggregations and an ES|QL query for log analysis
---
Search is where the index pays off. Knowing how analysis and scoring work saves you from queries that look right but return the wrong results.

@concept Analyzers
@plain
An analyzer converts text into terms in three steps: character filters clean the text, a **tokenizer** splits it, and token filters change the tokens (lowercase, remove stop words, stem).
@problem
Users search for `Timeout` and expect to find `timeout`; raw text matching would miss it.
@does
- The same analyzer runs at index time and, by default, at query time, so terms line up.
- `standard` is the default: splits on word boundaries and lowercases.
- Use `_analyze` to see the tokens of any text.
- `keyword` fields skip analysis entirely.
@diagram flow
caption: Analysis chain
nodes:
  - "Input|Payment TIMEOUT after 3000ms|plain"
  - "Tokenizer|split into words|info"
  - "Filters|lowercase|warn"
  - "Terms|payment, timeout, after, 3000ms|ok"
@h Try it
```text title="Dev Tools" nocheck
POST _analyze
{ "analyzer": "standard", "text": "Payment TIMEOUT after 3000ms" }
```
@end

@concept Query DSL basics
@plain
Queries are JSON. **Full-text queries** such as `match` analyse the input and are scored. **Term-level queries** such as `term` and `range` match exact values.
@problem
Using a `match` on a keyword or a `term` on a text field gives surprising results.
@does
- `match`: full-text on `text` fields. `match_phrase`: words in order.
- `term` / `terms`: exact value on `keyword`, numbers, dates, IPs.
- `range`: numbers and dates. `exists`: field present.
- Results include `_score` relevance; logs are usually sorted by time instead.
@diagram cmp
caption: Which query for which field
cards:
  - {h: "text field", kind: info, items: ["match", "match_phrase", "Scored"]}
  - {h: "keyword, number, date", kind: ok, items: ["term, terms", "range", "Exact"]}
@end

@concept The bool query and filters
@plain
A `bool` query combines clauses: `must` (and, scored), `filter` (and, not scored, cached), `should` (or) and `must_not` (not).
@problem
Log searches combine a time window, a service and a text condition. Scoring everything wastes CPU.
@does
- Put time range and exact conditions in `filter` so they are cached and skip scoring.
- Put free-text in `must`.
- Use `must_not` to exclude noise such as health checks.
- Always bound queries with a `@timestamp` range.
@diagram flow
caption: Typical log query
nodes:
  - "filter|last 15 minutes, service checkout|ok"
  - "must|message matches timeout|info"
  - "must_not|path is /health|warn"
  - "Results|sorted by time|app"
@h Example
```json
{
  "size": 20,
  "sort": [{ "@timestamp": "desc" }],
  "query": {
    "bool": {
      "filter": [
        { "range": { "@timestamp": { "gte": "now-15m" } } },
        { "term": { "service.name": "checkout" } }
      ],
      "must": [{ "match": { "message": "timeout" } }],
      "must_not": [{ "term": { "url.path": "/health" } }]
    }
  }
}
```
@end

@concept Pagination and search_after
@plain
`from` plus `size` pages are limited to 10 000 hits by default. To read more, use `search_after` with a sort, optionally with a point in time (PIT).
@problem
Deep pagination makes every shard sort and return `from + size` hits, which hurts the whole cluster.
@does
- `from`/`size`: fine for the first few pages in a UI.
- `search_after`: continue after the last sort values; needs a stable sort (add a tie-breaker field).
- PIT keeps a consistent view while you page.
- For exports use tools built for it, not deep paging.
@diagram flow
caption: Paging through results
nodes:
  - "Open PIT|consistent snapshot|info"
  - "Search page 1|sort by time and tie-breaker|app"
  - "search_after|last sort values|warn"
  - "Close PIT|free resources|ok"
@h Example
```json
{
  "size": 100,
  "pit": { "id": "PASTE_PIT_ID_HERE", "keep_alive": "1m" },
  "sort": [{ "@timestamp": "asc" }, { "_shard_doc": "asc" }],
  "search_after": ["2026-10-31T12:00:00.000Z", 4521]
}
```
@end

@concept Aggregations
@plain
Aggregations compute statistics over matching documents: counts per value (buckets), time histograms, percentiles and sums (metrics).
@problem
Search returns individual documents. Operations need totals such as errors per service per minute.
@does
- **Bucket** aggs group documents: `terms`, `date_histogram`, `range`.
- **Metric** aggs calculate numbers: `avg`, `max`, `percentiles`, `cardinality`.
- Aggs nest, for example errors per minute per service.
- They use doc values, so they run on `keyword`, number and date fields. Set `size: 0` to skip returning hits.
@diagram layers
caption: Nested aggregation
layers:
  - {label: "Buckets", nodes: ["date_histogram|per minute|info", "terms|per service|info"]}
  - {label: "Metrics", nodes: ["value_count|events|ok", "percentiles|p95 latency|ok"]}
@h Errors per service per minute
```json
{
  "size": 0,
  "query": {
    "bool": { "filter": [
      { "range": { "@timestamp": { "gte": "now-1h" } } },
      { "term": { "log.level": "error" } }
    ] }
  },
  "aggs": {
    "per_minute": {
      "date_histogram": { "field": "@timestamp", "fixed_interval": "1m" },
      "aggs": { "by_service": { "terms": { "field": "service.name", "size": 5 } } }
    }
  }
}
```
@end

@concept ES|QL
@plain
ES|QL is a piped query language. You start with `FROM`, then pass results through commands such as `WHERE`, `STATS`, `SORT` and `LIMIT`, much like a shell pipeline.
@problem
Query DSL JSON is verbose for analysis tasks, and joins of ideas such as "count by service then sort" take nested JSON.
@does
- Runs in Kibana Discover (ES|QL mode), Dev Tools or the `_query` API.
- Core commands: `FROM`, `WHERE`, `EVAL`, `STATS ... BY`, `SORT`, `LIMIT`, `KEEP`, `DROP`.
- Time bucketing with `BUCKET(@timestamp, 1 minute)` (older versions used `AUTO_BUCKET`).
- It is evolving fast; check the current docs for supported commands and functions in your version.
@diagram flow
caption: A pipeline of commands
nodes:
  - "FROM logs-*|choose indices|info"
  - "WHERE|filter rows|warn"
  - "STATS|aggregate by group|app"
  - "SORT and LIMIT|top results|ok"
@h Example
```text title="ES|QL in Discover or Dev Tools" nocheck
FROM logs-*
| WHERE @timestamp > NOW() - 1 hour AND log.level == "error"
| STATS errors = COUNT(*) BY service.name
| SORT errors DESC
| LIMIT 5
```
```bash title="Same query by API" lab
curl -s -u elastic:$ES_PASSWORD -H 'Content-Type: application/json' \
  "$ES_URL/_query?format=txt" -d '{"query":"FROM logs-* | WHERE log.level == \"error\" | STATS errors = COUNT(*) BY service.name | LIMIT 5"}'
```
@end

@concept Query performance habits
@plain
Fast log search comes from a few habits: narrow the time range, search a small set of indices, filter before text, and avoid costly queries.
@problem
One careless wildcard query over a year of data can slow every other user.
@does
- Use data streams and time-based indices so Elasticsearch skips indices outside the time range.
- Avoid leading wildcards (`*error`), `script` queries and regexes on large fields.
- Use `keyword` for exact matches and `filter` context for caching.
- Check slow queries with the search slow log and `_search?profile=true`; cancel long tasks through the tasks API.
@diagram cmp
caption: Habits
cards:
  - {h: "Do", kind: ok, items: ["Time range first", "Filter on keyword fields", "Limit size", "Use data streams"]}
  - {h: "Avoid", kind: bad, items: ["Leading wildcards", "Regex on message", "Deep from+size paging", "Search all indices"]}
@end
