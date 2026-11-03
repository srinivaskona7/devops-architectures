---
title: Dockerfiles and local development with Compose
minutes: 55
objectives:
  - Write small non-root images for the Python services and the nginx web tier
  - Run the whole Shop locally with Docker Compose and Postgres and Redis
  - Test the stack end to end with a smoke script
---
The Docker folder explains each instruction; here we apply them. The multi-stage and cache chapters are in `03-docker/05-caching-multistage`.

@concept One Dockerfile for the Python services
@plain
All four services and the mock gateway use the same Dockerfile shape: build a virtualenv, copy it into a slim runtime image, run as a non-root user.
@problem
Per-service Dockerfiles that differ slightly create different CVEs and different bugs for every service.
@does
- Builder stage installs requirements into `/opt/venv` with a pip cache mount.
- Runtime stage has a numeric non-root user (UID 10001) so Kubernetes `runAsNonRoot` can verify it.
- `HEALTHCHECK` is omitted on purpose: Kubernetes probes replace it and Compose has its own check.
- The pytest dependency is excluded from the runtime by splitting `requirements.txt` and `requirements-dev.txt` in a real repo.
@diagram layers
caption: Image content
layers:
  - {label: "Builder (discarded)", nodes: ["pip install|with cache mount|bad", "/opt/venv|packages|info"]}
  - {label: "Runtime (shipped)", nodes: ["python 3.12 slim|base|plain", "/opt/venv|copied|app", "app folder|source|app", "USER 10001|non-root|ok"]}
@h services/catalog/Dockerfile
```dockerfile title="services/catalog/Dockerfile" nocheck
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
WORKDIR /src
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /srv
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 app ./app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
@end

@concept The web image and .dockerignore
@plain
The frontend image is the unprivileged nginx image with our static file and config copied in. A `.dockerignore` keeps tests, caches and secrets out of every build context.
@problem
Without `.dockerignore`, `.git`, virtualenvs and local `.env` files go into the build context, slow every build and can leak into images.
@does
- `nginxinc/nginx-unprivileged` listens on 8080 and runs as UID 101. Check the current tag and pin it by digest in production.
- The default site config is replaced with ours.
- `.dockerignore` excludes `.git`, `__pycache__`, `tests`, `.env`, `*.tfstate`.
@diagram flow
caption: Web image build
nodes:
  - "nginx unprivileged|base image|plain"
  - "COPY nginx.conf|routing|app"
  - "COPY index.html|static page|app"
  - "Image|port 8080|ok"
@h web/Dockerfile and .dockerignore
```dockerfile title="web/Dockerfile" nocheck
FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html /usr/share/nginx/html/index.html
EXPOSE 8080
```
```text title=".dockerignore" nocheck
.git
**/__pycache__
**/tests
**/.pytest_cache
.env
*.tfstate
*.tfstate.*
.terraform
```
@end

@concept Build and scan locally
@plain
Build an image, run it, and scan it before pushing, using the same commands CI uses.
@problem
Finding a failed build or a critical CVE only after pushing wastes a pipeline run.
@does
- `docker build` with `--tag shop/catalog:dev`.
- Trivy scans the image for OS and library CVEs; `--severity HIGH,CRITICAL --exit-code 1` fails on findings. Check the Trivy docs for current flags.
- `docker run --rm -p 8000:8000` with `DATABASE_URL` unset uses in-memory SQLite.
- Check size with `docker images`; expect roughly 150 to 250 MB for slim Python with FastAPI and SQLAlchemy.
@diagram flow
caption: Local loop
nodes:
  - "docker build|image|app"
  - "docker run|try it|info"
  - "trivy image|scan|warn"
  - "Push later|CI does it|ok"
@h Commands
```bash title="Build, run, scan" lab
docker build -t shop/catalog:dev services/catalog
docker run --rm -d --name cat -p 8000:8000 shop/catalog:dev
curl -s localhost:8000/healthz
docker rm -f cat
trivy image --severity HIGH,CRITICAL --exit-code 1 shop/catalog:dev
```
@end

@concept docker compose for the full stack
@plain
One `compose.yaml` starts Postgres, Redis, the four services, the mock gateway and the web tier on a private network.
@problem
New engineers lose days installing databases and wiring ports by hand.
@does
- Postgres initialises three databases and users from a mounted SQL script.
- Services read the same environment variable names as in Kubernetes (`DATABASE_URL`, `REDIS_URL`, `CATALOG_URL`).
- `depends_on` with `condition: service_healthy` waits for Postgres and Redis.
- Only web (8080) is published to the host, which mirrors the cluster's single entry point.
@diagram layers
caption: Compose stack
layers:
  - {label: "Edge", nodes: ["web|localhost 8080|app"]}
  - {label: "Services", nodes: ["catalog|8000|app", "cart|8000|app", "orders|8000|app", "payments|8000|app", "upi-mock|8000|ext"]}
  - {label: "State", nodes: ["postgres 16|three databases|cp", "redis 7|carts|cp"]}
@h compose.yaml
```yaml title="compose.yaml"
name: shop
x-service: &svc
  restart: unless-stopped
  networks: [shop]
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_PASSWORD: devpassword
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./docker/init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks: [shop]
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    networks: [shop]
  catalog:
    <<: *svc
    build: ./services/catalog
    environment:
      DATABASE_URL: postgresql+psycopg://catalog:catalog@postgres:5432/catalog
    depends_on:
      postgres: {condition: service_healthy}
  cart:
    <<: *svc
    build: ./services/cart
    environment:
      REDIS_URL: redis://redis:6379/0
    depends_on:
      redis: {condition: service_healthy}
  orders:
    <<: *svc
    build: ./services/orders
    environment:
      DATABASE_URL: postgresql+psycopg://orders:orders@postgres:5432/orders
      CATALOG_URL: http://catalog:8000
      PAYMENTS_URL: http://payments:8000
    depends_on:
      postgres: {condition: service_healthy}
  payments:
    <<: *svc
    build: ./services/payments
    environment:
      DATABASE_URL: postgresql+psycopg://payments:payments@postgres:5432/payments
      GATEWAY_URL: http://upi-mock:8000
      ORDERS_URL: http://orders:8000
      WEBHOOK_SECRET: dev-only-secret
    depends_on:
      postgres: {condition: service_healthy}
  upi-mock:
    <<: *svc
    build: ./upi-mock
    environment:
      WEBHOOK_SECRET: dev-only-secret
  web:
    <<: *svc
    build: ./web
    ports: ["8080:8080"]
    depends_on: [catalog, cart, orders]
