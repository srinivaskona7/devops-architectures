---
title: Interview readiness guide
minutes: 35
objectives:
  - Prepare answers with a repeatable structure for technical and behavioural questions
  - Practise troubleshooting and system design out loud
  - Show evidence of operational maturity without exaggeration
---
Interviews for DevOps, SRE and platform roles test reasoning more than memory. This guide gives a structure for each kind of question and drills you can run alone.

@concept What interviewers look for
@plain
They want to know whether you can solve unfamiliar problems, communicate clearly, and be trusted with production.
@problem
Candidates memorise commands and then freeze when the question changes shape.
@does
- Fundamentals: Linux, networking, containers, one cloud, Git, one scripting language.
- Troubleshooting method: forming hypotheses and checking them in order.
- Design judgement: explaining trade offs and failure modes.
- Collaboration: blameless attitude, clear writing, honest about what you do not know.
@diagram cmp
caption: Typical interview rounds
cards:
  - {h: "Screen", kind: info, items: ["Background and basics", "Why this role"]}
  - {h: "Technical", kind: app, items: ["Linux, networking, Kubernetes", "Live troubleshooting"]}
  - {h: "Design", kind: cp, items: ["Whiteboard a system", "Failure and scale"]}
  - {h: "Behavioural", kind: ok, items: ["Incidents, conflict, leadership"]}
@h Prepare a question bank
```bash title="Make a study file" lab
mkdir -p ~/interview && cd ~/interview
cat > bank.md <<'EOF'
# Questions I must answer in under two minutes
- What happens when you type a URL?
- A pod is CrashLoopBackOff. What do you check?
- Explain a 502 from a load balancer.
- Difference between a process and a thread?
EOF
wc -l bank.md
```
@check
What matters more than the exact command? || The reasoning path and the ability to explain why you take each step.
@end

@concept The troubleshooting answer pattern
@plain
Use the same shape every time: clarify, scope, form hypotheses, test the cheapest first, fix, and prevent.
@problem
Jumping to a favourite cause sounds uncertain and misses simple explanations.
@does
- Clarify: what changed, who is affected, since when, what does the error say.
- Narrow with layers: client, DNS, network, load balancer, application, database.
- State the command you would run and what each outcome would mean.
- Finish with mitigation first (rollback, scale), root cause second, prevention third.
@diagram flow
caption: Spoken troubleshooting structure
numbered: true
nodes:
  - "Clarify|impact and recent change|plain"
  - "Scope|which layer|info"
  - "Hypothesise|cheapest check first|app"
  - "Mitigate|restore service|warn"
  - "Prevent|alert, test, runbook|ok"
@h Worked example
```bash title="Pod will not start" nocheck
kubectl get pod web-7d9 -o wide                      # state and node
kubectl describe pod web-7d9 | sed -n '/Events/,$p'  # image pull, scheduling, probe errors
kubectl logs web-7d9 --previous --tail=30            # why the last run died
kubectl get events --sort-by=.lastTimestamp | tail   # cluster-side clues
```
@check
Which comes first, root cause or mitigation? || Mitigation, to restore service; then find the root cause.
@end

@concept Common technical questions and model answers
@plain
Some questions appear constantly. Having a crisp answer for each shows command of fundamentals.
@problem
Rambling or vague answers hide real knowledge.
@does
- "What happens when you type a URL": DNS lookup, TCP handshake, TLS handshake, HTTP request through proxies and load balancer, application, response, rendering.
- "A server is slow": apply USE: CPU run queue, memory and swap, disk wait, network drops.
- "Difference between a container and a VM": containers share a kernel and are isolated with namespaces and cgroups; VMs run their own kernel.
- "CrashLoopBackOff": read events, logs of the previous container, probes, limits and exit code (137 is a kill, often OOM).
@diagram flow
caption: The URL question as a chain
nodes:
  - "DNS|name to address|info"
  - "TCP|three way handshake|plain"
  - "TLS|certificate and keys|cp"
  - "HTTP|request to balancer|app"
  - "Backend|app and database|ok"
@h Trace the chain
```bash title="One request, step by step" lab
dig +short example.com                       # DNS
curl -sv --connect-timeout 5 https://example.com -o /dev/null 2>&1 | grep -E 'Connected|SSL connection|HTTP/'
curl -s -o /dev/null -w 'dns=%{time_namelookup} connect=%{time_connect} tls=%{time_appconnect} total=%{time_total}\n' https://example.com
```
@end

