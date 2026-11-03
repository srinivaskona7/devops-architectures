---
title: Complete Node and Python services
minutes: 50
objectives:
  - Assemble a production grade Node service with Dockerfile, compose file and CI build
  - Assemble a production grade Python service with the same practices
  - Run a checklist that confirms the image is small, non-root, scanned, signed and reproducible
---
This section puts the preceding ideas into two complete, runnable projects. Copy them as starting points for your own services and compare them against the checklist at the end.

@concept Node service files
@plain
A small HTTP service with a health endpoint, graceful shutdown and a multi-stage Dockerfile that ends in a non-root runtime image.
@problem
Sample code is usually either trivial or missing production habits. This one has the minimum set that matters: pinned versions, cache mounts, non-root, healthcheck and signal handling.
@does
- `server.js` listens on `PORT`, answers `/healthz`, handles SIGTERM.
- `package.json` has zero dependencies, so `npm ci` works with a minimal lock file; add your framework later.
- The Dockerfile has `deps`, `test` and `runtime` stages.
- `.dockerignore` keeps the context to source files only.
@diagram flow
caption: Node project layout to image
nodes:
  - "package.json, lock|dependency layer|env"
  - "src/server.js|application|app"
  - "Dockerfile|deps, test, runtime|info"
  - "Image|non-root, health checked|ok"
@h Application
```javascript title="src/server.js" nocheck
const http = require('http');
const port = Number(process.env.PORT || 3000);

const server = http.createServer((req, res) => {
  if (req.url === '/healthz') {
    res.writeHead(200, { 'content-type': 'application/json' });
    return res.end('{"status":"ok"}');
  }
  res.writeHead(200, { 'content-type': 'text/plain' });
  res.end('hello from node\n');
});

server.listen(port, '0.0.0.0', () => console.log(JSON.stringify({ msg: 'listening', port })));

const shutdown = (signal) => {
  console.log(JSON.stringify({ msg: 'shutdown', signal }));
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 10000).unref();
};
process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));
```
```json title="package.json"
{
  "name": "shop-web",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "start": "node src/server.js",
    "test": "node --test"
  }
}
```
@h Dockerfile and ignore file
```dockerfile title="Dockerfile (Node)" nocheck
# syntax=docker/dockerfile:1
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm ci --omit=dev || npm install --omit=dev

FROM node:22-slim AS test
WORKDIR /app
COPY package.json package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm npm install
COPY . .
RUN npm test

FROM node:22-slim AS runtime
ENV NODE_ENV=production PORT=3000
WORKDIR /app
COPY --from=deps --chown=node:node /app/node_modules ./node_modules
COPY --chown=node:node package.json ./
COPY --chown=node:node src ./src
USER node
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "src/server.js"]
```
```text title=".dockerignore" nocheck
*
!package.json
!package-lock.json
!src
```
@end

@concept Node compose file and run
@plain
A compose file that builds the image, applies hardening and includes a MongoDB sidecar behind a profile.
@problem
Hardening that only exists in Kubernetes manifests is tested late. Applying it in Compose shows write-path problems on day one.
@does
- `target: runtime` builds the shipping stage.
- `read_only`, `tmpfs`, `cap_drop`, `no-new-privileges`, resource limits.
- Optional `mongo` service under the `db` profile.
- Healthcheck inherited from the image, with `up --wait` used to block until ready.
@diagram layers
caption: Compose stack for the Node service
layers:
  - {label: "Host", nodes: ["127.0.0.1:3000|published|ext"]}
  - {label: "Network", nodes: ["web|hardened Node image|app", "mongo|profile db|ok"]}
  - {label: "Storage", nodes: ["tmpfs /tmp|scratch|warn", "mongodata|named volume|env"]}
