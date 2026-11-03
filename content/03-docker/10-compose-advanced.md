---
title: Compose profiles, health and secrets
minutes: 45
objectives:
  - Order startup with healthcheck based depends_on conditions
  - Use profiles to include optional services such as debug tools and test runners
  - Handle credentials with Compose secrets and apply resource limits and hardening
---
A basic Compose file starts containers. A good one starts them in the right order, keeps secrets out of environment variables and can switch parts on or off.

@concept depends_on conditions
@plain
`depends_on` controls start order. By default it waits only until the dependency container has started, not until it is ready to serve.
@problem
The API starts before Postgres accepts connections and crashes with "connection refused". Restart loops hide the real ordering problem.
@does
- `condition: service_started` is the default and means the container process was launched.
- `condition: service_healthy` waits for the dependency's healthcheck to pass.
- `condition: service_completed_successfully` waits for a one-shot container such as a migration job to exit 0.
- `restart: true` under a dependency restarts the dependant when the dependency is restarted by Compose.
@diagram seq
caption: Startup ordering with a healthcheck and a migration job
actors: ["db|postgres|ok", "migrate|one shot job|env", "api|web service|app"]
steps:
  - "note 0..0: starts, healthcheck runs"
  - "0>0: pg_isready passes: healthy | resp"
  - "1>0: runs migrations | req"
  - "1>1: exit 0 | resp"
  - "2>0: starts and connects | req"
@h Example
```yaml title="Ordered startup with a migration job"
services:
  db:
    image: postgres:16
    environment: {POSTGRES_PASSWORD: devpass}
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 3s
      retries: 20
  migrate:
    image: shop-api:dev
    command: ["python", "-m", "alembic", "upgrade", "head"]
    depends_on:
      db: {condition: service_healthy}
  api:
    image: shop-api:dev
    depends_on:
      db: {condition: service_healthy}
      migrate: {condition: service_completed_successfully}
```
@check
What does service_healthy require that service_started does not? || The dependency must define a healthcheck and it must report healthy.
@end

@concept Healthchecks in Compose
@plain
A `healthcheck:` block in the service overrides or adds to the Dockerfile `HEALTHCHECK`. Compose uses it for ordering and `docker compose up --wait`.
@problem
CI scripts need to know when the stack is really ready, not just started. Sleep statements are fragile.
@does
- `test:` as `["CMD", ...]` (no shell) or `["CMD-SHELL", "..."]`.
- Tune `interval`, `timeout`, `retries` and `start_period` (failures during the start period do not count).
- `docker compose up -d --wait` blocks until services are running and healthy, then returns an exit code.
- Common tests: `pg_isready`, `redis-cli ping`, `mysqladmin ping`, `wget -qO- localhost/healthz`.
@diagram flow
caption: A CI job waits for health
numbered: true
nodes:
  - "compose up -d --wait|starts stack|app"
  - "Healthchecks run|every 5 seconds|info"
  - "All healthy|command returns 0|ok"
  - "Run tests|against localhost ports|app"
@h Examples
```yaml title="Healthchecks for common services"
services:
  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 2s
      retries: 10
  api:
    image: shop-api:dev
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"]
      interval: 10s
      timeout: 3s
      start_period: 15s
      retries: 5
```
```bash title="Wait for readiness in CI" lab
docker compose up -d --wait --wait-timeout 120 && echo "stack ready"
```
@end

@concept Profiles
@plain
A profile tags a service so it only starts when you ask for that profile. Services without a profile always start.
@problem
Debug tools, database admin UIs, test runners and seeders should not run in every environment, and separate compose files for each are noisy.
@does
- `profiles: ["debug"]` on a service.
- `docker compose --profile debug up` or `COMPOSE_PROFILES=debug,test`.
- A service explicitly named on the command line starts even if its profile is not active: `docker compose run --rm tests`.
- Dependencies between a profiled service and a non-profiled one work as expected.
@diagram cmp
caption: Which services start with which profile
cards:
  - {h: "No profile flag", kind: ok, items: ["api", "db", "cache"]}
  - {h: "--profile debug", kind: warn, items: ["api, db, cache", "adminer", "mailpit"]}
  - {h: "--profile test", kind: info, items: ["api, db, cache", "tests runner", "seed data job"]}
@h Example
```yaml title="Optional services with profiles"
services:
  api:
    image: shop-api:dev
  db:
    image: postgres:16
    environment: {POSTGRES_PASSWORD: devpass}
  adminer:
    image: adminer:4
    profiles: ["debug"]
    ports: ["127.0.0.1:8081:8080"]
  tests:
    image: shop-api:dev
    profiles: ["test"]
    command: ["pytest", "-q"]
    depends_on: [db]
```
```bash title="Use them" lab
docker compose up -d                      # api and db only
docker compose --profile debug up -d      # plus adminer
docker compose run --rm tests             # explicit run starts the test service
```
@end

