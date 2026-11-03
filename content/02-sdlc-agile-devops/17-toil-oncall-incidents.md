---
title: Toil, on-call and incident response
minutes: 45
objectives:
  - Identify toil and decide what to automate first
  - Run an on-call rotation that is sustainable and effective
  - Manage an incident with clear roles, severity levels and communication
---
Reliability depends on people as much as on systems. This section covers how SRE teams limit repetitive work, share on-call fairly and respond to incidents in an organised way.

@concept Toil
@plain
**Toil** is operational work that is manual, repetitive, automatable, tactical, without lasting value and grows as the service grows. Restarting a stuck job by hand every week is toil. Designing a fix is engineering.
@problem
If toil is not limited, it consumes the whole team, no time remains for improvement, and the team cannot scale with the service.
@does
- SRE aims to keep toil below about 50 percent of working time; the rest is engineering.
- Measure it: tag tickets and pages, then estimate hours per week.
- Automate by priority: frequency x time x risk of error.
- Not toil: overhead such as meetings, and project work with lasting benefit.
@diagram cmp
caption: Toil versus engineering
cards:
  - {h: "Toil", kind: bad, items: ["Manual and repeated", "No lasting value", "Scales with traffic"]}
  - {h: "Engineering", kind: ok, items: ["Removes future work", "Creates lasting improvement", "Scales without more people"]}
@h Prioritise automation
```python title="Rank toil by hours saved" lab
tasks = [("rotate certs by hand", 4, 12), ("restart stuck consumer", 1.5, 40), ("resize disks", 0.5, 20), ("create namespaces", 0.3, 60)]
# name, hours per occurrence, occurrences per quarter
for name, h, n in sorted(tasks, key=lambda t: -t[1] * t[2]):
    print(f"{name:<24} {h * n:6.1f} h per quarter")
```
@check
Is a weekly planning meeting toil? || No, toil is repetitive operational work that could be automated; meetings are overhead.
@end

@concept Automating toil away
@plain
Turn recurring manual steps into code: scripts first, then self-healing systems, then removing the cause.
@problem
Runbooks that say "log in and run these 12 commands" are error-prone at 3 a.m. and keep people on the pager.
@does
- Ladder: document, script, automate with a trigger, self-heal, and finally redesign so the problem cannot occur.
- Kubernetes already automates much: restarts, rescheduling, autoscaling, rolling updates.
- Candidates: certificate renewal (cert-manager), scaling (HPA, KEDA), capacity requests, access requests, patching.
- Automation can fail too: add limits, dry-run modes and alerts.
@diagram flow
caption: The automation ladder
numbered: true
nodes:
  - "Document|runbook|plain"
  - "Script|one command|app"
  - "Trigger|alert calls the script|info"
  - "Self-heal|system fixes itself|env"
  - "Eliminate|design the cause away|ok"
@h Example, remove manual cert renewal
```yaml title="cert-manager Certificate"
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: api-tls
  namespace: shop
spec:
  secretName: api-tls
  duration: 2160h
  renewBefore: 360h
  dnsNames: [api.example.com]
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```
@check
What is the last rung of the automation ladder? || Eliminating the cause through design, so no fix or automation is needed.
@end

@concept On-call that people can sustain
@plain
On-call means being available to respond to alerts outside normal hours. Done well it is shared, paid or compensated, and rare enough to avoid burnout.
@problem
Overloaded on-call causes burnout, bad decisions at night and attrition of the best engineers.
@does
- Rotation with at least 5 to 8 people for a 24x7 primary, so each person is on call about one week in five or more; follow-the-sun across regions where possible.
- Primary and secondary responders; clear escalation path and handover notes.
- Limit pages: Google's guidance is at most two incidents per 12 hour shift for sustainable work.
- Only page for symptoms users feel and that need a human now; everything else is a ticket.
- Compensation or time off in lieu.
@diagram flow
caption: Escalation path
nodes:
  - "Alert|SLO burn|warn"
  - "Primary|5 min to acknowledge|app"
  - "Secondary|if no ack|info"
  - "Manager or incident commander|major incident|bad"
@h Review the pager load
```python title="Pages per shift" lab
pages_per_week = {"week1": 3, "week2": 14, "week3": 5, "week4": 21}
for week, n in pages_per_week.items():
    flag = "too noisy - fix alerts" if n > 10 else "ok"
    print(f"{week}: {n:>2} pages  {flag}")
```
@check
Which alerts should page a human? || Those showing user-visible symptoms that need immediate action; the rest become tickets.
@end