@h compose.yaml
```yaml title="compose.yaml (Node)"
name: shop-web
services:
  web:
    build:
      context: .
      target: runtime
    image: shop-web:dev
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      PORT: "3000"
    read_only: true
    tmpfs:
      - /tmp
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    init: true
    mem_limit: 256m
    cpus: 0.5
    pids_limit: 100
    restart: unless-stopped
  mongo:
    image: mongo:7
    profiles: ["db"]
    volumes:
      - mongodata:/data/db
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]
      interval: 10s
      timeout: 5s
      retries: 5
volumes:
  mongodata:
```
```bash title="Run and verify" lab
docker compose up -d --build --wait
curl -s localhost:3000/healthz
docker compose exec web id
docker compose stop web && docker compose logs web | tail -3       # graceful shutdown message
docker compose down
```
@end

@concept Python service files
@plain
A FastAPI service reading its database password from a secret file, with health endpoint and a multi-stage Dockerfile using a virtualenv.
@problem
Python images often run as root with pip caches inside, and read secrets from environment variables.
@does
- `main.py` serves `/` and `/healthz`, and reads `DB_PASSWORD_FILE` if set.
- `requirements.txt` pins versions; for stricter builds generate hashes with `pip-compile --generate-hashes`.
- Dockerfile builds the venv in the builder and copies it to a slim runtime as UID 10001.
- Compose mounts the secret file and adds a Postgres service with `service_healthy` ordering.
@diagram flow
caption: Python project to running stack
nodes:
  - "requirements.txt|pinned deps|env"
  - "Dockerfile|builder to runtime|info"
  - "compose.yaml|api, db, secret|app"
  - "docker compose up --wait|ready when healthy|ok"
@h Application files
```python title="main.py"
import os
import pathlib
from fastapi import FastAPI

app = FastAPI()


def read_secret(name: str) -> str | None:
    path = os.environ.get(f"{name}_FILE")
    return pathlib.Path(path).read_text().strip() if path else os.environ.get(name)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/")
def root():
    return {"service": "shop-api", "db_password_configured": bool(read_secret("DB_PASSWORD"))}
```
```text title="requirements.txt" nocheck
fastapi==0.115.0
uvicorn[standard]==0.30.6
```
@h Dockerfile
```dockerfile title="Dockerfile (Python)" nocheck
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 main.py .
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
@end

@concept Python compose file with a secret
@plain
Compose ties the API to Postgres, passes the password as a mounted file and waits for the database to be healthy.
@problem
The common shortcut of a plain-text password in `environment:` is exactly what leaks into logs and inspect output.
@does
- `secrets.db_password` reads from `./secrets/db_password.txt`.
- Postgres uses `POSTGRES_PASSWORD_FILE`; the API uses `DB_PASSWORD_FILE`.
- `depends_on` with `condition: service_healthy` avoids startup races.
- The API runs read-only with a tmpfs and no capabilities.
@diagram seq
caption: Start order and secret flow
actors: ["Compose|up --wait|cp", "db|postgres|ok", "api|FastAPI|app"]
steps:
  - "0>1: start with secret file | req"
  - "1>1: pg_isready passes | resp"
  - "0>2: start after healthy | req"
  - "2>1: connects using the secret | tls"
  - "2>0: healthy | resp"
@h compose.yaml
```yaml title="compose.yaml (Python)"
name: shop-api
services:
  api:
    build:
      context: .
      target: runtime
    image: shop-api:dev
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      DB_PASSWORD_FILE: /run/secrets/db_password
      DATABASE_HOST: db
    secrets:
      - db_password
    depends_on:
      db:
        condition: service_healthy
    read_only: true
    tmpfs: [/tmp]
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    mem_limit: 256m
    restart: unless-stopped
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: shop
      POSTGRES_DB: shop
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U shop -d shop"]
      interval: 5s
      timeout: 3s
      retries: 10
secrets:
  db_password:
    file: ./secrets/db_password.txt
volumes:
  pgdata:
