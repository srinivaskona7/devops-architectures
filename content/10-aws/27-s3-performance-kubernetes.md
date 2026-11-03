---
title: S3 performance, transfer and use from Kubernetes
minutes: 45
objectives:
  - Design key layouts and clients for high request rates and throughput
  - Use multipart upload, byte-range fetches and Transfer Acceleration appropriately
  - Access S3 from pods through Pod Identity, the Mountpoint CSI driver and endpoints
---
S3 scales to very high request rates per prefix, but only if your clients are built to take advantage of that.

@concept Request rates and prefixes
@plain
S3 scales automatically per **prefix**. Each prefix supports thousands of requests per second, and you can use many prefixes in parallel.
@problem
A single hot key or a single client thread becomes the bottleneck and S3 returns 503 Slow Down errors during a spike.
@does
- Documented baseline per prefix is at least 3,500 PUT/COPY/POST/DELETE and 5,500 GET/HEAD requests per second; check the current performance guidelines.
- Spread load across prefixes when you need more. Random hash prefixes are no longer required for performance but help spread very heavy workloads.
- Retry with exponential backoff and jitter; the AWS SDKs do this for you.
- Parallelise requests and reuse HTTP connections.
@diagram flow
caption: Scaling a read workload
nodes:
  - "One prefix|thousands of requests per second|info"
  - "More prefixes|parallel partitions|app"
  - "Spiky load|503 Slow Down|warn"
  - "Backoff and retry|SDK default|ok"
@h Tune the CLI
```bash title="AWS CLI transfer settings" lab
aws configure set default.s3.max_concurrent_requests 32
aws configure set default.s3.multipart_threshold 64MB
aws configure set default.s3.multipart_chunksize 32MB
aws s3 cp s3://acme-data-eu/big/dataset.tar ./dataset.tar
```
@check
What should clients do on a 503 Slow Down? || Retry with exponential backoff and jitter and spread keys across prefixes.
@end

@concept Multipart upload and byte-range fetches
@plain
Large objects are uploaded in parts in parallel, and downloaded in ranges in parallel.
@problem
A single stream is limited by one connection's throughput and a failure restarts the whole transfer.
@does
- Multipart: parts of 5 MiB to 5 GiB, up to 10,000 parts; the final object up to 5 TB. Failed parts retry individually.
- Always add a lifecycle rule to abort stale multipart uploads.
- Byte-range GETs fetch pieces in parallel (8 to 16 MiB chunks are typical) and let you read just the footer of a Parquet file.
- Use **additional checksums** (CRC32, CRC32C, SHA-1, SHA-256) for end-to-end integrity; the SDK computes CRC by default in recent versions.
@diagram flow
caption: Parallel multipart
nodes:
  - "Split file|parts of 64 MB|plain"
  - "Upload in parallel|many connections|app"
  - "Complete|S3 assembles|cp"
  - "Verify|checksum|ok"
@h Python transfer config
```python title="Parallel upload with boto3"
import boto3
from boto3.s3.transfer import TransferConfig

cfg = TransferConfig(multipart_threshold=64 * 1024 * 1024,
                     multipart_chunksize=64 * 1024 * 1024,
                     max_concurrency=16, use_threads=True)
s3 = boto3.client("s3")
s3.upload_file("backup.tar.gz", "acme-data-eu", "backups/backup.tar.gz", Config=cfg)

# read only the last 1 MiB of an object
tail = s3.get_object(Bucket="acme-data-eu", Key="backups/backup.tar.gz", Range="bytes=-1048576")["Body"].read()
print(len(tail))
```
```bash title="Clean up stale uploads" lab
aws s3api list-multipart-uploads --bucket acme-data-eu --query 'Uploads[].[Key,Initiated,UploadId]' --output table
aws s3api abort-multipart-upload --bucket acme-data-eu --key backups/old.tar --upload-id EXAMPLEUPLOADID
```
@end