@concept Alert quality
@plain
A good alert is urgent, actionable, and tied to user impact. A bad alert is noise that teaches people to ignore the pager.
@problem
Alert fatigue: hundreds of non-actionable alerts hide the one that matters.
@does
- Alert on symptoms (SLO burn, error rate) not on every cause (CPU 80 percent).
- Every alert has a runbook link, severity, owner and clear next step.
- Review after each on-call week: delete, tune or automate alerts that did not need action.
- Route by severity: page, ticket, dashboard only.
@diagram cmp
caption: Symptom or cause
cards:
  - {h: "Page on symptoms", kind: ok, items: ["Checkout error budget burning", "Latency above SLO"]}
  - {h: "Ticket or dashboard", kind: info, items: ["Disk 70 percent full", "One pod restarted"]}
  - {h: "Delete", kind: bad, items: ["Alerts nobody acts on", "Duplicates"]}
@h Alertmanager routing
```yaml title="alertmanager.yml" nocheck
route:
  receiver: ticket
  routes:
    - matchers: ['severity="page"']
      receiver: pagerduty
    - matchers: ['severity="ticket"']
      receiver: ticket
receivers:
  - name: pagerduty
    pagerduty_configs: [{routing_key_file: /etc/alertmanager/pd-key}]
  - name: ticket
    webhook_configs: [{url: https://tickets.example.com/hook}]
```
@check
What should every alert include? || A runbook link, an owner and a severity.
@end

@concept Incident response roles
@plain
A major incident is handled by a small team with defined roles, so decisions are clear and nobody works in parallel on contradictory fixes.
@problem
In a crisis, everyone jumps in, communications are scattered and nobody knows who decides. Recovery is slower.
@does
- **Incident Commander (IC)** coordinates and decides; does not debug.
- **Operations / technical lead** investigates and applies fixes.
- **Communications lead** updates stakeholders and status page at fixed intervals.
- **Scribe** records a timeline in a shared channel or document.
- Roles can be combined in small incidents. Handover is explicit if the IC changes.
@diagram layers
caption: Incident roles
layers:
  - {label: "Command", nodes: ["Incident commander|decides and coordinates|cp"]}
  - {label: "Working", nodes: ["Ops lead|diagnose and fix|app", "Comms lead|status updates|info", "Scribe|timeline|plain"]}
@h Declaring an incident
```text title="Opening message in the incident channel"
INCIDENT 2026-10-31-01  SEV2  Checkout errors above 5 percent
IC: priya   Ops: sam   Comms: lee   Scribe: ana
Impact: about 20 percent of card payments fail since 10:42 UTC
Next update at 11:15 UTC
```
@check
Why should the incident commander not debug? || They must keep an overview and coordinate; deep debugging loses that view.
@end

@concept Severity levels and the incident lifecycle
@plain
Severity levels classify the impact, so the response is proportionate. The lifecycle is detect, triage, mitigate, resolve, learn.
@problem
Treating every issue as an emergency exhausts people; treating emergencies casually costs customers.
@does
- Example scale: **SEV1** total outage or data loss, all hands; **SEV2** major feature degraded; **SEV3** minor impact, working hours; **SEV4** cosmetic.
- **Mitigate first**: restore service by rollback, failover, flag off or scaling, then find the root cause later.
- Keep communication regular, even if there is no news.
- Record key metrics: time to detect, time to mitigate, time to resolve.
@diagram flow
caption: Incident lifecycle
numbered: true
nodes:
  - "Detect|alert or report|warn"
  - "Triage|severity and roles|info"
  - "Mitigate|restore service first|app"
  - "Resolve|fix underlying cause|ok"
  - "Learn|postmortem|env"
@h First moves in Kubernetes
```bash title="Mitigation toolbox" lab
kubectl rollout undo deployment/api -n shop 2>/dev/null          # revert the last deployment
kubectl scale deployment/api -n shop --replicas=10 2>/dev/null   # add capacity
kubectl get events -n shop --sort-by=.lastTimestamp 2>/dev/null | tail -10
kubectl logs deploy/api -n shop --since=15m 2>/dev/null | tail -20
```
@check
Why mitigate before finding root cause? || Users are affected now; restoring service reduces harm, and diagnosis can continue calmly afterwards.
@end

@concept Communication during incidents
@plain
Good communication keeps stakeholders informed and engineers free to work. Use one channel, regular updates and plain language.
@problem
Without updates, executives and customer teams interrupt responders for status, and customers lose trust.
@does
- One incident channel and a pinned summary of impact, status and next update time.
- Update at a fixed rhythm: every 15 to 30 minutes for major incidents.
- Customer-facing status page: what is affected, what we know, when the next update comes. No blame, no speculation.
- Record decisions and commands in the channel for the later timeline.
@diagram seq
caption: Information flow
actors: ["Responders|incident channel|app", "Comms lead|summarises|info", "Stakeholders|status page and email|ext"]
steps:
  - "0>1: facts and ETA | req"
  - "1>2: update every 30 minutes | resp"
  - "2>1: questions | req"
  - "note 1..1: shields responders from interruptions"
@h Status update template
```text title="Update template"
Status        Investigating | Identified | Mitigating | Monitoring | Resolved
Impact        who is affected and how
What we know  facts only
What we do    current action
Next update   exact time
```
@check
What goes in a status update? || Impact, current knowledge, current action and the time of the next update.
@end
