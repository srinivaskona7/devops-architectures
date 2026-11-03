---
title: Images and layers
minutes: 45
objectives:
  - Describe an image as a stack of read-only layers plus a manifest and config
  - Explain copy on write and why deleting a file in a later layer does not shrink an image
  - Inspect image history, sizes and digests and reduce image size
---
An image is the template a container starts from. Understanding layers explains build speed, image size, pull time and why secrets leak into images.

@concept What an image is
@plain
An image is a read-only bundle: a filesystem split into layers, plus a small JSON config that records the default command, environment variables, user and exposed ports.
@problem
Shipping a filesystem as one huge archive wastes bandwidth. Most of a new version is identical to the previous one.
@does
- Each layer is a compressed tar of file changes. Layers are identified by a SHA-256 hash of their content.
- The **manifest** lists the config and layers by digest; the **config** holds `Entrypoint`, `Cmd`, `Env`, `User`.
- Layers are shared. Ten images based on the same `python:3.12-slim` store that base only once, and a registry transfers only layers it lacks.
- A container adds one thin writable layer on top.
@diagram layers
caption: Image layers with the writable container layer on top
layers:
  - {label: "Container layer (read write)", nodes: ["Writable layer|lost when the container is removed|warn"]}
  - {label: "Image layers (read only)", nodes: ["COPY app code|small, changes often|app", "pip install|dependencies|app", "python runtime|from the base image|env", "Debian slim files|base filesystem|plain"]}
@h Look inside
```bash title="Inspect an image" lab
docker pull python:3.12-slim
docker image inspect python:3.12-slim --format '{{.Id}} {{.Architecture}} {{.Os}}'
docker image inspect python:3.12-slim --format '{{json .RootFS.Layers}}' | python3 -m json.tool | head
docker image inspect python:3.12-slim --format '{{json .Config.Cmd}} {{json .Config.Env}}'
docker history python:3.12-slim     # one row per layer with its size
```
@check
What stores the default command of an image? || The image config JSON (Cmd and Entrypoint), referenced by the manifest.
@end

@concept Copy on write and the union filesystem
@plain
Layers are stacked so they look like one directory tree. When a container changes a file from a lower layer, the file is first copied up to the writable layer, then changed there.
@problem
Without this, every container would need a full private copy of the image, and starting one would mean copying gigabytes.
@does
- The storage driver is `overlay2` on modern Linux (OverlayFS: lowerdirs, upperdir, workdir and a merged view).
- Deleting a file in a later layer only hides it with a "whiteout" marker; the bytes remain in the earlier layer and still count toward image size.
- Heavy writes inside the container layer are slower than writes to a volume.
:::warn
`COPY secrets.txt /` followed by `RUN rm /secrets.txt` leaves the secret in the earlier layer, and anyone who pulls the image can extract it. Use build secrets (covered in the Dockerfile files) instead.
:::
@diagram flow
caption: Reading and modifying a file with overlay2
nodes:
  - "Container reads /etc/app.conf|found in lower layer|plain"
  - "Container edits it|file copied up first|warn"
  - "Upper layer holds the copy|lower layer unchanged|ok"
  - "Container removed|upper layer deleted|bad"
@h Prove it with a lab
```bash title="Whiteouts keep the bytes" lab
mkdir -p /tmp/wo && cd /tmp/wo
printf 'FROM alpine:3.20\nRUN dd if=/dev/zero of=/big bs=1M count=50\nRUN rm /big\n' > Dockerfile
docker build -q -t whiteout-demo .
docker history whiteout-demo     # the 50MB layer is still listed
docker rmi whiteout-demo
```
@end

@concept Content addressable storage
@plain
Everything in an image is named by the hash of its content. Change one byte and the name changes.
@problem
Tags like `latest` can move; you need a way to prove two machines run exactly the same bytes.
@does
- A **digest** looks like `sha256:3f5a...` and identifies a manifest or layer.
- The same content always gets the same digest, which allows deduplication and verification on pull.
- A multi-architecture image has an **index** (manifest list) pointing to one manifest per platform.
- `repo@sha256:...` references an image immutably; `repo:tag` can be repointed.
@diagram rows
caption: Index to manifest to config and layers
rows:
  - {arrows: false, items: ["Image index|one per tag, lists platforms|cp"]}
  - {arrows: false, items: ["Manifest amd64|digest sha256 aaa|info", "Manifest arm64|digest sha256 bbb|info"]}
  - {arrows: false, items: ["Config|cmd, env, user|env", "Layer 1|tar.gz|app", "Layer 2|tar.gz|app"]}
