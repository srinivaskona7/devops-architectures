---
title: ConfigMaps and Secrets
minutes: 45
objectives:
  - Inject configuration as environment variables and files and know the update behaviour of each
  - Explain what a Secret protects and what it does not
  - Bring secrets in from AWS and Vault with External Secrets or CSI
---
Configuration should live outside the image. Kubernetes gives two objects for it and several patterns for delivering it to a container.
 
@concept ConfigMaps
@plain
A ConfigMap stores non-secret configuration as key-value pairs or whole files.
@problem
Baking config into images forces a rebuild per environment and mixes code with settings.
@does
- Keys hold short values or full file contents. Size limit about 1 MiB.
- Consume as environment variables, command arguments, or files in a volume.
- `immutable: true` forbids edits, protects against accidental change and reduces API server load.
- Namespaced; a Pod can only use ConfigMaps from its own namespace.
@diagram flow
caption: Image plus config
nodes:
  - "Image|same everywhere|app"
  - "ConfigMap|per environment|info"
  - "Pod|env or files|ok"
@h ConfigMap and its use
```yaml title="configmap.yaml"
apiVersion: v1
kind: ConfigMap
metadata:
  name: web-config
data:
  LOG_LEVEL: info
  FEATURE_X: "true"
  app.properties: |
    cache.ttl=60
    pool.size=10
immutable: false
---
apiVersion: v1
kind: Pod
metadata:
  name: web
spec:
  containers:
    - name: app
      image: nginx:1.27
      envFrom:
        - configMapRef:
            name: web-config
      volumeMounts:
        - name: cfg
          mountPath: /etc/app
          readOnly: true
  volumes:
    - name: cfg
      configMap:
        name: web-config
        items:
          - {key: app.properties, path: app.properties}
```
@end

@concept How config updates reach a Pod
@plain
Environment variables are fixed at container start. Files from a ConfigMap volume are refreshed by the kubelet, but only when you do not use `subPath`.
@problem
Changing a ConfigMap and seeing nothing happen is a classic surprise.
@does
- Env vars: change requires a Pod restart.
- Volume mounts: updated eventually (kubelet sync period plus cache, typically up to a minute or so). The app must reread the file.
- `subPath` mounts never update.
- To force a rollout on change, put a hash of the config into a Pod template annotation (Helm `checksum/config`) or use a reloader controller.
@diagram cmp
caption: Update behaviour
cards:
  - {h: "Environment variable", kind: warn, items: ["Read at start", "Restart needed"]}
  - {h: "Volume file", kind: ok, items: ["Updated by kubelet", "App must reload"]}
  - {h: "subPath file", kind: bad, items: ["Never updated", "Avoid for changing config"]}
@h Roll on change
```bash title="Restart after config change" lab
kubectl create configmap web-config --from-literal=LOG_LEVEL=debug --dry-run=client -o yaml | kubectl apply -f -
kubectl rollout restart deployment/web
kubectl exec deploy/web -- env | grep LOG_LEVEL
```
@check
You changed a ConfigMap used via envFrom and nothing changed. Why? || Environment variables are read when the container starts; restart the Pods.
@end

@concept Secrets
@plain
A Secret holds sensitive values such as passwords, tokens and keys. It is used like a ConfigMap but with tighter handling.
@problem
Passwords in manifests or images leak through Git, registries and logs.
@does
- Values are base64 encoded, which is **encoding, not encryption**. Anyone with `get secret` permission reads them.
- Types: `Opaque`, `kubernetes.io/tls`, `kubernetes.io/dockerconfigjson`, `kubernetes.io/basic-auth`, `kubernetes.io/service-account-token`.
- Mounted Secrets are held in memory (tmpfs) on the node, not written to disk.
- Prefer file mounts over env vars: env values appear in crash dumps, `docker inspect` style tools and child processes.
@diagram layers
caption: Where a Secret lives
layers:
  - {label: "API", nodes: ["Secret object|base64 values|warn"]}
  - {label: "Storage", nodes: ["etcd|plain unless encrypted at rest|bad"]}
  - {label: "Node", nodes: ["tmpfs mount|in memory|ok"]}
@h Create and use
```bash title="Secret commands" lab
kubectl create secret generic db-secret --from-literal=password='S3cr3t!' -n shop
kubectl get secret db-secret -n shop -o jsonpath='{.data.password}' | base64 -d; echo
kubectl create secret tls shop-tls --cert=tls.crt --key=tls.key -n shop
kubectl create secret docker-registry regcred --docker-server=ghcr.io --docker-username=bot --docker-password="$TOKEN"
```
:::danger
Never commit a Secret manifest to Git, even base64 encoded. Use Sealed Secrets, SOPS or an external secret store.
:::
@end

