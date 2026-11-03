---
title: Docker troubleshooting scenarios 9 to 15
minutes: 55
objectives:
  - Diagnose Compose, healthcheck, signal, performance, platform and daemon problems
  - Use inspect, events and logs to find the cause quickly
  - Apply fixes that prevent recurrence
---
The remaining scenarios cover Compose projects, process behaviour inside containers and the daemon itself.

@concept Scenario 9, Compose service starts before its dependency is ready
@plain
The app container starts, tries the database, fails and exits, though the database container is "up".
@problem
`depends_on` waits for the container to start, not for the service to be ready.
@does
- Symptom: connection refused at start; works if restarted later.
- Confirm: logs of both services, timing of startup, the db's own readiness (Postgres takes seconds to accept connections).
- Fix: add a `healthcheck` to the dependency and `depends_on` with `condition: service_healthy`; add retry logic in the app; use `restart: on-failure` as a safety net.
- Verify with `docker compose ps` showing `healthy`.
@diagram flow
caption: Waiting for health
nodes:
  - "db starts|process up|warn"
  - "Healthcheck passes|pg_isready|info"
  - "app starts|condition service_healthy|app"
  - "Connection works|ok|ok"
@h Compose example
```yaml title="compose.yaml with health-based ordering"
services:
  db:
    image: postgres:16
    environment:
      POSTGRES_PASSWORD: example
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 3s
      retries: 10
  app:
    image: registry.example.com/shop/api:1.8.3
    depends_on:
      db:
        condition: service_healthy
    restart: on-failure
```
@check
What does plain depends_on guarantee? || Only that the dependency container has been started, not that its service is ready.
@end

@concept Scenario 10, container is unhealthy or stuck restarting
@plain
`docker ps` shows `(unhealthy)` or `Restarting`. A healthcheck fails, or the restart policy keeps relaunching a crashing process.
@problem
It is hard to see why the check fails because its output is hidden by default.
@does
- Symptom: status `unhealthy`; `Restarting (1) 5 seconds ago`.
- Confirm: `docker inspect --format '{{json .State.Health}}'` shows the last check outputs; run the check command manually with `docker exec`.
- Causes: curl not installed in the image, wrong port or path, too short `start_period`, process needs more time.
- Fix: install or use a tool that exists, adjust `start_period`, `interval`, `retries`; for restart loops fix the crash first (see scenario 1) and set a restart limit (`on-failure:5`).
@diagram flow
caption: Healthcheck debugging
nodes:
  - "unhealthy|status|bad"
  - "Health log|inspect State.Health|info"
  - "Run check by hand|docker exec|app"
  - "Tune or fix|start_period, command|ok"
@h Commands
```bash title="Inspect health" lab
docker inspect web --format '{{json .State.Health}}' | python3 -m json.tool | tail -20
docker exec web sh -c 'wget -qO- http://localhost:8080/healthz || echo failed'
docker events --since 10m --filter container=web --filter event=health_status
```
@end

@concept Scenario 11, container ignores stop and takes 10 seconds
@plain
`docker stop` waits ten seconds and then kills the container. The main process does not handle SIGTERM.
@problem
Slow deployments, lost in-flight requests and in Kubernetes slow rollouts and hung terminations.
@does
- Cause 1: shell form `CMD npm start` runs `/bin/sh -c`, so the shell is PID 1 and does not forward signals. Use exec form `CMD ["node","server.js"]` or `exec` in scripts.
- Cause 2: the process as PID 1 ignores default signal actions; use `--init` (tini) or `init: true` in Compose.
- Cause 3: the app has no SIGTERM handler; add graceful shutdown.
- Fix and verify: `time docker stop` should be quick; also set `STOPSIGNAL` if the app expects another signal.
@diagram flow
caption: Signal forwarding
nodes:
  - "docker stop|SIGTERM|plain"
  - "Shell as PID 1|does not forward|bad"
  - "Exec form or tini|signal reaches app|ok"
  - "Graceful exit|within seconds|ok"
@h Compare forms
```dockerfile title="Shell form versus exec form" nocheck
# Bad: sh is PID 1 and swallows SIGTERM
CMD npm start
# Good: node receives SIGTERM directly
CMD ["node", "server.js"]
```
```bash title="Test shutdown time" lab
docker run -d --name t --init registry.example.com/shop/api:1.8.3
time docker stop t
```
@check
Why use exec form for CMD? || The application runs as PID 1 and receives signals directly instead of a shell that does not forward them.
@end

@concept Scenario 12, slow file access on macOS bind mounts
@plain
Builds and tests are slow when the project directory is bind mounted into a container on macOS.
@problem
Files cross a VM boundary, so many small file operations are expensive.
@does
- Symptom: `npm install` or test runs are several times slower in a bind mount than inside the container.
- Confirm: time the same command in a named volume or the container's own filesystem.
- Fix: keep `node_modules` or build output in a named volume or anonymous volume rather than the bind mount; use virtiofs (Docker Desktop, Colima `--vm-type vz`); use file sync (Compose watch, `docker compose watch`) instead of mounting; develop inside the container or on a remote Linux host.
- Mount read-only when possible and exclude heavy folders.
@diagram cmp
caption: Mount strategies
cards:
  - {h: "Bind mount all", kind: warn, items: ["Simple", "Slow on macOS with many files"]}
  - {h: "Bind plus volume for deps", kind: ok, items: ["Source live", "node_modules in a volume"]}
  - {h: "Compose watch", kind: ok, items: ["Sync changed files", "Rebuild on manifest change"]}
