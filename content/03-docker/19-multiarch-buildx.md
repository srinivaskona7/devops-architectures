---
title: Multi-architecture builds with buildx
minutes: 40
objectives:
  - Build and push one tag that serves both amd64 and arm64 nodes
  - Choose between QEMU emulation, cross compilation and native builders
  - Verify the resulting index and avoid architecture-specific pitfalls
---
Developers on Apple Silicon build arm64 images, many servers run amd64, and AWS Graviton nodes are arm64 and cheaper per unit of work. A multi-architecture image makes the same tag work everywhere.

@concept Why multi-arch
@plain
CPU architectures run different machine code. An amd64 binary cannot run on an arm64 node. A multi-arch image bundles one variant per platform behind a single tag.
@problem
Images built on an M-series Mac and deployed to amd64 EKS nodes crash with `exec format error`, and teams that run Graviton nodes for cost savings need arm64 images.
@does
- The registry holds an **index** (manifest list) with one manifest per platform.
- containerd picks the manifest that matches the node when pulling; the user sees one tag.
- Common platforms: `linux/amd64`, `linux/arm64`, sometimes `linux/arm/v7`.
- Graviton instances typically cost about 20 percent less than comparable x86 instances for the same work; verify for your workload and region.
@diagram flow
caption: One tag, the node picks its variant
nodes:
  - "shop-api:1.4.2|image index|cp"
  - "Graviton node|arm64|env"
  - "x86 node|amd64|env"
  - "Pulls matching manifest|automatic|ok"
@h Check a base image supports your targets
```bash title="Platforms of a tag" lab
docker buildx imagetools inspect node:22-slim | grep -E '^\s+Platform'
docker run --rm --platform linux/arm64 alpine:3.20 uname -m
docker run --rm --platform linux/amd64 alpine:3.20 uname -m
```
@end

@concept Three ways to build for another architecture
@plain
You can emulate the other CPU, cross compile on your own CPU, or build natively on a machine of each architecture.
@problem
Emulation is easy but 5 to 20 times slower for compilation heavy builds. Native is fastest but needs two kinds of runners.
@does
- **QEMU emulation**: `docker/setup-qemu-action` registers binfmt handlers; works for any Dockerfile; slow for compiled languages and `npm ci` with native modules.
- **Cross compilation**: use `FROM --platform=$BUILDPLATFORM` for the build stage and compile for `$TARGETARCH` (Go, Rust, .NET, Java are straightforward).
- **Native builders**: separate arm64 and amd64 runners, each build pushes by digest and a final job merges them into an index. GitHub offers arm64 hosted runners.
- Interpreted languages (pure Python or Node without native modules) are architecture independent in your code but their dependencies may include compiled wheels.
@diagram cmp
caption: Choosing a strategy
cards:
  - {h: "QEMU", kind: warn, items: ["Zero setup", "Slow for compile steps", "Good for small images"]}
  - {h: "Cross compile", kind: ok, items: ["Fast, one runner", "Needs language support", "Go, Rust, Java, .NET"]}
  - {h: "Native runners", kind: info, items: ["Fastest and most faithful", "Two runner types", "Merge step creates the index"]}
@h Cross compiling a Go service
```dockerfile title="Dockerfile (Go, cross compiled)" nocheck
# syntax=docker/dockerfile:1
FROM --platform=$BUILDPLATFORM golang:1.23 AS build
ARG TARGETOS TARGETARCH
WORKDIR /src
COPY go.mod go.sum ./
RUN --mount=type=cache,target=/go/pkg/mod go mod download
COPY . .
RUN --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=$TARGETOS GOARCH=$TARGETARCH go build -o /out/server ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /out/server /server
ENTRYPOINT ["/server"]
```
@end

@concept buildx builders and building the index
@plain
`docker buildx` manages builder instances. The default Docker driver cannot produce multi-platform images; the `docker-container` driver can.
@problem
`docker build --platform linux/amd64,linux/arm64` fails on the default driver with "multiple platforms feature is currently not supported".
@does
- `docker buildx create --name multi --driver docker-container --use` creates a BuildKit builder in a container.
- `--platform linux/amd64,linux/arm64 --push` builds both and pushes the index. Multi-platform results cannot be `--load`ed into the local engine unless the containerd image store is enabled.
- `docker buildx imagetools inspect` shows the platforms in the pushed index.
- Build arguments `TARGETPLATFORM`, `TARGETARCH`, `BUILDPLATFORM` are available inside the Dockerfile.
@diagram flow
caption: A multi-platform build and push
numbered: true
nodes:
  - "buildx builder|docker-container driver|app"
  - "Build amd64|native or QEMU|info"
  - "Build arm64|native or QEMU|info"
  - "Push index|one tag, two manifests|ok"
@h Commands
```bash title="Build and push both architectures" lab
docker buildx create --name multi --driver docker-container --use
docker buildx build --platform linux/amd64,linux/arm64 \
  -t ghcr.io/acme/shop-api:1.4.2 --push .
docker buildx imagetools inspect ghcr.io/acme/shop-api:1.4.2
docker buildx inspect --bootstrap | grep -i platforms
```
```yaml title="GitHub Actions steps with QEMU"
steps:
  - uses: actions/checkout@v4
  - uses: docker/setup-qemu-action@v3
  - uses: docker/setup-buildx-action@v3
  - uses: docker/login-action@v3
    with:
      registry: ghcr.io
      username: ${{ github.actor }}
      password: ${{ secrets.GITHUB_TOKEN }}
  - uses: docker/build-push-action@v6
    with:
      platforms: linux/amd64,linux/arm64
      push: true
      tags: ghcr.io/${{ github.repository }}:sha-${{ github.sha }}
      cache-from: type=gha
      cache-to: type=gha,mode=max
```
@check
Why cannot the default docker driver build multi-platform images? || It builds only for the engine's platform and cannot export an index; the docker-container driver runs a full BuildKit that can.
@end

