---
title: Disks, Filestore and Cloud Storage
minutes: 60
objectives:
  - Choose between Persistent Disk, Hyperdisk, Filestore and Cloud Storage
  - Configure bucket classes, lifecycle rules, Autoclass and versioning
  - Share objects safely with uniform bucket-level access and signed URLs
---
Google Cloud storage splits into block (disks), file (Filestore) and object (Cloud Storage). Each has an AWS equivalent but with different performance and scope rules.

@concept Persistent Disk
@plain
**Persistent Disk (PD)** is network block storage for VMs and GKE volumes. It is durable and independent of the VM.
@problem
VM boot and data volumes must survive VM deletion and be resizable.
@does
- Types: `pd-standard` (HDD), `pd-balanced` (default SSD), `pd-ssd`, `pd-extreme`. Check which are supported by your machine series.
- Zonal disks live in one zone. **Regional PDs** replicate synchronously across two zones in a region.
- Resize online (grow only), snapshot, clone, and attach read-only to many VMs.
- Performance scales with size and vCPU count.
- **AWS equivalent**: EBS gp3, io2. Main difference: regional PD offers built-in cross-zone replication, which EBS does not.
@diagram flow
caption: Disk attach and replication
nodes:
  - "VM|zone b|vm"
  - "Zonal PD|zone b|db"
  - "Regional PD|zone b and c|ok"
  - "Failover|attach in zone c|warn"
@h Create and attach
```bash title="Disks" lab
gcloud compute disks create shop-data --size=200GB --type=pd-balanced --zone=europe-west1-b
gcloud compute instances attach-disk shop-vm-1 --disk=shop-data --zone=europe-west1-b
gcloud compute disks create shop-data-r --size=200GB --type=pd-ssd --region=europe-west1 \
  --replica-zones=europe-west1-b,europe-west1-c
```
@check
Which disk survives a zone loss? || A regional Persistent Disk.
@end

@concept Hyperdisk
@plain
**Hyperdisk** is the newer block storage where you provision capacity, IOPS and throughput separately.
@problem
With PD, getting more IOPS means buying more capacity.
@does
- Types include Hyperdisk Balanced, Throughput, Extreme and ML; support depends on machine series (C3, N4 and others). Check the current docs.
- You set `--provisioned-iops` and `--provisioned-throughput` and change them online.
- Storage pools share capacity and performance among disks.
- **AWS equivalent**: gp3 and io2 Block Express. Main difference: gp3 is comparable, and Hyperdisk pools have no direct EBS counterpart.
@diagram cmp
caption: PD versus Hyperdisk
cards:
  - {h: "Persistent Disk", kind: info, items: ["Performance follows size", "Regional replication option"]}
  - {h: "Hyperdisk", kind: app, items: ["Provision IOPS and throughput", "Storage pools", "Newer machine series"]}
@h Create
```bash title="Hyperdisk Balanced" lab
gcloud compute disks create shop-hd --type=hyperdisk-balanced --size=500GB \
  --provisioned-iops=6000 --provisioned-throughput=300 --zone=europe-west1-b
```
@end

@concept Snapshots and snapshot schedules
@plain
A **snapshot** is an incremental backup of a disk. A **schedule** creates and expires them automatically.
@problem
Disk loss or corruption needs restorable backups without manual work.
@does
- First snapshot is full, later ones store changes. Snapshots are global and can restore to any zone or region.
- Storage location (regional or multi-regional) is configurable.
- Resource policy with `--daily-schedule` and `--max-retention-days` attaches to disks.
- Application-consistent snapshots need quiescing (guest flush).
- **AWS equivalent**: EBS snapshots with Data Lifecycle Manager. Main difference: schedules are resource policies you attach to disks.
@diagram flow
caption: Scheduled backups
nodes:
  - "Schedule policy|daily, keep 14 days|cp"
  - "Disk|attached policy|db"
  - "Snapshot|incremental|ok"
  - "Restore|new disk in any zone|app"
