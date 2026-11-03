---
title: Dockerfile fundamentals
minutes: 45
objectives:
  - Write a Dockerfile using FROM, WORKDIR, COPY, RUN, ENV, EXPOSE and CMD correctly
  - Choose between CMD and ENTRYPOINT and between shell and exec form
  - Keep the build context small with dockerignore
---
A Dockerfile is a recipe: each instruction produces a layer or metadata. Small habits here decide image size, build speed and whether signals reach your app.

@concept Anatomy of a Dockerfile
@plain
A Dockerfile is a text file of instructions run top to bottom by the builder. The first must be `FROM`, which names the starting image.
@problem
Setting up a runtime by hand is slow and not repeatable. A Dockerfile records every step so anyone gets the same image from the same inputs.
@does
- `FROM` base image. `WORKDIR` sets the directory (and creates it).
- `COPY` brings files from the build context. `RUN` executes a command at build time.
- `ENV` sets variables; `ARG` is build-time only. `EXPOSE` documents a port; it does not publish it.
- `CMD` or `ENTRYPOINT` defines what runs at container start.
@diagram flow
caption: Build time versus run time
nodes:
  - "FROM|choose the base|plain"
  - "COPY and RUN|build layers|app"
  - "Image|stored layers|info"
  - "CMD|runs at container start|ok"
