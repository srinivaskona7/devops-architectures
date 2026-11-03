---
title: S3 fundamentals and storage classes
minutes: 45
objectives:
  - Describe the S3 data model, consistency and durability
  - Choose a storage class by access pattern and retrieval needs
  - Create buckets safely with Block Public Access and ownership controls
---
**Amazon S3** is object storage with effectively unlimited capacity. It holds logs, backups, static sites, ML data, Terraform state and container registry layers, so it is part of nearly every design.

@concept Buckets, objects and keys
@plain
A **bucket** is a named container in one Region. An **object** is a blob of data with a **key** (its full name), metadata and optional tags. There are no real folders; slashes in keys are only a naming convention.
@problem
Traditional file systems struggle with billions of files and need servers. S3 offers an HTTP API with no servers to run.
@does
- Bucket names are globally unique within a partition. Create them in the Region closest to the workload.
- Objects can be up to 5 TB; a single PUT up to 5 GB, so use **multipart upload** for larger objects (recommended from about 100 MB).
- S3 provides **strong read-after-write consistency** for all operations.
- Designed for 99.999999999 percent (11 nines) durability by storing data redundantly across multiple AZs for most classes.
- Prefixes (`logs/2026/10/`) group keys for listing, permissions and lifecycle rules.
@diagram layers
caption: S3 data model
layers:
  - {label: "Account and Region", nodes: ["Bucket|acme-data-eu|cp"]}
  - {label: "Keys", nodes: ["logs/2026/10/app.gz|object|app", "images/logo.png|object|app"]}
  - {label: "Per object", nodes: ["Data|up to 5 TB|info", "Metadata and tags|content type, labels|env", "Version ID|if versioning is on|ok"]}
@h Everyday commands
```bash title="aws s3 and s3api" lab
aws s3 mb s3://acme-data-eu --region eu-west-1
aws s3 cp ./report.csv s3://acme-data-eu/reports/2026/10/report.csv
aws s3 sync ./site s3://acme-data-eu/site --delete --exclude ".git/*"
aws s3 ls s3://acme-data-eu/reports/ --recursive --human-readable --summarize
aws s3api head-object --bucket acme-data-eu --key reports/2026/10/report.csv
```
@check
Does S3 have real folders? || No. Keys are flat strings; the console shows prefixes as folders.
@end

@concept Secure bucket defaults
@plain
New buckets should block public access, enforce ownership by the bucket owner, encrypt data and require TLS.
@problem
Publicly exposed buckets are a repeated cause of data leaks, often through an old ACL or an overly broad policy.
@does
- **Block Public Access** (four settings) overrides ACLs and policies that would make data public. Enable at the account level, and in each bucket.
- **Object Ownership = BucketOwnerEnforced** disables ACLs entirely; control access with policies only. This is the default for new buckets.
- Default encryption with SSE-S3 is applied to all new objects automatically.
- Bucket policy denying `aws:SecureTransport = false` forces HTTPS.
@diagram flow
caption: Layers that must all allow public access
nodes:
  - "Account Block Public Access|off?|cp"
  - "Bucket Block Public Access|off?|cp"
  - "Bucket policy or ACL|grants public?|warn"
  - "Public|only if all three allow|bad"
@h Terraform baseline
```hcl title="bucket.tf"
resource "aws_s3_bucket" "data" {
  bucket = "acme-data-eu"
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

data "aws_iam_policy_document" "tls_only" {
  statement {
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket = aws_s3_bucket.data.id
  policy = data.aws_iam_policy_document.tls_only.json
}
```
```bash title="Account-wide block" lab
aws s3control put-public-access-block --account-id 111122223333 \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```
@check
What does BucketOwnerEnforced do? || Disables ACLs, so the bucket owner owns every object and policies are the only access control.
@end