@h Schedule
```bash title="Snapshot schedule" lab
gcloud compute resource-policies create snapshot-schedule daily-14 --region=europe-west1 \
  --daily-schedule --start-time=01:00 --max-retention-days=14 --on-source-disk-delete=keep-auto-snapshots
gcloud compute disks add-resource-policies shop-data --zone=europe-west1-b --resource-policies=daily-14
```
@check
Are snapshots tied to the zone of the disk? || No. They are global and can restore anywhere.
@end

@concept Filestore
@plain
**Filestore** is managed NFS file storage that many VMs or Pods can mount at the same time.
@problem
Applications that need a shared POSIX file system (CMS uploads, legacy apps) cannot use a block disk shared across zones.
@does
- Tiers include Basic HDD and SSD, Zonal, Regional and Enterprise. Higher tiers add capacity, performance and availability; check current limits.
- Mounts over your VPC via private services access or PSC, using standard NFS v3 or v4.1.
- Backups and snapshots are supported on some tiers. GKE has a Filestore CSI driver (`filestore.csi.storage.gke.io`).
- **AWS equivalent**: EFS (and FSx for NFS). Main difference: Filestore capacity is provisioned in advance, whereas EFS is elastic.
@diagram flow
caption: Shared mount
nodes:
  - "Pod A|zone b|app"
  - "Pod B|zone c|app"
  - "Filestore|NFS share|db"
@h Create and mount
```bash title="Filestore" lab
gcloud filestore instances create shop-share --zone=europe-west1-b --tier=BASIC_SSD \
  --file-share=name=uploads,capacity=2.5TB --network=name=shop-net
# On a VM, as root
mount -o rw,intr 10.0.0.2:/uploads /mnt/uploads
```
@end

@concept Cloud Storage buckets and storage classes
@plain
**Cloud Storage** is object storage. Objects live in **buckets** with a location and a default **storage class**.
@problem
You need durable, cheap, unlimited storage for files, backups, static sites and data lakes.
@does
- Location types: region, dual-region and multi-region. Dual-region offers turbo replication option.
- Classes: **Standard**, **Nearline** (30 days minimum), **Coldline** (90), **Archive** (365). All have the same latency and API; they differ in storage price, retrieval fee and minimum duration.
- Bucket names are globally unique. Strong consistency for all operations.
- **AWS equivalent**: S3 with storage classes. Main difference: Archive is still millisecond access, with no restore wait.
@diagram cmp
caption: Classes by access pattern
cards:
  - {h: "Standard", kind: ok, items: ["Hot data", "No minimum duration"]}
  - {h: "Nearline", kind: info, items: ["Monthly access", "30 day minimum"]}
  - {h: "Coldline", kind: warn, items: ["Quarterly access", "90 day minimum"]}
  - {h: "Archive", kind: bad, items: ["Yearly access", "365 day minimum", "Still online"]}
@h Create
```bash title="Bucket" lab
gcloud storage buckets create gs://shop-assets-123 --location=europe-west1 \
  --default-storage-class=STANDARD --uniform-bucket-level-access --public-access-prevention
gcloud storage cp ./dist/* gs://shop-assets-123/static/ --recursive
gcloud storage ls -L gs://shop-assets-123
```
@check
Does Archive class require a restore request before reading? || No. It is readable immediately but has a high retrieval cost.
@end

@concept Lifecycle rules and Autoclass
@plain
**Lifecycle rules** change class or delete objects by age or condition. **Autoclass** moves each object between classes automatically based on access.
@problem
Data goes cold. Keeping it all in Standard wastes money, and manual tiering is error-prone.
@does
- Rule conditions: `age`, `createdBefore`, `matchesPrefix`, `numNewerVersions`, `isLive`, `daysSinceNoncurrentTime`. Actions: `Delete`, `SetStorageClass`, `AbortIncompleteMultipartUpload`.
- Autoclass moves objects to colder classes when unused and back to Standard when read, with no retrieval fees for transitions. It is enabled at bucket level; check the current docs for terminal class options.
- Use lifecycle for predictable rules, Autoclass for unpredictable access.
- **AWS equivalent**: S3 Lifecycle and Intelligent-Tiering. Main difference: very similar; Autoclass applies to the whole bucket.
@diagram flow
caption: Age based tiering
nodes:
  - "Standard|0 to 30 days|ok"
  - "Nearline|30 to 90 days|info"
  - "Coldline|90 days on|warn"
  - "Delete|after 3 years|bad"
