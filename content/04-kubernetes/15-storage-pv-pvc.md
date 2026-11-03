---
title: Volumes, PersistentVolumes and StorageClasses
minutes: 50
objectives:
  - Pick the right volume type and access mode
  - Explain static and dynamic provisioning and binding modes
  - Resize, reclaim and debug persistent storage
---
Containers are disposable, data is not. Kubernetes separates the request for storage (PVC) from the supply of it (PV and StorageClass).

@concept Volume types
@plain
A volume is a directory made available to containers in a Pod. Its lifetime and backing storage depend on the type.
@problem
A container's filesystem disappears on restart, and containers in a Pod often need to share files.
@does
- `emptyDir`: scratch space that lives as long as the Pod; `medium: Memory` uses tmpfs.
- `hostPath`: a node directory. Powerful and risky; avoid except for node agents.
- `configMap`, `secret`, `projected`, `downwardAPI`: config as files.
- `persistentVolumeClaim`: durable storage that outlives the Pod.
- `csi` inline and `ephemeral` generic volumes: per-Pod volumes from a StorageClass that are deleted with the Pod.
@diagram cmp
caption: Lifetime of each kind
cards:
  - {h: "emptyDir", kind: info, items: ["Pod lifetime", "Cache, scratch"]}
  - {h: "hostPath", kind: bad, items: ["Node lifetime", "Security risk"]}
  - {h: "PVC", kind: ok, items: ["Independent lifetime", "Databases, state"]}
  - {h: "Generic ephemeral", kind: app, items: ["Pod lifetime", "Needs a fast disk"]}
@h Scratch space with a size limit
```yaml title="emptydir.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: scratch
spec:
  containers:
    - name: app
      image: busybox:1.36
      command: ["sleep", "3600"]
      resources:
        limits: {ephemeral-storage: 1Gi}
      volumeMounts:
        - {name: tmp, mountPath: /tmp}
  volumes:
    - name: tmp
      emptyDir:
        sizeLimit: 500Mi
```
@end

@concept PersistentVolume and PersistentVolumeClaim
@plain
A **PV** is a piece of storage in the cluster. A **PVC** is a user's request for storage of a size and access mode. Kubernetes binds one PVC to one matching PV.
@problem
Developers should ask for "20 GiB, read-write" without knowing about EBS volume IDs or NFS servers.
@does
- PV is cluster-scoped, usually created automatically; PVC is namespaced.
- Binding is one-to-one and exclusive. A bound PV cannot serve another claim.
- The Pod references only the PVC name.
- Phases: PV `Available`, `Bound`, `Released`, `Failed`; PVC `Pending`, `Bound`, `Lost`.
@diagram flow
caption: Claim to disk
nodes:
  - "Pod|volumes: claimName|app"
  - "PVC|20Gi RWO|info"
  - "PV|bound 1:1|cp"
  - "Disk|EBS vol-0abc|ext"
@h Claim and use
```yaml title="pvc.yaml"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: data
spec:
  accessModes: ["ReadWriteOnce"]
  storageClassName: gp3
  resources:
    requests:
      storage: 20Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: db
spec:
  containers:
    - name: pg
      image: postgres:16
      volumeMounts:
        - {name: data, mountPath: /var/lib/postgresql/data}
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: data
```
@end

@concept Access modes
@plain
Access modes say how many nodes may use a volume and whether they may write: `ReadWriteOnce`, `ReadOnlyMany`, `ReadWriteMany`, `ReadWriteOncePod`.
@problem
Two Pods writing the same block device on different nodes corrupts the filesystem.
@does
- **RWO**: one node at a time (several Pods on that node may share it). Typical for EBS and block disks.
- **RWOP**: exactly one Pod in the cluster (stable in 1.29). Safest for single-writer databases.
- **ROX**: many nodes read only.
- **RWX**: many nodes write; needs a shared filesystem such as EFS, NFS, CephFS or Azure Files.
- A Deployment with 3 replicas and one RWO PVC runs fine on one node but stalls on a rollout across nodes with Multi-Attach errors.
@diagram cmp
caption: What each mode means
cards:
  - {h: "RWO", kind: info, items: ["One node writes", "EBS, PD, Azure Disk"]}
  - {h: "RWOP", kind: ok, items: ["One Pod writes", "Strictest"]}
  - {h: "ROX", kind: app, items: ["Many nodes read", "Shared datasets"]}
  - {h: "RWX", kind: warn, items: ["Many nodes write", "EFS, NFS, CephFS"]}
