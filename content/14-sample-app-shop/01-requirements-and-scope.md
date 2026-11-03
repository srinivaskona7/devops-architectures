---
title: The Shop - requirements and scope
minutes: 45
objectives:
  - Turn a business idea into functional and non-functional requirements with numbers
  - Size the system from order volume and derive request rates and storage
  - Record scope, risks and success measures before any code exists
---
The Shop is one worked example that ties the whole curriculum together. It is a small e-commerce system with a catalog, a cart, orders, payments (including a mock UPI gateway) and a plain HTML frontend. Every other folder teaches a tool; this folder shows those tools working as one project, from the first requirement to the handover pack. We refer to the other folders by name instead of repeating them: [Docker](../03-docker/), [Kubernetes](../04-kubernetes/), [Terraform](../05-terraform/), [CI/CD](../06-cicd/), [Monitoring](../07-monitoring-alerting/) and [ELK](../08-elk-stack/).

@concept What we are building and why
@plain
An online shop for an Indian retailer. Customers browse products, fill a cart, place an order and pay by UPI. Staff manage products and watch orders.
@problem
Tool tutorials in isolation never show how decisions interact: the Dockerfile shapes the pipeline, the pipeline shapes the cluster, the cluster shapes the alerts. A single project shows the whole chain.
@does
- Defines five runtime parts: `catalog`, `cart`, `orders`, `payments` and a `web` frontend, plus `upi-mock` in non-production.
- Uses PostgreSQL for catalog, orders and payments data, and Redis for carts.
- Runs on AWS EKS in region ap-south-1, built with Terraform, deployed with Argo CD.
- Is deliberately small so every file fits on a screen, yet complete enough to build, test, scan, deploy, break and recover.
@diagram flow
caption: The Shop from browser to data
nodes:
  - "Browser|customer|ext"
  - "web|static HTML and nginx|app"
  - "catalog, cart, orders, payments|FastAPI services|app"
  - "Postgres and Redis|state|cp"
@end

@concept Personas and user journeys
@plain
A persona is a short description of a type of user. A journey is the ordered list of things that persona does.
@problem
Without journeys, teams build endpoints nobody calls and miss the one flow that earns money.
@does
- Shopper: browse products, add to cart, checkout, pay with UPI, see order status.
- Store admin: create or update products, adjust stock.
- Operator (us): deploy, watch dashboards, answer alerts, restore from backup.
- The shopper checkout journey is the critical path. Later chapters attach the main SLO, load test and runbooks to it.
@diagram flow
caption: The checkout journey that earns money
nodes:
  - "Browse|GET products|plain"
  - "Add to cart|PUT cart item|plain"
  - "Place order|POST orders|info"
  - "Pay by UPI|POST payments|warn"
  - "Confirmation|order paid|ok"
@check
Which journey becomes the basis of the SLO? || Checkout, because a failure there loses revenue directly.
@end

@concept Functional requirements
@plain
A list of what the system must do, written so each line can be tested.
@problem
Vague wishes such as "support payments" cannot be tested, estimated or accepted.
@does
- FR1 List and search products with price in paise (integer, 1 rupee = 100 paise).
- FR2 A cart holds sku and quantity per user and expires after 7 days of inactivity.
- FR3 An order reserves stock, records items and prices at purchase time, and has a status of pending, paid, failed or cancelled.
- FR4 A payment is created once per order (idempotent) and settled by a UPI collect request to a gateway.
- FR5 A slow gateway reports PENDING and later calls a signed webhook with the final result.
- FR6 Failed payment releases the reserved stock.
@diagram cmp
caption: In scope versus out of scope
cards:
  - {h: "In scope", kind: ok, items: ["Catalog, cart, orders, payments", "UPI collect with a mock gateway", "Single currency INR", "Admin API for products"]}
  - {h: "Out of scope", kind: warn, items: ["Real PSP or NPCI integration", "Shipping and tax engines", "Multi-currency, refunds", "Customer login (a user id header is used)"]}
@end

@concept Non-functional requirements with numbers
@plain
Non-functional requirements describe how well the system works: speed, availability, security, cost, recoverability.
@problem
"Fast and reliable" has no value to an engineer. A number can be measured, alerted on and paid for.
@does
- Availability SLO for checkout 99.9 percent over 30 days (error budget 43.2 minutes, shown in the observability file).
- Latency: 95th percentile of `POST /orders` under 800 ms; catalog reads under 200 ms.
- Recovery: RPO 5 minutes (RDS point-in-time restore), RTO 60 minutes.
- Security: no long-lived cloud keys in CI, secrets from a secret manager, images scanned, pods non-root.
- Cost: production under about 600 USD per month at launch scale (worked later).
@diagram layers
caption: Requirements grouped by concern
layers:
  - {label: "Reliability", nodes: ["SLO 99.9 percent|checkout|ok", "RPO 5 min, RTO 60 min|recovery|ok"]}
  - {label: "Performance", nodes: ["p95 orders under 800 ms|write path|info", "p95 catalog under 200 ms|read path|info"]}
  - {label: "Security and cost", nodes: ["OIDC, no static keys|CI|warn", "Under 600 USD per month|prod|warn"]}
