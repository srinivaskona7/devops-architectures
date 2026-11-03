---
title: Kibana - Discover, KQL, dashboards, alerting and access control
minutes: 55
objectives:
  - Search logs in Discover with KQL and filters
  - Build visualisations and dashboards with Lens
  - Create alerting rules and secure Kibana with spaces and roles
---
Kibana is the window onto Elasticsearch. Most engineers spend their time here during incidents.

@concept Data views and Discover
@plain
A **data view** (formerly index pattern) tells Kibana which indices or data streams to read and which field is the time field. **Discover** lets you search and browse the matching documents.
@problem
You need a quick way to see raw events in a time window and narrow them without writing JSON.
@does
- Create a data view such as `logs-*` with `@timestamp`.
- The time picker bounds every query, which is also the best performance habit.
- Click a field to see top values; click a value to add a filter.
- Save searches and share links to pin down an incident.
@diagram flow
caption: From question to answer
nodes:
  - "Pick data view|logs-*|info"
  - "Set time range|last 15 minutes|warn"
  - "Query and filter|KQL, pills|app"
  - "Inspect documents|fields, JSON|ok"
@end

@concept Kibana Query Language
@plain
KQL is the simple search syntax in Kibana's query bar: `field:value`, with `and`, `or`, `not`, wildcards and ranges.
@problem
Typing Query DSL JSON for every search is slow.
@does
- `log.level:error and service.name:checkout`
- `http.response.status_code >= 500`
- `message:"connection refused"` (phrase) and `url.path:/api/*` (wildcard)
- `not kubernetes.namespace:kube-system`
- Nested groups with parentheses. Field names are case sensitive; values on `keyword` fields are exact.
- Lucene syntax is also available. ES|QL mode offers piped queries.
@diagram cmp
caption: Query styles in Kibana
cards:
  - {h: "KQL", kind: ok, items: ["Fast to type", "Default in Discover", "Good for filtering"]}
  - {h: "Lucene", kind: info, items: ["Regex, fuzzy, boosting", "Older style"]}
  - {h: "ES|QL", kind: app, items: ["Pipes and STATS", "Analysis in Discover"]}
@h KQL examples
```text title="KQL" nocheck
log.level:error and service.name:checkout and not url.path:"/health"
http.response.status_code >= 500 and kubernetes.namespace:shop
message:"connection refused" or message:"timeout"
```
@end

@concept Lens and dashboards
@plain
**Lens** builds charts by dragging fields. Charts are combined on **dashboards** that share a time range and filters.
@problem
Operators need trends (errors per minute) and breakdowns (by service), not only lists of events.
@does
- Lens picks a good chart type, supports formulas (`count(kql='log.level:error') / count()`), and breakdowns by `terms`.
- Dashboards support controls and drilldowns to Discover.
- Export and import dashboards as saved objects (NDJSON) to keep them in Git.
- Standard dashboards from Elastic Agent integrations cover Nginx, Kubernetes, AWS and more.
@diagram layers
caption: Building a dashboard
layers:
  - {label: "Data", nodes: ["Data view|logs-*|info"]}
  - {label: "Visualisations", nodes: ["Errors per minute|date histogram|bad", "Top services|terms|app", "p95 latency|percentile|warn"]}
  - {label: "Dashboard", nodes: ["Shared time range and filters|one page|ok"]}
@h Lens formula
```text title="Error rate formula" nocheck
count(kql='log.level:error') / count()
```
@end

@concept Kibana alerting
@plain
Alerting rules run on a schedule, check a condition, and run **actions** (Slack, email, PagerDuty, webhook, index) when it is met.
@problem
Searching after the fact is too late. You want to be told when errors spike.
@does
- Rule types: Elasticsearch query (a KQL or DSL match count above a threshold), log threshold, custom threshold, ES|QL, anomaly detection (licence dependent).
- A rule has a check interval, a lookback window and a threshold, and notifies on status change or each interval.
- Connectors hold credentials for the destinations.
- Use action groups (for example `query matched` and `recovered`) to send resolution messages.
@diagram flow
caption: Rule lifecycle
nodes:
  - "Rule checks every minute|count errors in last 5m|info"
  - "Threshold exceeded|more than 100|bad"
  - "Action via connector|Slack, PagerDuty|warn"
  - "Recovered action|close the incident|ok"
@h Create a rule by API
```json
{
  "name": "Checkout errors over 100 in 5m",
  "rule_type_id": ".es-query",
  "consumer": "alerts",
  "schedule": { "interval": "1m" },
  "params": {
    "searchType": "esQuery",
    "index": ["logs-*"],
    "timeField": "@timestamp",
    "esQuery": "{\"query\":{\"bool\":{\"filter\":[{\"term\":{\"service.name\":\"checkout\"}},{\"term\":{\"log.level\":\"error\"}}]}}}",
    "threshold": [100],
    "thresholdComparator": ">",
    "timeWindowSize": 5,
    "timeWindowUnit": "m",
    "size": 100
  },
  "actions": []
}
```
:::note
Send to `POST /api/alerting/rule` with the header `kbn-xsrf: true`. Rule parameters differ by version; check the current API docs.
:::
@end

@concept Spaces
@plain
**Spaces** divide Kibana into separate areas, each with its own dashboards, data views, rules and saved objects.
@problem
Different teams (platform, payments, security) should not see or break each other's dashboards.
@does
- Create a space per team or environment (`payments`, `security`).
- Roles grant privileges per space (read, all, none) on features.
- Spaces do not restrict which data can be queried; that is controlled by index privileges in roles.
- Copy saved objects between spaces.
@diagram layers
caption: Spaces and data permissions
layers:
  - {label: "Kibana", nodes: ["Space payments|dashboards, rules|app", "Space security|SIEM, detections|app"]}
  - {label: "Elasticsearch", nodes: ["logs-payments-*|index privilege|cp", "logs-security-*|index privilege|cp"]}
@end

@concept Roles, RBAC and single sign-on
@plain
Role-based access control gives each user or group a role listing cluster privileges, index privileges (including field and document level security) and Kibana feature privileges per space.
@problem
Default superuser access for everyone is a risk. Developers should see their logs, not the finance data.
@does
- Create roles such as `payments-reader` with `read` on `logs-payments-*` and Kibana read access in the payments space.
- Map users and groups from SAML or OIDC (your corporate IdP) to roles with role mappings.
- Document level security restricts rows with a query; field level security hides fields such as `user.email`.
- API keys carry a restricted role for automation.
@diagram flow
caption: Access chain
nodes:
  - "User signs in|SAML or OIDC|ext"
  - "Role mapping|group to role|warn"
  - "Role|index and space privileges|cp"
  - "Kibana and data|only what is allowed|ok"
@h Role definition
```json
{
  "cluster": ["monitor"],
  "indices": [
    {
      "names": ["logs-payments-*"],
      "privileges": ["read", "view_index_metadata"],
      "field_security": { "grant": ["*"], "except": ["user.email", "client.ip"] }
    }
  ],
  "applications": [
    {
      "application": "kibana-.kibana",
      "privileges": ["feature_discover.read", "feature_dashboard.read"],
      "resources": ["space:payments"]
    }
  ]
}
```
:::note
Send with `PUT _security/role/payments-reader`. Kibana privilege names change between versions; check the current docs.
:::
@end