```
```bash title="First run" lab
mkdir -p secrets && printf 'devpassword' > secrets/db_password.txt && echo 'secrets/' >> .gitignore
docker compose up -d --build --wait
curl -s localhost:8000/
docker inspect shop-api-api-1 --format '{{.Config.Env}}' | grep -c devpassword || echo "password not in environment"
docker compose down
```
@end

@concept Release checklist and capstone verification
@plain
Before an image goes to a registry, check it against a short, scriptable list. Each item maps to a concept covered in this section.
@problem
Quality that depends on people remembering is lost under deadline pressure. A script that fails the build is reliable.
@does
- Runs as non-root: `docker inspect --format '{{.Config.User}}'` is not empty or `root`.
- Has a healthcheck, exposes the expected port, has OCI labels.
- Size under a stated budget (for example 200 MB for Python, 150 MB for Node slim).
- No HIGH or CRITICAL fixable CVEs (Trivy).
- SBOM and provenance attached; image signed; deployed by digest.
- Starts with `--read-only --cap-drop ALL` and answers its health endpoint.
@diagram flow
caption: Gate sequence before promotion
numbered: true
nodes:
  - "Static checks|user, labels, size|info"
  - "Trivy scan|no fixable HIGH|warn"
  - "Runtime test|read only, cap drop|app"
  - "Sign and publish|cosign, digest|ok"
@h Checker script
```bash title="check-image.sh" lab
#!/usr/bin/env bash
set -euo pipefail
img=${1:?usage: check-image.sh IMAGE}
user=$(docker inspect "$img" --format '{{.Config.User}}')
[[ -n "$user" && "$user" != "root" && "$user" != "0" ]] || { echo "FAIL runs as root"; exit 1; }
hc=$(docker inspect "$img" --format '{{if .Config.Healthcheck}}yes{{else}}no{{end}}')
[[ "$hc" == yes ]] || { echo "FAIL no healthcheck"; exit 1; }
size_mb=$(( $(docker image inspect "$img" --format '{{.Size}}') / 1024 / 1024 ))
echo "size ${size_mb} MB"; (( size_mb < 250 )) || { echo "FAIL image over 250 MB"; exit 1; }
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 --quiet "$img"
cid=$(docker run -d --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges "$img")
trap 'docker rm -f "$cid" >/dev/null' EXIT
for _ in $(seq 1 20); do
  s=$(docker inspect "$cid" --format '{{.State.Health.Status}}')
  [[ "$s" == healthy ]] && { echo "PASS healthy under hardened flags"; exit 0; }
  sleep 2
done
echo "FAIL not healthy"; docker logs "$cid" | tail -5; exit 1
```
@end

@concept Local development workflow
@plain
The same Dockerfile and compose file serve development: a bind mounted source tree with auto reload, a dev stage with test tools, and a fast loop with `docker compose watch`.
@problem
When developers use a different setup than CI and production, bugs appear only after deployment.
@does
- A `dev` target in the Dockerfile installs dev dependencies and runs the reload server.
- `compose.override.yaml` adds the dev target, bind mount and debugger port, and is loaded automatically.
- `develop.watch` with `action: sync` copies changed files in and `action: rebuild` rebuilds when `package.json` or `requirements.txt` change.
- Production-like checks still run through `docker compose -f compose.yaml up` without the override.
@diagram flow
caption: Dev loop with compose watch
nodes:
  - "Edit source|laptop|plain"
  - "compose watch|sync or rebuild|info"
  - "Container reloads|uvicorn --reload|app"
  - "Browser|new behaviour|ok"
@h Watch configuration
```yaml title="compose.override.yaml with develop.watch"
services:
  api:
    build:
      target: runtime
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--reload"]
    develop:
      watch:
        - action: sync
          path: ./main.py
          target: /app/main.py
        - action: rebuild
          path: ./requirements.txt
```
```bash title="Start the loop" lab
docker compose up --build --watch
```
@end
