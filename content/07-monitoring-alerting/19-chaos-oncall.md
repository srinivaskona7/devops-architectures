---
title: Chaos engineering, game days and on-call practice
minutes: 55
objectives:
  - Run controlled failure experiments and game days safely
  - Design an on-call rotation that is humane and effective
  - Write runbooks and blameless postmortems that lead to fixes
---
Reliability comes from practising failure before it happens and from a team that can respond calmly when it does.

@concept What chaos engineering is
@plain
Chaos engineering injects small, controlled failures into a system to check that it behaves as you believe.
@problem
Redundancy that was never tested often does not work: the failover has a typo, the timeout is too long, the alert never fires.
@does
- The method: define steady state (an SLI), form a hypothesis, inject a failure with a limited blast radius, observe, learn, fix.
- Start in staging, then production only with abort conditions and agreement.
- It tests the system and the humans: alerts, dashboards and runbooks.
- It is not random destruction; every experiment has a purpose and a stop button.
@diagram flow
caption: Experiment loop
numbered: true
nodes:
  - "Steady state|SLI baseline|info"
  - "Hypothesis|system will cope|app"
  - "Inject failure|small radius|warn"
  - "Learn and fix|record result|ok"
@check
What is the steady state? || A measurable normal behaviour, such as success rate and latency, used to judge the experiment.
@end

@concept Failure experiments on Kubernetes
@plain
Typical experiments: kill a pod, drain a node, add network latency, take down a zone, or break a dependency.
@problem
You need to know whether replicas, probes, PodDisruptionBudgets and retries really protect users.
@does
- Pod kill: does traffic continue with zero errors and does the replacement become ready in time?
- Node drain: do PodDisruptionBudgets and topology spread keep enough replicas up? Verify cordoned nodes are uncordoned afterwards.
- Network latency or loss: do timeouts and retries behave, or do retries amplify load?
- Zone failure: simulate by cordoning and draining all nodes of one zone in a non-production cluster.
- Tools: Chaos Mesh, LitmusChaos, AWS Fault Injection Service (FIS) for AWS-level faults such as stopping instances or throttling EBS.
@diagram cmp
caption: Experiment ideas by layer
cards:
  - {h: "Pod and node", kind: ok, items: ["Delete a pod", "Drain a node", "PDB and spread tested"]}
  - {h: "Network", kind: warn, items: ["Latency and loss", "DNS failure", "Retry storms"]}
  - {h: "Cloud", kind: info, items: ["Stop instances with FIS", "Zone loss", "Throttle storage"]}
@h A Chaos Mesh pod failure
```yaml title="podchaos.yaml"
apiVersion: chaos-mesh.org/v1alpha1
kind: PodChaos
metadata:
  name: kill-one-api-pod
  namespace: chaos-testing
spec:
  action: pod-kill
  mode: one
  selector:
    namespaces: [shop]
    labelSelectors:
      app: api
```
:::note
Check the current Chaos Mesh docs for the API version and installation steps.
:::
@end

@concept Running a game day
@plain
A game day is a scheduled exercise where a team practises a failure scenario together, with observers.
@problem
Real incidents are a poor place to learn who has access to what, where the runbook is, or how to reach a vendor.
@does
- Before: choose a scenario, set scope, announce, name a facilitator and a scribe, agree abort criteria and a rollback.
- During: the facilitator injects the failure; responders work as in a real incident (use the real channels, tools and roles); the scribe records timestamps.
- After: a review within a few days: detection time, diagnosis time, recovery time, gaps found, actions with owners.
- Run them quarterly and increase difficulty gradually.
@diagram seq
caption: Game day roles
actors: ["Facilitator|injects the fault|cp", "Responders|on-call team|app", "Scribe|records timeline|info"]
steps:
  - "0>1: failure injected | req"
  - "1>1: detect and diagnose | warn"
  - "1>0: ask for hints only if stuck | resp"
  - "2>2: note timestamps | req"
  - "1>0: recovery confirmed | resp"
@h Scenario template
```text title="Game day card" nocheck
Scenario: primary RDS instance fails over during peak checkout
Scope: staging, 14:00 to 15:30
Abort if: customer-facing error rate above 2 percent in production (should be unaffected)
Success: alert fires within 5 minutes, failover under 2 minutes, runbook accurate
```
@end

