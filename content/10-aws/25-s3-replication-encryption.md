---
title: S3 replication and encryption
minutes: 50
objectives:
  - Configure same-Region and cross-Region replication and know what it does not copy
  - Choose between SSE-S3, SSE-KMS, DSSE-KMS and client-side encryption
  - Use bucket keys and KMS key policies to control cost and access
---
Data protection in S3 has two halves: where copies live (replication) and who can decrypt them (encryption).

@concept Replication
@plain
**S3 Replication** copies new objects asynchronously from a source bucket to one or more destination buckets, in the same Region (SRR) or another (CRR), in the same or another account.
@problem
You need disaster recovery in another Region, data residency copies, log aggregation across accounts, or lower latency for remote readers.
@does
- Requires versioning on both buckets and an IAM role that S3 assumes to read from the source and write to the destination.
- Rules filter by prefix or tag. Replicates new objects only; existing objects need **Batch Replication**.
- Can change owner, storage class and KMS key on the destination. Delete markers replication is optional; permanent version deletes are not replicated, which protects against malicious deletes.
- **Replication Time Control (RTC)** gives a 15-minute SLA with metrics, for an extra fee.
- **Bidirectional** replication is possible with replica modification sync; avoid loops.
@diagram flow
caption: Cross-Region replication
nodes:
  - "Source bucket|eu-west-1, versioned|app"
  - "Replication role|assumed by S3|cp"
  - "Destination bucket|eu-central-1, versioned|ok"
  - "Metrics|latency, pending bytes|info"
@h Configuration
```json title="replication.json"
{
  "Role": "arn:aws:iam::111122223333:role/s3-replication",
  "Rules": [
    {
      "ID": "backups-to-dr",
      "Status": "Enabled",
      "Priority": 1,
      "Filter": {"Prefix": "backups/"},
      "DeleteMarkerReplication": {"Status": "Disabled"},
      "Destination": {
        "Bucket": "arn:aws:s3:::acme-data-dr",
        "StorageClass": "STANDARD_IA"
      }
    }
  ]
}
```
```bash title="Apply and monitor" lab
aws s3api put-bucket-replication --bucket acme-data-eu --replication-configuration file://replication.json
aws s3api head-object --bucket acme-data-eu --key backups/a.tar --query ReplicationStatus
aws s3api head-object --bucket acme-data-dr --key backups/a.tar --query ReplicationStatus   # REPLICA
```
@check
Are objects that existed before the rule replicated? || No. Use S3 Batch Replication for existing objects.
@end

@concept Encryption at rest
@plain
Every S3 object is encrypted at rest. You choose who manages the key.
@problem
Compliance and key-ownership rules differ; some data must be decryptable only by specific principals, with an audit trail.
@does
- **SSE-S3** (AES-256, keys managed by S3): default for all new objects since 2023, no cost, no extra audit.
- **SSE-KMS**: keys in AWS KMS (AWS managed `aws/s3` or your customer managed key). Every use is logged in CloudTrail; access needs both S3 and KMS permissions. KMS request quotas and cost apply.
- **DSSE-KMS**: two layers of encryption for special compliance cases.
- **SSE-C**: you supply the key per request; S3 does not store it. Uncommon. Check the current status of SSE-C defaults as they have changed.
- **Client-side**: encrypt before upload with your own tooling or the AWS Encryption SDK.
@diagram cmp
caption: Server-side options
cards:
  - {h: "SSE-S3", kind: ok, items: ["Default, free", "No key management", "No per-key audit"]}
  - {h: "SSE-KMS", kind: app, items: ["Customer managed key control", "CloudTrail audit", "KMS cost and quotas"]}
  - {h: "SSE-C", kind: warn, items: ["Key sent each request", "You manage everything"]}
@h SSE-KMS with bucket keys
```hcl title="kms-bucket.tf"
resource "aws_kms_key" "s3" {
  description         = "S3 data key"
  enable_key_rotation = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}
```
:::tip
Enable **S3 Bucket Keys** with SSE-KMS. They cut KMS requests substantially, lowering cost and the chance of KMS throttling.
:::
@end

