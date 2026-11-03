---
title: Shipping scripts as tools and complete ops tools
minutes: 60
objectives:
  - Package a script as a container image, a zipapp or a Lambda function
  - Schedule a tool with cron or a Kubernetes CronJob
  - Build an idle EBS volume finder and a tag auditor with testable cores
  - Build an S3 storage reporter and a safe two phase snapshot cleaner
---
A script on your laptop helps one person. A tool that others can install, schedule and trust helps a team. The first half of this section covers how to ship; the second half finishes with four complete tools that follow the same pattern: a pure core that is tested, and a thin cloud layer around it.

@concept Containers for tools
@plain
A container image bundles the tool, Python and its libraries. Kubernetes CronJobs, CI jobs and servers can run it with no Python setup.
@problem
Hosts differ in Python versions and installed libraries. Scheduled jobs on shared runners break when someone upgrades the system.
@does
- Use a slim base, install from the lock file, run as a non root user.
- Multi stage builds keep compilers out of the final image.
- `ENTRYPOINT ["opskit"]` makes `docker run image scan --days 14` natural.
- Pin the base image by digest in CI, and rebuild regularly for security patches.
@diagram layers
caption: Image layers for a tool
layers:
  - {label: "Final image", nodes: ["python slim base|small attack surface|env", "venv with locked deps|from uv.lock|app", "opskit wheel|your code|app", "non root user|UID 10001|ok"]}
  - {label: "Builder stage", nodes: ["uv and build tools|discarded|plain"]}
@h Dockerfile
```docker title="Dockerfile"
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /src
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev

FROM python:3.12-slim
RUN useradd --uid 10001 --create-home ops
COPY --from=build /src/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" PYTHONUNBUFFERED=1
USER 10001
ENTRYPOINT ["opskit"]
CMD ["--help"]
```
@check
Why run as a non root user? || A compromised tool then has far fewer permissions inside and outside the container.
@end

@concept zipapps, one file to copy
@plain
`python -m zipapp` packs a folder of Python code into one executable `.pyz` file. Copy it to a server that has Python and run it.
@problem
Bastion hosts and air gapped servers cannot install packages or pull images, yet need your tool.
@does
- `python -m zipapp src -m "opskit.cli:main" -p "/usr/bin/env python3" -o opskit.pyz`.
- Pure Python dependencies can be installed into the folder first with `pip install -t src/ ...`.
- Compiled libraries (numpy, cryptography) do not work reliably inside a zip; use `shiv` or `pex` or a container for those.
- Keep it to argparse and the standard library for the easiest result.
@diagram flow
caption: Building a .pyz
numbered: true
nodes:
  - "Source folder|code and pure deps|app"
  - "python -m zipapp|packs and sets entry|info"
  - "opskit.pyz|one executable file|env"
  - "scp and run|needs Python only|ok"
@h Commands and a self contained build
```bash title="Build and run" lab
set -e
d=$(mktemp -d)
mkdir -p "$d/src/hello"
cat > "$d/src/hello/__init__.py" <<'PY'
PY
cat > "$d/src/hello/cli.py" <<'PY'
import sys
def main():
    print("hello from a zipapp", sys.argv[1:])
PY
python3 -m zipapp "$d/src" -m "hello.cli:main" -o "$d/hello.pyz"
python3 "$d/hello.pyz" one two
rm -rf "$d"
```
@check
Why are compiled dependencies a problem in zipapps? || Shared libraries cannot be loaded from inside a zip, so such packages fail or need special tools.
@end

@concept Lambda packaging
@plain
AWS Lambda runs a function on demand. For Python you upload a zip (up to 50 MB zipped, 250 MB unzipped) or a container image (up to 10 GB). The function needs a **handler** that receives an event and context.
@problem
Small periodic checks (a certificate checker, a tag auditor) do not need a server running all day. Lambda with an EventBridge schedule costs almost nothing.
@does
- Handler signature: `def handler(event, context):`; set `Handler` to `module.handler`.
- boto3 is already in the managed runtime; include only other dependencies.
- Install dependencies for the Lambda platform: `pip install --platform manylinux2014_x86_64 --only-binary=:all: --target build/ -r requirements.txt` then zip `build/`.
- Give the function an execution role with least privilege, set memory, timeout and reserved concurrency.
- Initialise clients outside the handler so warm invocations reuse them.
@diagram flow
caption: Scheduled Lambda
nodes:
  - "EventBridge schedule|rate 1 day|cp"
  - "Lambda function|handler(event, context)|app"
  - "AWS APIs|read only role|ext"
  - "SNS or Slack|only when findings|ok"
