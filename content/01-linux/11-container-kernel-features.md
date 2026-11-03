---
title: Kernel features behind containers
minutes: 50
objectives:
  - Explain that a container is a normal process isolated by namespaces and limited by cgroups
  - Read and set cgroup v2 limits and understand OOM kills and CPU throttling
  - Drop capabilities, apply seccomp and describe how overlayfs builds image layers
---
There is no "container" object in the Linux kernel. A container is an ordinary process started with a few kernel features turned on. Knowing them explains Docker, containerd and every Kubernetes pod setting about resources and security.

@concept A container is a process with restrictions
@plain
Take a normal process and change what it can see (namespaces), how much it can use (cgroups), what it may do (capabilities, seccomp, LSM) and what its filesystem looks like (overlayfs). The result is what we call a container.
@problem
Virtual machines isolate strongly but each carries its own kernel and boots slowly. Teams needed isolation that starts in milliseconds and packs many workloads on one host.
@does
- All containers on a node **share the host kernel**. This is why a kernel bug can affect every container, and why Windows containers cannot run on a Linux kernel.
- Each feature is independent and can be used without Docker, for example `unshare`, `systemd-run` or `bwrap`.
- Container runtimes (runc) simply call these kernel interfaces in the right order.
@diagram layers
caption: The building blocks of a container
layers:
  - {label: "Isolation", nodes: ["Namespaces|what the process sees|cp"]}
  - {label: "Limits", nodes: ["cgroups v2|how much CPU, memory, IO|app"]}
  - {label: "Privilege", nodes: ["Capabilities|split up root|env", "seccomp|filter system calls|env", "SELinux or AppArmor|MAC policy|env"]}
  - {label: "Filesystem", nodes: ["overlayfs|image layers + writable layer|ok"]}
@h See it on any host
```bash title="A container process is visible from the host" lab
ls -l /proc/self/ns                          # the namespaces your shell lives in
cat /proc/self/cgroup                        # its cgroup path (a single line on cgroup v2)
grep -E 'Cap(Inh|Prm|Eff|Bnd)' /proc/self/status   # capability sets
grep Seccomp /proc/self/status               # 0 none, 1 strict, 2 filter
```
@check
Why can a kernel vulnerability break container isolation but not usually VM isolation? || Containers share one kernel; a VM has its own kernel and only the hypervisor is shared.
@end

@concept Namespaces
@plain
A **namespace** gives a process its own private view of one kind of system resource. Inside, the process thinks it is alone; outside, the host sees it as an ordinary process.
@problem
Without namespaces every process sees all other processes, all network interfaces and the same hostname and mounts. One application could kill or inspect another.
@does
- **pid**: own process tree where the first process is PID 1.
- **net**: own interfaces, routes, iptables and ports. **mnt**: own mount table. **uts**: own hostname. **ipc**: own shared memory.
- **user**: maps UIDs, so root inside can be an unprivileged user outside (rootless containers). **cgroup**: own view of the cgroup tree. **time** hides clock offsets.
- A Kubernetes pod shares one network namespace among its containers, which is why they talk over `localhost`.
@diagram cmp
caption: Namespace types and what each hides
cards:
  - {h: "pid", kind: cp, items: ["Own PID numbering", "Cannot see host processes"]}
  - {h: "net", kind: app, items: ["Own interfaces and ports", "Pod containers share one"]}
  - {h: "mnt and uts", kind: env, items: ["Own mounts and root dir", "Own hostname"]}
  - {h: "user", kind: ok, items: ["Root inside, nobody outside", "Basis of rootless mode"]}
@h Try it with unshare
```bash title="Create namespaces by hand" lab
sudo unshare --pid --fork --mount-proc --uts bash -c 'hostname demo; hostname; ps -ef | head -5'
sudo unshare --net bash -c 'ip link'          # only a loopback interface, and it is down
unshare --user --map-root-user bash -c 'id'   # uid=0 inside without real privileges
lsns | head                                    # namespaces on the host
sudo nsenter -t 1 -n ip -br addr | head -3     # enter PID 1's network namespace
```
:::tip
`nsenter -t <pid> -n` is the standard way to debug a container's network from the node when the image has no tools. In Kubernetes, `kubectl debug` with an ephemeral container does the same job.
:::
@check
Why do containers in one pod reach each other on localhost? || They share the pod's network namespace, so they share interfaces and the port space.
@end

