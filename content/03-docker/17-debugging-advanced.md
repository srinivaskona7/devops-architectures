---
title: Debugging containers part two
minutes: 45
objectives:
  - Debug shell-less and distroless containers with a toolbox container sharing namespaces
  - Use kubectl debug ephemeral containers and node debugging in Kubernetes
  - Inspect a container from the host with nsenter, strace and tcpdump
---
Hardened images have no shell and no tools, which is good for security and bad for debugging. The answer is to bring tools to the container instead of putting tools in the image.

@concept Sharing namespaces with a toolbox container
@plain
You can start a second container that joins the namespaces of the broken one. It brings its own tools but sees the target's network, processes or filesystem.
@problem
The target is distroless and has no shell. Installing packages into it is impossible and would alter the evidence.
@does
- `--network container:NAME` shares the network namespace: same IPs, same listening ports, same DNS.
- `--pid container:NAME` shares the process namespace, so `ps` and `strace -p` see the app.
- `--cap-add SYS_PTRACE` is needed for strace.
- Popular toolbox images: `nicolaka/netshoot`, `busybox`, `alpine` with `apk add`.
@diagram layers
caption: A toolbox container joined to the target
layers:
  - {label: "Toolbox container", nodes: ["netshoot|tcpdump, curl, dig, ss, strace|ok"]}
  - {label: "Shared namespaces", nodes: ["net|same IP and ports|info", "pid|same process list|info"]}
  - {label: "Target container", nodes: ["distroless app|no shell, no tools|app"]}
@h Attach netshoot
```bash title="Debug a distroless container from outside" lab
docker run --rm -it --network container:api --pid container:api --cap-add SYS_PTRACE nicolaka/netshoot
# now inside netshoot
ss -ltnp                      # what the app listens on
curl -s localhost:8000/healthz
ps aux                        # the app's processes
strace -f -p 1 -e trace=network -tt   # watch its network syscalls
```
@check
Why is --network container:NAME better than installing curl into the target? || The target stays unchanged, so the evidence is intact, and the same image keeps its small attack surface.
@end

@concept Ephemeral debug containers in Kubernetes
@plain
`kubectl debug` adds a temporary container to a running pod. It shares the pod's network, can share the target container's process namespace, and is removed when the pod is replaced.
@problem
Production pods use distroless images, and `kubectl exec` fails with "executable file not found". Rebuilding with a shell would change the thing being debugged.
@does
- Ephemeral containers are stable in Kubernetes 1.25 and later.
- `--target=CONTAINER` shares the target's process namespace, so you see its processes and `/proc/1/root` gives its filesystem.
- `kubectl debug -it POD --image=nicolaka/netshoot --target=app`.
- Copy a pod to debug: `kubectl debug POD -it --copy-to=POD-debug --container=app --image=busybox -- sh`.
- Needs RBAC on `pods/ephemeralcontainers`.
@diagram flow
caption: Ephemeral container added to a live pod
numbered: true
nodes:
  - "kubectl debug|POD, image, target|ext"
  - "API server|patches pod ephemeralcontainers|cp"
  - "kubelet|starts the container|env"
  - "Shell in pod|shared net and pid namespace|ok"
@h Commands
```bash title="Debug a pod without a shell" lab
kubectl debug -it pod/shop-api-7d9c -n shop --image=nicolaka/netshoot --target=api
# inside
ps aux
ls /proc/1/root/app                 # the target container filesystem
curl -s localhost:8000/healthz
exit
kubectl get pod shop-api-7d9c -n shop -o jsonpath='{.spec.ephemeralContainers[*].name}'
```
```bash title="Debug a node and a crashing pod" lab
kubectl debug node/ip-10-0-1-23.eu-west-1.compute.internal -it --image=busybox      # host filesystem under /host
kubectl debug pod/shop-api-7d9c -n shop -it --copy-to=shop-api-debug --container=api -- sh
kubectl logs shop-api-7d9c -n shop --previous                                       # last crashed instance
```
:::note
A pod copy created with `--copy-to` is a new pod, so it lacks the crashed state but runs the same image and spec, with the command you override. Delete it when done.
:::
@end

@concept nsenter from the host
@plain
`nsenter` runs a command from the host inside any of a process's namespaces. It needs the PID of the container's main process on the host.
@problem
Sometimes only the node is reachable, the container has no tools and the engine is unhealthy. nsenter still works because it needs only the kernel.
@does
- Get the PID: `docker inspect -f '{{.State.Pid}}' NAME`, or `crictl inspect --output go-template --template '{{.info.pid}}' ID`.
- `nsenter -t PID -n ip addr` enters only the network namespace, using the host's own tools on the container's network.
- `-m` mount, `-p` pid, `-u` hostname, `-i` ipc, `-a` all.
- Typical use: run the host's `tcpdump`, `ss`, `iptables` against the pod's network namespace.
@diagram flow
caption: Host tools, container namespace
nodes:
  - "Host shell|root with full tools|env"
  - "Find PID|docker inspect or crictl|info"
  - "nsenter -t PID -n|joins the net namespace|app"
  - "ss, tcpdump, curl|run host binaries|ok"
@h Examples
```bash title="Inspect the container network from the node" lab
PID=$(docker inspect -f '{{.State.Pid}}' api)
sudo nsenter -t $PID -n ip -br addr
sudo nsenter -t $PID -n ss -ltnp
sudo nsenter -t $PID -n tcpdump -ni eth0 -c 10 port 5432
sudo nsenter -t $PID -m -p ls /app           # its filesystem and process view
```
@end

