---
title: Containers versus virtual machines
minutes: 45
objectives:
  - Explain what a container really is on a Linux host and how it differs from a virtual machine
  - Describe the Docker client, daemon, containerd and runc roles at a high level
  - Run, list, stop and clean up containers with the right lifecycle commands
---
A container is not a small virtual machine. It is an ordinary Linux process that the kernel has fenced in with namespaces, limited with cgroups and given its own root filesystem. Everything in Kubernetes pods, ECS tasks and CI runners builds on that idea.

@concept What a container really is
@plain
A container is a normal process (or group of processes) started with a restricted view of the machine: its own process list, network, hostname and filesystem. It shares the host kernel with every other container.
@problem
Applications break when the machine differs: a different Python version, a missing library, a conflicting port. Copying a whole operating system per application fixes that but is slow and heavy.
@does
- Packages the app together with its libraries and files, so "works on my machine" travels with it.
- Starts in milliseconds to a second, because no operating system boots; only a process starts.
- Costs megabytes instead of gigabytes, so one host runs dozens or hundreds.
- Isolation is weaker than a VM, because the kernel is shared. A kernel bug can affect every container.
@diagram layers
caption: Where a container sits on a host
layers:
  - {label: "Containers", nodes: ["api|python process + libs|app", "web|nginx process + libs|app", "worker|node process + libs|app"]}
  - {label: "Container runtime", nodes: ["containerd + runc|creates the isolated processes|cp"]}
  - {label: "Host", nodes: ["Linux kernel|shared by all containers|env", "Hardware or cloud VM|EC2 instance|plain"]}
@h See it is just a process
```bash title="A container is a host process" lab
docker run -d --name demo nginx:1.27-alpine        # start a container in the background
docker top demo                                    # the processes as the host sees them
ps -ef | grep "nginx: master" | head -2            # on Linux the same PID is visible on the host
docker exec demo cat /proc/1/cgroup                # the cgroup that limits it
docker rm -f demo                                  # stop and delete
```
:::note
On macOS and Windows, Docker Desktop runs a small Linux VM and your containers live inside it. The host-PID trick above only works on a Linux host or inside that VM.
:::
@check
Do containers have their own kernel? || No. They share the host kernel; only the view of processes, network and files is separate.
@end

@concept Containers versus virtual machines
@plain
A virtual machine emulates hardware and runs a complete guest operating system with its own kernel. A container skips all that and uses the host kernel directly.
@problem
Choosing wrongly costs money or security. VMs give strong isolation but boot slowly and waste memory on duplicate kernels. Containers are light but share a kernel.
@does
- VM: hypervisor (KVM, Nitro on AWS) plus guest kernel. Boot in tens of seconds, gigabytes per instance.
- Container: namespaces and cgroups on one kernel. Start in under a second, megabytes per instance.
- A container image must match the host kernel family: Linux containers need a Linux kernel, and the CPU architecture (amd64 or arm64) must match.
- For hostile multi-tenant workloads, run containers inside VMs or use microVMs (Firecracker, Kata Containers).
@diagram cmp
caption: Same goal, different cost and isolation
cards:
  - {h: "Virtual machine", kind: env, items: ["Own kernel per instance", "Boots in 20 to 60 seconds", "Gigabytes of disk and RAM", "Strong hardware level isolation"]}
  - {h: "Container", kind: app, items: ["Shares the host kernel", "Starts in under a second", "Megabytes per instance", "Process level isolation"]}
  - {h: "MicroVM", kind: info, items: ["Tiny VM with minimal devices", "Boots in about 125 ms (Firecracker)", "Used by AWS Lambda and Fargate", "Strong isolation, light cost"]}
@choose Picking an isolation unit
Container | packaging and running your own trusted services | running untrusted code from unknown tenants on a shared kernel
Virtual machine | different operating systems or strict tenant isolation | you need thousands of tiny, fast-starting units
MicroVM | multi-tenant platforms such as serverless | you need to run arbitrary host devices or GPUs directly
@end

@concept Docker architecture
@plain
Docker is several parts. The `docker` command is a client that talks over a socket to the Docker daemon (`dockerd`). The daemon builds images and delegates running containers to `containerd`, which uses `runc` to create them.
@problem
When something fails, you need to know which layer to blame: the CLI, the daemon, the runtime or the kernel. Kubernetes itself skips dockerd and talks to containerd directly.
@does
- `docker` CLI: sends REST requests to `/var/run/docker.sock`.
- `dockerd`: images, networks, volumes, the build engine (BuildKit).
- `containerd`: pulls images, manages snapshots and container lifecycle.
- `runc`: the small tool that sets up namespaces and cgroups, then starts your process.
:::danger
Access to `/var/run/docker.sock` is equal to root on the host. Never mount it into an untrusted container, and treat membership of the `docker` group as root access.
:::
@diagram flow
caption: What happens on docker run
numbered: true
nodes:
  - "docker CLI|sends the request|plain"
  - "dockerd|API, build, networks|app"
  - "containerd|image and lifecycle|cp"
  - "runc|namespaces and cgroups|env"
  - "Your process|PID 1 in the container|ok"
