---
title: High availability control plane and etcd drills
minutes: 55
objectives:
  - Design a three node control plane with a stable API endpoint
  - Back up and restore etcd and rehearse failures
  - Monitor etcd health and handle member replacement
---
The control plane is only as available as etcd and the endpoint in front of the API servers. These drills turn theory into muscle memory.

@concept HA topologies
@plain
A highly available control plane runs at least three API servers and three etcd members, behind one stable address.
@problem
A single control plane node is a single point of failure for scheduling, scaling and deployments (running Pods continue, but nothing changes).
@does
- **Stacked etcd**: etcd runs on the same nodes as the control plane. Simpler, fewer machines.
- **External etcd**: separate etcd nodes. More machines, isolates failure and resources.
- API servers are stateless and are placed behind a load balancer or virtual IP (kube-vip, HAProxy, cloud LB).
- Spread across failure zones. Managed services do this for you.
@diagram layers
caption: Stacked HA topology
layers:
  - {label: "Endpoint", nodes: ["Load balancer|api.example.com 6443|ext"]}
  - {label: "Control plane nodes", nodes: ["cp-1|apiserver and etcd|cp", "cp-2|apiserver and etcd|cp", "cp-3|apiserver and etcd|cp"]}
  - {label: "Workers", nodes: ["Nodes|kubelets talk to the LB|app"]}
@check
Why use a load balancer address as controlPlaneEndpoint? || Nodes and users keep working when one API server fails or is replaced, and certificates stay valid.
@end

@concept Raft quorum and failure math
@plain
etcd uses the Raft algorithm. A write needs agreement from a majority (quorum) of members.
@problem
Wrong member counts give no extra safety, or leave the cluster read-only after a failure.
@does
- Quorum is floor(n/2)+1. For 3 members quorum is 2 (tolerates 1 failure). For 5 it is 3 (tolerates 2). Even numbers add cost without tolerance.
- Losing quorum makes etcd unavailable for writes; the API server then fails requests.
- More members slows writes slightly. Three or five is the practical range.
- Disk latency is the main risk: slow fsync causes leader elections and "etcdserver: request timed out".
@diagram cmp
caption: Members and tolerated failures
cards:
  - {h: "1 member", kind: bad, items: ["Quorum 1", "Tolerates 0"]}
  - {h: "3 members", kind: ok, items: ["Quorum 2", "Tolerates 1"]}
  - {h: "4 members", kind: warn, items: ["Quorum 3", "Tolerates 1", "Worse than 3 in cost"]}
  - {h: "5 members", kind: ok, items: ["Quorum 3", "Tolerates 2"]}
@h Verify the numbers
```python title="Quorum table"
for n in range(1, 8):
    quorum = n // 2 + 1
    print(n, "members, quorum", quorum, ", tolerates", n - quorum)
```
@end

@concept Taking an etcd snapshot
@plain
`etcdctl snapshot save` writes a consistent copy of the whole etcd database to a file.
@problem
Without a recent snapshot, losing quorum or corrupting data means rebuilding the cluster and redeploying everything.
@does
- Needs endpoint and client certificates: `--endpoints`, `--cacert`, `--cert`, `--key` (kubeadm paths under `/etc/kubernetes/pki/etcd`).
- Verify with `etcdutl snapshot status` (older versions: `etcdctl snapshot status`).
- Copy off the node to object storage. Encrypt, since snapshots contain Secrets. Automate with a CronJob or a systemd timer, and retain several days.
- Managed control planes (EKS, Gardener) take backups for you; you cannot access etcd directly. Gardener backs up each shoot's etcd to object storage automatically.
@diagram flow
caption: Backup routine
nodes:
  - "etcdctl snapshot save|on a member|app"
  - "Verify status|hash and revision|info"
  - "Encrypt and upload|object storage|ext"
  - "Retention|delete old copies|ok"
@h Commands
```bash title="Snapshot (on a kubeadm control plane node)" lab
sudo ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /var/backups/etcd-$(date +%F).db
sudo etcdutl snapshot status /var/backups/etcd-$(date +%F).db -w table
```
@check
Why encrypt etcd snapshots? || They contain all cluster data including Secrets in readable form unless encryption at rest was enabled.
@end

