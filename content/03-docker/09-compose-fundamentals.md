---
title: Docker Compose fundamentals
minutes: 45
objectives:
  - Describe a multi service application in one compose.yaml file
  - Start, inspect, scale and stop a Compose project
  - Wire services together with networks, volumes and environment files
---
Compose describes a whole local stack, such as an API, a database and a cache, in one file and starts it with one command. It is the standard way to run a development environment and a good test harness in CI.

@concept What Compose is
@plain
Compose reads a YAML file (`compose.yaml`) that lists services, networks and volumes, and calls the Docker engine to create them. A set of running services is called a **project**.
@problem
Starting five containers by hand needs five long `docker run` commands in the right order with the right flags. Nobody remembers them, and teammates run them differently.
@does
- One file is the single source of truth for ports, environment, volumes and dependencies.
- The Compose Specification is used by `docker compose` (v2, a CLI plugin); the old `docker-compose` v1 binary and the top level `version:` key are obsolete.
- Each project gets its own default network and prefixes names with the project name (the folder name by default, change with `-p`).
- Compose is for a single host. For clusters use Kubernetes.
@diagram flow
caption: From file to running containers
numbered: true
nodes:
  - "compose.yaml|services, networks, volumes|env"
  - "docker compose up|reads and plans|app"
  - "Engine|creates network, volumes, containers|cp"
  - "Running stack|api, db, cache|ok"
@h Everyday commands
```bash title="Compose lifecycle" lab
docker compose up -d --build        # build images if needed and start in the background
docker compose ps                   # status and published ports
docker compose logs -f --tail 50 api
docker compose exec api sh          # shell inside a running service
docker compose down                 # stop and remove containers and networks (keeps volumes)
docker compose down -v              # also delete named volumes
```
@end

@concept A complete Python stack
@plain
A realistic file: a FastAPI app built from a local Dockerfile, a Postgres database with a persistent volume, and Redis.
@problem
Examples with one service hide the details that matter: service names as hostnames, volumes and ports.
@does
- `build:` builds the local Dockerfile; `image:` pulls a ready image.
- The API reaches Postgres at host `db` and Redis at host `cache`, since service names are DNS names on the project network.
- Only the API publishes a port, on localhost; the database is not exposed.
- `${VAR:-default}` reads from the shell or a `.env` file next to the compose file.
@diagram layers
caption: Services on one project network
layers:
  - {label: "Host", nodes: ["127.0.0.1:8000|published port|ext"]}
  - {label: "Project network default", nodes: ["api|FastAPI, built locally|app", "db|postgres:16|ok", "cache|redis:7|ok"]}
  - {label: "Volumes", nodes: ["pgdata|database files|env"]}
@h compose.yaml
```yaml title="compose.yaml (Python)"
name: shop
services:
  api:
    build: .
    ports:
      - "127.0.0.1:8000:8000"
    environment:
      DATABASE_URL: postgresql://shop:${DB_PASSWORD:-devpass}@db:5432/shop
      REDIS_URL: redis://cache:6379/0
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
    restart: unless-stopped
  db:
    image: postgres:16
    environment:
      POSTGRES_USER: shop
      POSTGRES_PASSWORD: ${DB_PASSWORD:-devpass}
      POSTGRES_DB: shop
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U shop -d shop"]
      interval: 5s
      timeout: 3s
      retries: 10
  cache:
    image: redis:7-alpine
volumes:
  pgdata:
```
```bash title="Validate and run" lab
docker compose config --quiet && echo "valid"
docker compose up -d
docker compose ps
```
@end

@concept Networks, DNS and ports in Compose
@plain
Compose creates one network called `<project>_default` and attaches every service. Services find each other by service name.
@problem
Developers hardcode `localhost` for a database that lives in another container, which fails because each container has its own localhost.
@does
- `localhost` inside a container is that container; use the service name.
- `ports: "8000:8000"` is for the host to reach the container. Service to service traffic needs no `ports`.
- `expose:` is documentation only. Define extra networks to split frontend and backend.
- Aliases: `networks: { backend: { aliases: [database] } }`.
@diagram cmp
caption: Which address to use
cards:
  - {h: "From your laptop", kind: info, items: ["localhost:8000", "Needs ports: published", "Prefer 127.0.0.1 binding"]}
  - {h: "From another service", kind: ok, items: ["db:5432", "Service name is the host", "No ports: needed"]}
  - {h: "From the container itself", kind: warn, items: ["localhost means itself", "Not the database", "Common mistake"]}
