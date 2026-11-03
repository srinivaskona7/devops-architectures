---
title: How a computer runs your program
minutes: 35
objectives:
  - Explain how source code becomes a running process
  - Describe what the CPU, memory and storage each contribute and where they limit performance
  - Relate processes and threads to containers and pods
---
Every DevOps problem eventually lands on one of four resources: CPU, memory, storage or network. This page builds the mental model that makes the rest of the path easier.

@concept From source code to a running program
@plain
You write text. A **compiler** or **interpreter** turns it into instructions the CPU understands. The result is stored as a file, and the operating system loads that file into memory to run it.
@problem
Without this model, errors like "exec format error" or "no such file or directory" for a file that clearly exists are baffling. They are usually a mismatch between the program and the machine.
@does
- Compiled languages (Go, C, Rust) produce a binary for one CPU architecture, such as amd64 or arm64.
- Interpreted languages (Python, JavaScript) need an interpreter installed alongside your code.
- A container image bundles the program, its libraries and its interpreter so the host only needs a kernel.
- An arm64 image on an amd64 node fails because the instructions differ. Multi-architecture images solve this.
@diagram flow
caption: The path from code to a running process
numbered: true
nodes:
  - "Source|app.go|plain"
  - "Compile|build step in CI|info"
  - "Binary file|stored on disk or in an image|app"
  - "Loader|kernel maps it into memory|cp"
  - "Process|CPU executes instructions|ok"
@h Inspecting a binary
```bash title="What kind of program is this" lab
uname -m                      # CPU architecture of this machine
file /bin/ls                  # executable format and target architecture
ldd /bin/ls | head -5         # shared libraries it needs at start-up
head -c 4 /bin/ls | od -c     # the first bytes: ELF on Linux
```
@check
Why can an arm64 container image fail on an amd64 node? || The compiled instructions are for a different CPU architecture, so the kernel cannot execute them.
@end

@concept The CPU, cores and threads
@plain
The CPU executes instructions billions of times per second. A modern server CPU has many **cores**, and each core runs one instruction stream at a time (two with hyper-threading).
@problem
When an application is slow you must tell apart "waiting for the CPU" from "waiting for something else". Adding CPUs to an application that waits on a database changes nothing.
@does
- A **thread** is one stream of execution; a process has one or more threads sharing memory.
- The scheduler time-slices runnable threads across cores. More runnable threads than cores means queueing.
- Utilization is the share of time a core is busy; the **run queue** length shows how many threads are waiting.
- Kubernetes CPU requests and limits are expressed in cores or millicores. 500m means half a core.
@diagram layers
caption: Where CPU time goes on a node
layers:
  - {label: "Hardware", nodes: ["Core 0|runs one thread|env", "Core 1|runs one thread|env", "Core 2|runs one thread|env"]}
  - {label: "Kernel", nodes: ["Scheduler|time slices threads|cp", "cgroup cpu|enforces limits|cp"]}
  - {label: "Workloads", nodes: ["Pod A|500m request|app", "Pod B|2 cores limit|app"]}
@h Looking at CPUs
```bash title="CPU facts and load" lab
nproc                         # logical CPUs available
lscpu | head -12              # model, cores, threads, caches
uptime                        # load averages
top -b -n 1 | head -5         # one snapshot, shows user, system, idle, iowait
```
:::tip
A CPU limit in Kubernetes does not reduce cores; it throttles the container after it uses its quota in each 100 ms period. Heavy throttling shows as latency, not as errors.
:::
@end

@concept Memory, virtual memory and the OOM killer
@plain
Memory (RAM) is fast, temporary storage that the CPU reads directly. Each process sees its own private **virtual** address space, and the kernel maps pieces of it to real RAM.
@problem
Programs would overwrite each other without isolation, and a machine with 8 GiB could never run programs that together want 20 GiB. When memory truly runs out, something must give.
@does
- Pages (usually 4 KiB) are mapped on demand; untouched memory costs nothing.
- Spare RAM becomes the **page cache**, speeding up file reads. It is reclaimed when applications need it, so "free" memory looks low on healthy servers.
- Swap moves cold pages to disk. It is slow, so heavy swapping means too little RAM.
- When the kernel cannot reclaim enough, the **OOM killer** ends a process. Inside a container, exceeding the memory limit gets the container killed with exit code 137.
@diagram flow
caption: Memory pressure escalates in stages
nodes:
  - "Free RAM|plenty|ok"
  - "Page cache shrinks|reclaimed quietly|info"
  - "Swap|cold pages to disk, slow|warn"
  - "OOM kill|process ended, exit 137|bad"
@h Reading memory
```bash title="Memory views" lab
free -h                              # use the available column, not free
grep -E 'MemTotal|MemAvailable|SwapTotal' /proc/meminfo
ps -eo pid,rss,comm --sort=-rss | head -5      # biggest resident users
dmesg 2>/dev/null | grep -i 'killed process' | tail -3   # past OOM kills
```
@check
Why is low "free" memory not a problem by itself? || The kernel uses spare RAM as page cache and gives it back on demand; check "available" instead.
@end

