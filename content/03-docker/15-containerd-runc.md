---
title: containerd, runc and the runtime stack
minutes: 45
objectives:
  - Trace what happens from docker run or a Kubernetes pod to a running process
  - Use ctr, nerdctl and crictl to inspect containers on a node
  - Compare runc, crun, gVisor and Kata runtimes and select a RuntimeClass
---
Kubernetes nodes run containerd or CRI-O, not Docker. When a pod is stuck you often need to look one layer below kubectl. This section shows the stack and the tools for each layer.
 
@concept The runtime stack
@plain
Starting a container passes through several programs, each with one job: an orchestrator asks a high level runtime (containerd), which asks a shim, which calls a low level runtime (runc), which makes the kernel calls and then exits.
@problem
Without clear layers, upgrading Docker would kill every container, and Kubernetes would need Docker specific code.
@does
- **kubelet** talks CRI (gRPC) to containerd's CRI plugin.
- **containerd** pulls images, unpacks snapshots, manages container metadata.
- **containerd-shim-runc-v2** stays alive as the container's parent, so containerd can restart without killing containers.
- **runc** creates namespaces, cgroups, mounts, drops capabilities, then `exec`s your process and exits.
- Dockershim was removed from Kubernetes in 1.24; Docker built images still run unchanged.
@diagram flow
caption: From kubelet to your process
numbered: true
nodes:
  - "kubelet|CRI gRPC|cp"
  - "containerd|images, snapshots, tasks|app"
  - "shim v2|parent of the container|info"
  - "runc|sets up kernel isolation|env"
  - "Your process|PID 1 in the container|ok"
@h See the process tree on a node
```bash title="Shim and container processes" lab
ps -eo pid,ppid,comm,args --forest | grep -E 'containerd|shim|nginx' | head -12
pstree -ap $(pgrep -o containerd-shim) 2>/dev/null | head
```
@check
Why can containerd restart without stopping running containers? || Each container's parent is its own shim process, not the containerd daemon.
@end

@concept containerd and its namespaces
@plain
containerd stores containers and images in **namespaces**, which are just logical groups inside containerd. Kubernetes uses `k8s.io`, Docker uses `moby`.
@problem
Running `ctr containers ls` on a Kubernetes node shows nothing and confuses people, because it looks in the `default` namespace.
@does
- `ctr` is the low level client bundled with containerd, `nerdctl` is a Docker-compatible CLI, `crictl` speaks CRI and is the right tool on Kubernetes nodes.
- Config lives in `/etc/containerd/config.toml`; sockets at `/run/containerd/containerd.sock`.
- Snapshotter is `overlayfs` by default; `stargz` and `nydus` enable lazy pulling of large images.
- Registry mirrors and credentials are configured per host under `/etc/containerd/certs.d/`.
@diagram layers
caption: containerd internals
layers:
  - {label: "API", nodes: ["gRPC socket|containerd.sock|cp", "CRI plugin|for kubelet|cp"]}
  - {label: "Services", nodes: ["Content store|blobs by digest|info", "Snapshotter|overlayfs layers|info", "Metadata|containers and tasks|info"]}
  - {label: "Runtime", nodes: ["shim v2|per container|env", "runc|OCI runtime|env"]}
@h Tools on a node
```bash title="ctr and crictl" lab
ctr namespaces ls                              # default, k8s.io, moby ...
ctr -n k8s.io images ls | head -5
ctr -n k8s.io containers ls | head -5
crictl ps                                      # CRI view: running containers
crictl images | head -5
crictl inspect $(crictl ps -q | head -1) | jq '.info.runtimeSpec.linux.cgroupsPath'
```
@end

@concept runc in action
@plain
`runc` is a small command that reads a bundle and starts the container. It does the kernel work then leaves; the shim keeps watching.
@problem
Seeing runc directly demystifies container start: no scheduler, no network plugin, just a process in namespaces.
@does
- `runc create`, `start`, `exec`, `kill`, `delete`, `state`, `list` operate on a bundle directory.
- Container state lives in `/run/runc/<id>` (Docker) or `/run/containerd/runc/k8s.io/<id>` (Kubernetes).
- Rootless mode uses a user namespace so no root is needed.
- Faster alternative `crun` (written in C) is the default on Red Hat based systems.
@diagram seq
caption: What runc does when started
actors: ["shim|containerd-shim-runc-v2|info", "runc|OCI runtime|env", "Kernel|clone, mount, cgroups|cp", "App|container process|app"]
steps:
  - "0>1: runc create with bundle | req"
  - "1>2: clone with new namespaces | req"
  - "1>2: pivot_root, mount proc, cgroups, seccomp | req"
  - "0>1: runc start | req"
  - "1>3: exec the entrypoint | resp"
  - "note 0..1: runc exits, shim stays as parent"
