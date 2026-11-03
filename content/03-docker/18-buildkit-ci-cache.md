---
title: BuildKit and CI build caching
minutes: 45
objectives:
  - Explain how BuildKit schedules builds as a graph and why that is faster than the legacy builder
  - Persist build cache across CI runs with registry, GitHub Actions and S3 cache backends
  - Measure and reduce build time with context trimming, ordering and parallel stages
---
On a laptop the Docker cache just works. On a fresh CI runner every build starts cold, so a two minute local build can take ten minutes in the pipeline. The fix is to move the cache somewhere that outlives the runner.

@concept BuildKit
@plain
BuildKit is the build engine behind `docker build` and `docker buildx build`. It turns a Dockerfile into a dependency graph and runs independent steps in parallel.
@problem
The legacy builder executed instructions one after another, sent the whole context every time and could not share cache between machines.
@does
- Skips stages the target does not need and builds independent stages concurrently.
- Sends only the files that `COPY` actually reads, instead of the whole context.
- Offers `RUN --mount` for cache, secret and SSH, and exports cache to external storage.
- Default since Docker 23; on older engines set `DOCKER_BUILDKIT=1`.
- Plain progress output for CI logs: `--progress=plain`.
@diagram flow
caption: BuildKit runs independent branches in parallel
nodes:
  - "deps stage|npm ci|app"
  - "build stage|compile|app"
  - "test stage|unit tests|info"
  - "runtime stage|copies artifacts|ok"
@h Try it
```bash title="Observe the graph and timings" lab
DOCKER_BUILDKIT=1 docker build --progress=plain -t shop-api:dev . 2>&1 | grep -E '^#[0-9]+ (\[|DONE|CACHED)' | head -20
docker buildx ls
docker buildx du | head
```
@end

@concept Why CI builds are slow
@plain
A CI runner is usually a fresh virtual machine. It has no layers, no pip or npm cache, and no previous build to compare with, so every step runs.
@problem
Pull request feedback takes ten minutes when it should take two, developers batch their changes, and the runner minutes bill grows.
@does
- Cold layer cache: every `RUN` re-executes, every base image is pulled.
- Cold package caches: all dependencies download again.
- Large build contexts: uploading `.git` or `node_modules`.
- Serial pipelines: build, test and scan run one after another.
- Fixes: external cache backend, cache mounts, small context, parallel jobs, a pull through registry mirror.
@diagram cmp
caption: Cold versus warm build (illustrative)
cards:
  - {h: "Cold runner", kind: bad, items: ["Pull base: 20 s", "Install deps: 150 s", "Compile: 90 s", "Total about 4.5 minutes"]}
  - {h: "With cache backend", kind: ok, items: ["Pull base: 3 s", "Deps layer: cache hit", "Compile: only if source changed", "Total about 40 s"]}
@h Measure first
```bash title="Time each step and size the context" lab
du -sh . --exclude=.git 2>/dev/null; du -sh .git
docker buildx build --progress=plain --no-cache -t t:cold . 2>&1 | grep -E '^#[0-9]+ DONE' | sort -t' ' -k3 -n -r | head
```
@end

@concept Cache backends
@plain
`--cache-to` exports the build cache and `--cache-from` imports it. The backend decides where the cache lives.
@problem
Without export, the cache is destroyed with the runner. You need storage reachable from every runner.
@does
- `type=registry`: cache stored as an image in a registry (for example `:buildcache` tag). Works anywhere; use `mode=max` to include intermediate layers.
- `type=gha`: GitHub Actions cache service; no extra infrastructure, 10 GB per repository limit.
- `type=s3`: S3 bucket, good for self-hosted runners on AWS.
- `type=local`: directory, pairs with `actions/cache` or a CI cache volume.
- `type=inline`: embeds cache in the pushed image; simple but only caches the final stage.
@diagram flow
caption: Cache import and export in one build
numbered: true
nodes:
  - "Runner starts empty|no layers|warn"
  - "cache-from|import previous cache|info"
  - "Build|reuse unchanged steps|app"
  - "cache-to mode=max|export for next run|ok"
@h Registry and S3 cache
```bash title="Registry cache with ECR" lab
REG=123456789012.dkr.ecr.eu-west-1.amazonaws.com/shop-api
docker buildx build \
  --cache-from type=registry,ref=$REG:buildcache \
  --cache-to   type=registry,ref=$REG:buildcache,mode=max,image-manifest=true,oci-mediatypes=true \
  -t $REG:sha-$(git rev-parse --short HEAD) --push .
```
```bash title="S3 cache for self hosted runners" lab
docker buildx build \
  --cache-from type=s3,region=eu-west-1,bucket=ci-buildcache,name=shop-api \
  --cache-to   type=s3,region=eu-west-1,bucket=ci-buildcache,name=shop-api,mode=max \
  -t shop-api:ci .
```
:::note
ECR needs `image-manifest=true,oci-mediatypes=true` on cache export, because it does not accept the default cache manifest format.
:::
@check
What does mode=max add compared with mode=min? || It exports every intermediate layer of all stages, not only the final image layers, so multi-stage builds get cache hits.
@end