@h Handler pattern
```python title="lambda_function.py" nocheck
import json
import os

import boto3

ec2 = boto3.client("ec2")          # created once per container, reused when warm
sns = boto3.client("sns")
TOPIC = os.environ["ALERT_TOPIC_ARN"]


def handler(event, context):
    found = []
    for page in ec2.get_paginator("describe_volumes").paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]):
        found += [v["VolumeId"] for v in page["Volumes"]]
    if found:
        sns.publish(TopicArn=TOPIC, Subject="Idle EBS volumes",
                    Message=json.dumps({"count": len(found), "ids": found[:50]}))
    return {"idle": len(found)}
```
```bash title="Build the zip" nocheck
pip install --platform manylinux2014_x86_64 --only-binary=:all: --target build/ -r requirements.txt
cp lambda_function.py build/
(cd build && zip -qr ../function.zip .)
aws lambda update-function-code --function-name idle-volumes --zip-file fileb://function.zip
```
@check
Why create boto3 clients outside the handler? || Warm invocations reuse them, which saves setup time on every call.
@end

@concept Scheduling with cron and Kubernetes CronJobs
@plain
A scheduler runs your tool at set times. Use a CronJob in Kubernetes, EventBridge for Lambda, or a systemd timer on a host, and make sure runs cannot overlap.
@problem
A hand started tool is forgotten. A cron entry with no logging, locking or timeout fails silently and overlapping runs corrupt state.
@does
- CronJob fields: `schedule`, `concurrencyPolicy: Forbid`, `startingDeadlineSeconds`, `activeDeadlineSeconds`, `backoffLimit`, history limits.
- Give the pod a ServiceAccount; map it to a cloud role with IRSA or workload identity.
- Exit non zero on failure so the Job is marked failed; push a last success metric.
- Always set resource requests and `ttlSecondsAfterFinished` to clean finished pods.
@diagram flow
caption: A CronJob run
nodes:
  - "Schedule 02:00|cron expression|cp"
  - "Job|one run, no overlap|app"
  - "Pod|image and service account|env"
  - "Exit code|0 or failure|info"
  - "Metrics and alert|last success|ok"
@h Manifest
```yaml title="cronjob.yaml"
apiVersion: batch/v1
kind: CronJob
metadata:
  name: idle-volumes
spec:
  schedule: "0 2 * * *"
  timeZone: "Etc/UTC"
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 900
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          serviceAccountName: opskit
          restartPolicy: Never
          containers:
            - name: opskit
              image: registry.example.com/ops/opskit:1.2.0
              args: ["idle-volumes", "--region", "eu-west-1", "--format", "json"]
              resources:
                requests: {cpu: 50m, memory: 128Mi}
                limits: {memory: 256Mi}
              securityContext:
                runAsNonRoot: true
                allowPrivilegeEscalation: false
                readOnlyRootFilesystem: true
                capabilities: {drop: ["ALL"]}
```
@check
What does concurrencyPolicy Forbid do? || It skips a new run while the previous one is still running.
@end

@concept Tool: idle EBS volume finder
@plain
Finds EBS volumes in the `available` state (not attached) older than N days, estimates their monthly cost and prints a report. Read only by default.
@problem
Unattached volumes keep billing after instances are deleted. Across accounts they add up to real money.
@does
- Pure function `find_idle(volumes, now, min_age_days, price_per_gb)` decides; AWS calls only fetch data.
- Excludes volumes tagged `keep=true`.
- Prices come from a dictionary by volume type (approximate; adjust to your region).
- Output as table or JSON; exit 3 when anything is found.
@diagram flow
caption: Idle volume finder
nodes:
  - "describe_volumes|status available|app"
  - "find_idle|age, tags, cost|info"
  - "Report|table or JSON|env"
  - "Exit 3 if found|for CI or cron|ok"
