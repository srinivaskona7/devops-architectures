---
title: Incident labs
minutes: 60
objectives:
  - Follow a fixed triage routine for any host incident
  - Diagnose and fix a full disk, including deleted but open files and inode exhaustion
  - Find a memory leak and a runaway process and contain them
  - Resolve a DNS outage and an expired certificate under time pressure
---
Each lab gives symptoms, the commands that find the cause, the fix, and how to stop it recurring. Run the reproduction steps only in a disposable VM or container, never on a shared machine.

@concept The triage routine
@plain
Before diving into one theory, spend two minutes collecting the same facts every time. It prevents tunnel vision and produces notes for the postmortem.
@problem
Under pressure people start restarting services, which destroys evidence and may hide the root cause.
@does
- Confirm impact and timing: what is failing, for whom, since when, what changed.
- Capture state before changing it: `uptime`, `df -h`, `free -h`, `ss -s`, top processes, `dmesg`, journal errors.
- Mitigate first if users are hurt (rollback, failover, scale), investigate second.
- Write down each command and its result with a timestamp.
@diagram flow
caption: Two minute first look
numbered: true
nodes:
  - "Impact|who and since when|info"
  - "Snapshot state|load, disk, memory, network|app"
  - "Recent change|deploy, config, cert, date|warn"
  - "Mitigate|restore service|cp"
  - "Root cause|then prevent|ok"
@h A snapshot script
```bash title="triage.sh" lab
#!/usr/bin/env bash
# Save the first-look facts with a timestamp. Safe, read-only.
out=/tmp/triage-$(date +%Y%m%dT%H%M%S).txt
{
  date -u; uptime
  echo "--- disk";   df -hP | head -15; df -iP | head -8
  echo "--- memory"; free -m
  echo "--- cpu";    ps -eo pid,user,%cpu,%mem,etime,comm --sort=-%cpu | head -6
  echo "--- net";    ss -s | head -4
  echo "--- kernel"; dmesg 2>/dev/null | tail -5
  echo "--- failed"; systemctl --failed --no-pager 2>/dev/null | head -6
} > "$out"
echo "saved $out"
```
@check
Why capture state before restarting? || A restart destroys evidence such as memory use, open files and error state.
@end

@concept Lab 1: the disk is full
@plain
Writes fail with "No space left on device". Services crash, databases refuse writes and logs stop. There are two kinds: out of blocks, and out of inodes.
@problem
`df` says 100 percent but `du` cannot find the big files, or `df` says 40 percent and you still cannot create files.
@does
- **Symptoms**: errors on write, `df -h` at 100 percent on one mount.
- **Find**: `du -xh --max-depth=1 / | sort -h | tail` walks down one level at a time.
- **Deleted but open**: if a process holds a deleted file open, space is not freed until the process closes it. `lsof +L1` lists them.
- **Inodes**: `df -i` at 100 percent means millions of tiny files, for example a session directory.
- **Fix**: truncate (`: > file`) rather than delete a log a process holds open; restart or signal the holder; add rotation.
@diagram flow
caption: Disk full decision path
nodes:
  - "df -h|which mount is full|info"
  - "du -xh depth 1|find the biggest directory|app"
  - "lsof +L1|deleted but open files|warn"
  - "df -i|inodes exhausted|warn"
  - "Free space|truncate, rotate, resize|ok"
@h Reproduce and fix
```bash title="Create the problem in a small loop filesystem" nocheck
# needs root; creates a 50 MB filesystem so nothing real fills up
dd if=/dev/zero of=/tmp/small.img bs=1M count=50 status=none
mkfs.ext4 -q /tmp/small.img && sudo mkdir -p /mnt/small && sudo mount -o loop /tmp/small.img /mnt/small
sudo dd if=/dev/zero of=/mnt/small/big.log bs=1M count=60 2>&1 | tail -1     # No space left on device
df -h /mnt/small
# deleted-but-open trick
sudo bash -c 'exec 3>/mnt/small/held.log; rm /mnt/small/big.log; sleep 120' &
sleep 1; df -h /mnt/small; sudo lsof +L1 /mnt/small | head -3
```
```bash title="Diagnose and fix" nocheck
sudo du -xh --max-depth=1 /var | sort -h | tail -5
sudo lsof +L1 | head                          # which PID holds deleted files
sudo truncate -s 0 /var/log/app/big.log       # frees space, keeps the inode for the writer
sudo journalctl --vacuum-size=500M
sudo umount /mnt/small; rm /tmp/small.img     # clean up the lab
```
:::note
Cloud fix: grow the volume (`aws ec2 modify-volume`), then `growpart` and `resize2fs` or `xfs_growfs`. Check current docs for modification limits.
:::
@check
df shows 100 percent but du totals far less. Why? || A process still holds deleted files open; find with lsof +L1.
@end

