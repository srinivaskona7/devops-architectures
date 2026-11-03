---
title: Security review, load testing with k6 and cost estimate
minutes: 65
objectives:
  - Review the Shop against a layered security checklist and fix the findings
  - Load test the checkout path with k6 and read the results against the SLO
  - Estimate the monthly AWS cost for prod and dev and find the largest savings
---
Before launch three reviews are done: security, performance and cost. Each produces numbers and a short list of actions.

@concept Security review by layer
@plain
Walk the system from the outside in and check one control per layer. Record what is done, what is accepted risk and what is open.
@problem
Security found by an auditor after launch costs far more than the same findings fixed during build.
@does
- Edge: HTTPS only (ACM), WAF rules for common attacks and rate limits, only `web` and the webhook path are public.
- Identity: OIDC for CI, IRSA for pods, EKS access entries for people, no long-lived keys anywhere.
- Workload: non-root, read-only filesystem, no privilege escalation, Pod Security `restricted`, NetworkPolicy default deny.
- Data: encryption at rest (RDS, ElastiCache, EBS), in transit (TLS to Redis), secrets in Secrets Manager only.
- Supply chain: pinned base images, Trivy scan gate, immutable tags, SBOM and signatures (see CI/CD folder).
- Detection: audit logs, CloudTrail, GuardDuty for EKS (check the current feature set).
@diagram layers
caption: Defence in depth
layers:
  - {label: "Edge", nodes: ["ALB and WAF|TLS, rate limit|info", "Public paths only|web, webhook|ok"]}
  - {label: "Cluster", nodes: ["Pod Security restricted|namespace label|ok", "NetworkPolicy|default deny|ok", "Access entries|SSO roles|ok"]}
  - {label: "Data", nodes: ["RDS encrypted|private subnets|cp", "Secrets Manager|ESO via IRSA|cp"]}
  - {label: "Pipeline", nodes: ["OIDC no keys|CI|ok", "Trivy gate|images|ok", "Branch protection|CODEOWNERS|ok"]}
@end

@concept Application-level security findings
@plain
The code review looks for the classic web risks (OWASP Top 10) in the Shop's own logic.
@problem
Infrastructure hardening does not stop a missing authorisation check.
@does
- Authentication: the demo uses an `X-User-Id` header. In production a gateway or an OIDC identity provider validates a token and sets the header; the services must reject requests that do not come through it (NetworkPolicy plus a signed header).
- Authorisation: `GET /orders/{id}` checks the owner (done in the code). Admin routes (`POST /products`) must be limited to an admin role; add that before launch.
- Input: pydantic validates sizes and patterns; SQLAlchemy uses bound parameters (no string-built SQL).
- Money: integer paise, amount limit in payments, idempotency key, signed webhook with constant-time compare.
- Logging: VPA masked; never log tokens.
@diagram cmp
caption: Findings and status
cards:
  - {h: "Done in code", kind: ok, items: ["Owner check on orders", "Parameterised SQL", "HMAC webhook", "VPA masked in logs"]}
  - {h: "Open before launch", kind: warn, items: ["Admin role on product writes", "Gateway validates user token", "Rate limit per user", "Dependency audit in CI"]}
@h Add an admin guard
```python title="services/catalog/app/admin.py"
import os

from fastapi import Header, HTTPException


def require_admin(x_admin_token: str = Header(default="")) -> None:
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(403, "admin only")
```
:::note
A shared static token is the minimum; replace it with role claims from your identity provider. Use it with `Depends(require_admin)` on the product write routes.
:::
@end

@concept Threat model of the payment path
@plain
List who could attack the payment flow, how, and which control stops it. Use STRIDE headings as a prompt.
@problem
Payments are the highest-value target; a gap here is a financial loss.
@does
- Spoofing: forged webhook. Control: HMAC with a per-environment secret, constant-time compare.
- Tampering: changed amount. Control: payments uses the amount stored by orders at purchase time; the client never supplies price.
- Repudiation: customer denies paying. Control: payment row, gateway reference, logs with order id.
- Information disclosure: VPA or order data in logs. Control: masking, Loki access limited by role.
- Denial of service: flood on the webhook path. Control: WAF rate rule, small request body limit, cheap signature check first.
- Elevation of privilege: pod compromise reaches the database. Control: separate DB users per service, NetworkPolicy, non-root.
@diagram flow
caption: Attack to control
nodes:
  - "Forged webhook|spoofing|bad"
  - "HMAC check|control|ok"
  - "Replay of old webhook|tampering|bad"
  - "Idempotent update|control|ok"
@check
Why does the webhook handler ignore events for payments that are no longer PENDING? || A replayed or duplicated event must not change a settled payment, so the handler is idempotent.
@end

