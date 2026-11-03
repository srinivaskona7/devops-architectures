---
title: S3 versioning, lifecycle and inventory
minutes: 45
objectives:
  - Enable versioning and recover deleted or overwritten objects
  - Write lifecycle rules that transition, expire and clean up safely
  - Use Inventory, Storage Lens and Batch Operations to manage large buckets
---
Time is the main cost driver in S3. Versioning protects data, lifecycle rules control its cost, and inventory tools tell you what you have.

@concept Versioning
@plain
With **versioning** on, every write creates a new version and a delete adds a **delete marker** instead of removing data.
@problem
Overwrites and deletes are permanent by default, so a script bug can destroy data.
@does
- Each version has a version ID. A plain GET returns the latest non-deleted version.
- Deleting with a version ID permanently removes that version; deleting without one adds a delete marker.
- Versioning can be suspended but never fully turned off once enabled.
- Noncurrent versions cost storage, so pair versioning with lifecycle rules.
- **MFA Delete** requires MFA to permanently delete versions or change versioning state (root user only to enable).
@diagram flow
caption: Overwrite and delete with versioning
nodes:
  - "PUT v1|first write|app"
  - "PUT v2|new version, v1 kept|info"
  - "DELETE|adds delete marker|warn"
  - "Remove marker|v2 visible again|ok"
@h Recover
```bash title="Versions and restore" lab
aws s3api put-bucket-versioning --bucket acme-data-eu --versioning-configuration Status=Enabled
aws s3api list-object-versions --bucket acme-data-eu --prefix reports/a.csv \
  --query '{Versions:Versions[].[VersionId,IsLatest,LastModified],Markers:DeleteMarkers[].[VersionId,IsLatest]}'
# undo a delete by removing the delete marker
aws s3api delete-object --bucket acme-data-eu --key reports/a.csv --version-id EXAMPLEMARKERVERSIONID
# restore an older version by copying it onto the key
aws s3api copy-object --bucket acme-data-eu --key reports/a.csv --copy-source "acme-data-eu/reports/a.csv?versionId=EXAMPLEOLDVERSIONID"
```
@check
What does deleting an object in a versioned bucket do? || It adds a delete marker; earlier versions remain and can be restored.
@end

@concept Lifecycle rules
@plain
A **lifecycle configuration** is a set of rules that move objects to cheaper classes or delete them after a number of days, optionally filtered by prefix, tag or size.
@problem
Manual cleanup of logs, backups and old versions never happens, so cost grows forever.
@does
- **Transition** actions move current or noncurrent versions between classes (respecting minimum days between transitions, check the current rules).
- **Expiration** deletes current objects (or adds a delete marker in versioned buckets) and, for noncurrent versions, permanently removes them after N days.
- **Abort incomplete multipart uploads** after some days; leftovers are billed invisibly.
- **Expired object delete markers** cleanup; filter by prefix, tags, `ObjectSizeGreaterThan` / `LessThan`.
- Rules run asynchronously, typically at midnight UTC; changes take time to apply.
@diagram flow
caption: Age based progression
nodes:
  - "Standard|0 to 30 days|ok"
  - "Standard-IA or Intelligent|30 days|info"
  - "Glacier Flexible|90 days|warn"
  - "Expire|365 days|bad"
@h A typical rule set
```json title="lifecycle.json"
{
  "Rules": [
    {
      "ID": "logs-tiering",
      "Status": "Enabled",
      "Filter": {"Prefix": "logs/"},
      "Transitions": [
        {"Days": 30, "StorageClass": "STANDARD_IA"},
        {"Days": 90, "StorageClass": "GLACIER"}
      ],
      "Expiration": {"Days": 365},
      "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
      "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": 7}
    },
    {
      "ID": "clean-delete-markers",
      "Status": "Enabled",
      "Filter": {"Prefix": ""},
      "Expiration": {"ExpiredObjectDeleteMarker": true}
    }
  ]
}
```
```bash title="Apply" lab
aws s3api put-bucket-lifecycle-configuration --bucket acme-data-eu --lifecycle-configuration file://lifecycle.json
aws s3api get-bucket-lifecycle-configuration --bucket acme-data-eu --query 'Rules[].ID'
```
:::warn
Transitioning many tiny objects to IA or Glacier can cost more than it saves because of per-object fees and the 128 KB minimum billable size. Filter by size and test with a small prefix.
:::
@check
Why add AbortIncompleteMultipartUpload? || Failed multipart uploads leave hidden parts that you pay for until they are aborted.
@end

