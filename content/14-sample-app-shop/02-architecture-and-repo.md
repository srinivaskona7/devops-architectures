---
title: Architecture decisions and repository layout
minutes: 50
objectives:
  - Draw the Shop architecture at context and container level
  - Record decisions as short architecture decision records
  - Organise a mono-repo with services, infrastructure and deployment folders
---
This file fixes the architecture and the repository that all later files build on. For the general method of weighing options see the Architecture Decisions folder (13).

@concept System context and containers
@plain
A context view shows the system and who talks to it. A container view shows the deployable parts inside it.
@problem
Without a shared picture, every engineer holds a different model of the system.
@does
- External actors: shopper browser, admin, the UPI gateway (mock in staging, a payment provider in production).
- Inside: web (nginx), catalog, cart, orders, payments, plus PostgreSQL (RDS) and Redis (ElastiCache).
- Orders calls catalog and payments over HTTP inside the cluster. Payments calls the gateway outside.
- Only `web` is exposed through the load balancer. It proxies `/api/<service>/` to the Services.
@diagram flow
caption: Request path for a checkout
nodes:
  - "Browser|shopper|ext"
  - "ALB|HTTPS, ACM certificate|info"
  - "web|nginx proxy|app"
  - "orders|creates order|app"
  - "payments|UPI collect|app"
  - "UPI gateway|external|ext"
@end

@concept Sequence of a successful checkout
@plain
The order of calls between services for one purchase.
@problem
Hidden call chains cause hidden failure modes: each arrow is a place where a timeout can happen.
@does
- Orders checks prices and reserves stock in catalog, then writes a pending order.
- Orders asks payments to collect. Payments creates a payment row first, then calls the gateway.
- Success marks the order paid. Failure releases stock. PENDING waits for the webhook.
@diagram seq
caption: Checkout with a synchronous gateway answer
actors: ["web|browser path|ext", "orders|service|app", "catalog|service|app", "payments|service|app", "UPI gateway|collect API|ext"]
steps:
  - "0>1: POST /orders | req"
  - "1>2: reserve stock | req"
  - "2>1: reserved | resp"
  - "1>3: create payment | req"
  - "3>4: collect request | tls"
  - "4>3: SUCCESS | resp"
  - "3>1: paid | resp"
  - "1>0: 201 order paid | resp"
@end

@concept Technology choices at a glance
@plain
The stack, with one line of reason for each part.
@problem
Choices made by habit are hard to defend or change later.
@does
- Python 3.12 and FastAPI: fast to write, typed models, built-in OpenAPI docs.
- PostgreSQL on RDS: transactions for orders and payments. Redis on ElastiCache: cheap expiring carts.
- Containers on EKS: the stack your organisation already runs. Managed node groups keep node patching simple.
- Kustomize plus Argo CD: plain YAML with overlays, pull-based deploys.
- GitHub Actions with OIDC to AWS: no stored keys. A Jenkinsfile is included for teams that use Jenkins.
@diagram layers
caption: Stack by layer
layers:
  - {label: "Application", nodes: ["FastAPI|Python 3.12|app", "nginx|static web|app"]}
  - {label: "Data", nodes: ["RDS PostgreSQL|orders, payments, catalog|cp", "ElastiCache Redis|carts|cp"]}
  - {label: "Platform", nodes: ["EKS|managed nodes|info", "Argo CD|GitOps|info", "Kustomize|overlays|info"]}
  - {label: "Delivery", nodes: ["GitHub Actions|build, scan, push|ok", "ECR|images|ok"]}
@end

@concept Architecture decision records
@plain
An ADR is a half-page file that records one decision: context, the decision, and consequences. It lives in the repo next to the code.
@problem
Six months later nobody remembers why the team chose X, so they either fear changing it or change it blindly.
@does
- One file per decision in `docs/adr/`, numbered, never edited after acceptance; a new ADR supersedes an old one.
- Status values: proposed, accepted, superseded.
- Review ADRs in pull requests like code.
@diagram flow
caption: Lifecycle of an ADR
nodes:
  - "Proposed|pull request|plain"
  - "Discussed|review comments|info"
  - "Accepted|merged|ok"
  - "Superseded|new ADR links back|warn"
@h Template
```markdown title="docs/adr/0000-template.md" nocheck
# ADR NNNN Title
Status: proposed | accepted | superseded by ADR NNNN
Date: YYYY-MM-DD

## Context
What forces are at play? Numbers, constraints, deadlines.

## Decision
We will ...

## Consequences
Good, bad and what we must now do.
```
@end