@concept On-call rotation design
@plain
On-call means one or more people are responsible for responding to alerts outside normal work.
@problem
A bad rotation burns people out, and tired engineers make poor decisions and leave.
@does
- Size: a rotation of fewer than 5 to 6 people is hard to sustain. With 8 people and one week each, each person carries 52 ÷ 8 = 6.5 weeks per year.
- Primary and secondary layers, with escalation after 5 to 15 minutes of no acknowledgement.
- Follow-the-sun for global teams avoids night pages.
- Compensation and time off after a heavy week are part of the design.
- Measure: pages per shift, night pages, time to acknowledge. A common target is a small number of actionable pages per shift (the Google SRE book mentions two incidents per 12 hour shift as a limit).
@diagram flow
caption: Escalation path
nodes:
  - "Alert|from Alertmanager|warn"
  - "Primary|acknowledge in 5 min|app"
  - "Secondary|next 10 min|cp"
  - "Manager or incident lead|last resort|bad"
@check
Weeks per year per person with 8 engineers and weekly shifts? || 52 ÷ 8 = 6.5 weeks.
@end

@concept Alert quality and noise reduction
@plain
Every page must be urgent, actionable and need a human. Anything else should be a ticket or a dashboard.
@problem
Noisy alerts train people to ignore pages. Alert fatigue is a leading cause of missed real incidents.
@does
- Page on symptoms users feel (SLO burn rate), not on causes (CPU high).
- Each alert has an owner, severity, runbook link and a clear first step.
- Review weekly: which alerts fired, were they actionable, how many were duplicates? Delete or fix the worst offenders.
- Use Alertmanager grouping, inhibition (a cluster-down alert suppresses its child alerts) and silences with expiry and a reason.
@diagram flow
caption: Decide what an alert becomes
nodes:
  - "Condition|something looks wrong|warn"
  - "User impact now?|yes pages|cp"
  - "Needs action soon?|ticket|info"
  - "Otherwise|dashboard only|plain"
@h Inhibition rule
```yaml title="alertmanager inhibit"
inhibit_rules:
  - source_matchers:
      - alertname = "KubeNodeNotReady"
    target_matchers:
      - severity = "warning"
    equal: ["node"]
```
@end

@concept Runbooks
@plain
A runbook is a short document attached to an alert that tells the responder what it means and what to do first.
@problem
At 3 am nobody remembers details. Without a runbook each page restarts the investigation from zero.
@does
- Fixed sections: what this alert means, user impact, dashboards to open, diagnosis commands, mitigation steps (rollback, scale, failover), escalation contacts.
- Keep commands copy-ready and safe; mark dangerous steps.
- Link from the alert annotation `runbook_url`; test the links.
- Update the runbook after every incident where it was wrong. Treat a missing step as a bug.
@diagram layers
caption: Parts of a good runbook
layers:
  - {label: "Understand", nodes: ["Meaning|what fired|info", "Impact|who is affected|info"]}
  - {label: "Act", nodes: ["Diagnose|commands and dashboards|app", "Mitigate|rollback, scale, failover|ok"]}
  - {label: "Escalate", nodes: ["Contacts|who to wake|warn"]}
@h Skeleton
```text title="runbook.md" nocheck
# HighErrorRate on checkout
Meaning: more than 2 percent 5xx for 5 minutes.
First look: Grafana Checkout dashboard, then Loki {app="checkout"} |= "error".
Mitigation: if a deploy happened in the last hour, run: kubectl rollout undo deploy/checkout -n shop
Escalate: payments team on-call if the provider returns 429.
```
@end

@concept Incident response and blameless postmortems
@plain
During an incident, roles keep the work orderly. Afterwards, a blameless review turns the event into lasting fixes.
@problem
Without roles everyone investigates and nobody communicates. Without a blameless culture people hide mistakes.
@does
- Roles: incident commander (decides, coordinates), operations lead (hands on), communications lead (status updates), scribe.
- Mitigate first, find root cause later. Roll back before you investigate if a deploy is the likely trigger.
- Postmortem within about a week: timeline, impact, contributing factors (systems and processes, not people), what went well, action items with owners and dates.
- Track actions to completion; an unfixed action is the same incident waiting.
@diagram flow
caption: Incident lifecycle
numbered: true
nodes:
  - "Detect|alert or report|warn"
  - "Mitigate|restore service|cp"
  - "Communicate|status updates|info"
  - "Postmortem|actions with owners|ok"
@check
Why mitigate before finding the root cause? || Restoring service limits user impact; the investigation can continue safely afterwards.
@end