@h Inspect the pieces
```bash title="Client, server and runtime versions" lab
docker version --format 'client={{.Client.Version}} server={{.Server.Version}}'
docker info --format 'runtime={{.DefaultRuntime}} storage={{.Driver}} cgroup={{.CgroupVersion}}'
ls -l /var/run/docker.sock
docker context ls          # which daemon the CLI is currently talking to
```
@end

@concept Container lifecycle
@plain
A container moves through states: created, running, paused, exited, removed. Its writable data lives only as long as the container exists unless you store it in a volume.
@problem
Engineers lose data by deleting a container that held it, or leave hundreds of stopped containers consuming disk.
@does
- `docker run` = `create` + `start`. Add `-d` for background, `--rm` to delete on exit, `--name` to name it.
- `docker stop` sends SIGTERM, waits 10 seconds, then SIGKILL. Change the wait with `-t`.
- `docker ps -a` includes exited containers; `docker rm` deletes them.
- `--restart unless-stopped` makes the daemon restart the container after a crash or reboot.
@diagram flow
caption: Container states and the commands that move between them
nodes:
  - "Created|docker create|plain"
  - "Running|docker start or run|ok"
  - "Exited|stopped or crashed|warn"
  - "Removed|docker rm|bad"
@h Day one commands
```bash title="Lifecycle commands" lab
docker run -d --name web -p 8080:80 --restart unless-stopped nginx:1.27-alpine
docker ps                                  # running only
docker logs --tail 5 web
docker stop -t 5 web                       # SIGTERM, then SIGKILL after 5 seconds
docker ps -a --filter status=exited
docker start web && docker rm -f web
docker container prune -f                  # delete all stopped containers
```
@check
Why does docker stop sometimes take 10 seconds? || The app ignored SIGTERM (often because the shell is PID 1), so Docker waited the grace period and sent SIGKILL.
@end

@concept Running options you will use daily
@plain
`docker run` has dozens of flags. A small set covers nearly everything: ports, environment, volumes, resource limits and the user.
@problem
Defaults are unlimited: a container can use all host memory, run as root and listen on any port. Production use needs explicit limits.
@does
- `-p host:container` publishes a port. `-p 127.0.0.1:8080:80` binds only to localhost.
- `-e KEY=value` and `--env-file` set environment variables.
- `--memory 256m --cpus 0.5` set cgroup limits. Exceeding memory triggers the OOM killer (exit code 137).
- `--user 1000:1000` runs as a non-root user; `--read-only` makes the root filesystem read-only.
@diagram cmp
caption: Flags grouped by what they control
cards:
  - {h: "Network", kind: info, items: ["-p 8080:80", "--network mynet", "--hostname api"]}
  - {h: "Resources", kind: warn, items: ["--memory 256m", "--cpus 0.5", "--pids-limit 200"]}
  - {h: "Security", kind: bad, items: ["--user 1000:1000", "--read-only", "--cap-drop ALL"]}
  - {h: "Data", kind: ok, items: ["-v data:/var/lib/app", "--tmpfs /tmp", "-e KEY=value"]}
@h A realistic run
```bash title="Limits and safety in one command" lab
docker run -d --name api \
  -p 127.0.0.1:8000:8000 \
  -e LOG_LEVEL=info \
  --memory 256m --cpus 0.5 --pids-limit 200 \
  --user 1000:1000 --read-only --tmpfs /tmp \
  --cap-drop ALL --security-opt no-new-privileges \
  python:3.12-slim python -m http.server 8000
docker stats --no-stream api
docker rm -f api
```
:::tip
Exit code 137 means SIGKILL (128 + 9), very often the OOM killer. Check with `docker inspect -f '{{.State.OOMKilled}}' api`.
:::
@end

@concept Containers on AWS and Kubernetes
@plain
The same container image runs on your laptop, in CI, on ECS or Fargate and in a Kubernetes pod. What differs is who starts it and how.
@problem
Engineers often think of Docker as a development tool only, and then are surprised that production uses a different runtime and different defaults.
@does
- Kubernetes (EKS, Kyma) uses containerd or CRI-O through the CRI interface; there is no dockerd on the node.
- A pod is one or more containers sharing a network namespace; the image is the same OCI image.
- `docker run` flags map to pod spec fields: `--memory` to `resources.limits.memory`, `--user` to `securityContext.runAsUser`, `-e` to `env`.
- ECS and Fargate use the same images with a task definition instead.
@diagram flow
caption: One image, many places to run it
nodes:
  - "Image|built once in CI|app"
  - "Registry|ECR or GHCR|cp"
  - "Laptop|docker run|plain"
  - "EKS or Kyma|pod via containerd|ok"
  - "ECS Fargate|task definition|ok"
@h The mapping
```yaml title="docker run flags as a pod spec" nocheck
# docker run --memory 256m --cpus 0.5 --user 1000 --read-only -e LOG_LEVEL=info app:1.0
apiVersion: v1
kind: Pod
metadata:
  name: app
spec:
  containers:
    - name: app
      image: app:1.0
      env:
        - {name: LOG_LEVEL, value: info}
      resources:
        limits: {memory: 256Mi, cpu: 500m}
      securityContext:
        runAsUser: 1000
        readOnlyRootFilesystem: true
```
@end
