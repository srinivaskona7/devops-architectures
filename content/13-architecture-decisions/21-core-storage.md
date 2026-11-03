---
title: Core services 6 to 10, storage and backup
minutes: 60
objectives:
  - Compare object, block, file, archive and backup services
  - State when to choose each service
  - List the limits to verify in the current docs
---
Storage choices are driven by access pattern. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
Match the shape to how the data is read and written. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Storage shapes
layers:
  - {label: "Services on this page", nodes: ["Object storage|S3|app", "Block storage|EBS|info", "Shared file storage|EFS|env", "Archive tiers|S3 Glacier|ok", "Backup|AWS Backup|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 6 | Object storage | S3 | Blob Storage | Cloud Storage |
| 7 | Block storage | EBS | Managed Disks | Persistent Disk or Hyperdisk |
| 8 | Shared file storage | EFS | Azure Files | Filestore |
| 9 | Archive tiers | S3 Glacier | Blob Archive tier | Cloud Storage Archive class |
| 10 | Backup | AWS Backup | Azure Backup | Backup and DR Service |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 6. Object storage
@plain
A flat store of files called objects, addressed by bucket or container and key, accessed over HTTPS.
@problem
File systems and disks do not scale to billions of files, global access and cheap durable retention.
@does
- **Names**: AWS S3; Azure Blob Storage; GCP Cloud Storage.
- **What it is**: Stores objects with versioning, lifecycle rules, encryption, access policies, event notifications and several storage classes.
- **Choose it when**: Backups, logs, media, data lakes and static websites; Any data read by many services; Source for CDN and analytics.
- **Check in the current docs**: Bucket or account naming rules are global, so names must be unique; Public access should be blocked by default and checked; Request, retrieval and egress charges can exceed storage cost.
@diagram cmp
caption: Object storage on the three clouds
cards:
  - {h: "S3", kind: warn, items: ["Storage classes, Object Lock, bucket policies"]}
  - {h: "Blob Storage", kind: info, items: ["Storage accounts, access tiers, immutability policies"]}
  - {h: "Cloud Storage", kind: ok, items: ["Buckets, classes, uniform bucket-level access"]}
@h Example
A data lake keeps raw logs in a bucket, moves them to a cheaper class after 30 days, and expires them after a year.
@h CLI on each cloud
```bash title="AWS CLI, Object storage" nocheck
aws s3 mb s3://demo-bucket-123456
aws s3 cp report.csv s3://demo-bucket-123456/raw/
```
```bash title="Azure CLI, Object storage" nocheck
az storage account create --name stdemo123 --resource-group rg-demo --sku Standard_LRS
az storage container create --account-name stdemo123 --name raw --auth-mode login
az storage blob upload --account-name stdemo123 --container-name raw --name report.csv --file report.csv --auth-mode login
```
```bash title="gcloud, Object storage" nocheck
gcloud storage buckets create gs://demo-bucket-123456 --location=europe-west1
gcloud storage cp report.csv gs://demo-bucket-123456/raw/
```
@check
What is the usual hidden cost of object storage? || Requests, retrieval and data egress rather than the stored gigabytes.
@end

@concept 7. Block storage
@plain
A virtual hard disk that attaches to one VM and survives when the VM stops.
@problem
VMs need fast, durable, resizable disks with snapshots, separate from the machine's lifetime.
@does
- **Names**: AWS EBS; Azure Managed Disks; GCP Persistent Disk or Hyperdisk.
- **What it is**: Provides volumes with selectable performance types, encryption, snapshots and online resize.
- **Choose it when**: Boot and data disks for VMs; Databases on VMs and Kubernetes persistent volumes; Low-latency random I/O.
- **Check in the current docs**: Disks are zonal or regional resources, so a volume cannot move across zones without a snapshot; IOPS and throughput are tied to type and size, so check the current docs; Unattached disks still cost money.
@diagram cmp
caption: Block storage on the three clouds
cards:
  - {h: "EBS", kind: warn, items: ["gp3 and io2 volume types, snapshots"]}
  - {h: "Managed Disks", kind: info, items: ["Premium SSD, Ultra and Standard SSD disks"]}
  - {h: "Persistent Disk or Hyperdisk", kind: ok, items: ["Balanced, SSD and Hyperdisk options"]}
@h Example
A database VM uses a provisioned-IOPS volume with hourly snapshots and an alert when IOPS reach 80 percent of the limit.
@h CLI on each cloud
```bash title="AWS CLI, Block storage" nocheck
aws ec2 create-volume --availability-zone eu-west-1a --size 100 --volume-type gp3
```
```bash title="Azure CLI, Block storage" nocheck
az disk create --resource-group rg-demo --name data1 --size-gb 100 --sku Premium_LRS
```
```bash title="gcloud, Block storage" nocheck
gcloud compute disks create data1 --zone=europe-west1-b --size=100GB --type=pd-balanced
```
@check
Can a zonal disk be attached to a VM in another zone? || No, you snapshot it and create a new disk in the target zone.
@end

@concept 8. Shared file storage
@plain
A network file share that many machines can mount at once using NFS or SMB.
@problem
Block disks attach to one machine, but some applications need the same files visible on many servers or pods.
@does
- **Names**: AWS EFS; Azure Azure Files; GCP Filestore.
- **What it is**: Provides managed shared file systems with POSIX or SMB semantics, backup and encryption.
- **Choose it when**: Shared content, home directories and CMS uploads; ReadWriteMany volumes in Kubernetes; Lift-and-shift apps expecting a file share.
- **Check in the current docs**: Latency is higher than local block disks; Protocol support differs, for example SMB versus NFS, so check each service; Throughput modes and minimum sizes affect cost.
@diagram cmp
caption: Shared file storage on the three clouds
cards:
  - {h: "EFS", kind: warn, items: ["NFS, elastic throughput, access points"]}
  - {h: "Azure Files", kind: info, items: ["SMB and NFS shares, share snapshots"]}
  - {h: "Filestore", kind: ok, items: ["NFS tiers such as zonal and regional"]}
@h Example
Several web servers mount one share for user uploads, while a nightly job backs it up.
@h CLI on each cloud
```bash title="AWS CLI, Shared file storage" nocheck
aws efs create-file-system --creation-token demo-efs --encrypted
```
```bash title="Azure CLI, Shared file storage" nocheck
az storage share-rm create --resource-group rg-demo --storage-account stdemo123 --name shared --quota 100
```
```bash title="gcloud, Shared file storage" nocheck
gcloud filestore instances create demo-fs --zone=europe-west1-b --tier=BASIC_HDD --file-share=name=share1,capacity=1TB --network=name=default
```
@check
Why choose shared files over block disks? || Many servers must read and write the same files at once.
@end

@concept 9. Archive tiers
@plain
Very cheap storage for data you almost never read, with slower and costlier retrieval.
@problem
Compliance and history require keeping data for years, and normal storage prices make that expensive.
@does
- **Names**: AWS S3 Glacier; Azure Blob Archive tier; GCP Cloud Storage Archive class.
- **What it is**: Moves old objects to a cold class by lifecycle rules, with minimum storage durations and retrieval fees.
- **Choose it when**: Compliance records and old logs; Backups kept for years; Raw data kept only in case of audit.
- **Check in the current docs**: Minimum storage duration charges apply if you delete early, so check the current docs; Retrieval can take minutes to hours on some tiers; Small objects can cost more due to per-object overhead.
@diagram cmp
caption: Archive tiers on the three clouds
cards:
  - {h: "S3 Glacier", kind: warn, items: ["Glacier Instant, Flexible and Deep Archive classes"]}
  - {h: "Blob Archive tier", kind: info, items: ["Archive tier with rehydration"]}
  - {h: "Cloud Storage Archive class", kind: ok, items: ["Archive class with immediate access but retrieval fees"]}
@h Example
Audit logs older than 90 days move to an archive class and are expired after seven years.
@h CLI on each cloud
```bash title="AWS CLI, Archive tiers" nocheck
aws s3api put-bucket-lifecycle-configuration --bucket demo-bucket-123456 --lifecycle-configuration '{"Rules":[{"ID":"archive","Status":"Enabled","Filter":{"Prefix":"logs/"},"Transitions":[{"Days":90,"StorageClass":"GLACIER"}]}]}'
```
```bash title="Azure CLI, Archive tiers" nocheck
az storage blob set-tier --account-name stdemo123 --container-name raw --name old.log --tier Archive --auth-mode login
```
```bash title="gcloud, Archive tiers" nocheck
gcloud storage objects update gs://demo-bucket-123456/logs/old.log --storage-class=ARCHIVE
```
@check
What happens if you delete archived data early? || You are charged for the remaining minimum storage duration.
@end

@concept 10. Backup
@plain
A central service that takes scheduled, policy-driven copies of many resource types and keeps them for a set time.
@problem
Ad hoc snapshots are forgotten, inconsistent and hard to prove during an audit.
@does
- **Names**: AWS AWS Backup; Azure Azure Backup; GCP Backup and DR Service.
- **What it is**: Defines plans with schedule, retention, vault and cross-region or cross-account copies, and supports restore tests.
- **Choose it when**: Compliance-driven retention across many services; Protecting VMs, databases and file shares uniformly; Ransomware resilience with immutable vaults.
- **Check in the current docs**: Supported resource types differ, so check the current docs; Backups are not recovery until a restore has been tested; Cross-region copies add storage and transfer cost.
@diagram cmp
caption: Backup on the three clouds
cards:
  - {h: "AWS Backup", kind: warn, items: ["Backup plans, vaults, Vault Lock"]}
  - {h: "Azure Backup", kind: info, items: ["Recovery Services and Backup vaults, policies"]}
  - {h: "Backup and DR Service", kind: ok, items: ["Backup vaults and backup plans"]}
@h Example
A policy backs up all VMs tagged backup=daily, keeps 35 days, and copies weekly backups to a second region.
@h CLI on each cloud
```bash title="AWS CLI, Backup" nocheck
aws backup create-backup-vault --backup-vault-name demo-vault
aws backup list-backup-plans
```
```bash title="Azure CLI, Backup" nocheck
az backup vault create --resource-group rg-demo --name demo-vault --location westeurope
az backup protection enable-for-vm --resource-group rg-demo --vault-name demo-vault --vm web1 --policy-name DefaultPolicy
```
```bash title="gcloud, Backup" nocheck
gcloud backup-dr backup-vaults list --location=europe-west1
```
@check
What proves a backup works? || A successful, timed restore test.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Using object storage as a POSIX file system.
- Archiving data you read monthly.
- Counting snapshots as tested backups.
- Always confirm limits, prices and regional availability in the current documentation before committing.
@diagram flow
caption: A safe habit before adopting any service
nodes:
  - "Define need|workload, size, latency|plain"
  - "Map services|three cloud names|info"
  - "Check docs|limits, price, regions|warn"
  - "Prototype|measure on real data|app"
  - "Decide|record in an ADR|ok"
@h Habit as a checklist
```yaml title="service-evaluation.yaml" nocheck
service: Object storage
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