networks:
  shop: {}
volumes:
  pgdata: {}
```
@end

@concept Database initialisation script
@plain
A SQL file runs once when the Postgres volume is first created and makes a database and a limited user per service.
@problem
If every service connects as the `postgres` superuser, one SQL injection or one bug reads and changes every table.
@does
- Creates users `catalog`, `orders`, `payments` with simple development passwords.
- Creates one database each and revokes `PUBLIC` access.
- The same pattern is applied on RDS by a one-time Kubernetes Job in the platform setup, with generated passwords stored in Secrets Manager.
@diagram flow
caption: First start of Postgres
nodes:
  - "Empty volume|first start|plain"
  - "init.sql|runs once|info"
  - "Users and databases|three each|cp"
  - "Services connect|limited rights|ok"
@h docker/init.sql
```sql title="docker/init.sql" nocheck
CREATE USER catalog  WITH PASSWORD 'catalog';
CREATE USER orders   WITH PASSWORD 'orders';
CREATE USER payments WITH PASSWORD 'payments';

CREATE DATABASE catalog  OWNER catalog;
CREATE DATABASE orders   OWNER orders;
CREATE DATABASE payments OWNER payments;

REVOKE ALL ON DATABASE catalog  FROM PUBLIC;
REVOKE ALL ON DATABASE orders   FROM PUBLIC;
REVOKE ALL ON DATABASE payments FROM PUBLIC;
```
:::warn
These passwords are for a laptop only. Never reuse them in any shared environment.
:::
@end

@concept Smoke test script
@plain
A short shell script that places an order through the web tier and checks the three outcomes: success, failure and late success.
@problem
Unit tests prove each service alone; they do not prove that the pieces are wired together.
@does
- Seeds one product through the catalog API, then posts orders with VPAs ending in `okbank`, `okfail` and `okslow`.
- Waits three seconds, then checks that the slow order became paid.
- Exit code is non-zero on any failure, so CI and the post-deploy step reuse it by changing `BASE`.
@diagram seq
caption: What the smoke script exercises
actors: ["smoke.sh|script|ext", "web|nginx|app", "orders|service|app", "upi-mock|gateway|ext"]
steps:
  - "0>1: POST order okbank | req"
  - "1>2: proxy | req"
  - "2>3: collect | req"
  - "3>2: SUCCESS | resp"
  - "0>1: POST order okslow | req"
  - "note 3..3: webhook after 2 seconds"
  - "0>1: GET order later | req"
@h scripts/smoke.sh
```bash title="scripts/smoke.sh" lab
#!/usr/bin/env bash
set -euo pipefail
BASE="${BASE:-http://localhost:8080}"
H=(-H "X-User-Id: smoke" -H "Content-Type: application/json")

curl -fsS "${H[@]}" -X POST "$BASE/api/catalog/products" \
  -d '{"sku":"SMOKE","name":"Smoke item","price_paise":10000,"stock":100}' >/dev/null || true

order() {
  curl -sS "${H[@]}" -H "Idempotency-Key: $(uuidgen)" -X POST "$BASE/api/orders/orders" \
    -d "{\"items\":[{\"sku\":\"SMOKE\",\"qty\":1}],\"vpa\":\"$1\"}" -w ' HTTP %{http_code}\n'
}

ok=$(order a@okbank);   echo "$ok";   grep -q '"paid"' <<<"$ok"
bad=$(order a@okfail);  echo "$bad";  grep -q 'HTTP 402' <<<"$bad"
slow=$(order a@okslow); echo "$slow"; grep -q '"pending"' <<<"$slow"
id=$(sed -E 's/.*"id":([0-9]+).*/\1/' <<<"$slow")
sleep 3
final=$(curl -fsS "${H[@]}" "$BASE/api/orders/orders/$id"); echo "$final"
grep -q '"paid"' <<<"$final"
echo "smoke ok"
```
```bash title="Run it" lab
docker compose up --build -d && sleep 10 && bash scripts/smoke.sh
```
@end
