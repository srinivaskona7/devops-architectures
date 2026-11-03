---
title: Namespaces, cgroups and container isolation
minutes: 40
objectives:
  - Name the Linux namespaces that give a container its own view of the system
  - Explain how cgroups limit CPU, memory and process count
  - Reproduce container isolation by hand with unshare and read cgroup limits
---
Docker did not invent containers. It packaged two Linux kernel features, namespaces and cgroups, behind a friendly tool. Knowing them explains OOM kills, CPU throttling and why a container sees only its own processes.

@concept Namespaces
@plain
A namespace wraps a global system resource so a process sees its own private copy. Processes in the same namespace see each other; others do not.
@problem
Without namespaces every process sees every other process, every network interface and the whole filesystem, so two apps could not both listen on port 80.
@does
- **pid**: own process tree; your app is PID 1.
- **net**: own interfaces, routes, iptables and ports.
- **mnt**: own mount table, so a different root filesystem.
- **uts** (hostname), **ipc** (shared memory), **user** (UID mapping), **cgroup** and **time** complete the set.
@diagram cmp
caption: Main namespaces and what each hides
cards:
  - {h: "pid", kind: app, items: ["Own process list", "App is PID 1", "Host PIDs invisible"]}
  - {h: "net", kind: info, items: ["Own eth0 and routes", "Own port space", "Own iptables"]}
  - {h: "mnt", kind: env, items: ["Own root filesystem", "Own mount points", "From the image"]}
  - {h: "user", kind: warn, items: ["UID 0 inside maps to high UID outside", "Basis of rootless mode", "Reduces root risk"]}
@h List a container's namespaces
```bash title="Namespaces of a process" lab
docker run -d --name ns alpine:3.20 sleep 300
PID=$(docker inspect -f '{{.State.Pid}}' ns)     # PID as seen by the host (Linux host or Docker VM)
sudo ls -l /proc/$PID/ns                           # one symlink per namespace
lsns -p $PID 2>/dev/null | head
docker rm -f ns
```
@check
Which namespace lets two containers both listen on port 8080? || The network namespace, because each has its own port space.
@end

@concept Building a container by hand
@plain
You can create a mini container with one command: `unshare` starts a program inside new namespaces. A container runtime does this plus a root filesystem and cgroups.
@problem
Containers feel like magic until you see that the core is a few system calls: clone, unshare, setns and pivot_root.
@does
- `unshare --pid --fork --mount-proc` gives a new PID namespace.
- `chroot` or `pivot_root` swaps the root directory to an image's files.
- A runtime then applies cgroups, drops capabilities and applies seccomp.
@diagram flow
caption: Steps a runtime performs to start a container
numbered: true
nodes:
  - "Unpack image|rootfs directory|info"
  - "New namespaces|pid net mnt uts ipc|env"
  - "pivot_root|switch to the rootfs|app"
  - "cgroups and seccomp|limits and syscall filter|warn"
  - "exec|your process starts|ok"
@h Try it
```bash title="A container without Docker" lab
sudo unshare --pid --fork --mount-proc --uts --net bash -c '
  hostname isolated
  echo "hostname is $(hostname)"
  ps -ef            # only this shell and ps are visible
  ip link           # only a loopback that is down
'
```
:::note
Needs a Linux host and root. On macOS use a Linux VM such as Colima or Multipass.
:::
@end

@concept Control groups (cgroups)
@plain
A cgroup is a kernel group of processes with limits and accounting. Namespaces control what a process can see; cgroups control how much it can use.
@problem
One runaway container could consume all memory or CPU and starve the others, or fill the process table with a fork bomb.
@does
- Modern kernels use **cgroup v2**, one tree under `/sys/fs/cgroup`.
- Files such as `memory.max`, `cpu.max`, `pids.max` hold the limits; `memory.current` and `cpu.stat` give usage.
- Docker flags map directly: `--memory`, `--cpus`, `--pids-limit`. Kubernetes `resources.limits` do the same.
@diagram layers
caption: cgroup v2 hierarchy on a Docker host
layers:
  - {label: "Root", nodes: ["/sys/fs/cgroup|kernel controllers|cp"]}
  - {label: "Docker slice", nodes: ["docker-abc.scope|container A, memory.max 128M|app", "docker-def.scope|container B, cpu.max 50000 100000|app"]}
  - {label: "Controllers", nodes: ["memory|bytes and OOM|ok", "cpu|shares and quota|ok", "pids|process count|ok", "io|disk bandwidth|ok"]}
