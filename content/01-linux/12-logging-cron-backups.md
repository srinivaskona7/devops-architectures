---
title: Logging, cron, timers and backups
minutes: 45
objectives:
  - Read and filter logs with journalctl and keep log files under control with logrotate
  - Schedule recurring work with cron and systemd timers and avoid overlapping runs
  - Design a backup that follows 3-2-1 and prove it with a restore test
---
Operations is mostly three things: knowing what happened (logs), making routine things happen (schedules) and being able to recover (backups). This section covers all three on a single Linux host. The same ideas return in Kubernetes as stdout logs, CronJobs and Velero.

@concept Where Linux logs live
@plain
Programs report what they do as log lines. On a modern Linux host they flow into the **systemd journal** and often also into text files under `/var/log`.
@problem
When something breaks you need a timeline: what started, what failed, who logged in. Without central, timestamped logs you are guessing.
@does
- `journald` stores structured, indexed logs from services, the kernel and `logger`. `journalctl` queries them.
- Classic files remain: `/var/log/syslog` or `/var/log/messages`, `/var/log/auth.log` or `/var/log/secure`, `/var/log/audit/audit.log`.
- Containers write to stdout and stderr; the runtime stores or forwards them, and `kubectl logs` reads them.
- The journal is volatile unless `/var/log/journal` exists or `Storage=persistent` is set.
@diagram flow
caption: Log paths on a host
nodes:
  - "Services|stdout, syslog calls|app"
  - "journald|structured store|cp"
  - "rsyslog or agent|forwards copies|info"
  - "Central store|Loki, OpenSearch, CloudWatch|ok"
@h Finding the logs
```bash title="Where things are written" lab
ls -lh /var/log | head -15
journalctl --disk-usage                         # how big the journal is
journalctl --list-boots | tail -3               # boots with logs available
logger -t demo "hello from the lab"             # write a line yourself
journalctl -t demo -n 2 --no-pager
```
@check
Why might journalctl show nothing from before the last reboot? || The journal is stored in memory under /run unless persistent storage is enabled.
@end

@concept Searching the journal
@plain
`journalctl` filters by unit, time, priority and boot, so you can narrow millions of lines to the few that matter.
@problem
Running `grep` over text files loses structure and is slow. Incidents need a fast "errors from this service in the 10 minutes before the outage" query.
@does
- `-u unit` selects a service, `-p err` means priority error and worse, `-b` the current boot, `-k` kernel messages.
- `--since` and `--until` accept times such as `"2026-10-31 10:00"` or `"30 min ago"`.
- `-o json` gives structured output for `jq`; `-f` follows live; `-n` limits lines.
- Priorities run from 0 emerg to 7 debug; `-p warning` includes warning and everything more severe.
@diagram flow
caption: Narrowing a search
numbered: true
nodes:
  - "Time window|--since 30 min ago|info"
  - "Unit|-u shop|app"
  - "Priority|-p err|warn"
  - "Pattern|-g timeout|ok"
@h Queries
```bash title="Useful journalctl queries" lab
journalctl -u ssh -u sshd --since "1 hour ago" --no-pager | tail -5
journalctl -p err -b --no-pager | tail -10        # errors since boot
journalctl -k --since "today" | grep -i oom       # kernel OOM kills
journalctl -u cron --since yesterday -g "CMD" --no-pager | tail -3
journalctl -o json -n 1 --no-pager | jq '{unit: ._SYSTEMD_UNIT, msg: .MESSAGE}'
sudo journalctl --vacuum-time=14d                 # delete entries older than 14 days
```
@check
How would you see only errors from one service in the last hour? || journalctl -u name -p err --since "1 hour ago".
@end