@h Two networks
```yaml title="Frontend and backend isolation"
services:
  proxy:
    image: nginx:1.27-alpine
    ports: ["8080:80"]
    networks: [frontend]
  api:
    image: shop-api:dev
    networks: [frontend, backend]
  db:
    image: postgres:16
    environment: {POSTGRES_PASSWORD: devpass}
    networks: [backend]
networks:
  frontend: {}
  backend:
    internal: true
```
@check
Why does connecting to localhost:5432 from the API container fail? || Localhost is the API container itself; the database is reached at db:5432.
@end

@concept Volumes and bind mounts in Compose
@plain
Compose declares named volumes at the top level and mounts them into services. A relative path such as `./src` becomes a bind mount.
@problem
Without volumes, `docker compose down` and `up` recreates containers with empty databases.
@does
- Short form `pgdata:/var/lib/postgresql/data` or long form with `type`, `source`, `target`, `read_only`.
- Bind mounts for live reload during development; named volumes for state.
- Anonymous volume trick: add `/app/node_modules` as an empty volume so the host folder does not hide installed dependencies.
- `docker compose down -v` deletes named volumes; use it deliberately.
@diagram flow
caption: Live reload loop for a Node service
nodes:
  - "Edit on laptop|src/index.js|plain"
  - "Bind mount ./src|same files in container|env"
  - "node --watch|restarts the process|app"
  - "Browser refresh|new behaviour|ok"
@h Node stack with a dev bind mount
```yaml title="compose.yaml (Node)"
name: web
services:
  web:
    build:
      context: .
      target: dev
    ports:
      - "127.0.0.1:3000:3000"
    environment:
      NODE_ENV: development
      MONGO_URL: mongodb://mongo:27017/web
    volumes:
      - ./src:/app/src
      - /app/node_modules
    command: ["node", "--watch", "src/index.js"]
    depends_on:
      mongo:
        condition: service_started
  mongo:
    image: mongo:7
    volumes:
      - mongodata:/data/db
volumes:
  mongodata:
```
@end

@concept Environment variables and .env files
@plain
Compose can substitute variables into the YAML itself and pass them into containers. These are two different things.
@problem
Confusion about which `.env` does what leads to missing values and committed secrets.
@does
- `.env` next to `compose.yaml`: values used for `${VAR}` substitution in the YAML file.
- `env_file: [app.env]`: loads every line into the container's environment.
- `environment:` entries win over `env_file`; shell variables win over `.env`.
- Add `.env` and `*.env` to `.gitignore`; commit an `.env.example`.
- `docker compose config` prints the final merged and substituted file.
@diagram rows
caption: Precedence from highest to lowest
rows:
  - {arrows: true, items: ["Shell or CLI -e|highest|ok", "environment key|in compose.yaml|app", "env_file|file entries|info", "Image ENV|lowest|plain"]}
@h Inspect
```bash title="See what Compose will really use" lab
printf 'DB_PASSWORD=s3cret\n' > .env
docker compose config | grep -A3 environment
DB_PASSWORD=override docker compose config | grep POSTGRES_PASSWORD
```
:::warn
Environment variables are visible in `docker inspect` and in `/proc/<pid>/environ`. For real credentials use Compose secrets (next section).
:::
@end

@concept Build, scale and override files
@plain
Compose merges several files, so one base file serves development, test and CI with small overrides.
@problem
A single file full of `if dev` hacks is unreadable. Different environments need different ports, mounts and images.
@does
- `compose.yaml` plus `compose.override.yaml` are merged automatically.
- Choose files explicitly: `docker compose -f compose.yaml -f compose.ci.yaml up`.
- `docker compose up -d --scale worker=3` runs three replicas (the service must not set a fixed `container_name` or host port).
- `docker compose watch` with `develop.watch` syncs or rebuilds on file changes, an alternative to bind mounts.
@diagram flow
caption: Layering files
nodes:
  - "compose.yaml|base services|env"
  - "compose.override.yaml|dev mounts and ports|info"
  - "Merged result|docker compose config|ok"
@h Override example
```yaml title="compose.override.yaml"
services:
  api:
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - ./:/app
    command: ["uvicorn", "main:app", "--host", "0.0.0.0", "--reload"]
```
```bash title="Develop with watch and scale workers" lab
docker compose -f compose.yaml -f compose.override.yaml config --quiet
docker compose up -d --scale worker=3
```
@end
