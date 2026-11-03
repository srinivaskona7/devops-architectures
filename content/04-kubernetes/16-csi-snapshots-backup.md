---
title: Snapshots, cloning and backup
minutes: 35
objectives:
  - Take and restore CSI VolumeSnapshots
  - Clone volumes and tune volume performance
  - Plan application consistent backup with Velero
---
A volume is not a backup. This lesson shows the tools Kubernetes provides for point-in-time copies, and what they still do not cover.

@concept VolumeSnapshots
@plain
A VolumeSnapshot is a point-in-time copy of a PVC, created by the CSI driver using the storage system's snapshot feature.
@problem
You need a fast, cheap restore point before an upgrade or migration, without copying data through the Pod.
@does
- Three objects: `VolumeSnapshotClass` (driver settings), `VolumeSnapshot` (namespaced request), `VolumeSnapshotContent` (cluster-scoped result).
- The snapshot CRDs and the snapshot controller must be installed; EKS and Gardener add-ons usually provide them.
- Snapshots are **crash consistent** unless the application is quiesced first.
- Snapshots on EBS are stored in S3 and are incremental, but they remain inside the same account unless copied.
@diagram flow
caption: Snapshot object chain
nodes:
  - "VolumeSnapshot|namespaced request|info"
  - "Snapshot controller|sidecar|cp"
  - "VolumeSnapshotContent|cluster scoped|cp"
  - "Cloud snapshot|snap-0abc|ext"
@h Take a snapshot
```yaml title="snapshot.yaml"
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshotClass
metadata:
  name: ebs-snap
driver: ebs.csi.aws.com
deletionPolicy: Retain
---
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: data-pre-upgrade
spec:
  volumeSnapshotClassName: ebs-snap
  source:
    persistentVolumeClaimName: data
```
@end

@concept Restore and clone
@plain
You restore by creating a new PVC whose `dataSource` is a snapshot. A clone does the same from another PVC.
@problem
Testing a migration or recovering from corruption needs a fresh volume populated from known data.
@does
- The new PVC must be the same or larger size and same namespace as the source snapshot.
- Restores always create a new volume; they never rewind the old one.
- Cloning (`dataSource.kind: PersistentVolumeClaim`) needs driver support and the same StorageClass.
- Switch the application to the new PVC (new StatefulSet claim or Deployment edit) after verifying data.
@diagram flow
caption: Restore path
numbered: true
nodes:
  - "Snapshot|data-pre-upgrade|info"
  - "New PVC|dataSource snapshot|app"
  - "New volume|provisioned|cp"
  - "Pod|mounts restored data|ok"
@h Restore PVC
```yaml title="restore-pvc.yaml"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-restored
spec:
  storageClassName: gp3
  accessModes: ["ReadWriteOnce"]
  resources:
    requests:
      storage: 20Gi
  dataSource:
    apiGroup: snapshot.storage.k8s.io
    kind: VolumeSnapshot
    name: data-pre-upgrade
```
@check
Does restoring a snapshot overwrite the original volume? || No. It creates a new volume; you then point the workload at it.
@end

@concept Application consistent backups
@plain
A snapshot taken while a database writes may need crash recovery on restore. Quiescing or using native dumps gives clean copies.
@problem
Crash-consistent copies of databases can be unusable or lose recent transactions.
@does
- Prefer the database's own tools: `pg_dump` or `pg_basebackup`, WAL archiving to object storage, `mysqldump`, or an operator's backup resource.
- Use pre and post hooks (Velero hooks, `fsfreeze`) when relying on volume snapshots.
- Test restores on a schedule; an untested backup is a hope.
- HANA, as used with Kyma, has its own backup tooling; use that for data consistency.
@diagram flow
caption: Consistent snapshot
nodes:
  - "Pre hook|flush and freeze|warn"
  - "Snapshot|instant|info"
  - "Post hook|thaw|ok"
@h Backup CronJob using pg_dump
```yaml title="pgdump-cronjob.yaml"
apiVersion: batch/v1
kind: CronJob
metadata:
  name: pg-dump
spec:
  schedule: "30 1 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      activeDeadlineSeconds: 3600
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: dump
              image: postgres:16
              command: ["sh", "-c", "pg_dump -h db -U app shop | gzip > /backup/shop-$(date +%F).sql.gz"]
              env:
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef: {name: db-secret, key: password}
              volumeMounts:
                - {name: backup, mountPath: /backup}
          volumes:
            - name: backup
              persistentVolumeClaim:
                claimName: backup-pvc
```
@end

@concept Velero
@plain
Velero backs up Kubernetes objects and volume data to object storage, and restores them into the same or another cluster.
@problem
Snapshots cover disks only. After a cluster loss you also need Deployments, Services, Secrets and CRDs.
@does
- `Backup` saves selected namespaces and resources to an S3 bucket; volumes via CSI snapshots or file-system backup (Kopia).
- `Schedule` runs backups with a TTL; `Restore` recreates objects, optionally into a different namespace.
- Used for cluster migration, DR and namespace recovery.
- It does not replace GitOps: Git is the source for manifests, Velero for state and stateful data.
@diagram layers
caption: What Velero captures
layers:
  - {label: "Objects", nodes: ["Namespaces|resources|info", "CRDs|custom resources|info"]}
  - {label: "Data", nodes: ["CSI snapshots|volumes|ok", "Kopia file backup|any volume|ok"]}
  - {label: "Storage", nodes: ["S3 bucket|backups|ext"]}
@h Schedule
```yaml title="velero-schedule.yaml"
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: daily-shop
  namespace: velero
spec:
  schedule: "0 3 * * *"
  template:
    includedNamespaces: ["shop"]
    snapshotMoveData: true
    ttl: 720h
```
@end

@concept Ephemeral storage, local volumes and performance
@plain
Containers also use node disk through logs, writable layers and emptyDir. Local SSDs and instance stores give speed without durability.
@problem
A chatty Pod fills the node disk and gets evicted, or a database on network storage is slower than expected.
@does
- Set `requests` and `limits` for `ephemeral-storage`; exceeding the limit evicts the Pod.
- Kubelet eviction triggers on `nodefs.available` and `imagefs.available` thresholds.
- Local PVs (`local` volume type) and CSI local drivers (TopoLVM, Local Path) give NVMe speed but pin the Pod to a node and lose data with the node.
- EBS gp3 lets you set IOPS and throughput independently of size; check `VolumeQueueLength` and throttling metrics when latency rises.
@diagram cmp
caption: Network disk versus local disk
cards:
  - {h: "Network block (EBS, PD)", kind: ok, items: ["Survives node loss", "Zonal", "Moderate latency"]}
  - {h: "Local NVMe", kind: warn, items: ["Lost with the node", "Pinned to node", "Lowest latency"]}
  - {h: "Shared file (EFS)", kind: info, items: ["Many writers", "Higher latency", "Pay per use"]}
@h Watch node disk
```bash title="Disk pressure" lab
kubectl describe node worker-1 | grep -E 'DiskPressure|ephemeral-storage'
kubectl top pods --containers -A | head
kubectl get pods -A -o json | grep -c Evicted
```
@end
