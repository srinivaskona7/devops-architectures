---
title: Storage deep dive
minutes: 60
objectives:
  - Describe how CSI drivers provision, attach, mount and snapshot volumes
  - Expand volumes and use topology aware binding safely
  - Use ephemeral volumes and back up applications with Velero
---
Storage failures cause the longest incidents because data cannot be recreated. This page goes beyond PVC basics into the CSI machinery, snapshots, expansion and backups.

@concept The CSI architecture
@plain
The Container Storage Interface lets storage vendors ship a driver as Pods instead of code inside Kubernetes. A controller part talks to the storage API and a node part mounts volumes.
@problem
In-tree volume plugins tied every storage system to the Kubernetes release cycle. CSI separates them.
@does
- **Controller plugin** (Deployment) handles create, delete, attach, snapshot, resize, using sidecars: external-provisioner, external-attacher, external-resizer, external-snapshotter.
- **Node plugin** (DaemonSet) runs `NodeStageVolume` and `NodePublishVolume` to format and mount into the Pod path. It registers with the kubelet through node-driver-registrar.
- `CSIDriver` object describes capabilities (`attachRequired`, `fsGroupPolicy`). `CSINode` lists drivers per node.
- On EKS the EBS CSI driver is an add-on that needs IAM permissions (IRSA or Pod Identity).
@diagram flow
caption: Dynamic provisioning path
nodes:
  - "PVC|requests storageClass|app"
  - "external-provisioner|CreateVolume|cp"
  - "external-attacher|ControllerPublish|cp"
  - "Node plugin|stage and mount|info"
  - "Pod|sees directory|ok"
@h Inspect drivers
```bash title="CSI objects" lab
kubectl get csidrivers
kubectl get csinodes
kubectl get pods -n kube-system -l app.kubernetes.io/name=aws-ebs-csi-driver
kubectl get volumeattachments
```
@check
Which part mounts a volume on the node? || The CSI node plugin DaemonSet, called by the kubelet through the NodeStage and NodePublish calls.
@end

@concept StorageClasses, binding modes and reclaim
@plain
A StorageClass is a template for dynamic volumes: which driver, which parameters, when to bind and what happens after deletion.
@problem
Wrong binding mode creates volumes in a zone where the Pod can never run. Wrong reclaim policy deletes data or leaves orphaned disks.
@does
- `volumeBindingMode: WaitForFirstConsumer` delays creation until a Pod is scheduled, so the volume lands in the right zone.
- `reclaimPolicy: Delete` removes the disk with the PVC; `Retain` keeps it for manual recovery.
- `allowVolumeExpansion: true` is required to grow volumes later.
- `parameters` are driver specific, for example EBS `type: gp3`, `iops`, `encrypted`.
- Mark exactly one class default with an annotation.
@diagram flow
caption: Immediate versus late binding
nodes:
  - "Immediate|disk created in any zone|warn"
  - "Pod scheduled in another zone|cannot attach|bad"
  - "WaitForFirstConsumer|disk follows the Pod|ok"
@h Example class
```yaml title="gp3 class with late binding"
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3-encrypted
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
```
@end

@concept Volume expansion
@plain
You can grow a PVC by editing its requested size. The driver resizes the disk, and the filesystem grows, often without restarting the Pod.
@problem
Disks fill up, and recreating a database volume by copying is risky.
@does
- Needs `allowVolumeExpansion` on the class and a driver that supports it.
- Edit `spec.resources.requests.storage` to a larger value. Shrinking is not supported.
- Conditions on the PVC: `Resizing`, `FileSystemResizePending`. Online expansion works for most CSI drivers.
- Cloud limit: EBS allows one modification per volume about every 6 hours. Check provider limits.
- StatefulSet templates cannot be edited, so patch each PVC and recreate the StatefulSet object with `--cascade=orphan`.
@diagram seq
caption: Online expansion
actors: ["You|patch PVC|plain", "external-resizer|controller|cp", "Node plugin|filesystem|info"]
steps:
  - "0>1: 20Gi to 50Gi | req"
  - "1>1: ControllerExpandVolume | warn"
  - "1>2: NodeExpandVolume | req"
  - "2>0: capacity 50Gi | resp"
@h Commands
```bash title="Grow a PVC" lab
kubectl patch pvc data-db-0 -n shop -p '{"spec":{"resources":{"requests":{"storage":"50Gi"}}}}'
kubectl get pvc data-db-0 -n shop -w
kubectl describe pvc data-db-0 -n shop | grep -A5 -i conditions
kubectl exec -n shop db-0 -- df -h /var/lib/postgresql/data
```
@check
Can you shrink a PVC? || No. Kubernetes only supports growing. Restore into a smaller volume from a backup instead.
@end

@concept Snapshots and clones
@plain
A VolumeSnapshot captures a volume at a point in time through the CSI driver. You can create a new PVC from it, or clone a PVC directly.
@problem
Copying data by hand is slow and inconsistent. Snapshots are fast and storage side.
@does
- Needs the snapshot CRDs, the snapshot controller, and a `VolumeSnapshotClass` for the driver.
- `VolumeSnapshotContent` is the cluster-wide counterpart, like PV for PVC.
- Restore: a new PVC with `dataSource` of kind `VolumeSnapshot`.
- Crash consistent only. For databases quiesce or use application tools. Snapshots on the same storage system are not a backup against account loss.
@diagram flow
caption: Snapshot and restore
nodes:
  - "PVC data-db-0|source|app"
  - "VolumeSnapshot|point in time|info"
  - "New PVC|dataSource snapshot|app"
  - "Pod|test restore|ok"
