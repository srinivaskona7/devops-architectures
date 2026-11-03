---
title: Troubleshooting scenarios 8 to 14, rollouts, policies and access
minutes: 70
objectives:
  - Diagnose stuck rollouts, webhooks, finalizers, autoscalers, jobs, RBAC and certificates
  - Use events, conditions and logs to pin the cause
  - Apply a safe fix and verify it
---
These scenarios concern the control loops of the cluster. The cause is usually visible in a condition or event on a related object rather than on the failing one.

@concept Scenario 8, Rollout stuck
@plain
A Deployment update never completes. The new ReplicaSet does not become available within `progressDeadlineSeconds`.
@problem
Part of the fleet runs the old version, part the new, and the pipeline times out.
@does
- Symptom: `rollout status` waits, condition `Progressing=False reason=ProgressDeadlineExceeded`.
- Confirm: new Pods Pending (resources, quota), CrashLoopBackOff, ImagePull errors, readiness failing, PDB or `maxUnavailable` blocking.
- Fix the cause of the failing Pods; if urgent, `kubectl rollout undo`.
- Verify the old ReplicaSet scales down and the new one is fully available.
@diagram flow
caption: Stuck rollout causes
nodes:
  - "New ReplicaSet|Pods not Ready|warn"
  - "Pending|capacity or quota|bad"
  - "CrashLoop or probe fail|app problem|bad"
  - "Undo or fix|rollout completes|ok"
@h Commands
```bash title="Rollout diagnosis" lab
kubectl rollout status deploy/api -n shop --timeout=60s
kubectl get rs -n shop -l app=api
kubectl describe deploy api -n shop | grep -A8 Conditions
kubectl get pods -n shop -l app=api
kubectl rollout undo deploy/api -n shop
```
@check
What does ProgressDeadlineExceeded mean? || The rollout made no progress within the deadline. The Deployment reports it; it does not roll back by itself.
@end

@concept Scenario 9, A webhook blocks all changes
@plain
Creating or updating objects fails with `failed calling webhook`. An admission webhook is unreachable and set to `failurePolicy: Fail`.
@problem
Even fixing the broken service can be impossible, since the fix is itself blocked.
@does
- Symptom: `Internal error occurred: failed calling webhook "x.example.com": ... connection refused/timeout`.
- Confirm: list `ValidatingWebhookConfiguration` and `MutatingWebhookConfiguration`; check the backing Service and Pods.
- Fix: restore the webhook Pods; if not possible, delete or patch the configuration (set `failurePolicy: Ignore`) using an account that can still write webhook configs.
- Prevent: exclude `kube-system` and the webhook's own namespace with `namespaceSelector`, run 2 or more replicas with PDB, use `timeoutSeconds` low.
@diagram flow
caption: Deadlock
nodes:
  - "Create Pod|API request|app"
  - "Webhook call|service has no endpoints|bad"
  - "Request rejected|failurePolicy Fail|bad"
  - "Delete webhook config|unblocks|ok"
@h Commands
```bash title="Webhook rescue" lab
kubectl get validatingwebhookconfigurations,mutatingwebhookconfigurations
kubectl get validatingwebhookconfiguration policy-webhook -o jsonpath='{range .webhooks[*]}{.name}{" "}{.failurePolicy}{" "}{.clientConfig.service.name}{"\n"}{end}'
kubectl delete validatingwebhookconfiguration policy-webhook
```
:::warn
Deleting a security webhook removes protection. Do it only to recover, and restore it from Git afterwards.
:::
@end

@concept Scenario 10, Namespace stuck Terminating
@plain
A namespace deletion never finishes. Remaining objects have finalizers, or an API service is unavailable so the controller cannot list all resources.
@problem
CI environments and cleanup jobs hang, and names cannot be reused.
@does
- Symptom: namespace `Terminating` for a long time; `status.conditions` explain what remains.
- Confirm: `kubectl get ns NAME -o yaml`; list all resource types in the namespace; check `kubectl get apiservices` for `False` entries.
- Frequent causes: CRs whose controller was removed (finalizer never cleared), PVCs with `kubernetes.io/pvc-protection`, broken aggregated API such as metrics-server.
- Fix: repair the controller or API service; as a last resort remove the finalizer on the stuck object (`kubectl patch ... --type=merge -p '{"metadata":{"finalizers":null}}'`), accepting that external resources may be left behind.
@diagram flow
caption: Finding what blocks deletion
numbered: true
nodes:
  - "Namespace conditions|read status|info"
  - "Remaining objects|list all types|app"
  - "Broken APIService|discovery failure|warn"
  - "Clear finalizer|last resort|bad"
@h Commands
```bash title="Find leftovers" lab
kubectl get ns stuck -o jsonpath='{range .status.conditions[*]}{.type}{": "}{.message}{"\n"}{end}'
kubectl api-resources --verbs=list --namespaced -o name | xargs -n1 kubectl get --ignore-not-found -n stuck --show-kind
kubectl get apiservices | grep False
```
@check
Why is clearing a finalizer a last resort? || The finalizer exists to clean external resources. Removing it skips that clean-up and can leave cloud resources behind.
@end

