---
title: Monitoring tools, log parsing and reports
minutes: 55
objectives:
  - Expose custom metrics to Prometheus with prometheus_client
  - Push metrics from short lived batch jobs
  - Parse and summarise logs with regular expressions
  - Check certificate expiry and build CSV and pandas reports
---
Python is a good fit for the small monitoring glue that no off the shelf exporter covers: a business metric, a certificate date, a nightly summary. This section builds those pieces.

@concept Prometheus metric types
@plain
Prometheus scrapes numbers over HTTP. Each number is a **metric** of one of four types: counter, gauge, histogram or summary, and may have **labels** such as `region="eu-west-1"`.
@problem
Choosing the wrong type gives graphs and alerts that mislead. A counter used for "current queue size" cannot go down; a gauge used for "requests served" loses events between scrapes.
@does
- **Counter**: only goes up (requests, errors). Query it with `rate()`.
- **Gauge**: goes up and down (queue length, temperature, idle volumes).
- **Histogram**: counts observations in buckets (request duration) so you can compute percentiles with `histogram_quantile()`.
- Keep label values to a small, known set; one label per user id would create millions of series.
@diagram cmp
caption: Picking a metric type
cards:
  - {h: "Counter", kind: ok, items: ["Total errors since start", "Use rate() in queries", "Resets on restart"]}
  - {h: "Gauge", kind: info, items: ["Current value", "Idle volumes, queue size", "Set, inc and dec"]}
  - {h: "Histogram", kind: app, items: ["Durations and sizes", "Buckets chosen by you", "Percentiles in PromQL"]}
@h Defining metrics
```python title="metrics_defs.py" nocheck
from prometheus_client import Counter, Gauge, Histogram

SCANS = Counter("opskit_scans_total", "Number of scans run", ["region", "result"])
IDLE_VOLUMES = Gauge("opskit_idle_volumes", "Unattached EBS volumes", ["region"])
SCAN_SECONDS = Histogram("opskit_scan_seconds", "Scan duration", buckets=(0.5, 1, 2, 5, 10, 30))

with SCAN_SECONDS.time():
    IDLE_VOLUMES.labels(region="eu-west-1").set(7)
    SCANS.labels(region="eu-west-1", result="ok").inc()
```
@check
Which type for the number of idle volumes right now? || A gauge, because the value rises and falls.
@end

@concept Writing an exporter
@plain
An **exporter** is a small web server whose `/metrics` page lists current values in the Prometheus text format. `prometheus_client` serves the page; you update the metrics.
@problem
Prometheus can only scrape what is exposed. Cloud inventory, certificate dates and business counts need a bridge.
@does
- `start_http_server(9105)` serves `/metrics` in a background thread.
- Update gauges in a loop with a sleep, or better, in a **custom collector** that queries the source at scrape time.
- Keep each scrape fast; cache slow API results for a few minutes.
- Name metrics `<prefix>_<what>_<unit>`, for example `opskit_idle_volume_bytes`.
@diagram flow
caption: From cloud API to a graph
nodes:
  - "Cloud API|slow, rate limited|ext"
  - "Exporter loop|refresh every 5 minutes|app"
  - "/metrics|text format|info"
  - "Prometheus|scrape every 30 seconds|cp"
  - "Grafana and alerts|queries|ok"
@h A collector that builds the text format
```python title="exporter_core.py" lab
def render_metrics(idle_by_region: dict[str, int]) -> str:
    lines = [
        "# HELP opskit_idle_volumes Unattached EBS volumes",
        "# TYPE opskit_idle_volumes gauge",
    ]
    for region, count in sorted(idle_by_region.items()):
        lines.append(f'opskit_idle_volumes{{region="{region}"}} {count}')
    return "\n".join(lines) + "\n"


print(render_metrics({"eu-west-1": 7, "us-east-1": 2}))
```
```python title="exporter.py" nocheck
import time

import boto3
from prometheus_client import Gauge, start_http_server

IDLE = Gauge("opskit_idle_volumes", "Unattached EBS volumes", ["region"])
UP = Gauge("opskit_scan_success", "1 if the last scan worked")
REGIONS = ["eu-west-1", "us-east-1"]


def refresh() -> None:
    try:
        for region in REGIONS:
            ec2 = boto3.client("ec2", region_name=region)
            n = sum(len(p["Volumes"]) for p in ec2.get_paginator("describe_volumes").paginate(
                Filters=[{"Name": "status", "Values": ["available"]}]))
            IDLE.labels(region=region).set(n)
        UP.set(1)
    except Exception:
        UP.set(0)


if __name__ == "__main__":
    start_http_server(9105)
    while True:
        refresh()
        time.sleep(300)
```
@check
Why cache slow API results in an exporter? || Prometheus scrapes often, and each scrape must be fast and must not exhaust API rate limits.
@end

