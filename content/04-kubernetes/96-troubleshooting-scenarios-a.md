---
title: Troubleshooting scenarios 1 to 7, networking and storage
minutes: 70
objectives:
  - Diagnose Services, DNS, gateways, policies and volumes from symptoms
  - Run the exact commands that confirm each cause
  - Apply the fix and verify it
---
Each scenario lists the symptom, the commands that confirm the cause and the fix. Work from the symptom, confirm before changing anything, then verify.

@concept Scenario 1, Service has no endpoints
@plain
The Service exists but requests time out or are refused. The Service routes only to Pods that match its selector and are Ready.
@problem
A label typo or a failing readiness probe leaves the endpoint list empty.
@does
- Symptom: `connection refused` or timeout to the ClusterIP, `kubectl get endpoints` shows `<none>`.
- Confirm: compare `spec.selector` with Pod labels; check Pod readiness and `targetPort`.
- Fix: correct the label or selector, fix the readiness probe, or set the right `targetPort`.
- Verify: endpoints list Pod IPs and a curl from a debug Pod succeeds.
@diagram flow
caption: Why endpoints are empty
nodes:
  - "Selector matches labels|no|bad"
  - "Pods Ready|no|bad"
  - "targetPort listens|no|warn"
  - "Endpoints filled|yes|ok"
@h Commands
```bash title="Diagnose endpoints" lab
kubectl get svc api -n shop -o jsonpath='{.spec.selector}{"\n"}'
kubectl get pods -n shop --show-labels
kubectl get endpointslices -n shop -l kubernetes.io/service-name=api
kubectl run t --rm -it --restart=Never --image=nicolaka/netshoot -n shop -- curl -sv http://api:8080/healthz
```
@check
Which Pods appear in endpoints? || Pods matching the selector whose Ready condition is true (unless publishNotReadyAddresses is set).
@end

@concept Scenario 2, DNS failures
@plain
Pods cannot resolve names, or resolve slowly. CoreDNS answers cluster names and forwards the rest.
@problem
Applications fail with `no such host` or take 5 seconds per call.
@does
- Symptom: `nslookup kubernetes.default` fails, or external names time out intermittently.
- Confirm: CoreDNS Pods Ready, logs, `kube-dns` endpoints, node-level DNS reachability, NetworkPolicy blocking port 53, the `ndots:5` effect on external names.
- Fix: restart or scale CoreDNS, allow UDP and TCP 53 in policies, use trailing dots or lower `ndots` through `dnsConfig`, consider NodeLocal DNSCache.
- Verify: lookups are fast and succeed from several nodes.
@diagram flow
caption: DNS path
nodes:
  - "Pod resolv.conf|ndots 5, search domains|plain"
  - "CoreDNS|cluster.local and forward|cp"
  - "Upstream resolver|node or VPC DNS|ext"
  - "Answer|cached|ok"
@h Commands
```bash title="DNS checks" lab
kubectl run d --rm -it --restart=Never --image=nicolaka/netshoot -- sh -c 'cat /etc/resolv.conf; dig +short kubernetes.default.svc.cluster.local; time dig +short example.com'
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=30
kubectl get endpoints kube-dns -n kube-system
```
@end

@concept Scenario 3, Ingress or Gateway returns 502 or 503
@plain
The load balancer works but users see 502, 503 or 404. The proxy cannot find or reach a healthy backend.
@problem
It is unclear whether the fault is in DNS, the load balancer, the proxy rules or the application.
@does
- Symptom: `502 Bad Gateway`, `503 no healthy upstream`, `404` from the proxy.
- Confirm: route/ingress status conditions (Accepted, ResolvedRefs), backend Service endpoints, port names, proxy logs, health checks of the cloud LB.
- Frequent causes: wrong `port` in backendRef, Service has no endpoints, readiness failing, backend uses HTTPS but proxy speaks HTTP, host header mismatch.
- Fix the mismatch, then test by `curl --resolve` to bypass DNS.
@diagram flow
caption: Layer by layer
numbered: true
nodes:
  - "DNS|record points to LB|plain"
  - "Load balancer|health check green|info"
  - "Gateway or Ingress|route accepted|cp"
  - "Service endpoints|ready Pods|app"
@h Commands
```bash title="Find the broken layer" lab
curl -skI --resolve app.example.com:443:203.0.113.10 https://app.example.com/
kubectl get httproute,gateway -A
kubectl describe httproute app -n shop | grep -A12 -i conditions
kubectl logs -n istio-system deploy/istio-ingressgateway --tail=30
```
@check
What does 503 with "no healthy upstream" usually mean? || The proxy has no ready endpoints for the route's backend.
@end

@concept Scenario 4, NetworkPolicy blocks traffic
@plain
Traffic worked yesterday and now times out after a policy was added. Policies are additive allow lists once a Pod is selected.
@problem
A default deny or a too narrow rule silently drops traffic with no error message.
@does
- Symptom: timeouts (not refusals) between specific workloads or to DNS.
- Confirm: list policies selecting the Pod; use Hubble or CNI flow logs to see drops; test from another namespace.
- Frequent causes: DNS not allowed in egress, namespaceSelector without the `kubernetes.io/metadata.name` label, ingress from the gateway namespace missing, monitoring scrapes blocked.
- Fix: add targeted allow rules; keep policy tests in CI.
@diagram flow
caption: Policy selection
nodes:
  - "Pod selected by policy|isolated for that direction|warn"
  - "Rule matches|allowed|ok"
  - "No rule matches|dropped silently|bad"