@h Snapshot and restore
```yaml title="Snapshot, then restore into a new PVC"
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: db-snap-1
  namespace: shop
spec:
  volumeSnapshotClassName: ebs-snap
  source:
    persistentVolumeClaimName: data-db-0
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data-db-restore
  namespace: shop
spec:
  storageClassName: gp3-encrypted
  dataSource:
    name: db-snap-1
    kind: VolumeSnapshot
    apiGroup: snapshot.storage.k8s.io
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 50Gi
```
@end

@concept Topology and access modes
@plain
Volumes live somewhere: a zone, a node or a rack. Topology rules keep Pods and data together. Access modes say who may mount at once.
@problem
A zone outage or a Pod move can leave a RWO disk stranded in another zone.
@does
- Block volumes (EBS) are zonal and `ReadWriteOnce`. A Pod must run in the zone of its volume.
- `allowedTopologies` in StorageClass restricts zones. PV `nodeAffinity` records where a volume can attach.
- `ReadWriteOncePod` (GA in recent releases) guarantees one Pod only; `ReadWriteMany` needs a file system such as EFS or NFS.
- Multi-attach errors after a node failure appear until the old attachment is gone; check `VolumeAttachment` objects.
- Spread StatefulSet replicas across zones with topology spread constraints, each with its own volume.
@diagram cmp
caption: Access modes
cards:
  - {h: "ReadWriteOnce", kind: info, items: ["One node at a time", "Block disks", "Pods on that node share"]}
  - {h: "ReadWriteOncePod", kind: ok, items: ["Exactly one Pod", "Safe for singletons"]}
  - {h: "ReadWriteMany", kind: warn, items: ["Many nodes", "File systems", "Lock behaviour is up to you"]}
@h Diagnose Multi-Attach
```bash title="Attachment checks" lab
kubectl describe pod POD -n shop | grep -i -A3 'multi-attach\|FailedAttach'
kubectl get volumeattachments -o custom-columns=NAME:.metadata.name,NODE:.spec.nodeName,PV:.spec.source.persistentVolumeName,ATTACHED:.status.attached
kubectl get pv PVNAME -o jsonpath='{.spec.nodeAffinity}{"\n"}'
```
@end

@concept Ephemeral volumes
@plain
Some volumes live only as long as a Pod: emptyDir, ConfigMap and Secret volumes, and generic ephemeral volumes that use a real StorageClass.
@problem
Scratch space such as caches or ML datasets can be large, and emptyDir uses the node root disk and can cause evictions.
@does
- `emptyDir` can use `medium: Memory` (counts toward memory limits) and has `sizeLimit`.
- **Generic ephemeral volume**: a `volumeClaimTemplate` in the Pod spec. The PVC is created and deleted with the Pod, and can use any CSI class, snapshots and capacity tracking.
- **CSI ephemeral volumes** are inline and driver defined, used by Secrets Store CSI for example.
- Set `ephemeral-storage` requests so the scheduler accounts for it.
@diagram flow
caption: Generic ephemeral volume lifecycle
nodes:
  - "Pod created|has claim template|app"
  - "PVC generated|owned by Pod|info"
  - "Pod runs|volume mounted|ok"
  - "Pod deleted|PVC deleted too|warn"
@h Example
```yaml title="Scratch volume from a StorageClass"
apiVersion: v1
kind: Pod
metadata:
  name: scratch
spec:
  containers:
    - name: work
      image: busybox:1.36
      command: ["sleep", "3600"]
      volumeMounts:
        - {name: scratch, mountPath: /scratch}
      resources:
        requests: {ephemeral-storage: 1Gi}
  volumes:
    - name: scratch
      ephemeral:
        volumeClaimTemplate:
          spec:
            accessModes: [ReadWriteOnce]
            storageClassName: gp3-encrypted
            resources:
              requests:
                storage: 20Gi
```
@check
What happens to a generic ephemeral volume when the Pod is deleted? || Its PVC is owned by the Pod and is deleted with it.
@end

@concept Backup and restore with Velero
@plain
Velero backs up Kubernetes objects to object storage and can back up volume data through CSI snapshots or file-level copy (kopia).
@problem
Snapshots live in the same account and region as the cluster. A backup of both manifests and data lets you recover from deletion, corruption or cluster loss.
@does
- `Backup`, `Schedule` and `Restore` are CRDs. Backup locations point at an S3 compatible bucket.
- Volume data: CSI snapshot integration (data stays in cloud snapshots, optionally moved to the bucket with data mover) or file system backup with node agent.
- Hooks run commands before and after backup (for example `pg_dump` or fsfreeze) for consistency.
- Restore can map namespaces, storage classes, and skip existing objects.
- A backup is only proven by a restore test in an empty cluster. Schedule drills.
@diagram flow
caption: Velero backup
nodes:
  - "Schedule|cron|plain"
  - "Velero server|reads API objects|cp"
  - "CSI snapshot or kopia|volume data|info"
  - "Object storage|bucket in another account|ext"
@h Commands and schedule
```bash title="Backup and restore drill" lab
velero backup create shop-$(date +%F) --include-namespaces shop --snapshot-move-data
velero backup describe shop-$(date +%F) --details
velero restore create --from-backup shop-$(date +%F) --namespace-mappings shop:shop-restore
```
```yaml title="Nightly schedule"
apiVersion: velero.io/v1
kind: Schedule
metadata:
  name: shop-nightly
  namespace: velero
spec:
  schedule: "0 2 * * *"
  template:
    includedNamespaces: [shop]
    ttl: 168h
    snapshotMoveData: true
```
:::tip
Restore into a different namespace or cluster first. Watch for Secrets, PVCs and webhooks that conflict with the live copy.
:::
@end
