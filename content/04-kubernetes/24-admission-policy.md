---
title: Admission webhooks and policy engines
minutes: 50
objectives:
  - Write ValidatingAdmissionPolicy rules in CEL
  - Explain webhook configuration, failure policy and safe operation
  - Compare Kyverno and OPA Gatekeeper and write one policy in each
---
RBAC says who may act. Admission policy says what a request may contain. This is where you enforce labels, resource limits, trusted registries and security settings.

@concept Admission webhooks
@plain
A webhook admission controller sends the request to an HTTPS service you run. The service answers allow, deny or a patch.
@problem
Built-in admission cannot know your organisation's rules.
@does
- `MutatingWebhookConfiguration` and `ValidatingWebhookConfiguration` list rules (operations, resources), the service, `failurePolicy`, `timeoutSeconds` and selectors.
- The API server calls the webhook with an `AdmissionReview` and expects an answer within the timeout (default 10 s, max 30 s).
- `failurePolicy: Fail` blocks requests if the webhook is down; `Ignore` lets them through.
- `namespaceSelector`, `objectSelector` and `matchConditions` (CEL) narrow what is sent.
- Webhook servers need a trusted TLS certificate, usually via cert-manager `caBundle` injection.
@diagram seq
caption: A validating webhook call
actors: ["API server|cp|cp", "Webhook service|policy engine|info"]
steps:
  - "0>1: AdmissionReview Pod create | tls"
  - "note 1..1: check rules"
  - "1>0: allowed false, reason | bad"
  - "0>1: next request | tls"
  - "1>0: allowed true | resp"
@h Webhook configuration
```yaml title="webhook-config.yaml"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingWebhookConfiguration
metadata:
  name: policy-check
  annotations:
    cert-manager.io/inject-ca-from: policy/policy-webhook
webhooks:
  - name: pods.policy.example.com
    admissionReviewVersions: ["v1"]
    sideEffects: None
    timeoutSeconds: 5
    failurePolicy: Fail
    clientConfig:
      service:
        name: policy-webhook
        namespace: policy
        path: /validate
    rules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
    namespaceSelector:
      matchExpressions:
        - {key: kubernetes.io/metadata.name, operator: NotIn, values: [kube-system, policy]}
```
:::danger
Exclude `kube-system` and the webhook's own namespace. A `Fail` webhook that blocks its own Pods can prevent the cluster from recovering.
:::
@end

@concept ValidatingAdmissionPolicy with CEL
@plain
ValidatingAdmissionPolicy (VAP) runs validation rules written in CEL inside the API server, with no webhook service. It is stable since 1.30.
@problem
Webhooks need a service, certificates and high availability just to check one field.
@does
- A `ValidatingAdmissionPolicy` holds `matchConstraints`, `validations` (CEL expressions with messages) and optional `variables`.
- A `ValidatingAdmissionPolicyBinding` applies it to namespaces with an action: `Deny`, `Warn` or `Audit`.
- `paramKind` lets a policy read thresholds from a CRD or ConfigMap, so one policy serves many teams.
- Fast, in-process and fail-safe: no network call.
- A `MutatingAdmissionPolicy` equivalent is newer and less widely available; check your version.
@diagram flow
caption: CEL in the API server
nodes:
  - "Request|Deployment create|ext"
  - "Policy and binding|CEL rules|cp"
  - "Result|Deny, Warn or Audit|ok"
@h Require resource limits and a team label
```yaml title="vap.yaml"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: require-team-and-memory-limit
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: ["apps"]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["deployments"]
  validations:
    - expression: "has(object.metadata.labels) && 'team' in object.metadata.labels"
      message: "Deployment must have a team label"
    - expression: >-
        object.spec.template.spec.containers.all(c,
        has(c.resources) && has(c.resources.limits) && 'memory' in c.resources.limits)
      message: "Every container needs a memory limit"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: require-team-and-memory-limit
spec:
  policyName: require-team-and-memory-limit
  validationActions: ["Deny"]
  matchResources:
    namespaceSelector:
      matchLabels:
        policy: enforced
```
@check
Why use VAP before writing a webhook? || It runs inside the API server, needs no service or certificates and cannot be down.
@end

@concept Kyverno
@plain
Kyverno is a Kubernetes-native policy engine whose policies are plain YAML. It can validate, mutate, generate and verify images.
@problem
Writing Rego or webhook servers is a barrier for platform teams that think in Kubernetes manifests.
@does
- `ClusterPolicy` or the newer `ValidatingPolicy`, `MutatingPolicy` and related CEL-based policies in current releases; check the API available in your installed version.
- Rule types: **validate** (block or audit), **mutate** (add defaults), **generate** (create NetworkPolicy or quota for each new namespace), **verifyImages** (signature checks).
- `validationFailureAction: Audit` reports to PolicyReports without blocking, useful for rollout.
- `kyverno test` and the CLI let you run policies in CI against manifests.
@diagram layers
caption: Kyverno capabilities
layers:
  - {label: "Admission", nodes: ["validate|block bad objects|ok", "mutate|set defaults|info", "verifyImages|signatures|ok"]}
  - {label: "Background", nodes: ["generate|per namespace objects|app", "PolicyReport|existing violations|warn"]}
