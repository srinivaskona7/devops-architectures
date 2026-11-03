---
title: EFS and FSx file storage
minutes: 45
objectives:
  - Choose between EBS, EFS, S3 and the FSx family
  - Configure EFS mount targets, access points and throughput modes
  - Pick the right FSx variant for Windows, Lustre, NetApp ONTAP or OpenZFS
---
When many servers or containers need the same files, block storage is not enough. AWS offers managed file systems for each protocol and performance profile.

@concept Storage types compared
@plain
**Block** (EBS) attaches to one instance. **File** (EFS, FSx) is shared over NFS or SMB. **Object** (S3) is accessed over HTTP API.
@problem
Choosing the wrong type leads to poor performance or code rewrites.
@does
- EBS: single instance (Multi-Attach only for some volume types), low latency.
- EFS: elastic shared NFS for Linux, many clients across AZs.
- FSx: managed specialised file systems.
- S3: cheapest for large objects, no POSIX semantics.
@diagram cmp
caption: Which storage
cards:
  - {h: "EBS", kind: info, items: ["One instance", "Low latency", "Snapshots"]}
  - {h: "EFS", kind: ok, items: ["Shared NFS", "Elastic size", "Multi-AZ"]}
  - {h: "FSx", kind: cp, items: ["Windows SMB, Lustre, ONTAP, OpenZFS", "Specialised"]}
  - {h: "S3", kind: app, items: ["Objects", "Cheapest", "No POSIX"]}
@choose Shared storage
EFS | many Linux clients need a growing shared POSIX filesystem | you need SMB or extreme parallel throughput
FSx for Windows | Windows apps need SMB and Active Directory | workloads are Linux only
FSx for Lustre | HPC or ML needs very high throughput with S3 linkage | you need long term durable general storage
S3 | files are written once and read as objects | applications require file locking and POSIX
@check
Which service gives shared NFS across AZs with elastic size? || EFS.
@end

@concept EFS architecture and storage classes
@plain
EFS is a regional NFS 4.x file system with **mount targets** in each AZ subnet. Capacity grows and shrinks automatically.
@problem
Provisioning and resizing shared file servers is manual and a single server is a single point of failure.
@does
- Create one mount target per AZ; clients mount via DNS name or the EFS mount helper.
- Storage classes: Standard (Multi-AZ), One Zone, plus Infrequent Access and Archive tiers via lifecycle policies (check the current class list and prices).
- Encryption at rest with KMS and in transit with TLS through the mount helper.
- Security groups on mount targets must allow TCP 2049 from clients.
@diagram flow
caption: Mounting EFS
nodes:
  - "Clients|EC2, ECS, Lambda, EKS|app"
  - "Mount target|per AZ, port 2049|cp"
  - "EFS file system|regional|ok"
@h Terraform
```hcl title="efs.tf"
resource "aws_efs_file_system" "shared" {
  encrypted = true
  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }
}

resource "aws_efs_mount_target" "az" {
  for_each        = toset(var.private_subnet_ids)
  file_system_id  = aws_efs_file_system.shared.id
  subnet_id       = each.value
  security_groups = [aws_security_group.efs.id]
}
```
```bash title="Mount with the helper" nocheck
sudo mount -t efs -o tls fs-0123456789abcdef0:/ /mnt/shared
```
@check
Which port must the mount target security group allow? || TCP 2049 (NFS).
@end

@concept EFS performance and throughput modes
@plain
EFS has performance behaviour set by its throughput mode: **Elastic**, **Provisioned** or **Bursting**.
@problem
Throughput needs differ between a quiet web content share and a busy analytics job.
@does
- **Elastic** scales throughput up and down with the workload and bills per data transferred; recommended default for spiky or unknown workloads.
- **Provisioned** fixes throughput regardless of stored size and bills for it.
- **Bursting** ties baseline to stored size, with burst credits.
- Latency is higher than EBS (network file system); small file metadata heavy workloads suffer.
- Check the current throughput limits per file system.
@diagram cmp
caption: Throughput modes
cards:
  - {h: "Elastic", kind: ok, items: ["Automatic scaling", "Pay per use", "Default choice"]}
  - {h: "Provisioned", kind: cp, items: ["Fixed MiB per s", "Predictable", "Pay for provisioned"]}
  - {h: "Bursting", kind: info, items: ["Scales with size", "Credits", "Older default"]}
@h Change mode
```bash title="Set elastic throughput" nocheck
aws efs update-file-system --file-system-id fs-0123456789abcdef0 --throughput-mode elastic
```
@end

