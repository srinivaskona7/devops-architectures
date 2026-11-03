---
title: Storage, filesystems and LVM
minutes: 45
objectives:
  - Describe block devices, partitions and filesystems and how they are mounted
  - Grow storage online with LVM and diagnose full disks and inodes
  - Choose between ext4 and XFS, and explain RAID and quotas
---
Everything stateful eventually lands on a disk. Knowing the layers between "an application wrote a file" and "bits on a device" lets you grow volumes safely and recognise the usual ways storage fills up.

@concept Block devices, partitions and filesystems
@plain
A **block device** is raw storage (`/dev/nvme0n1`). A **partition** is a slice of it. A **filesystem** is the structure (files, folders, permissions) written onto it so the kernel can present it as a tree.
@problem
Raw storage has no names or folders. Without a filesystem you cannot store files, and without understanding the layers you cannot tell which one is full or failing.
@does
- `lsblk` shows devices and what is mounted where; `blkid` shows filesystem types and UUIDs.
- Partition tables are GPT (modern) or MBR (legacy, limited to 2 TB).
- `mkfs.ext4` or `mkfs.xfs` creates a filesystem; `mount` attaches it at a directory.
- Mount by **UUID** in `/etc/fstab`, since device names such as `/dev/sdb` can change between boots.
@diagram layers
caption: From disk to file
layers:
  - {label: "Application", nodes: ["open, write, read|file API|app"]}
  - {label: "Filesystem", nodes: ["ext4 or XFS|names, permissions, journal|env"]}
  - {label: "Volume layer", nodes: ["LVM or partition|slices and resizing|cp"]}
  - {label: "Block device", nodes: ["/dev/nvme0n1|EBS volume, SSD, disk|plain"]}
@h Preparing a new disk
```bash title="Partition, format and mount" nocheck
lsblk -f                                  # find the new device, e.g. nvme1n1
sudo parted -s /dev/nvme1n1 mklabel gpt mkpart data 0% 100%
sudo mkfs.xfs /dev/nvme1n1p1
sudo mkdir -p /data && sudo mount /dev/nvme1n1p1 /data
sudo blkid /dev/nvme1n1p1                 # copy the UUID
echo 'UUID=<uuid-here> /data xfs defaults,nofail 0 2' | sudo tee -a /etc/fstab
sudo mount -a && df -hT /data             # a bad fstab line shows up here, not at the next boot
```
:::warn
Run `mount -a` after editing `/etc/fstab`. An invalid line can stop the machine booting. Use `nofail` for non-critical data disks.
:::
@check
Why mount by UUID? || Device names like /dev/sdb depend on detection order and can change; the UUID is stored in the filesystem itself.
@end

@concept Filesystems: ext4 and XFS
@plain
Both are journalling filesystems: they write intended changes to a log first, so a crash does not corrupt the structure.
@problem
Choosing a filesystem by habit leads to surprises, such as being unable to shrink XFS or running out of inodes on ext4.
@does
- **ext4**: the default for many distributions, can grow and shrink (offline), simple, mature.
- **XFS**: default on RHEL family, excellent with large files and parallel I/O, grows online but **cannot shrink**.
- Both support extended attributes and ACLs. Neither replaces backups.
- Tools: `fsck` / `xfs_repair` repair an unmounted filesystem; `tune2fs` and `xfs_info` show settings.
@diagram cmp
caption: ext4 versus XFS
cards:
  - {h: "ext4", kind: app, items: ["Can shrink offline and grow", "Fixed inode count set at creation", "Good general default"]}
  - {h: "XFS", kind: env, items: ["Grows online, never shrinks", "Inodes allocated dynamically", "Strong for big files and databases"]}
@choose Filesystem choice
ext4 | you may need to shrink volumes or want maximum compatibility | you expect billions of small files
XFS | large volumes, databases, RHEL family defaults | you expect to reduce the size later
@h Growing a filesystem
```bash title="Grow after enlarging the volume" nocheck
sudo growpart /dev/nvme0n1 1               # extend the partition (cloud-utils)
sudo resize2fs /dev/nvme0n1p1              # ext4: grow online
sudo xfs_growfs /                          # XFS: give it the mount point
df -h /
```
@end