@concept Storage classes
@plain
A **storage class** trades storage price against retrieval cost, retrieval time and minimum duration.
@problem
Keeping rarely used data in the standard class overpays, while moving hot data to a cold class makes reads slow or costly.
@does
- **S3 Standard**: frequent access, no retrieval fee, lowest latency.
- **S3 Intelligent-Tiering**: moves objects between access tiers automatically for a small monitoring fee per object; best when patterns are unknown. Small objects (under 128 KB) are not auto-tiered.
- **Standard-IA** and **One Zone-IA**: infrequent access, retrieval fee, 30-day minimum, 128 KB minimum billable size. One Zone-IA keeps data in a single AZ.
- **Glacier Instant Retrieval**: archive with millisecond access, 90-day minimum.
- **Glacier Flexible Retrieval**: minutes to hours, 90-day minimum. **Glacier Deep Archive**: lowest price, hours (about 12 or more), 180-day minimum.
- **S3 Express One Zone**: single-digit millisecond directory buckets for hot, latency-sensitive data. Check current pricing and Regions.
- Minimum durations, sizes and prices change; verify them on the current pricing page.
@diagram cmp
caption: Access pattern to class
cards:
  - {h: "Hot", kind: ok, items: ["Standard", "Express One Zone for latency"]}
  - {h: "Unknown or changing", kind: info, items: ["Intelligent-Tiering", "No retrieval charges"]}
  - {h: "Cool", kind: warn, items: ["Standard-IA", "Glacier Instant Retrieval"]}
  - {h: "Cold archive", kind: bad, items: ["Glacier Flexible", "Deep Archive", "Restore before reading"]}
@h Set a class on upload
```bash title="Choose at write time" lab
aws s3 cp backup.tar.gz s3://acme-data-eu/backups/ --storage-class GLACIER_IR
aws s3 cp scratch.bin s3://acme-data-eu/tmp/ --storage-class INTELLIGENT_TIERING
aws s3api list-objects-v2 --bucket acme-data-eu --prefix backups/ --query 'Contents[].[Key,StorageClass,Size]' --output table
```
:::tip
For Kubernetes logs and backups, write directly into Intelligent-Tiering or add a lifecycle rule, rather than leaving everything in Standard.
:::
@end

@concept Restoring archived objects
@plain
Objects in Glacier Flexible Retrieval and Deep Archive are not readable until you request a restore, which creates a temporary copy.
@problem
An application that reads archived keys directly fails with `InvalidObjectState`.
@does
- `restore-object` with a tier: Expedited (minutes, Flexible only), Standard, Bulk (cheapest, slowest). Days setting controls how long the copy stays.
- Poll `head-object` for the `Restore` header, or enable event notifications for `s3:ObjectRestore:Completed`.
- Glacier Instant Retrieval objects are readable immediately.
- Use **S3 Batch Operations** to restore many objects.
@diagram seq
caption: Restoring an archived object
actors: ["You|operator|app", "S3|Glacier Flexible|cp", "Temporary copy|Standard class|ok"]
steps:
  - "0>1: restore-object Days=7 Tier=Standard | req"
  - "note 1..1: retrieval takes hours"
  - "1>2: temporary copy created | resp"
  - "0>2: GET works until expiry | req"
@h Restore
```bash title="Request and check" lab
aws s3api restore-object --bucket acme-data-eu --key archive/2024.tar \
  --restore-request '{"Days":7,"GlacierJobParameters":{"Tier":"Standard"}}'
aws s3api head-object --bucket acme-data-eu --key archive/2024.tar --query Restore
```
@check
Can you GET a Deep Archive object directly? || No. Restore it first and read the temporary copy.
@end

@concept Consistency, durability and availability
@plain
S3 reads see the latest write immediately. Durability is about not losing data; availability is about reaching it.
@problem
Engineers confuse durability with protection from deletion and corruption. S3 will faithfully store a deletion you ask for.
@does
- Strong consistency removes old workarounds such as listing delays.
- 11 nines is the designed durability; availability differs per class (for example 99.99 percent for Standard; check the current SLA table).
- Protect against human error with versioning, MFA delete, Object Lock and replication, not by relying on durability.
- Regional endpoints: reach them via a **gateway endpoint** from a VPC; use the same Region as compute to avoid transfer fees.
@diagram flow
caption: Durability does not equal safety
nodes:
  - "Accidental delete|API call succeeds|bad"
  - "Versioning|keeps previous version|ok"
  - "Replication|second copy elsewhere|info"
  - "Object Lock|cannot be removed|cp"
@h Checks
```bash title="Check protection state" lab
aws s3api get-bucket-versioning --bucket acme-data-eu
aws s3api get-public-access-block --bucket acme-data-eu
aws s3api get-bucket-encryption --bucket acme-data-eu
```
@end
