---
title: Docker Desktop alternatives
minutes: 50
objectives:
  - Compare Podman, Colima, nerdctl, Buildah and Kaniko and choose for each job
  - Run a container workflow on macOS without Docker Desktop
  - Build images in CI and clusters without a Docker daemon
---
Docker Desktop is convenient, but licensing, resource use or policy may rule it out. The OCI standards mean images and most commands carry over to other tools.

@concept What you actually need from Docker
@plain
Docker is several parts: a CLI, a daemon (dockerd) with an API, a runtime (containerd and runc), a builder (BuildKit) and, on Mac and Windows, a Linux VM.
@problem
When you replace Docker you must replace each part, or you lose features without noticing.
@does
- On macOS containers need a Linux VM. Alternatives differ mainly in how they create and manage that VM.
- The Docker API socket is used by many tools (Testcontainers, IDE plugins, Compose). Some alternatives expose a compatible socket.
- Images are OCI images, so they run anywhere. Differences appear in networking, volumes, file sharing and Compose support.
- Check licences and your organisation's approved tools before switching.
@diagram layers
caption: Parts of a container workflow
layers:
  - {label: "Client", nodes: ["docker or podman or nerdctl CLI|commands|app"]}
  - {label: "Engine", nodes: ["dockerd or podman or containerd|API and lifecycle|cp"]}
  - {label: "Runtime", nodes: ["runc or crun|creates the container|info"]}
  - {label: "Host", nodes: ["Linux VM on macOS|Lima, QEMU, vz|env"]}
@check
Why do containers on a Mac need a VM? || Containers use Linux kernel features (namespaces, cgroups), so a Linux kernel must run in a VM.
@end

@concept Podman
@plain
Podman is a daemonless, rootless-friendly container engine with a Docker-compatible CLI. Each container is a child process of the command that started it.
@problem
A root daemon is a single privileged target and a single point of failure; some environments forbid it.
@does
- `alias docker=podman` works for most commands (`run`, `build`, `ps`, `push`).
- Rootless by default for normal users. Pods (`podman pod`) group containers like Kubernetes Pods, and `podman generate kube` or `podman kube play` moves between Podman and YAML.
- On macOS use `podman machine init` and `podman machine start`, which run a Linux VM.
- `podman compose` delegates to docker-compose or podman-compose. Quadlet files run containers under systemd on Linux.
@diagram flow
caption: Daemonless model
nodes:
  - "podman run|CLI process|app"
  - "conmon|monitors container|info"
  - "crun or runc|starts process|cp"
  - "Container|runs rootless|ok"
@h Mac quick start
```bash title="Podman on macOS" lab
brew install podman
podman machine init --cpus 4 --memory 6144 --disk-size 60
podman machine start
podman run --rm -p 8080:80 docker.io/library/nginx:1.27
podman ps
```
@end

@concept Colima and Lima
@plain
Colima runs a small Linux VM (through Lima) and installs the Docker or containerd runtime in it. You keep the normal `docker` CLI.
@problem
You want the Docker experience on macOS with less overhead and a command-line-only setup.
@does
- `colima start --cpu 4 --memory 8 --disk 60` creates the VM; `colima start --runtime containerd` uses containerd with nerdctl.
- VM type: `--vm-type vz` uses Apple's Virtualization framework and `--vz-rosetta` can run amd64 images faster on Apple silicon; otherwise QEMU.
- The Docker context `colima` is created, so the `docker` CLI talks to the VM's dockerd through a socket.
- Kubernetes: `colima start --kubernetes` runs a local k3s cluster.
- File sharing uses virtiofs or sshfs; bind-mount performance differs from Docker Desktop.
@diagram flow
caption: Colima stack
nodes:
  - "docker CLI|context colima|app"
  - "Socket on the Mac|forwarded|info"
  - "Lima VM|vz or QEMU|env"
  - "dockerd or containerd|inside VM|cp"
@h Commands
```bash title="Colima basics" lab
brew install colima docker docker-compose
colima start --cpu 4 --memory 8 --vm-type vz --vz-rosetta
docker context ls
docker run --rm hello-world
colima stop
```
@check
What does the Docker CLI use to talk to Colima? || A Docker context that points to a socket forwarded from the Lima VM.
@end

@concept nerdctl and containerd
@plain
nerdctl is a Docker-compatible CLI for containerd. It adds features such as lazy pulling, image encryption and rootless support.
@problem
Kubernetes nodes run containerd, but the `ctr` tool is low-level and unfriendly for debugging.
@does
- `nerdctl run`, `build` (with BuildKit), `compose up` mirror Docker usage.
- Works in namespaces: Kubernetes images live in the `k8s.io` containerd namespace (`nerdctl --namespace k8s.io images`).
- Rancher Desktop and Lima use nerdctl; `nerdctl.lima` wraps it on macOS.
- On cluster nodes `crictl` is the CRI-level tool for debugging Pods and images.
@diagram flow
caption: Tools talking to containerd
nodes:
  - "nerdctl|Docker-like CLI|app"
  - "crictl|CRI debug tool|app"
  - "containerd|runtime daemon|cp"
  - "runc|containers|ok"