@concept Batch jobs and the Pushgateway
@plain
Prometheus pulls from long running processes. A job that runs for seconds and exits cannot be scraped, so it **pushes** its final numbers to a **Pushgateway**, which holds them for Prometheus to scrape.
@problem
Nightly backups and cleanups finish before Prometheus visits them, leaving no record of success, duration or last run time.
@does
- `push_to_gateway("pushgateway:9091", job="nightly_cleanup", registry=registry)` replaces the group's metrics.
- Always push a `last_success_timestamp` gauge and alert when it is too old.
- Delete groups of jobs you retire, or their stale values stay forever.
- For Kubernetes CronJobs with the Prometheus Operator, a Pushgateway is still the simple route.
@diagram seq
caption: A batch job reports
actors: ["Job|CronJob|app", "Pushgateway|holds last values|cp", "Prometheus|scrapes|cp"]
steps:
  - "0>0: run cleanup, count results | req"
  - "0>1: push metrics at the end | req"
  - "2>1: scrape /metrics | req"
  - "note 2..2: alert if timestamp too old"
@h Example
```python title="push_job.py" nocheck
import time

from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

registry = CollectorRegistry()
deleted = Gauge("cleanup_deleted_total", "Objects deleted in last run", registry=registry)
last_ok = Gauge("cleanup_last_success_timestamp_seconds", "Unix time of last success", registry=registry)

deleted.set(14)
last_ok.set(time.time())
push_to_gateway("pushgateway.monitoring.svc:9091", job="nightly_cleanup", registry=registry)
```
```yaml title="Alert rule for a missed run"
groups:
  - name: batch
    rules:
      - alert: CleanupNotRunning
        expr: time() - cleanup_last_success_timestamp_seconds > 129600
        for: 15m
        labels: {severity: warning}
        annotations:
          summary: "nightly cleanup has not succeeded for 36 hours"
```
@check
What should every batch job push besides counts? || A last success timestamp, so a missed run can trigger an alert.
@end

@concept Parsing logs with regular expressions
@plain
A log line is text with a pattern. A **regular expression** with named groups turns each line into fields you can count and group.
@problem
`grep | awk | sort | uniq` pipelines are hard to maintain and cannot compute percentiles or join with other data.
@does
- `re.compile(r"...(?P<status>\d{3})...")` once, then `.match(line)` per line.
- Named groups give a dictionary with `m.groupdict()`.
- Skip non matching lines but count them, so format changes are noticed.
- Parse timestamps with `datetime.strptime`; keep them timezone aware.
@diagram flow
caption: From text to records
nodes:
  - "Raw line|text|plain"
  - "Regex with names|groupdict|info"
  - "Typed record|int, float, datetime|app"
  - "Counters|by status or path|ok"
@h Access log line
```python title="parse_access.py" lab
import re
from datetime import datetime

LINE = re.compile(
    r'(?P<ip>\S+) \S+ \S+ \[(?P<ts>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>\S+) [^"]*" '
    r'(?P<status>\d{3}) (?P<size>\d+|-) "[^"]*" "(?P<agent>[^"]*)" (?P<ms>\d+)'
)


def parse(line: str) -> dict | None:
    m = LINE.match(line)
    if not m:
        return None
    d = m.groupdict()
    d["status"] = int(d["status"])
    d["size"] = 0 if d["size"] == "-" else int(d["size"])
    d["ms"] = int(d["ms"])
    d["ts"] = datetime.strptime(d["ts"], "%d/%b/%Y:%H:%M:%S %z")
    return d


sample = '10.0.0.5 - - [05/Mar/2026:10:15:32 +0000] "GET /api/items HTTP/1.1" 200 512 "-" "curl/8.0" 42'
print(parse(sample))
print(parse("garbage line"))
```
@check
Why count lines that do not match? || A sudden rise shows the log format changed or the parser is wrong.
@end

@concept Tool: an access log summariser
@plain
This tool reads a log file line by line and prints request counts per status, the slowest paths and the 95th percentile latency. It never loads the whole file into memory.
@problem
During an incident you need quick answers: what is failing, which endpoint is slow, since when.
@does
- Streams lines, parses, aggregates with `Counter` and `defaultdict`.
- Computes percentiles with `statistics.quantiles`.
- Prints a short text report, or JSON for other tools.
- Handles gzip files by opening with `gzip.open` when the name ends with `.gz`.
@diagram flow
caption: Summariser pipeline
nodes:
  - "Open file|plain or gzip|app"
  - "Parse each line|skip bad ones|info"
  - "Aggregate|status, path, latency|env"
  - "Report|text or JSON|ok"
