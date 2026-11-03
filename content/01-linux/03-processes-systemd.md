---
title: Processes, signals and systemd
minutes: 45
objectives:
  - Explain how a process is created, what its states mean and how it ends
  - Send the right signal and know why SIGTERM comes before SIGKILL
  - Write a hardened systemd service and a timer, and read its logs
---
A running program is a **process**. Containers, Kubernetes pods and CI jobs are all processes with extra isolation around them, so understanding processes explains most of what you will later see in `docker` and `kubectl`.

@concept What a process is
@plain
A process is a program that is running. The kernel gives it an ID (**PID**), its own memory, a list of open files, and a user identity. New processes are created by an existing process asking the kernel to **fork** a copy and then **exec** a different program into it.
@problem
Without separate processes, one crashing program would take everything down, programs could read each other's memory, and the system could not share one CPU between many tasks fairly.
@does
- Every process has a parent. **PID 1** is the first one started by the kernel; it adopts orphans and, inside a container, it is your application.
- The scheduler gives each runnable process short slices of CPU time.
- `/proc/<pid>/` exposes live details: command line, open files, memory map and limits.
@diagram flow
caption: A shell starting a command: fork, then exec
numbered: true
nodes:
  - "Shell|PID 812|app"
  - "fork()|child is a copy, PID 930|info"
  - "exec(ls)|child becomes the ls program|env"
  - "Runs|reads and prints|ok"
  - "exit(0)|parent collects the status|plain"
@h Looking at processes
```bash title="See what is running"
ps -eo pid,ppid,user,stat,%cpu,%mem,etime,comm --sort=-%cpu | head -8   # busiest first
pstree -p $$ 2>/dev/null | head       # the tree above and below your shell
ls -l /proc/$$/fd                     # files this shell has open
cat /proc/$$/limits | head -5         # per-process limits
top -b -n 1 | head -12                # one batch snapshot instead of an interactive screen
```
@check
Why does it matter that PID 1 handles signals correctly in a container? || The runtime sends the stop signal to PID 1; if it ignores it, the container waits and is then killed after the grace period.
@end

@concept Process states and zombies
@plain
At any moment a process is running, waiting, sleeping, stopped or finished-but-not-collected. The one letter in the `STAT` column of `ps` tells you which.
@problem
When a server is slow or stuck, the first question is whether processes are busy computing, waiting for a disk, or just idle. Reading the state saves guesswork.
@does
- `R` running or ready, `S` sleeping and interruptible, `D` **uninterruptible sleep** (usually waiting on disk or network storage; it cannot be killed), `T` stopped, `Z` **zombie**.
- A zombie has already exited; only its exit status remains until its parent calls `wait`. It uses no CPU or memory, but a growing number means a buggy parent.
- Many processes in `D` with a high load average point to a storage problem, not a CPU one.
@diagram cmp
caption: What each state letter tells you
cards:
  - {h: "R running", kind: ok, items: ["On a CPU or waiting for one", "Many R with high load = CPU bound"]}
  - {h: "S sleeping", kind: app, items: ["Waiting for an event", "Normal for idle services"]}
  - {h: "D disk wait", kind: warn, items: ["Cannot be interrupted", "Suspect storage or NFS"]}
  - {h: "Z zombie", kind: bad, items: ["Finished, not yet reaped", "Fix the parent, not the zombie"]}
@h Spotting trouble
```bash title="Find stuck and zombie processes"
ps -eo pid,ppid,stat,wchan:20,comm | awk '$3 ~ /^D/'     # uninterruptible, and what they wait on
ps -eo pid,ppid,stat,comm | awk '$3 ~ /^Z/'              # zombies and their parent PID
uptime                                                   # load averages for 1, 5, 15 minutes
```
:::tip
Load average counts running *and* uninterruptible tasks. A load of 20 on a 4-core machine could be CPU saturation or a stuck disk. Check the `D` states before adding CPUs.
:::
@end

@concept Signals
@plain
A signal is a short message sent to a process: stop, reload, or you have done something illegal. Most can be caught so the program can tidy up. Two cannot.
@problem
You need a way to tell a program to shut down cleanly (finish requests, flush data) and a way to force it when it will not listen. Killing everything instantly would corrupt data.
@does
- **SIGTERM (15)**: polite stop request; programs catch it, finish work and exit. This is the default of `kill`.
- **SIGINT (2)**: what Ctrl-C sends. **SIGHUP (1)**: terminal closed; many daemons reread config on it.
- **SIGKILL (9)**: cannot be caught or ignored; the kernel removes the process immediately with no cleanup.
- Kubernetes and Docker do exactly this: send SIGTERM, wait the grace period (30 seconds by default in Kubernetes), then send SIGKILL.
@diagram seq
caption: A graceful stop that escalates to a forced kill
actors: ["Orchestrator|Kubernetes or Docker|cp", "App|PID 1|app"]
steps:
  - "0>1: SIGTERM | req"
  - "note 1..1: finish requests, close DB"
  - "1>0: exits 0 | resp"
  - "0>1: grace period over: SIGKILL | bad"
  - "note 0..1: no cleanup, data may be lost"