@concept Lab 2: a memory leak
@plain
Memory use of one process climbs steadily until the OOM killer ends it or the host starts to swap. The classic pattern is a sawtooth on the dashboard: rises, crash, restart, rises again.
@problem
Restarting hides it for hours. You need to show that memory grows with time or load and find where it is allocated.
@does
- **Symptoms**: container restarts with exit code 137 and reason OOMKilled; `dmesg` says "Out of memory: Killed process".
- **Measure**: sample RSS repeatedly (`ps -o rss= -p PID`) and fit a trend. 12 samples one minute apart growing by 40 MB each means about 40 MB per minute, so a 2 GiB limit lasts about 51 minutes (2048 / 40).
- **Locate**: language profilers (heap dump, `tracemalloc`, pprof), `pmap -x PID`, `/proc/PID/smaps_rollup`.
- **Fix**: correct the leak; meanwhile raise the limit modestly, restart on schedule, and alert on trend.
@diagram flow
caption: From OOM kill to cause
nodes:
  - "OOMKilled|exit 137, dmesg line|bad"
  - "RSS trend|sample over time|info"
  - "Heap profile|what is growing|app"
  - "Fix and test|soak test in staging|ok"
@h Reproduce and measure
```python title="leaky.py" lab
import time
cache = []
while True:
    cache.append(bytearray(10 * 1024 * 1024))     # 10 MiB retained forever
    time.sleep(1)
```
```bash title="Watch it grow, then cap it" nocheck
python3 leaky.py & pid=$!
for i in 1 2 3 4 5; do ps -o rss= -p $pid | awk '{printf "%.0f MiB\n", $1/1024}'; sleep 2; done
kill $pid
sudo systemd-run --scope -p MemoryMax=120M python3 leaky.py; echo "exit=$?"     # killed at the cap
journalctl -k --since "2 min ago" | grep -i 'killed process'
```
```python title="Time until the limit" lab
limit_mib, used_mib, rate_mib_per_min = 2048, 300, 40
print(round((limit_mib - used_mib) / rate_mib_per_min, 1), "minutes left")    # 43.7
```
@check
What exit code does a container OOM kill report? || 137, which is 128 plus signal 9.
@end

@concept Lab 3: a DNS outage
@plain
Names stop resolving, so everything that uses a hostname fails even though the network is up. In Kubernetes, CoreDNS problems look like random timeouts across all services.
@problem
Applications report "connection timed out" or "temporary failure in name resolution", and teams chase the network instead of DNS.
@does
- **Symptoms**: `ping 8.8.8.8` works, `ping example.com` fails; `curl` hangs at name lookup (`time_namelookup` is large).
- **Find the layer**: `cat /etc/resolv.conf` (which server), `resolvectl status`, `dig @server name` against the server directly, `dig +trace` for delegation.
- **Kubernetes**: check `kubectl -n kube-system get pods -l k8s-app=kube-dns`, CoreDNS logs, and the `ndots:5` search path effect that multiplies lookups.
- **Fix**: restore or fail over the resolver; correct the record; flush caches; add a local cache (node-local DNS); alert on lookup latency.
@diagram flow
caption: Narrowing a DNS failure
numbered: true
nodes:
  - "IP works?|ping 8.8.8.8|info"
  - "Resolver config|resolv.conf|app"
  - "Ask the server|dig @ip name|cp"
  - "Authoritative|dig +trace|env"
  - "Fix and flush|record or resolver|ok"