@end

@concept Capacity estimate with the arithmetic
@plain
Turn the business forecast into requests per second and storage so that replica counts and instance sizes are not guesses.
@problem
Over-provisioning wastes money; under-provisioning fails on the first sale day.
@does
- Forecast 20,000 orders per day. Assume 15 percent of them fall in the busiest hour: 20,000 x 0.15 = 3,000 orders per hour = 0.83 orders per second.
- Assume 30 API requests per order across browse, cart and checkout: 0.83 x 30 = 25 requests per second.
- Apply a 3x headroom factor for spikes: 75 requests per second.
- One uvicorn worker handles roughly 150 requests per second for these light handlers (measure with k6 before trusting), so 75 / 150 = 0.5 workers. Three replicas are chosen for availability, not for throughput.
- Storage: 20,000 orders per day x 365 days x 2 KB per order and items = about 14.6 GB per year. A 50 GB gp3 volume is ample for the first year.
@diagram flow
caption: From forecast to sizing
nodes:
  - "20,000 orders per day|forecast|info"
  - "0.83 orders per second|busy hour|plain"
  - "25 requests per second|x 30 requests|plain"
  - "75 requests per second|x 3 headroom|warn"
  - "3 replicas|for availability|ok"
@h Check the numbers
```python title="capacity.py" lab
orders_per_day = 20_000
busy_hour_share = 0.15
requests_per_order = 30
headroom = 3
per_worker_rps = 150

orders_per_sec = orders_per_day * busy_hour_share / 3600
rps = orders_per_sec * requests_per_order
target = rps * headroom
print(f"orders/s={orders_per_sec:.2f} rps={rps:.0f} target={target:.0f}")
print(f"workers needed={target / per_worker_rps:.2f}")
print(f"storage GB/year={orders_per_day * 365 * 2 / 1e6:.1f}")
```
@end

@concept Constraints, assumptions and risks
@plain
Constraints are fixed facts, assumptions are things we believe but have not proven, risks are things that could hurt.
@problem
Unwritten assumptions turn into surprises in production.
@does
- Constraint: AWS only at launch, EKS for compute, existing GitHub organisation.
- Assumption: traffic is mostly India daytime; the per-worker 150 rps figure holds (verify with k6).
- Risk: payment gateway latency stalls checkout. Mitigation: timeouts, PENDING state, webhook completion.
- Risk: stock oversell under concurrency. Mitigation: atomic conditional update in SQL.
- Keep a short register in the repo and review it each release.
@diagram flow
caption: A risk becomes a control becomes a test
nodes:
  - "Risk|gateway slow|bad"
  - "Control|timeout and PENDING|info"
  - "Test|chaos drill and unit test|app"
  - "Alert|burn rate on checkout|ok"
@h Risk register in the repo
```yaml title="docs/risks.yaml"
- id: R1
  risk: Payment gateway latency stalls checkout
  likelihood: medium
  impact: high
  control: 3 second timeout, PENDING state, signed webhook
  verified_by: tests/test_payments.py and the incident drill
- id: R2
  risk: Stock oversell under concurrent orders
  likelihood: medium
  impact: high
  control: single UPDATE with stock >= qty condition
  verified_by: tests/test_catalog.py
```
@end

@concept Definition of done and success measures
@plain
A checklist that says when a feature or the whole project is finished and healthy.
@problem
Projects drift when "done" means "merged".
@does
- Feature done: code, unit tests, container builds, manifests, dashboard panel, alert if user facing, runbook line.
- Release done: deployed to staging, smoke tests green, load test within budget, rollback tested.
- Project done: handover pack accepted, disaster recovery test passed, on-call trained.
- Measure DORA metrics (see the CI/CD folder) to know whether the process is working.
@diagram flow
caption: Done grows as the change moves right
nodes:
  - "Merged|tests pass|plain"
  - "Deployed|staging smoke ok|info"
  - "Observed|dashboard and alert|app"
  - "Operable|runbook and drill|ok"
@check
Is a merged pull request done? || No. It must also be deployable, observable and covered by a runbook if it is user facing.
@end

@concept How this folder is organised
@plain
The files follow the life of the project: decide, build, run locally, provision, deploy, observe, secure, hand over, port.
@problem
A learner needs to know where to look and in which order.
@does
- Files 1 to 2: requirements, architecture and repository.
- Files 3 to 6: the application, tests and frontend.
- Files 7 to 8: environments, branching, containers and Compose.
- Files 9 to 12: Terraform and Kustomize.
- Files 13 to 15: pipelines, Argo CD, rollout and upgrade.
- Files 16 to 17: observability, security, load and cost.
- File 18: handover, then the same app on Azure and GCP.
@diagram flow
caption: Reading order
nodes:
  - "Decide|files 1 to 2|info"
  - "Build|files 3 to 8|app"
  - "Provision and deploy|files 9 to 15|cp"
  - "Operate|files 16 to 18|ok"
@end