@h Sending signals
```bash title="Signals in practice" lab
sleep 300 & echo "pid=$!"          # a harmless process to practise on
kill -TERM %1                      # polite request (same as: kill %1)
sleep 300 & kill -KILL %2          # forced; the process never sees it
trap 'echo cleaning up; exit 0' TERM    # a script can catch TERM
kill -l | head -3                  # list signal names and numbers
pkill -HUP nginx                   # ask nginx to reload its configuration
```
:::warn
`kill -9` as a first resort skips cleanup and can leave locks, half-written files and corrupt databases. Always try TERM first and wait a few seconds.
:::
@check
Which signal can a program never handle? || SIGKILL (9) and SIGSTOP; the kernel acts on them directly.
Why does a container that ignores SIGTERM take 30 seconds to stop? || The orchestrator waits the grace period and then sends SIGKILL.
@end

@concept Foreground, background and job control
@plain
Your shell can run one program in front of you and many behind it. `&` starts a command in the background, Ctrl-Z pauses the foreground one, and `bg`/`fg` move jobs back and forth.
@problem
A long task should not lock your terminal, and it should not die when your SSH connection drops.
@does
- `cmd &` runs in the background but still belongs to your terminal session and may receive SIGHUP when you log out.
- `nohup cmd &` or, better, a systemd service survives logout.
- `tmux` or `screen` keep a persistent session you can re-attach to.
@diagram flow
caption: Choosing how to keep a long job alive
nodes:
  - "Run in foreground|stays until done|plain"
  - "cmd & |background, dies with the session|warn"
  - "nohup or tmux|survives logout|info"
  - "systemd service|restarts, logs, limits|ok"
@choose Keeping a job running
Foreground | a quick task you want to watch | it takes longer than your connection is reliable
tmux / screen | an interactive, long-lived session | the job must start at boot or restart on failure
systemd service | anything that should run unattended | a one-off command you will never repeat
@end

@concept systemd services
@plain
**systemd** is the first process (PID 1) on most Linux servers. It starts services in the right order, restarts them when they fail, and collects their logs. A **unit file** describes one service.
@problem
Before systemd, each service had its own init script with different behaviour. Writing "start this program at boot, restart it if it crashes, and run it as a limited user" meant a lot of fragile shell.
@does
- Units live in `/etc/systemd/system/` (yours) and `/usr/lib/systemd/system/` (packages). Never edit the packaged ones; use drop-ins.
- `systemctl` starts, stops, enables at boot and shows status. `journalctl` reads the logs.
- Built-in sandboxing options reduce what a compromised service can do.
@diagram layers
caption: How systemd organises a server
layers:
  - {label: "Targets", nodes: ["multi-user.target|normal server state|cp", "network-online.target|network is ready|cp"]}
  - {label: "Units", nodes: ["shop.service|your app|app", "nginx.service|web server|app", "backup.timer|schedule|env"]}
  - {label: "Services of systemd", nodes: ["journald|collects logs|ok", "cgroups|resource limits per service|ok"]}
@h A hardened unit file
```ini title="/etc/systemd/system/shop.service"
[Unit]
Description=Shop API
After=network-online.target
Wants=network-online.target

[Service]
User=shop
Group=shop
WorkingDirectory=/opt/shop
EnvironmentFile=/etc/shop/shop.env
ExecStart=/opt/shop/bin/shop --port 8080
Restart=on-failure
RestartSec=3
TimeoutStopSec=30
# sandboxing: each line removes something a bug could abuse
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/shop
CapabilityBoundingSet=
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```
@h Operating it
```bash title="systemctl and journalctl" lab
sudo systemctl daemon-reload              # after creating or editing a unit file
sudo systemctl enable --now shop          # start now and at every boot
systemctl status shop --no-pager          # state, PID, last log lines
sudo systemctl restart shop
journalctl -u shop -f                     # follow the logs
journalctl -u shop --since "1 hour ago" -p err   # only errors from the last hour
systemd-analyze security shop             # score how exposed the service is
```
@check
What does Restart=on-failure not restart? || A service that exits cleanly with status 0 or was stopped by an administrator.
Why set User= in a unit file? || So the service does not run as root; a compromise then stays inside that user's permissions.
@end

@concept systemd timers
@plain
A **timer unit** starts a service on a schedule, like cron but with logs, dependencies and the ability to catch up after the machine was off.
@problem
Cron jobs fail silently, have no built-in logging, run even when a previous run is still going, and miss jobs while the host is down.
@does
- `OnCalendar=` takes calendar expressions such as `daily` or `Mon..Fri 02:30`.
- `Persistent=true` runs a missed job at the next boot.
- The job's output goes to the journal, so `journalctl -u backup.service` shows every run.
- `systemd-analyze calendar "<expression>"` shows when it will next run.
@diagram flow
caption: A timer triggers a service
nodes:
  - "backup.timer|OnCalendar=daily|env"
  - "backup.service|oneshot job|app"
  - "journal|every run logged|ok"
@h Example
```ini title="backup.timer and backup.service"
# /etc/systemd/system/backup.timer
[Unit]
Description=Nightly backup

[Timer]
OnCalendar=*-*-* 02:30:00
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target

# /etc/systemd/system/backup.service
[Unit]
Description=Backup job

[Service]
Type=oneshot
ExecStart=/usr/local/bin/backup.sh
```
```bash title="Enable and inspect" lab
sudo systemctl enable --now backup.timer
systemctl list-timers --all | head
systemd-analyze calendar "Mon..Fri 02:30"
```
@end
