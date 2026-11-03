---
title: EBS, instance store and instance networking
minutes: 50
objectives:
  - Choose an EBS volume type and set size, IOPS and throughput correctly
  - Take and manage snapshots, encryption and fast restore
  - Explain ENIs, ENA, EFA and the limits that bound a node's pods and bandwidth
---
Storage and network limits decide how an instance really performs. They also explain many Kubernetes surprises, such as pod-per-node limits and slow volume attach.

@concept EBS volume types
@plain
**Amazon EBS** is network-attached block storage that persists independently of the instance. You pick a volume type by the performance profile you need.
@problem
Using the wrong type either wastes money (provisioned IOPS for a log disk) or throttles a database.
@does
- **gp3** (SSD, general purpose): baseline 3,000 IOPS and 125 MiB/s regardless of size, and you can raise IOPS and throughput independently. Default choice. Check current maximums.
- **gp2**: older, IOPS tied to size with burst credits; migrate to gp3.
- **io2 / io2 Block Express**: provisioned IOPS, high durability, for latency-sensitive databases.
- **st1 / sc1** (HDD): throughput-oriented, cheap sequential workloads; cannot be boot volumes.
- Volume is in one AZ and attaches to instances in that AZ only (Multi-Attach only on io1/io2 with restrictions).
@diagram cmp
caption: Choosing a volume type
cards:
  - {h: "gp3", kind: ok, items: ["Default", "IOPS and throughput set separately"]}
  - {h: "io2", kind: app, items: ["Provisioned IOPS", "Critical databases"]}
  - {h: "st1", kind: info, items: ["Throughput HDD", "Logs and big sequential reads"]}
  - {h: "sc1", kind: warn, items: ["Cold HDD", "Rarely accessed data"]}
@h gp3 in Terraform and resizing
```hcl title="ebs.tf"
resource "aws_ebs_volume" "data" {
  availability_zone = "eu-west-1a"
  size              = 200
  type              = "gp3"
  iops              = 6000
  throughput        = 250
  encrypted         = true
  kms_key_id        = aws_kms_key.ebs.arn
}
```
```bash title="Modify live" lab
aws ec2 modify-volume --volume-id vol-0123456789abcdef0 --size 300 --iops 8000 --throughput 300
aws ec2 describe-volumes-modifications --volume-ids vol-0123456789abcdef0 --query 'VolumesModifications[].[ModificationState,Progress]'
sudo growpart /dev/nvme1n1 1 && sudo xfs_growfs -d /mnt/data   # extend partition and filesystem
```
@check
How does gp3 differ from gp2 for performance? || gp3 has a fixed baseline and lets you provision IOPS and throughput independently of size; gp2 ties IOPS to size.
@end

@concept Instance limits on storage throughput
@plain
Each instance type has its own maximum EBS bandwidth and IOPS. A fast volume on a small instance is capped by the instance.
@problem
Teams buy io2 volumes and get no improvement because the instance limit is lower than the volume.
@does
- Effective IOPS = min(volume limit, instance limit). Check `EbsInfo` from `describe-instance-types`.
- Some smaller types have burst bandwidth for limited time; sustained numbers are lower.
- CloudWatch `VolumeQueueLength`, `VolumeThroughputPercentage`, and the instance-level `EBSReadOps` and `EBSIOBalance%` show saturation.
- On Linux, `iostat -x 1` shows `await` and `%util`.
@diagram flow
caption: The slowest link wins
nodes:
  - "Application IO|queue depth|app"
  - "Instance EBS limit|per type|cp"
  - "Volume limit|type and settings|info"
  - "Achieved IOPS|minimum of the two|ok"
@h Check limits
```bash title="Compare" lab
aws ec2 describe-instance-types --instance-types m7g.large m7g.4xlarge \
  --query 'InstanceTypes[].[InstanceType,EbsInfo.EbsOptimizedInfo.BaselineIops,EbsInfo.EbsOptimizedInfo.MaximumIops,EbsInfo.EbsOptimizedInfo.BaselineBandwidthInMbps]' --output table
iostat -x 1 3
```
@end

