---
title: Stateful workloads, databases and operators
minutes: 55
objectives:
  - Decide when a database belongs on Kubernetes and when it does not
  - Run PostgreSQL with CloudNativePG and Kafka with Strimzi
  - Plan backups, failover, upgrades and storage for stateful systems
---
Kubernetes can run databases well when an operator encodes the operational knowledge. Without one, a StatefulSet alone leaves failover, backup and upgrades to you.

@concept Should this database run on Kubernetes
@plain
Running state on Kubernetes is a trade-off between portability and operational effort. A managed service moves the work to the provider.
@problem
Teams either move every database into the cluster and drown in operations, or avoid it and lose the benefits for dev, test and edge cases.
@does
- Good fit: dev and test, many small databases per team, Kafka and caches close to apps, platforms that already have strong storage and backup.
- Weaker fit: a single critical database with no one on call who knows it, or needs beyond what your storage offers (IOPS, cross-region replication).
- Managed options (RDS, SAP HANA Cloud, BTP service instances) give backups, patching and SLAs.
- In Kyma, consuming a BTP service through service bindings is often the supported path.
@diagram flow
caption: Decision questions
nodes:
  - "Need SLA and patching done for you|yes|info"
  - "Managed service|RDS, HANA Cloud, BTP|ok"
  - "Team has operator skills|yes|info"
  - "Operator on Kubernetes|CloudNativePG, Strimzi|app"
@choose Where to run
Managed service | production data and a small team | you need a feature the service does not offer
Operator on Kubernetes | many instances, GitOps, portability | storage or backups are not proven
StatefulSet by hand | learning and throwaway tests | anything you would be paged for
@end

@concept StatefulSet guarantees and limits
@plain
A StatefulSet gives each replica a stable name, stable network identity and its own PVC. It starts and stops replicas in order.
@problem
Replicated databases need a fixed identity for peers and their own data directory.
@does
- Pods are `db-0`, `db-1` with DNS names via a headless Service: `db-0.db.shop.svc`.
- `volumeClaimTemplates` create one PVC per Pod, kept when scaling down or deleting the set (check `persistentVolumeClaimRetentionPolicy`).
- `podManagementPolicy: Parallel` removes ordering; `updateStrategy.rollingUpdate.partition` lets you stage upgrades.
- It does not know about replication roles, failover or backups. That is the operator's job.
@diagram layers
caption: StatefulSet pieces
layers:
  - {label: "Network", nodes: ["Headless Service|stable DNS per Pod|info"]}
  - {label: "Pods", nodes: ["db-0|primary|ok", "db-1|replica|app", "db-2|replica|app"]}
  - {label: "Storage", nodes: ["PVC data-db-0|own volume|plain", "PVC data-db-1|own volume|plain", "PVC data-db-2|own volume|plain"]}
@h Commands
```bash title="Staged update with a partition" lab
kubectl patch sts db -n shop -p '{"spec":{"updateStrategy":{"rollingUpdate":{"partition":2}}}}'
kubectl rollout status sts/db -n shop
kubectl get pods -n shop -l app=db -o custom-columns=NAME:.metadata.name,REV:.metadata.labels.controller-revision-hash
```
@check
What happens to PVCs when you scale a StatefulSet to zero? || They stay by default, so data survives and returns when you scale up, unless a retention policy says otherwise.
@end

@concept The operator pattern for databases
@plain
An operator is a controller plus CRDs that encodes what a human DBA does: create a cluster, fail over, back up, upgrade and rotate certificates.
@problem
Doing these steps by script or runbook is error-prone, especially at 3 am.
@does
- You declare `kind: Cluster` (CloudNativePG) or `kind: Kafka` (Strimzi) and the operator creates StatefulSets or Pods, Services, Secrets and PVCs.
- It reconciles continuously: it replaces a lost replica, promotes a standby and issues certificates.
- Check maturity: activity, release notes, upgrade path, backup and restore documentation, and what happens when the operator is down (databases normally keep running).
- Operators from vendors or CNCF projects (CloudNativePG, Zalando, Percona, Strimzi) differ in features.
@diagram flow
caption: Reconcile loop
nodes:
  - "Cluster resource|desired state|app"
  - "Operator|compares with reality|cp"
  - "Pods, PVCs, Services|created or fixed|info"
  - "Status|healthy replicas, primary|ok"
@end

@concept PostgreSQL with CloudNativePG
@plain
CloudNativePG manages PostgreSQL clusters with one primary and streaming replicas, using native Kubernetes objects and no external HA tool.
@problem
Automatic failover and backups for Postgres need many moving parts when built by hand.
@does
- A `Cluster` with `instances: 3` creates a primary and two replicas, services `-rw`, `-ro` and `-r`.
- Failover: if the primary fails, the most advanced replica is promoted and the `-rw` service switches.
- Backups use Barman Cloud to object storage with WAL archiving, enabling point in time recovery. Scheduled with `ScheduledBackup`.
- Rolling upgrades of minor versions and switchover supported. Check the current docs for how backup plugins are configured, as this has changed between releases.
@diagram flow
caption: Services in front of a Postgres cluster
nodes:
  - "App|writes|app"
  - "shop-db-rw|service to primary|cp"
  - "Primary|pod 1|ok"
  - "Replicas|pods 2 and 3|info"