@concept Restoring etcd, the drill
@plain
Restore creates a new data directory from a snapshot. All members then start from the same state with new cluster identity.
@problem
Restores are done rarely and under pressure. Rehearsal avoids mistakes such as restoring only one member.
@does
- Stop the API servers and etcd (move static Pod manifests away on kubeadm).
- Single member: `etcdutl snapshot restore snap.db --data-dir /var/lib/etcd-restore`, then point the etcd manifest at the new dir.
- Multi member: restore on each node with `--name`, `--initial-cluster`, `--initial-advertise-peer-urls` and a new `--initial-cluster-token`.
- Restart and check `etcdctl endpoint status` and `kubectl get nodes`.
- Objects created after the snapshot are lost; controllers will reconcile what remains. Lease and node state catch up.
@diagram seq
caption: Restore order
actors: ["Operator|you|plain", "etcd members|all nodes|db", "API servers|after etcd|cp"]
steps:
  - "0>2: stop API servers | warn"
  - "0>1: stop etcd | warn"
  - "0>1: restore on every member | req"
  - "0>1: start etcd | req"
  - "0>2: start API servers | resp"
@h Commands
```bash title="Restore single member" lab
sudo mv /etc/kubernetes/manifests/kube-apiserver.yaml /tmp/
sudo mv /etc/kubernetes/manifests/etcd.yaml /tmp/
sudo etcdutl snapshot restore /var/backups/etcd-2026-10-30.db --data-dir /var/lib/etcd-restore
sudo sed -i 's#/var/lib/etcd$#/var/lib/etcd-restore#' /tmp/etcd.yaml
sudo mv /tmp/etcd.yaml /tmp/kube-apiserver.yaml /etc/kubernetes/manifests/
```
:::warn
Never restore on only some members of a multi-member cluster. Stop, restore and start all of them with the same snapshot.
:::
@end

@concept Failure drills
@plain
A drill is a planned experiment: break one thing in a test cluster, observe, recover, and write down the steps and the time taken.
@problem
Untested recovery plans fail on the day: wrong certificates, missing backups, expired tokens.
@does
- Drill 1: stop one control plane node. Expect API available through the LB, etcd still healthy.
- Drill 2: stop two nodes. Expect writes to fail; restore quorum by bringing one back.
- Drill 3: replace a member: `etcdctl member remove`, then `member add`, and start the new node with `--initial-cluster-state existing`.
- Drill 4: full restore from snapshot into new machines.
- Drill 5: expire certificates in a lab (set clock or use short lifetimes) and renew.
@diagram flow
caption: Drill cycle
nodes:
  - "Hypothesis|what should happen|info"
  - "Break|one thing|warn"
  - "Observe and recover|time it|app"
  - "Update runbook|share|ok"
@h Member commands
```bash title="Member health and replacement" lab
ETCD="etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key"
sudo $ETCD member list -w table
sudo $ETCD endpoint status --cluster -w table
sudo $ETCD endpoint health --cluster
```
@check
What happens to the API when two of three etcd members are down? || Quorum is lost. Reads may fail and writes are rejected until one member returns.
@end

@concept etcd performance, defrag and monitoring
@plain
etcd keeps history of changes, and its database file grows. Compaction removes old revisions and defragmentation returns space to the disk.
@problem
When the database hits its quota (2 GiB by default) etcd raises an alarm and becomes read-only: "mvcc: database space exceeded".
@does
- The API server compacts automatically (every 5 minutes by default); defragment members one at a time during quiet hours.
- Clear alarms with `etcdctl alarm disarm` after freeing space.
- Monitor `etcd_server_has_leader`, `etcd_server_leader_changes_seen_total`, `etcd_disk_wal_fsync_duration_seconds` (p99 under 10 ms is the guidance), `etcd_mvcc_db_total_size_in_bytes`.
- Use fast local SSD or NVMe disks. Avoid noisy neighbours. Large numbers of Events or CRD objects inflate the database.
@diagram flow
caption: Space exceeded recovery
nodes:
  - "NOSPACE alarm|read-only|bad"
  - "Compact|drop old revisions|info"
  - "Defrag each member|one at a time|warn"
  - "Alarm disarm|writes return|ok"
@h Commands
```bash title="Defragment" lab
ETCD="etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key"
sudo $ETCD endpoint status --cluster -w table
sudo $ETCD defrag
sudo $ETCD alarm list
```
@end
