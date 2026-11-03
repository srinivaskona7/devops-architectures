---
title: Troubleshooting playbook, network, nodes and storage
minutes: 50
objectives:
  - Trace a failing connection from Pod to Service to endpoints to DNS to policy
  - Diagnose NotReady nodes and PVCs stuck in Pending or Terminating
  - Use kubectl debug with ephemeral containers and node debugging
---
Pod level problems are only half of the playbook. The other half is connectivity, node health and storage, where the cause is rarely in the Pod you are looking at.
@concept Service has no endpoints
@plain
A Service forwards to the Pods that match its selector and are Ready. If the endpoint list is empty, connections fail even though Pods are running.
@problem
`connection refused` or timeouts when calling a Service name, while the Pods look healthy.
@does
- Compare `kubectl get svc -o yaml` selector with Pod labels. A single mismatched label gives zero endpoints.
- Check `targetPort` matches the container port the process listens on, and that the process binds `0.0.0.0`, not `127.0.0.1`.
- Pods failing readiness are excluded; see them as `notReadyAddresses`.
- Test inside the cluster, not from your laptop, to separate application from exposure problems.
@diagram flow
caption: Service to Pod chain
nodes:
  - "Service|selector, port, targetPort|cp"
  - "EndpointSlice|ready Pod IPs|info"
  - "Pod|labels and readiness|app"
  - "Process|listens on targetPort|ok"
@h Commands
```bash title="Check the chain" lab
kubectl get svc api -n shop -o jsonpath='{.spec.selector}{" "}{.spec.ports}{"\n"}'
kubectl get pods -n shop --show-labels
kubectl get endpointslices -n shop -l kubernetes.io/service-name=api -o wide
kubectl get pods -n shop -l app=api -o wide        # same selector as the Service
kubectl run curl --rm -it --restart=Never -n shop --image=curlimages/curl:8.8.0 -- curl -sv http://api/healthz
```
@end

@concept DNS failures
@plain
Pods resolve names through CoreDNS. Names look like `service.namespace.svc.cluster.local`, and short names work through search domains in the Pod's `/etc/resolv.conf`.
@problem
Applications report `no such host`, intermittent timeouts of five seconds, or slow lookups.
@does
- First prove DNS rather than assume: resolve the name from a Pod, then resolve an external name.
- Check CoreDNS Pods and logs in `kube-system`; look at their CPU throttling and restarts.
- `ndots:5` makes external names try several search domains first, causing extra queries. Use fully qualified names with a trailing dot or lower `ndots` through `dnsConfig`.
- Intermittent failures often come from a NetworkPolicy blocking egress to port 53, a node level conntrack issue, or an overloaded CoreDNS. NodeLocal DNSCache reduces load.
- On EKS, CoreDNS is a managed add-on; scale it through add-on config or an autoscaler.
@diagram seq
caption: A lookup through the cluster
actors: ["App Pod|client|app", "CoreDNS|kube-system|cp", "Upstream DNS|VPC resolver|ext"]
steps:
  - "0>1: api.shop.svc.cluster.local | req"
  - "1>0: ClusterIP | resp"
  - "0>1: example.com tries search domains | req"
  - "1>2: forward | req"
  - "2>0: answer | resp"
  - "0>1: query blocked by policy | bad"
@h Commands
```bash title="Prove DNS" lab
kubectl run dns --rm -it --restart=Never -n shop --image=registry.k8s.io/e2e-test-images/agnhost:2.47 -- nslookup api.shop.svc.cluster.local
kubectl exec POD -n shop -- cat /etc/resolv.conf
kubectl get pods -n kube-system -l k8s-app=kube-dns -o wide
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=30
kubectl top pods -n kube-system -l k8s-app=kube-dns
kubectl get cm coredns -n kube-system -o jsonpath='{.data.Corefile}'
```
```yaml title="Reduce ndots for one workload"
apiVersion: v1
kind: Pod
metadata:
  name: api-dns
spec:
  dnsConfig:
    options:
      - name: ndots
        value: "2"
  containers:
    - name: api
      image: registry.example.com/shop/api:1.8.3
```
@end