@h Read the real manifest
```bash title="Digests and platforms" lab
docker buildx imagetools inspect python:3.12-slim | head -20
docker image ls --digests python
docker manifest inspect nginx:1.27-alpine 2>/dev/null | head -20
```
@end

@concept Image size and why it matters
@plain
Size drives pull time, cold start on a new Kubernetes node, registry cost and attack surface. A 1.2 GB image takes much longer to start on a fresh node than a 60 MB one.
@problem
Images grow because build tools, package caches and source trees end up in the final layers.
@does
- Choose a smaller base: `alpine` (about 8 MB, musl libc), `*-slim` Debian (about 50 MB), or distroless.
- Combine install and cleanup in one `RUN` so the cache is never committed to a layer.
- Use multi-stage builds so compilers stay in the build stage.
- Add a `.dockerignore` so `.git`, `node_modules` and local files are not sent or copied.
@diagram cmp
caption: Typical Python web service image sizes (approximate)
cards:
  - {h: "python:3.12 full", kind: bad, items: ["About 1 GB", "Compilers and headers included", "Large attack surface"]}
  - {h: "python:3.12-slim", kind: warn, items: ["About 130 MB with Python", "Debian minimal", "Good default"]}
  - {h: "python slim + multi-stage", kind: ok, items: ["Only runtime and app", "No pip cache or build tools", "Smaller and faster to pull"]}
  - {h: "distroless python", kind: ok, items: ["No shell or package manager", "Smallest attack surface", "Harder to debug"]}
@h Measuring
```bash title="Compare sizes" lab
docker pull -q python:3.12 python:3.12-slim python:3.12-alpine 2>/dev/null || true
docker image ls --format 'table {{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -E 'python|REPOSITORY'
docker system df                       # images, containers, volumes, build cache
docker image prune -a --filter "until=168h" -f   # remove unused images older than 7 days
```
:::tip
Alpine uses musl libc. Python wheels and some native Node modules expect glibc and may need compiling, which can make Alpine builds slower and larger. Prefer `-slim` for Python unless you have tested Alpine.
:::
@end

@concept Tags, names and references
@plain
An image reference has the form `registry/namespace/repository:tag@digest`. Missing parts get defaults: Docker Hub, the `library` namespace and the `latest` tag.
@problem
`FROM python` or `image: app:latest` resolves differently over time and across machines, making builds and rollbacks unpredictable.
@does
- `nginx` means `docker.io/library/nginx:latest`.
- A tag is a mutable pointer. Several tags can point to one digest.
- Pin both for reproducibility: `python:3.12.7-slim@sha256:...`.
- `docker tag src dst` adds a name; it does not copy data.
@diagram flow
caption: Anatomy of a full reference
nodes:
  - "123456789012.dkr.ecr.eu-west-1.amazonaws.com|registry host|cp"
  - "shop/api|repository path|info"
  - "1.4.2|tag, mutable|warn"
  - "sha256 digest|immutable content id|ok"
@h Practice
```bash title="Tagging and pinning" lab
docker pull alpine:3.20
docker tag alpine:3.20 myorg/tools:v1
docker image ls myorg/tools
docker image inspect alpine:3.20 --format '{{index .RepoDigests 0}}'   # the pinnable reference
docker rmi myorg/tools:v1
```
@check
Why is latest a poor production tag? || It moves whenever someone pushes, so two deployments of the same name may run different code and rollbacks are not reproducible.
@end

@concept Saving, loading and cleaning images
@plain
Images can be moved without a registry as a tar file, and disk can fill quickly with unused layers and build cache.
@problem
Air-gapped environments need offline transfer, and CI runners and laptops regularly run out of disk space.
@does
- `docker save -o app.tar app:1.0` and `docker load -i app.tar` move images between hosts.
- `docker system df` shows reclaimable space; `docker image prune` removes dangling images, `-a` removes all unused ones.
- `docker builder prune` clears build cache.
- Dangling images are untagged leftovers from rebuilds of the same tag.
@diagram flow
caption: Moving an image offline
nodes:
  - "Build host|docker save|app"
  - "app.tar|portable archive|info"
  - "Target host|docker load|app"
  - "Runs|docker run|ok"
@h Commands
```bash title="Offline transfer and cleanup" lab
docker pull -q alpine:3.20
docker save alpine:3.20 | gzip > /tmp/alpine.tar.gz
docker rmi alpine:3.20 && gunzip -c /tmp/alpine.tar.gz | docker load
docker system df
docker image prune -f
docker builder prune --filter "until=24h" -f
```
@end
