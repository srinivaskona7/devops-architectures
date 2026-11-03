---
title: StatefulSets and DaemonSets
minutes: 45
objectives:
  - Explain stable identity, ordered rollout and per Pod storage in a StatefulSet
  - Write a headless Service and volumeClaimTemplates
  - Use DaemonSets for node agents and understand their update behaviour
---
Stateless Pods are interchangeable. Databases, queues and per-node agents are not, and they need controllers built for that.

@concept Why StatefulSets exist
@plain
A StatefulSet runs Pods with a stable name, a stable network identity and their own persistent disk, which survive rescheduling.
@problem
A Deployment gives random names and shared templates. A database replica must know it is `db-1`, keep its own data and be reachable by a predictable DNS name.
@does
- Pods are named `<set>-0`, `<set>-1` and so on.
- Each Pod gets its own PVC from `volumeClaimTemplates`; the same PVC reattaches when the Pod is recreated.
- Pods are created in order 0..N-1 and removed in reverse (the default `OrderedReady` policy). `Parallel` skips the ordering.
- A **headless Service** (`clusterIP: None`) gives each Pod DNS `db-0.db.shop.svc`.
@diagram layers
caption: Identity that survives rescheduling
layers:
  - {label: "Network", nodes: ["db-0.db|stable DNS|info", "db-1.db|stable DNS|info"]}
  - {label: "Pods", nodes: ["db-0|ordinal 0|app", "db-1|ordinal 1|app"]}
  - {label: "Storage", nodes: ["data-db-0|own PVC|ok", "data-db-1|own PVC|ok"]}
@h Headless Service and StatefulSet
```yaml title="statefulset.yaml"
apiVersion: v1
kind: Service
metadata:
  name: db
spec:
  clusterIP: None
  selector:
    app: db
  ports:
    - {name: pg, port: 5432}
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
spec:
  serviceName: db
  replicas: 3
  selector:
    matchLabels:
      app: db
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  template:
    metadata:
      labels:
        app: db
    spec:
      containers:
        - name: postgres
          image: postgres:16
          env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef: {name: db-secret, key: password}
          ports:
            - {name: pg, containerPort: 5432}
          volumeMounts:
            - {name: data, mountPath: /var/lib/postgresql/data}
  volumeClaimTemplates:
    - metadata:
        name: data
      spec:
        accessModes: ["ReadWriteOnce"]
        storageClassName: gp3
        resources:
          requests:
            storage: 20Gi
```
@end

@concept StatefulSet updates and failure behaviour
@plain
StatefulSets update Pods one at a time from the highest ordinal down, waiting for each to be Ready.
@problem
Clustered databases need a quorum. Replacing all members at once, or running two Pods with the same identity, can corrupt data.
@does
- `partition: N` updates only ordinals at or above N, a built-in canary: lower it step by step.
- `OnDelete` updates only when you delete Pods yourself.
- If a node vanishes, the Pod stays `Terminating` or `Unknown`. Kubernetes will not start a duplicate until the old one is confirmed gone, preserving at-most-one semantics.
- Scaling down keeps PVCs unless `persistentVolumeClaimRetentionPolicy` says `Delete`. Disks cost money; clean up deliberately.
@diagram flow
caption: Ordered rolling update
numbered: true
nodes:
  - "db-2 updated|highest first|app"
  - "Ready|wait|ok"
  - "db-1 updated|next|app"
  - "Ready|wait|ok"
  - "db-0 updated|last|app"
@h Staged update
```bash title="Canary a StatefulSet" lab
kubectl patch sts db -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
kubectl set image sts/db postgres=postgres:16.4         # only db-2 updates
kubectl rollout status sts/db
kubectl patch sts db -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":0}}}}'
kubectl get pvc -l app=db
```
:::tip
For production databases prefer an operator (CloudNativePG, Percona, Zalando) over a hand-written StatefulSet. It encodes failover, backups and upgrades that the StatefulSet does not know about.
:::
@check
What does `partition: 2` on a 3-replica StatefulSet do? || Only db-2 receives the new template; db-0 and db-1 stay on the old revision.
@end

@concept DaemonSets
@plain
A DaemonSet runs one Pod on every node, or on every node that matches a selector.
@problem
Node-level agents, such as log collectors, metrics exporters, CNI and CSI node plug-ins, must be on each machine, including ones added later by autoscaling.
@does
- New nodes get the Pod automatically; removed nodes drop it.
- Use `nodeSelector` or affinity to target a subset (for example GPU nodes).
- Add tolerations so it runs on tainted nodes, as agents usually should.
- `RollingUpdate` replaces Pods node by node with `maxUnavailable` (default 1); `OnDelete` is manual.
- Set a `priorityClassName` such as `system-node-critical` for essential agents and keep requests small.
@diagram flow
caption: One agent per node
nodes:
  - "DaemonSet|template|app"
  - "node-a|agent Pod|ok"
  - "node-b|agent Pod|ok"
  - "new node-c|agent Pod added|info"
