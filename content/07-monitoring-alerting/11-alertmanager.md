---
title: Alertmanager and alert design
minutes: 55
objectives:
  - Describe how Alertmanager groups, routes, inhibits and silences alerts
  - Write a routing tree with receivers for Slack and PagerDuty
  - Design on-call alerts and runbooks that people can act on
---
Prometheus decides that something is wrong. Alertmanager decides who hears about it, when, and how often.

@concept What Alertmanager does
@plain
Alertmanager receives alerts from Prometheus, removes duplicates, groups them, applies silences and inhibitions, and sends notifications to receivers.
@problem
Without it, a failed node with 40 pods would send 40 separate pages.
@does
- Prometheus keeps pushing a firing alert on every evaluation; Alertmanager dedups.
- It sends a notification when a group first fires, again on changes, and a reminder every `repeat_interval`.
- Runs as a cluster of 3 replicas using gossip for HA. Point Prometheus at all replicas.
@diagram flow
caption: Alert pipeline
nodes:
  - "Prometheus|fires alerts|cp"
  - "Alertmanager|dedup, group, route|warn"
  - "Receiver|Slack, PagerDuty, email|ext"
  - "Human|acknowledges|app"
@end

@concept Routing tree
@plain
Routes form a tree. An alert enters at the root and descends to the first child whose matchers fit (unless `continue: true`).
@problem
Different teams and severities need different destinations and timings.
@does
- `receiver` at the root is the default fallback.
- `matchers` select by label, such as `severity="page"` and `team="payments"`.
- Children inherit group and timing settings unless overridden.
- Each alert goes to the deepest matching route.
@diagram flow
caption: A small routing tree
nodes:
  - "Root|default receiver slack|plain"
  - "severity=page|pagerduty|bad"
  - "team=payments|payments channel|info"
  - "severity=ticket|jira webhook|warn"
@h Configuration
```yaml title="alertmanager.yml"
global:
  resolve_timeout: 5m
route:
  receiver: slack-default
  group_by: [alertname, cluster, service]
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  routes:
    - matchers: [severity="page"]
      receiver: pagerduty-oncall
      repeat_interval: 1h
      routes:
        - matchers: [team="payments"]
          receiver: pagerduty-payments
    - matchers: [severity="ticket"]
      receiver: jira-webhook
      group_wait: 5m
      repeat_interval: 24h
receivers:
  - name: slack-default
    slack_configs:
      - channel: "#alerts"
        api_url_file: /etc/alertmanager/secrets/slack_url
        send_resolved: true
  - name: pagerduty-oncall
    pagerduty_configs:
      - routing_key_file: /etc/alertmanager/secrets/pd_platform
  - name: pagerduty-payments
    pagerduty_configs:
      - routing_key_file: /etc/alertmanager/secrets/pd_payments
  - name: jira-webhook
    webhook_configs:
      - url: http://jira-bridge.monitoring:8080/alerts
```
@end

@concept Grouping and timers
@plain
`group_by` decides which alerts are combined into one notification. Three timers control the pace: `group_wait`, `group_interval`, `repeat_interval`.
@problem
A cascading failure creates a storm of related alerts.
@does
- `group_wait` (30s): wait for more alerts of a new group before the first notification.
- `group_interval` (5m): minimum gap before notifying about new alerts added to an existing group.
- `repeat_interval` (4h): reminder for unchanged firing groups.
- `group_by: ['...']` disables grouping; avoid it.
@diagram seq
caption: Timers in action
actors: ["Prometheus|alerts|cp", "Alertmanager|group|warn", "Receiver|Slack|ext"]
steps:
  - "0>1: alert A | req"
  - "0>1: alert B | req"
  - "note 1..1: group_wait 30s"
  - "1>2: one message A and B | req"
  - "note 1..1: repeat after 4h"
@end

@concept Inhibition
@plain
An inhibition rule mutes target alerts while a source alert is firing and both share chosen labels.
@problem
When the cluster is down, hundreds of "service down" alerts add no information.
@does
- Source: ClusterDown. Target: any alert with severity warning in the same cluster.
- `equal` lists labels that must match on both sides.
- Pair with good label hygiene (`cluster`, `namespace`, `service`).
@diagram flow
caption: Root cause hides symptoms
nodes:
  - "NodeDown|source alert|bad"
  - "Pod alerts|target alerts on that node|warn"
  - "Muted|only the root cause pages|ok"