@h Core (runs offline)
```python title="idle_ebs.py" lab
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PRICE_GB_MONTH = {"gp3": 0.08, "gp2": 0.10, "io1": 0.125, "io2": 0.125, "st1": 0.045, "sc1": 0.015}


@dataclass(frozen=True)
class IdleVolume:
    volume_id: str
    size_gb: int
    vol_type: str
    age_days: int
    monthly_cost: float


def find_idle(volumes: list[dict], now: datetime, min_age_days: int = 14) -> list[IdleVolume]:
    out = []
    for v in volumes:
        if v["State"] != "available":
            continue
        tags = {t["Key"]: t["Value"] for t in v.get("Tags", [])}
        if tags.get("keep", "").lower() == "true":
            continue
        age = (now - v["CreateTime"]).days
        if age < min_age_days:
            continue
        price = PRICE_GB_MONTH.get(v["VolumeType"], 0.10)
        out.append(IdleVolume(v["VolumeId"], v["Size"], v["VolumeType"], age, round(v["Size"] * price, 2)))
    return sorted(out, key=lambda x: x.monthly_cost, reverse=True)


now = datetime(2026, 3, 1, tzinfo=timezone.utc)
sample = [
    {"VolumeId": "vol-1", "State": "available", "Size": 500, "VolumeType": "gp3", "CreateTime": now - timedelta(days=90)},
    {"VolumeId": "vol-2", "State": "available", "Size": 50, "VolumeType": "gp2", "CreateTime": now - timedelta(days=3)},
    {"VolumeId": "vol-3", "State": "available", "Size": 100, "VolumeType": "gp3", "CreateTime": now - timedelta(days=40),
     "Tags": [{"Key": "keep", "Value": "true"}]},
    {"VolumeId": "vol-4", "State": "in-use", "Size": 20, "VolumeType": "gp3", "CreateTime": now - timedelta(days=200)},
]
found = find_idle(sample, now)
for f in found:
    print(f)
print("total per month:", round(sum(f.monthly_cost for f in found), 2))
```
@h AWS layer
```python title="idle_ebs_cli.py" nocheck
import json
import sys
from datetime import datetime, timezone

import boto3

from idle_ebs import find_idle


def fetch(region: str) -> list[dict]:
    ec2 = boto3.client("ec2", region_name=region)
    pager = ec2.get_paginator("describe_volumes")
    return [v for page in pager.paginate(Filters=[{"Name": "status", "Values": ["available"]}]) for v in page["Volumes"]]


if __name__ == "__main__":
    region = sys.argv[1] if len(sys.argv) > 1 else "eu-west-1"
    idle = find_idle(fetch(region), datetime.now(timezone.utc))
    print(json.dumps([i.__dict__ for i in idle], indent=2))
    sys.exit(3 if idle else 0)
```
@check
Why is the decision function separate from the AWS call? || It can be tested with sample data and never needs credentials.
@end

@concept Tool: tag auditor
@plain
Checks that every EC2 instance, volume and bucket carries required tags (Owner, Env, CostCenter) with allowed values, and reports the violations per owner or account.
@problem
Without consistent tags, cost cannot be allocated, orphaned resources cannot be traced, and policies cannot target environments.
@does
- A policy dictionary lists required keys and, optionally, allowed values or a regex.
- `audit(resources, policy)` returns a list of violations, each naming the resource and the problem.
- The AWS layer can use the Resource Groups Tagging API `get_resources` (paginated) to see many resource types in one call.
- Results can feed a report, a chat message, or an auto tagging step.
@diagram flow
caption: Tag audit
nodes:
  - "get_resources|all tagged resources|app"
  - "Policy|required keys and values|cp"
  - "audit|violations list|info"
  - "Report by owner|who must fix|ok"