@h Commands
```bash title="Diagnose resolution" lab
cat /etc/resolv.conf
dig +short example.com                         # uses the system resolver
dig +short example.com @1.1.1.1                # bypass it: works here but not above means local resolver problem
dig +trace example.com | tail -4
curl -s -o /dev/null -w 'dns=%{time_namelookup}s total=%{time_total}s\n' https://example.com
resolvectl status 2>/dev/null | head -8
```
```bash title="Kubernetes view" nocheck
kubectl -n kube-system get pods -l k8s-app=kube-dns -o wide
kubectl -n kube-system logs -l k8s-app=kube-dns --tail=20
kubectl run dnscheck --rm -it --image=busybox:1.36 --restart=Never -- nslookup kubernetes.default
kubectl get cm coredns -n kube-system -o yaml | grep -A8 Corefile
```
:::tip
A pod default `ndots:5` makes a lookup of `api.example.com` try several search domains first. Use a trailing dot (`api.example.com.`) in hot paths if latency matters.
:::
@check
ping by IP works but by name fails. What layer is broken? || Name resolution (DNS), not routing.
@end

@concept Lab 4: a runaway process
@plain
One process uses all the CPU, or spawns children until the process table fills (a fork bomb), and the machine becomes unresponsive.
@problem
You cannot even log in, or the load average is 50 and the application is slow. Killing blindly may kill the wrong thing.
@does
- **Symptoms**: load far above core count, `top` shows one process near 100 percent per core, or thousands of identical child processes.
- **Find**: `ps -eo pid,ppid,%cpu,etime,cmd --sort=-%cpu | head`; `pstree -p`; `cat /proc/PID/status`.
- **Contain**: `renice +19 PID` and `cpulimit`; stop it with `kill -STOP PID` (reversible) while you read what it is doing; then TERM, wait, then KILL.
- **Prevent**: cgroup limits (`CPUQuota`, `TasksMax`), `ulimit -u`, Kubernetes CPU limits and pod disruption.
@diagram flow
caption: Contain, understand, then end
numbered: true
nodes:
  - "Find the PID|ps sorted by CPU|info"
  - "Pause|kill -STOP|warn"
  - "Inspect|strace, /proc, logs|app"
  - "Terminate|TERM then KILL|bad"
  - "Limit|cgroup quota, TasksMax|ok"
@h Reproduce and contain
```bash title="Burn CPU and handle it" lab
yes > /dev/null & pid=$!
sleep 2; ps -o pid,%cpu,stat,cmd -p $pid
renice +19 -p $pid                               # lower its priority
kill -STOP $pid; ps -o pid,stat -p $pid          # T = stopped, CPU use goes to zero
kill -CONT $pid
kill -TERM $pid; sleep 1; ps -p $pid || echo "gone"
```
```bash title="Limit with systemd" nocheck
sudo systemd-run --unit=burn --property=CPUQuota=20% --property=TasksMax=50 sh -c 'yes > /dev/null'
sleep 3; systemctl status burn --no-pager | grep -E 'CPU|Tasks'
sudo systemctl stop burn
```
@check
Why STOP before KILL? || It freezes the process reversibly so you can inspect it without losing evidence.
@end

@concept Lab 5: an expired certificate
@plain
At a known second, HTTPS connections start failing with "certificate has expired". Browsers show a full-page warning and APIs return TLS errors.
@problem
It is entirely predictable yet it still causes outages, because the renewal automation silently broke or a forgotten internal certificate was never in the inventory.
@does
- **Symptoms**: `curl: (60) SSL certificate problem: certificate has expired`; clients with strict TLS fail while some lenient ones continue.
- **Find**: `openssl s_client` against the real endpoint (not the file on disk): check `notAfter` for the leaf and intermediates. In Kubernetes: `kubectl get certificate -A` and `kubectl describe certificate`.
- **Fix**: renew now (`certbot renew`, delete the failed cert-manager Order to retrigger, issue manually), install the new full chain, reload the server (a running nginx does not read new files until reload), verify through the load balancer.
- **Prevent**: alert at 21 and 7 days; a certificate inventory; short-lived automated certificates.
@diagram flow
caption: Expiry response
numbered: true
nodes:
  - "Confirm|openssl s_client on the endpoint|info"
  - "Renew|ACME or CA|app"
  - "Install full chain|key and fullchain|cp"
  - "Reload|nginx, ingress, LB|warn"
  - "Verify and alert|from outside|ok"
