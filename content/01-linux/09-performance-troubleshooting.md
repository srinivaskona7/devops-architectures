---
title: Performance and troubleshooting
minutes: 50
objectives:
  - Apply the USE method to CPU, memory, disk and network
  - Read top, vmstat, iostat and free correctly
  - Use strace, lsof and journalctl to trace a misbehaving process
---
"The server is slow" is not a diagnosis. A repeatable method finds the constrained resource in minutes, and a few tools tell you which process is responsible.

@concept The USE method
@plain
For every resource, check **U**tilisation (how busy), **S**aturation (how much work is waiting) and **E**rrors. The resource with high saturation or errors is your bottleneck.
@problem
Random tool-running creates noise. Engineers stare at CPU graphs while the real limit is a disk queue or a memory cap.
@does
- CPU: utilisation = busy percent; saturation = run queue length; errors = rare.
- Memory: utilisation = used; saturation = swapping or OOM kills; errors = ECC or allocation failures.
- Disk: utilisation = busy percent; saturation = queue depth and wait; errors = I/O errors in `dmesg`.
- Network: utilisation = bandwidth; saturation = drops and retransmits; errors = interface error counters.
@diagram layers
caption: USE across resources
layers:
  - {label: "CPU", nodes: ["Utilisation|%us + %sy|info", "Saturation|run queue, load|warn", "Errors|machine checks|bad"]}
  - {label: "Memory", nodes: ["Utilisation|used vs total|info", "Saturation|swap in/out, OOM|warn", "Errors|failed allocations|bad"]}
  - {label: "Disk", nodes: ["Utilisation|%util|info", "Saturation|await, queue|warn", "Errors|dmesg I/O errors|bad"]}
  - {label: "Network", nodes: ["Utilisation|throughput|info", "Saturation|drops, retransmits|warn", "Errors|ip -s link|bad"]}
@h A 60-second first look
```bash title="First minute on a slow Linux host" lab
uptime                      # load averages: 1, 5 and 15 minutes
dmesg -T 2>/dev/null | tail -5      # kernel errors, OOM kills, disk errors
vmstat 1 3                  # run queue (r), swap (si/so), cpu split
free -m                     # memory and swap
df -h | head -5             # space
ss -s                       # socket summary
```
@check
What does a high load average with low CPU use usually mean? || Tasks are waiting, often on disk or network storage (uninterruptible sleep), not on the CPU.
@end

@concept CPU and load
@plain
Load average is the number of tasks running or waiting, averaged over 1, 5 and 15 minutes. It must be compared with the number of CPU cores.
@problem
A load of 8 is fine on 16 cores and a crisis on 2. Without context, the number misleads.
@does
- `nproc` gives core count. Load persistently above the core count means saturation.
- `top` or `htop` show per-process CPU. Press `1` to see each core, `P` to sort by CPU.
- CPU split: `us` user code, `sy` kernel, `wa` waiting on I/O, `st` stolen by the hypervisor (noisy neighbour), `id` idle.
- `pidstat 1`, `mpstat -P ALL 1` give per-process and per-core views.
@diagram cmp
caption: Reading the CPU line
cards:
  - {h: "High us", kind: app, items: ["Application code is busy", "Profile the app", "Scale out or optimise"]}
  - {h: "High sy", kind: warn, items: ["Kernel work: syscalls, networking", "Check interrupts and context switches", "strace -c helps"]}
  - {h: "High wa", kind: bad, items: ["Waiting for storage", "Look at iostat", "Not a CPU problem"]}
  - {h: "High st", kind: env, items: ["Hypervisor takes time", "Cloud noisy neighbour or throttling", "Check burst credits"]}
@h Commands
```bash title="CPU views" lab
nproc
top -b -n1 | head -12
ps -eo pid,%cpu,%mem,comm --sort=-%cpu | head -6
vmstat 1 3
```
:::note
On burstable cloud instances (for example T-series), sustained load can exhaust CPU credits and throttle the instance even though the guest shows idle time.
:::
@end

@concept Memory, swap and the OOM killer
@plain
Linux uses spare memory as a file cache, so "free" looks small on a healthy system. The number that matters is **available** memory. When it runs out, the kernel kills a process.
@problem
Misreading `free` causes false alarms, while ignoring real pressure ends with a database killed at peak time.
@does
- `free -m`: look at the `available` column, not `free`.
- Swap in use is normal in small amounts; constant swap-in and swap-out (`si`/`so` in `vmstat`) means thrashing.
- The **OOM killer** picks a process when memory is exhausted. Evidence is in `dmesg` and `journalctl -k`.
- In containers, the **cgroup memory limit** triggers OOM for that container even when the host has memory.
- `/proc/<pid>/status` shows `VmRSS` (resident memory).
@diagram flow
caption: What happens as memory runs out
numbered: true
nodes:
  - "Cache shrinks|free memory reclaimed|ok"
  - "Swap used|slow but alive|warn"
  - "Reclaim stalls|everything slows|bad"
  - "OOM killer|kills the largest scorer|bad"