@h Rule
```yaml title="inhibit_rules"
inhibit_rules:
  - source_matchers: [alertname="ClusterDown"]
    target_matchers: [severity=~"warning|page"]
    equal: [cluster]
  - source_matchers: [severity="page"]
    target_matchers: [severity="warning"]
    equal: [alertname, namespace, service]
```
@end

@concept Silences
@plain
A silence mutes alerts matching label matchers for a fixed time. It is for planned work or known issues.
@problem
During a maintenance window you do not want pages for expected failures.
@does
- Created in the Alertmanager UI, with `amtool`, or the API; they have an author and a comment.
- Silences expire automatically; never use year-long silences.
- They do not stop Prometheus evaluating; they only suppress notification.
@diagram flow
caption: Silencing for maintenance
nodes:
  - "Start maintenance|drain nodes|info"
  - "Create silence|namespace=shop, 2 hours|warn"
  - "Work done|silence expires|ok"
@h amtool
```bash title="Create and list silences" lab
amtool --alertmanager.url=http://localhost:9093 silence add \
  namespace=shop --duration=2h --author="ops" --comment="node maintenance CHG1234"
amtool --alertmanager.url=http://localhost:9093 silence query
amtool check-config alertmanager.yml
amtool config routes test --config.file=alertmanager.yml severity=page team=payments
```
@end

@concept Receivers and on-call tools
@plain
A receiver is a named list of integrations: Slack, email, PagerDuty, Opsgenie, VictoriaOps, webhooks, Amazon SNS, Microsoft Teams.
@problem
A chat message is easy to miss at 3 a.m. Paging needs escalation and acknowledgement.
@does
- Use chat for awareness and tickets, and a paging service for urgent alerts.
- PagerDuty and similar tools hold schedules, escalation policies and acknowledgement state.
- Always set `send_resolved: true` for chat so threads close.
- Store secrets in files or Kubernetes Secrets, not inline.
@diagram flow
caption: Escalation path
nodes:
  - "Alertmanager|page|warn"
  - "On-call tool|primary engineer|app"
  - "No ack in 10 min|escalate to secondary|bad"
  - "Manager|last resort|ext"
@choose Pick the channel
Page the on-call engineer | users are affected now and a human can act | the alert would wait until morning
Chat channel | needs awareness or is a ticket candidate | the issue is urgent
Ticket automatically | slow capacity or hygiene issues | a human must see it within minutes
@end

@concept Designing alerts that people trust
@plain
Each page should be urgent, actionable, real and rare. If it is not, change the alert.
@problem
Alert fatigue causes real incidents to be missed.
@does
- Page only on symptoms tied to an SLO (see burn rate alerts).
- Route cause alerts to tickets.
- Track pages per on-call shift; aim for at most a couple per 12 hours.
- Review every page in a weekly meeting: fix, tune, or delete the alert.
@diagram flow
caption: Alert quality loop
numbered: true
nodes:
  - "Page fires|measure it|bad"
  - "Was it actionable?|yes or no|warn"
  - "No means tune or delete|fix the rule|info"
  - "Quieter pager|fewer, better pages|ok"
@check
What are the four qualities of a good page? || Urgent, actionable, real (not noise) and rare.
@end

@concept On-call runbooks
@plain
A runbook is a short document linked from the alert that tells the responder what the alert means, how to check impact, and what to try.
@problem
At 3 a.m. nobody remembers how a rarely failing component works.
@does
- Every paging alert has `runbook_url` in annotations.
- Structure: meaning, impact, quick checks (dashboards, `kubectl`, queries), mitigations (restart, scale, roll back), escalation contacts.
- Keep it short and test it during game days.
- Update it after each incident in the post-incident review.
@diagram layers
caption: Runbook layout
layers:
  - {label: "Context", nodes: ["What it means|plain words|info", "Impact|who is hurt|warn"]}
  - {label: "Action", nodes: ["Checks|dashboard, kubectl|app", "Fixes|restart, scale, rollback|ok"]}
  - {label: "Escalate", nodes: ["Owner team|contacts|ext"]}
@h Runbook template
```text title="runbooks/high-error-ratio.md"
# HighErrorRatio

Meaning: more than 5 percent of requests to a service return 5xx for 10 minutes.
Impact: customers see failures at checkout.

Checks
1. Open the service dashboard, compare to the last deploy annotation.
2. kubectl -n shop get pods ; kubectl -n shop logs deploy/checkout --tail=100
3. Check dependencies: database connections, payment provider status.

Fix
- Recent deploy: kubectl -n shop rollout undo deploy/checkout
- Saturation: kubectl -n shop scale deploy/checkout --replicas=6

Escalate to the payments on-call after 20 minutes without improvement.
```
@end