@h Detect and repair
```bash title="Check expiry from the client side" lab
host=example.com
echo | openssl s_client -connect $host:443 -servername $host 2>/dev/null | openssl x509 -noout -subject -enddate
curl -sv https://$host -o /dev/null 2>&1 | grep -iE 'expire|certificate verify'
```
```bash title="Kubernetes and cert-manager" nocheck
kubectl get certificate -A
kubectl describe certificate shop-tls -n shop | sed -n '/Status/,$p'
kubectl get order,challenge -n shop
kubectl delete secret shop-tls -n shop        # cert-manager re-issues; ingress serves the old one until then
```
```bash title="Reload and verify" nocheck
sudo nginx -t && sudo systemctl reload nginx
echo | openssl s_client -connect shop.example.com:443 -servername shop.example.com 2>/dev/null | openssl x509 -noout -enddate
```
@check
After renewing the file, nginx still serves the old certificate. Why? || It loaded the certificate at start; it needs a reload.
@end

@concept Lab 6: inode exhaustion and file descriptor limits
@plain
Two quiet limits that look like a full disk or a broken network: no free inodes, and no free file descriptors.
@problem
`touch` fails with "No space left on device" while `df -h` shows free space, or a server logs "too many open files" and refuses connections.
@does
- **Inodes**: each file uses one. `df -i` shows usage. Find the directory with millions of files using `find /var -xdev -type f | cut -d/ -f1-4 | sort | uniq -c | sort -rn | head`. Fix by deleting old small files, for example PHP sessions or mail queue entries.
- **Descriptors**: `ls /proc/PID/fd | wc -l` against `grep 'open files' /proc/PID/limits`. Raise `LimitNOFILE` and fix leaks (unclosed sockets show as many `CLOSE_WAIT` in `ss -tan`).
- Both belong in alerts: inode percent and descriptors per process.
@diagram cmp
caption: Same error, different cause
cards:
  - {h: "No space left", kind: warn, items: ["df -h fine, df -i at 100 percent", "Too many small files"]}
  - {h: "Too many open files", kind: bad, items: ["Per process limit reached", "Leaked sockets, CLOSE_WAIT"]}
@h Check
```bash title="Inodes and descriptors" lab
df -i / | tail -1
pid=$$; echo "fds: $(ls /proc/$pid/fd | wc -l), limit: $(grep 'open files' /proc/$pid/limits | awk '{print $4}')"
ss -tan | awk 'NR>1 {c[$1]++} END {for (s in c) print s, c[s]}'
```
@check
Which state count rising points to a socket leak in the application? || CLOSE_WAIT, meaning the app has not closed sockets the peer closed.
@end

@concept After the incident: runbook and prevention
@plain
Every lab ends the same way: write down what happened, add a detection, and add the guard rail so it cannot recur silently.
@problem
Fixes known only to the person who was on call get re-discovered painfully at the next incident.
@does
- Add the symptom, the commands and the fix to a runbook linked from the alert.
- Convert findings into alerts (disk at 80 percent, memory growth trend, certificate days left, DNS latency) with an owner.
- Hold a blameless review: timeline, contributing factors, what slowed detection and recovery, action items with dates.
- Practise: schedule game days that replay these labs.
@diagram flow
caption: Closing the loop
nodes:
  - "Incident|resolved|bad"
  - "Runbook|commands and decisions|app"
  - "Alert|detect earlier|warn"
  - "Guard rail|limits, rotation, automation|ok"
  - "Game day|rehearse|cp"
@h Alert examples
```yaml title="Prometheus alerts for the five incidents"
groups:
  - name: host-incidents
    rules:
      - alert: DiskFillingFast
        expr: predict_linear(node_filesystem_avail_bytes{fstype!="tmpfs"}[1h], 4 * 3600) < 0
        for: 15m
        labels: {severity: warning}
      - alert: InodesLow
        expr: node_filesystem_files_free / node_filesystem_files < 0.10
        for: 10m
        labels: {severity: warning}
      - alert: MemoryGrowing
        expr: deriv(process_resident_memory_bytes[30m]) > 1e6
        for: 1h
        labels: {severity: warning}
      - alert: CertExpiring
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 21
        labels: {severity: warning}
      - alert: DnsSlow
        expr: probe_dns_lookup_time_seconds > 0.5
        for: 5m
        labels: {severity: warning}
```
@check
Which is better, an alert on 90 percent disk or on predicted exhaustion in 4 hours? || The prediction, because it measures the time you have left rather than a fixed level.
@end
