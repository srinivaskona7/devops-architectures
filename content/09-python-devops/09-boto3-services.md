---
title: boto3 in practice with S3, EC2, IAM and costs
minutes: 55
objectives:
  - Work with S3 objects safely including uploads and presigned URLs
  - Find and filter EC2 resources and act on them with dry runs
  - Review IAM users and keys programmatically
  - Query Cost Explorer and use CloudWatch metrics and SSM parameters
---
These are the calls that fill real operations scripts. Every example uses the current client API, paginates properly, and treats changes as opt in.

@concept S3 listing and reading objects
@plain
S3 stores objects under keys inside buckets. `list_objects_v2` returns up to 1,000 keys per call, so listing always needs a paginator.
@problem
Looping once over `list_objects_v2` misses most of a large bucket, and downloading whole objects into memory can crash a small container.
@does
- `Prefix` and `Delimiter="/"` emulate folders; `CommonPrefixes` lists the sub folders.
- `get_object(...)["Body"]` is a stream; read in chunks or use `iter_lines()`.
- `head_object` returns size, metadata and last modified without downloading.
- `download_file` and `upload_file` use the transfer manager (multipart, retries, threads).
@diagram flow
caption: Safe listing and reading
nodes:
  - "Paginator|list_objects_v2|app"
  - "Filter keys|prefix and age|info"
  - "head_object|check size first|env"
  - "Stream Body|chunks or lines|ok"
@h Examples
```python title="s3_list.py" nocheck
import boto3

s3 = boto3.client("s3")


def old_objects(bucket: str, prefix: str, older_than_days: int):
    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=older_than_days)
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                yield obj["Key"], obj["Size"]


total = 0
for key, size in old_objects("my-logs", "app/2025/", 90):
    total += size
print(f"{total / 1024**3:.2f} GiB older than 90 days")

body = s3.get_object(Bucket="my-logs", Key="app/2026/01/01.log")["Body"]
for line in body.iter_lines():
    if b"ERROR" in line:
        print(line.decode("utf-8", "replace"))
```
@check
Why use Delimiter="/"? || It groups keys by folder like prefix so CommonPrefixes lists sub folders without listing every object.
@end

@concept S3 uploads, presigned URLs and safety
@plain
`upload_file` uploads big files in parts. A **presigned URL** is a temporary link that lets someone without AWS credentials download or upload one specific object.
@problem
Sharing a report would otherwise mean making a bucket public or sending long lived keys. Public buckets are a classic data leak.
@does
- `s3.upload_file(path, bucket, key, ExtraArgs={"ServerSideEncryption": "aws:kms"})`.
- `generate_presigned_url("get_object", Params={...}, ExpiresIn=3600)` signs locally with no API call; it works only as long as the signing credentials do.
- Block public access at account level; keep presigned lifetimes short.
- `put_object` with `ContentType` makes browsers display files correctly.
@diagram seq
caption: Sharing a report without making it public
actors: ["Tool|has IAM role|app", "S3|private bucket|ext", "Reader|no AWS access|ext"]
steps:
  - "0>1: upload_file report.html | req"
  - "0>0: sign URL, expires in 1 hour | tls"
  - "0>2: send the link | resp"
  - "2>1: GET with signature | req"
  - "1>2: object bytes | resp"
@h Example
```python title="s3_share.py" nocheck
import boto3

s3 = boto3.client("s3")
s3.upload_file(
    "report.html", "ops-reports", "weekly/2026-w10.html",
    ExtraArgs={"ContentType": "text/html", "ServerSideEncryption": "AES256"},
)
url = s3.generate_presigned_url(
    "get_object",
    Params={"Bucket": "ops-reports", "Key": "weekly/2026-w10.html"},
    ExpiresIn=3600,
)
print(url)
```
:::warn
A presigned URL made with temporary role credentials stops working when those credentials expire, even if ExpiresIn is longer.
:::
@check
Does generating a presigned URL call AWS? || No, it is signed locally using your credentials.
@end

@concept EC2 describe calls and filters
@plain
`describe_instances`, `describe_volumes` and similar calls list resources. Filters run on the AWS side, so you transfer less and avoid client side loops.
@problem
Fetching every instance in an account and filtering in Python is slow and hits throttles. Nested response shapes (`Reservations` then `Instances`) also trip people up.
@does
- `Filters=[{"Name": "tag:Env", "Values": ["prod"]}, {"Name": "instance-state-name", "Values": ["running"]}]`.
- Tags arrive as a list of `{"Key", "Value"}` dictionaries; convert once to a dict.
- Use a paginator for all describe calls.
- One client covers one region; loop regions explicitly.
@diagram flow
caption: Shape of describe_instances
nodes:
  - "Page|one API response|plain"
  - "Reservations|list|info"
  - "Instances|list inside each|app"
  - "Tags|list of Key and Value|env"