@choose Access mode
RWOP | a database that must have a single writer | several replicas must share files
RWO | block disk for one Pod or one node | replicas on different nodes need the same data
RWX | shared uploads or content | you need low latency block performance
@check
Why does a Deployment with an RWO PVC fail rolling updates across nodes? || The new Pod lands on another node while the volume is still attached to the old one: Multi-Attach error. Use Recreate, a StatefulSet, or RWX.
@end

@concept StorageClasses and dynamic provisioning
@plain
A StorageClass describes a kind of storage (type, IOPS, encryption) and the CSI driver that creates it on demand when a PVC names the class.
@problem
Pre-creating disks for every request is slow and manual.
@does
- A PVC with `storageClassName` triggers the provisioner, which creates the disk and the PV automatically.
- `volumeBindingMode: WaitForFirstConsumer` delays creation until a Pod is scheduled, so the disk is made in the right zone.
- `allowVolumeExpansion: true` allows growing a PVC later.
- `reclaimPolicy` `Delete` removes the disk with the PVC; `Retain` keeps it.
- One class can be the default (annotation `storageclass.kubernetes.io/is-default-class`).
@diagram seq
caption: Dynamic provisioning
actors: ["PVC|request|info", "Provisioner|CSI controller|cp", "Cloud|EBS API|ext", "Scheduler|places Pod|cp"]
steps:
  - "0>3: Pod uses PVC | req"
  - "3>1: node chosen, zone a | resp"
  - "1>2: CreateVolume zone a | req"
  - "2>1: vol-0abc | resp"
  - "note 1..1: PV created and bound"
@h EBS gp3 class
```yaml title="storageclass.yaml"
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: ebs.csi.aws.com
parameters:
  type: gp3
  encrypted: "true"
  iops: "3000"
  throughput: "125"
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
```
@end

@concept Reclaim, resize and static PVs
@plain
What happens to data when a claim goes away, how to grow a disk, and how to adopt an existing one.
@problem
Deleting a PVC can destroy production data, and running out of space is common.
@does
- `Delete`: PV and disk removed with the PVC. `Retain`: PV becomes `Released` with data intact; an admin must clean and reuse it.
- Production databases usually use a class with `Retain`, or snapshots plus backups.
- **Expand** by editing `spec.resources.requests.storage` upward on the PVC; shrinking is not supported. Many CSI drivers resize online; the filesystem grows after a Pod restart if needed.
- **Static** PV: create a PV pointing at an existing disk, then a PVC with `volumeName`.
@diagram flow
caption: Growing a volume
numbered: true
nodes:
  - "Edit PVC size|20Gi to 50Gi|info"
  - "Controller resizes disk|cloud API|cp"
  - "Node expands filesystem|online or on restart|app"
  - "Done|FileSystemResizePending clears|ok"
@h Commands
```bash title="Resize and inspect" lab
kubectl patch pvc data -p '{"spec":{"resources":{"requests":{"storage":"50Gi"}}}}'
kubectl get pvc data -w
kubectl describe pvc data | grep -A5 Conditions
kubectl patch pv pvc-1234 -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
kubectl get pv
```
:::warn
Setting `Retain` on the PV before deleting a PVC is the cheapest data-loss insurance. Do it before risky operations like namespace cleanup.
:::
@end

@concept Debugging storage
@plain
Storage failures show up as Pods stuck in `ContainerCreating` or PVCs stuck in `Pending`.
@problem
Without a method, you look in the wrong layer: Pod, PVC, PV, driver or cloud.
@does
- PVC `Pending`: no matching class, provisioner down, quota exceeded, or `WaitForFirstConsumer` waiting for a Pod.
- Pod `ContainerCreating` with `FailedAttachVolume`: volume still attached elsewhere, or node limit on attachments reached.
- `FailedMount`: filesystem error, wrong permissions, missing NFS target.
- Permission denied on write: set `securityContext.fsGroup` so volume files get the right group.
@diagram flow
caption: Follow the chain
numbered: true
nodes:
  - "Pod events|FailedMount, FailedAttach|info"
  - "PVC|Pending or Bound|info"
  - "PV and class|provisioner|info"
  - "CSI driver logs|controller and node|warn"
@h Investigate
```bash title="Storage triage" lab
kubectl describe pod db | sed -n '/Events/,$p'
kubectl describe pvc data
kubectl get volumeattachments
kubectl -n kube-system logs deploy/ebs-csi-controller -c csi-provisioner --tail=30
kubectl get events --field-selector reason=ProvisioningFailed -A
```
@end
