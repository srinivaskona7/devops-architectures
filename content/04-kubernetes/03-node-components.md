---
title: Nodes, kubelet and the runtime interfaces
minutes: 50
objectives:
  - Explain what the kubelet does and how it talks to CRI, CNI and CSI
  - Describe node heartbeats, conditions and what happens when a node dies
  - Inspect a node and its container runtime
---
A node is just a Linux machine with a few agents. The three plug-in interfaces CRI, CNI and CSI are why Kubernetes works the same on EKS, Gardener and bare metal.

@concept The kubelet
@plain
The kubelet is the agent on every node. It watches the API server for Pods assigned to its node and makes the container runtime match them.
@problem
The scheduler only writes a node name into a Pod. Something local must pull images, mount volumes, start containers, run probes and report status.
@does
- Watches Pods with `spec.nodeName` equal to its node and runs a sync loop for each.
- Calls the runtime over CRI, the network plugin over CNI (through the runtime) and storage plug-ins over CSI.
- Runs liveness, readiness and startup probes, and restarts containers per `restartPolicy`.
- Reports Pod status, node status and a heartbeat back to the API server.
- Keeps working from local state if the control plane is briefly unreachable.
@diagram flow
caption: What the kubelet coordinates
nodes:
  - "API server|desired Pods|cp"
  - "kubelet|sync loop|app"
  - "containerd|CRI|info"
  - "Containers|running Pod|ok"
@h Look at a node
```bash title="Node details" lab
kubectl describe node $(kubectl get nodes -o name | head -1 | cut -d/ -f2) | sed -n '1,60p'
kubectl get node -o jsonpath='{.items[0].status.nodeInfo}' | head -c 600
kubectl get --raw "/api/v1/nodes/$(kubectl get nodes -o name | head -1 | cut -d/ -f2)/proxy/healthz"
```
@end

@concept CRI and the container runtime
@plain
The **Container Runtime Interface** is a gRPC API between the kubelet and a runtime. containerd and CRI-O implement it. Docker Engine support (dockershim) was removed in 1.24.
@problem
Without a standard interface the kubelet would need code for every runtime. CRI lets you swap runtimes without touching Kubernetes.
@does
- Two services: `RuntimeService` (sandboxes and containers) and `ImageService` (pull, list, remove).
- A **Pod sandbox** is created first (the pause container, holding the network namespace); then app containers join it.
- containerd uses a low level runtime such as `runc`; a `RuntimeClass` can select `gVisor` or `Kata` for isolation.
- Use `crictl` on the node for debugging; `docker` commands do not see Kubernetes containers.
@diagram layers
caption: From kubelet to a process
layers:
  - {label: "Kubelet", nodes: ["kubelet|CRI client|app"]}
  - {label: "High level runtime", nodes: ["containerd or CRI-O|images, sandboxes|info"]}
  - {label: "Low level runtime", nodes: ["runc|namespaces and cgroups|env", "gVisor or Kata|optional sandbox|warn"]}
  - {label: "Kernel", nodes: ["namespaces|isolation|ok", "cgroups|resource limits|ok"]}
@h crictl on a node
```bash title="Debugging at runtime level" lab
crictl ps                       # running containers
crictl pods                     # Pod sandboxes
crictl logs 
crictl images | head
crictl inspectp $(crictl pods -q | head -1) | head -30
```
@check
Why does every Pod have a pause container? || It owns the shared network namespace so app containers can restart without losing the Pod IP.
@end

@concept CNI, the Pod network plug-in
@plain
The **Container Network Interface** is how the runtime asks a plug-in to give a new Pod sandbox an IP and wire it into the cluster network.
@problem
Kubernetes requires that every Pod can reach every other Pod without NAT, but does not say how. The CNI plug-in does the actual wiring.
@does
- The runtime calls the plug-in with ADD when a sandbox starts and DEL when it is removed.
- The plug-in creates a veth pair, assigns an IP from a Pod CIDR and sets up routes or tunnels.
- Examples: AWS VPC CNI (Pods get real VPC IPs from ENIs), Calico, Cilium (eBPF), Flannel (overlay).
- The plug-in also often enforces NetworkPolicy. Flannel alone does not.
@diagram seq
caption: Giving a Pod an IP
actors: ["kubelet|node agent|app", "containerd|runtime|info", "CNI plugin|network|env"]
steps:
  - "0>1: RunPodSandbox | req"
  - "1>2: ADD sandbox netns | req"
  - "2>2: veth, IP, routes | req"
  - "2>1: IP 10.0.1.17 | resp"
  - "1>0: sandbox ready | resp"
