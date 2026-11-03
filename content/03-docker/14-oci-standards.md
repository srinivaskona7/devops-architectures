---
title: OCI standards and image formats
minutes: 40
objectives:
  - Name the three OCI specifications and what each one standardises
  - Read an OCI image layout on disk, including index, manifest, config and layer blobs
  - Explain why Docker images run on Kubernetes without Docker
---
Docker, Podman, containerd, Kubernetes and every cloud registry interoperate because of the Open Container Initiative. Knowing the formats lets you inspect, copy and build images without any daemon.

@concept The three OCI specifications
@plain
The OCI publishes three specifications: the **Image spec** (what an image is), the **Runtime spec** (how to run a container from a filesystem bundle) and the **Distribution spec** (how registries serve images).
@problem
In 2014 only Docker's own formats existed. Orchestrators and registries needed neutral standards so no single vendor controlled how containers are packaged and run.
@does
- Image spec: index, manifest, config JSON, layers as tar archives, all addressed by digest.
- Runtime spec: a `config.json` plus a root filesystem directory (a **bundle**); implemented by `runc`, `crun`, `youki`, `runsc` (gVisor), `kata-runtime`.
- Distribution spec: the `/v2/` HTTP API for push and pull.
- Docker image format v2 is nearly identical and still widely served alongside OCI media types.
@diagram layers
caption: Who implements which specification
layers:
  - {label: "Distribution spec", nodes: ["ECR, GHCR, Harbor, Quay|registries|cp"]}
  - {label: "Image spec", nodes: ["BuildKit, Buildah, Kaniko, ko|builders|app", "skopeo, crane, oras|copy tools|app"]}
  - {label: "Runtime spec", nodes: ["runc, crun|standard runtimes|env", "gVisor, Kata, Firecracker|sandboxed runtimes|env"]}
@h Inspect with neutral tools
```bash title="Copy and read an image without Docker" lab
skopeo copy docker://alpine:3.20 oci:/tmp/alpine-oci:3.20     # write an OCI layout to disk
ls /tmp/alpine-oci                                            # blobs  index.json  oci-layout
cat /tmp/alpine-oci/oci-layout
python3 -m json.tool /tmp/alpine-oci/index.json | head -20
```
@end

@concept Anatomy of an image on disk
@plain
An OCI layout is a folder with an `index.json`, an `oci-layout` marker and a `blobs/sha256/` directory. Every file in `blobs/` is named by the SHA-256 of its contents.
@problem
"Images are magic archives" blocks debugging. Once you see that an image is JSON files and tarballs, you can verify, diff or repair them with ordinary tools.
@does
- `index.json` points to a manifest digest (or to a multi-platform index).
- The manifest lists the config blob and ordered layer blobs, each with `mediaType`, `digest` and `size`.
- The config holds `architecture`, `os`, `config.Cmd/Env/User`, `rootfs.diff_ids` and the build `history`.
- Layers are tar (optionally gzip or zstd) with whiteout files `.wh.<name>` for deletions.
@diagram flow
caption: Following the digests down
numbered: true
nodes:
  - "index.json|entry point|cp"
  - "Manifest|config and layer digests|info"
  - "Config blob|cmd, env, history|env"
  - "Layer blobs|tar archives|app"
@h Walk the tree with jq
```bash title="From index to files" lab
cd /tmp/alpine-oci
MANIFEST=$(jq -r '.manifests[0].digest' index.json | cut -d: -f2)
jq '.config.digest, (.layers[] | .digest, .size)' blobs/sha256/$MANIFEST
LAYER=$(jq -r '.layers[0].digest' blobs/sha256/$MANIFEST | cut -d: -f2)
tar -tzf blobs/sha256/$LAYER | head -8          # the files that layer adds
CONFIG=$(jq -r '.config.digest' blobs/sha256/$MANIFEST | cut -d: -f2)
jq '.config.Cmd, .architecture, .rootfs' blobs/sha256/$CONFIG
```
@check
What is the difference between a layer digest and a diff_id? || The digest is the hash of the compressed blob as stored; the diff_id is the hash of the uncompressed tar, used to identify content independent of compression.
@end

@concept Media types, compression and multi-platform images
@plain
Each blob has a media type that tells tools how to read it. A single tag can point to an index containing one manifest per CPU architecture.
@problem
Apple Silicon laptops build arm64 images while most servers are amd64; an image built for the wrong architecture fails with `exec format error`.
@does
- Manifest types: `application/vnd.oci.image.manifest.v1+json` (OCI) or `application/vnd.docker.distribution.manifest.v2+json` (Docker).
- Layers: `...layer.v1.tar+gzip` or `+zstd`. zstd decompresses faster; supported by containerd 1.5+ and BuildKit.
- The index has `platform: {os, architecture, variant}` per entry; the runtime picks the matching one.
- `--platform linux/amd64` forces a choice; Kubernetes picks automatically by node architecture.
@diagram cmp
caption: One tag, several manifests
cards:
  - {h: "Index python:3.12-slim", kind: cp, items: ["Tag points to one index", "Digest of the index is stable"]}
  - {h: "linux/amd64 manifest", kind: app, items: ["x86 server and CI", "Own layers and config"]}
  - {h: "linux/arm64 manifest", kind: app, items: ["Graviton, Apple Silicon", "Own layers and config"]}