@concept cgroups v2 resource limits
@plain
**Control groups** put processes into a tree and apply limits and accounting to each group: memory, CPU, IO and process count. Version 2 has one unified hierarchy under `/sys/fs/cgroup`.
@problem
One runaway process can eat all memory or CPU and starve its neighbours. Without limits, a node hosting many containers is only as stable as its worst application.
@does
- `memory.max` is a hard limit; exceeding it triggers the **OOM killer** inside that group. `memory.high` throttles before that. `memory.current` shows use.
- `cpu.max` holds `quota period`, for example `50000 100000` means half a CPU. When a group uses its quota it is **throttled** until the next period.
- `cpu.weight` sets relative share when CPUs are busy; `io.max` limits disk throughput; `pids.max` stops fork bombs.
- Kubernetes maps resource `limits` to these files: memory limit to `memory.max`, CPU limit to `cpu.max`, and CPU request to `cpu.weight`.
@diagram flow
caption: From a pod spec to kernel enforcement
numbered: true
nodes:
  - "Pod spec|limits memory 512Mi, cpu 500m|app"
  - "kubelet and runtime|create a cgroup per container|cp"
  - "cgroup files|memory.max, cpu.max|info"
  - "Kernel|OOM kill or throttle|warn"
@h Inspect and set limits
```bash title="cgroup v2 in practice" lab
stat -fc %T /sys/fs/cgroup                    # cgroup2fs means unified v2
cat /sys/fs/cgroup/cgroup.controllers         # controllers available
systemd-run --user --scope -p MemoryMax=100M -p CPUQuota=50% sleep 30 &   # start a limited process
systemd-cgls --no-pager | head -20            # the tree as systemd sees it
cat /sys/fs/cgroup/system.slice/cpu.stat 2>/dev/null | head -6   # nr_throttled shows throttling
```
:::warn
A container with a low CPU limit can be slow while the node shows idle CPUs, because of throttling. Check `nr_throttled` in `cpu.stat`, and consider raising or removing CPU limits while keeping requests.
:::
@check
What does exit code 137 with reason OOMKilled mean? || The container exceeded memory.max and the kernel sent SIGKILL (128 plus 9).
@end

@concept Linux capabilities
@plain
Historically root could do everything. **Capabilities** split that power into about forty separate rights, such as binding low ports or changing the system clock, which can be granted one by one.
@problem
A web server only needs to bind port 80. Running it as full root means a bug gives the attacker complete control of the host.
@does
- `CAP_NET_BIND_SERVICE` binds ports below 1024. `CAP_NET_ADMIN` changes network config. `CAP_SYS_ADMIN` is a huge catch-all that you should almost never grant.
- Each process has sets (permitted, effective, bounding). `capsh --decode` turns the hex mask into names.
- Docker drops most capabilities by default; Kubernetes lets you `drop: ["ALL"]` and add back only what you need.
- Privileged containers get everything and effectively remove isolation.
@diagram cmp
caption: Capability posture of a container
cards:
  - {h: "privileged: true", kind: bad, items: ["All capabilities", "Access to host devices", "Avoid except for system agents"]}
  - {h: "Runtime default", kind: warn, items: ["Roughly 14 capabilities", "Includes NET_RAW, CHOWN, SETUID"]}
  - {h: "drop ALL + add one", kind: ok, items: ["Only NET_BIND_SERVICE if needed", "Smallest blast radius"]}
@h Reading and restricting capabilities
```bash title="Inspect and drop capabilities" lab
grep CapEff /proc/self/status                 # effective set as a hex mask
capsh --decode=00000000a80425fb               # translate a mask into names
getcap -r /usr/bin 2>/dev/null | head         # binaries with file capabilities
docker run --rm --cap-drop ALL --cap-add NET_BIND_SERVICE alpine sh -c 'grep CapEff /proc/self/status'
```
```yaml title="Kubernetes securityContext"
securityContext:
  runAsNonRoot: true
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
    add: ["NET_BIND_SERVICE"]
```
@check
Which capability should make you suspicious in a pod review? || CAP_SYS_ADMIN, because it covers mounts, namespaces and many other privileged operations.
@end