@h Core (runs offline)
```python title="tag_audit.py" lab
from __future__ import annotations

import re

POLICY = {
    "Owner": {"pattern": r"^[a-z0-9._-]+@example\.com$"},
    "Env": {"allowed": {"dev", "staging", "prod"}},
    "CostCenter": {"pattern": r"^\d{4}$"},
}


def audit(resources: list[dict], policy: dict = POLICY) -> list[tuple[str, str]]:
    problems = []
    for r in resources:
        tags = {t["Key"]: t["Value"] for t in r.get("Tags", [])}
        for key, rule in policy.items():
            if key not in tags:
                problems.append((r["ResourceARN"], f"missing {key}"))
                continue
            value = tags[key]
            if "allowed" in rule and value not in rule["allowed"]:
                problems.append((r["ResourceARN"], f"{key}={value!r} not allowed"))
            if "pattern" in rule and not re.match(rule["pattern"], value):
                problems.append((r["ResourceARN"], f"{key}={value!r} bad format"))
    return problems


sample = [
    {"ResourceARN": "arn:aws:ec2:eu-west-1:1:instance/i-1",
     "Tags": [{"Key": "Owner", "Value": "ana@example.com"}, {"Key": "Env", "Value": "prod"}, {"Key": "CostCenter", "Value": "1234"}]},
    {"ResourceARN": "arn:aws:ec2:eu-west-1:1:volume/vol-9",
     "Tags": [{"Key": "Env", "Value": "production"}]},
]
for arn, issue in audit(sample):
    print(f"{arn}: {issue}")
```
@h AWS layer
```python title="tag_audit_cli.py" nocheck
import boto3

from tag_audit import audit

tagging = boto3.client("resourcegroupstaggingapi", region_name="eu-west-1")
resources = []
for page in tagging.get_paginator("get_resources").paginate(
        ResourceTypeFilters=["ec2:instance", "ec2:volume", "s3"]):
    resources += page["ResourceTagMappingList"]
for arn, issue in audit(resources):
    print(arn, issue)
```
:::note
`get_resources` only returns resources that have or once had tags. A resource that never had any tag may not appear. Cross check with `describe_instances` for full coverage.
:::
@check
What does the policy dictionary let you change without editing code? || Required keys, allowed values and formats, so the rules can come from a config file.
@end

@concept Tool: S3 storage reporter
@plain
Sums object sizes per bucket and prefix, and estimates cost by storage class, so you see where data is and which prefix to put under a lifecycle rule.
@problem
The S3 console cannot group by prefix cheaply, and forgotten log or backup prefixes grow quietly for years.
@does
- `list_objects_v2` paginated, aggregating `Size` and `StorageClass` into a dictionary.
- Approximate monthly prices per GB by class (Standard, Standard-IA, Glacier Instant and so on); update for your region.
- For big buckets prefer S3 Storage Lens or S3 Inventory; listing every object costs requests and time.
- Output sorted by cost with a total.
@diagram flow
caption: Storage report
nodes:
  - "list_objects_v2|paginated|app"
  - "Group by prefix and class|sum bytes|info"
  - "Price per class|approximate|env"
  - "Sorted report|biggest first|ok"
@h Core (runs offline)
```python title="s3_report.py" lab
from __future__ import annotations

from collections import defaultdict

PRICE_GB_MONTH = {"STANDARD": 0.023, "STANDARD_IA": 0.0125, "GLACIER_IR": 0.004, "GLACIER": 0.0036, "DEEP_ARCHIVE": 0.00099}
GIB = 1024**3


def report(objects: list[dict], depth: int = 1) -> list[tuple[str, float, float]]:
    sizes: dict[tuple[str, str], int] = defaultdict(int)
    for o in objects:
        prefix = "/".join(o["Key"].split("/")[:depth]) + "/"
        sizes[(prefix, o.get("StorageClass", "STANDARD"))] += o["Size"]
    by_prefix: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for (prefix, cls), size in sizes.items():
        gib = size / GIB
        by_prefix[prefix][0] += gib
        by_prefix[prefix][1] += gib * PRICE_GB_MONTH.get(cls, 0.023)
    return sorted(((p, g, c) for p, (g, c) in by_prefix.items()), key=lambda x: x[2], reverse=True)


sample = [
    {"Key": "logs/2025/a.gz", "Size": 800 * GIB // 10, "StorageClass": "STANDARD"},
    {"Key": "logs/2026/b.gz", "Size": 300 * GIB // 10, "StorageClass": "STANDARD"},
    {"Key": "backups/db1.dump", "Size": 120 * GIB, "StorageClass": "GLACIER"},
    {"Key": "images/x.png", "Size": 5 * GIB, "StorageClass": "STANDARD_IA"},
]
total = 0.0
for prefix, gib, cost in report(sample):
    total += cost
    print(f"{prefix:12} {gib:8.1f} GiB  ${cost:7.2f}/month")
print(f"total ${total:.2f}/month")
```
@h AWS layer
```python title="s3_report_cli.py" nocheck
import sys

import boto3

from s3_report import report

bucket = sys.argv[1]
s3 = boto3.client("s3")
objects = []
for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
    objects += [{"Key": o["Key"], "Size": o["Size"], "StorageClass": o.get("StorageClass", "STANDARD")}
                for o in page.get("Contents", [])]
for prefix, gib, cost in report(objects):
    print(f"{prefix:30} {gib:10.1f} GiB ${cost:8.2f}")
```
@check
What is a better source than listing for very large buckets? || S3 Inventory or Storage Lens, which provide the data without millions of list requests.
@end