@h Commands
```bash title="Policy debugging" lab
kubectl get networkpolicy -n shop -o wide
kubectl describe networkpolicy -n shop | grep -E 'Name:|PodSelector|Allowing|Not affecting'
hubble observe --namespace shop --verdict DROPPED --last 20
kubectl exec -n shop deploy/web -- nc -zv -w 2 api 8080
```
@end

@concept Scenario 5, PVC stuck in Pending
@plain
A PersistentVolumeClaim never binds, so the Pod stays Pending.
@problem
Storage problems look like scheduling problems from the Pod view.
@does
- Symptom: PVC `Pending`; events `waiting for first consumer`, `no persistent volumes available`, `storageclass not found`, or provisioning errors.
- Confirm: `describe pvc`, StorageClass exists and is default, binding mode, CSI controller Pods and logs, cloud quota, IAM permissions.
- Frequent causes: wrong `storageClassName`, CSI driver not installed, missing IAM role (EBS CSI on EKS), zone mismatch, quota.
- Fix: install or repair the driver, correct the class, grant permission. Note `WaitForFirstConsumer` Pending is normal until a Pod is scheduled.
@diagram flow
caption: Provisioning chain
nodes:
  - "PVC|class gp3|app"
  - "external-provisioner|CreateVolume|cp"
  - "Cloud API|quota and IAM|ext"
  - "PV bound|ok|ok"
@h Commands
```bash title="PVC diagnosis" lab
kubectl describe pvc data -n shop | tail -15
kubectl get sc
kubectl logs -n kube-system deploy/ebs-csi-controller -c csi-provisioner --tail=30
kubectl get pods -n kube-system | grep csi
```
@check
Is a Pending PVC with WaitForFirstConsumer an error? || Not by itself. It waits for a Pod to be scheduled so that the volume can be created in the right zone.
@end

@concept Scenario 6, Multi-Attach error after a node failure
@plain
A Pod using a ReadWriteOnce volume is rescheduled to another node and cannot start because the volume is still attached to the old node.
@problem
Stateful Pods stay in ContainerCreating for many minutes after a node crash.
@does
- Symptom: event `Multi-Attach error for volume ... already exclusively attached to one node`, or `FailedAttachVolume`.
- Confirm: `kubectl get volumeattachments`; the old node may be NotReady or gone.
- Fix: wait for the attach/detach controller timeout (about 6 minutes), or confirm the old node is truly down and delete the stale VolumeAttachment; for deleted nodes, remove the Node object. Use `Force detach` only when sure the old node no longer writes.
- Prevent: use a StatefulSet with an operator that fences, and ReadWriteOncePod where suitable.
@diagram flow
caption: Stale attachment
nodes:
  - "Node A fails|volume still attached|bad"
  - "Pod recreated on node B|cannot attach|warn"
  - "Detach after timeout|or manual clean-up|info"
  - "Pod starts|volume attached to B|ok"
@h Commands
```bash title="Attachment diagnosis" lab
kubectl describe pod db-0 -n shop | grep -i -B2 -A4 attach
kubectl get volumeattachments | grep pvc-
kubectl get nodes
kubectl delete volumeattachment csi-0123456789abcdef --wait=false
```
:::danger
Only delete a VolumeAttachment when you are certain the old node is powered off. Two nodes writing to one block device corrupt the filesystem.
:::
@end

@concept Scenario 7, Node NotReady
@plain
A node stops reporting Ready. The control plane marks its Pods for eviction after the toleration period (5 minutes by default).
@problem
Workloads on the node become unreachable and may be rescheduled.
@does
- Symptom: `kubectl get nodes` shows NotReady; Pods Terminating or Unknown.
- Confirm: `describe node` conditions (`Ready`, `MemoryPressure`, `DiskPressure`, `NetworkUnavailable`), kubelet and runtime status, CNI agent Pod, disk and memory, cloud console instance state, certificate expiry.
- Frequent causes: kubelet crash, disk full, runtime hung, CNI not running, network partition, instance stopped.
- Fix: restart the service, free disk, replace the node (cordon, drain if possible, let the autoscaler or Gardener roll it). In managed platforms prefer replacing the machine.
@diagram flow
caption: Triage order
numbered: true
nodes:
  - "Node conditions|describe node|info"
  - "Kubelet and runtime|journal|app"
  - "CNI and disk|agent Pod, df|warn"
  - "Replace or repair|verify Ready|ok"
@h Commands
```bash title="Node triage" lab
kubectl describe node NODE | sed -n '/Conditions/,/Addresses/p'
kubectl get pods -A -o wide --field-selector spec.nodeName=NODE | head -20
kubectl debug node/NODE -it --image=busybox:1.36 -- sh -c 'df -h /host; chroot /host journalctl -u kubelet -n 30 --no-pager'
kubectl cordon NODE
```
@check
After you finish node maintenance, what must you check? || That the node is uncordoned and schedulable, because reconciliation or a partial drain can leave it cordoned.
@end