@concept Secrets
@plain
A Compose secret mounts a file into the container at `/run/secrets/<name>`. The value never appears in environment variables or `docker inspect`.
@problem
Passwords in `environment:` leak through `inspect`, process listings, crash dumps and child processes.
@does
- Define top level `secrets:` from a `file:` (or an `environment:` variable on the host).
- Reference them in a service; the file is read-only and in tmpfs.
- Official images support the `_FILE` convention: `POSTGRES_PASSWORD_FILE=/run/secrets/db_password`.
- Your own app should read the file path variable instead of the value.
- Compose secrets are file mounts on one host. In Kubernetes the same idea is a Secret volume, preferably backed by an external store.
@diagram flow
caption: A secret travels as a file, not as an environment value
nodes:
  - "secrets/db_password.txt|on host, git ignored|ext"
  - "Compose secret|mounted read only|env"
  - "/run/secrets/db_password|inside container|app"
  - "App reads the file|value in memory only|ok"
@h Example
```yaml title="Postgres with a secret file"
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
  api:
    image: shop-api:dev
    environment:
      DB_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
secrets:
  db_password:
    file: ./secrets/db_password.txt
```
```python title="Reading a secret file in Python"
import os, pathlib

def read_secret(name: str, default: str | None = None) -> str | None:
    path = os.environ.get(f"{name}_FILE")
    if path:
        return pathlib.Path(path).read_text().strip()
    return os.environ.get(name, default)

db_password = read_secret("DB_PASSWORD")
```
:::danger
Do not commit `secrets/` to Git. Add it to `.gitignore` and generate files in CI from your secret manager.
:::
@end

@concept Resource limits, restart policy and hardening
@plain
Compose can apply the same limits and security options as `docker run`, so a development stack mirrors production settings.
@problem
A stack that works unlimited and root in development fails in Kubernetes with OOMKilled or a Pod Security rejection.
@does
- `mem_limit` and `cpus` (or `deploy.resources.limits` which Compose v2 also honours).
- `read_only: true`, `tmpfs: [/tmp]`, `cap_drop: [ALL]`, `security_opt: [no-new-privileges:true]`, `user: "10001:10001"`.
- `restart: unless-stopped` for services, `restart: "no"` for jobs.
- `init: true` adds a tiny init process to reap zombies and forward signals.
- `stop_grace_period: 30s` for slow shutdowns.
@diagram layers
caption: Hardening applied per service
layers:
  - {label: "Identity", nodes: ["user 10001|non-root|ok", "no-new-privileges|no setuid escalation|ok"]}
  - {label: "Filesystem", nodes: ["read_only true|immutable root|ok", "tmpfs /tmp|scratch space|warn"]}
  - {label: "Resources", nodes: ["mem_limit 256m|OOM instead of host swap|warn", "cpus 0.5|quota|warn", "pids_limit 200|fork bomb guard|warn"]}
@h Example
```yaml title="Hardened service"
services:
  api:
    image: shop-api:dev
    user: "10001:10001"
    read_only: true
    tmpfs:
      - /tmp
    cap_drop: [ALL]
    security_opt:
      - no-new-privileges:true
    init: true
    mem_limit: 256m
    cpus: 0.5
    pids_limit: 200
    stop_grace_period: 20s
    restart: unless-stopped
```
```bash title="Check the effective configuration" lab
docker compose config | grep -E 'read_only|cap_drop|mem_limit|user'
docker stats --no-stream
```
@end

@concept Compose as a CI test harness
@plain
Compose can start the real dependencies of your tests (database, queue, mock services) inside a CI job, run the tests, and always clean up.
@problem
Tests that mock the database miss real bugs. Shared test databases cause flaky runs.
@does
- A unique project name per run (`-p ci-$GITHUB_RUN_ID`) avoids clashes on shared runners.
- `--exit-code-from tests` returns the tests container exit code; `--abort-on-container-exit` stops everything when it ends.
- Always run `docker compose down -v` in an `always()` step.
- On failure, print `docker compose logs` as a build artefact.
@diagram flow
caption: CI job around a Compose stack
numbered: true
nodes:
  - "compose up --wait|dependencies ready|app"
  - "Run tests|inside the tests service|info"
  - "Collect logs|on failure|warn"
  - "compose down -v|always|ok"
@h CI script
```bash title="ci-test.sh" lab
#!/usr/bin/env bash
set -euo pipefail
export COMPOSE_PROJECT_NAME="ci-${GITHUB_RUN_ID:-local}"
trap 'docker compose logs --no-color > compose.log || true; docker compose down -v --remove-orphans' EXIT
docker compose --profile test up --build --abort-on-container-exit --exit-code-from tests
```
@end