@h Example
```python title="ec2_list.py" nocheck
import boto3


def tags_to_dict(tags: list[dict[str, str]] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in tags or []}


def running_instances(ec2):
    pager = ec2.get_paginator("describe_instances")
    flt = [{"Name": "instance-state-name", "Values": ["running"]}]
    for page in pager.paginate(Filters=flt):
        for res in page["Reservations"]:
            for inst in res["Instances"]:
                yield inst["InstanceId"], inst["InstanceType"], tags_to_dict(inst.get("Tags"))


ec2 = boto3.client("ec2", region_name="eu-west-1")
for iid, itype, tags in running_instances(ec2):
    print(iid, itype, tags.get("Owner", "UNOWNED"))
```
```python title="Helper that runs offline" lab
def tags_to_dict(tags):
    return {t["Key"]: t["Value"] for t in tags or []}


print(tags_to_dict([{"Key": "Owner", "Value": "platform"}]), tags_to_dict(None))
```
@check
Why filter on the server side? || Less data transfers, fewer throttles, and simpler code.
@end

@concept DryRun and safe changes on EC2
@plain
Many EC2 write calls accept `DryRun=True`. AWS checks permissions and parameters and replies with an error code instead of acting: `DryRunOperation` means "this would have worked".
@problem
Scripts that delete or stop resources can do serious damage on the first mistake. You want to check permissions and targets before the real run.
@does
- Pass `DryRun=True`; catch `ClientError` and look for `DryRunOperation` (success) or `UnauthorizedOperation` (missing permission).
- Make dry run the default in your tool; require `--apply` to change anything.
- Tag before you delete, wait a grace period, then delete (two phase cleanup).
@diagram flow
caption: Two phase cleanup
numbered: true
nodes:
  - "Find candidates|filters and age|info"
  - "Dry run|permission check|warn"
  - "Tag as pending delete|with date|env"
  - "Delete after grace period|only tagged items|ok"
@h Example
```python title="dry_run.py" nocheck
import boto3
from botocore.exceptions import ClientError

ec2 = boto3.client("ec2", region_name="eu-west-1")


def delete_volume(volume_id: str, apply: bool) -> str:
    try:
        ec2.delete_volume(VolumeId=volume_id, DryRun=not apply)
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "DryRunOperation":
            return "would delete"
        raise
    return "deleted"


print(delete_volume("vol-0123456789abcdef0", apply=False))
```
@check
What does DryRunOperation mean? || The call would have succeeded; nothing was changed.
@end

@concept IAM review with boto3
@plain
IAM holds users, roles, groups and keys. Scripts can list them and flag risks such as old access keys, users without MFA and unused credentials.
@problem
Manual console reviews miss things and do not repeat. Old access keys are one of the most common causes of cloud breaches.
@does
- `list_users`, `list_access_keys(UserName=...)`, `get_access_key_last_used(AccessKeyId=...)` and `list_mfa_devices` are paginated or small.
- IAM is a global service: use any region.
- `generate_credential_report()` then `get_credential_report()` returns a CSV of all users in one call.
- Report first; disable keys only after owners confirm.
@diagram flow
caption: Finding stale access keys
nodes:
  - "list_users|paginator|app"
  - "list_access_keys|per user|info"
  - "Age and last used|compare to limit|env"
  - "Report|owner, key id, days|ok"
@h Example
```python title="iam_old_keys.py" nocheck
from datetime import datetime, timezone

import boto3

iam = boto3.client("iam")
now = datetime.now(timezone.utc)

for page in iam.get_paginator("list_users").paginate():
    for user in page["Users"]:
        name = user["UserName"]
        for key in iam.list_access_keys(UserName=name)["AccessKeyMetadata"]:
            age = (now - key["CreateDate"]).days
            used = iam.get_access_key_last_used(AccessKeyId=key["AccessKeyId"])["AccessKeyLastUsed"]
            last = used.get("LastUsedDate")
            if age > 90 and key["Status"] == "Active":
                print(name, key["AccessKeyId"], f"{age}d old", "last used", last or "never")
```
@check
Why is IAM region independent? || It is a global service with one control plane, so any region endpoint reaches the same data.
@end

@concept Cost Explorer queries
@plain
The Cost Explorer API returns spend grouped by service, account or tag over a period. It answers "where did the money go this month".
@problem
The console cannot be scheduled, and finance asks the same question every week. A script can email a report or fail a pipeline when costs jump.
@does
- `ce.get_cost_and_usage(TimePeriod={"Start": "2026-01-01", "End": "2026-02-01"}, Granularity="MONTHLY", Metrics=["UnblendedCost"], GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}])`.
- `End` is exclusive. Results can continue with `NextPageToken`; there is no paginator for this call.
- Amounts are strings; convert with `Decimal`, not `float`.
- Each API request is billed (about one cent), so cache and do not poll in loops. The service endpoint is in `us-east-1`.
@diagram flow
caption: Cost query to report
nodes:
  - "get_cost_and_usage|group by service|app"
  - "NextPageToken loop|until empty|info"
  - "Decimal totals|no float errors|env"
  - "Top services|sorted table|ok"