@concept ADR 1 - services split by domain, not by layer
@plain
Each business domain (catalog, cart, orders, payments) is its own small service with its own data.
@problem
One big service is simple but deploys together, scales together and fails together. Splitting by technical layer (an "API service", a "DB service") creates chatty coupling.
@does
- Decision: four services, each owning its tables or keys; no service reads another service's tables.
- Payments is separate because it needs stricter security, its own scaling and its own on-call attention.
- Consequence: cross-service calls need timeouts and idempotency, which later files implement.
- Rejected: a single modular monolith. It would be a fair choice for a team of two; revisit if the team stays small.
@diagram cmp
caption: Options considered
cards:
  - {h: "Modular monolith", kind: info, items: ["One deploy, simple", "Shared failure and scaling", "Good for a tiny team"]}
  - {h: "Service per domain (chosen)", kind: ok, items: ["Independent deploys", "Network calls need care", "Matches ownership of teams"]}
  - {h: "Service per layer", kind: bad, items: ["Chatty coupling", "Every change touches all", "No clear owner"]}
@h The record
```markdown title="docs/adr/0001-service-per-domain.md" nocheck
# ADR 0001 Split by business domain
Status: accepted
Context: 4 domains, different scaling and security needs. Team of 6.
Decision: one service per domain, each owns its data.
Consequences: network timeouts, idempotency keys, per-service pipelines.
```
@end

@concept ADR 2 - one RDS instance, a database per service
@plain
Catalog, orders and payments each get their own database and database user, but share one RDS instance at launch.
@problem
One RDS instance per service would cost four times as much; one shared schema would let services read each other's data.
@does
- Decision: one multi-AZ PostgreSQL instance, three databases, three users with access only to their own database.
- Cart uses Redis, not Postgres, because carts are temporary and read often.
- Consequence: the instance is a shared failure point and a noisy-neighbour risk. Split payments to its own instance when load or compliance requires.
- Credentials are different per service and come from Secrets Manager (see the Kustomize files).
@diagram layers
caption: Shared instance, separate databases
layers:
  - {label: "RDS PostgreSQL multi-AZ", nodes: ["db catalog|user catalog|cp", "db orders|user orders|cp", "db payments|user payments|cp"]}
  - {label: "ElastiCache Redis", nodes: ["cart keys|TTL 7 days|info"]}
@end

@concept ADR 3 - GitOps with Argo CD and Kustomize
@plain
The cluster state is described in Git. A controller in the cluster pulls and applies it.
@problem
CI pipelines holding cluster-admin credentials are a large attack surface and drift silently when someone runs `kubectl edit`.
@does
- Decision: CI builds and pushes an image, then commits the new image tag into the deploy folder; Argo CD syncs it.
- Kustomize overlays hold per-environment differences, so there is no template language to learn.
- Consequence: rollback is a Git revert; the CI role needs only ECR push, not cluster access.
- See the CI/CD folder for Argo CD internals and the Kubernetes folder for Kustomize basics.
@diagram flow
caption: Push versus pull deploy
nodes:
  - "CI builds image|push to ECR|app"
  - "Commit tag to Git|deploy folder|info"
  - "Argo CD|pulls and syncs|cp"
  - "Cluster|desired state|ok"
@end

@concept Repository layout
@plain
One mono-repo holds services, infrastructure and deployment so that one pull request can change code and manifests together.
@problem
Scattered repositories make cross-cutting changes hard and let versions drift.
@does
- `services/<name>/` holds code, tests, Dockerfile and requirements for each service.
- `web/` holds the static frontend and nginx config.
- `infra/` holds Terraform modules and environment roots.
- `deploy/` holds Kustomize `base/` and `overlays/`.
- `.github/workflows/` and `Jenkinsfile` hold pipelines; `docs/` holds ADRs and runbooks; `loadtest/` holds k6.
@diagram layers
caption: Mono-repo top level
layers:
  - {label: "Code", nodes: ["services|four Python services|app", "web|HTML and nginx|app", "upi-mock|test gateway|app"]}
  - {label: "Platform", nodes: ["infra|Terraform|cp", "deploy|Kustomize|cp", "compose.yaml|local dev|info"]}
  - {label: "Process", nodes: [".github|workflows|ok", "docs|ADRs and runbooks|ok", "loadtest|k6|ok"]}
@h Tree
```text title="Repository tree" nocheck
shop/
  services/
    catalog/   app/ tests/ Dockerfile requirements.txt
    cart/      app/ tests/ Dockerfile requirements.txt
    orders/    app/ tests/ Dockerfile requirements.txt
    payments/  app/ tests/ Dockerfile requirements.txt
    upi-mock/  app/ tests/ Dockerfile requirements.txt
  web/         index.html nginx.conf Dockerfile
  infra/       modules/ envs/dev envs/staging envs/prod
  deploy/      base/ overlays/dev overlays/staging overlays/prod
  docs/        adr/ runbooks/
  loadtest/    checkout.js
  compose.yaml Jenkinsfile Makefile
  .github/workflows/
```
@end