@concept Load test design with k6
@plain
k6 is a load testing tool that runs JavaScript scenarios. It sends the same journey as a shopper: browse, add to cart, check out.
@problem
Guesses about capacity fail on the first big sale. A test shows where the system bends before real customers do.
@does
- Target from the capacity estimate: 25 requests per second normal, 75 with headroom. In a closed model the virtual users needed follow Little's law: users = rate x time per iteration. At 2.5 orders per second (3x the 0.83 busy-hour rate) and 6 seconds per full journey (about 30 requests with think time) that is 2.5 x 6 = 15 users.
- Scenario types: smoke (1 user, 1 minute), load (target for 10 minutes), stress (increase until errors), soak (target for hours to find leaks).
- Thresholds turn the test into a pass/fail gate: `http_req_failed < 0.001` and `http_req_duration p(95) < 800`.
- Always test staging with the mock gateway, never prod and never a real payment provider.
@diagram flow
caption: Test types
nodes:
  - "Smoke|1 user, 1 minute|plain"
  - "Load|target rate, 10 minutes|ok"
  - "Stress|ramp until errors|warn"
  - "Soak|target for hours|info"
@h Check Little's law
```python title="littles_law.py" lab
orders_per_sec_busy = 20_000 * 0.15 / 3600
target = orders_per_sec_busy * 3
seconds_per_journey = 6
print("busy hour orders/s:", round(orders_per_sec_busy, 2))
print("test rate orders/s:", round(target, 2))
print("virtual users needed:", round(target * seconds_per_journey, 1))
```
@end

@concept The k6 script
@plain
One scenario with a ramping arrival rate, a journey function and thresholds.
@problem
A constant-VU test hides latency problems: when the server slows, fewer requests are sent, so the test looks better than reality (coordinated omission). An arrival-rate executor keeps sending at the planned rate.
@does
- `ramping-arrival-rate` goes from 1 to 2.5 iterations per second in 2 minutes, holds for 10, and ramps down.
- Each iteration lists products, adds one to the cart and posts an order with a random VPA suffix mix: 90 percent `okbank`, 5 percent `okfail`, 5 percent `okslow`.
- `check` counts expected statuses: 201 for paid, 402 for the failing VPA.
- Run with `k6 run -e BASE=https://shop-staging.example.com loadtest/checkout.js`.
@diagram seq
caption: One iteration
actors: ["k6|virtual user|ext", "web|nginx|app", "services|catalog cart orders|app"]
steps:
  - "0>1: GET products | req"
  - "1>2: proxy | req"
  - "0>1: PUT cart item | req"
  - "0>1: POST order | req"
  - "2>1: 201 or 402 | resp"
  - "1>0: response | resp"
@h loadtest/checkout.js
```javascript title="loadtest/checkout.js" nocheck
import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

const BASE = __ENV.BASE || 'http://localhost:8080';

export const options = {
  scenarios: {
    checkout: {
      executor: 'ramping-arrival-rate',
      startRate: 1, timeUnit: '1s',
      preAllocatedVUs: 30, maxVUs: 100,
      stages: [
        { target: 2.5, duration: '2m' },
        { target: 2.5, duration: '10m' },
        { target: 0, duration: '1m' },
      ],
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    'http_req_duration{name:order}': ['p(95)<800'],
  },
};

function pickVpa() {
  const r = Math.random();
  if (r < 0.90) return 'load@okbank';
  if (r < 0.95) return 'load@okfail';
  return 'load@okslow';
}

export default function () {
  const user = `u${__VU}-${__ITER}`;
  const h = { headers: { 'X-User-Id': user, 'Content-Type': 'application/json' } };

  http.get(`${BASE}/api/catalog/products`, h);
  http.put(`${BASE}/api/cart/cart/items/SMOKE`, JSON.stringify({ qty: 1 }), h);
  sleep(1);

  const res = http.post(`${BASE}/api/orders/orders`,
    JSON.stringify({ items: [{ sku: 'SMOKE', qty: 1 }], vpa: pickVpa() }),
    { headers: { ...h.headers, 'Idempotency-Key': uuidv4() }, tags: { name: 'order' }, responseCallback: http.expectedStatuses(201, 402) });
  check(res, { 'order accepted or declined': (r) => r.status === 201 || r.status === 402 });
}
```
:::warn
The SMOKE product must have enough stock (set it to a large number) or orders return 409. Seed it with the smoke script before the run.
:::
@end

@concept Reading load test results
@plain
Compare the numbers with the SLO and look for the first resource that saturates.
@problem
A run that "passes" without being read teaches nothing. A failed run without a diagnosis is just noise.
@does
- Look at k6 summary: `http_req_duration` p95 and p99, `http_req_failed`, iteration rate achieved versus planned (dropped iterations mean the target could not keep up).
- On the Grafana dashboard find which resource hits its limit first: pod CPU near the limit, DB connections near the pool size (5 + 5 overflow per pod = 10), Redis latency, node CPU.
- Typical findings: HPA reacts too slowly (raise `minReplicas` before events), connection pool too small, CPU limit throttling (raise limit or remove it).
- Record the result in `docs/loadtest/<date>.md` with the commit SHA and the replica counts.
- Capacity statement example: "3 orders pods handled 2.5 orders per second with p95 420 ms and 38 percent CPU; limit estimated at 10 orders per second". Replace with your measured numbers.
@diagram flow
caption: Find the bottleneck
nodes:
  - "k6 p95 rises|symptom|warn"
  - "Which resource is full|dashboard|info"
  - "Fix or scale|one change|app"
  - "Run again|compare|ok"
