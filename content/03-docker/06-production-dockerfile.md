---
title: Production ready Dockerfiles
minutes: 45
objectives:
  - Run containers as a non-root user with correct file ownership
  - Add HEALTHCHECK and handle graceful shutdown
  - Use labels, pinning and reproducible settings in Python and Node images
---
A Dockerfile that builds is not yet a Dockerfile you can run in production. This section adds the habits that avoid root, hung containers and mystery images.

@concept Running as non-root
@plain
By default the process in a container is root (UID 0). Create an unprivileged user and switch to it with `USER`.
@problem
If an attacker exploits the app, root inside the container has far more power: it can write anywhere in the image, bind low ports and use any granted capability. Kubernetes Pod Security `restricted` rejects root images.
@does
- Create a fixed numeric UID (such as 10001) so Kubernetes `runAsNonRoot` can verify it.
- Use `COPY --chown` and `RUN chown` only where the app must write.
- Ports below 1024 need root or a capability; use 8080 instead and map externally.
- Official `node` images already include user `node` (UID 1000).
@diagram cmp
caption: Root versus non-root process
cards:
  - {h: "Root (default)", kind: bad, items: ["UID 0 in the container", "Can modify any file", "Fails restricted pod policy"]}
  - {h: "Non-root", kind: ok, items: ["UID 10001", "Writes only to its own paths", "Passes runAsNonRoot"]}
@h Add a user
```dockerfile title="Debian based" nocheck
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
USER 10001:10001
```
```bash title="Verify" lab
docker run --rm myapp:dev id
docker run --rm myapp:dev sh -c 'touch /etc/x' 2>&1 | head -1   # permission denied expected
```
@end

@concept HEALTHCHECK
@plain
`HEALTHCHECK` tells Docker how to test whether the app inside works, not merely whether the process is alive.
@problem
A deadlocked web server still has a running process. Without a check, Docker and Compose report it as running and healthy-looking, and dependants start against it.
@does
- Options: `--interval=30s --timeout=3s --start-period=20s --retries=3`.
- Exit 0 healthy, 1 unhealthy. Status shows in `docker ps` and is used by Compose `depends_on` with `condition: service_healthy`.
- Slim images may lack `curl`; use a tiny script in the app language instead.
- Kubernetes ignores Dockerfile HEALTHCHECK. Define liveness and readiness probes in the pod spec.
@diagram flow
caption: Health states
nodes:
  - "starting|inside start period|info"
  - "healthy|check passes|ok"
  - "unhealthy|3 failures in a row|bad"
@h Python and Node checks
```dockerfile title="Python without curl" nocheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
```
```dockerfile title="Node 22 using fetch" nocheck
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD node -e "fetch('http://127.0.0.1:3000/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
```
```bash title="Read the status" lab
docker inspect -f '{{.State.Health.Status}}' web
docker inspect -f '{{json .State.Health.Log}}' web | python3 -m json.tool | tail -12
```
:::note
Kubernetes does not read HEALTHCHECK. Keep the endpoint and mirror it as `livenessProbe` and `readinessProbe`.
:::
@end

@concept Graceful shutdown
@plain
When asked to stop, your application should finish current requests, close connections and exit before the grace period ends.
@problem
Rolling deploys drop requests when the app dies mid-request, and Kubernetes pods hang for 30 seconds when SIGTERM is ignored.
@does
- `STOPSIGNAL SIGTERM` is the default; some servers (nginx) prefer `SIGQUIT`.
- Node: handle `SIGTERM` by calling `server.close()` then exiting.
- uvicorn and gunicorn handle SIGTERM themselves; plain Python scripts need `signal.signal`.
- Use `docker stop -t 30` or compose `stop_grace_period: 30s` for slow shutdowns.
@diagram seq
caption: Graceful stop in a Node service
actors: ["Docker|stop|cp", "Node app|PID 1|app", "Clients|in flight|ext"]
steps:
  - "0>1: SIGTERM | req"
  - "note 1..1: stop accepting, drain requests"
  - "1>2: finish responses | resp"
  - "1>0: exit 0 | resp"
@h Node handler
```javascript title="server.js shutdown" nocheck
const http = require('http');
const server = http.createServer((req, res) => {
  if (req.url === '/healthz') { res.writeHead(200); return res.end('ok'); }
  res.end('hello\n');
}).listen(process.env.PORT || 3000);

process.on('SIGTERM', () => {
  console.log('SIGTERM received, draining');
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 25000).unref();
});
```
@end