@h Read the limits
```bash title="Limits as files" lab
docker run -d --name lim --memory 128m --cpus 0.5 --pids-limit 50 alpine:3.20 sleep 300
docker exec lim cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/cpu.max /sys/fs/cgroup/pids.max
docker stats --no-stream lim
docker rm -f lim
```
@check
What do the two numbers in cpu.max 50000 100000 mean? || A quota of 50 ms of CPU time per 100 ms period, which equals 0.5 CPU.
@end

@concept Memory limits and the OOM killer
@plain
When a container uses more memory than its limit, the kernel kills a process in it. The exit code is 137 and the container is marked OOMKilled.
@problem
Applications that run fine unlimited suddenly restart in production. The cause is usually a limit set too low or a leak, not a Docker fault.
@does
- The limit covers heap, stacks, page cache of the container's files and kernel memory it causes.
- JVMs and Node need tuning: Java reads the cgroup limit; Node needs `--max-old-space-size` below the limit.
- In Kubernetes `OOMKilled` appears in `kubectl describe pod`, with exit code 137.
@diagram seq
caption: How an OOM kill happens
actors: ["Container|your app|app", "Kernel|memory cgroup|cp", "Runtime|containerd or dockerd|env"]
steps:
  - "0>1: allocates more memory | req"
  - "note 1..1: usage reaches memory.max, reclaim fails"
  - "1>0: SIGKILL to a process | bad"
  - "2>0: container exits 137 | resp"
@h Reproduce
```bash title="Force an OOM kill" lab
docker run --name oom --memory 64m python:3.12-slim python -c "x = bytearray(200*1024*1024)"; echo "exit=$?"
docker inspect -f 'oom={{.State.OOMKilled}} exit={{.State.ExitCode}}' oom
docker rm oom
```
@end

@concept CPU limits and throttling
@plain
CPU limits do not kill; they pause. A container with `--cpus 0.5` may run only 50 ms in each 100 ms window, then waits.
@problem
Latency spikes appear in services that are not using much CPU on average, because bursts hit the quota and the process is frozen until the next period.
@does
- `--cpus` sets a hard quota (`cpu.max`). `--cpu-shares` is only a relative weight under contention.
- `cpu.stat` fields `nr_throttled` and `throttled_usec` show throttling directly.
- Many teams set CPU requests but omit CPU limits in Kubernetes to avoid throttling; memory limits are always kept.
@diagram flow
caption: Quota in a 100 ms window with 0.5 CPU
nodes:
  - "0 to 50 ms|process runs|ok"
  - "50 to 100 ms|throttled, waits|bad"
  - "Next window|quota refreshed|info"
@h Check for throttling
```bash title="Throttling counters" lab
docker run -d --name cpu --cpus 0.2 alpine:3.20 sh -c 'while :; do :; done'
sleep 5
docker exec cpu cat /sys/fs/cgroup/cpu.stat | grep -E 'nr_throttled|throttled_usec'
docker rm -f cpu
```
@end

@concept Linux features that harden containers
@plain
Beyond namespaces and cgroups, three features cut what a contained process can do: capabilities, seccomp and LSM profiles (AppArmor or SELinux).
@problem
Root inside a container is still the kernel's idea of root unless restricted. A shared kernel means every allowed syscall is attack surface.
@does
- **Capabilities** split root into about 40 pieces. Docker drops most by default and keeps 14.
- **seccomp** filters system calls; Docker's default profile blocks around 44 of over 300 calls.
- **AppArmor/SELinux** add mandatory access control rules.
- **no_new_privs** prevents setuid programs from gaining privileges.
@diagram layers
caption: Defence in depth around a container process
layers:
  - {label: "Process", nodes: ["Your app|runs as non-root|app"]}
  - {label: "Filters", nodes: ["Capabilities|reduced root powers|warn", "seccomp|syscall allow list|warn", "AppArmor or SELinux|file and resource rules|warn"]}
  - {label: "Isolation", nodes: ["Namespaces|what it can see|env", "cgroups|how much it can use|env"]}
@h Look at them
```bash title="Capabilities and seccomp status" lab
docker run --rm alpine:3.20 grep -E 'Cap(Prm|Eff)|Seccomp|NoNewPrivs' /proc/self/status
docker run --rm --cap-drop ALL alpine:3.20 grep CapEff /proc/self/status
docker run --rm --privileged alpine:3.20 grep CapEff /proc/self/status   # almost everything: avoid
```
:::danger
`--privileged` disables most isolation. Do not use it in production or in CI on shared runners.
:::
@end