@concept GitHub Actions workflow with cache
@plain
The standard pipeline uses `docker/setup-buildx-action`, logs in, builds with the `gha` cache and pushes tags generated from metadata.
@problem
Hand written pipelines drift. A tested template avoids missing cache settings and wrong tags.
@does
- `docker/setup-buildx-action` creates a BuildKit builder with the `docker-container` driver (required for external cache export).
- `docker/build-push-action` handles `cache-from`, `cache-to`, `platforms`, secrets and outputs.
- The digest output feeds signing and deployment.
- Pull requests from forks have no registry write access: build without pushing (`push: false`).
@diagram flow
caption: Pipeline stages
nodes:
  - "Checkout|source|plain"
  - "Buildx and login|builder, registry|info"
  - "Build and push|cache gha|app"
  - "Scan and sign|digest output|warn"
@h Workflow
```yaml title=".github/workflows/image.yml"
name: image
on:
  push:
    branches: [main]
  pull_request:
permissions:
  contents: read
  packages: write
  id-token: write
jobs:
  build:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        if: github.event_name != 'pull_request'
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - id: meta
        uses: docker/metadata-action@v5
        with:
          images: ghcr.io/${{ github.repository }}
          tags: |
            type=sha
            type=ref,event=branch
      - id: build
        uses: docker/build-push-action@v6
        with:
          context: .
          push: ${{ github.event_name != 'pull_request' }}
          tags: ${{ steps.meta.outputs.tags }}
          labels: ${{ steps.meta.outputs.labels }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
          provenance: mode=max
          sbom: true
      - name: Show digest
        run: echo "${{ steps.build.outputs.digest }}"
```
@end

@concept Keeping the context and cache keys small
@plain
Every byte in the build context is hashed and possibly uploaded, and any change to a copied file invalidates the layers after it.
@problem
Copying `.` early means a changed README rebuilds your dependency layer. A huge context makes even cached builds slow to start.
@does
- Use precise `.dockerignore` rules, or an allow-list: ignore everything with `*` then add `!src`, `!package*.json`.
- Copy dependency manifests first, install, then copy source.
- Mount lock files and install with bind mounts: `RUN --mount=type=bind,source=requirements.txt,target=requirements.txt pip install -r requirements.txt`.
- Pin `ARG` values that change every run (such as build timestamps) outside early layers, as they bust cache.
- Avoid `COPY . .` before `RUN`s that only need a few files.
@diagram flow
caption: Layer order that survives code edits
nodes:
  - "Base image|changes monthly|ok"
  - "Dependency manifests|change weekly|ok"
  - "Install dependencies|cached|ok"
  - "Source code|changes every commit|warn"
@h Allow-list context and bind-mounted install
```text title=".dockerignore as an allow list" nocheck
*
!src
!package.json
!package-lock.json
!tsconfig.json
```
```dockerfile title="Install without copying the manifest into a layer" nocheck
RUN --mount=type=bind,source=requirements.txt,target=requirements.txt \
    --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt
```
@end

@concept Parallel jobs, test stages and builders at scale
@plain
Treat the Dockerfile as the pipeline: a `test` stage runs the tests, a `lint` stage runs linters, and the `runtime` stage is what you ship. CI builds named targets.
@problem
Duplicating setup between a CI test job and the image build wastes time and allows drift between "what we tested" and "what we shipped".
@does
- `docker build --target test .` runs tests inside the same dependency layers as production.
- Run `lint`, `test` and `scan` as parallel CI jobs sharing the cache.
- Remote builders: BuildKit on Kubernetes (`docker buildx create --driver kubernetes`), Docker Build Cloud, or large runners for CPU-heavy builds.
- Self-hosted runner tip: keep a persistent BuildKit daemon so the local cache survives.
@diagram flow
caption: One Dockerfile, three CI jobs
nodes:
  - "Dockerfile|stages deps, test, runtime|env"
  - "Job lint|target lint|info"
  - "Job test|target test|info"
  - "Job image|target runtime, push|ok"
@h Test stage in the Dockerfile
```dockerfile title="Dockerfile (Python with a test stage)" nocheck
# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt requirements-dev.txt ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.txt

FROM base AS test
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-dev.txt
COPY . .
RUN pytest -q

FROM base AS runtime
RUN useradd --system --uid 10001 app
COPY --chown=10001:10001 . .
USER 10001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```
```bash title="Run just the tests in CI" lab
docker buildx build --target test --cache-from type=gha --cache-to type=gha,mode=max .
docker buildx build --target runtime -t shop-api:ci --load .
```
@end