@concept logrotate and disk safety
@plain
Log files grow forever unless something rotates them. **logrotate** renames old logs, compresses them and deletes the oldest by a policy you define.
@problem
A full disk is one of the most common outages. A single chatty application writing a text log can fill `/var` in days and take down everything on the host.
@does
- Policies live in `/etc/logrotate.d/`. Typical options: `daily`, `rotate 14`, `compress`, `missingok`, `notifempty`.
- `copytruncate` is for programs that cannot reopen their log; otherwise use `postrotate` to signal them.
- It runs daily from a systemd timer or cron. `logrotate -d` is a dry run.
- Set journal limits with `SystemMaxUse=` in `/etc/systemd/journald.conf`.
@diagram flow
caption: A rotation cycle
numbered: true
nodes:
  - "app.log|active file|app"
  - "app.log.1|renamed|info"
  - "app.log.2.gz|compressed|info"
  - "Deleted|beyond 14 copies|bad"
@h Example policy
```text title="/etc/logrotate.d/shop"
/var/log/shop/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    create 0640 shop shop
    postrotate
        systemctl kill -s HUP shop.service
    endscript
}
```
```bash title="Test without changing anything" lab
sudo logrotate -d /etc/logrotate.d/shop     # debug mode, shows what would happen
sudo logrotate -f /etc/logrotate.d/shop     # force a rotation now
df -h /var /var/log                         # watch free space
sudo du -xh /var/log --max-depth=1 | sort -h | tail -5
```
:::tip
In containers do not write log files at all. Write to stdout and let the platform collect, rotate and ship the logs.
:::
@check
Why signal the app after rotating? || It holds the old file open; the signal makes it reopen a fresh file at the original path.
@end

@concept Central logging and structured logs
@plain
Instead of logging into servers to read files, every host sends its logs to one searchable place. Applications write each event as one **JSON line** with fields rather than free text.
@problem
With hundreds of pods and nodes, logs vanish when a pod is replaced, and nobody can search across services. Free text also makes it hard to filter by user, request or status.
@does
- Agents such as Fluent Bit, Vector or the OpenTelemetry Collector tail logs and forward them to Loki, OpenSearch or CloudWatch Logs.
- Structured fields (`level`, `service`, `trace_id`, `status`) allow queries like "all 5xx from checkout for trace X".
- Add a correlation or trace ID to every line to follow one request across services.
- Never log secrets or personal data; mask them at the source.
@diagram flow
caption: A central logging pipeline
nodes:
  - "App stdout|one JSON event per line|app"
  - "Agent|Fluent Bit on each node|cp"
  - "Storage|Loki or OpenSearch|env"
  - "Search and alerts|Grafana or Kibana|ok"
@h A structured line and a query
```json title="One log event"
{"ts":"2026-10-31T11:29:39Z","level":"error","service":"checkout","trace_id":"4bf92f35","status":502,"msg":"payment gateway timeout","duration_ms":3012}
```
```bash title="Filter JSON logs with jq" lab
printf '%s\n' '{"level":"info","status":200}' '{"level":"error","status":502}' | jq -c 'select(.level=="error")'
journalctl -u shop -o cat -n 100 --no-pager | jq -c 'select(.status >= 500)' 2>/dev/null | head
```
@check
Why are JSON logs better than plain text at scale? || Fields are indexed and filterable without fragile regular expressions.
@end

@concept cron
@plain
**cron** runs commands on a schedule. Each line has five time fields and then a command.
@problem
Routine jobs such as report generation, cleanup and renewals should happen without a person remembering them.
@does
- Fields: minute, hour, day of month, month, day of week. `*/15` means every 15, `1-5` is a range.
- Edit your table with `crontab -e`; system jobs live in `/etc/cron.d/` and include a user field.
- Cron has a tiny environment: a short `PATH` and no profile. Use full paths and set variables.
- Output is mailed or lost. Redirect to a log or use `logger`. Use `flock` to prevent overlapping runs.
@diagram cmp
caption: The five cron fields
cards:
  - {h: "0 2 * * *", kind: app, items: ["02:00 every day", "minute 0, hour 2"]}
  - {h: "*/15 * * * *", kind: info, items: ["Every 15 minutes", "Good for light checks"]}
  - {h: "30 3 * * 1-5", kind: env, items: ["03:30 Monday to Friday", "Weekday batch jobs"]}
  - {h: "0 0 1 * *", kind: ok, items: ["Midnight on the 1st", "Monthly tasks"]}
