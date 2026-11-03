---
title: eBPF and observability tooling
minutes: 50
objectives:
  - Explain what eBPF is and why it is safe to run in production
  - Use perf and bpftrace for one-liner investigations
  - Capture and read a flame graph
  - Pick the right tool for CPU, disk, network and latency questions
---
When metrics and logs cannot explain a slowdown, you need to look inside the kernel and the running process. Commands here need root and a reasonably recent kernel (5.x or newer is comfortable). Tool packages differ by distribution; check your distribution's names for `perf`, `bpftrace` and `bcc-tools`.

@concept What eBPF is
@plain
eBPF lets you load small, verified programs into the Linux kernel that run when events happen: a system call, a function entry, a network packet, a timer tick.
@problem
Before eBPF, deep tracing meant kernel modules (risky) or heavy tools that slowed the system. You could not ask "which files does each process open" on a live production host cheaply.
@does
- A **verifier** proves the program terminates and cannot crash the kernel or read arbitrary memory, before it is allowed to run.
- Programs attach to hooks: kprobes (kernel functions), uprobes (user functions), tracepoints, network hooks (XDP, tc) and perf events.
- Data flows back through **maps** and ring buffers to user space.
- Cilium, Falco, Pixie, Parca and many profilers are built on it.
@diagram flow
caption: From idea to data
numbered: true
nodes:
  - "Write program|bpftrace or C|app"
  - "Verifier|proves it is safe|cp"
  - "Attach to hook|kprobe, tracepoint|info"
  - "Event fires|program runs in kernel|env"
  - "Maps|aggregate results to user space|ok"
@h Is it available
```bash title="Check support" lab
uname -r
ls /sys/kernel/btf/vmlinux && echo "BTF present, CO-RE tools work"
sudo bpftool prog list 2>/dev/null | head -5       # programs already loaded (Cilium, systemd)
which bpftrace perf
```
@check
What stops an eBPF program from crashing the kernel? || The verifier rejects unsafe or non-terminating programs before loading.
@end

@concept perf: the first tool to reach for
@plain
`perf` samples what the CPU is doing many times per second and reports which functions use the most time.
@problem
"The server is slow and CPU is high" does not tell you which code to fix.
@does
- `perf top` is a live view like `top` for functions.
- `perf record -F 99 -g -p PID -- sleep 30` samples 99 times per second with call stacks for 30 seconds; `perf report` explores it.
- `perf stat` reports counters: instructions, cache misses, context switches.
- Without symbols you see hex addresses; install debug symbols or build with frame pointers where possible.
@diagram flow
caption: Sampling profile workflow
nodes:
  - "perf record|sample stacks at 99 Hz|app"
  - "perf.data|raw samples|plain"
  - "perf report|sort by cost|info"
  - "Hot function|fix or tune it|ok"
@h Profile something
```bash title="Burn CPU, then find it" lab
yes > /dev/null & pid=$!
sudo perf stat -p $pid -- sleep 2 2>&1 | head -12
sudo perf record -F 99 -g -p $pid -- sleep 5 2>&1 | tail -2
sudo perf report --stdio 2>/dev/null | head -20
kill $pid
```
:::note
Why 99 and not 100 Hz? An odd rate avoids sampling in lockstep with timers that run at 100 Hz.
:::
@end

@concept Flame graphs
@plain
A **flame graph** turns thousands of stack samples into one picture. Width shows how often a function was on the CPU, and stacking shows who called whom.
@problem
A text report of 5000 stack traces is unreadable. The picture shows the one wide tower that matters.
@does
- Read it bottom up: the bottom is the entry point, each box above is a callee.
- Look for wide plateaus at the top: those functions burn time themselves.
- Colour is mostly decorative. The x axis is not time; it is sorted alphabetically to merge identical stacks.
- Tools: Brendan Gregg's FlameGraph scripts, `perf script`, Parca, Pyroscope, `py-spy` for Python, and async-profiler for Java.
@diagram cmp
caption: How to read one
cards:
  - {h: "Width", kind: ok, items: ["Share of samples", "Wide equals expensive"]}
  - {h: "Height", kind: info, items: ["Call depth", "Tall is not necessarily slow"]}
  - {h: "Plateau on top", kind: warn, items: ["Function using CPU itself", "First place to optimise"]}
@h Make one
```bash title="perf to flame graph" nocheck
git clone https://github.com/brendangregg/FlameGraph /tmp/FlameGraph
sudo perf record -F 99 -a -g -- sleep 30
sudo perf script | /tmp/FlameGraph/stackcollapse-perf.pl | /tmp/FlameGraph/flamegraph.pl > flame.svg
# open flame.svg in a browser; click boxes to zoom
```
@check
Does the x axis of a flame graph show time? || No, it shows sample counts, with stacks sorted alphabetically.
@end

@concept bpftrace one-liners
@plain
`bpftrace` is a short scripting language for eBPF. A single line can answer a question that used to need a custom tool.
@problem
You want facts such as "which processes call `openat` the most" without stopping the application.
@does
- Syntax is `probe /filter/ { action }`. Built-ins include `pid`, `comm`, `arg0`, `retval` and `@maps` for aggregates.
- Probe types: `tracepoint:syscalls:sys_enter_openat`, `kprobe:vfs_read`, `uprobe:/bin/bash:readline`, `interval:s:5`.
- Maps print automatically on exit with Ctrl-C.
@diagram seq
caption: A bpftrace session
actors: ["You|terminal|app", "bpftrace|compiles and loads|cp", "Kernel|runs the probe|env"]
steps:
  - "0>1: one-liner | req"
  - "1>2: load verified program | req"
  - "2>1: events counted in a map | resp"
  - "1>0: summary on Ctrl-C | resp"