@h Complete tool
```python title="logsum.py" lab
from __future__ import annotations

import gzip
import io
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

LINE = re.compile(r'"(?P<method>[A-Z]+) (?P<path>[^ ?]+)[^"]*" (?P<status>\d{3}) \S+ (?P<ms>\d+)$')


def open_text(path: Path):
    if path.suffix == ".gz":
        return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


def summarise(lines) -> dict:
    status = Counter()
    by_path: dict[str, list[int]] = defaultdict(list)
    bad = 0
    for line in lines:
        m = LINE.search(line.rstrip())
        if not m:
            bad += 1
            continue
        status[m["status"]] += 1
        by_path[m["path"]].append(int(m["ms"]))
    all_ms = [ms for v in by_path.values() for ms in v]
    p95 = statistics.quantiles(all_ms, n=20)[18] if len(all_ms) >= 2 else (all_ms[0] if all_ms else 0)
    slowest = sorted(((statistics.mean(v), p, len(v)) for p, v in by_path.items()), reverse=True)[:3]
    return {"status": dict(status), "p95_ms": p95, "unparsed": bad,
            "slowest": [{"path": p, "avg_ms": round(a), "hits": n} for a, p, n in slowest]}


SAMPLE = """\
1.1.1.1 - - [05/Mar/2026:10:00:00 +0000] "GET /api/items HTTP/1.1" 200 10 40
1.1.1.1 - - [05/Mar/2026:10:00:01 +0000] "GET /api/items HTTP/1.1" 200 10 60
1.1.1.1 - - [05/Mar/2026:10:00:02 +0000] "POST /api/orders HTTP/1.1" 500 5 900
1.1.1.1 - - [05/Mar/2026:10:00:03 +0000] "GET /health HTTP/1.1" 200 2 3
not a log line
""".splitlines()

print(summarise(SAMPLE))
```
@check
Why use quantiles for the 95th percentile instead of the average? || The average hides slow outliers; the percentile shows what the slowest 5 percent experience.
@end

@concept Tool: a certificate expiry checker
@plain
The tool connects to each host, reads the TLS certificate, and reports days until it expires, so expiring certificates are found before users find them.
@problem
Expired certificates are a top cause of avoidable outages, and they are easy to forget when issued by hand or by ageing automation.
@does
- `ssl.create_default_context()` plus `getpeercert()` returns the certificate dictionary with `notAfter`.
- `ssl.cert_time_to_seconds` converts the date text to epoch seconds.
- Exit code 3 when any certificate expires within the warning window, so cron and CI can alert.
- Run checks in a thread pool; set a short socket timeout.
@diagram flow
caption: Expiry check
nodes:
  - "Host list|from file or arguments|plain"
  - "TLS connect|timeout 5s|app"
  - "notAfter|certificate field|info"
  - "Days left|compare to threshold|env"
  - "Exit 0 or 3|alert signal|ok"
@h The parts that run offline
```python title="certcheck_core.py" lab
import ssl
import time

WARN_DAYS = 21


def days_left(not_after: str, now: float | None = None) -> float:
    expires = ssl.cert_time_to_seconds(not_after)
    return (expires - (now if now is not None else time.time())) / 86400


def classify(days: float) -> str:
    if days < 0:
        return "EXPIRED"
    return "WARN" if days < WARN_DAYS else "OK"


now = ssl.cert_time_to_seconds("Jan  1 00:00:00 2026 GMT")
for text in ("Jan 10 00:00:00 2026 GMT", "Feb  1 00:00:00 2026 GMT", "Dec 25 00:00:00 2025 GMT"):
    d = days_left(text, now)
    print(f"{text}  {d:6.1f} days  {classify(d)}")
```
```python title="certcheck.py" nocheck
import socket
import ssl
import sys
from concurrent.futures import ThreadPoolExecutor

from certcheck_core import classify, days_left


def check(host: str, port: int = 443) -> tuple[str, float | None, str]:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as tls:
                days = days_left(tls.getpeercert()["notAfter"])
        return host, days, classify(days)
    except (OSError, ssl.SSLError) as exc:
        return host, None, f"ERROR {type(exc).__name__}"


if __name__ == "__main__":
    hosts = sys.argv[1:] or ["example.com"]
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(check, hosts))
    for host, days, state in results:
        print(f"{host:35} {'-' if days is None else f'{days:6.1f}'} {state}")
    sys.exit(3 if any(s != "OK" for _, _, s in results) else 0)
```
@check
What exit code design makes the tool useful in cron or CI? || A distinct non zero code when something expires soon, so schedulers can alert on it.
@end