@h A safe cron entry
```text title="/etc/cron.d/shop-cleanup"
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin
MAILTO=""
# m h dom mon dow user command
15 2 * * * shop flock -n /run/shop-cleanup.lock /opt/shop/bin/cleanup.sh 2>&1 | logger -t shop-cleanup
```
```bash title="Work with crontab" lab
crontab -l 2>/dev/null || echo "no crontab yet"
( crontab -l 2>/dev/null; echo '*/30 * * * * /usr/bin/date >> /tmp/cron-demo.log' ) | crontab -
crontab -l
crontab -r                                       # remove your whole table (careful)
```
:::warn
`crontab -r` deletes the whole table without confirmation. Keep crontabs in Git and install them from there.
:::
@check
Why does a script that works in a terminal fail from cron? || Cron has a minimal environment, so PATH and variables differ; use absolute paths.
@end

@concept systemd timers versus cron
@plain
A systemd timer starts a service unit on a schedule. It gives you the logging, resource limits and dependency handling of a service.
@problem
Cron lacks a record of past runs, cannot catch up after downtime, and runs overlapping copies if a job is slow.
@does
- `OnCalendar=` for wall clock schedules; `OnBootSec=` and `OnUnitActiveSec=` for relative ones.
- `Persistent=true` catches up missed runs; `RandomizedDelaySec=` spreads load across a fleet.
- A oneshot service does not start again while still running, which prevents overlap.
- `systemctl list-timers` shows last and next run.
@diagram cmp
caption: Choosing a scheduler
cards:
  - {h: "cron", kind: warn, items: ["Simple, everywhere", "No history, no catch-up", "Best for quick personal jobs"]}
  - {h: "systemd timer", kind: ok, items: ["Journal logs per run", "Persistent catch-up", "Best for server duties"]}
  - {h: "Kubernetes CronJob", kind: cp, items: ["Runs a pod on schedule", "concurrencyPolicy controls overlap", "Best for cluster workloads"]}
@h Calendar expressions
```bash title="Check when a timer would fire" lab
systemd-analyze calendar "Mon..Fri *-*-* 02:30:00"
systemd-analyze calendar "*:0/15"                   # every 15 minutes
systemd-analyze calendar "weekly" --iterations=3
systemctl list-timers --all --no-pager | head -8
```
@check
Which setting makes a timer run a job that was missed while the host was off? || Persistent=true.
@end

@concept Backups that can be restored
@plain
A backup is a copy of data that lets you recover after deletion, corruption, ransomware or a failed host. A backup you have never restored is only a hope.
@problem
Replicas copy mistakes instantly: if someone drops a table, all replicas drop it too. Only independent point-in-time copies protect against that.
@does
- Follow **3-2-1**: three copies, on two kinds of storage, one off-site or in another account and region.
- Define **RPO** (how much data you can lose) and **RTO** (how long recovery may take); these decide frequency and tooling.
- Use tools with deduplication, encryption and verification such as `restic` or `borg`; for databases use their native dump or snapshot tools.
- Make the destination append-only or versioned (S3 Object Lock) so ransomware cannot erase it. Run a restore test on a schedule.
@diagram flow
caption: A backup lifecycle that includes proof
numbered: true
nodes:
  - "Snapshot or dump|consistent copy|app"
  - "Encrypt and upload|S3 in another account|info"
  - "Verify|restic check|warn"
  - "Restore test|monthly, into a scratch host|ok"
@h Backups with restic
```bash title="restic to S3" lab
export RESTIC_REPOSITORY=s3:s3.amazonaws.com/example-backups/shop
export RESTIC_PASSWORD_FILE=/etc/restic/password
restic init                                         # once
restic backup /var/lib/shop --exclude '*.tmp' --tag nightly
restic snapshots --compact | tail -5
restic check --read-data-subset=5%                  # verify a sample of stored data
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 6 --prune
restic restore latest --target /tmp/restore-test    # the step most teams skip
```
:::danger
Keep the backup encryption key and credentials outside the system being backed up. Losing the key makes every backup useless, and keeping it only on the failed host is a common mistake.
:::
@check
What is the difference between RPO and RTO? || RPO is the maximum acceptable data loss measured in time; RTO is the maximum acceptable time to restore service.
@end