@concept Scenario 11, HPA shows unknown metrics
@plain
The Horizontal Pod Autoscaler reports `<unknown>/80%` and does not scale.
@problem
Load grows and replicas stay at the minimum.
@does
- Symptom: `kubectl get hpa` shows `<unknown>`; events `FailedGetResourceMetric`.
- Confirm: metrics-server is running (`kubectl top pods` works); the target Pods define CPU `requests` (utilisation is relative to requests); the APIService `v1beta1.metrics.k8s.io` is available; for custom metrics check the adapter.
- Fix: install or repair metrics-server (on some clusters add `--kubelet-insecure-tls` only in labs), add requests to the Deployment.
- Verify: HPA shows numbers and replicas change under load.
@diagram flow
caption: Metrics path
nodes:
  - "kubelet|cAdvisor stats|app"
  - "metrics-server|aggregates|cp"
  - "metrics API|metrics.k8s.io|info"
  - "HPA|computes replicas|ok"
@h Commands
```bash title="HPA checks" lab
kubectl describe hpa api -n shop | tail -15
kubectl top pods -n shop
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl get deploy api -n shop -o jsonpath='{.spec.template.spec.containers[*].resources}{"\n"}'
```
@end

@concept Scenario 12, CronJob does not run
@plain
A CronJob exists but no Jobs appear, or Jobs appear but fail.
@problem
Scheduled backups and cleanups silently stop.
@does
- Symptom: `LAST SCHEDULE` is empty or old; no Job objects.
- Confirm: `suspend: true`; invalid cron expression or time zone; `startingDeadlineSeconds` too short after controller downtime; `concurrencyPolicy: Forbid` with a stuck earlier Job; quota blocking Pod creation; image or RBAC errors in the created Pods.
- Fix: unsuspend, correct the schedule, delete the stuck Job, raise the deadline, and test with `kubectl create job --from=cronjob/NAME test-run`.
- Alert on `kube_cronjob_status_last_successful_time` age.
@diagram flow
caption: Why no run
nodes:
  - "suspend true|paused|warn"
  - "Previous Job stuck|Forbid policy|warn"
  - "Deadline missed|skipped|bad"
  - "Manual test job|prove the template works|ok"
@h Commands
```bash title="CronJob diagnosis" lab
kubectl get cronjob cleanup -n batch -o jsonpath='{.spec.suspend} {.spec.schedule} {.status.lastScheduleTime}{"\n"}'
kubectl get jobs -n batch --sort-by=.metadata.creationTimestamp | tail
kubectl create job --from=cronjob/cleanup test-run -n batch
kubectl logs job/test-run -n batch
```
@check
How can you test a CronJob without waiting for the schedule? || Create a Job from it with kubectl create job --from=cronjob/NAME.
@end

@concept Scenario 13, Forbidden by RBAC
@plain
A user, pipeline or controller receives `forbidden: User "x" cannot list resource "pods"`.
@problem
Permissions are spread over Roles, ClusterRoles, bindings and groups, so the missing link is hard to see.
@does
- Symptom: `Error from server (Forbidden)` with the user, verb, resource, namespace.
- Confirm: `kubectl auth can-i VERB RESOURCE --as=USER -n NS`; check which bindings reference the subject; verify group claims from OIDC; check subresources (`pods/log`, `pods/exec`) and API groups (`apps`).
- Fix: add the minimum verb on the exact resource; prefer a Role in the namespace; avoid wildcards.
- For ServiceAccounts remember the full name `system:serviceaccount:NAMESPACE:NAME`.
@diagram flow
caption: Tracing a denial
nodes:
  - "Error message|user verb resource|bad"
  - "can-i --as|reproduce|info"
  - "Bindings and groups|who has what|app"
  - "Add narrow rule|verify|ok"
@h Commands
```bash title="RBAC checks" lab
kubectl auth can-i list pods --as=system:serviceaccount:ci:deployer -n shop
kubectl auth can-i --list --as=system:serviceaccount:ci:deployer -n shop | head -20
kubectl get rolebindings,clusterrolebindings -A -o wide | grep deployer
kubectl auth whoami
```
@end

@concept Scenario 14, Expired or unissued certificates
@plain
Browsers show certificate errors, or a Certificate stays `Ready=False` in cert-manager.
@problem
Expiry causes sudden outages, and issuance depends on DNS or HTTP challenges that can silently fail.
@does
- Symptom: `x509: certificate has expired`, `NET::ERR_CERT_DATE_INVALID`, Certificate not Ready.
- Confirm with chain: `Certificate` then `CertificateRequest` then `Order` then `Challenge`; read their events. Check the ClusterIssuer, ACME rate limits, DNS-01 credentials (IAM/IRSA), HTTP-01 reachability and Gateway or Ingress class.
- Fix the failing link; renew with `cmctl renew NAME`.
- Prevent: alert when `certmanager_certificate_expiration_timestamp_seconds` is within 14 days.
@diagram flow
caption: cert-manager chain
nodes:
  - "Certificate|desired cert|app"
  - "CertificateRequest|CSR|info"
  - "Order and Challenge|ACME proof|warn"
  - "Secret|issued cert|ok"
@h Commands
```bash title="cert-manager diagnosis" lab
kubectl get certificate,certificaterequest,order,challenge -n shop
kubectl describe challenge -n shop | tail -20
cmctl status certificate web-tls -n shop
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null | openssl x509 -noout -dates
```
@check
What is the order of cert-manager objects during ACME issuance? || Certificate, CertificateRequest, Order, Challenge. Failures show in the lowest object that exists.
@end
