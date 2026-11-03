---
title: systemd deep dive
minutes: 50
objectives:
  - Explain targets, dependency ordering and how a boot reaches a target
  - Read and filter the journal and make it persistent
  - Limit CPU and memory of a service with cgroup controls
  - Use drop-ins, socket activation and analysis tools to debug units
---
The processes page showed a basic service and timer. This page covers the machinery underneath, which matters when a service starts in the wrong order, a node runs out of memory, or logs vanish at reboot.

@concept Targets and the boot graph
@plain
A **target** is a named goal state made of other units, such as `multi-user.target` (a normal server) or `rescue.target` (single-user repair). systemd boots by reaching the default target and starting everything it pulls in.
@problem
Old init systems used numbered runlevels and scripts run in a fixed order. That was slow and hid real dependencies.
@does
- `systemctl get-default` shows the default target; `systemctl set-default` changes it.
- `systemctl isolate rescue.target` switches state now (it stops units not part of the target).
- Units are started in parallel as far as their declared dependencies allow.
@diagram flow
caption: Targets reached during a typical boot
numbered: true
nodes:
  - "sysinit.target|mounts, swap, udev|info"
  - "basic.target|sockets, timers, paths|app"
  - "network-online.target|network is configured|env"
  - "multi-user.target|services running|ok"
@h Explore
```bash title="Targets and the default" lab
systemctl get-default
systemctl list-units --type=target --no-pager | head -12
systemctl list-dependencies multi-user.target --no-pager | head -15
systemd-analyze                     # total boot time split into firmware, kernel, userspace
```
@check
What does isolate do that start does not? || It stops every unit not required by the target, switching to exactly that state.
@end

@concept Dependencies and ordering
@plain
Two separate ideas: **requirement** (must this other unit exist and run?) and **ordering** (who starts first?). They are declared separately.
@problem
Writing only `After=` does not start the other unit, and writing only `Requires=` does not wait for it. Services then fail intermittently at boot.
@does
- `Wants=` is a soft requirement: pull it in, but carry on if it fails. `Requires=` is hard: if it fails, I fail. `BindsTo=` also stops me when it stops.
- `After=` and `Before=` set order only.
- `network.target` means the network stack is up; `network-online.target` means an address is configured. Services that connect at start need the latter plus `Wants=network-online.target`.
@diagram cmp
caption: Requirement versus ordering
cards:
  - {h: "Wants / Requires", kind: app, items: ["Which units get started", "Wants tolerates failure", "Requires does not"]}
  - {h: "After / Before", kind: info, items: ["Order of start only", "Does not start the other unit", "Reversed at shutdown"]}
@h See why a unit started
```bash title="Inspect dependencies" lab
systemctl list-dependencies sshd.service --no-pager | head -10     # use ssh.service on Debian
systemctl list-dependencies --reverse network-online.target --no-pager | head
systemd-analyze critical-chain multi-user.target --no-pager | head -15   # what delayed the boot
systemctl show sshd.service -p Wants -p After -p Requires 2>/dev/null
```
:::warn
Ordering cycles are broken by systemd by dropping a job, usually with a log line. Search the journal for "ordering cycle" when something silently does not start.
:::
@check
A service needs a database on another host at start. Which targets should it use? || `After=network-online.target` and `Wants=network-online.target`, plus retry logic in the app.
@end

@concept Drop-ins and overriding units
@plain
Never edit a unit file shipped by a package. A **drop-in** file in `unit.service.d/` overrides only the settings you name, and survives package upgrades.
@problem
Edited vendor files are overwritten on upgrade or flagged as conflicts, and nobody remembers what was changed.
@does
- `systemctl edit nginx` creates `/etc/systemd/system/nginx.service.d/override.conf` and reloads for you.
- To reset a list option such as `ExecStart=` first assign it empty, then give the new value.
- `systemctl cat` shows the unit and all drop-ins merged; `systemd-delta` lists overridden files.
@diagram layers
caption: Where systemd looks, highest priority first
layers:
  - {label: "Runtime", nodes: ["/run/systemd/system|temporary overrides|warn"]}
  - {label: "Administrator", nodes: ["/etc/systemd/system|your units and .d drop-ins|ok"]}
  - {label: "Package", nodes: ["/usr/lib/systemd/system|vendor defaults|info"]}
@h A drop-in
```ini title="/etc/systemd/system/nginx.service.d/override.conf"
[Service]
Restart=on-failure
RestartSec=2
LimitNOFILE=65536
# to replace a command, clear it first
ExecStart=
ExecStart=/usr/sbin/nginx -g 'daemon off;'
```
```bash title="Apply and verify" lab
sudo systemctl daemon-reload
systemctl cat nginx.service | tail -12
systemctl show nginx -p LimitNOFILE
```
@end

@concept journald and persistent logs
@plain
**journald** collects output of all services plus kernel messages in a structured, indexed binary journal. `journalctl` queries it.
@problem
On many distributions the journal lives in `/run` and disappears at reboot, which is exactly when you need the previous boot's logs.
@does
- Create `/var/log/journal` (or set `Storage=persistent` in `/etc/systemd/journald.conf`) to keep logs across boots.
- Filter by unit, priority, time, boot and fields: `-u`, `-p err`, `--since`, `-b -1`, `_PID=`.
- `journalctl --disk-usage` and `--vacuum-size=500M` or `--vacuum-time=14d` limit growth; `SystemMaxUse=` sets a cap.
- Output formats such as `-o json` feed other tools.
@diagram flow
caption: From service output to a query
nodes:
  - "Service stdout, stderr|or syslog calls|app"
  - "journald|adds metadata, indexes|cp"
  - "/var/log/journal|persistent storage|env"
  - "journalctl|filter and follow|ok"