@h Check a platform
```bash title="Which architectures does this tag offer" lab
docker buildx imagetools inspect python:3.12-slim | grep -E 'Platform|Name'
docker run --rm --platform linux/amd64 alpine:3.20 uname -m
docker image inspect alpine:3.20 --format '{{.Os}}/{{.Architecture}}'
```
:::tip
`exec format error` almost always means the image architecture does not match the node. Check with `docker image inspect` or `kubectl get node -o wide` and build multi-arch images (see the CI section).
:::
@end

@concept The runtime bundle and config.json
@plain
To run a container, the runtime needs a **bundle**: a directory with a `rootfs/` (the unpacked image layers) and a `config.json` describing process, mounts, namespaces and limits.
@problem
The image spec says what to ship, not how to run it. Something must translate image config plus runtime options into precise kernel settings.
@does
- `config.json` fields: `process.args`, `process.env`, `process.user`, `root.path`, `mounts`, `linux.namespaces`, `linux.resources` (cgroup limits), `linux.seccomp`, `process.capabilities`.
- containerd (or dockerd) creates this file from the image config plus your flags or the Kubernetes pod spec.
- `runc spec` writes a template you can edit.
@diagram flow
caption: From image to bundle
nodes:
  - "Image layers|unpacked with overlayfs|app"
  - "Image config|cmd, env, user|env"
  - "Runtime options|limits, mounts, caps|info"
  - "Bundle|rootfs plus config.json|cp"
@h Look at a generated config
```bash title="Create a bundle and read it" lab
mkdir -p /tmp/bundle/rootfs && cd /tmp/bundle
docker export $(docker create alpine:3.20) | tar -C rootfs -xf -
runc spec                                 # writes config.json
jq '.process.args, .linux.namespaces[].type, .process.capabilities.bounding' config.json
```
@end

@concept Building without a daemon
@plain
Because images are just files, several tools build or assemble them without Docker: Buildah, Kaniko, BuildKit rootless, `ko` (Go) and Jib (Java).
@problem
CI runners and Kubernetes pods should not mount `/var/run/docker.sock` or run privileged, since that hands out root on the node.
@does
- **BuildKit** (`buildkitd`, rootless mode) is the engine inside modern Docker and `docker buildx`.
- **Buildah** builds from Dockerfiles or scripts, rootless.
- **Kaniko** (maintained by Chainguard now) builds inside a container without a daemon, popular in GitLab and Tekton.
- **ko** builds minimal Go images straight from source; **Jib** does the same for Java.
- All produce OCI images pushed to a registry with a digest.
@diagram cmp
caption: Daemonless build options
cards:
  - {h: "BuildKit rootless", kind: ok, items: ["Dockerfile compatible", "Best cache support", "Docker and buildx use it"]}
  - {h: "Buildah", kind: info, items: ["Rootless on Linux", "Scriptable", "RHEL and Podman family"]}
  - {h: "Kaniko", kind: warn, items: ["Runs as a pod", "No daemon or privileges", "Slower cache"]}
  - {h: "ko and Jib", kind: app, items: ["No Dockerfile", "Language aware", "Tiny reproducible images"]}
@h Example with ko
```bash title="Build and push a Go service without a Dockerfile" lab
export KO_DOCKER_REPO=ghcr.io/acme/shop-api
ko build ./cmd/server --bare --tags sha-$(git rev-parse --short HEAD)
```
@end

@concept OCI artifacts and referrers
@plain
A registry can store more than runnable images. The same manifest format carries Helm charts, SBOMs, signatures and policy bundles as OCI artifacts, linked to an image through the referrers API.
@problem
Teams ran separate stores for charts, signatures and SBOMs. Keeping all of them next to the image under one access control and one replication path is simpler.
@does
- Helm 3.8 and later: `helm push chart.tgz oci://REGISTRY/charts`.
- cosign stores signatures and attestations as artifacts that refer to the image digest through the `subject` field.
- `oras` pushes arbitrary files; `oras discover IMAGE` or `cosign tree IMAGE` lists what is attached.
- Registries that support the OCI 1.1 referrers API return attached artifacts directly.
@diagram layers
caption: Artifacts attached to one image digest
layers:
  - {label: "Subject", nodes: ["shop-api@sha256:abc|the image|app"]}
  - {label: "Referrers", nodes: ["Signature|cosign|ok", "SBOM|spdx json|info", "Provenance|SLSA attestation|info", "Scan report|Trivy sarif|warn"]}
@h Explore
```bash title="List what is attached to an image" lab
cosign tree ghcr.io/acme/shop-api:sha-3f9c2ab
oras discover ghcr.io/acme/shop-api:sha-3f9c2ab
helm push shop-0.1.0.tgz oci://ghcr.io/acme/charts
```
@end
