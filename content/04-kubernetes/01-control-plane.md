---
title: Control plane and etcd
minutes: 50
objectives:
  - Name every control plane and node component and say what it owns
  - Explain how etcd and Raft keep cluster state consistent
  - Describe a controller reconcile loop and why Kubernetes is level driven
---
Kubernetes is a database of desired state (the API server and etcd) plus many small programs that keep reality matching it. Learn that split and the rest of the platform becomes predictable.

@concept The cluster at a glance
@plain
A cluster is a **control plane** that makes decisions and **worker nodes** that run your containers. You talk only to the control plane, through the API server.
@problem
Running containers across many machines needs one place that knows what should run, where it runs, and what to do when a machine dies. Doing that by hand with SSH does not scale or heal.
@does
- The control plane runs kube-apiserver, etcd, kube-scheduler and kube-controller-manager (plus cloud-controller-manager on cloud providers).
- Each node runs a kubelet, a container runtime and usually kube-proxy and a CNI agent.
- Everything communicates through the API server; components never talk to each other directly.
- On managed platforms (EKS, Gardener-managed Kyma) the provider operates the control plane and you only see worker nodes.
@diagram layers
caption: Where each component lives
layers:
  - {label: "You", nodes: ["kubectl|CLI|ext", "CI/CD and GitOps|automation|ext"]}
  - {label: "Control plane", nodes: ["kube-apiserver|front door|cp", "etcd|state store|cp", "scheduler|places Pods|cp", "controller-manager|reconcile loops|cp"]}
  - {label: "Worker node", nodes: ["kubelet|runs Pods|app", "container runtime|containerd|app", "kube-proxy|Service rules|app", "CNI plugin|Pod network|app"]}
@h First look
```bash title="Inspect a cluster" lab
kubectl cluster-info                         # API server and CoreDNS endpoints
kubectl get nodes -o wide                    # nodes, versions, runtime, IPs
kubectl get --raw='/readyz?verbose' | head   # API server health checks
kubectl -n kube-system get pods -o wide      # system components that run as Pods
kubectl api-resources | head -20             # every kind this cluster serves
```
:::note
On Kyma and EKS you will not see kube-apiserver or etcd as Pods. The provider hosts them outside your nodes.
:::
@check
Which component do kubectl and the kubelet both talk to? || The kube-apiserver. It is the only component that reads and writes etcd.
@end

@concept The API server
@plain
The kube-apiserver is a stateless HTTPS server that exposes every Kubernetes object as a REST resource. It is the single gateway to the cluster state.
@problem
If every component read and wrote the data store directly, there would be no common place to enforce identity, permissions, validation and audit.
@does
- Authenticates and authorises each request, runs admission, validates and then persists to etcd.
- Offers `list` and `watch` so clients can stream changes instead of polling.
- Is stateless, so you run several replicas behind a load balancer for availability.
- Serves built-in APIs and extension APIs (CRDs, aggregated APIs) the same way.
@diagram flow
caption: The API server sits between all clients and etcd
nodes:
  - "Clients|kubectl, kubelet, controllers|ext"
  - "kube-apiserver|auth, admission, validation|cp"
  - "etcd|only the API server connects|cp"
@h Talk to it directly
```bash title="The REST API behind kubectl" lab
kubectl get --raw /api/v1/namespaces/default/pods | head -c 300   # raw list call
kubectl get pods -v=8 2>&1 | grep -E 'GET|Response Status' | head -3   # see the HTTP calls
kubectl proxy --port=8001 &                                       # local authenticated proxy
curl -s localhost:8001/apis | head -c 300                         # API groups available
kill %1
```
@end

@concept etcd, the state store
@plain
etcd is a small, strongly consistent key-value database. Every object you create, such as a Deployment or Secret, is a key in etcd with its serialised value.
@problem
The cluster needs one authoritative record that survives restarts and gives every reader the same answer, otherwise two controllers could act on different truths.
@does
- Stores objects under keys such as `/registry/pods/default/web-0`.
- Supports transactions and **revisions**, which is what makes `watch` and optimistic concurrency (`resourceVersion`) possible.
- Is sensitive to disk latency, since each write is fsynced. Slow disks cause leader elections and API timeouts.
- Has a size quota (2 GiB default, 8 GiB suggested maximum). Past the quota it goes read-only until compacted and defragmented.
@diagram layers
caption: What etcd holds and what depends on it
layers:
  - {label: "Consumers", nodes: ["kube-apiserver|the only client|cp"]}
  - {label: "etcd members", nodes: ["etcd-0|leader|ok", "etcd-1|follower|info", "etcd-2|follower|info"]}
  - {label: "Disk", nodes: ["WAL|write ahead log, fsync|warn", "snapshot|periodic compaction|plain"]}
@h Back up and inspect
```bash title="etcd snapshot on a self-managed cluster" nocheck
ETCDCTL_API=3 etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/server.crt \
  --key=/etc/kubernetes/pki/etcd/server.key \
  snapshot save /backup/etcd-$(date +%F).db
etcdutl snapshot status /backup/etcd-$(date +%F).db -w table
etcdctl endpoint status --cluster -w table     # leader, DB size, raft index
```
:::warn
A cluster without tested etcd backups has no disaster recovery. On managed services (EKS, Gardener) the provider backs up etcd; Gardener also keeps etcd backups in object storage. Your workload data still needs its own backups, for example Velero.
:::
@check
Why do slow disks hurt the whole cluster? || etcd fsyncs every write. Slow fsync delays commits, heartbeats are missed, leaders change, and the API server times out.
@end