@concept Tool: two phase snapshot cleaner
@plain
Old EBS snapshots cost money. The cleaner works in two phases: first it tags candidates with a deletion date, and only a later run deletes those whose date has passed and that are not in use by an AMI.
@problem
Deleting directly is irreversible. A mistaken filter could remove the only backup.
@does
- Phase one tags `delete-after=YYYY-MM-DD` (7 days ahead) on snapshots older than the retention period; owners have time to object by removing the tag or adding `keep=true`.
- Phase two deletes only snapshots whose tag date has passed, using `DryRun` unless `--apply`.
- Skips snapshots used by AMIs (check `describe_images(Owners=["self"])` block device mappings).
- Logs every action with the snapshot id, so there is an audit trail.
@diagram flow
caption: Two phases with a grace period
numbered: true
nodes:
  - "Find old snapshots|older than retention|info"
  - "Tag delete-after|7 days ahead|env"
  - "Owners can object|remove tag or keep=true|warn"
  - "Delete expired tags|dry run unless apply|ok"
@h Core (runs offline)
```python title="snapshot_clean.py" lab
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

GRACE_DAYS = 7


def plan(snapshots: list[dict], ami_snapshot_ids: set[str], today: date, retention_days: int = 180):
    to_tag, to_delete = [], []
    for s in snapshots:
        sid = s["SnapshotId"]
        tags = {t["Key"]: t["Value"] for t in s.get("Tags", [])}
        if tags.get("keep", "").lower() == "true" or sid in ami_snapshot_ids:
            continue
        marker = tags.get("delete-after")
        if marker:
            if date.fromisoformat(marker) <= today:
                to_delete.append(sid)
            continue
        age = (today - s["StartTime"].date()).days
        if age > retention_days:
            to_tag.append((sid, (today + timedelta(days=GRACE_DAYS)).isoformat()))
    return to_tag, to_delete


today = date(2026, 3, 1)
old = datetime(2025, 1, 1, tzinfo=timezone.utc)
snaps = [
    {"SnapshotId": "snap-1", "StartTime": old},
    {"SnapshotId": "snap-2", "StartTime": old, "Tags": [{"Key": "delete-after", "Value": "2026-02-20"}]},
    {"SnapshotId": "snap-3", "StartTime": old, "Tags": [{"Key": "keep", "Value": "true"}]},
    {"SnapshotId": "snap-4", "StartTime": old},
    {"SnapshotId": "snap-5", "StartTime": datetime(2026, 2, 1, tzinfo=timezone.utc)},
]
tag, delete = plan(snaps, ami_snapshot_ids={"snap-4"}, today=today)
print("tag:", tag)
print("delete:", delete)
```
@h AWS layer
```python title="snapshot_clean_cli.py" nocheck
import sys
from datetime import date

import boto3
from botocore.exceptions import ClientError

from snapshot_clean import plan

apply = "--apply" in sys.argv
ec2 = boto3.client("ec2", region_name="eu-west-1")
snaps = [s for p in ec2.get_paginator("describe_snapshots").paginate(OwnerIds=["self"]) for s in p["Snapshots"]]
ami_snaps = {
    bd["Ebs"]["SnapshotId"]
    for p in ec2.get_paginator("describe_images").paginate(Owners=["self"])
    for img in p["Images"] for bd in img.get("BlockDeviceMappings", []) if "Ebs" in bd and "SnapshotId" in bd["Ebs"]
}
to_tag, to_delete = plan(snaps, ami_snaps, date.today())

for sid, when in to_tag:
    print("tagging", sid, "delete-after", when)
    if apply:
        ec2.create_tags(Resources=[sid], Tags=[{"Key": "delete-after", "Value": when}])

for sid in to_delete:
    try:
        ec2.delete_snapshot(SnapshotId=sid, DryRun=not apply)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "DryRunOperation":
            raise
    print("would delete" if not apply else "deleted", sid)
```
:::danger
Run with dry run first, in a test account, and review the output before using `--apply`. Also remember that snapshots are incremental; deleting one may not free as much space as its size suggests.
:::
@check
What gives owners a chance to object before deletion? || The delete-after tag with a grace period; removing it or adding keep=true protects the snapshot.
@end
