---
title: Objects, namespaces and extending the API
minutes: 45
objectives:
  - Write correct labels, selectors and ownership relations
  - Use namespaces, contexts and finalizers correctly
  - Explain how CRDs extend the API and how rate limiting protects it
---
Everything in Kubernetes is an object with the same envelope. Once you read that envelope fluently, any resource, built in or custom, is easy to follow.

@concept The anatomy of an object
@plain
Every object has `apiVersion`, `kind`, `metadata`, usually a `spec` (what you want) and a `status` (what the controllers observed).
@problem
A uniform shape lets one tool (kubectl, Argo CD, Kyverno) work with thousands of resource types.
@does
- `metadata` holds `name`, `namespace`, `labels`, `annotations`, `uid`, `ownerReferences` and `finalizers`.
- You write `spec`; controllers write `status`. Status is a separate subresource, so editing it needs different RBAC.
- Names are unique per kind per namespace; the `uid` is unique forever.
@diagram layers
caption: The object envelope
layers:
  - {label: "Type", nodes: ["apiVersion|group and version|info", "kind|resource type|info"]}
  - {label: "Identity", nodes: ["metadata|name, labels, owners|env"]}
  - {label: "Desired", nodes: ["spec|written by you|app"]}
  - {label: "Observed", nodes: ["status|written by controllers|ok"]}
@h A complete small object
```yaml title="namespace.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    team: payments
    pod-security.kubernetes.io/enforce: baseline
  annotations:
    owner-email: payments@example.com
```
@end

@concept Labels, selectors and annotations
@plain
Labels are key-value tags used to group objects. Selectors pick objects by those tags. Annotations are free-form metadata that nothing selects on.
@problem
Objects need loose coupling. A Service should find its Pods by what they are, not by fixed names that change on every rollout.
@does
- Services, ReplicaSets, NetworkPolicies and PDBs all select by label.
- Equality selectors: `app=web`; set based: `env in (prod,stage)`; presence: `!canary`.
- Recommended labels: `app.kubernetes.io/name`, `instance`, `version`, `component`, `part-of`, `managed-by`.
- A Deployment's `spec.selector` is immutable. A wrong selector overlap between two Deployments causes them to fight over Pods.
@diagram flow
caption: A Service finding Pods
nodes:
  - "Service|selector app=web|app"
  - "Pod web-1|app=web|ok"
  - "Pod web-2|app=web|ok"
  - "Pod db-0|app=db, not selected|plain"
@h Selecting from the CLI
```bash title="Label queries" lab
kubectl get pods -l 'app=web,env in (prod,stage)' --show-labels
kubectl label pod web-1 canary=true
kubectl label pod web-1 canary-
kubectl get pods -L app,version
kubectl annotate deploy web kubernetes.io/change-cause="bump to 1.27"
```
@end

@concept Namespaces
@plain
Namespaces split one cluster into virtual sub-clusters for names, permissions and quotas.
@problem
Teams and environments sharing a cluster would collide on names and could touch each other's objects.
@does
- Namespaced objects: Pods, Services, Deployments, Secrets, Roles. Cluster-scoped: Nodes, PersistentVolumes, StorageClasses, Namespaces, CRDs, ClusterRoles.
- RBAC, ResourceQuota, LimitRange, NetworkPolicy and Pod Security labels attach at namespace level.
- Namespaces are **not** a network or hard security boundary by default. Add NetworkPolicy and quotas.
- Deleting a namespace deletes everything inside it.
- Default namespaces: `default`, `kube-system`, `kube-public`, `kube-node-lease`. On Kyma, `kyma-system` and `istio-system` hold platform parts.
@diagram cmp
caption: Namespace scope
cards:
  - {h: "Namespaced", kind: app, items: ["Pod, Deployment, Service", "ConfigMap, Secret", "Role, RoleBinding"]}
  - {h: "Cluster scoped", kind: cp, items: ["Node, PersistentVolume", "StorageClass, CRD", "ClusterRole, Namespace"]}
@h Working with namespaces
```bash title="Namespaces and contexts" lab
kubectl api-resources --namespaced=false | head -15
kubectl create namespace shop
kubectl config set-context --current --namespace=shop
kubectl config get-contexts
kubectl get all -n shop
```
:::tip
A wrong default namespace in your context is a classic cause of "it works for them". Show it in your shell prompt or use kubectx and kubens.
:::
@end