@concept Access points and permissions
@plain
An **access point** is an application entry into an EFS file system that enforces a root directory and POSIX identity.
@problem
Many apps share one filesystem but must not see each other's data or run as root.
@does
- Each access point fixes a path, UID and GID and creates the directory with given permissions.
- IAM authorisation: the file system policy and `elasticfilesystem:ClientMount` / `ClientWrite` permissions control who may mount.
- Lambda and Fargate attach through access points.
- Use a resource policy to require TLS (`aws:SecureTransport`).
@diagram layers
caption: Access control layers
layers:
  - {label: "Network", nodes: ["Security group|port 2049|info"]}
  - {label: "IAM", nodes: ["File system policy|mount and write|cp"]}
  - {label: "POSIX", nodes: ["Access point|path, UID and GID|ok"]}
@h Policy requiring TLS
```json title="efs-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Deny",
    "Principal": {"AWS": "*"},
    "Action": "*",
    "Condition": {"Bool": {"aws:SecureTransport": "false"}}
  }]
}
```
@check
How can two apps share one EFS yet stay isolated? || Give each its own access point with a distinct path and POSIX identity.
@end

@concept FSx for Windows and NetApp ONTAP
@plain
**FSx for Windows File Server** offers SMB shares with Active Directory. **FSx for NetApp ONTAP** offers NFS, SMB and iSCSI with NetApp features.
@problem
Windows applications and enterprise NAS users need native protocols and features that EFS lacks.
@does
- Windows: integrates with AWS Managed Microsoft AD or self-managed AD, DFS namespaces, shadow copies, Multi-AZ option.
- ONTAP: snapshots, clones, SnapMirror replication, tiering to a capacity pool, multi-protocol. Good for migrating NetApp users.
- Backups through AWS Backup or built-in daily backups.
- Check each variant's current Region availability and throughput capacities.
@diagram flow
caption: Windows file share
nodes:
  - "Windows clients|SMB|app"
  - "FSx Windows|Multi-AZ pair|cp"
  - "Active Directory|auth|ext"
@h Create (CLI shape)
```bash title="FSx Windows" nocheck
aws fsx create-file-system --file-system-type WINDOWS --storage-capacity 1024 \
  --subnet-ids subnet-0aaa subnet-0bbb --storage-type SSD \
  --windows-configuration DeploymentType=MULTI_AZ_1,PreferredSubnetId=subnet-0aaa,ThroughputCapacity=64,ActiveDirectoryId=d-1234567890
```
@end

@concept FSx for Lustre and OpenZFS
@plain
**FSx for Lustre** is a high performance parallel file system for HPC and machine learning. **FSx for OpenZFS** gives NFS with ZFS snapshots and clones.
@problem
Training jobs and simulations read data at rates that standard network file systems cannot sustain.
@does
- Lustre scratch deployments: fastest and cheapest, not replicated. Persistent deployments: replicated within an AZ for longer-term data.
- Data repository association links a path to an S3 bucket: lazy load on first read and export changes back.
- OpenZFS: low latency NFS, instant snapshots and clones, for migrating ZFS or Linux NAS.
- Both are single-AZ options in many configurations; check current deployment types.
@diagram flow
caption: ML training data path
nodes:
  - "S3 data lake|source of truth|ok"
  - "FSx for Lustre|high throughput cache|cp"
  - "GPU cluster|training|app"
@h Link to S3
```bash title="Lustre with S3" nocheck
aws fsx create-file-system --file-system-type LUSTRE --storage-capacity 1200 \
  --subnet-ids subnet-0aaa --lustre-configuration DeploymentType=SCRATCH_2
aws fsx create-data-repository-association --file-system-id fs-0abc --file-system-path /data --data-repository-path s3://ml-datasets/train
```
@check
Which FSx variant is meant for HPC and ML with S3 integration? || FSx for Lustre.
@end

@concept Backups, cost and operating file systems
@plain
Protect shared files with backups, watch growth and pick storage tiers to control cost.
@problem
A shared filesystem tends to accumulate data nobody owns, and one deletion can affect many servers.
@does
- AWS Backup protects EFS and FSx with schedules, retention and cross-account copies.
- EFS lifecycle moves cold files to Infrequent Access; example: 10 TB with 70 percent untouched for 30 days leaves 3 TB in Standard and 7 TB in IA. Compute the monthly cost with the current per-GB prices.
- Monitor `PercentIOLimit`, `BurstCreditBalance`, `ClientConnections` for EFS.
- Replication copies EFS to another Region (read-only target).
@diagram flow
caption: Protect and tier
nodes:
  - "File system|EFS or FSx|cp"
  - "Lifecycle|move cold data|info"
  - "AWS Backup|schedule and copy|ok"
  - "Replica Region|DR copy|ext"
@h Enable backup policy
```bash title="EFS automatic backups" nocheck
aws efs put-backup-policy --file-system-id fs-0123456789abcdef0 --backup-policy Status=ENABLED
```
@end
