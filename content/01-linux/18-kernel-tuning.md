---
title: Kernel tuning
minutes: 45
objectives:
  - Read and set kernel parameters with sysctl and make them persistent
  - Explain hugepages, NUMA and swappiness and when they matter
  - Choose an I/O scheduler and tune file descriptor and network limits
  - Measure before and after every change
---
Defaults suit general use. Tune only after measuring a problem, change one thing at a time, and record the old value. Parameter names and defaults vary by kernel version, so check the kernel documentation for your release. Labs that change values use runtime settings that revert on reboot.

@concept sysctl and persistent settings
@plain
`sysctl` reads and writes kernel parameters, which appear as files under `/proc/sys`. Changes made at runtime are lost on reboot unless saved in a config file.
@problem
Tuning done by hand on one server is forgotten and not repeated on the next, causing "works on node 1 only" bugs.
@does
- `sysctl net.core.somaxconn` reads; `sysctl -w name=value` sets for now.
- Persist in `/etc/sysctl.d/NN-name.conf`, then apply with `sysctl --system`.
- In Kubernetes, safe namespaced sysctls can be set per pod; others need node configuration or privileged setup.
@diagram flow
caption: Safe tuning loop
numbered: true
nodes:
  - "Measure|baseline numbers|info"
  - "Change one value|sysctl -w|app"
  - "Measure again|compare|info"
  - "Persist|file in sysctl.d, in code|ok"
@h Read and set
```bash title="Inspect and change a parameter" lab
sysctl net.core.somaxconn vm.swappiness fs.file-max
cat /proc/sys/vm/swappiness
sudo sysctl -w vm.swappiness=10                     # runtime only
printf 'vm.swappiness = 10\n' | sudo tee /etc/sysctl.d/60-lab.conf
sudo sysctl --system | tail -3
sudo rm /etc/sysctl.d/60-lab.conf
```
@check
How does a sysctl survive reboot? || It is placed in a file under /etc/sysctl.d and loaded at boot.
@end

@concept Memory tuning: swappiness, dirty pages and overcommit
@plain
`vm.swappiness` sets how eagerly the kernel swaps process memory out in favour of page cache. Dirty-page settings control when written data is flushed to disk. Overcommit controls whether the kernel allows promising more memory than exists.
@problem
Databases that are swapped out stall. Large bursts of dirty pages flush at once and freeze I/O. Applications that allocate lazily are killed by the OOM killer.
@does
- Lower `vm.swappiness` (for example 1 to 10) on database or Kubernetes hosts; Kubernetes historically required swap off, so check the current kubelet documentation for swap support.
- `vm.dirty_background_ratio` and `vm.dirty_ratio` set percentages of memory; the `_bytes` variants are better on large-memory hosts.
- `vm.overcommit_memory`: 0 heuristic (default), 1 always allow, 2 strict accounting.
- `vm.max_map_count` must be raised for Elasticsearch and OpenSearch (262144 is the value in their docs).
@diagram cmp
caption: Common memory settings
cards:
  - {h: "swappiness", kind: info, items: ["0 to 100 scale", "Lower keeps apps in RAM"]}
  - {h: "dirty ratios", kind: warn, items: ["When writeback starts and blocks", "Smaller bursts, smoother I/O"]}
  - {h: "overcommit", kind: bad, items: ["2 refuses over-allocation", "Can break forking programs"]}
@h Look at the signals
```bash title="Is the host swapping or stalling on writeback" lab
vmstat 1 5                       # si and so columns are swap in and out
grep -E 'Dirty|Writeback' /proc/meminfo
sysctl vm.dirty_background_ratio vm.dirty_ratio vm.overcommit_memory vm.max_map_count
grep -E 'oom|Out of memory' <(dmesg 2>/dev/null) | tail -3
```
:::warn
Setting swappiness to 0 does not disable swap. It only makes the kernel avoid it until memory is almost gone.
:::
@end

