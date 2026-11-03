---
title: Admission and conversion webhooks
minutes: 45
objectives:
  - Place mutating and validating webhooks in the admission chain
  - Configure a webhook safely with failure policy, selectors and timeouts
  - Use ValidatingAdmissionPolicy and conversion webhooks, and debug webhook outages
---
Webhooks let external services take part in API requests. They power policy engines, sidecar injection and CRD version conversion. They are also a leading cause of cluster-wide outages when badly configured.
@concept The admission chain
@plain
After a request is authenticated and authorised, it passes through admission. **Mutating** admission can change the object; **validating** admission can only accept or reject. Then the object is stored.
@problem
RBAC says who may create a Pod, not what the Pod may contain. You need a place to enforce rules (no `latest` tags, required labels) and to inject defaults (sidecars, resource limits).
@does
- Order: authentication, authorisation, **mutating** admission (plugins, then webhooks), schema validation, **validating** admission (plugins, webhooks, ValidatingAdmissionPolicy), persist to etcd.
- Admission applies to create, update, delete and connect operations, not to reads.
- Built-in plugins include LimitRanger, ResourceQuota, ServiceAccount, PodSecurity and NodeRestriction.
- Mutating webhooks may run more than once if another one changes the object (reinvocation); keep them idempotent.
@diagram flow
caption: Request path through the API server
numbered: true
nodes:
  - "AuthN and AuthZ|who and may they|cp"
  - "Mutating admission|defaults, sidecars|warn"
  - "Schema validation|OpenAPI|info"
  - "Validating admission|policy and rules|bad"
  - "etcd|stored|db"
@h Which webhooks are installed
```bash title="Inspect the chain" lab
kubectl get mutatingwebhookconfigurations
kubectl get validatingwebhookconfigurations
kubectl get validatingadmissionpolicies,validatingadmissionpolicybindings
kubectl get mutatingwebhookconfiguration istio-sidecar-injector -o jsonpath='{.webhooks[*].failurePolicy}{"\n"}'
```
@end

@concept Writing a validating webhook configuration
@plain
A webhook configuration tells the API server which requests to send to which HTTPS endpoint, and what to do if it cannot be reached.
@problem
A webhook that matches too much, or fails closed while its Pod is down, can block all Pod creation, including the Pods needed to fix the webhook.
@does
- `rules` select operations, API groups and resources. `namespaceSelector` and `objectSelector` narrow the scope. **Exclude `kube-system` and the webhook's own namespace.**
- `failurePolicy`: `Fail` rejects when the webhook errors or times out (safe but risky); `Ignore` lets requests through (available but unenforced).
- `timeoutSeconds` (1 to 30, default 10) caps the delay added to every matching request.
- `sideEffects` must be `None` or `NoneOnDryRun` for dry-run to work. `matchConditions` (CEL) filter requests before the call, reducing load.
- TLS: the API server needs a CA bundle (`caBundle`) for the service certificate; cert-manager can inject it.
@diagram flow
caption: Failure policy decides availability
nodes:
  - "API request|create Pod|app"
  - "Webhook down|connection refused|bad"
  - "failurePolicy Fail|request rejected|warn"
  - "failurePolicy Ignore|request allowed|ok"
@h A configuration with guardrails
```yaml title="validating-webhook.yaml"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: policy-check
  annotations:
    cert-manager.io/inject-ca-from: policy-system/policy-webhook-cert
webhooks:
  - name: pods.policy.example.com
    admissionReviewVersions: ["v1"]
    sideEffects: None
    timeoutSeconds: 5
    failurePolicy: Fail
    clientConfig:
      service:
        name: policy-webhook
        namespace: policy-system
        path: /validate-pods
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE"]
        resources: ["pods"]
    namespaceSelector:
      matchExpressions:
        - key: kubernetes.io/metadata.name
          operator: NotIn
          values: ["kube-system", "policy-system"]
    matchConditions:
      - name: skip-system-pods
        expression: "!object.metadata.name.startsWith('kube-')"
```
@end

@concept The AdmissionReview exchange
@plain
The API server POSTs an `AdmissionReview` JSON document containing the object and request details. The webhook answers with an `AdmissionReview` response with `allowed` true or false, and for mutation a JSON Patch.
@problem
You need to know the contract to write, test and debug a webhook without a framework hiding it.
@does
- Request contains `uid`, `kind`, `operation`, `userInfo`, `object` and `oldObject`.
- The response must echo the same `uid`. Rejection includes `status.message`, which the user sees in the error.
- Mutation returns `patchType: JSONPatch` and a base64 encoded patch.
- Webhook servers should respond fast and be stateless, run with several replicas, spread across nodes, and have a PodDisruptionBudget.
@diagram seq
caption: One admission call
actors: ["API server|caller|cp", "Webhook|policy service|app"]
steps:
  - "0>1: AdmissionReview request with object | req"
  - "note 1..1: evaluate rules"
  - "1>0: allowed true and JSON patch | resp"
  - "1>0: allowed false and message | bad"
@h Response shapes
```json title="admission-response.json"
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "response": {
    "uid": "705ab4f5-6393-11e8-b7cc-42010a800002",
    "allowed": false,
    "status": {
      "code": 403,
      "message": "image must not use the latest tag"
    }
  }
}
```
@end

