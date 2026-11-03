---
title: API request flow
minutes: 50
objectives:
  - Follow a request through authentication, authorisation, admission, validation and persistence
  - Explain resourceVersion, watches and server-side apply
  - Debug a rejected request from its error message
---
Every change in Kubernetes is an HTTPS request to the API server. Knowing the stages in order tells you which layer rejected you and why.

@concept Resources, groups and versions
@plain
Every object type has a **group**, a **version** and a **kind**, for example `apps/v1` and `Deployment`. The REST path is built from them.
@problem
Types change over time. Versioned APIs let the project add fields and retire old shapes without breaking existing manifests.
@does
- The core group has no name: `/api/v1/pods`. Others use `/apis/apps/v1/deployments`.
- Maturity is encoded in the version: `v1` stable, `v1beta1` pre-release, `v1alpha1` experimental and off by default.
- Objects are stored in one storage version; the API server converts between served versions.
- Deprecated versions are removed after announced periods, so run a deprecation check before upgrades.
@diagram flow
caption: Anatomy of an API path
nodes:
  - "/apis|extension groups|plain"
  - "apps/v1|group and version|info"
  - "namespaces/shop|scope|env"
  - "deployments/web|resource and name|app"
@h Explore the API
```bash title="Discover kinds and fields" lab
kubectl api-resources --api-group=apps -o wide
kubectl api-versions | head
kubectl explain deployment.spec.strategy --recursive | head -30
kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis | head -3
```
@end

@concept The request pipeline
@plain
A write passes through fixed stages: authentication, authorisation, mutating admission, schema validation, validating admission, and finally storage in etcd.
@problem
Without ordered gates, a client could write unvalidated or unauthorised objects. Each stage answers a different question.
@does
- **Authentication**: who are you.
- **Authorisation**: may you do this verb on this resource.
- **Mutating admission**: change the object, for example inject defaults or sidecars.
- **Validation** against the schema, then **validating admission**: accept or reject the final object.
- **Persistence** to etcd. Only then do controllers see it.
@diagram flow
caption: The path of one write
numbered: true
nodes:
  - "Authn|who|cp"
  - "Authz|allowed|cp"
  - "Mutating admission|may change|warn"
  - "Schema validation|valid shape|cp"
  - "Validating admission|policy|warn"
  - "etcd|persisted|ok"
@h Rejections tell you the stage
```bash title="Reading errors" lab
kubectl auth whoami                                  # authentication result (1.28+)
kubectl auth can-i create deployments -n shop       # authorisation check
kubectl apply --dry-run=server -f deploy.yaml       # runs the whole pipeline without storing
```
:::tip
`--dry-run=server` runs admission and validation exactly as a real apply would. `--dry-run=client` only checks locally and misses webhook and policy rejections.
:::
@check
A request fails with "forbidden". Which stage rejected it? || Authorisation. A 401 means authentication failed; a webhook denial mentions "admission webhook" or a policy name.
@end

@concept Authentication
@plain
The API server decides who you are from a credential on the request. It has no user database of its own for people.
@problem
The cluster must identify humans, workloads and nodes without storing passwords. It delegates trust to certificates, tokens and external identity providers.
@does
- X.509 client certificates: the common name becomes the user, organisation fields become groups. Used by kubelets and admin kubeconfigs.
- **ServiceAccount tokens**: signed JWTs for workloads, normally short lived and projected into Pods.
- **OIDC**: the API server trusts an external IdP (for example SAP IAS or Entra ID) and reads username and group claims from the ID token.
- Webhook token authentication and EKS `aws-iam-authenticator` or access entries plug in the same way.
- A request that matches no authenticator becomes `system:anonymous` or is rejected with 401.
@diagram cmp
caption: Common credentials
cards:
  - {h: "Client certificate", kind: info, items: ["Kubelets, bootstrap admin", "Hard to revoke"]}
  - {h: "ServiceAccount token", kind: app, items: ["Workloads in the cluster", "Audience bound, expires"]}
  - {h: "OIDC ID token", kind: ok, items: ["Humans via company IdP", "Groups come from claims"]}
  - {h: "Cloud IAM", kind: ext, items: ["EKS access entries", "Maps IAM to Kubernetes users"]}
