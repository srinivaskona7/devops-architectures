---
title: boto3 core concepts
minutes: 50
objectives:
  - Explain how boto3 finds credentials and regions
  - Use sessions, clients and resources appropriately
  - Page through large results with paginators and wait for state with waiters
  - Tune retries and assume roles across accounts with STS
---
boto3 is the AWS SDK for Python. Every cloud automation script depends on a handful of core ideas: who am I, which region, how do I page, how do I wait, and what happens when AWS throttles me.

@concept The credential provider chain
@plain
boto3 looks for credentials in a fixed order and uses the first it finds. You rarely pass keys in code; the environment supplies them.
@problem
Hard coded access keys leak and do not rotate. The same script must run on a laptop, in a pipeline and on an EC2 instance or pod without edits.
@does
- Order: explicit parameters, environment variables (`AWS_ACCESS_KEY_ID` and so on), shared files (`~/.aws/credentials`, `~/.aws/config` profiles including SSO), web identity token (EKS IRSA), container credentials (ECS), then instance metadata (EC2).
- `AWS_PROFILE` selects a profile; `AWS_REGION` or `AWS_DEFAULT_REGION` selects the region.
- Temporary credentials from roles are refreshed automatically.
@diagram flow
caption: First match wins
nodes:
  - "Code parameters|avoid|warn"
  - "Environment variables|CI jobs|env"
  - "Profile or SSO|laptops|info"
  - "Web identity|EKS pods|app"
  - "Instance or task role|EC2 and ECS|ok"
@h Check who you are
```python title="whoami_aws.py" nocheck
import boto3

sts = boto3.client("sts")
ident = sts.get_caller_identity()
print(ident["Account"], ident["Arn"])
print("region:", boto3.session.Session().region_name)
```
:::tip
Call `get_caller_identity` at the start of every tool and print the account. It prevents running a cleanup against the wrong account.
:::
@check
Why should code avoid passing access keys directly? || Keys in code leak through Git and cannot rotate; roles and the provider chain supply temporary credentials.
@end

@concept Sessions
@plain
A `boto3.Session` holds credentials and region. Clients created from the same session share them, and you can create several sessions for several accounts or regions.
@problem
The default session is global state. A tool that must scan three regions or two accounts needs separate, explicit configurations.
@does
- `boto3.Session(profile_name="prod", region_name="eu-west-1")`.
- `session.client("ec2")` and `session.resource("s3")` inherit the configuration.
- `session.get_available_regions("ec2")` and `session.region_name` help loop over regions.
- Sessions are not thread safe to share when created; make one per thread, but clients themselves are thread safe.
@diagram layers
caption: Sessions group credentials and region
layers:
  - {label: "Sessions", nodes: ["prod eu-west-1|profile prod|app", "prod us-east-1|profile prod|app", "dev eu-west-1|profile dev|env"]}
  - {label: "Clients", nodes: ["ec2 client|per session|ok", "s3 client|per session|ok"]}
@h Loop over regions
```python title="regions.py" nocheck
import boto3

base = boto3.Session(profile_name="prod")
for region in ("eu-west-1", "us-east-1"):
    ec2 = base.client("ec2", region_name=region)
    count = sum(len(r["Instances"]) for page in ec2.get_paginator("describe_instances").paginate()
                for r in page["Reservations"])
    print(region, count)
```
@check
How do you query two regions with one profile? || Create a client per region from the same session using region_name.
@end

@concept Clients versus resources
@plain
A **client** maps one to one to the AWS API: methods like `describe_instances` return dictionaries. A **resource** is an object oriented wrapper (`s3.Bucket("x").objects.all()`).
@problem
Mixing styles randomly makes code hard to follow, and resources hide the API calls that cost money or hit limits.
@does
- Clients cover every service, are always current, and give full control. Prefer them for new code.
- Resources exist only for some services (S3, EC2, DynamoDB, IAM, SQS and a few more) and are in maintenance mode: no new features.
- Client responses include `ResponseMetadata`; errors arrive as `botocore.exceptions.ClientError`.
@diagram cmp
caption: Which style to use
cards:
  - {h: "Client", kind: ok, items: ["Every service and operation", "Dictionaries in and out", "Paginators and waiters available"]}
  - {h: "Resource", kind: warn, items: ["Few services only", "Objects and collections", "No new features, hides API calls"]}