@end

@concept AWS monthly cost estimate - prod
@plain
Add up each component using on-demand prices for ap-south-1 as an example, so the team knows the baseline.
@problem
Cloud bills surprise teams that never wrote down what each part costs. The biggest line items are usually compute, NAT gateways and databases.
@does
- Hours per month: 730. Prices below are illustrative on-demand figures; check the AWS pricing pages for the current values and region.
- EKS control plane 0.10 x 730 = 73.00. Nodes 3 x m6i.large at 0.096 x 730 = 210.24. NAT gateways 3 x 0.045 x 730 = 98.55 (plus data processing).
- RDS db.t4g.medium multi-AZ: 2 x 0.073 x 730 = 106.58; storage 50 GB x 2 x 0.115 = 11.50. Redis 2 x cache.t4g.small at 0.032 x 730 = 46.72.
- ALB: hours 0.0225 x 730 = 16.43 plus about 8 LCU average x 0.008 x 730 x 0.25 = 11.68 (assumption: a quarter of the time at 8 LCU). Secrets Manager 8 x 0.40 = 3.20, logs 20 GB x 0.50 = 10.00, ECR 1.00.
- Total about 588.89 USD per month, under the 600 target, before data transfer and support plans.
@diagram flow
caption: Largest items
nodes:
  - "Nodes|210|app"
  - "RDS and storage|118|cp"
  - "NAT gateways|99|warn"
  - "EKS control plane|73|info"
  - "Everything else|89|plain"
@h Add the lines
```python title="cost_prod.py" lab
h = 730
lines = {
    "EKS control plane": 0.10 * h,
    "3 x m6i.large": 3 * 0.096 * h,
    "3 NAT gateways": 3 * 0.045 * h,
    "RDS db.t4g.medium multi-AZ": 2 * 0.073 * h,
    "RDS storage 50 GB x 2": 50 * 0.115 * 2,
    "Redis 2 x cache.t4g.small": 2 * 0.032 * h,
    "ALB hours": 0.0225 * h,
    "ALB LCU": 8 * 0.008 * h * 0.25,
    "Secrets Manager 8": 8 * 0.40,
    "CloudWatch logs 20 GB": 20 * 0.50,
    "ECR": 1.0,
}
for name, cost in lines.items():
    print(f"{name:30} {cost:8.2f}")
print(f"{'TOTAL':30} {sum(lines.values()):8.2f}")
```
@end

@concept Dev and staging cost, and where to save
@plain
Non-production environments should cost a fraction of prod and should switch off when nobody uses them.
@problem
Dev and staging that run 24 hours at prod size can double the bill for no customer benefit.
@does
- Staging (2 x m6i.large 140.16, one NAT 32.85, multi-AZ RDS 118.08, Redis 46.72, EKS 73.00, ALB 16.43, misc 10) adds up to 437.24 if left on all month.
- Dev: EKS 73.00, 2 x t3.medium 0.0416 x 730 x 2 = 60.74, one NAT 32.85, db.t4g.micro 11.68, Redis 11.68, ALB 16.43, misc 10 = about 216.37 per month.
- Savings: scale dev and staging nodes to zero outside working hours (about 60 hours of 168 per week in use is 36 percent, so node hours drop by about 64 percent); a night-and-weekend schedule on dev nodes saves roughly 60.74 x 0.643 = 39.04 per month.
- Prod savings: Savings Plans or reserved instances for steady nodes (often 20 to 40 percent discount, check current terms), Graviton nodes (`m7g`) if images are arm64, Spot nodes for stateless dev workloads, VPC endpoints for ECR and S3 to cut NAT data charges.
- Tag everything (`project`, `env`) and use Cost Explorer and budgets with alerts at 80 percent of the monthly plan.
@diagram cmp
caption: Environment cost
cards:
  - {h: "Prod", kind: ok, items: ["About 589 USD per month", "Multi-AZ everything", "Always on"]}
  - {h: "Staging", kind: warn, items: ["About 437 USD if always on", "Schedule off at night", "Same shape as prod"]}
  - {h: "Dev", kind: info, items: ["About 216 USD", "Scale to zero off hours", "Single NAT"]}
@h Check the savings
```python title="dev_savings.py" lab
nodes_cost = 2 * 0.0416 * 730
in_use_hours, week_hours = 60, 168
saving = nodes_cost * (1 - in_use_hours / week_hours)
print("dev nodes per month:", round(nodes_cost, 2))
print("saving with schedule:", round(saving, 2))
```
:::note
EKS control plane and NAT gateway charges continue when nodes are scaled to zero. Dev totals fall by roughly 39 USD out of 216, not by half.
:::
@end