@concept NetworkPolicy blocking traffic
@plain
If a Pod is selected by a NetworkPolicy, only traffic that a policy allows can reach it (ingress) or leave it (egress). A missing allow rule looks exactly like a network fault: timeouts, not refusals.
@problem
A new default deny policy is applied and half the application stops working, including DNS lookups and calls to the metrics scraper.
@does
- List policies in both namespaces involved; check `policyTypes` and whether egress DNS (UDP and TCP 53 to kube-dns) is allowed.
- Remember a connection needs allowance at both ends: egress from the source and ingress at the destination.
- A **timeout** suggests policy or routing; **connection refused** suggests nothing is listening or the Service has no endpoints.
- Cilium users can see decisions with Hubble (`hubble observe --verdict DROPPED`); Calico has flow logs.
@diagram flow
caption: Timeouts versus refusals
nodes:
  - "Timeout|packets dropped|bad"
  - "Check NetworkPolicy|both directions and DNS|warn"
  - "Refused|nothing listening|warn"
  - "Check endpoints and ports|Service chain|info"
@h Commands and a DNS egress allow
```bash title="Inspect policies" lab
kubectl get networkpolicy -A
kubectl describe networkpolicy -n shop
kubectl get pod POD -n shop --show-labels                      # does a policy select it
kubectl run nettest --rm -it --restart=Never -n shop --image=nicolaka/netshoot -- nc -zv api 80
```
```yaml title="allow-dns-egress.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: shop
spec:
  podSelector: {}
  policyTypes: ["Egress"]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - {protocol: UDP, port: 53}
        - {protocol: TCP, port: 53}
```
@end

@concept Nodes in NotReady
@plain
A node is `NotReady` when the kubelet stops reporting healthy to the control plane. After a grace period the node gets taints and its Pods are evicted.
@problem
Workloads stop being scheduled to a node, or Pods on it go Unknown or Terminating.
@does
- Read node `Conditions` and events: `Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`, `NetworkUnavailable`.
- Causes: kubelet or container runtime stopped, node out of disk or memory, CNI failure, lost network to the API server, instance terminated.
- Debug the node with `kubectl debug node/NAME` and `chroot /host`; then `systemctl status kubelet`, `journalctl -u kubelet`, `crictl ps`.
- The node lifecycle controller adds `node.kubernetes.io/not-ready` and `unreachable` taints; Pods tolerate them for 300 seconds by default.
- On managed clusters prefer replacing the node (EKS node group, Gardener worker pool, Karpenter) over repairing it, after capturing evidence.
@diagram flow
caption: What happens when a node goes quiet
nodes:
  - "Kubelet heartbeat stops|Lease not renewed|bad"
  - "Node NotReady|after grace period|warn"
  - "Taint added|not-ready or unreachable|info"
  - "Pods evicted|rescheduled elsewhere|ok"
@h Commands
```bash title="Investigate a node" lab
kubectl get nodes -o wide
kubectl describe node NODE | sed -n '/Conditions/,/Addresses/p'
kubectl get lease NODE -n kube-node-lease -o jsonpath='{.spec.renewTime}{"\n"}'
kubectl debug node/NODE -it --image=busybox:1.36
# inside the debug container, the node filesystem is at /host
chroot /host systemctl status kubelet --no-pager
chroot /host journalctl -u kubelet --since "30 min ago" | tail -30
chroot /host crictl ps | head
```
:::warn
Do not delete a NotReady node object from the API to "fix" it unless you know the instance is gone. For StatefulSets with attached volumes, force-deleting Pods on an unreachable node risks two writers on one volume.
:::
@end