@concept Scripting and coding rounds
@plain
Expect small practical tasks: parse a log, call an API, transform YAML. They test clean, safe, readable code more than clever tricks.
@problem
Candidates write long solutions without testing or clear naming and run out of time.
@does
- Choose the language you know best, usually Python or Bash.
- Read the input format first, handle empty input and errors, then print output.
- Talk through edge cases and how you would test.
@diagram flow
caption: A calm coding approach
nodes:
  - "Restate|inputs and outputs|plain"
  - "Small example|work it by hand|info"
  - "Implement|simple first|app"
  - "Test edge cases|empty, bad lines|ok"
@h Typical task
```python title="Count HTTP status codes from an access log" lab
import collections
log = """10.0.0.1 - - "GET /a HTTP/1.1" 200 12
10.0.0.2 - - "GET /b HTTP/1.1" 502 0
10.0.0.1 - - "GET /a HTTP/1.1" 200 12
bad line
"""
counts = collections.Counter()
for line in log.splitlines():
    parts = line.split()
    if len(parts) >= 2 and parts[-2].isdigit():
        counts[parts[-2]] += 1
print(dict(counts))     # {'200': 2, '502': 1}
```
@check
What happens to the malformed line in the example? || It is skipped because the status field is not numeric.
@end

@concept System design for operations roles
@plain
You will be asked to design something like a highly available web service. Interviewers want requirements first, then components, then failure.
@problem
Drawing boxes before understanding the need produces a design that answers no question.
@does
- Ask for traffic, data size, latency and availability targets. Convert them to numbers: 1 million requests a day is about 12 requests per second on average (1000000 divided by 86400); plan for a multiple at peak.
- Draw clients, DNS, load balancer, stateless app tier across three zones, database with replica, cache, queue.
- Walk through failures: zone loss, database failover, bad deploy, traffic spike. Add monitoring and rollout strategy.
@diagram flow
caption: A baseline highly available design
nodes:
  - "Users|global|ext"
  - "DNS and CDN|cache at edge|info"
  - "Load balancer|3 zones|cp"
  - "App tier|stateless, autoscaled|app"
  - "Database|primary and replica|ok"
@h Back of envelope
```python title="Capacity numbers" lab
per_day = 1_000_000
avg_rps = per_day / 86400
print("average rps", round(avg_rps, 1))
peak = avg_rps * 5
per_pod = 50
import math
pods = math.ceil(peak / per_pod)
print("peak rps", round(peak, 1), "pods needed", pods, "plus one zone of headroom", math.ceil(pods * 3 / 2))
```
@end

@concept Behavioural questions with STAR
@plain
STAR means Situation, Task, Action, Result. It keeps stories short and focused on what you did.
@problem
Stories without a result or without your own contribution are forgettable.
@does
- Prepare five stories: an outage you handled, a mistake you made, a disagreement, an improvement you led, and something you learned quickly.
- Quantify results honestly: "cut deploy time from 40 minutes to 12".
- For mistakes, show what you changed afterwards. Blameless language: describe systems, not people.
@diagram flow
caption: STAR in two minutes
numbered: true
nodes:
  - "Situation|one sentence of context|plain"
  - "Task|your responsibility|info"
  - "Action|what you did and why|app"
  - "Result|numbers and what you learned|ok"
@h Story bank
```yaml title="stories.yaml"
- title: Disk full outage
  situation: logs filled a node disk at night
  task: restore the service and prevent repeat
  action: cleared safely, added log rotation and a disk alert
  result: no repeat in six months
```
@check
What should follow the story of a mistake? || What you changed so it cannot happen again.
@end

@concept Questions to ask and the final week
@plain
Good questions show you care about operating reality. The final week is for rehearsal, not new topics.
@problem
Candidates arrive tired from cramming and unable to judge whether the job suits them.
@does
- Ask about on-call load and compensation, incident review habits, deployment frequency, how technical debt is prioritised, and what the first 90 days look like.
- Final week: two mock interviews, rebuild one lab from scratch, review your question bank and stories, sleep well.
- Be honest about gaps. "I have not used that, here is how I would learn it" is a good answer.
@diagram flow
caption: Final seven days
numbered: true
nodes:
  - "Days 7 to 5|fix weak topics|warn"
  - "Days 4 to 3|mock interviews|app"
  - "Day 2|review stories|info"
  - "Day 1|rest and logistics|ok"
@h Checklist
```bash title="Pre interview checklist" lab
cat <<'EOF'
[ ] Can explain the URL journey in two minutes
[ ] Can debug a CrashLoopBackOff aloud
[ ] Five STAR stories written
[ ] Three questions for the interviewer
[ ] Tested camera, network and a backup contact method
EOF
```
:::tip
After the interview, write down every question you struggled with and add it to your bank the same day.
:::
@end