@concept Native builders with a merge step
@plain
For the best speed, build each architecture on a matching runner, push each by digest only, then create the index from those digests.
@problem
QEMU builds of a Node or Python service with native extensions can take 20 minutes. Native builds take two.
@does
- Matrix over `linux/amd64` on `ubuntu-24.04` and `linux/arm64` on `ubuntu-24.04-arm`.
- Each job: `push-by-digest=true,name-canonical=true,push=true`, and uploads the digest as an artifact.
- Final job: `docker buildx imagetools create -t IMAGE:TAG IMAGE@sha256:AMD IMAGE@sha256:ARM`.
- Sign the index digest once at the end.
@diagram flow
caption: Two native builds merged into one index
nodes:
  - "amd64 runner|builds, pushes digest|app"
  - "arm64 runner|builds, pushes digest|app"
  - "Merge job|imagetools create|cp"
  - "Tag with index|sign and scan|ok"
@h Merge step
```bash title="Create the index from two digests" lab
IMAGE=ghcr.io/acme/shop-api
docker buildx imagetools create -t $IMAGE:sha-$(git rev-parse --short HEAD) \
  $IMAGE@sha256:AMD64_DIGEST_HERE $IMAGE@sha256:ARM64_DIGEST_HERE
docker buildx imagetools inspect $IMAGE:sha-$(git rev-parse --short HEAD)
```
@end

@concept Architecture pitfalls
@plain
A multi-arch tag proves both images exist, not that both work. The dependencies and base images must also support each architecture.
@problem
Arm images that build fine but crash at runtime because a prebuilt binary, wheel or sidecar image exists only for amd64.
@does
- Pin versions that publish arm64 wheels or binaries; check PyPI "manylinux aarch64" or npm optional dependency packages (for example `esbuild`, `sharp`, `@swc/core`).
- Download tools in Dockerfiles using `TARGETARCH`, not a hard-coded `amd64` URL.
- Test the arm64 image on an arm64 node or with emulation in CI before release: `docker run --platform linux/arm64 IMAGE --version`.
- Mixed clusters need `nodeSelector` or the automatic platform match; `kubernetes.io/arch` label tells you the node architecture.
- Use `uname -m` and `file /path/binary` to confirm binaries.
@diagram cmp
caption: Common arm64 failures and fixes
cards:
  - {h: "exec format error", kind: bad, items: ["Image has only amd64", "Build both platforms"]}
  - {h: "Missing wheel or binary", kind: warn, items: ["pip builds from source or fails", "Upgrade package or install build tools"]}
  - {h: "Hard-coded download URL", kind: warn, items: ["Fetches amd64 tool on arm64", "Use TARGETARCH in the URL"]}
@h Download the right binary
```dockerfile title="Use TARGETARCH for tool downloads" nocheck
FROM debian:12-slim
ARG TARGETARCH
ARG KUBECTL_VERSION=v{{v.kubernetes_latest_patch}}
ADD https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl /usr/local/bin/kubectl
RUN chmod +x /usr/local/bin/kubectl
```
```bash title="Check node architectures in the cluster" lab
kubectl get nodes -L kubernetes.io/arch
kubectl get pods -A -o wide | head
```
@end

@concept Verifying and running multi-arch images
@plain
After pushing, confirm the index lists every platform and run a smoke test for each one before relying on the tag.
@problem
A pipeline can report success while an index contains only one platform, or while the arm64 image starts but fails on a missing library.
@does
- `docker buildx imagetools inspect IMAGE` lists the platforms and their digests.
- `docker run --platform linux/arm64 IMAGE CMD` runs the arm64 variant under emulation on an amd64 host (and the reverse on a Mac).
- Add an `arch` label or print `uname -m` in the health response during testing.
- In Kubernetes use `nodeSelector: {kubernetes.io/arch: arm64}` to move a workload to Graviton nodes gradually.
@diagram flow
caption: Release smoke test per platform
nodes:
  - "Push index|two platforms|cp"
  - "Run amd64|health check|info"
  - "Run arm64|health check|info"
  - "Promote tag|both pass|ok"
@h Smoke test
```bash title="Test each platform" lab
IMG=ghcr.io/acme/shop-api:sha-3f9c2ab
for p in linux/amd64 linux/arm64; do
  docker run --rm --platform $p --entrypoint uname $IMG -m || echo "FAIL $p"
done
docker buildx imagetools inspect $IMG | grep -c 'Platform:'
```
```yaml title="Pin a workload to Graviton nodes"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shop-api
spec:
  replicas: 2
  selector:
    matchLabels: {app: shop-api}
  template:
    metadata:
      labels: {app: shop-api}
    spec:
      nodeSelector:
        kubernetes.io/arch: arm64
      containers:
        - name: api
          image: ghcr.io/acme/shop-api:sha-3f9c2ab
```
@end