@h Compose with watch
```yaml title="Compose develop.watch"
services:
  web:
    build: .
    develop:
      watch:
        - action: sync
          path: ./src
          target: /app/src
        - action: rebuild
          path: package.json
```
@end

@concept Scenario 13, wrong architecture: exec format error
@plain
A container fails with `exec format error` or a warning about platform mismatch.
@problem
Apple silicon (arm64) and cloud servers (often amd64) need images built for the right CPU.
@does
- Symptom: `exec /app: exec format error`, or `The requested image's platform (linux/amd64) does not match the detected host platform`.
- Confirm: `docker image inspect --format '{{.Os}}/{{.Architecture}}'`, `uname -m` on the host, and the manifest list of the tag.
- Fix: build multi-arch with `docker buildx build --platform linux/amd64,linux/arm64`, or choose the platform at run time with `--platform`; emulation (QEMU or Rosetta) works but is slower and can crash some binaries.
- In Kubernetes, make sure node architecture matches the image or use a multi-arch manifest.
@diagram flow
caption: Platform match
nodes:
  - "Image arch|amd64 only|warn"
  - "Host arch|arm64|info"
  - "Mismatch|exec format error|bad"
  - "Multi-arch image|manifest list|ok"
@h Commands
```bash title="Inspect and rebuild" lab
docker image inspect registry.example.com/shop/api:1.8.3 --format '{{.Os}}/{{.Architecture}}'
docker buildx imagetools inspect registry.example.com/shop/api:1.8.3
docker buildx build --platform linux/amd64,linux/arm64 -t registry.example.com/shop/api:1.8.4 --push .
```
@check
What is a manifest list? || An image index that points to one image per platform, so each host pulls the matching architecture.
@end

@concept Scenario 14, high CPU or a runaway container
@plain
One container takes all CPU or memory on a shared Docker host and other services slow down.
@problem
Without limits, one process can starve the host.
@does
- Symptom: load average high, `docker stats` shows one container at several hundred percent CPU, swap in use.
- Confirm: `docker stats`, `docker top c`, and `top` on the host; check for a loop, a crypto miner (compare with the expected process list) or a busy retry loop against a failing dependency.
- Fix: set `--cpus`, `--memory`, `--pids-limit` limits; fix the loop; if compromised, stop and isolate the container, preserve it for analysis (`docker export` or `docker commit` to an offline image), and rotate secrets.
- Prevent: resource limits in Compose and Kubernetes, monitoring, alerts on CPU throttling.
@diagram flow
caption: Runaway container
nodes:
  - "High load|host|bad"
  - "docker stats and top|which container, which process|info"
  - "Expected process?|compare|warn"
  - "Limit or isolate|fix root cause|ok"
@h Commands
```bash title="Find and limit" lab
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}'
docker top worker -eo pid,user,pcpu,args
docker update --cpus 1 --memory 512m --pids-limit 200 worker
```
@end

@concept Scenario 15, the Docker daemon will not start or hangs
@plain
`docker ps` reports `Cannot connect to the Docker daemon` or hangs. The daemon failed to start or is stuck.
@problem
Everything depending on Docker stops: builds, deployments on that host and local development.
@does
- Symptom: `Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?`; wrong context; socket permission denied for your user.
- Confirm: `docker context ls` (wrong context or `DOCKER_HOST` set), `systemctl status docker`, `journalctl -u docker -n 100`, `dockerd --validate` on the config.
- Causes: invalid `daemon.json`, full disk, corrupted storage, port or bridge IP conflict with VPN, user not in the `docker` group.
- Fix: correct the JSON, free disk, remove the conflicting setting (`bip`), add the user to the group and re-login; on Docker Desktop or Colima restart the VM (`colima restart`). Last resort: stop Docker and move `/var/lib/docker` aside (this loses local images and volumes).
@diagram flow
caption: Daemon triage
numbered: true
nodes:
  - "Right context?|docker context ls|plain"
  - "Service status|systemctl, journalctl|info"
  - "Config valid?|daemon.json|warn"
  - "Disk and network|df, bridge conflict|warn"
  - "Restart and verify|docker info|ok"
@h Commands
```bash title="Daemon checks" lab
docker context ls
systemctl status docker --no-pager | head -15
journalctl -u docker -n 50 --no-pager
python3 -m json.tool /etc/docker/daemon.json
df -h /var/lib/docker
```
@check
Name two quick checks when docker cannot connect to the daemon. || Whether the current context or DOCKER_HOST points to the right socket, and whether the docker service is running (systemctl status docker or colima status).
@end
