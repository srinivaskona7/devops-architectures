---
title: Image optimisation labs
minutes: 60
objectives:
  - Measure image size, layers and build time before changing anything
  - Apply base image, layer and cache techniques and verify the gain
  - Build a repeatable size and speed budget into CI
---
Optimising without measuring is guessing. Each lab here starts with a measurement, makes one change and measures again.

@concept Lab 1, measure first
@plain
Record size, layer sizes, build time and vulnerability count for the current image. These numbers are your baseline.
@problem
Without a baseline you cannot tell whether a change helped, and you may optimise the wrong layer.
@does
- `docker image ls` shows total size; `docker history IMAGE --no-trunc` lists layer sizes and the commands.
- `dive IMAGE` shows wasted space per layer interactively; `dive --ci` can fail a build on thresholds.
- Time a clean build (`--no-cache`) and a rebuild after changing one source file.
- `trivy image` or `docker scout quickview` gives vulnerability counts.
@diagram flow
caption: Baseline set
nodes:
  - "Build|time it|app"
  - "Size and layers|docker history, dive|info"
  - "Vulnerabilities|trivy|warn"
  - "Write down numbers|baseline|ok"
@h Commands
```bash title="Baseline" lab
time docker build --no-cache -t app:base .
docker image ls app:base --format '{{.Size}}'
docker history app:base --format '{{.Size}}\t{{.CreatedBy}}' | head -15
dive app:base --ci || true
trivy image --severity HIGH,CRITICAL app:base | tail -5
```
@check
Why time both a clean build and an incremental rebuild? || Clean build shows CI worst case; incremental shows the developer loop and cache effectiveness.
@end

@concept Lab 2, choose a smaller base image
@plain
The base image is often most of the size. Compare full, slim, Alpine, distroless and scratch options for your language.
@problem
A full Debian-based image can be ten times larger than needed and carries unused packages with CVEs.
@does
- `slim` variants remove docs and extra packages and are a safe first step.
- Alpine uses musl libc: small, but some Python wheels, Node native modules and glibc-built binaries misbehave or compile slowly.
- Distroless (`gcr.io/distroless/*`, or Chainguard and similar images) has no shell or package manager: smaller attack surface, harder to debug (use `kubectl debug`).
- `scratch` suits static binaries (Go with `CGO_ENABLED=0`). Add CA certificates and a non-root user.
- Pin by version and digest for reproducibility.
@diagram cmp
caption: Typical trade-offs
cards:
  - {h: "Full", kind: warn, items: ["Large", "All tools", "Many CVEs"]}
  - {h: "Slim", kind: ok, items: ["Moderate", "glibc compatible", "Good default"]}
  - {h: "Alpine", kind: info, items: ["Small", "musl differences", "Fine for static or pure code"]}
  - {h: "Distroless or scratch", kind: ok, items: ["Smallest", "No shell", "Debug with ephemeral containers"]}
@h Compare sizes
```bash title="Pull and compare" lab
for t in python:3.12 python:3.12-slim python:3.12-alpine; do docker pull -q $t >/dev/null; printf '%s ' $t; docker image ls $t --format '{{.Size}}'; done
```
@choose Base image
Slim | most services | you need glibc plus unusual tools
Alpine | static or pure-language apps | wheels or native modules fail on musl
Distroless | production runtime stage | you must shell in without debug tooling
scratch | static Go or Rust binaries | the binary needs certificates, timezone data or a user you did not copy
@end

@concept Lab 3, shrink layers
@plain
A file deleted in a later layer still exists in the earlier layer. Clean up in the same instruction that creates the files.
@problem
Package caches, build tools and archives remain in the image history and inflate it.
@does
- Combine install and cleanup in one `RUN`: `apt-get install ... && rm -rf /var/lib/apt/lists/*`.
- Use `--no-install-recommends`, `pip install --no-cache-dir`, `npm ci --omit=dev`, and `.dockerignore` to keep `.git`, `node_modules` and local env files out of the build context.
- Prefer multi-stage builds so toolchains never reach the final stage.
- Remove with `COPY --from` selectively; do not copy whole `/usr` trees.
@diagram flow
caption: Deleting later does not shrink
nodes:
  - "Layer 1|adds 200 MB archive|warn"
  - "Layer 2|deletes archive|info"
  - "Image size|still 200 MB|bad"
  - "Same RUN|download, use, delete|ok"