@h A log agent
```yaml title="daemonset.yaml"
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: log-agent
  namespace: logging
spec:
  selector:
    matchLabels:
      app: log-agent
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 10%
  template:
    metadata:
      labels:
        app: log-agent
    spec:
      priorityClassName: system-node-critical
      tolerations:
        - operator: Exists
      containers:
        - name: agent
          image: fluent/fluent-bit:3.1
          resources:
            requests: {cpu: 50m, memory: 64Mi}
            limits: {memory: 128Mi}
          volumeMounts:
            - {name: varlog, mountPath: /var/log, readOnly: true}
      volumes:
        - name: varlog
          hostPath:
            path: /var/log
```
@end

@concept Choosing the right workload controller
@plain
Each controller models a different promise about identity, ordering and completion.
@problem
Using a Deployment for a database, or a StatefulSet for a stateless API, brings unnecessary risk or complexity.
@does
- Deployment: interchangeable replicas, fast rollouts.
- StatefulSet: stable identity and per-Pod storage.
- DaemonSet: one per node.
- Job and CronJob: run to completion.
- ReplicaSet and bare Pods: only for experiments or custom controllers.
@diagram cmp
caption: Controller decision
cards:
  - {h: "Deployment", kind: app, items: ["Stateless", "Any replica serves"]}
  - {h: "StatefulSet", kind: warn, items: ["Identity and disk", "Ordered changes"]}
  - {h: "DaemonSet", kind: info, items: ["Node agents", "Follows node count"]}
  - {h: "Job", kind: ok, items: ["Finite work", "Retries until done"]}
@choose Workload controller
Deployment | web apps, APIs, workers | you need a stable hostname or own disk
StatefulSet | databases, brokers, quorum systems | the app is stateless
DaemonSet | log, metric, network, storage agents | you want N replicas anywhere
Job | batch, migrations | it must run forever
@end

@concept Operating StatefulSets safely
@plain
Most StatefulSet incidents are storage related: a Pod bound to a disk in one zone, or a volume that cannot attach.
@problem
An EBS volume lives in one availability zone. If the Pod is rescheduled to another zone it stays Pending.
@does
- Use a StorageClass with `volumeBindingMode: WaitForFirstConsumer` so the disk is created in the zone where the Pod lands.
- Spread replicas over zones with topology spread so one zone failure leaves quorum.
- Expand volumes by editing the PVC (if the class allows expansion); the StatefulSet template itself cannot be changed, delete it with `--cascade=orphan` and recreate it to change `volumeClaimTemplates`.
- Always add a PDB so drains cannot take quorum below the safe number.
@diagram flow
caption: A zone failure and a pinned disk
nodes:
  - "Zone A fails|node gone|bad"
  - "db-0 Pending|its disk is in zone A|warn"
  - "Replicas in B and C|quorum holds|ok"
@h Diagnose a stuck Pod
```bash title="Pending StatefulSet Pod" lab
kubectl describe pod db-0 | sed -n '/Events/,$p'
kubectl get pvc data-db-0 -o wide
kubectl get pv $(kubectl get pvc data-db-0 -o jsonpath='{.spec.volumeName}') -o jsonpath='{.spec.nodeAffinity}'
kubectl get volumeattachments
```
@end

@concept Headless Services and Pod DNS
@plain
A headless Service has no virtual IP. Its DNS name returns the individual Pod IPs, and each StatefulSet Pod gets its own record.
@problem
Cluster members and clients sometimes need to reach a specific replica (the primary, or peer number two), not a random one behind a load balancer.
@does
- `db.shop.svc.cluster.local` returns all ready Pod IPs as A records.
- `db-0.db.shop.svc.cluster.local` returns only that Pod, valid as long as the StatefulSet's `serviceName` is `db`.
- `publishNotReadyAddresses: true` lets peers find each other before they are Ready, which clustered databases need to bootstrap.
- Pod IPs change on reschedule; the DNS name stays stable.
@diagram flow
caption: Resolving a single replica
nodes:
  - "Client|asks db-0.db|ext"
  - "CoreDNS|headless record|info"
  - "Pod IP|10.0.2.9|ok"
@h Test the records
```bash title="Resolve from inside the cluster" lab
kubectl run dns --rm -it --image=busybox:1.36 --restart=Never -- nslookup db-0.db.shop.svc.cluster.local
kubectl run dns --rm -it --image=busybox:1.36 --restart=Never -- nslookup db.shop.svc.cluster.local
```
@end