@h Where CNI lives
```bash title="CNI config on a node" nocheck
ls /etc/cni/net.d/              # network configuration files
ls /opt/cni/bin/                # plug-in binaries
kubectl -n kube-system get ds   # aws-node, calico-node, cilium ...
kubectl get pods -A -o wide | head -5   # Pod IPs
```
@end

@concept CSI, the storage plug-in
@plain
The **Container Storage Interface** lets storage vendors ship a driver as ordinary Pods, instead of code compiled into Kubernetes.
@problem
In-tree volume code for each cloud bloated Kubernetes and tied storage fixes to Kubernetes releases.
@does
- A driver has a **controller** part (create, delete, snapshot, expand volumes via the cloud API) and a **node** part (attach, format, mount on the host).
- Sidecars such as `external-provisioner`, `external-attacher`, `external-snapshotter` and `external-resizer` translate Kubernetes objects into CSI calls.
- Examples: `ebs.csi.aws.com`, `efs.csi.aws.com`, `pd.csi.storage.gke.io`.
- Registered drivers appear as `CSIDriver` and `CSINode` objects.
@diagram layers
caption: Pieces of a CSI driver
layers:
  - {label: "Control plane side", nodes: ["external-provisioner|watches PVCs|cp", "external-attacher|VolumeAttachment|cp", "driver controller|cloud API calls|ext"]}
  - {label: "Node side", nodes: ["kubelet|mount request|app", "driver node plugin|format and mount|app"]}
@h Installed drivers
```bash title="List CSI drivers" lab
kubectl get csidrivers
kubectl get csinodes -o wide
kubectl get storageclass
```
@end

@concept Node lifecycle and health
@plain
Each kubelet renews a **Lease** object every few seconds and reports node conditions such as Ready, MemoryPressure and DiskPressure.
@problem
The control plane must notice dead nodes and move work off them, but must not panic over a brief network blip.
@does
- Leases in `kube-node-lease` are cheap heartbeats. If none arrives for the grace period (default 40 s) the node controller marks the node `Unknown`.
- The controller adds `node.kubernetes.io/unreachable` taints. Pods tolerate them for 300 s by default before eviction.
- Under pressure the kubelet evicts Pods itself, lowest QoS first, and taints the node.
- Cluster autoscalers and Gardener replace machines that stay NotReady.
@diagram flow
caption: A node dies
numbered: true
nodes:
  - "Heartbeats stop|lease not renewed|warn"
  - "Node Unknown|after about 40 s|warn"
  - "Taint added|unreachable NoExecute|bad"
  - "Pods evicted|after 300 s tolerance|bad"
  - "Rescheduled|ReplicaSets recreate|ok"
@h Conditions and leases
```bash title="Node health" lab
kubectl get lease -n kube-node-lease
kubectl get nodes -o custom-columns=NAME:.metadata.name,READY:.status.conditions[-1].type,STATUS:.status.conditions[-1].status
kubectl describe node worker-1 | grep -A8 Conditions
kubectl get node worker-1 -o jsonpath='{.spec.taints}'
```
:::warn
Stateful Pods are not moved automatically if the node might still be running them. A StatefulSet waits for the Pod to be confirmed gone, to avoid two Pods with the same identity.
:::
@end

@concept Static Pods, kube-proxy and node add-ons
@plain
Some Pods are not created through the API. **Static Pods** are defined by manifest files the kubelet reads from disk. DaemonSets run one agent per node through the API.
@problem
The control plane has to start before the API server exists, and every node needs network and proxy agents.
@does
- A static Pod manifest in `/etc/kubernetes/manifests` is started by the kubelet; the API shows a read-only mirror Pod. kubeadm runs apiserver, etcd and scheduler this way.
- Node add-ons run as DaemonSets: kube-proxy, CNI agent, log shipper, node exporter, CSI node plugin.
- The kubelet reserves resources for the system with `kubeReserved` and `systemReserved`; allocatable = capacity minus reservations minus eviction thresholds.
@diagram cmp
caption: How a Pod can come into existence
cards:
  - {h: "API Pod", kind: app, items: ["Created via the API", "Scheduled by scheduler"]}
  - {h: "DaemonSet Pod", kind: info, items: ["One per matching node", "Managed by DaemonSet controller"]}
  - {h: "Static Pod", kind: warn, items: ["File on the node disk", "Kubelet only, no scheduler"]}
@h Capacity versus allocatable
```bash title="What the scheduler can use" lab
kubectl get node worker-1 -o jsonpath='{"capacity: "}{.status.capacity}{"\nallocatable: "}{.status.allocatable}{"\n"}'
kubectl describe node worker-1 | sed -n '/Allocated resources/,/Events/p'
```
@check
Where does a kubelet find static Pod manifests? || In the directory set by `staticPodPath` in its config, commonly `/etc/kubernetes/manifests`.
@end