@concept PVC stuck Pending or Terminating
@plain
A PersistentVolumeClaim is Pending until a volume is bound to it. A claim or Pod stuck in Terminating usually waits on a finalizer, a mount or a detach.
@problem
Stateful Pods stay Pending, or a deleted namespace never finishes deleting.
@does
- **Pending PVC**: `describe pvc` shows the provisioner message. Typical causes: no default StorageClass, wrong class name, access mode unsupported, quota, or `WaitForFirstConsumer` binding where the claim waits for a Pod to be scheduled.
- **Zone mismatch**: an EBS volume lives in one AZ; the Pod must be scheduled in that zone. Topology aware binding avoids this.
- **Multi-Attach error**: a ReadWriteOnce volume is still attached to another node. Wait for detach or check the old Pod.
- **Terminating PVC** is protected by `kubernetes.io/pvc-protection` while a Pod uses it. Stuck namespaces typically wait on custom resources with finalizers.
- CSI problems show in the driver Pods (`ebs-csi-controller`) logs.
@diagram flow
caption: A claim becomes usable
numbered: true
nodes:
  - "PVC created|class, size, mode|env"
  - "Provisioner|CSI creates the volume|cp"
  - "Bind|PV linked to PVC|info"
  - "Attach and mount|on the Pod's node|ok"
@h Commands
```bash title="Storage checks" lab
kubectl get pvc,pv -n shop
kubectl describe pvc data-db-0 -n shop | tail -15
kubectl get storageclass
kubectl get volumeattachments | head
kubectl logs -n kube-system -l app=ebs-csi-controller -c csi-provisioner --tail=30
kubectl get namespace shop -o jsonpath='{.spec.finalizers}{" "}{.status.conditions}{"\n"}'
```
@check
Why does a PVC stay Pending with WaitForFirstConsumer? || Binding is delayed until a Pod using it is scheduled, so the volume is created in the right zone. It is normal until a consumer exists.
@end

@concept kubectl debug and ephemeral containers
@plain
`kubectl debug` adds a temporary container with your tools to a running Pod, or makes a modified copy of a Pod, or opens a shell on a node.
@problem
Production images are often minimal or distroless, with no shell, curl or tcpdump. You still need to look inside the Pod's network and process space.
@does
- **Ephemeral container**: `kubectl debug -it POD --image=nicolaka/netshoot --target=api` shares the network namespace, and with `--target` the process namespace, of the container. It cannot be removed until the Pod ends.
- **Copy**: `--copy-to=NAME` clones the Pod; `--container` plus a new command or `--set-image` changes it. The original is unharmed.
- **Node**: `kubectl debug node/NAME -it --image=...` runs a Pod on that node with the host filesystem at `/host`.
- Needs RBAC on `pods/ephemeralcontainers`. Pod Security restricted may block node debug profiles; use `--profile=` options (`general`, `baseline`, `restricted`, `netadmin`, `sysadmin`) as appropriate.
@diagram cmp
caption: Three ways to debug
cards:
  - {h: "Ephemeral container", kind: ok, items: ["Joins the live Pod", "Shares network and process space", "Best for live traffic"]}
  - {h: "Copy of the Pod", kind: info, items: ["Change command or image", "Original keeps serving", "Best for crash loops"]}
  - {h: "Node debug", kind: warn, items: ["Host filesystem at /host", "Kubelet and runtime logs", "Best for node faults"]}
@h Commands
```bash title="Debug recipes" lab
kubectl debug -it api-7d9f8c-x2k4p -n shop --image=nicolaka/netshoot --target=api -- bash
kubectl debug api-7d9f8c-x2k4p -n shop -it --copy-to=api-dbg --set-image=api=busybox:1.36 -- sh
kubectl debug node/ip-10-0-1-23.eu-west-1.compute.internal -it --image=busybox:1.36 --profile=sysadmin
kubectl get pod api-7d9f8c-x2k4p -n shop -o jsonpath='{.spec.ephemeralContainers[*].name}{"\n"}'
kubectl delete pod api-dbg -n shop
```
@end