@concept Raft and quorum
@plain
Raft is how etcd members agree. One member is the leader, writes go through it, and a write counts only after a **majority** has stored it.
@problem
With several copies of the data, members could disagree after a crash or network split. Raft guarantees that all members agree on one ordered history.
@does
- A quorum is `floor(n/2) + 1` members: 2 of 3, 3 of 5.
- A 3-member cluster survives 1 failure, a 5-member cluster survives 2. Four members tolerate no more than three do, so use odd sizes.
- Without a quorum etcd refuses writes, so the cluster cannot change, but running Pods keep running because the kubelet works from its local state.
- More members means slower writes (more acknowledgements), so 3 or 5 is the norm.
@diagram seq
caption: A write needs a majority to acknowledge
actors: ["API server|client|cp", "Leader|etcd-0|cp", "Follower A|etcd-1|info", "Follower B|etcd-2|info"]
steps:
  - "0>1: write Pod | req"
  - "1>2: append entry | req"
  - "1>3: append entry | req"
  - "2>1: ack | resp"
  - "note 1..1: majority reached 2 of 3"
  - "1>0: committed | resp"
@h Quorum arithmetic
```python title="Quorum and failure tolerance" lab
for n in range(1, 8):
    quorum = n // 2 + 1
    print(f"members={n} quorum={quorum} tolerated_failures={n - quorum}")
```
@check
How many failures does a 5-member etcd tolerate? || Two. Quorum is 3, so 5 - 3 = 2.
@end

@concept kube-scheduler
@plain
The scheduler watches for Pods with no node assigned and picks the best node for each one.
@problem
Someone must decide which of hundreds of machines has the room, labels and constraints a Pod needs. Doing it by hand wastes capacity and breaks rules like spreading across zones.
@does
- Filters nodes that cannot run the Pod, then scores the remaining ones.
- Writes the result by creating a **binding**, which sets `spec.nodeName`.
- Never starts containers. The kubelet on the chosen node does that.
- A Pod with no suitable node stays `Pending` with a `FailedScheduling` event explaining why.
@diagram flow
caption: Scheduling one Pod
numbered: true
nodes:
  - "Unscheduled Pod|nodeName is empty|warn"
  - "Filter|resources, taints, affinity|cp"
  - "Score|spread, image locality, fit|cp"
  - "Bind|nodeName is set|ok"
  - "kubelet|starts the containers|app"
@h See the decision
```bash title="Why is it Pending" lab
kubectl get pods --field-selector=status.phase=Pending -A
kubectl describe pod web-0 | sed -n '/Events/,$p'     # FailedScheduling reasons
kubectl get events -A --field-selector reason=FailedScheduling --sort-by=.lastTimestamp | tail
```
@end

@concept Controllers and reconcile loops
@plain
A controller is a loop that compares desired state (the spec) with observed state (the status) and acts to close the gap. It then repeats forever.
@problem
Imperative scripts break when something changes behind their back. A loop that always re-checks reality recovers from crashes, deleted Pods and missed events.
@does
- kube-controller-manager bundles dozens of controllers: Deployment, ReplicaSet, Job, Node, EndpointSlice, ServiceAccount and others.
- Each controller watches objects through an **informer** (a local cache fed by `watch`) and puts keys on a work queue.
- Reconcile is **level driven**: it looks at current state, not at the event that woke it, so a missed event is harmless.
- Reconcile must be idempotent. Your own operators and CRD controllers follow the same pattern.
@diagram flow
caption: The reconcile loop
nodes:
  - "Watch|informer cache|info"
  - "Queue|object key|plain"
  - "Compare|spec versus status|cp"
  - "Act|create, update, delete|app"
  - "Write status|report result|ok"
@h Watch a controller work
```bash title="Delete a Pod and watch it come back" lab
kubectl create deployment web --image=nginx:1.27 --replicas=3
kubectl get pods -l app=web -w &
kubectl delete pod -l app=web --wait=false --field-selector=status.phase=Running | head -1
sleep 5; kill %1
kubectl get rs -l app=web -o wide       # ReplicaSet controller restored the count
kubectl delete deployment web
```
@check
What does level driven mean? || The controller reacts to the current state difference, not to individual events, so lost or duplicated events do not matter.
@end

@concept Cloud controller manager and managed control planes
@plain
The cloud-controller-manager holds the code that talks to a cloud provider API: create load balancers, find node metadata and remove nodes whose VM is gone.
@problem
Core Kubernetes should not contain AWS, Azure or Google specific logic. Splitting it out lets providers release on their own schedule.
@does
- Its Service controller turns a `type: LoadBalancer` Service into a cloud load balancer.
- Its node controller sets zone and instance type labels and deletes Node objects for terminated VMs.
- In EKS the AWS Load Balancer Controller adds ALB and NLB features on top of this.
- In Gardener (the base of SAP BTP Kyma) a seed cluster hosts each shoot cluster's control plane, so you never manage etcd or API server nodes.
@diagram cmp
caption: Who runs what in each model
cards:
  - {h: "Self-managed (kubeadm)", kind: warn, items: ["You run etcd and apiserver", "You upgrade and back up", "Most flexible, most work"]}
  - {h: "EKS", kind: info, items: ["AWS runs the control plane", "You run nodes or Fargate", "Upgrades are a managed API call"]}
  - {h: "Gardener and Kyma", kind: ok, items: ["Seed hosts the shoot control plane", "Worker pools managed by Gardener", "Kyma modules add Istio, serverless and more"]}
@h Check what your nodes report
```bash title="Provider information on nodes" lab
kubectl get nodes -L topology.kubernetes.io/zone,node.kubernetes.io/instance-type
kubectl get node -o jsonpath='{.items[0].spec.providerID}{"\n"}'
```
@end