@concept Hugepages and transparent hugepages
@plain
Memory is mapped in pages of 4 KiB. A **hugepage** is 2 MiB (or 1 GiB), so fewer mappings and fewer TLB misses are needed for large memory users.
@problem
A database with 64 GiB of buffers needs about 16.8 million page mappings at 4 KiB, which costs CPU and page table memory.
@does
- Arithmetic: 64 GiB divided by 2 MiB is 32768 hugepages; the same memory in 4 KiB pages is 16777216 mappings, 512 times more.
- **Explicit hugepages** are reserved (`vm.nr_hugepages`) and used by software configured for it, for example PostgreSQL `huge_pages = try`.
- **Transparent HugePages (THP)** are automatic. Some databases (MongoDB, Redis, some Oracle setups) recommend disabling them because of latency spikes during compaction. Follow your database vendor's guidance.
@diagram flow
caption: Fewer, larger pages
nodes:
  - "64 GiB buffers|database memory|app"
  - "4 KiB pages|16777216 mappings|warn"
  - "2 MiB hugepages|32768 mappings|ok"
@h Check and reserve
```bash title="Hugepage status" lab
grep -i huge /proc/meminfo
cat /sys/kernel/mm/transparent_hugepage/enabled
sudo sysctl -w vm.nr_hugepages=128               # reserves 128 x 2 MiB = 256 MiB
grep -E 'HugePages_(Total|Free)' /proc/meminfo
sudo sysctl -w vm.nr_hugepages=0
```
```python title="Page count math" lab
gib = 64
print(gib * 1024**3 // (4096), "small pages")
print(gib * 1024**3 // (2 * 1024**2), "hugepages")
print(128 * 2, "MiB reserved by 128 hugepages")
```
@check
Why is THP sometimes disabled for databases? || Background compaction can cause latency spikes; vendors often recommend turning it off.
@end

@concept NUMA
@plain
On multi-socket servers each CPU has memory attached to it. Access to **local** memory is faster than access to memory attached to another socket (**NUMA**: non-uniform memory access).
@problem
A process that runs on socket 0 but has its memory on socket 1 pays extra latency on every access, and one node can run out of memory while the other has plenty.
@does
- `numactl --hardware` shows nodes, CPUs and free memory per node. `numastat` shows hits and misses.
- `numactl --cpunodebind=0 --membind=0 cmd` pins both.
- Kubernetes Topology Manager with the static CPU manager aligns CPUs and devices for latency sensitive pods; check current docs for policies.
- Most cloud instances below a certain size are a single NUMA node; this matters on large instances.
@diagram layers
caption: Two sockets, two memory banks
layers:
  - {label: "Socket 0", nodes: ["CPUs 0 to 15|local|app", "Memory bank 0|fast for socket 0|ok"]}
  - {label: "Socket 1", nodes: ["CPUs 16 to 31|local|app", "Memory bank 1|fast for socket 1|ok"]}
  - {label: "Interconnect", nodes: ["Cross socket link|remote access is slower|warn"]}
@h Look at your topology
```bash title="NUMA inspection" lab
lscpu | grep -i numa
numactl --hardware 2>/dev/null || echo "install numactl"
numastat 2>/dev/null | head -8
numactl --cpunodebind=0 --membind=0 sleep 1 2>/dev/null && echo pinned
```
@check
What does a high numa_miss count suggest? || Processes are using memory from a remote node, adding latency.
@end

@concept I/O schedulers and block device settings
@plain
The I/O scheduler orders requests to a disk. Modern blk-mq kernels offer `none`, `mq-deadline`, `bfq` and `kyber`.
@problem
A scheduler designed for spinning disks, which sort requests to reduce head movement, only adds overhead on NVMe.
@does
- NVMe: `none` is usually best. SATA SSD: `mq-deadline` or `none`. Spinning disks and desktop fairness: `mq-deadline` or `bfq`.
- Read the current choice in `/sys/block/DEV/queue/scheduler`; the one in brackets is active.
- `read_ahead_kb` and `nr_requests` also influence throughput. Persist with a udev rule.
- Always benchmark with `fio` using your real block size and queue depth.
@diagram cmp
caption: Typical scheduler choices
cards:
  - {h: "none", kind: ok, items: ["NVMe and fast SSD", "Device does the queueing"]}
  - {h: "mq-deadline", kind: info, items: ["Good default for many", "Bounds request latency"]}
  - {h: "bfq", kind: app, items: ["Fair across processes", "More CPU overhead"]}