@concept KMS permissions for S3
@plain
With SSE-KMS a caller needs permission on the bucket and on the key. A missing key permission looks like an S3 access denied.
@problem
Cross-account reads and replication fail with confusing errors when the key policy does not name the other principal.
@does
- Reader needs `s3:GetObject` and `kms:Decrypt`; writer needs `s3:PutObject` and `kms:GenerateDataKey` (and `kms:Encrypt` for some paths).
- The key policy must allow the account (via the root statement enabling IAM) or the principal explicitly; cross-account needs both key policy and IAM policy.
- Replication role needs `kms:Decrypt` on the source key and `kms:Encrypt`/`GenerateDataKey` on the destination key.
- Use `kms:ViaService` and `kms:CallerAccount` conditions to restrict key use to S3.
- Enforce encryption with a bucket policy condition on `s3:x-amz-server-side-encryption`.
@diagram seq
caption: Reading an SSE-KMS object
actors: ["Reader role|app|app", "S3|bucket|env", "KMS|customer key|cp"]
steps:
  - "0>1: GetObject | req"
  - "1>2: Decrypt data key as caller | req"
  - "2>1: allowed by key policy and IAM | resp"
  - "1>0: plaintext object | resp"
@h Reader policy and key conditions
```json title="reader-kms.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::acme-data-eu/reports/*"},
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:eu-west-1:111122223333:key/11111111-2222-3333-4444-555555555555",
      "Condition": {"StringEquals": {"kms:ViaService": "s3.eu-west-1.amazonaws.com"}}
    }
  ]
}
```
```bash title="Debug an access denied" lab
aws kms describe-key --key-id alias/s3-data --query 'KeyMetadata.[KeyState,KeyManager]'
aws kms get-key-policy --key-id alias/s3-data --policy-name default --query Policy --output text | python3 -m json.tool | head -30
```
@check
A read fails only for SSE-KMS objects. What do you check first? || The caller's kms:Decrypt permission and the key policy, in addition to the S3 policy.
@end

@concept Enforcing encryption and transit security
@plain
Policies can reject uploads that do not meet your encryption and TLS standards.
@problem
Defaults help but a developer may request another algorithm or key.
@does
- Deny `PutObject` unless `s3:x-amz-server-side-encryption` equals `aws:kms` and the key ARN matches (`s3:x-amz-server-side-encryption-aws-kms-key-id`).
- Deny non-TLS requests, and require a minimum TLS version with `s3:TlsVersion`.
- Default bucket encryption applies when no header is sent, so such a policy must permit requests without headers if you rely on defaults; test before enforcing.
- Use Access Analyzer and AWS Config rules (`s3-bucket-server-side-encryption-enabled`) to report drift.
@diagram flow
caption: Gate before write
nodes:
  - "PutObject|with headers|app"
  - "Bucket policy|encryption and TLS conditions|cp"
  - "Accepted|matches policy|ok"
  - "Denied 403|wrong algorithm or key|bad"
@h Policy
```json title="enforce-kms.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyWrongKey",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:PutObject",
      "Resource": "arn:aws:s3:::acme-data-eu/*",
      "Condition": {
        "StringNotEqualsIfExists": {
          "s3:x-amz-server-side-encryption-aws-kms-key-id": "arn:aws:kms:eu-west-1:111122223333:key/11111111-2222-3333-4444-555555555555"
        },
        "Null": {"s3:x-amz-server-side-encryption-aws-kms-key-id": "false"}
      }
    },
    {
      "Sid": "MinimumTls",
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": ["arn:aws:s3:::acme-data-eu", "arn:aws:s3:::acme-data-eu/*"],
      "Condition": {"NumericLessThan": {"s3:TlsVersion": "1.2"}}
    }
  ]
}
```
@end

@concept Multi-Region Access Points and replication patterns
@plain
A **Multi-Region Access Point** gives one global endpoint that routes requests to the closest replicated bucket.
@problem
Multi-Region applications want one name, low latency reads and failover without client logic.
@does
- Create the access point over buckets in different Regions that are already linked by replication.
- Requests are routed over the AWS network to the lowest-latency bucket; failover controls shift traffic between active and passive buckets.
- Use with two-way replication for active-active. Reads are eventually consistent across Regions.
- Requests are signed with SigV4A (multi-Region signing); use a recent SDK or CLI.
- Extra data routing and request costs apply; check current pricing.
@diagram layers
caption: One endpoint, two buckets
layers:
  - {label: "Global", nodes: ["Multi-Region Access Point|one alias|cp"]}
  - {label: "Region A", nodes: ["Bucket eu-west-1|active|app"]}
  - {label: "Region B", nodes: ["Bucket us-east-1|active or passive|app"]}
@choose Multi-Region data
Cross-Region replication | DR copy, residency | you need one global endpoint for clients
Multi-Region Access Point | active-active reads and failover | single Region applications
Backups with AWS Backup | scheduled, vault-locked copies | low RPO sync is required
@check
Why must versioning be enabled before replication? || Replication tracks object versions, so both source and destination need versioning.
@end