@h The same task in both
```python title="client_vs_resource.py" nocheck
import boto3

# client: explicit API call
s3c = boto3.client("s3")
for page in s3c.get_paginator("list_objects_v2").paginate(Bucket="my-logs", Prefix="2026/"):
    for obj in page.get("Contents", []):
        print(obj["Key"], obj["Size"])

# resource: object style
s3r = boto3.resource("s3")
for obj in s3r.Bucket("my-logs").objects.filter(Prefix="2026/"):
    print(obj.key, obj.size)
```
@check
Which should new code prefer and why? || Clients, because they cover all services and receive every new feature.
@end

@concept Paginators
@plain
Most list calls return only a limited number of items per call and a continuation token. A **paginator** hides the token handling and yields every page.
@problem
Calling `describe_volumes()` once misses everything past the first page, so reports and cleanups quietly cover only part of the account.
@does
- `client.get_paginator("describe_volumes")` returns a paginator when the operation supports it; `client.can_paginate("name")` checks.
- `paginate(**params)` yields response pages; `PaginationConfig={"MaxItems": 500, "PageSize": 100}` limits.
- `paginate(...).search("Volumes[?State=='available'].VolumeId")` applies a JMESPath query across all pages.
@diagram flow
caption: What a paginator loops over
nodes:
  - "Call 1|returns 100 items and token|app"
  - "Call 2|sends token|app"
  - "Call n|no token returned|app"
  - "Generator|you see one stream of pages|ok"
@h Example
```python title="paginator.py" nocheck
import boto3

ec2 = boto3.client("ec2", region_name="eu-west-1")
pager = ec2.get_paginator("describe_volumes")

for page in pager.paginate(Filters=[{"Name": "status", "Values": ["available"]}]):
    for v in page["Volumes"]:
        print(v["VolumeId"], v["Size"])

ids = pager.paginate().search("Volumes[?State=='available'].VolumeId")
print(list(ids))
```
@check
What does can_paginate tell you? || Whether an operation has a paginator, since a few list operations do not.
@end

@concept Waiters
@plain
A **waiter** polls AWS until a resource reaches a state, such as an instance running or a snapshot completed, and raises an error if it does not within a limit.
@problem
Hand written `while True: sleep()` loops forget timeouts and check the wrong field, leaving scripts that hang or continue too early.
@does
- `client.get_waiter("instance_running").wait(InstanceIds=[id])`.
- `WaiterConfig={"Delay": 10, "MaxAttempts": 30}` sets the polling rate and the limit.
- Failure raises `botocore.exceptions.WaiterError`.
- `client.waiter_names` lists what exists for that service.
@diagram seq
caption: Waiter polling
actors: ["Script|waiter.wait|app", "EC2|describe_instances|ext"]
steps:
  - "0>1: run_instances | req"
  - "0>1: poll state | req"
  - "1>0: pending | resp"
  - "0>1: poll again after Delay | req"
  - "1>0: running | resp"
@h Example
```python title="waiter.py" nocheck
import boto3
from botocore.exceptions import WaiterError

ec2 = boto3.client("ec2", region_name="eu-west-1")
snap = ec2.create_snapshot(VolumeId="vol-0123456789abcdef0", Description="pre-change")
try:
    ec2.get_waiter("snapshot_completed").wait(
        SnapshotIds=[snap["SnapshotId"]],
        WaiterConfig={"Delay": 15, "MaxAttempts": 40},
    )
except WaiterError as exc:
    raise SystemExit(f"snapshot did not complete: {exc}")
print("snapshot ready")
```
@check
What happens if the resource never reaches the state? || The waiter stops after MaxAttempts and raises WaiterError.
@end

@concept Retries, timeouts and Config
@plain
botocore retries throttling and transient errors by itself. The `Config` object lets you choose the mode, the number of attempts and the timeouts.
@problem
Bulk scripts hit API rate limits (`ThrottlingException`, `RequestLimitExceeded`). The legacy default of few attempts fails; no timeouts means hangs.
@does
- `Config(retries={"max_attempts": 10, "mode": "adaptive"})`; modes are `legacy`, `standard` and `adaptive` (adds client side rate limiting).
- `connect_timeout` and `read_timeout` bound each call; defaults are 60 seconds.
- `region_name`, `user_agent_extra` and `max_pool_connections` live in the same object.
- Retries are for throttling and 5xx; permission errors fail at once.
@diagram flow
caption: What the SDK does for you
nodes:
  - "Call|your request|app"
  - "Throttled|error from AWS|bad"
  - "Backoff with jitter|SDK waits|warn"
  - "Retry up to max|then raise|info"
  - "Success|result returned|ok"
