---
title: Build cache and multi-stage builds
minutes: 45
objectives:
  - Order Dockerfile instructions so the layer cache is reused
  - Split build and runtime into stages to ship small images
  - Use BuildKit features such as cache mounts and secret mounts
---
A build that takes ten minutes on every commit wastes a team's day. The cache and multi-stage builds turn it into seconds and shrink the shipped image.

@concept How the layer cache works
@plain
For each instruction BuildKit checks whether it already built the same instruction on the same parent layer with the same inputs. If yes, it reuses the result; if not, that step and every step after it run again.
@problem
Reinstalling all dependencies after changing one line of source code is slow and wasteful.
@does
- For `RUN` the cache key is the command text and parent layer. For `COPY` it is the checksum of the copied files.
- A change in one layer invalidates all layers below it in the file.
- So put things that change rarely (OS packages, dependency manifests) first and source code last.
- `ARG` values and changed files used by an instruction also invalidate it.
@diagram flow
caption: A source change only rebuilds from COPY onward
nodes:
  - "FROM|cached|ok"
  - "COPY requirements|cached|ok"
  - "RUN pip install|cached|ok"
  - "COPY source|changed, rebuilt|warn"
  - "CMD|rebuilt|warn"
@h Bad order versus good order
```dockerfile title="Slow order, reinstalls on every edit" nocheck
FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt
```
```dockerfile title="Fast order, dependencies cached" nocheck
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
```
@check
Why copy requirements.txt before the rest of the code? || Its checksum rarely changes, so the pip install layer stays cached when only source files change.
@end

@concept Multi-stage builds
@plain
A Dockerfile can have several `FROM` lines. Each starts a new stage. The final image contains only the last stage, and you copy chosen files into it from earlier stages.
@problem
Compilers, dev dependencies and test tools are needed to build but are dead weight and attack surface at runtime.
@does
- `FROM node:22 AS build` names a stage; `COPY --from=build /app/dist ./dist` pulls artifacts.
- `docker build --target build .` stops at a stage, useful for running tests.
- Stages that are not needed by the target are skipped by BuildKit, and independent stages build in parallel.
- Typical result: a Go or Java service drops from over 800 MB to under 100 MB.
@diagram flow
caption: Build stage produces artifacts, runtime stage ships them
nodes:
  - "Stage build|compiler, dev dependencies|env"
  - "Artifacts|dist or wheels or binary|info"
  - "Stage runtime|slim base, non-root|app"
  - "Final image|only the last stage|ok"
@h Node example, complete
```dockerfile title="Dockerfile (Node, TypeScript)" nocheck
# syntax=docker/dockerfile:1
FROM node:22-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci

FROM deps AS build
COPY . .
RUN npm run build && npm prune --omit=dev

FROM node:22-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist
COPY --chown=node:node package.json ./
USER node
EXPOSE 3000
CMD ["node", "dist/server.js"]
```
@end

@concept Python multi-stage with a virtualenv
@plain
Python packages with native extensions need compilers to install. Build them in one stage into a virtualenv, then copy only that folder into a clean runtime stage.
@problem
Installing `gcc` and headers in the final image adds hundreds of megabytes and many CVEs.
@does
- Create `/opt/venv` in the builder and put it first in `PATH`.
- Copy `/opt/venv` to the runtime stage; both stages must use the same Python version and OS family.
- Add `PYTHONUNBUFFERED=1` so logs appear immediately and `PYTHONDONTWRITEBYTECODE=1` to avoid `.pyc` clutter.
@diagram layers
caption: What each stage contains
layers:
  - {label: "Builder stage (discarded)", nodes: ["gcc and headers|compile wheels|bad", "pip cache|downloaded files|bad", "/opt/venv|installed packages|info"]}
  - {label: "Runtime stage (shipped)", nodes: ["python slim|base|plain", "/opt/venv|copied from builder|app", "app code|your files|app", "USER app|non-root|ok"]}