@concept strace, tcpdump and /proc
@plain
When logs are silent, look at system calls and packets. `strace` shows every syscall the process makes; `tcpdump` shows the bytes on the wire; `/proc` shows live state without any tool.
@problem
Hangs, "permission denied" and "connection refused" with no explanation need evidence below the application layer.
@does
- `strace -f -tt -p PID -e trace=openat,connect` shows files opened and connections attempted, including failing ones with `ENOENT` or `EACCES`.
- `tcpdump -ni any port 5432 -w out.pcap` captures traffic for Wireshark.
- `/proc/PID/environ`, `/proc/PID/cmdline`, `/proc/PID/fd`, `/proc/PID/limits`, `/proc/PID/status` (Threads, VmRSS).
- strace slows the process and needs `SYS_PTRACE`; use briefly.
@diagram cmp
caption: Which tool answers which question
cards:
  - {h: "strace", kind: info, items: ["Which file or syscall fails", "ENOENT, EACCES, EPERM", "Where is it blocked"]}
  - {h: "tcpdump", kind: app, items: ["Is traffic leaving", "Resets, retransmits, DNS", "TLS handshake failures"]}
  - {h: "/proc", kind: ok, items: ["No tools needed", "Env, fds, limits, memory", "Works in any container"]}
@h Examples
```bash title="From inside a toolbox container" lab
strace -f -tt -e trace=openat,connect -p 1 2>&1 | grep -E 'ENOENT|EACCES|ECONNREFUSED' | head
tcpdump -ni any -c 20 'port 53'                  # watch DNS lookups
tr '\0' '\n' < /proc/1/environ | sort | head     # environment of PID 1, needs the pid namespace
ls -l /proc/1/fd | head
grep -E 'VmRSS|Threads' /proc/1/status
```
@end

@concept Common failure patterns
@plain
A short catalogue of symptoms, their usual cause and the quickest confirmation.
@problem
Most incidents repeat. Recognising the pattern cuts diagnosis to minutes.
@does
- `exec format error`: image architecture differs from the node. Check `docker image inspect --format '{{.Architecture}}'`.
- `permission denied` writing files: non-root user versus root-owned volume, or read-only root filesystem.
- `connection refused` between containers: app listens on 127.0.0.1 instead of 0.0.0.0, or wrong port.
- Exits immediately with code 0: process daemonised or the command is a shell that ended.
- `no space left on device`: images, build cache, logs or volumes. Check `docker system df`.
- `ImagePullBackOff`: wrong name or tag, missing pull secret, rate limit, no network egress.
- `CrashLoopBackOff`: look at `kubectl logs --previous` and `describe pod` for exit code and OOMKilled.
@diagram cmp
caption: Symptom to first check
cards:
  - {h: "Will not start", kind: bad, items: ["exec format error: architecture", "127: command or file missing", "125: bad docker run flags"]}
  - {h: "Starts then dies", kind: warn, items: ["137: OOM or kill", "1: read the logs", "0: no foreground process"]}
  - {h: "Runs but unreachable", kind: info, items: ["Bound to 127.0.0.1", "Port not published", "Wrong network or DNS"]}
  - {h: "Slow or full", kind: env, items: ["docker system df", "CPU throttling", "Log growth"]}
@h Triage script
```bash title="triage.sh" lab
#!/usr/bin/env bash
# usage: triage.sh CONTAINER
set -u
c=${1:?container name required}
docker inspect "$c" --format 'status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} restarts={{.RestartCount}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}'
echo "--- last logs"; docker logs --tail 20 "$c" 2>&1
echo "--- image arch vs host"; docker image inspect "$(docker inspect -f '{{.Image}}' "$c")" --format '{{.Architecture}}'; uname -m
echo "--- disk"; docker system df
```
@end

@concept Debugging performance and resource problems
@plain
Slow containers are usually CPU throttled, memory starved, waiting on disk or limited by the process count. The cgroup files and `docker stats` show which.
@problem
Application metrics say the service is slow but not why. Node level graphs average away short throttling bursts.
@does
- `docker stats` for live CPU, memory, network and block I/O per container.
- `/sys/fs/cgroup/cpu.stat` throttling counters, `memory.events` (oom, oom_kill counts), `pids.current` versus `pids.max`.
- Kubernetes: `kubectl top pod --containers`, and the metric `container_cpu_cfs_throttled_periods_total` in Prometheus.
- Disk: `docker system df -v`, `du -sh /var/lib/docker/*`, and `iostat -x` on the host.
@diagram cmp
caption: Resource symptom to evidence
cards:
  - {h: "CPU throttled", kind: warn, items: ["nr_throttled rising in cpu.stat", "Raise the limit or remove it"]}
  - {h: "Memory pressure", kind: bad, items: ["memory.events oom_kill > 0", "Raise limit or fix the leak"]}
  - {h: "PID exhaustion", kind: bad, items: ["pids.current near pids.max", "Fork errors in logs"]}
  - {h: "Disk full", kind: env, items: ["docker system df", "Prune images, cache, logs"]}
@h Read the counters
```bash title="cgroup evidence" lab
docker exec api sh -c 'cat /sys/fs/cgroup/memory.events; cat /sys/fs/cgroup/pids.current /sys/fs/cgroup/pids.max'
docker exec api sh -c 'grep -E "nr_periods|nr_throttled|throttled_usec" /sys/fs/cgroup/cpu.stat'
docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}'
```
@end