@h Example
```python title="cost_by_service.py" nocheck
from decimal import Decimal

import boto3

ce = boto3.client("ce", region_name="us-east-1")


def cost_by_service(start: str, end: str) -> list[tuple[str, Decimal]]:
    totals: dict[str, Decimal] = {}
    token = None
    while True:
        kwargs = dict(
            TimePeriod={"Start": start, "End": end},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        if token:
            kwargs["NextPageToken"] = token
        resp = ce.get_cost_and_usage(**kwargs)
        for period in resp["ResultsByTime"]:
            for g in period["Groups"]:
                amount = Decimal(g["Metrics"]["UnblendedCost"]["Amount"])
                totals[g["Keys"][0]] = totals.get(g["Keys"][0], Decimal(0)) + amount
        token = resp.get("NextPageToken")
        if not token:
            break
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


for name, amount in cost_by_service("2026-01-01", "2026-02-01")[:10]:
    print(f"{name:45} {amount:>10.2f}")
```
```python title="Decimal versus float" lab
from decimal import Decimal

print(0.1 + 0.2, Decimal("0.1") + Decimal("0.2"))
```
@check
Why Decimal for money? || Floats cannot represent most decimal fractions exactly, so sums drift; Decimal is exact.
@end

@concept CloudWatch metrics and logs
@plain
CloudWatch stores metrics (numbers over time) and logs. `get_metric_data` fetches series; Logs Insights queries run over log groups.
@problem
Checking utilisation by hand in the console does not scale to 300 instances. Right sizing and idle detection need metrics in code.
@does
- `cloudwatch.get_metric_data(MetricDataQueries=[...], StartTime=..., EndTime=...)` fetches many series in one call; each query has an `Id` and a `MetricStat` with `Period` and `Stat`.
- `put_metric_data(Namespace=..., MetricData=[...])` publishes custom metrics.
- `logs.start_query` then `get_query_results` runs Insights queries asynchronously.
- Datapoints can be missing; treat "no data" separately from zero.
@diagram flow
caption: Average CPU for one instance
nodes:
  - "MetricDataQueries|Id, Namespace, Name, Dimensions|app"
  - "get_metric_data|paginated by NextToken|info"
  - "Values list|per period|env"
  - "Decision|idle if below threshold|ok"
@h Example
```python title="cpu_average.py" nocheck
from datetime import datetime, timedelta, timezone

import boto3

cw = boto3.client("cloudwatch", region_name="eu-west-1")
end = datetime.now(timezone.utc)
resp = cw.get_metric_data(
    MetricDataQueries=[{
        "Id": "cpu",
        "MetricStat": {
            "Metric": {
                "Namespace": "AWS/EC2",
                "MetricName": "CPUUtilization",
                "Dimensions": [{"Name": "InstanceId", "Value": "i-0123456789abcdef0"}],
            },
            "Period": 3600,
            "Stat": "Average",
        },
    }],
    StartTime=end - timedelta(days=7),
    EndTime=end,
)
values = resp["MetricDataResults"][0]["Values"]
print("avg cpu", sum(values) / len(values) if values else "no data")
```
@check
Why is "no data" different from zero? || An instance that reported nothing may be stopped or misconfigured, which is not the same as being idle.
@end

@concept SSM Parameter Store and Secrets Manager
@plain
Parameter Store (SSM) and Secrets Manager hold configuration and secrets that your tool reads at run time, so nothing sensitive lives in code.
@problem
Credentials in environment files drift between hosts and cannot be rotated centrally or audited.
@does
- `ssm.get_parameter(Name="/ops/slack/webhook", WithDecryption=True)["Parameter"]["Value"]`.
- `ssm.get_parameters_by_path(Path="/ops/", Recursive=True, WithDecryption=True)` has a paginator.
- `secretsmanager.get_secret_value(SecretId="ops/db")["SecretString"]` returns JSON text for structured secrets.
- Grant the role only the specific parameter paths or secret ARNs it needs.
@diagram flow
caption: Secrets are fetched, not shipped
nodes:
  - "IAM role|least privilege|cp"
  - "SSM or Secrets Manager|encrypted store|ext"
  - "Tool at start|reads once|app"
  - "In memory only|not logged|ok"
@h Example
```python title="read_secret.py" nocheck
import json

import boto3

secrets = boto3.client("secretsmanager", region_name="eu-west-1")
raw = secrets.get_secret_value(SecretId="ops/database")["SecretString"]
db = json.loads(raw)
print("connecting as", db["username"])      # never print db["password"]

ssm = boto3.client("ssm", region_name="eu-west-1")
for page in ssm.get_paginator("get_parameters_by_path").paginate(Path="/ops/", Recursive=True):
    for p in page["Parameters"]:
        print(p["Name"], p["Type"])
```
@check
Which flag decrypts SecureString parameters? || WithDecryption=True.
@end