@h Examples
```bash title="nerdctl and crictl" lab
nerdctl run -d --name web -p 8080:80 nginx:1.27
nerdctl --namespace k8s.io images | head
crictl ps
crictl pods
```
@end

@concept Buildah
@plain
Buildah builds OCI images without a daemon, using either Dockerfiles or step-by-step shell commands.
@problem
Building images in CI or on a locked-down host should not require access to a Docker socket, which gives root.
@does
- `buildah bud -t app:1 .` (also `buildah build`) reads a Containerfile or Dockerfile.
- Scripted builds: `buildah from`, `buildah copy`, `buildah run`, `buildah commit` let you create images without a Dockerfile.
- Can build rootless and, with `buildah from scratch`, make minimal images by mounting the root filesystem.
- Pairs with Podman (shares storage) and Skopeo for copying images between registries.
@diagram flow
caption: Scripted build
numbered: true
nodes:
  - "buildah from|starting container|app"
  - "copy and run|modify filesystem|info"
  - "commit|image created|cp"
  - "push|registry|ok"
@h Scripted build
```bash title="Build without a Dockerfile" lab
c=$(buildah from docker.io/library/alpine:3.20)
buildah run "$c" -- apk add --no-cache curl
buildah config --entrypoint '["curl"]' "$c"
buildah commit "$c" localhost/curl:1
buildah rm "$c"
skopeo inspect containers-storage:localhost/curl:1 | head
```
@check
Why prefer daemonless builders in CI? || No Docker socket (root access) needs to be mounted into the job, which reduces the risk of a container escape.
@end

@concept Kaniko and in-cluster builds
@plain
Kaniko builds images from a Dockerfile inside a container or Kubernetes Pod without privileged mode or a daemon.
@problem
Building images in a CI runner that itself runs on Kubernetes normally needs Docker-in-Docker, which requires privileged Pods.
@does
- The executor runs each Dockerfile instruction in userspace and snapshots the filesystem, then pushes to a registry.
- Supports a remote layer cache (`--cache=true --cache-repo=...`) and reproducible options.
- Limitations: slower than BuildKit for many cases; some Dockerfile features differ. The upstream Google repository was archived in 2025; community forks exist, so check the current status and your supply chain policy.
- Alternatives for rootless in-cluster builds: BuildKit rootless, Buildah in a Pod, `ko` for Go, Cloud Native Buildpacks, Jib for Java.
@diagram flow
caption: Build inside Kubernetes
nodes:
  - "CI job|creates a Pod|app"
  - "Kaniko executor|no daemon|cp"
  - "Registry|push image|ext"
  - "Deployment|pulls image|ok"
@h Pod (shape)
```yaml title="Kaniko Pod" nocheck
apiVersion: v1
kind: Pod
metadata:
  name: build-api
spec:
  restartPolicy: Never
  containers:
    - name: kaniko
      image: gcr.io/kaniko-project/executor:latest
      args:
        - --context=git://git.example.com/shop/api.git#refs/heads/main
        - --destination=registry.example.com/shop/api:1.8.4
        - --cache=true
      volumeMounts:
        - {name: docker-config, mountPath: /kaniko/.docker}
  volumes:
    - name: docker-config
      secret:
        secretName: regcred
        items:
          - {key: .dockerconfigjson, path: config.json}
```
:::note
Pin the executor to a version or digest you trust rather than latest, and check whether the project you use is still maintained.
:::
@end

@concept Choosing a toolchain
@plain
Pick by environment: developer laptop, CI, cluster node. They need not be the same tool.
@problem
Standardising on one tool everywhere leads to compromises, while choosing randomly breaks scripts.
@does
- Laptop: Colima (Docker CLI, light), Podman (daemonless), Rancher Desktop or OrbStack as GUI options; check each licence.
- CI: BuildKit (buildx) with remote cache, or Buildah/Podman rootless; avoid mounting the Docker socket.
- Cluster nodes: containerd with `crictl`; `nerdctl` for deeper debugging.
- Test your Compose files and Testcontainers setup before migrating a team.
@diagram cmp
caption: Where each tool fits
cards:
  - {h: "Laptop", kind: info, items: ["Colima", "Podman machine", "Rancher Desktop"]}
  - {h: "CI", kind: ok, items: ["BuildKit buildx", "Buildah rootless", "Kaniko or similar in Pods"]}
  - {h: "Cluster node", kind: warn, items: ["containerd", "crictl", "nerdctl for debug"]}
@choose Developer machine
Colima | you want the docker CLI and Compose unchanged | you need a GUI
Podman | you want rootless and daemonless | tools need the Docker socket and you cannot map it
Docker Desktop | policy allows it and you want the GUI and extensions | licence cost or resource use is an issue
@end
