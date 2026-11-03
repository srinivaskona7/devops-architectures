---
title: Troubleshooting scenarios 15 to 20, platform and cloud
minutes: 60
objectives:
  - Diagnose API server overload, etcd space, Kyma APIRule and Istio issues
  - Fix EKS IAM roles for service accounts and registry pull problems
  - Recover from stuck Gardener maintenance and PDB-blocked drains
---
These scenarios belong to the platform layer: control plane load, identity with the cloud, service mesh and managed cluster maintenance.
@concept Scenario 15, API server slow or returning 429
@plain
kubectl is slow, controllers log timeouts, and some requests return `429 Too Many Requests`.
@problem
One noisy client can degrade the whole control plane.
@does
- Symptom: slow `kubectl get`, `etcdserver: request timed out`, `429` with `Retry-After`.
- Confirm: API server metrics `apiserver_request_duration_seconds`, `apiserver_flowcontrol_rejected_requests_total`, and audit logs showing the top user agents; look for controllers doing frequent full LISTs.
- Fix: add a FlowSchema to isolate the noisy client, fix the client (use informers, `resourceVersion=0`, pagination), reduce Event churn, scale the control plane on self-managed clusters. On managed clusters contact the provider with evidence.
- Verify rejection counters stop growing.
@diagram flow
caption: Find the noisy client
nodes:
  - "Slow API|429 and timeouts|bad"
  - "Metrics and audit|top users|info"
  - "Noisy controller|list loops|warn"
  - "Fix client and FlowSchema|stable|ok"
@h Commands
```bash title="API load diagnosis" lab
kubectl get --raw /metrics | grep apiserver_flowcontrol_rejected_requests_total | head
kubectl get --raw /debug/api_priority_and_fairness/dump_queues | head
kubectl get flowschemas
jq -r 'select(.verb=="list") | .userAgent' /var/log/kubernetes/audit.log | sort | uniq -c | sort -nr | head
```
@check
Which setting makes a LIST cheaper for the API server? || Reading from the watch cache (resourceVersion=0 or informers) and using pagination, instead of repeated full quorum reads.
@end

@concept Scenario 16, etcd database space exceeded
@plain
Writes fail with `mvcc: database space exceeded`. etcd raised a NOSPACE alarm and became read-only.
@problem
No object can be created, updated or deleted until space is recovered.
@does
- Symptom: API errors on write, `etcdctl alarm list` shows `NOSPACE`.
- Confirm: `etcdctl endpoint status` for DB size versus quota (2 GiB default, `--quota-backend-bytes`).
- Fix: compact to the latest revision, defragment each member one at a time, `alarm disarm`; then find the cause (millions of Events, leaked custom resources, large ConfigMaps).
- On EKS or Gardener the provider operates etcd; open a support case if the cluster hits storage limits.
@diagram flow
caption: Recovery steps
numbered: true
nodes:
  - "Alarm NOSPACE|read-only|bad"
  - "Compact|latest revision|info"
  - "Defrag each member|space returned|warn"
  - "Disarm and find cause|ok|ok"
@h Commands
```bash title="Compact and defrag" lab
ETCD="etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key"
rev=$($ETCD endpoint status --write-out=json | jq '.[0].Status.header.revision')
$ETCD compact $rev
$ETCD defrag
$ETCD alarm disarm
```
@end

@concept Scenario 17, Kyma APIRule returns 403 or 404
@plain
An APIRule exposes a service through the Kyma API Gateway, but calls return 403, 404 or a redirect to login.
@problem
Several layers are involved: DNS, the Istio ingress gateway, the VirtualService created by the module, JWT validation and the workload.
@does
- Symptom: `403 RBAC: access denied`, `404`, `401 Jwt verification fails`.
- Confirm: APIRule `status` (Ready or Error); the host is under your Kyma domain; the rule's access strategy (`jwt`, `noAuth`, `extAuth`) and issuer/JWKS URL; the service port; Istio sidecar injected on the workload namespace; `AuthorizationPolicy` objects generated.
- Fix: correct host/service/port, issuer and audience, enable sidecar injection (`istio-injection=enabled`) and restart Pods. Use `istioctl analyze` and proxy logs.
- Field names differ between APIRule `v2alpha1` and `v2`; check the current API Gateway module docs.
@diagram flow
caption: Request path through Kyma
nodes:
  - "Client|JWT from IAS|plain"
  - "Istio ingress gateway|host routing|cp"
  - "AuthorizationPolicy and RequestAuthentication|from APIRule|warn"
  - "Workload with sidecar|service port|app"
@h Commands
```bash title="APIRule diagnosis" lab
kubectl get apirules -A
kubectl get apirule api -n shop -o jsonpath='{.status}{"\n"}'
kubectl get authorizationpolicy,requestauthentication,virtualservice -n shop
istioctl analyze -n shop
kubectl logs -n istio-system -l app=istio-ingressgateway --tail=20
```
@check
Why must the workload namespace have Istio injection for JWT rules to apply? || Authorization is enforced by the Envoy sidecar. Without it, the policy objects cannot protect or identify the workload.
@end