@concept Versioning plus lifecycle in Terraform
@plain
Treat bucket configuration as code so that versioning and retention are consistent and reviewed.
@problem
Console changes drift and nobody knows why a bucket keeps data forever.
@does
- Provider v4 and later split settings into separate resources (`aws_s3_bucket_versioning`, `aws_s3_bucket_lifecycle_configuration`).
- Lifecycle rules depend on versioning when they use noncurrent actions.
- Use modules for standard buckets: logs, backups, data lake, static site.
@diagram layers
caption: A bucket module
layers:
  - {label: "Module inputs", nodes: ["name|bucket name|plain", "retention days|per type|plain"]}
  - {label: "Resources", nodes: ["Bucket|aws_s3_bucket|app", "Versioning|enabled|ok", "Lifecycle|tiering and expiry|info", "Encryption and block public|baseline|cp"]}
@h Resources
```hcl title="lifecycle.tf"
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket     = aws_s3_bucket.data.id
  depends_on = [aws_s3_bucket_versioning.data]

  rule {
    id     = "logs"
    status = "Enabled"
    filter {
      prefix = "logs/"
    }
    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
    expiration {
      days = 365
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
```
@end

@concept S3 Inventory and Storage Lens
@plain
Listing a billion objects through the API is slow and expensive. **Inventory** delivers a scheduled report file; **Storage Lens** shows usage and activity trends across accounts.
@problem
You cannot optimise or audit what you cannot see: which prefixes are huge, which objects are unencrypted or cold.
@does
- **S3 Inventory**: daily or weekly CSV, ORC or Parquet listing with size, class, encryption, replication state and more, delivered to another bucket. Query with Athena.
- **S3 Storage Lens**: dashboards for the organization with metrics on bytes, request rates, incomplete multipart uploads, noncurrent versions, and recommendations; advanced metrics are paid.
- **Storage Class Analysis** suggests when to move data to IA.
- CloudWatch request metrics (opt in per prefix) give 4xx, 5xx and latency.
@diagram flow
caption: Understanding a large bucket
nodes:
  - "Inventory file|every object, daily|info"
  - "Athena|SQL on Parquet|cp"
  - "Findings|cold data, no encryption|warn"
  - "Lifecycle or Batch job|fix|ok"
@h Enable inventory
```bash title="Inventory configuration" lab
aws s3api put-bucket-inventory-configuration --bucket acme-data-eu --id weekly --inventory-configuration '{
  "Id":"weekly","IsEnabled":true,"IncludedObjectVersions":"Current","Schedule":{"Frequency":"Weekly"},
  "Destination":{"S3BucketDestination":{"Bucket":"arn:aws:s3:::acme-inventory","Format":"Parquet","Prefix":"acme-data-eu"}},
  "OptionalFields":["Size","StorageClass","EncryptionStatus","LastModifiedDate"]}'
aws s3api list-bucket-inventory-configurations --bucket acme-data-eu
```
@check
Why use Inventory instead of list-objects for huge buckets? || It produces a scheduled bulk report cheaply, avoiding millions of slow, billed LIST calls.
@end

@concept Batch Operations and cost review
@plain
**S3 Batch Operations** runs one action (copy, tag, restore, invoke a Lambda function, replace ACLs, set Object Lock) across a manifest of objects.
@problem
One-off fleet changes such as re-encrypting existing objects or restoring archives need a reliable bulk mechanism.
@does
- Manifest from an Inventory report or a CSV of keys. Job produces a completion report.
- Typical uses: copy in place to apply new encryption keys, add tags, restore archived data, replicate existing objects.
- Check costs: requests, transfers across Regions, retrieval fees, minimum duration penalties for early deletion in IA and Glacier classes.
- Cost levers: lifecycle, Intelligent-Tiering, fewer small objects (compact logs), same-Region access, gateway endpoint.
@diagram flow
caption: Batch job
numbered: true
nodes:
  - "Inventory manifest|list of objects|info"
  - "Create job|operation and role|cp"
  - "Run|parallel and tracked|app"
  - "Report|succeeded and failed|ok"
@h Job outline
```bash title="Create a tagging job" lab
aws s3control create-job --account-id 111122223333 --no-confirmation-required --priority 10 \
  --role-arn arn:aws:iam::111122223333:role/s3-batch \
  --operation '{"S3PutObjectTagging":{"TagSet":[{"Key":"reviewed","Value":"2026"}]}}' \
  --manifest '{"Spec":{"Format":"S3BatchOperations_CSV_20180820","Fields":["Bucket","Key"]},"Location":{"ObjectArn":"arn:aws:s3:::acme-inventory/manifest.csv","ETag":"example"}}' \
  --report '{"Bucket":"arn:aws:s3:::acme-inventory","Format":"Report_CSV_20180820","Enabled":true,"Prefix":"reports","ReportScope":"AllTasks"}'
```
@end