@h Kubeconfig with OIDC login
```yaml title="kubeconfig user using the kubelogin plugin"
apiVersion: v1
kind: Config
clusters:
  - name: dev
    cluster:
      server: https://api.dev.example.com
      certificate-authority-data: LS0tLS1CRUdJTi0tLS0t
contexts:
  - name: dev
    context: {cluster: dev, user: oidc-user}
current-context: dev
users:
  - name: oidc-user
    user:
      exec:
        apiVersion: client.authentication.k8s.io/v1
        command: kubectl
        args:
          - oidc-login
          - get-token
          - --oidc-issuer-url=https://tenant.accounts.example.com
          - --oidc-client-id=kubernetes
        interactiveMode: IfAvailable
```
@end

@concept Authorisation
@plain
After identity is known, authorisers decide whether that identity may perform a verb (get, create, delete) on a resource in a namespace.
@problem
Being logged in must not mean being allowed to do anything. Fine grained rules keep a team out of another team's namespace.
@does
- Modes are configured on the API server and checked in order. **Node** and **RBAC** are the usual pair; webhook authorisers can be added.
- The decision is allow, deny or no opinion; if nobody allows, the request is denied.
- RBAC is purely additive: there are no deny rules.
- Authorisation sees verbs, resources and names, not the object content. Content rules belong to admission.
@diagram flow
caption: Authorisers are asked in order
nodes:
  - "Request|user, verb, resource|ext"
  - "Node authorizer|kubelet access|cp"
  - "RBAC|roles and bindings|cp"
  - "Webhook|optional external|info"
  - "Allow or 403|first allow wins|ok"
@h Test permissions
```bash title="Ask the authoriser" lab
kubectl auth can-i delete pods -n shop
kubectl auth can-i --list -n shop | head
kubectl auth can-i get secrets -n shop --as=system:serviceaccount:shop:web
```
@end

@concept Admission control
@plain
Admission controllers are plug-ins that inspect or change a request after it is authorised and before it is stored. They apply to create, update and delete, but not to reads.
@problem
RBAC cannot say "no container may run as root" or "every Pod needs a cost label". Admission sees the full object and can enforce such rules.
@does
- **Mutating** controllers run first and may modify the object, for example default StorageClass, Istio sidecar injection, or a Kyverno mutate rule.
- **Validating** controllers run after and can only accept or reject.
- Built-ins include `NamespaceLifecycle`, `LimitRanger`, `ResourceQuota`, `ServiceAccount` and Pod Security Admission.
- Your own rules arrive through webhooks, `ValidatingAdmissionPolicy` (CEL) and policy engines.
@diagram layers
caption: Admission is two phases with a schema check between
layers:
  - {label: "Phase 1 mutating", nodes: ["Built-in defaults|LimitRanger, StorageClass|cp", "Mutating webhooks|sidecars, labels|warn"]}
  - {label: "Between", nodes: ["Object schema validation|reject unknown shapes|info"]}
  - {label: "Phase 2 validating", nodes: ["Pod Security Admission|baseline, restricted|cp", "ValidatingAdmissionPolicy|CEL rules|ok", "Validating webhooks|Kyverno, Gatekeeper|warn"]}
@h Which webhooks are active
```bash title="List admission configuration" lab
kubectl get mutatingwebhookconfigurations
kubectl get validatingwebhookconfigurations
kubectl get validatingadmissionpolicies,validatingadmissionpolicybindings
```
:::danger
A validating webhook with `failurePolicy: Fail` that targets kube-system or its own namespace can lock the cluster when the webhook Pod is down. Exclude system namespaces and the webhook itself.
:::
@check
Can a validating webhook modify an object? || No. Only mutating admission can change it; validating can only accept or deny.
@end