@h Commands
```bash title="Memory checks" lab
free -m
grep -E 'MemAvailable|SwapFree' /proc/meminfo
ps -eo pid,rss,comm --sort=-rss | head -5
sudo journalctl -k --since "1 day ago" 2>/dev/null | grep -i 'out of memory' | tail -3
```
@check
In a Kubernetes pod the app is OOMKilled but the node has free memory. Why? || The container exceeded its own memory limit; the cgroup enforces it regardless of node memory.
@end

@concept Disk I/O
@plain
Slow storage often looks like a slow application. `iostat` shows how busy a device is and how long requests wait.
@problem
Applications blocked on disk show low CPU and high load, and nothing in the app logs says why.
@does
- `iostat -xz 1`: `%util` near 100 on a single device, `await` (average latency in ms), `aqu-sz` (queue length) and read/write rates.
- SSDs and cloud volumes can serve many requests in parallel, so `%util` alone can mislead; high `await` is the stronger signal.
- Cloud volumes have IOPS and throughput limits (for example EBS). Hitting them shows as latency with a flat throughput line.
- `iotop` shows which process generates the I/O.
@diagram flow
caption: From application to latency
nodes:
  - "App write|fsync waits for the disk|app"
  - "Queue|requests wait their turn|warn"
  - "Device|limited IOPS or throughput|env"
  - "await rises|the app feels slow|bad"
@h Commands
```bash title="Disk I/O views" lab
iostat -xz 1 3 2>/dev/null || echo "install sysstat for iostat"
sudo iotop -oPa -n 3 -b 2>/dev/null | head -10
cat /proc/pressure/io 2>/dev/null
```
@end

@concept Tracing with strace, lsof and the journal
@plain
When metrics show *where* the pressure is, tracing shows *what the process is doing*. `strace` lists every system call, `lsof` lists open files and sockets, and the journal holds what the program said.
@problem
A process hangs, loops, or fails with "permission denied" and no further detail. You need to see which file, socket or call is involved.
@does
- `strace -p PID -f -tt` attaches to a running process; `-e trace=network` or `-e trace=file` narrows output; `strace -c` summarises time per call.
- `lsof -p PID` lists open files, `lsof -i` lists network connections, `lsof +D /path` finds who uses a directory (why a mount cannot unmount).
- `journalctl -u name --since ... -p err` for service logs.
- `perf top` and flame graphs are the next step for CPU profiling.
:::warn
`strace` slows the target process. Use it briefly on production, with narrow filters.
:::
@diagram seq
caption: Following a hung process
actors: ["You|operator|app", "Process|PID 4821|env", "Kernel|syscalls|cp"]
steps:
  - "0>1: strace -p 4821 -f | req"
  - "1>2: connect() to 10.0.0.9:5432 | req"
  - "note 1..2: connect never returns: database unreachable"
  - "0>0: check security group and route | resp"
@h Commands
```bash title="Tracing recipes" nocheck
sudo strace -f -tt -e trace=network -p 4821 2>&1 | head -20
sudo strace -c -p 4821 -f -o /tmp/summary.txt &   # then Ctrl-C after 10 s
sudo lsof -p 4821 | head -20
sudo lsof +D /mnt/data                  # who is keeping the mount busy
sudo journalctl -u shop --since "30 min ago" -p warning
```
@check
A process shows 0% CPU but never answers. Which tool shows what it is waiting for? || strace -p PID (blocked system call) or cat /proc/PID/wchan; lsof shows the files and sockets involved.
@end

@concept A troubleshooting playbook
@plain
Combine the method and tools into a fixed order: define the symptom, check recent changes, find the constrained resource, find the responsible process, fix, and write it down.
@problem
Under pressure people jump to favourite theories. A checklist keeps the investigation systematic and the incident record useful.
@does
- Ask first: what changed (deploy, config, traffic, certificate expiry, quota)?
- Compare with a healthy peer or the previous hour before inventing a theory.
- Change one thing at a time and record the result.
- Capture evidence (command output, graphs) before restarting, because restarts destroy it.
@diagram flow
caption: The investigation loop
numbered: true
nodes:
  - "Symptom|what, since when, who is affected|plain"
  - "What changed|deploys, configs, traffic|info"
  - "USE check|find the saturated resource|app"
  - "Trace the process|strace, lsof, logs|env"
  - "Fix and record|runbook entry|ok"
@choose First tool to reach for
uptime and vmstat | you need a broad first look | you already know it is the network
iostat | load is high and CPU is low | the problem is clearly inside the app
ss and tcpdump | connections fail or time out | the host is out of memory
strace | one process behaves oddly | the entire host is slow
@end
