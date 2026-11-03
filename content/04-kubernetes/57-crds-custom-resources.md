---
title: CRDs and custom resources
minutes: 45
objectives:
  - Explain how a CustomResourceDefinition extends the Kubernetes API
  - Write a CRD with a validated schema, printer columns and a status subresource
  - Version, validate and safely upgrade CRDs
---
Kubernetes is an API platform. Everything from Pods to cert-manager Certificates is an object in the same API server. **CustomResourceDefinitions** let you add your own object types and use them with kubectl, RBAC and GitOps like built-in ones.

@concept What a CRD is
@plain
A **CustomResourceDefinition (CRD)** teaches the API server a new object type. After you apply it, you can create, read and watch objects of that kind. A CRD stores data only; behaviour comes from a controller.
@problem
You want to describe higher level things (a database, a certificate, a tenant) in YAML and manage them with the same tools as everything else, instead of a separate system with its own API and access control.
@does
- The CRD defines group, kind, scope (Namespaced or Cluster), versions and a schema. The API server then serves REST endpoints for it, with storage in etcd, RBAC, watch and audit for free.
- The objects are called **custom resources (CRs)**. Delete the CRD and **all its CRs are deleted**.
- Names: `plural.group`, for example `databases.data.example.com`.
- `kubectl api-resources` and `kubectl explain` work on CRDs.
@diagram flow
caption: A new API type appears
numbered: true
nodes:
  - "Apply CRD|defines kind Database|cp"
  - "API server|serves new REST path|cp"
  - "Create a Database object|stored in etcd|db"
  - "Controller watches|makes it real|app"
@h Looking at CRDs
```bash title="Explore CRDs on a cluster" lab
kubectl get crd | head -20
kubectl get crd certificates.cert-manager.io -o jsonpath='{.spec.versions[*].name}{"\n"}'
kubectl api-resources --api-group=cert-manager.io
kubectl explain certificate.spec.issuerRef
kubectl get crd | wc -l                          # Kyma and Istio add dozens
```
@end

@concept Writing a CRD
@plain
A CRD names the type, lists versions, and gives an OpenAPI v3 schema describing allowed fields.
@problem
Without a schema anyone could store any shape of data in your resource, and typos like `replcias` would be silently accepted.
@does
- `spec.versions[].schema.openAPIV3Schema` defines types, `required` fields, enums, minimum and maximum, and defaults.
- Exactly one version has `storage: true`.
- `additionalPrinterColumns` choose what `kubectl get` shows, such as phase and age.
- `subresources.status` enables a separate `/status` endpoint so controllers update status without touching spec; `scale` lets `kubectl scale` and HPA work.
- Structural schemas are required: every field needs a type; use `x-kubernetes-preserve-unknown-fields` sparingly.
@diagram layers
caption: Pieces of a CRD
layers:
  - {label: "Identity", nodes: ["group and names|data.example.com, Database|info", "scope|Namespaced|info"]}
  - {label: "Version", nodes: ["schema|OpenAPI v3, defaults, enums|warn", "printer columns|kubectl get output|plain"]}
  - {label: "Subresources", nodes: ["status|separate endpoint|ok", "scale|HPA and kubectl scale|ok"]}
@h A Database CRD
```yaml title="database-crd.yaml"
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: databases.data.example.com
spec:
  group: data.example.com
  scope: Namespaced
  names:
    kind: Database
    listKind: DatabaseList
    plural: databases
    singular: database
    shortNames: ["db"]
  versions:
    - name: v1
      served: true
      storage: true
      subresources:
        status: {}
      additionalPrinterColumns:
        - name: Engine
          type: string
          jsonPath: .spec.engine
        - name: Phase
          type: string
          jsonPath: .status.phase
        - name: Age
          type: date
          jsonPath: .metadata.creationTimestamp
      schema:
        openAPIV3Schema:
          type: object
          required: ["spec"]
          properties:
            spec:
              type: object
              required: ["engine", "storageGB"]
              properties:
                engine:
                  type: string
                  enum: ["postgres", "mysql"]
                version:
                  type: string
                  default: "16"
                storageGB:
                  type: integer
                  minimum: 1
                  maximum: 1000
            status:
              type: object
              properties:
                phase:
                  type: string
                observedGeneration:
                  type: integer
                  format: int64
```
@end

@concept Custom resources in use
@plain
Once the CRD exists, you create objects of the new kind like any other manifest and manage them with the usual commands.
@problem
Users need a simple, declarative interface. They should say what they want, not how it is built.
@does
- `kubectl apply -f database.yaml` creates the CR; validation runs at admission and errors come back immediately.
- `kubectl get db`, `describe`, `edit`, `delete` all work. `kubectl get db -o yaml` shows both spec and status.
- RBAC applies per resource and verb on the group, for example `databases` in `data.example.com`.
- Because they are API objects, they work with Helm, Kustomize and GitOps without special handling.
@diagram flow
caption: A declarative request becomes real
nodes:
  - "Developer|writes 6 lines of YAML|ext"
  - "Database object|spec says what|info"
  - "Controller|creates StatefulSet, PVC, Secret|app"
  - "status.phase Ready|shown in kubectl get|ok"