@concept Snapshots, encryption and fast restore
@plain
A **snapshot** is a point-in-time copy of a volume stored in S3-managed storage. Only changed blocks are saved after the first one.
@problem
You need backups, a way to copy data between AZs and Regions, and a template for new volumes.
@does
- Snapshots are incremental, crash-consistent. For databases quiesce first or use application-level backups.
- Automate with **Data Lifecycle Manager** or **AWS Backup**; copy to another account or Region for disaster recovery.
- **Encryption** uses KMS; turn on **EBS encryption by default** per Region in each account. Encrypted snapshots can be shared only with a customer managed key.
- New volumes load data lazily from snapshots; **fast snapshot restore** removes the first-read latency (extra cost).
- **Recycle Bin** can recover accidentally deleted snapshots.
@diagram flow
caption: Backup chain
numbered: true
nodes:
  - "Volume|in AZ a|app"
  - "Snapshot|incremental|info"
  - "Copy|other Region or account|cp"
  - "Restore|new volume in any AZ|ok"
@h Policies
```bash title="Default encryption and snapshots" lab
aws ec2 enable-ebs-encryption-by-default
aws ec2 get-ebs-encryption-by-default
aws ec2 create-snapshot --volume-id vol-0123456789abcdef0 --description "pre-upgrade" \
  --tag-specifications 'ResourceType=snapshot,Tags=[{Key=retain,Value=7d}]'
aws ec2 copy-snapshot --source-region eu-west-1 --source-snapshot-id snap-0123456789abcdef0 --region eu-central-1 --encrypted
```
@check
Why use EBS encryption by default? || Any new volume is encrypted automatically, so nobody can forget to enable it.
@end

@concept Instance store
@plain
**Instance store** is local NVMe or SSD storage physically attached to the host. It is very fast and included in the instance price, but temporary.
@problem
Some workloads need very high IOPS or low latency that networked EBS cannot match, for scratch data, caches, or replicated databases.
@does
- Available only on types with `d` or `i`/`g4ad` style storage; size fixed by type.
- Data survives reboot but not stop, hibernate, terminate or host failure.
- Encrypted at the hardware level on Nitro.
- On Kubernetes use the local static provisioner, or mount as `emptyDir` for scratch, and let the application replicate data.
@diagram cmp
caption: EBS versus instance store
cards:
  - {h: "EBS", kind: ok, items: ["Persistent", "Snapshots", "Network attached", "Moves between instances"]}
  - {h: "Instance store", kind: warn, items: ["Ephemeral", "Very low latency", "Tied to host", "No snapshots"]}
@h Format on boot
```bash title="Mount instance store at first boot" lab
lsblk -o NAME,SIZE,MODEL | grep -i "Instance Storage"
sudo mkfs.xfs /dev/nvme1n1 && sudo mkdir -p /scratch && sudo mount -o noatime /dev/nvme1n1 /scratch
```
:::danger
Do not put the only copy of a database on instance store without replication across hosts and AZs.
:::
@end

@concept ENIs, ENA and EFA
@plain
An **elastic network interface (ENI)** is a virtual network card with private IPs, a MAC and security groups. **ENA** is the high-performance driver on Nitro. **EFA** adds OS-bypass networking for HPC and ML.
@problem
Network throughput, packets per second and the number of IPs you can attach are all bounded by instance type.
@does
- Each type allows a maximum number of ENIs and IPv4 addresses per ENI. This bounds pods per node with the default VPC CNI: roughly `ENIs * (IPs per ENI - 1) + 2`. Verify with the EKS max-pods calculator for your type.
- **Prefix delegation** gives ENIs /28 prefixes so a node can host many more pods.
- Network bandwidth is shown per type; flows to a single destination are limited, and instances have a burst baseline pattern. Check `NetworkInfo` for numbers.
- Security groups can be attached to pods in EKS (security groups for pods) using trunk ENIs.
@diagram layers
caption: Where the pod IPs come from
layers:
  - {label: "Instance", nodes: ["Primary ENI|node IP|app", "Secondary ENIs|up to the type maximum|app"]}
  - {label: "Per ENI", nodes: ["Secondary IPs|one per pod|info", "Or /28 prefixes|prefix delegation|ok"]}
  - {label: "Limit", nodes: ["Max pods|set by ENI math or kubelet|warn"]}
@h Check limits and drivers
```bash title="ENI limits" lab
aws ec2 describe-instance-types --instance-types m7g.large \
  --query 'InstanceTypes[0].NetworkInfo.[MaximumNetworkInterfaces,Ipv4AddressesPerInterface,NetworkPerformance]'
ethtool -i eth0 | head -3      # driver: ena
ethtool -S eth0 | grep -i exceeded   # bw_in_allowance_exceeded and similar counters
kubectl -n kube-system set env daemonset aws-node ENABLE_PREFIX_DELEGATION=true
```
@check
What does the ENA exceeded counter tell you? || The instance hit a network allowance (bandwidth, packets per second, connection tracking), so packets were dropped or queued.
@end