@h Disallow latest tag and generate a default deny
```yaml title="kyverno.yaml"
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: disallow-latest-tag
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: no-latest
      match:
        any:
          - resources:
              kinds: ["Pod"]
      validate:
        message: "Images must use a pinned tag, not latest."
        pattern:
          spec:
            containers:
              - image: "!*:latest"
---
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: default-deny-netpol
spec:
  rules:
    - name: generate-deny
      match:
        any:
          - resources:
              kinds: ["Namespace"]
      generate:
        apiVersion: networking.k8s.io/v1
        kind: NetworkPolicy
        name: default-deny
        namespace: "{{request.object.metadata.name}}"
        synchronize: true
        data:
          spec:
            podSelector: {}
            policyTypes: ["Ingress"]
```
@end

@concept OPA Gatekeeper
@plain
Gatekeeper enforces policies written in Rego through **ConstraintTemplates** (the logic) and **Constraints** (where and how it applies).
@problem
Organisations that already use OPA for other systems want one policy language across them.
@does
- A ConstraintTemplate defines a new CRD and its Rego; a Constraint is an instance that carries parameters.
- `enforcementAction`: `deny`, `warn` or `dryrun`.
- Audit controller scans existing objects and lists violations on the constraint status.
- Config sync can replicate resources into OPA for cross-object checks.
- Compared with Kyverno: more flexible logic and shared language with Conftest in CI, but a steeper learning curve and no built-in generate.
@diagram cmp
caption: Kyverno versus Gatekeeper
cards:
  - {h: "Kyverno", kind: ok, items: ["YAML policies", "Mutate and generate built in", "Image verification"]}
  - {h: "Gatekeeper", kind: info, items: ["Rego language", "Template plus constraint", "Reuse OPA skills"]}
@h Required labels constraint
```yaml title="gatekeeper.yaml"
apiVersion: templates.gatekeeper.sh/v1
kind: ConstraintTemplate
metadata:
  name: k8srequiredlabels
spec:
  crd:
    spec:
      names:
        kind: K8sRequiredLabels
      validation:
        openAPIV3Schema:
          type: object
          properties:
            labels:
              type: array
              items:
                type: string
  targets:
    - target: admission.k8s.gatekeeper.sh
      rego: |
        package k8srequiredlabels
        violation[{"msg": msg}] {
          required := input.parameters.labels[_]
          not input.review.object.metadata.labels[required]
          msg := sprintf("missing required label: %v", [required])
        }
---
apiVersion: constraints.gatekeeper.sh/v1beta1
kind: K8sRequiredLabels
metadata:
  name: ns-must-have-team
spec:
  enforcementAction: deny
  match:
    kinds:
      - apiGroups: [""]
        kinds: ["Namespace"]
  parameters:
    labels: ["team"]
```
@choose Policy engine
ValidatingAdmissionPolicy | simple field checks with no extra install | you need mutate, generate or cross-resource lookups
Kyverno | Kubernetes teams who want YAML policies and generation | you require a single language shared with non-Kubernetes OPA
Gatekeeper | complex logic and shared Rego across systems | your team does not want to learn Rego
@end

@concept Operating policy safely
@plain
Policies are production code. Roll them out in stages, test them and watch the webhooks.
@problem
A new deny rule can stop deployments across the company on a Friday.
@does
- Start in `Audit` or `Warn`, read the reports, fix owners, then enforce.
- Exempt system namespaces and the policy engine itself; use `matchConditions` to narrow scope.
- Run the policy engine with multiple replicas, PDB, anti-affinity and a high priority class; monitor webhook latency and failures (`apiserver_admission_webhook_rejection_count`).
- Version policies in Git, test with `kyverno test` or `gator verify`, and ship via GitOps.
- Provide clear messages: tell developers exactly how to fix the rejection.
@diagram flow
caption: Policy rollout
numbered: true
nodes:
  - "Write and test|CI|info"
  - "Audit mode|collect violations|warn"
  - "Notify owners|fix workloads|app"
  - "Enforce|deny new violations|ok"
@h Test commands
```bash title="Policy in CI" lab
kyverno test ./policies
kyverno apply ./policies --resource ./manifests/deploy.yaml
gator verify ./gatekeeper-tests
kubectl get policyreport -A
kubectl get constraints
```
@end