@h Cluster manifest
```yaml title="Three instance Postgres cluster" nocheck
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: shop-db
  namespace: shop
spec:
  instances: 3
  imageName: ghcr.io/cloudnative-pg/postgresql:17
  storage:
    size: 50Gi
    storageClass: gp3-encrypted
  walStorage:
    size: 10Gi
  affinity:
    topologyKey: topology.kubernetes.io/zone
  resources:
    requests: {cpu: "1", memory: 4Gi}
    limits: {memory: 4Gi}
  backup:
    retentionPolicy: 14d
    barmanObjectStore:
      destinationPath: s3://shop-db-backups/
      s3Credentials:
        inheritFromIAMRole: true
```
```bash title="Operate" lab
kubectl cnpg status shop-db -n shop
kubectl cnpg promote shop-db shop-db-2 -n shop
kubectl get svc -n shop | grep shop-db
```
@end

@concept Kafka with Strimzi
@plain
Strimzi runs Apache Kafka on Kubernetes with CRDs for clusters, topics, users and connectors.
@problem
Kafka needs careful configuration of brokers, storage, listeners, TLS and rolling restarts.
@does
- Resources: `Kafka`, `KafkaNodePool`, `KafkaTopic`, `KafkaUser`, `KafkaConnect`. Recent Strimzi versions use KRaft mode without ZooKeeper; check the version notes for your release.
- Node pools set roles (controller, broker), storage and replicas separately.
- The Cluster Operator performs safe rolling updates, one broker at a time, checking in-sync replicas.
- Users and ACLs are declared as resources, with generated Secrets for credentials.
- Use `rack` awareness over zones so replicas are in different zones.
@diagram layers
caption: Strimzi operators
layers:
  - {label: "Operators", nodes: ["Cluster Operator|brokers and rolling updates|cp", "Entity Operator|topics and users|cp"]}
  - {label: "Kafka", nodes: ["Controller pool|3 nodes|info", "Broker pool|3 nodes with PVCs|app"]}
  - {label: "Clients", nodes: ["Producers|TLS and SCRAM|plain", "Consumers|consumer groups|plain"]}
@h Topic as code
```yaml title="Topic resource" nocheck
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaTopic
metadata:
  name: orders
  namespace: kafka
  labels:
    strimzi.io/cluster: main
spec:
  partitions: 12
  replicas: 3
  config:
    retention.ms: 604800000
    min.insync.replicas: 2
```
@check
Why set min.insync.replicas to 2 with replicas 3? || Writes with acks=all need two copies, so one broker can fail without losing data or availability.
@end

@concept Backup, restore and disaster recovery
@plain
Replication protects against node loss. Backups protect against mistakes and corruption. Both are needed.
@problem
A `DROP TABLE` replicates to all replicas within milliseconds.
@does
- Define RPO (how much data you can lose) and RTO (how long recovery may take) first.
- Logical (`pg_dump`) is portable but slow; physical base backups plus WAL archive allow point in time recovery.
- Store backups outside the cluster and the account, with retention and encryption.
- Practise restoring into a new cluster, for example CNPG `bootstrap.recovery` from the object store, and measure the time.
- Cross-region DR: replica clusters or storage-level replication, depending on the operator.
@diagram flow
caption: Point in time recovery
nodes:
  - "Base backup|nightly|info"
  - "WAL archive|continuous|info"
  - "Pick target time|before the bad change|warn"
  - "Recovered cluster|new instance|ok"
@h Recovery manifest
```yaml title="Recover to a point in time" nocheck
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: shop-db-restored
  namespace: shop
spec:
  instances: 1
  storage:
    size: 50Gi
  bootstrap:
    recovery:
      source: shop-db
      recoveryTarget:
        targetTime: "2026-10-30 09:15:00+00"
  externalClusters:
    - name: shop-db
      barmanObjectStore:
        destinationPath: s3://shop-db-backups/
        s3Credentials:
          inheritFromIAMRole: true
```
@end

@concept Operating stateful workloads safely
@plain
Day-two work: upgrades, node drains, disk growth, monitoring and protecting data from accidental deletion.
@problem
Routine platform actions such as node upgrades can break quorum if they are not coordinated with the database.
@does
- PodDisruptionBudgets so a drain never takes two members of a quorum. Most operators create them.
- Anti-affinity or spread constraints across nodes and zones.
- Monitor replication lag, disk use, WAL growth, and under-replicated partitions, with alerts before the disk fills.
- Protect PVCs: `reclaimPolicy: Retain` for important classes, RBAC that limits who can delete CRs, and finalizers or admission policies.
- Upgrade in order: test restore, minor version first, operator before database version when the docs say so.
@diagram flow
caption: Safe node drain
nodes:
  - "kubectl drain|evicts a database Pod|warn"
  - "PDB check|min 2 of 3 available|cp"
  - "Operator|switchover if primary|app"
  - "Pod rescheduled|same zone volume|ok"
@h PDB example
```yaml title="Keep quorum during drains"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: kafka-brokers
  namespace: kafka
spec:
  minAvailable: 2
  selector:
    matchLabels:
      strimzi.io/name: main-kafka
```
@check
Which risk does a PDB address? || Voluntary disruptions such as drains. It does not protect from node crashes or data deletion.
@end