@concept Validation, persistence and optimistic concurrency
@plain
Every object carries a `resourceVersion`. An update succeeds only if the version you send is still the current one.
@problem
Two controllers or people editing the same object can overwrite each other's changes silently.
@does
- The API server rejects an update with a stale version with **409 Conflict**, and the client re-reads and retries.
- Schema validation rejects unknown or mistyped fields (strict field validation is on by default in kubectl).
- After a successful write, `metadata.generation` increases when the spec changes, and controllers record `status.observedGeneration` to show they have caught up.
- Deleting with a finalizer sets `deletionTimestamp` but keeps the object until the finalizer is removed.
@diagram seq
caption: A conflict and its retry
actors: ["Client A|controller|app", "API server|cp|cp", "Client B|you|ext"]
steps:
  - "0>1: GET rv=100 | req"
  - "2>1: GET rv=100 | req"
  - "2>1: PUT rv=100 | req"
  - "1>2: OK rv=101 | resp"
  - "0>1: PUT rv=100 | req"
  - "1>0: 409 Conflict | bad"
  - "note 0..1: A re-reads and retries"
@h See the fields
```bash title="Metadata the server maintains" lab
kubectl create deployment demo --image=nginx:1.27
kubectl get deploy demo -o jsonpath='{.metadata.resourceVersion} gen={.metadata.generation} observed={.status.observedGeneration}{"\n"}'
kubectl scale deploy demo --replicas=2
kubectl get deploy demo -o jsonpath='{.metadata.resourceVersion} gen={.metadata.generation}{"\n"}'
kubectl delete deploy demo
```
@end

@concept Watches and informers
@plain
A `watch` is a long lived HTTP request that streams changes to objects. Controllers use it instead of polling.
@problem
Polling thousands of objects constantly would overload the API server and react slowly.
@does
- A client lists once, remembers the `resourceVersion`, then watches from that point.
- If the version is too old (compacted away) the server answers 410 Gone and the client must list again.
- Informers keep an in-memory cache and share one watch among many handlers, which is why a controller restart costs one list.
- **Watch bookmarks** and API Priority and Fairness protect the server from noisy clients.
@diagram flow
caption: List then watch
nodes:
  - "LIST|snapshot and resourceVersion|info"
  - "WATCH from rv|stream of ADDED MODIFIED DELETED|cp"
  - "Local cache|informer store|app"
  - "Handler|reconcile|ok"
@h Try a watch
```bash title="Streaming changes" lab
kubectl get pods -w --output-watch-events    # shows the event type per change
kubectl get --raw '/api/v1/namespaces/default/pods?watch=1&timeoutSeconds=5' | head -c 400
```
@end

@concept Server-side apply
@plain
Server-side apply (SSA) lets the API server track which actor owns which field and merge changes from several actors safely.
@problem
When a controller (such as an HPA setting `replicas`) and your Git manifest both write the same field, a client-side merge makes them fight.
@does
- Each field records a **manager** in `metadata.managedFields`.
- Applying a value another manager owns raises a conflict unless you use `--force-conflicts`.
- Removing a field from your manifest removes it from the object only if you owned it.
- Flux and Argo CD can use SSA. Use `kubectl apply --server-side`.
@diagram cmp
caption: Client-side versus server-side
cards:
  - {h: "Client-side apply", kind: warn, items: ["Merge happens in kubectl", "Uses last-applied annotation", "Silent overwrite of others"]}
  - {h: "Server-side apply", kind: ok, items: ["Merge in the API server", "Field ownership per manager", "Explicit conflicts"]}
@h Ownership in practice
```bash title="Two managers on one field" lab
kubectl create deployment demo --image=nginx:1.27 --dry-run=client -o yaml > demo.yaml
kubectl apply --server-side --field-manager=gitops -f demo.yaml
kubectl scale deploy demo --replicas=4            # a different manager now owns replicas
kubectl apply --server-side --field-manager=gitops -f demo.yaml
kubectl get deploy demo --show-managed-fields -o yaml | grep -E 'manager|f:replicas'
kubectl delete deploy demo
```
@check
Why use SSA with an HPA? || The HPA owns `spec.replicas`; if Git does not set it, SSA leaves the HPA value alone instead of resetting it on every sync.
@end