@h Run alpine with only runc
```bash title="A container with runc, no Docker" lab
mkdir -p /tmp/rc/rootfs && cd /tmp/rc
docker export $(docker create alpine:3.20) | tar -C rootfs -xf -
runc spec --rootless                           # rootless-friendly config.json
jq '.process.args = ["sh","-c","echo hello from runc; hostname"] | .process.terminal = false' config.json > c.json && mv c.json config.json
runc run demo1
```
@end

@concept Alternative runtimes and RuntimeClass
@plain
Because the runtime spec is standard, you can replace runc with a runtime that adds a stronger isolation boundary, and choose it per pod.
@problem
Some workloads run code you do not trust (CI jobs, customer plugins). A shared kernel is a risk there, but full VMs are heavy.
@does
- **gVisor** (`runsc`): a user space kernel intercepts syscalls; strong isolation, some compatibility and I/O cost.
- **Kata Containers**: each pod in a lightweight VM with its own kernel.
- **Firecracker** microVMs power AWS Lambda and Fargate; on EKS you can use Fargate profiles for pod-level VM isolation.
- Kubernetes `RuntimeClass` maps a name to a runtime handler configured in containerd.
@diagram cmp
caption: Isolation versus overhead
cards:
  - {h: "runc", kind: warn, items: ["Shared kernel", "Fastest, default", "Namespaces and cgroups"]}
  - {h: "gVisor", kind: info, items: ["User space kernel", "Syscall filtering layer", "Some apps incompatible"]}
  - {h: "Kata or Firecracker", kind: ok, items: ["Own kernel per pod", "Hardware isolation", "Higher memory and startup cost"]}
@h Use a RuntimeClass
```yaml title="RuntimeClass and a pod that uses it"
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
---
apiVersion: v1
kind: Pod
metadata:
  name: untrusted-job
spec:
  runtimeClassName: gvisor
  containers:
    - name: job
      image: alpine:3.20
      command: ["sh", "-c", "uname -a; sleep 30"]
```
@end

@concept Image pull path and lazy pulling
@plain
When a pod starts on a new node the image pull often dominates startup time. containerd downloads the manifest, then layers in parallel, decompresses and unpacks each one into a snapshot.
@problem
A 2 GB image on a node with a cold cache makes scale-out events slow and can exceed deployment timeouts.
@does
- Layers are fetched in parallel (`max_concurrent_downloads`, default 3) and unpacked sequentially.
- Smaller images, fewer large layers and zstd compression all shorten pulls.
- Lazy-pulling snapshotters (SOCI on AWS, stargz, Nydus) start the container before the whole image is downloaded.
- Pre-pulling with a DaemonSet or baking images into the node AMI removes pull time for critical images.
- `imagePullPolicy: IfNotPresent` prevents repeated registry checks.
@diagram flow
caption: Where pull time goes
nodes:
  - "Manifest fetch|small|ok"
  - "Layer download|parallel, network bound|warn"
  - "Decompress and unpack|CPU and disk bound|warn"
  - "Create container|fast|ok"
@h Measure
```bash title="Time a pull on a node" lab
crictl rmi python:3.12-slim 2>/dev/null
time crictl pull python:3.12-slim
crictl imagefsinfo | jq '.status.imageFilesystems[0].usedBytes'
kubectl get events -A --field-selector reason=Pulled | tail -5      # shows 'Successfully pulled image ... in 4.2s'
```
@end

@concept Troubleshooting on a Kubernetes node
@plain
When kubectl shows a pod stuck in ContainerCreating or ImagePullBackOff, the cause is often visible only on the node, in kubelet and containerd logs.
@problem
Control plane tools show a symptom; the node knows the reason: a CNI failure, disk pressure, a registry certificate error or a runtime crash.
@does
- `journalctl -u kubelet -u containerd --since "15 min ago"` for runtime and kubelet errors.
- `crictl pods`, `crictl ps -a`, `crictl logs ID`, `crictl inspectp POD` for the runtime view.
- `df -h /var/lib/containerd` and `crictl imagefsinfo` for image disk pressure; kubelet evicts pods and garbage collects images at thresholds (85 percent by default for image GC).
- On EKS and Kyma use SSM Session Manager or `kubectl debug node/NAME` instead of SSH.
@diagram flow
caption: From symptom to node evidence
numbered: true
nodes:
  - "kubectl describe pod|events and reason|info"
  - "kubectl debug node|shell on the node|ext"
  - "crictl and journalctl|runtime evidence|app"
  - "Fix|disk, registry auth, CNI|ok"
@h Commands
```bash title="On the node" lab
journalctl -u containerd -u kubelet --since "15 min ago" --no-pager | grep -iE 'error|fail|denied' | tail -15
crictl ps -a | head
df -h /var/lib/containerd /var/lib/kubelet
crictl pull ghcr.io/acme/shop-api:sha-3f9c2ab        # reproduce the pull outside kubelet
```
@end