@concept seccomp system call filtering
@plain
Programs ask the kernel to do things through **system calls**. A **seccomp** profile is a list of calls a process may make; any other call is blocked or logged.
@problem
Most applications use fewer than a hundred of the roughly three hundred and fifty system calls. Unused ones, such as `kexec_load` or `mount`, are attack surface for kernel exploits.
@does
- Mode 2 (filter) uses a BPF program to return allow, errno, log or kill for each call.
- Docker's default profile blocks around 44 risky calls. Kubernetes selects `RuntimeDefault` or a custom `Localhost` profile.
- `seccompProfile: RuntimeDefault` is a cheap, widely compatible hardening step and is part of the Pod Security Standards restricted level.
- `Unconfined` disables filtering and should be exceptional.
@diagram seq
caption: What happens when a process calls a blocked system call
actors: ["Process|container app|app", "Kernel|seccomp filter|cp"]
steps:
  - "0>1: syscall mount | req"
  - "note 1..1: BPF filter checks the call against the profile"
  - "1>0: EPERM or SIGSYS | bad"
  - "0>1: syscall read | req"
  - "1>0: allowed, result returned | resp"
@h Using seccomp
```yaml title="Pod with the runtime default profile"
apiVersion: v1
kind: Pod
metadata:
  name: api
spec:
  securityContext:
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: api
      image: registry.example.com/api:1.4.2
```
```bash title="Check the effect" lab
grep Seccomp /proc/self/status                         # 0 on a plain shell
docker run --rm alpine grep Seccomp /proc/self/status   # 2 means a filter is active
docker run --rm --security-opt seccomp=unconfined alpine grep Seccomp /proc/self/status
strace -c -f ls 2>&1 | head -12                        # which calls does a program use?
```
@check
What does seccomp restrict that capabilities do not? || The system calls a process may make at all, regardless of its privileges.
@end

@concept overlayfs and image layers
@plain
**overlayfs** stacks several read-only directories (image layers) under one writable directory and presents them as one merged filesystem. This is how container images share data and start instantly.
@problem
Copying a whole image for each container wastes disk and time. Ten containers from the same image should share the same bytes and store only what each one changes.
@does
- `lowerdir` holds read-only layers, `upperdir` the writable layer, `workdir` is scratch space, and `merged` is the combined view.
- Reading finds the first layer containing the file. Writing a lower file first **copies it up** into the writable layer. Deleting creates a **whiteout** marker.
- The writable layer disappears with the container. Persistent data belongs in volumes.
- Writes to deep layers are slower; heavy IO paths should use volumes.
@diagram layers
caption: How a container sees its filesystem
layers:
  - {label: "Merged view", nodes: ["/ of the container|what the app sees|ok"]}
  - {label: "Writable", nodes: ["upperdir|container changes, deleted on exit|warn"]}
  - {label: "Read only image", nodes: ["app layer|your code|app", "runtime layer|language packages|app", "base layer|OS files|app"]}
@h Build an overlay yourself
```bash title="Mount an overlay by hand" lab
mkdir -p /tmp/ov/{lower,upper,work,merged}
echo "from image" > /tmp/ov/lower/a.txt
sudo mount -t overlay overlay -o lowerdir=/tmp/ov/lower,upperdir=/tmp/ov/upper,workdir=/tmp/ov/work /tmp/ov/merged
echo "changed" > /tmp/ov/merged/a.txt          # triggers copy-up
cat /tmp/ov/lower/a.txt                         # unchanged: still "from image"
ls /tmp/ov/upper                                # the modified copy lives here
rm /tmp/ov/merged/a.txt && ls -l /tmp/ov/upper  # a whiteout (character device 0,0)
sudo umount /tmp/ov/merged
docker info --format '{{.Driver}}'              # normally overlay2
```
@check
Why does deleting a big file in a later Dockerfile layer not shrink the image? || The lower layer still contains it; the delete only adds a whiteout in a new layer.
@end