@concept ValidatingAdmissionPolicy with CEL
@plain
**ValidatingAdmissionPolicy (VAP)** lets you write validation rules in CEL that run inside the API server, with no webhook service to host. A binding says where the policy applies.
@problem
Webhooks need a running service, certificates and careful failure handling. For many simple rules that is more infrastructure than the rule is worth.
@does
- Stable (GA) since 1.30. A policy defines `matchConstraints`, optional `paramKind`, `variables` and `validations`; a `ValidatingAdmissionPolicyBinding` selects namespaces and sets `validationActions` (`Deny`, `Warn`, `Audit`).
- Use `Warn` and `Audit` first to see what would be blocked, then switch to `Deny`.
- Mutating counterpart `MutatingAdmissionPolicy` is newer; check its status in your Kubernetes version before relying on it.
- Kyverno and OPA Gatekeeper still add richer features: mutation, generation, external data, reporting.
@diagram cmp
caption: Policy mechanisms
cards:
  - {h: "ValidatingAdmissionPolicy", kind: ok, items: ["CEL in the API server", "No extra service", "Validate only"]}
  - {h: "Kyverno or Gatekeeper", kind: info, items: ["Webhook based", "Mutate, generate, report", "More to operate"]}
  - {h: "Custom webhook", kind: warn, items: ["Any logic", "You own availability", "Highest risk"]}
@h Disallow latest tags
```yaml title="no-latest.yaml"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: no-latest-tag
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments"]
  validations:
    - expression: "object.spec.template.spec.containers.all(c, !c.image.endsWith(':latest') && c.image.contains(':'))"
      message: "images must have an explicit tag and not use latest"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: no-latest-tag
spec:
  policyName: no-latest-tag
  validationActions: ["Warn", "Audit"]
  matchResources:
    namespaceSelector:
      matchLabels:
        env: prod
```
@end

@concept Conversion webhooks
@plain
A **conversion webhook** converts a custom resource between versions when a client asks for a version that differs from the stored one. It is the CRD counterpart of admission webhooks.
@problem
When v1 renames `spec.size` to `spec.storageGB`, old clients still read and write v1beta1. The API server needs a way to translate both ways without losing data.
@does
- Set `spec.conversion.strategy: Webhook` in the CRD with the service and `conversionReviewVersions`.
- The webhook receives a `ConversionReview` with a list of objects and a `desiredAPIVersion`, and returns the converted list.
- Conversions must be **lossless and round-trip safe**: converting there and back gives the original. Use annotations to hold fields that older versions cannot represent.
- The webhook becomes a dependency of reads and writes for that CRD; if it is down, requests for that type fail. controller-runtime supports a hub and spoke model: every version converts to and from one hub version.
@diagram flow
caption: Hub and spoke conversion
nodes:
  - "v1beta1 client|reads old shape|ext"
  - "Conversion webhook|translates via hub v1|app"
  - "Stored as v1|one storage version|db"
  - "v1 client|reads new shape|ext"
@h CRD conversion section
```yaml title="crd-conversion.yaml"
spec:
  conversion:
    strategy: Webhook
    webhook:
      conversionReviewVersions: ["v1"]
      clientConfig:
        service:
          name: database-operator-webhook
          namespace: database-system
          path: /convert
```
@check
What happens to reads of a custom resource if its conversion webhook is down? || Requests that need conversion fail, because the API server cannot translate between the stored and requested versions.
@end

@concept Debugging and hardening webhooks
@plain
Webhook failures show up as odd API errors: timeouts when creating Pods, `failed calling webhook`, or Helm installs that hang. Know the symptoms and the emergency exit.
@problem
A broken policy webhook can block Pod creation cluster-wide, including the controllers that would repair it, and the fix itself requires creating Pods.
@does
- Typical errors: `failed calling webhook "...": context deadline exceeded` (slow or unreachable), `x509: certificate signed by unknown authority` (bad `caBundle`), `no endpoints available for service` (webhook Pods down).
- Emergency: delete or patch the `failurePolicy` of the configuration with `kubectl`; this works because API requests for webhook configurations themselves are not sent to webhooks.
- Hardening: replicas of 2 or more with anti-affinity, PDB, a priority class, namespace exclusions, short timeouts, and `matchConditions`.
- On EKS the control plane must reach the webhook Pod: security groups must allow the control plane to the webhook port (commonly 8443, 9443). Gardener and Kyma usually run webhooks within the cluster network without extra rules.
- Observe: `apiserver_admission_webhook_rejection_count` and `apiserver_admission_webhook_admission_duration_seconds` metrics.
@diagram flow
caption: Recovering from a failing webhook
nodes:
  - "Webhook call failed|API requests failing|bad"
  - "Check endpoints and certs|kubectl get endpoints, logs|info"
  - "Set failurePolicy Ignore|or delete configuration|warn"
  - "Fix and restore Fail|after the webhook is healthy|ok"
@h Commands
```bash title="Triage and emergency steps" lab
kubectl get endpoints policy-webhook -n policy-system
kubectl logs -n policy-system deploy/policy-webhook --tail=30
kubectl get validatingwebhookconfiguration policy-check -o jsonpath='{.webhooks[*].failurePolicy}{"\n"}'
# emergency: stop blocking the cluster, then fix and revert
kubectl patch validatingwebhookconfiguration policy-check --type=json \
  -p='[{"op":"replace","path":"/webhooks/0/failurePolicy","value":"Ignore"}]'
kubectl get --raw /metrics | grep apiserver_admission_webhook_rejection_count | head
```
:::warn
Remember to set `failurePolicy` back after the incident, and add a PDB and exclusions so it cannot happen again. An `Ignore` left in place silently disables your policy.
:::
@end