@h A first Dockerfile
```dockerfile title="Dockerfile" nocheck
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
```bash title="Build and run" lab
docker build -t myapp:dev .
docker run --rm -p 8000:8000 myapp:dev
```
@end

@concept COPY, ADD and the build context
@plain
`docker build .` sends the directory `.` (the **context**) to the builder. `COPY` can only read files from inside it.
@problem
Without control, `node_modules`, `.git`, `.env` files and test data are uploaded and may be copied into the image, slowing builds and leaking secrets.
@does
- `.dockerignore` lists patterns excluded from the context, like `.gitignore`.
- `COPY --chown=app:app` sets ownership during copy (no extra layer).
- Prefer `COPY` over `ADD`. `ADD` also unpacks tar files and fetches URLs, which is rarely wanted.
- `COPY --from=stage` takes files from another build stage.
@diagram flow
caption: Only what survives dockerignore reaches the builder
nodes:
  - "Project folder|all files|plain"
  - ".dockerignore|filters out|warn"
  - "Build context|sent to BuildKit|info"
  - "COPY|selected files into a layer|ok"
@h Typical ignore file
```text title=".dockerignore" nocheck
.git
.env
.env.*
node_modules
__pycache__
*.pyc
.venv
dist
coverage
Dockerfile
docker-compose*.yaml
*.md
```
:::warn
Never rely on a later `rm` to remove secrets copied by `COPY`; the earlier layer keeps them. Exclude them with `.dockerignore`.
:::
@end

@concept RUN, shell form and exec form
@plain
`RUN` runs commands while building. Instructions come in two syntaxes: shell form (`RUN apt-get update`) runs via `/bin/sh -c`; exec form (`["cmd","arg"]`) runs the program directly.
@problem
Each `RUN` creates a layer. Splitting install and cleanup into separate layers keeps the junk in the image forever.
@does
- Chain related commands with `&&` and clean up in the same `RUN`.
- For apt: `apt-get update && apt-get install -y --no-install-recommends pkg && rm -rf /var/lib/apt/lists/*`.
- Use `set -eux` in long scripts, or `SHELL ["/bin/bash","-o","pipefail","-c"]` so pipes fail loudly.
- Always pin versions you care about.
@diagram cmp
caption: One layer or three
cards:
  - {h: "Three RUN lines", kind: bad, items: ["update, install, cleanup separately", "Cache stays in a lower layer", "Image is larger"]}
  - {h: "One RUN with &&", kind: ok, items: ["Install and clean together", "Single smaller layer", "Stale apt index never cached alone"]}
@h Example
```dockerfile title="apt install done right" nocheck
FROM debian:12-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*
```
@end

@concept CMD versus ENTRYPOINT
@plain
`ENTRYPOINT` is the fixed program; `CMD` is the default arguments, easy to override at `docker run`.
@problem
Choosing wrong makes images awkward: users cannot pass flags, or cannot replace the command to debug.
@does
- `CMD ["python","app.py"]` alone is fully replaced by `docker run img other-command`.
- `ENTRYPOINT ["python","app.py"]` stays; extra words after the image name are appended as arguments.
- Together, `ENTRYPOINT ["curl"]` plus `CMD ["--help"]` gives a tool with default args.
- Override the entrypoint with `docker run --entrypoint sh img` for debugging.
- Kubernetes names differ: `command` replaces ENTRYPOINT, `args` replaces CMD.
@diagram rows
caption: How the final command is assembled
rows:
  - {arrows: true, items: ["ENTRYPOINT|fixed program|cp", "CMD|default arguments|info", "docker run args|replace CMD|warn"]}
  - {arrows: false, items: ["Final command|ENTRYPOINT then arguments|ok"]}
@h Try it
```bash title="Override behaviour" lab
printf 'FROM alpine:3.20\nENTRYPOINT ["echo","hello"]\nCMD ["world"]\n' | docker build -q -t ep-demo -
docker run --rm ep-demo              # hello world
docker run --rm ep-demo docker       # hello docker (CMD replaced)
docker run --rm --entrypoint date ep-demo   # entrypoint replaced
```
@check
What is the Kubernetes equivalent of ENTRYPOINT? || The container field command; args maps to CMD.
@end

@concept Exec form and signal handling
@plain
Shell form wraps your program in `/bin/sh -c`, making the shell PID 1. The shell does not forward SIGTERM, so the app never shuts down gracefully.
@problem
`docker stop` and Kubernetes pod termination wait the full grace period, then SIGKILL, dropping in-flight requests.
@does
- Use exec form for `CMD`/`ENTRYPOINT`: `CMD ["node","server.js"]`.
- If a wrapper script is needed, end it with `exec "$@"` so the app replaces the shell.
- PID 1 also must reap zombies; add `--init` (tini) for apps that spawn children.
- Do not run `npm start` as PID 1; call `node` directly because npm does not forward signals reliably.
@diagram seq
caption: Shell form swallows the signal
actors: ["Docker|stop request|cp", "sh|PID 1|warn", "App|child|app"]
steps:
  - "0>1: SIGTERM | req"
  - "note 1..2: sh ignores it, app never hears"
  - "0>1: SIGKILL after 10 s | bad"
@h Entrypoint script pattern
```bash title="docker-entrypoint.sh" lab
#!/bin/sh
set -e
# run migrations or render config, then hand over PID 1 to the app
echo "starting with LOG_LEVEL=${LOG_LEVEL:-info}"
exec "$@"
```
```dockerfile title="Using it" nocheck
COPY docker-entrypoint.sh /usr/local/bin/
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["node", "server.js"]
```
@end

@concept ENV, ARG and configuration
@plain
`ARG` exists only during build. `ENV` persists into the image and every running container.
@problem
Mixing them up leaks values: anything in `ENV` or `ARG` is visible in `docker history` and `docker inspect`.
@does
- `ARG VERSION=1.0` then `docker build --build-arg VERSION=2.0`.
- `ENV PORT=8000` gives a default overridable with `docker run -e PORT=9000`.
- Never place passwords or tokens in either. Use build secrets for build time and runtime secrets from the platform.
- Twelve-factor apps read configuration from the environment; images stay identical across environments.
@diagram cmp
caption: ARG versus ENV
cards:
  - {h: "ARG", kind: info, items: ["Build time only", "Set with --build-arg", "Still visible in history"]}
  - {h: "ENV", kind: app, items: ["Build and run time", "Override with -e", "Visible in inspect"]}
  - {h: "Secret mount", kind: ok, items: ["Build time only", "Never stored in a layer", "RUN --mount=type=secret"]}
@h Example
```bash title="Passing configuration" lab
printf 'FROM alpine:3.20\nARG VERSION=1.0\nENV APP_VERSION=$VERSION\nCMD ["sh","-c","echo version $APP_VERSION"]\n' > /tmp/Dockerfile.env
docker build -q -t env-demo -f /tmp/Dockerfile.env --build-arg VERSION=2.5 /tmp
docker run --rm env-demo
docker run --rm -e APP_VERSION=override env-demo
```
@end