@h Python example, complete
```dockerfile title="Dockerfile (Python, FastAPI)" nocheck
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
RUN groupadd --system --gid 10001 app && useradd --system --uid 10001 --gid app --no-create-home app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app . .
USER app
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
@end

@concept BuildKit cache mounts
@plain
`RUN --mount=type=cache` gives a build step a directory that persists between builds but is never stored in an image layer.
@problem
Even with layer caching, changing one dependency re-downloads all of them. Package manager caches are lost because they are deleted to keep layers small.
@does
- Targets: `/root/.cache/pip`, `/root/.npm`, `/go/pkg/mod`, `/var/cache/apt`, `~/.m2`.
- The mount is local to the builder; in CI it must be exported or stored in a remote cache to survive.
- Pair with `sharing=locked` for apt to avoid concurrent writes.
@diagram cmp
caption: Layer cache versus cache mount
cards:
  - {h: "Layer cache", kind: info, items: ["Whole step reused or rerun", "Any change redoes everything", "Stored in the image"]}
  - {h: "Cache mount", kind: ok, items: ["Folder kept between runs", "Only the changed packages download", "Never in the image"]}
@h apt with a cache mount
```dockerfile title="apt with cache mounts" nocheck
RUN rm -f /etc/apt/apt.conf.d/docker-clean
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends curl
```
@end

@concept Build secrets and SSH mounts
@plain
`RUN --mount=type=secret` makes a file available only during one build step. It is not written into any layer or the image history.
@problem
Private package registries and Git repositories need credentials at build time. `ARG` and `COPY` leave them in the image.
@does
- Supply with `docker build --secret id=npmrc,src=$HOME/.npmrc`.
- The file appears at `/run/secrets/<id>` inside that `RUN` only.
- `--mount=type=ssh` forwards your SSH agent for `git clone` of private repos.
@diagram flow
caption: The secret exists only for one RUN step
nodes:
  - "Host file|.npmrc|ext"
  - "docker build --secret|passes the file|info"
  - "RUN mount|visible in this step|warn"
  - "Image|contains no secret|ok"
@h Use it
```dockerfile title="Private npm registry" nocheck
RUN --mount=type=secret,id=npmrc,target=/root/.npmrc npm ci
```
```bash title="Build with the secret" lab
docker build --secret id=npmrc,src=$HOME/.npmrc -t app:dev .
docker history app:dev | grep -ci npmrc || echo "no trace in history"
```
:::danger
`ARG NPM_TOKEN` followed by `RUN npm config set` stores the token in the image history. Anyone with pull access can read it. Rotate any token that was ever built this way.
:::
@check
Where can you read a secret mounted with --mount=type=secret? || Only inside the RUN step that mounts it, at /run/secrets/<id> by default.
@end

@concept Heredocs, syntax directive and linting
@plain
Modern Dockerfile syntax allows multi-line scripts with heredocs and a version directive that enables newer features without upgrading Docker.
@problem
Long `&&` chains with backslashes are hard to read and easy to break.
@does
- First line `# syntax=docker/dockerfile:1` selects the current stable frontend.
- Heredoc: `RUN <<EOF ... EOF` runs a multi-line script; add `set -e` at the top.
- `docker build --check .` (BuildKit 0.15 and later) lints the Dockerfile for common mistakes.
- `hadolint` is a popular external linter for CI.
@diagram flow
caption: Feedback before the image is built
nodes:
  - "Edit Dockerfile|developer|plain"
  - "docker build --check|BuildKit rules|info"
  - "hadolint|style and shell rules|info"
  - "Build|only if clean|ok"
@h Heredoc example
```dockerfile title="Readable multi-line RUN" nocheck
# syntax=docker/dockerfile:1
FROM debian:12-slim
RUN <<EOF
set -eux
apt-get update
apt-get install -y --no-install-recommends curl ca-certificates
rm -rf /var/lib/apt/lists/*
EOF
```
```bash title="Lint" lab
docker build --check .
```
@end
