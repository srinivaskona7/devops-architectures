---
title: S3 access control, access points and presigned URLs
minutes: 50
objectives:
  - Combine IAM, bucket policies and access points without conflicting rules
  - Generate and constrain presigned URLs and presigned POST for uploads
  - Use Object Lock and MFA delete to make data tamper resistant
---
S3 has several overlapping ways to grant access. A clear mental model, and one place where rules live, avoids both leaks and mystery denials.

@concept How S3 authorises requests
@plain
S3 combines the caller's IAM policies, the bucket policy, access point policies, Block Public Access, ACLs (if enabled) and any organization SCPs/RCPs. Evaluation follows the IAM logic: explicit deny wins, otherwise some allow is needed.
@problem
People add a policy in one place and wonder why another still denies, or leave an ACL allowing public read.
@does
- Same-account access: an allow in either the identity policy or the bucket policy is enough (unless the bucket policy only names the account root, in which case identity policies must allow).
- Cross-account: both sides must allow.
- Keep ACLs disabled with BucketOwnerEnforced.
- Prefer **prefix-scoped bucket policies** or **access points** over one huge bucket policy.
@diagram flow
caption: Request evaluation in S3
numbered: true
nodes:
  - "Request|signed by a principal|plain"
  - "Org policies|SCP and RCP|cp"
  - "Block Public Access|public grants removed|warn"
  - "Bucket and access point policy|resource side|env"
  - "Identity policy|caller side|app"
@h Bucket policy for a prefix
```json title="prefix-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "TeamRead",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::444455556666:role/analytics"},
      "Action": ["s3:GetObject"],
      "Resource": "arn:aws:s3:::acme-data-eu/shared/analytics/*"
    },
    {
      "Sid": "TeamList",
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::444455556666:role/analytics"},
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::acme-data-eu",
      "Condition": {"StringLike": {"s3:prefix": ["shared/analytics/*"]}}
    }
  ]
}
```
@check
Can an object ACL still expose data in a BucketOwnerEnforced bucket? || No. ACLs are disabled, so only policies apply.
@end

@concept S3 Access Points
@plain
An **access point** is a named endpoint attached to a bucket with its own policy and optional VPC restriction.
@problem
A shared bucket used by dozens of teams ends up with an unreadable bucket policy near the size limit.
@does
- Each access point has its own DNS name and ARN (`arn:aws:s3:region:account:accesspoint/name`) and its own policy; the bucket policy simply delegates to access points in the same account.
- **VPC-restricted** access points accept requests only from the specified VPC.
- **Object Lambda access points** transform data on read (redact, convert) with a Lambda function.
- **Multi-Region** access points route across buckets (see replication).
- Applications use the access point ARN in place of the bucket name.
@diagram layers
caption: One bucket, scoped doors
layers:
  - {label: "Bucket", nodes: ["acme-data-eu|delegates to access points|cp"]}
  - {label: "Access points", nodes: ["analytics-ap|prefix shared/analytics|app", "ingest-ap|VPC only, write|env", "audit-ap|read only|info"]}
@h Create
```bash title="Access point with a VPC restriction" lab
aws s3control create-access-point --account-id 111122223333 --bucket acme-data-eu --name ingest-ap \
  --vpc-configuration VpcId=vpc-0123456789abcdef0
aws s3control put-access-point-policy --account-id 111122223333 --name ingest-ap --policy file://ap-policy.json
aws s3 cp ./file s3://arn:aws:s3:eu-west-1:111122223333:accesspoint/ingest-ap/incoming/file
```
```json title="delegate-to-access-points.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": "*"},
      "Action": "*",
      "Resource": ["arn:aws:s3:::acme-data-eu", "arn:aws:s3:::acme-data-eu/*"],
      "Condition": {"StringEquals": {"s3:DataAccessPointAccount": "111122223333"}}
    }
  ]
}
```
@end

@concept Presigned URLs
@plain
A **presigned URL** carries a signature that lets anyone who holds it perform one specific S3 operation until it expires, without AWS credentials.
@problem
Browsers and partners need to upload or download a single object, and you do not want to proxy the bytes through your servers or share credentials.
@does
- The URL is signed with the credentials of the signer, so it can do only what the signer's permissions allow, and stops working if those credentials expire or are revoked.
- Expiry up to seven days with IAM user keys; shorter limited by the session lifetime for temporary credentials.
- Generate from the SDK or CLI. `PUT` URLs for uploads; `GET` for downloads. **Presigned POST** adds form conditions such as size limits and content type.
- Treat URLs as bearer secrets; keep expiry short, avoid logging them.
@diagram seq
caption: Browser upload via presigned URL
actors: ["Browser|client|ext", "API|your service|app", "S3|bucket|env"]
steps:
  - "0>1: request upload permission | req"
  - "1>0: presigned PUT URL, 5 minutes | resp"
  - "0>2: PUT file directly | tls"
  - "2>0: 200 OK | resp"