@h Example
```yaml title="orders-db.yaml"
apiVersion: data.example.com/v1
kind: Database
metadata:
  name: orders
  namespace: shop
spec:
  engine: postgres
  version: "16"
  storageGB: 50
```
```bash title="Use it" lab
kubectl apply -f database-crd.yaml
kubectl wait --for=condition=Established crd/databases.data.example.com --timeout=30s
kubectl apply -f orders-db.yaml
kubectl get db -n shop
kubectl apply -f - <<'YAML'
apiVersion: data.example.com/v1
kind: Database
metadata:
  name: bad
  namespace: shop
spec:
  engine: oracle
  storageGB: 0
YAML
```
@check
What happens to existing custom resources if you delete their CRD? || They are all deleted, because the API no longer knows the type.
@end

@concept Validation rules with CEL
@plain
Beyond schema types, CRDs can carry **CEL** (Common Expression Language) rules that check relations between fields, evaluated by the API server.
@problem
Some constraints are not expressible with types: "storage may only grow", "if replicas > 1 then highAvailability must be true". Putting these in a webhook adds an extra service to run.
@does
- `x-kubernetes-validations` holds rules with `rule` (the expression) and `message`.
- `self` is the object at that schema level; `oldSelf` enables **transition rules** that compare to the previous value on update.
- Rules run inside the API server, so no network call, no webhook availability risk, and they are cost-limited to prevent abuse.
- GA since 1.29.
@diagram flow
caption: Validation layers in order
nodes:
  - "OpenAPI schema|types, enum, ranges|info"
  - "CEL rules|cross field and transitions|warn"
  - "Validating webhook|anything else|cp"
  - "Stored in etcd|accepted|ok"
@h Rules inside the schema
```yaml title="cel-fragment.yaml"
spec:
  type: object
  properties:
    storageGB:
      type: integer
      x-kubernetes-validations:
        - rule: "self >= oldSelf"
          message: "storage can only grow"
    replicas:
      type: integer
    highAvailability:
      type: boolean
  x-kubernetes-validations:
    - rule: "self.replicas == 1 || self.highAvailability"
      message: "highAvailability must be true when replicas is above 1"
```
@end

@concept Versions and conversion
@plain
A CRD can serve several versions (v1alpha1, v1beta1, v1) of the same type. The API converts between them, while only one version is stored in etcd.
@problem
APIs evolve. You must change field names or structure without breaking existing users or stored objects.
@does
- `served: true` makes a version available; `storage: true` marks the stored one; `deprecated: true` adds a warning header.
- Conversion strategy `None` only changes `apiVersion`, which is fine if schemas are identical. `Webhook` calls a conversion webhook for real structural changes.
- To retire an old version: migrate stored objects (storage version migration), set `served: false`, then remove it from `status.storedVersions` after migrating.
- Follow Kubernetes naming: alpha may break, beta is mostly stable, v1 is a commitment.
@diagram flow
caption: Migrating storage versions
numbered: true
nodes:
  - "Serve v1beta1 and v1|both available|info"
  - "Switch storage to v1|new writes use v1|app"
  - "Rewrite old objects|storage migration|warn"
  - "Stop serving v1beta1|remove from storedVersions|ok"
@h Commands
```bash title="Which versions are stored" lab
kubectl get crd databases.data.example.com -o jsonpath='{.status.storedVersions}{"\n"}'
kubectl get crd databases.data.example.com -o jsonpath='{range .spec.versions[*]}{.name}{" served="}{.served}{" storage="}{.storage}{"\n"}{end}'
kubectl get databases.v1.data.example.com -A       # request a specific version explicitly
```
@end

@concept Installing and upgrading CRDs safely
@plain
CRDs are cluster-wide and shared by everyone. Their lifecycle needs more care than ordinary workload manifests.
@problem
Helm does not upgrade or delete CRDs in a chart's `crds/` folder. A CRD upgrade applied late or never leads to controllers expecting fields the API drops.
@does
- Install CRDs **before** the CRs and controllers. In GitOps, use sync waves or a separate Kustomization that other layers depend on.
- Use **server-side apply** (`kubectl apply --server-side`) for big CRDs; client-side apply fails because the last-applied annotation exceeds 262144 bytes.
- Many projects ship CRDs as a separate chart or a manifest file; follow their upgrade notes for each release.
- Never delete a CRD to "refresh" it; that deletes all data of that type.
- Back up custom resources (Velero) before CRD changes.
@diagram flow
caption: Safe order of operations
numbered: true
nodes:
  - "Upgrade CRDs|server-side apply|cp"
  - "Upgrade controller|new version|app"
  - "Apply new CR fields|after controller is ready|info"
  - "Verify|status and events|ok"
@h Commands
```bash title="Apply big CRDs" lab
kubectl apply --server-side --force-conflicts -f https://github.com/cert-manager/cert-manager/releases/download/v1.16.2/cert-manager.crds.yaml
kubectl get crd -o custom-columns=NAME:.metadata.name,CREATED:.metadata.creationTimestamp | sort -k2 | tail -5
kubectl get crd -l app.kubernetes.io/instance=cert-manager
```
:::warn
Deleting a CRD cascades to every custom resource of that type, including ones created by other teams. Treat `kubectl delete crd` like dropping a database table.
:::
@end