@h Configuration
```python title="config_retries.py" nocheck
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

cfg = Config(
    region_name="eu-west-1",
    retries={"max_attempts": 10, "mode": "adaptive"},
    connect_timeout=5,
    read_timeout=30,
)
ce = boto3.client("ec2", config=cfg)

try:
    ce.describe_instances(InstanceIds=["i-doesnotexist"])
except ClientError as exc:
    code = exc.response["Error"]["Code"]          # for example InvalidInstanceID.Malformed
    print(code, exc.response["ResponseMetadata"]["HTTPStatusCode"])
```
@check
Which retry mode adds client side rate limiting? || adaptive.
@end

@concept Handling ClientError
@plain
Every failed AWS call raises `botocore.exceptions.ClientError`. The specific problem is in `exc.response["Error"]["Code"]`, not in the exception class.
@problem
Catching all exceptions hides real bugs, and string matching on messages breaks when wording changes.
@does
- Read `Error.Code` and compare to known codes such as `NoSuchBucket`, `AccessDenied`, `ResourceNotFoundException`, `Throttling`.
- Catch narrowly around one call; let unexpected codes propagate.
- Client objects also expose modelled exceptions as `client.exceptions.NoSuchBucket`.
- `botocore.exceptions.NoCredentialsError`, `EndpointConnectionError` are separate, non-ClientError cases.
@diagram flow
caption: Decide from the error code
nodes:
  - "ClientError|raised|bad"
  - "Read Error Code|exc.response|info"
  - "Expected code|handle it|ok"
  - "Unexpected|re-raise|warn"
@h Example
```python title="client_error.py" nocheck
import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")


def bucket_exists(name: str) -> bool:
    try:
        s3.head_bucket(Bucket=name)
        return True
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code in ("404", "NoSuchBucket"):
            return False
        raise                                   # 403 and others are real problems
```
@check
Why not catch Exception around an AWS call? || It hides credential, permission and programming errors that you need to see.
@end

@concept STS and assuming roles
@plain
**STS** (Security Token Service) gives short lived credentials. `assume_role` lets a tool in one account act in another by taking on a role there, which is how multi account automation works.
@problem
Long lived keys for every account are a security risk. A central tool needs to reach dozens of accounts safely and with an audit trail.
@does
- `sts.assume_role(RoleArn=..., RoleSessionName=...)` returns `AccessKeyId`, `SecretAccessKey`, `SessionToken` and `Expiration`.
- The target role's trust policy must allow your principal; add `ExternalId` for third party access.
- Credentials expire (default 1 hour); request a new set for long runs.
- Profiles with `role_arn` and `source_profile` in `~/.aws/config` do the same automatically with refresh.
@diagram seq
caption: Assuming a role in another account
actors: ["Tool|central account|app", "STS|token service|cp", "Target role|workload account|ok"]
steps:
  - "0>1: AssumeRole with ARN | req"
  - "1>2: check trust policy | tls"
  - "2>1: allowed | resp"
  - "1>0: temporary credentials | resp"
  - "0>2: API calls as the role | req"
@h Example
```python title="assume_role.py" nocheck
import boto3


def session_for(account_id: str, role_name: str = "OpsReadOnly", region: str = "eu-west-1") -> boto3.Session:
    sts = boto3.client("sts")
    creds = sts.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/{role_name}",
        RoleSessionName="opskit-scan",
        DurationSeconds=3600,
    )["Credentials"]
    return boto3.Session(
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
        region_name=region,
    )


for acct in ("111111111111", "222222222222"):
    sess = session_for(acct)
    print(acct, sess.client("sts").get_caller_identity()["Arn"])
```
:::warn
Use the least privileged role, such as read only for reports. A scanner that can also delete is a risk if its credentials leak.
:::
@check
What two things must allow an assume role call? || The caller's identity policy (permission to call sts:AssumeRole) and the target role's trust policy.
@end