@concept Storage: disks, latency and IOPS
@plain
Storage keeps data when the power is off. Its speed is described by **throughput** (MB per second), **IOPS** (operations per second) and **latency** (time per operation).
@problem
A database on slow storage is slow no matter how big the CPU is. Choosing a volume type without knowing which number matters wastes money or causes outages.
@does
- Memory access takes about 100 nanoseconds; an NVMe read about 100 microseconds; a network disk such as an EBS volume about a millisecond. Each step is roughly ten to a thousand times slower.
- Small random reads and writes are limited by IOPS; large sequential copies by throughput.
- Cloud volumes have provisioned or burst limits. When the limit is hit, latency rises sharply.
- Local (instance store) disks are fast but vanish with the instance.
@diagram cmp
caption: Rough speed and durability of storage tiers
cards:
  - {h: "RAM", kind: ok, items: ["About 100 ns", "Lost at power off"]}
  - {h: "Local NVMe", kind: app, items: ["About 100 us", "Lost if instance stops"]}
  - {h: "Network block volume", kind: info, items: ["About 1 ms", "Survives the instance"]}
  - {h: "Object storage", kind: warn, items: ["Tens of ms", "Cheap and very durable"]}
@h Measuring a disk
```bash title="Quick disk checks" lab
df -h /                       # capacity used
lsblk                         # block devices and mount points
iostat -x 1 3                 # per device utilization and wait (package sysstat)
dd if=/dev/zero of=/tmp/t bs=1M count=256 oflag=direct 2>&1 | tail -1; rm /tmp/t   # crude write speed
```
:::note
`dd` is only a crude check. For real planning use `fio` and check the current cloud provider documentation for volume limits.
:::
@end

@concept The kernel, system calls and user space
@plain
The **kernel** is the privileged core of the operating system. Programs run in **user space** and ask the kernel to do anything involving hardware, files or the network through **system calls**.
@problem
If every program could touch the disk or network card directly, a single bug would corrupt everything. The boundary gives safety and a place to observe behaviour.
@does
- Opening a file, reading a socket or starting a process each become syscalls such as `openat`, `read`, `clone`.
- `strace` lists the syscalls a program makes, which is often the quickest way to see why it fails.
- Containers share the host kernel. This is why they start in milliseconds and why a kernel bug affects all of them.
@diagram layers
caption: The boundary between your program and the hardware
layers:
  - {label: "User space", nodes: ["Your app|Python, Go, Java|app", "libc|wraps syscalls|info"]}
  - {label: "Kernel", nodes: ["Syscall interface|open, read, write, clone|cp", "Filesystems|ext4, xfs|cp", "TCP/IP stack|sockets|cp"]}
  - {label: "Hardware", nodes: ["CPU|plain", "Disk|plain", "Network card|plain"]}
@h See syscalls
```bash title="Trace a command" lab
strace -f -e trace=openat,connect curl -sI http://example.com 2>&1 | head -15
strace -c ls /etc > /dev/null      # summary count of syscalls by type
```
@check
Why do containers share a kernel but virtual machines do not? || Containers are isolated processes on one kernel; each VM boots its own kernel on virtual hardware.
@end

@concept Processes, threads and containers
@plain
A process is an isolated running program. A thread is a lighter unit inside it. A container is simply a process (or group) with a restricted view of the system.
@problem
Newcomers think a container is a small virtual machine and then cannot explain why `ps` on the host shows container processes.
@does
- Namespaces limit what a process can see (processes, network, mounts). Cgroups limit what it can use (CPU, memory).
- A pod is one or more containers that share a network namespace.
- Killing the main process ends the container, because it is PID 1 of that namespace.
@diagram flow
caption: Layers of isolation around one process
nodes:
  - "Process|your app|app"
  - "Namespaces|restrict what it sees|cp"
  - "Cgroups|restrict what it uses|cp"
  - "Container|runtime packages these|ok"
  - "Pod|containers sharing network|env"
@h Same process, two views
```bash title="Container process seen from the host" nocheck
docker run -d --name demo --memory 64m nginx:stable
docker top demo                       # processes as the host sees them
docker exec demo ps aux | head -3     # same processes, PID 1 inside
docker inspect -f '{{.HostConfig.Memory}}' demo
docker rm -f demo
```
@end

@concept Putting it together with the USE method
@plain
For each resource ask three questions: how **U**tilized is it, is it **S**aturated (work waiting), and does it show **E**rrors. This gives a repeatable way to find a bottleneck.
@problem
Random guessing and restarting services hides the cause and wastes the incident window.
@does
- CPU: utilization from `top`, saturation from run queue and throttling, errors rare.
- Memory: utilization from `free`, saturation from swapping, errors from OOM kills.
- Disk: utilization and queue from `iostat`, errors from `dmesg`.
- Network: throughput from `sar` or `ip -s link`, saturation from drops and retransmits.
@diagram cmp
caption: One question per resource
cards:
  - {h: "CPU", kind: app, items: ["top, mpstat", "Run queue above core count"]}
  - {h: "Memory", kind: info, items: ["free, vmstat", "Swap activity, OOM kills"]}
  - {h: "Disk", kind: warn, items: ["iostat -x", "High await and queue"]}
  - {h: "Network", kind: env, items: ["ip -s link, ss -s", "Drops, retransmits"]}
@h A first-minute checklist
```bash title="Sixty seconds on an unfamiliar host" lab
uptime                    # load trend
vmstat 1 3                # run queue, swap, io wait
free -h
iostat -x 1 2
ip -s link | head -12
dmesg | tail -5
```
@check
Which single number tells you the CPU is saturated rather than just busy? || A run queue (vmstat r column) consistently above the number of cores.
@end