@h Create them
```bash title="CLI" lab
aws s3 presign s3://acme-data-eu/reports/a.csv --expires-in 600
```
```python title="Python (boto3) PUT and POST"
import boto3

s3 = boto3.client("s3", region_name="eu-west-1")

put_url = s3.generate_presigned_url(
    "put_object",
    Params={"Bucket": "acme-data-eu", "Key": "uploads/photo.jpg", "ContentType": "image/jpeg"},
    ExpiresIn=300,
)

post = s3.generate_presigned_post(
    Bucket="acme-data-eu",
    Key="uploads/${filename}",
    Fields={"Content-Type": "image/jpeg"},
    Conditions=[["content-length-range", 1, 10_000_000], {"Content-Type": "image/jpeg"}],
    ExpiresIn=300,
)
print(put_url[:60], post["url"])
```
:::warn
A presigned URL made with an assumed role dies when that role session ends, even if the expiry is longer. Sign with a suitably long-lived identity for long links.
:::
@check
Why use presigned POST instead of PUT for browser uploads? || POST lets you enforce conditions such as maximum size and content type.
@end

@concept Object Lock and MFA delete
@plain
**Object Lock** makes object versions write-once-read-many (WORM) for a retention period or indefinitely.
@problem
Ransomware, insider threats and regulations (financial records, audit logs) require data that nobody can delete or alter, including administrators.
@does
- Must be enabled when a bucket is created (it can be enabled on existing buckets with support involvement; check the current rules). Requires versioning.
- **Governance mode**: users with special permission (`s3:BypassGovernanceRetention`) can override. **Compliance mode**: nobody, including root, can delete or shorten retention until it expires.
- **Legal hold**: indefinite lock independent of retention, toggled with a permission.
- A default retention can apply to every new object. Lifecycle expiration respects locks.
- **MFA Delete**: needs MFA for permanent version deletion; different from Object Lock and managed only by the root user.
@diagram cmp
caption: Retention modes
cards:
  - {h: "Governance", kind: warn, items: ["Protected from normal users", "Privileged bypass possible", "Good for testing"]}
  - {h: "Compliance", kind: bad, items: ["No one can delete", "Not even root", "Cannot shorten retention"]}
  - {h: "Legal hold", kind: info, items: ["No expiry date", "Removed with permission", "Independent of retention"]}
@h Create a locked bucket
```bash title="Object Lock setup" lab
aws s3api create-bucket --bucket acme-audit-logs --region eu-west-1 --create-bucket-configuration LocationConstraint=eu-west-1 \
  --object-lock-enabled-for-bucket
aws s3api put-object-lock-configuration --bucket acme-audit-logs \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"GOVERNANCE","Days":30}}}'
aws s3api get-object-retention --bucket acme-audit-logs --key log.gz --version-id EXAMPLEVERSIONID
```
:::danger
Compliance mode retention cannot be shortened or removed, and you pay for the storage until it ends. Test in governance mode with short periods first.
:::
@end

@concept Event notifications and access logging
@plain
S3 can announce changes and record access, giving you hooks for automation and audit trails.
@problem
You need to react to uploads and prove who accessed sensitive data.
@does
- **Event notifications** (and EventBridge integration) fire on object created, removed, restored, replication and lifecycle events; targets include Lambda, SQS, SNS and EventBridge.
- **Server access logs** are best-effort deliveries of request records to another bucket; **CloudTrail data events** give reliable object-level API logging at extra cost.
- Use the same Region log bucket, no logging loop, and lifecycle on the logs.
- Enable EventBridge for fan-out, filtering and archive.
@diagram flow
caption: Upload triggers processing
nodes:
  - "Object created|PUT or multipart|app"
  - "EventBridge|filter by prefix|cp"
  - "Lambda or queue|process|info"
  - "Result bucket|ok|ok"
@h Enable EventBridge
```bash title="Notifications" lab
aws s3api put-bucket-notification-configuration --bucket acme-data-eu --notification-configuration '{"EventBridgeConfiguration":{}}'
aws s3api get-bucket-notification-configuration --bucket acme-data-eu
```
@check
Which logging gives reliable object level auditing? || CloudTrail data events; server access logs are best effort.
@end