@concept Protecting Secrets in the cluster
@plain
Secrets need encryption at rest in etcd, tight RBAC and audit.
@problem
Anyone who can read etcd or has broad `get secrets` rights can read every password in the cluster.
@does
- **Encryption at rest** through an `EncryptionConfiguration` on the API server, ideally with a KMS provider (AWS KMS, Google KMS). EKS supports envelope encryption with a KMS key; Gardener enables etcd encryption by default.
- Limit `get`, `list` and `watch` on Secrets. `list` also returns the values.
- Avoid wildcard Roles on `secrets`.
- Audit access and rotate on suspicion.
@diagram flow
caption: Envelope encryption
nodes:
  - "Secret write|API server|cp"
  - "DEK encrypts value|data key|info"
  - "KMS wraps DEK|key in HSM|ext"
  - "etcd|ciphertext|ok"
@h Check encryption is on
```bash title="EKS envelope encryption" lab
aws eks describe-cluster --name prod --query 'cluster.encryptionConfig'
kubectl auth can-i list secrets -A --as=system:serviceaccount:shop:web
```
@end

@concept External Secrets Operator
@plain
External Secrets Operator (ESO) reads secrets from a cloud store such as AWS Secrets Manager, Azure Key Vault or HashiCorp Vault and creates ordinary Kubernetes Secrets from them.
@problem
Real secrets belong in a managed store with rotation and audit, while apps still expect a Kubernetes Secret.
@does
- A `SecretStore` or `ClusterSecretStore` defines the connection and auth (IRSA or Pod Identity on EKS, no static keys).
- An `ExternalSecret` maps remote keys to the target Secret and a `refreshInterval`.
- Git holds only the references, never the values.
- Changes upstream propagate on the next refresh; pair with a reloader to restart Pods.
@diagram flow
caption: Sync from a vault
nodes:
  - "AWS Secrets Manager|source of truth|ext"
  - "ESO controller|IRSA identity|cp"
  - "K8s Secret|db-secret|info"
  - "Pod|mounts it|app"
@h ExternalSecret
```yaml title="externalsecret.yaml"
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: aws-sm
spec:
  provider:
    aws:
      service: SecretsManager
      region: eu-west-1
      auth:
        jwt:
          serviceAccountRef:
            name: eso
            namespace: external-secrets
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: db-secret
  namespace: shop
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-sm
    kind: ClusterSecretStore
  target:
    name: db-secret
  data:
    - secretKey: password
      remoteRef:
        key: prod/shop/db
        property: password
```
:::note
Use the API version your installed ESO release serves (`v1` in recent releases, `v1beta1` earlier). Check with `kubectl api-resources | grep external-secrets`.
:::
@check
Why is IRSA or Pod Identity better than an access key Secret for ESO? || The pod gets short-lived credentials tied to a role, so no long-lived key is stored in the cluster.
@end

@concept Secrets Store CSI driver, Sealed Secrets and SOPS
@plain
Three other patterns: mount secrets straight from a store as files, encrypt secrets so they can live in Git, or decrypt them in the pipeline.
@problem
Teams doing GitOps want secrets versioned like other config, or want secrets never stored as Kubernetes Secrets at all.
@does
- **Secrets Store CSI driver** mounts values from a provider (AWS, Vault, Azure) as a volume at Pod start. It can also sync to a Kubernetes Secret.
- **Sealed Secrets** encrypts with a cluster public key into a `SealedSecret` that only the in-cluster controller decrypts. Safe in Git, bound to the cluster and namespace.
- **SOPS** (with age or KMS) encrypts values in YAML files; Flux and Argo CD plug-ins decrypt at apply time.
- **Vault Agent / injector** or Vault Secrets Operator for dynamic credentials with leases.
@diagram cmp
caption: Pick by workflow
cards:
  - {h: "ESO", kind: ok, items: ["Store is source of truth", "Creates K8s Secrets"]}
  - {h: "CSI driver", kind: info, items: ["Files at mount time", "Optional no Secret object"]}
  - {h: "Sealed Secrets / SOPS", kind: app, items: ["Encrypted in Git", "GitOps friendly"]}
@h Secrets Store CSI volume
```yaml title="secretproviderclass.yaml"
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: aws-db
  namespace: shop
spec:
  provider: aws
  parameters:
    objects: |
      - objectName: "prod/shop/db"
        objectType: "secretsmanager"
---
apiVersion: v1
kind: Pod
metadata:
  name: api
  namespace: shop
spec:
  serviceAccountName: api
  containers:
    - name: app
      image: ghcr.io/example/api:1.4.2
      volumeMounts:
        - {name: secrets, mountPath: /mnt/secrets, readOnly: true}
  volumes:
    - name: secrets
      csi:
        driver: secrets-store.csi.k8s.io
        readOnly: true
        volumeAttributes:
          secretProviderClass: aws-db
```
@end