@h Query recipes
```bash title="Useful journal queries" lab
journalctl --list-boots | tail -3                        # which boots are stored
journalctl -b -1 -p err --no-pager | tail -20            # errors from the previous boot
journalctl -u sshd --since "1 hour ago" --no-pager | tail
journalctl -k --no-pager | tail -5                       # kernel messages only
journalctl -u nginx -o json --no-pager | head -1 | python3 -m json.tool | head -12
journalctl --disk-usage
```
```ini title="/etc/systemd/journald.conf.d/size.conf"
[Journal]
Storage=persistent
SystemMaxUse=1G
MaxRetentionSec=30day
```
@check
How do you read the logs from before the last reboot? || `journalctl -b -1`, which needs persistent storage.
@end

@concept Resource control with cgroups
@plain
Every service runs in its own **cgroup**, a kernel group that can limit and measure CPU, memory, I/O and process count. systemd exposes these as unit settings.
@problem
One runaway service can starve a host. Without limits, a memory leak triggers the global OOM killer, which may kill something important.
@does
- `CPUWeight=` is a relative share when contended; `CPUQuota=200%` caps at two cores.
- `MemoryHigh=` throttles and reclaims above the threshold; `MemoryMax=` is a hard limit that triggers an OOM kill inside the cgroup only.
- `TasksMax=` limits process and thread count; `IOWeight=` and `IOReadBandwidthMax=` control disk use.
- `systemd-cgtop` shows live per-cgroup use. Kubernetes uses the same kernel feature for pod limits.
@diagram cmp
caption: Soft and hard memory limits
cards:
  - {h: "MemoryHigh", kind: warn, items: ["Soft ceiling", "Kernel slows and reclaims", "No kill"]}
  - {h: "MemoryMax", kind: bad, items: ["Hard ceiling", "OOM kill inside the cgroup", "Other services unaffected"]}
  - {h: "CPUQuota", kind: info, items: ["Hard CPU cap", "200% equals two cores"]}
@h Limit a service
```bash title="Runtime limits and a one-off sandbox" lab
sudo systemctl set-property --runtime nginx.service MemoryHigh=300M MemoryMax=400M CPUQuota=150%
systemctl show nginx -p MemoryMax -p CPUQuotaPerSecUSec
systemd-cgtop -n 1 -b | head -8
# a throwaway test of the OOM behaviour (needs about 200 MB of RAM free)
sudo systemd-run --scope -p MemoryMax=50M python3 -c "x = bytearray(200*1024*1024)"; echo exit=$?
```
:::note
Memory accounting depends on cgroup v2, which current distributions use by default. Check with `stat -fc %T /sys/fs/cgroup` (expect cgroup2fs).
:::
@end

@concept Socket and path activation
@plain
systemd can listen on a port for you and start the service only when the first connection arrives. A **path unit** starts a service when a file appears or changes.
@problem
Services that are rarely used still consume memory, and dependencies between services at boot can be avoided if the socket exists before the process does.
@does
- A `.socket` unit with the same name as the `.service` hands the open socket to the service.
- Connections queue while the service starts, so no request is lost during restarts.
- A `.path` unit with `PathChanged=` or `PathExists=` triggers a job, a simple way to process dropped files.
@diagram seq
caption: First request starts the service
actors: ["Client|curl|ext", "systemd|holds the socket|cp", "Service|started on demand|app"]
steps:
  - "0>1: connect to port 9000 | req"
  - "1>2: start service, pass socket | req"
  - "2>0: response | resp"
@h Example
```ini title="/etc/systemd/system/echo.socket"
[Socket]
ListenStream=127.0.0.1:9000
Accept=yes

[Install]
WantedBy=sockets.target
```
```ini title="/etc/systemd/system/echo@.service"
[Service]
ExecStart=/usr/bin/cat
StandardInput=socket
```
```bash title="Try it" lab
sudo systemctl daemon-reload && sudo systemctl enable --now echo.socket
echo hello | nc 127.0.0.1 9000
systemctl list-sockets --no-pager | head
```
@check
Why use socket activation for restarts? || The socket stays open, so clients queue instead of being refused while the process restarts.
@end

@concept Debugging failed units
@plain
When a unit fails, work through status, the journal, the exact environment, and the security settings. Most failures are a wrong path, a wrong user, or a sandbox option that blocks something.
@problem
Guessing and editing randomly wastes time, and a unit restarted by `Restart=` in a loop hides the first error.
@does
- `systemctl status -l` shows the exit code or signal. `systemctl reset-failed` clears the state.
- Start rate limits (`StartLimitBurst`) put a unit into failed state after repeated crashes; find "start request repeated too quickly".
- `systemd-analyze verify unit` checks syntax; `systemd-analyze security unit` scores sandboxing; `systemd-run --pty` reproduces the environment.
@diagram flow
caption: A unit debugging routine
numbered: true
nodes:
  - "status -l|exit code and last logs|info"
  - "journalctl -u|full first error|app"
  - "verify and cat|syntax and merged config|env"
  - "run by hand|as the same user|warn"
  - "relax sandbox|one option at a time|ok"
@h Routine
```bash title="Debug commands" lab
systemctl --failed --no-pager
systemctl status sshd -l --no-pager | head -15
journalctl -u sshd -b --no-pager | head -20
systemd-analyze verify /etc/systemd/system/*.service 2>&1 | head
sudo systemd-run --pty --uid=nobody --property=PrivateTmp=yes /bin/bash -c 'id; echo $PATH'
```
:::tip
Exit status 203/EXEC means the binary was not found or not executable; 217/USER means the User= does not exist; 226/NAMESPACE means a sandbox option could not be applied.
:::
@end