@h Lifecycle JSON
```json title="lifecycle.json"
{
  "rule": [
    {"action": {"type": "SetStorageClass", "storageClass": "NEARLINE"}, "condition": {"age": 30, "matchesStorageClass": ["STANDARD"]}},
    {"action": {"type": "SetStorageClass", "storageClass": "COLDLINE"}, "condition": {"age": 90, "matchesStorageClass": ["NEARLINE"]}},
    {"action": {"type": "Delete"}, "condition": {"age": 1095}}
  ]
}
```
```bash title="Apply or use Autoclass" lab
gcloud storage buckets update gs://shop-assets-123 --lifecycle-file=lifecycle.json
gcloud storage buckets update gs://shop-logs-123 --enable-autoclass
```
@end

@concept Object versioning, retention and soft delete
@plain
Versioning keeps old generations of an object. Retention policies and soft delete protect from deletion.
@problem
Overwrites and accidental deletes should be recoverable, and compliance may require immutability.
@does
- With versioning on, overwrites and deletes create noncurrent versions; pair with a lifecycle rule to expire them.
- **Soft delete** keeps deleted objects for a retention window (default seven days; check the current default) even without versioning.
- **Retention policy** and bucket lock prevent deletion before a period; object holds protect individual objects.
- **AWS equivalent**: S3 Versioning, Object Lock. Main difference: each object has a numeric generation, and soft delete is a separate feature.
@diagram flow
caption: Overwrite with versioning
nodes:
  - "Upload v1|generation 1|app"
  - "Upload v2|v1 becomes noncurrent|info"
  - "Delete|live version hidden|warn"
  - "Restore|copy old generation|ok"
@h Use versions
```bash title="Versioning" lab
gcloud storage buckets update gs://shop-assets-123 --versioning
gcloud storage ls --all-versions gs://shop-assets-123/static/app.js
gcloud storage cp gs://shop-assets-123/static/app.js#1700000000000000 gs://shop-assets-123/static/app.js
```
@check
How do you stop noncurrent versions from growing forever? || A lifecycle rule using numNewerVersions or age on noncurrent objects.
@end

@concept Access control and signed URLs
@plain
**Uniform bucket-level access (UBLA)** disables per-object ACLs so only IAM controls access. **Signed URLs** give time-limited access to one object without a Google identity.
@problem
Mixed ACLs and IAM are hard to audit, and users without accounts need temporary downloads or uploads.
@does
- Enable UBLA and **public access prevention** by default (org policies exist for both).
- Grant `roles/storage.objectViewer` or `objectAdmin` to groups or service accounts on the bucket or by IAM condition.
- Signed URL V4 can last up to seven days. Sign with a service account key or, better, with the IAM Credentials API (`signBlob`) via impersonation.
- **AWS equivalent**: S3 bucket policies, Block Public Access and presigned URLs. Main difference: ACLs are legacy in both.
@diagram seq
caption: Signed URL download
actors: ["App backend|service account|app", "Browser|end user|ext", "Cloud Storage|bucket|db"]
steps:
  - "0>0: sign URL with expiry | tls"
  - "0>1: return signed URL | resp"
  - "1>2: GET object with signature | req"
  - "2>1: object bytes | resp"
@h Sign without a key
```bash title="Signed URL" lab
gcloud storage sign-url gs://shop-assets-123/invoices/1001.pdf --duration=15m \
  --impersonate-service-account=shop-api@shop-dev-123456.iam.gserviceaccount.com
gcloud storage buckets add-iam-policy-binding gs://shop-assets-123 \
  --member="serviceAccount:shop-api@shop-dev-123456.iam.gserviceaccount.com" --role="roles/storage.objectUser"
```
:::danger
`allUsers` bindings on a bucket make it public. Keep public access prevention on and serve public content through the CDN or load balancer.
:::
@end