@h Inspect and test
```bash title="Scheduler and a fio test" lab
for d in /sys/block/*/queue/scheduler; do echo "$d: $(cat $d)"; done
lsblk -d -o NAME,ROTA,SIZE,MODEL        # ROTA 1 means rotational
fio --name=randread --filename=/tmp/fio.test --size=256M --rw=randread --bs=4k --iodepth=16 --runtime=10 --time_based --direct=1 2>/dev/null | grep -E 'IOPS|lat '
rm -f /tmp/fio.test
```
```text title="/etc/udev/rules.d/60-scheduler.rules" nocheck
ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/scheduler}="none"
```
@end

@concept File descriptors and process limits
@plain
Every open file, socket and pipe uses a **file descriptor**. Limits exist per process and per system. Hitting them gives "too many open files".
@problem
A busy proxy or database with thousands of connections hits the default per-process limit of 1024 and refuses new clients.
@does
- Per process: `ulimit -n`, `LimitNOFILE=` in a systemd unit, or `securityContext`/runtime defaults in containers.
- System wide: `fs.file-max` and `fs.nr_open` (the per-process ceiling).
- For inotify watchers (kubectl, IDEs, log tailers) raise `fs.inotify.max_user_watches` and `max_user_instances`.
- See actual use with `ls /proc/PID/fd | wc -l`.
@diagram flow
caption: Limits stack up
nodes:
  - "Process soft limit|ulimit -n or LimitNOFILE|app"
  - "Process hard limit|ceiling for the soft limit|info"
  - "fs.nr_open|per process maximum|cp"
  - "fs.file-max|whole system|cp"
@h Check use
```bash title="Descriptor usage" lab
ulimit -Sn; ulimit -Hn
cat /proc/sys/fs/file-nr                      # allocated, unused, max
for p in $(pgrep -n sshd) $$; do echo "$p $(ls /proc/$p/fd 2>/dev/null | wc -l) fds, limit: $(grep 'open files' /proc/$p/limits | awk '{print $4}')"; done
sysctl fs.inotify.max_user_watches
```
@check
Where do you raise the limit for a systemd service? || `LimitNOFILE=` in the unit or a drop-in.
@end

@concept Network stack tuning
@plain
A few parameters matter for busy servers: listen queue length, ephemeral port range, buffer sizes and congestion control.
@problem
Under high connection rates, SYN queues overflow, outgoing connections run out of ports, and long fat links under-utilise bandwidth.
@does
- `net.core.somaxconn` caps the accept queue (the application's backlog also matters). `net.ipv4.tcp_max_syn_backlog` handles half-open connections.
- `net.ipv4.ip_local_port_range` sets source ports; 32768 to 60999 gives 28232 ports per destination tuple.
- `net.ipv4.tcp_congestion_control=bbr` is available on many kernels (check `net.ipv4.tcp_available_congestion_control`).
- Buffers: `net.core.rmem_max`, `wmem_max`. Bandwidth delay product: 1 Gbit/s with 50 ms round trip is 6.25 MB in flight.
@diagram cmp
caption: Symptom to parameter
cards:
  - {h: "Listen drops", kind: bad, items: ["netstat -s shows overflowed", "somaxconn and app backlog"]}
  - {h: "Cannot assign address", kind: warn, items: ["Ephemeral ports exhausted", "Widen range, reuse connections"]}
  - {h: "Slow long distance transfer", kind: info, items: ["Buffers too small", "Check BDP and congestion control"]}
@h Calculate and check
```python title="Bandwidth delay product and port range" lab
bw_bits = 1_000_000_000
rtt = 0.050
print("BDP bytes:", bw_bits * rtt / 8)          # 6250000.0
print("ephemeral ports:", 60999 - 32768 + 1)    # 28232
```
```bash title="Counters" lab
nstat -az TcpExtListenOverflows TcpExtListenDrops 2>/dev/null
sysctl net.core.somaxconn net.ipv4.ip_local_port_range net.ipv4.tcp_congestion_control
ss -s
```
:::note
Check the current kernel documentation before copying tuning blocks from the internet. Many old recommendations are now defaults or harmful.
:::
@check
How much data can be in flight on a 1 Gbit/s, 50 ms path? || 1e9 x 0.05 / 8 = 6,250,000 bytes.
@end