@h Before and after
```dockerfile title="Wasteful" nocheck
RUN curl -fsSL https://example.com/tool.tar.gz -o /tmp/tool.tgz
RUN tar -xzf /tmp/tool.tgz -C /opt
RUN rm /tmp/tool.tgz
```
```dockerfile title="Lean" nocheck
RUN curl -fsSL https://example.com/tool.tar.gz | tar -xz -C /opt
```
```bash title=".dockerignore" lab
printf '.git\nnode_modules\n*.log\n.env\ndist\n' > .dockerignore
docker build -t app:v2 . && docker image ls app:v2
```
@check
Why does deleting a file in a later RUN not reduce image size? || Layers are additive. The earlier layer still stores the file, and the later one only hides it.
@end

@concept Lab 4, speed up builds with cache and ordering
@plain
Order instructions from least to most frequently changing, and use BuildKit cache mounts and remote caches.
@problem
Cache misses make CI builds slow, and developers wait on every commit.
@does
- Copy dependency manifests first, install, then copy sources.
- Use `RUN --mount=type=cache,target=...` for package caches.
- In CI use `--cache-from` and `--cache-to` (registry or `type=gha`, `type=s3`) with `mode=max` to cache intermediate stages.
- Avoid `ARG BUILD_DATE` or `COPY . .` early, since they change every build and invalidate everything below.
- Compare timings: record a table of base, after ordering, after cache mounts.
@diagram flow
caption: Timing table
nodes:
  - "Baseline|240 s|bad"
  - "Ordered layers|90 s|warn"
  - "Cache mounts|45 s|info"
  - "Remote cache in CI|20 s|ok"
@h Measure with BuildKit
```bash title="Time each variant" lab
time docker buildx build --load -t app:ordered .
touch src/main.py && time docker buildx build --load -t app:ordered .
docker buildx build --cache-to type=registry,ref=registry.example.com/cache/app:buildcache,mode=max --cache-from type=registry,ref=registry.example.com/cache/app:buildcache -t registry.example.com/app:dev --push .
```
:::note
The numbers in the diagram are illustrative. Your table must come from your own measurements.
:::
@end

@concept Lab 5, language specific tips
@plain
Each language has its own large files and cheap wins.
@problem
Generic advice misses the biggest savings in a given stack.
@does
- **Go**: static binary, `-ldflags "-s -w"`, `-trimpath`, copy to scratch or distroless static.
- **Java**: use a JRE rather than a JDK, `jlink` custom runtimes, Spring Boot layered jars (`java -Djarmode=layertools`) so dependencies cache apart from app code, or Jib.
- **Node**: `npm ci --omit=dev`, build in one stage and copy `dist`, avoid shipping devDependencies; consider `node:*-slim`.
- **Python**: virtualenv copied from builder, `--no-cache-dir`, avoid `build-essential` in runtime, use wheels.
@diagram layers
caption: Where size hides
layers:
  - {label: "Go", nodes: ["Static binary|10 to 20 MB|ok"]}
  - {label: "Java", nodes: ["JDK vs JRE|hundreds of MB|warn", "Fat jar|rebuilt each change|warn"]}
  - {label: "Node", nodes: ["node_modules dev deps|large|warn"]}
  - {label: "Python", nodes: ["Compilers and caches|large|warn"]}
@h Go to distroless
```dockerfile title="Static Go service" nocheck
# syntax=docker/dockerfile:1
FROM golang:1.23 AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/app ./cmd/app

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/app /app
USER nonroot
ENTRYPOINT ["/app"]
```
@check
Why layer a Spring Boot jar? || Dependencies change rarely and the application classes often, so separate layers keep the large dependency layer cached.
@end

@concept Lab 6, enforce a budget in CI
@plain
A budget is a limit on image size, build time and high severity CVEs. CI fails when a change exceeds it.
@problem
Images grow slowly with every dependency until startup, pulls and scans become slow, and nobody notices.
@does
- Store a max size (for example 200 MB) and compare in a script using `docker image inspect`.
- Run `trivy image --exit-code 1 --severity CRITICAL`.
- Track the size per commit in the build log or metrics, and comment on pull requests with the delta.
- Smaller images pull faster: on a new Kubernetes node image pull time often dominates start time.
@diagram flow
caption: CI gate
nodes:
  - "Build image|CI|app"
  - "Size check|under 200 MB|info"
  - "Scan|no critical CVEs|warn"
  - "Push|only if both pass|ok"
@h Script
```bash title="Size gate" lab
IMG=app:ci
max=$((200*1024*1024))
size=$(docker image inspect "$IMG" --format '{{.Size}}')
echo "size=$size max=$max"
[ "$size" -le "$max" ] || { echo "image too large"; exit 1; }
trivy image --exit-code 1 --severity CRITICAL "$IMG"
```
@end