@concept Owners, garbage collection and finalizers
@plain
`ownerReferences` link a child to its parent. When the parent goes, the garbage collector removes children. **Finalizers** hold deletion until cleanup is done.
@problem
Deleting a Deployment should remove its ReplicaSets and Pods, and deleting a PVC-bound resource should release external disks first.
@does
- Deployment owns ReplicaSets, which own Pods. Deleting the Deployment cascades.
- Delete modes: `background` (default), `foreground` (children first), `orphan` (children kept).
- A finalizer in `metadata.finalizers` keeps the object in `Terminating` until its controller removes it. A stuck finalizer is the usual reason a namespace hangs in Terminating.
@diagram flow
caption: Delete with a finalizer
numbered: true
nodes:
  - "kubectl delete|deletionTimestamp set|info"
  - "Terminating|object still exists|warn"
  - "Controller cleanup|external resource removed|app"
  - "Finalizer removed|controller patches|ok"
  - "Object gone|garbage collected|plain"
@h Inspect and unstick
```bash title="Owners and finalizers" lab
kubectl get pod web-abc -o jsonpath='{.metadata.ownerReferences[0].kind}/{.metadata.ownerReferences[0].name}{"\n"}'
kubectl delete deploy web --cascade=orphan      # keep the Pods
kubectl get ns stuck -o jsonpath='{.spec.finalizers}{"\n"}'
kubectl get all,pvc -n stuck                    # find what still blocks deletion
```
:::danger
Removing a finalizer by hand skips the cleanup it guarded and can leak cloud load balancers or disks. Find and fix the controller first.
:::
@check
What does `--cascade=orphan` do? || Deletes the parent but leaves the children running without an owner.
@end

@concept Custom resources and operators
@plain
A **CustomResourceDefinition** (CRD) adds a new kind to the API. A controller for it, often called an operator, reconciles it like any built-in.
@problem
Built-in kinds cannot model everything, such as a database cluster, a certificate or an Istio route. CRDs add domain objects without forking Kubernetes.
@does
- The CRD declares group, kind, scope, versions and an OpenAPI schema; the API server then validates and stores instances.
- Features: `status` subresource, printer columns, CEL validation rules, conversion webhooks between versions.
- Kyma itself is built from CRDs such as `Kyma`, `APIRule`, `Function` and module resources.
- Cert-manager, Gateway API, Argo CD, Karpenter and KEDA are all CRD driven.
@diagram flow
caption: A custom kind from definition to behaviour
nodes:
  - "CRD|defines kind Backup|cp"
  - "Backup object|written by users|app"
  - "Operator|watches Backup|info"
  - "Real work|jobs, snapshots, cloud calls|ok"
@h A small CRD and instance
```yaml title="crd.yaml"
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: backups.ops.example.com
spec:
  group: ops.example.com
  scope: Namespaced
  names:
    plural: backups
    singular: backup
    kind: Backup
  versions:
    - name: v1
      served: true
      storage: true
      subresources:
        status: {}
      schema:
        openAPIV3Schema:
          type: object
          properties:
            spec:
              type: object
              required: [schedule]
              properties:
                schedule:
                  type: string
                retentionDays:
                  type: integer
                  minimum: 1
            status:
              type: object
              x-kubernetes-preserve-unknown-fields: true
---
apiVersion: ops.example.com/v1
kind: Backup
metadata:
  name: nightly
spec:
  schedule: "0 2 * * *"
  retentionDays: 14
```
@check
Does a CRD alone do anything? || No. It only stores validated data. Behaviour needs a controller that watches the resource.
@end

@concept API Priority and Fairness, events and audit
@plain
The API server protects itself from overload by queueing requests per client class, records Events about object changes, and can write an audit log of every request.
@problem
One runaway controller listing all Pods in a loop could starve kubectl and the scheduler.
@does
- **APF** classifies requests into priority levels and flow-queues them; excess requests get HTTP 429 and clients should back off.
- **Events** are short lived objects (about one hour) explaining what happened: Scheduled, Pulled, BackOff, FailedMount.
- **Audit policy** records who did what at levels None, Metadata, Request, RequestResponse. Managed offerings expose audit logs through their own services.
@diagram layers
caption: Operational visibility on the API
layers:
  - {label: "Protect", nodes: ["API Priority and Fairness|queues and 429|warn"]}
  - {label: "Explain", nodes: ["Events|why a Pod is stuck|info"]}
  - {label: "Record", nodes: ["Audit log|who changed what|ok"]}
@h Reading events and throttling
```bash title="Events first" lab
kubectl get events -A --sort-by=.lastTimestamp | tail -20
kubectl events --for pod/web-0 --watch
kubectl get flowschemas,prioritylevelconfigurations
kubectl get --raw /metrics | grep apiserver_flowcontrol_rejected_requests_total | head
```
@end