@concept Network path and Transfer Acceleration
@plain
Where your client sits relative to the bucket decides latency and cost. Transfer Acceleration routes uploads through the nearest CloudFront edge.
@problem
Long-distance uploads over the public internet are slow and inconsistent; traffic from private subnets through NAT is expensive.
@does
- Same-Region access from EC2 or EKS is free of data transfer charges; cross-Region and internet egress are billed.
- Use the **S3 gateway endpoint** for private subnets and an endpoint policy to restrict buckets.
- **Transfer Acceleration** (`bucketname.s3-accelerate.amazonaws.com`) helps for far-away clients uploading to a central bucket; extra per GB fee; test with the speed comparison tool.
- **Requester Pays** shifts transfer cost to the downloader for shared datasets.
- Consider CloudFront in front of S3 for repeated public reads.
@diagram cmp
caption: Path choice
cards:
  - {h: "From EKS in same Region", kind: ok, items: ["Gateway endpoint", "No NAT charges", "Free transfer"]}
  - {h: "From far-away clients", kind: info, items: ["Transfer Acceleration", "Or Multi-Region Access Point"]}
  - {h: "Public reads", kind: app, items: ["CloudFront with OAC", "Caching reduces requests"]}
@h Enable acceleration
```bash title="Acceleration" lab
aws s3api put-bucket-accelerate-configuration --bucket acme-data-eu --accelerate-configuration Status=Enabled
aws configure set default.s3.use_accelerate_endpoint true
aws s3 cp ./large.bin s3://acme-data-eu/uploads/large.bin
```
@check
How do you avoid NAT cost for S3 traffic from private subnets? || Add an S3 gateway VPC endpoint and route the subnets to it.
@end

@concept S3 from pods
@plain
Pods access S3 using IAM roles through Pod Identity or IRSA. The **Mountpoint for Amazon S3 CSI driver** can mount a bucket as a file system for read-heavy workloads.
@problem
Applications built for POSIX files cannot call the S3 API directly, and baked-in keys are unsafe.
@does
- Give the service account a role scoped to the bucket and prefix it needs.
- **Mountpoint** supports sequential writes of new objects and fast reads, but not random writes, renames or file locking. Good for ML data loading and batch reads; not a general NFS replacement.
- The CSI driver is installed as an EKS add-on (`aws-mountpoint-s3-csi-driver`) and uses static provisioning of a PersistentVolume pointing to a bucket.
- Cache reads on local disk if the same data is read repeatedly.
@diagram layers
caption: S3 access from a pod
layers:
  - {label: "Pod", nodes: ["App container|reads /data|app"]}
  - {label: "Kubernetes", nodes: ["PVC and PV|Mountpoint CSI|env", "Service account|Pod Identity role|cp"]}
  - {label: "AWS", nodes: ["Gateway endpoint|private path|info", "S3 bucket|prefix scoped|ok"]}
@h Static volume
```yaml title="s3-pv.yaml"
apiVersion: v1
kind: PersistentVolume
metadata:
  name: s3-datasets
spec:
  capacity:
    storage: 1200Gi
  accessModes:
    - ReadWriteMany
  mountOptions:
    - allow-delete
    - region eu-west-1
    - prefix datasets/
  csi:
    driver: s3.csi.aws.com
    volumeHandle: s3-datasets
    volumeAttributes:
      bucketName: acme-data-eu
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: s3-datasets
  namespace: ml
spec:
  accessModes:
    - ReadWriteMany
  storageClassName: ""
  resources:
    requests:
      storage: 1200Gi
  volumeName: s3-datasets
```
:::note
The capacity field is required by Kubernetes but ignored by the driver. Check the add-on documentation for the mount options your version supports.
:::
@end

@concept Choosing an S3 design
@plain
Pulling the section together: a short decision flow for a new bucket.
@problem
Each setting is easy alone, but the combination decides cost, safety and speed.
@does
- Purpose and sensitivity decide encryption and access pattern (SSE-KMS with a customer key for regulated data; SSE-S3 otherwise).
- Data lifetime decides lifecycle and class (Intelligent-Tiering for unknown patterns).
- Recovery goals decide versioning, replication and Object Lock.
- Consumers decide the access path (access points, presigned URLs, CloudFront, gateway endpoint).
- Codify all of it in a module.
@diagram flow
caption: New bucket checklist
numbered: true
nodes:
  - "Block public access|ownership enforced|cp"
  - "Encryption and TLS|SSE-S3 or KMS|info"
  - "Versioning and lifecycle|protect and expire|app"
  - "Replication or lock|if required|warn"
  - "Access path|policy, access point, endpoint|ok"
@choose Backup bucket
Versioning plus lifecycle | any important data | you need immutability against admins
Add Object Lock | compliance or ransomware protection | data must be deletable at will
Add cross-Region replication | regional disaster recovery | data residency forbids copies
@check
Which feature protects against an administrator deleting audit logs? || Object Lock in compliance mode (with retention).
@end