@concept Scenario 18, EKS IRSA or Pod Identity AccessDenied
@plain
A Pod calls AWS and gets `AccessDenied`, or uses the node role instead of its own role.
@problem
Several trust links (ServiceAccount, OIDC provider or Pod Identity association, IAM trust policy, permissions) must all match exactly.
@does
- Symptom: `AccessDenied`, `WebIdentityErr`, `NoCredentialProviders`, or calls signed as the node instance profile.
- Confirm (IRSA): ServiceAccount annotation `eks.amazonaws.com/role-arn`; Pod has `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE` env; the cluster OIDC provider exists in IAM; trust policy `sub` equals `system:serviceaccount:NAMESPACE:NAME` and `aud` is `sts.amazonaws.com`; the SDK is recent enough.
- Confirm (Pod Identity): agent add-on running and an association for that namespace and ServiceAccount.
- Fix: correct trust policy or annotation and restart Pods (credentials are injected at Pod creation).
@diagram flow
caption: Trust chain
nodes:
  - "ServiceAccount annotation|role ARN|app"
  - "Projected token|aud sts|info"
  - "IAM trust policy|sub matches|cp"
  - "STS credentials|role permissions|ok"
@h Commands
```bash title="IRSA diagnosis" lab
kubectl get sa app -n shop -o jsonpath='{.metadata.annotations}{"\n"}'
kubectl exec -n shop deploy/app -- env | grep AWS_
kubectl exec -n shop deploy/app -- aws sts get-caller-identity
aws iam get-role --role-name app-role --query 'Role.AssumeRolePolicyDocument'
```
@end

@concept Scenario 19, Image pull rate limits and registry failures
@plain
Many Pods fail with `toomanyrequests` or `429` when pulling from a public registry, especially after a scale-out or node replacement.
@problem
All nodes pull from the same public address and hit anonymous rate limits.
@does
- Symptom: `ErrImagePull`, `You have reached your pull rate limit`, bursts after autoscaling.
- Confirm: Pod events and the registry named in the image; compare failure times with node scale events.
- Fix: authenticate pulls with `imagePullSecrets`, mirror required images into your own registry (ECR, Harbor, the company registry) with a pull-through cache, and reference your mirror. Pre-pull base images in node images where appropriate.
- Prevent: admission policy that allows only your registry; image cache on nodes.
@diagram flow
caption: Mirror to avoid limits
nodes:
  - "Public registry|rate limited|ext"
  - "Pull-through cache|your registry|cp"
  - "Nodes|pull locally|app"
  - "Pods start|ok|ok"
@h Commands
```bash title="Mirror an image" lab
kubectl get events -A --field-selector reason=Failed | grep -i 'rate\|toomany' | head
crane copy docker.io/library/nginx:1.27 registry.example.com/mirror/nginx:1.27
kubectl set image deploy/web web=registry.example.com/mirror/nginx:1.27 -n shop
```
@check
Why do failures burst after a scale-out? || New nodes have empty image caches, so every node pulls at once from the same source and hits the limit.
@end

@concept Scenario 20, Gardener maintenance stuck on a drain
@plain
A shoot reconcile or node roll stays in `Processing` because a node cannot be drained.
@problem
Nodes are not replaced, the cluster stays in a mixed state and updates appear to hang.
@does
- Symptom: shoot or worker pool shows rolling update in progress for hours; cannot evict Pods; events `Cannot evict pod as it would violate the pod's disruption budget`.
- Confirm: `kubectl get pdb -A` for `ALLOWED DISRUPTIONS 0`; single replica workloads with PDB `minAvailable: 1`; Pods without controllers; long `terminationGracePeriodSeconds`; Pods using local storage with no controller.
- Fix: scale the workload to 2 or more replicas, relax the PDB, or fix a failing readiness probe that keeps the PDB at zero. Do not delete PDBs globally.
- After the roll, verify nodes are uncordoned and schedulable.
@diagram flow
caption: Drain blocked by PDB
nodes:
  - "Node drain|eviction request|warn"
  - "PDB allows 0|single replica|bad"
  - "Scale to 2 or relax PDB|app owner|info"
  - "Drain succeeds|node replaced|ok"
@h Commands
```bash title="Find blocking budgets" lab
kubectl get pdb -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,MIN:.spec.minAvailable,MAXUN:.spec.maxUnavailable,ALLOWED:.status.disruptionsAllowed
kubectl get pods -A --field-selector spec.nodeName=NODE -o wide
kubectl get nodes -o custom-columns=NAME:.metadata.name,UNSCHEDULABLE:.spec.unschedulable
```
@end