@concept Labels, pinning and reproducibility
@plain
Labels are metadata on the image. Pinned bases and lock files make the same source produce the same image.
@problem
During an incident you must tell which commit built an image running in production, and builds that float on `latest` change without anyone editing code.
@does
- OCI standard labels: `org.opencontainers.image.source`, `.revision`, `.version`, `.created`. GHCR uses `source` to link the package to the repo.
- Pin base images to a digest and let Renovate or Dependabot update it.
- Use lock files: `npm ci`, `pip install --require-hashes`, `uv sync --frozen`.
- Set `SOURCE_DATE_EPOCH` for timestamps when you need bit-for-bit builds.
@diagram flow
caption: From commit to traceable image
nodes:
  - "Git commit|abc1234|plain"
  - "Build args|REVISION, VERSION|info"
  - "Image labels|OCI annotations|app"
  - "Production|docker inspect shows commit|ok"
@h Example
```dockerfile title="Labels set at build time" nocheck
ARG REVISION=unknown
ARG VERSION=dev
LABEL org.opencontainers.image.source="https://github.com/acme/shop-api" \
      org.opencontainers.image.revision="$REVISION" \
      org.opencontainers.image.version="$VERSION"
```
```bash title="Build and read back" lab
docker build --build-arg REVISION=$(git rev-parse --short HEAD) --build-arg VERSION=1.4.2 -t shop-api:1.4.2 .
docker inspect shop-api:1.4.2 -f '{{json .Config.Labels}}'
```
@end

@concept A complete Python image
@plain
Putting the pieces together: multi-stage build, venv, non-root, health check, exec-form command and OCI labels.
@problem
Examples taught one flag at a time do not show how the parts fit.
@does
- Builder installs dependencies with a pip cache mount.
- Runtime copies only the venv and application code.
- Port 8000, user 10001, health check on `/healthz`.
- A matching `.dockerignore` keeps the context small.
@diagram flow
caption: Pipeline of the finished image
nodes:
  - "builder|pip install into venv|env"
  - "runtime|slim base, user 10001|app"
  - "HEALTHCHECK|python urllib|info"
  - "CMD|uvicorn exec form|ok"
@h main.py and Dockerfile
```python title="main.py"
from fastapi import FastAPI
app = FastAPI()

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"service": "shop-api"}
```
```text title="requirements.txt" nocheck
fastapi==0.115.0
uvicorn[standard]==0.30.6
```
```dockerfile title="Dockerfile" nocheck
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS builder
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

FROM python:3.12-slim
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=10001:10001 main.py .
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
```bash title="Build, run, probe" lab
docker build -t shop-api:dev .
docker run -d --name shop-api -p 8000:8000 shop-api:dev
sleep 12; docker ps --filter name=shop-api --format '{{.Names}} {{.Status}}'
curl -s localhost:8000/healthz
docker rm -f shop-api
```
@end

@concept Signals, PID 1 and the init process
@plain
The first process in a container is PID 1. The kernel treats it specially: signals without a handler are ignored, and orphaned child processes are re-parented to it.
@problem
An app that spawns children (shell scripts, workers) leaves zombies behind because it never calls wait, and a script as PID 1 ignores SIGTERM so every stop takes the full grace period.
@does
- `docker run --init` or Compose `init: true` injects `tini` as PID 1, which forwards signals and reaps zombies.
- In a Dockerfile you can install `tini` and use `ENTRYPOINT ["tini", "--"]`.
- Kubernetes has no `--init` flag; use `shareProcessNamespace` carefully, or put tini in the image.
- Check with `docker exec NAME ps -o pid,stat,comm` and look for `Z` states.
@diagram flow
caption: tini as PID 1
nodes:
  - "docker stop|SIGTERM|cp"
  - "tini PID 1|forwards the signal|info"
  - "App child|shuts down cleanly|app"
  - "Zombies|reaped by tini|ok"
@h Try it
```bash title="Run with an init process" lab
docker run -d --name withinit --init alpine:3.20 sleep 300
docker exec withinit ps -o pid,ppid,comm
time docker stop withinit          # returns at once because SIGTERM is forwarded
docker rm withinit
```
@end