@h Useful one-liners
```bash title="Common questions" lab
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_openat { @[comm] = count(); }'          # who opens files
sudo bpftrace -e 'tracepoint:syscalls:sys_enter_execve { printf("%s -> %s\n", comm, str(args->filename)); }'
sudo bpftrace -e 'tracepoint:block:block_rq_issue { @bytes = hist(args->bytes); }'      # disk request size
sudo bpftrace -e 'interval:s:5 { exit(); } profile:hz:99 { @[comm] = count(); }'        # who is on CPU
```
@check
How do you stop a bpftrace aggregate and see it? || Press Ctrl-C and the map is printed.
@end

@concept Latency histograms with BCC tools
@plain
The `bcc-tools` (or `libbpf-tools`) package ships ready made tracers. Each is a tested program for one question, with names like `biolatency` and `tcpconnect`.
@problem
Averages hide the slow tail. A disk with 1 ms average and a few 500 ms requests makes databases stall.
@does
- `biolatency` prints a histogram of block I/O latency; `biosnoop` lists each request.
- `execsnoop` shows every new process; `opensnoop` file opens; `tcpconnect` and `tcplife` outgoing TCP flows; `runqlat` scheduler delay.
- On Debian and Ubuntu the tools are suffixed `-bpfcc`; paths vary by distribution.
@diagram cmp
caption: Which tool for which question
cards:
  - {h: "Disk", kind: warn, items: ["biolatency, biosnoop", "ext4slower"]}
  - {h: "Network", kind: info, items: ["tcpconnect, tcpretrans", "tcplife"]}
  - {h: "CPU", kind: app, items: ["runqlat, profile", "cpudist"]}
  - {h: "Processes", kind: ok, items: ["execsnoop, opensnoop", "killsnoop"]}
@h Run
```bash title="Disk latency distribution" lab
sudo biolatency-bpfcc 5 1 2>/dev/null || sudo /usr/share/bcc/tools/biolatency 5 1
sudo tcpretrans-bpfcc 2>/dev/null | head -5
sudo runqlat-bpfcc 5 1 2>/dev/null
```
:::tip
A bimodal histogram (two humps) means two populations, such as cache hits and misses. Investigate both.
:::
@end

@concept Observability in Kubernetes with eBPF
@plain
On a Kubernetes node eBPF tools see every pod because they share the kernel. Projects wrap them so you get per pod answers without changing images.
@problem
Sidecars and agents inside each application add cost and need code changes, while a node-level view needs none.
@does
- **Cilium and Hubble**: network flows and policy verdicts per pod.
- **Falco and Tetragon**: runtime security events such as a shell opened in a container.
- **Parca, Pyroscope**: continuous profiling across the fleet.
- `kubectl debug node/NAME -it --image=...` gives a privileged shell on a node for ad hoc `bpftrace`; follow your platform's security policy.
@diagram layers
caption: A shared kernel, many views
layers:
  - {label: "Pods", nodes: ["web|app", "api|app", "db|app"]}
  - {label: "Node kernel", nodes: ["eBPF programs|attached once, see all pods|cp"]}
  - {label: "Outputs", nodes: ["Hubble|network flows|ok", "Falco|security events|ok", "Parca|CPU profiles|ok"]}
@h Node debugging
```bash title="Debug a node" nocheck
kubectl debug node/worker-1 -it --image=ubuntu:24.04 -- bash
# inside the debug pod the host filesystem is under /host
chroot /host
bpftool prog list | head
hubble observe --pod default/web --last 20       # if Hubble is installed
```
@check
Why can one eBPF agent per node observe all pods? || Pods share the node's kernel, where the programs attach.
@end

@concept Choosing the right tool and staying safe
@plain
Start with cheap tools and escalate only if needed. Tracing has overhead, and a careless probe on a hot function can slow production.
@problem
Jumping straight to deep tracing takes time and risk, when `vmstat` would have shown the answer.
@does
- Order: metrics and `top`, then `pidstat`/`iostat`, then `perf`/profile, then tracing specific events.
- Prefer sampling (`profile`, `perf record`) to tracing every event of high frequency calls such as `vfs_read`.
- Limit the run time (`-- sleep 30`, `interval:s:10 { exit(); }`) and filter by pid.
- Record what you ran in the incident notes.
@diagram flow
caption: Escalation ladder
numbered: true
nodes:
  - "Metrics|dashboards, top, vmstat|ok"
  - "Per process|pidstat, iostat|info"
  - "Sampling|perf, profile, flame graph|app"
  - "Event tracing|bpftrace, bcc|warn"
@h Safe habit
```bash title="Time boxed tracing" lab
pid=$(pgrep -n sshd || echo 1)
sudo timeout 10 bpftrace -e "tracepoint:syscalls:sys_enter_read /pid == $pid/ { @n = count(); }" 2>&1 | tail -3
pidstat -p $pid 1 3
```
@check
Which is safer on a busy host, sampling or tracing every event? || Sampling, because overhead is bounded by the rate.
@end