@concept Reports with csv and pandas
@plain
`csv` is enough for simple tables. `pandas` adds a table object (a DataFrame) that can filter, group, join and pivot thousands of rows in one line each, then write CSV, Excel or HTML.
@problem
Loops with dictionaries become unreadable once you need "total per team per month, top five, joined with the owner list".
@does
- `pd.DataFrame(list_of_dicts)` or `pd.read_csv(path)` creates a table.
- `df[df.state == "available"]`, `df.groupby("team")["cost"].sum()`, `df.sort_values("cost", ascending=False).head(5)`.
- `pd.merge(a, b, on="account_id", how="left")` joins tables.
- `df.to_csv(path, index=False)` and `df.to_markdown()` write reports.
@diagram flow
caption: A report from raw rows
nodes:
  - "Rows|list of dicts|app"
  - "DataFrame|table in memory|info"
  - "groupby and sort|summaries|env"
  - "to_csv or to_html|share|ok"
@h Example
```python title="pandas_report.py" nocheck
import pandas as pd

rows = [
    {"team": "platform", "service": "ec2", "cost": 1200.50},
    {"team": "platform", "service": "s3", "cost": 310.00},
    {"team": "data", "service": "ec2", "cost": 2210.75},
    {"team": "data", "service": "s3", "cost": 980.20},
]
df = pd.DataFrame(rows)
by_team = df.groupby("team", as_index=False)["cost"].sum().sort_values("cost", ascending=False)
by_team["share_pct"] = (by_team["cost"] / by_team["cost"].sum() * 100).round(1)
print(by_team.to_string(index=False))
by_team.to_csv("cost_by_team.csv", index=False)
```
```python title="Same result with the standard library" lab
from collections import defaultdict
from decimal import Decimal

rows = [("platform", "1200.50"), ("platform", "310.00"), ("data", "2210.75"), ("data", "980.20")]
totals: dict[str, Decimal] = defaultdict(Decimal)
for team, cost in rows:
    totals[team] += Decimal(cost)
grand = sum(totals.values())
for team, total in sorted(totals.items(), key=lambda kv: kv[1], reverse=True):
    print(f"{team:10} {total:>10} {total / grand * 100:5.1f}%")
```
@choose csv or pandas
csv module | small outputs, zipapps and Lambda size limits | you need joins, pivots or statistics
pandas | analysis with grouping and joins | the tool must stay tiny and fast to start
Decimal in plain Python | money that must be exact | millions of rows
@check
When is pandas not worth it? || When the script only filters and writes a few hundred rows, or must stay small and quick to start.
@end

@concept Alerting from scripts
@plain
A script can notify people: post to Slack or Teams through an incoming webhook, send email, or open a ticket. The art is to alert on change and on things someone must act on.
@problem
A tool that posts every run trains people to ignore it; a tool that stays silent on failure is worse.
@does
- Post JSON with a timeout and a retry; failure to notify is itself logged.
- Include what, where, how bad and what to do, with a link to the dashboard or runbook.
- Deduplicate: store the last alert state and notify only when it changes, plus a daily reminder.
- Keep webhook URLs in secrets, never in code or logs.
@diagram flow
caption: Alert only on change
nodes:
  - "Check result|OK, WARN, FAIL|app"
  - "Compare with last state|stored file or tag|info"
  - "Changed or reminder due?|decision|warn"
  - "Post to webhook|message with link|ok"
@h Decision logic and sender
```python title="alert_state.py" lab
import json
import tempfile
import time
from pathlib import Path

REMIND_AFTER = 24 * 3600


def should_notify(state_path: Path, key: str, status: str, now: float) -> bool:
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    last = state.get(key, {"status": "OK", "at": 0})
    changed = last["status"] != status
    reminder = status != "OK" and now - last["at"] > REMIND_AFTER
    if changed or reminder:
        state[key] = {"status": status, "at": now}
        state_path.write_text(json.dumps(state))
        return True
    return False


p = Path(tempfile.mkdtemp()) / "state.json"
t = time.time()
print(should_notify(p, "cert:example.com", "WARN", t))        # first warning
print(should_notify(p, "cert:example.com", "WARN", t + 60))   # same state, quiet
print(should_notify(p, "cert:example.com", "OK", t + 120))    # recovered
```
```python title="slack.py" nocheck
import os

import requests


def notify(text: str) -> None:
    url = os.environ["SLACK_WEBHOOK_URL"]
    r = requests.post(url, json={"text": text}, timeout=10)
    r.raise_for_status()


notify(":warning: cert for example.com expires in 12 days. Runbook: https://wiki.example.com/certs")
```
@check
Why alert on change plus a reminder? || Changes avoid noise, and the reminder prevents a long standing problem from being forgotten.
@end