@concept Logical Volume Manager (LVM)
@plain
LVM adds a flexible layer between disks and filesystems. You pool disks into a **volume group**, then carve out **logical volumes** that can grow, shrink or move without repartitioning.
@problem
Fixed partitions force guesses about future size. Running out of space then means downtime, copying data or buying a new disk.
@does
- **PV** (physical volume): a disk or partition given to LVM. **VG** (volume group): the pool made from PVs. **LV** (logical volume): a slice of the pool with a filesystem on it.
- `lvextend -r` grows an LV and its filesystem in one step.
- Snapshots give a point-in-time view for consistent backups.
- Adding a new disk to the VG gives more room without touching existing data.
@diagram flow
caption: Pooling disks and slicing volumes
numbered: true
nodes:
  - "Disk /dev/nvme1n1|pvcreate|plain"
  - "Volume group vg_data|vgcreate or vgextend|cp"
  - "Logical volume lv_db|lvcreate|app"
  - "Filesystem + mount|mkfs, mount|ok"
@h Create and extend
```bash title="LVM workflow" nocheck
sudo pvcreate /dev/nvme1n1
sudo vgcreate vg_data /dev/nvme1n1
sudo lvcreate -n lv_db -L 100G vg_data
sudo mkfs.xfs /dev/vg_data/lv_db && sudo mount /dev/vg_data/lv_db /var/lib/db
# later: add another disk and grow online
sudo vgextend vg_data /dev/nvme2n1
sudo lvextend -r -L +50G /dev/vg_data/lv_db       # -r also grows the filesystem
sudo vgs; sudo lvs                                 # check free space
```
@check
You added a disk to the VG. What is left to do to give the database more room? || Extend the logical volume and its filesystem, for example lvextend -r.
@end

@concept Full disks and inodes
@plain
A filesystem can be "full" in two ways: out of **space** (bytes) or out of **inodes** (file records). Deleted files can also still hold space if a process keeps them open.
@problem
`No space left on device` while `df -h` shows free space is a classic puzzle. The cause is usually inodes or open deleted files.
@does
- `df -h` shows space, `df -i` shows inodes. Millions of tiny files exhaust inodes first.
- `du -xh --max-depth=1 /var | sort -h` finds which directory is large.
- `lsof +L1` lists files deleted but still open, holding space until the process closes them or restarts.
- Common culprits: logs without rotation, container image layers, core dumps, package caches.
@diagram flow
caption: Triage for "No space left on device"
numbered: true
nodes:
  - "df -h|bytes free?|info"
  - "df -i|inodes free?|app"
  - "du --max-depth=1|which directory?|warn"
  - "lsof +L1|deleted but open?|bad"
  - "Fix|rotate, clean, grow|ok"
@h Commands
```bash title="Find what is filling the disk" lab
df -hT | head
df -i | head -5
du -xh --max-depth=1 /var 2>/dev/null | sort -h | tail -5
sudo lsof +L1 2>/dev/null | head
journalctl --disk-usage
```
:::tip
For a file that is deleted but still open, truncating via `: > /proc/<pid>/fd/<n>` frees the space without restarting. Prefer restarting the process during a maintenance window.
:::
@end

@concept RAID, mounts and quotas
@plain
**RAID** combines disks for speed or redundancy. **Quotas** cap how much a user or project may store. Mount options tune behaviour.
@problem
A single disk fails eventually, and one runaway user or project can fill a shared volume for everyone.
@does
- RAID 1 mirrors (survives one failure), RAID 5 stripes with parity (one failure), RAID 6 survives two, RAID 10 mirrors and stripes. RAID is not a backup: deletes and corruption are copied too.
- In the cloud, replication and snapshots (EBS, managed disks) usually replace software RAID; RAID 0 across volumes is used only to raise throughput.
- Useful mount options: `noatime` (fewer writes), `noexec,nosuid,nodev` on data and `/tmp` for safety, `ro` for read-only.
- XFS project quotas and ext4 user quotas limit usage.
@diagram cmp
caption: Common RAID levels
cards:
  - {h: "RAID 0", kind: bad, items: ["Striping only", "Faster, any failure loses all", "Use for scratch data"]}
  - {h: "RAID 1", kind: ok, items: ["Mirror of two disks", "Survives one failure", "Capacity is halved"]}
  - {h: "RAID 5/6", kind: app, items: ["Parity across disks", "Survives 1 or 2 failures", "Slow rebuilds on large disks"]}
  - {h: "RAID 10", kind: env, items: ["Mirrors that are striped", "Fast and resilient", "Capacity is halved"]}
@h Hands-on
```bash title="Mount options and mdadm status" nocheck
mount | grep -E ' /data | /tmp '
sudo mount -o remount,noexec,nosuid,nodev /tmp
cat /proc/mdstat 2>/dev/null || echo "no software RAID here"
sudo xfs_quota -x -c 'report -h' /data 2>/dev/null | head
```
@check
Is RAID a backup? || No. It protects against disk failure only; accidental deletion, corruption and ransomware are replicated to every disk.
@end
