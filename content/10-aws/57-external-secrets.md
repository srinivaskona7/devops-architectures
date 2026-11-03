---
title: External Secrets with AWS Secrets Manager
minutes: 45
objectives:
  - Sync secrets from AWS Secrets Manager and Parameter Store into Kubernetes
  - Configure a SecretStore with Pod Identity or IRSA and scoped IAM
  - Handle rotation, refresh intervals and templating safely
---
Kubernetes Secrets are base64, not encryption, and putting values in Git is risky. The External Secrets Operator (ESO) keeps the source of truth in AWS and copies values into the cluster when needed.
@concept The problem with Kubernetes Secrets
@plain
A Secret object is stored in etcd, readable by anyone with `get secret` rights in the namespace, and often committed to Git in some encoded form.
@problem
Rotating a database password means editing manifests and redeploying. Auditing who read what is hard.
@does
- EKS encrypts etcd at rest, and you can add envelope encryption with your own KMS key to Secrets.
- RBAC must restrict `get/list` on secrets; avoid cluster-wide read.
- Better pattern: store in Secrets Manager (versioned, audited, rotated) and sync into the cluster, or mount via the Secrets Store CSI driver.
- Never print secrets in logs or CI output.
@diagram flow
caption: Source of truth outside the cluster
nodes:
  - "Secrets Manager|versioned, rotated|ext"
  - "External Secrets Operator|syncs|cp"
  - "Kubernetes Secret|created and updated|env"
  - "Pod|env or volume|app"
@h Enable envelope encryption
```bash title="Encrypt Kubernetes secrets with a KMS key" nocheck
aws eks associate-encryption-config --cluster-name shop-prod \
  --encryption-config '[{"resources":["secrets"],"provider":{"keyArn":"arn:aws:kms:us-east-1:111122223333:key/11111111-2222-3333-4444-555555555555"}}]'
```
@check
Is base64 encryption? || No; it is an encoding anyone can reverse.
@end

@concept ESO architecture
@plain
ESO adds custom resources: a `SecretStore` (or cluster-wide `ClusterSecretStore`) says how to reach the provider, and an `ExternalSecret` says which remote keys to pull and what Secret to create.
@problem
Applications want an ordinary Kubernetes Secret or environment variable without knowing about AWS.
@does
- The operator reconciles every `refreshInterval` and updates the target Secret when the remote value changes.
- Targets can be templated to build config files or connection strings.
- `creationPolicy`, `deletionPolicy` decide ownership and cleanup.
- Providers: AWS Secrets Manager, Parameter Store, and many others (Vault, GCP, Azure).
@diagram layers
caption: Resources
layers:
  - {label: "Config", nodes: ["ClusterSecretStore|provider and auth|cp", "ExternalSecret|which keys, which target|app"]}
  - {label: "Operator", nodes: ["External Secrets Operator|reconciles|info"]}
  - {label: "Result", nodes: ["Secret|data from AWS|ok"]}
@h Install
```bash title="Helm install" nocheck
helm repo add external-secrets https://charts.external-secrets.io
helm upgrade --install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace --set installCRDs=true
kubectl -n external-secrets get pods
```
@check
What is the difference between SecretStore and ExternalSecret? || The store defines how to authenticate to the provider; the ExternalSecret defines which values to fetch and the Secret to create.
@end

@concept IAM and ClusterSecretStore
@plain
ESO's service account assumes an IAM role that can read only the secrets it should. The store references that service account.
@problem
Operators with `secretsmanager:*` on everything can read every secret in the account.
@does
- Allow `secretsmanager:GetSecretValue` and `DescribeSecret` on specific ARNs or a name prefix such as `shop/*`.
- Add `kms:Decrypt` if secrets use a customer managed key.
- For Parameter Store allow `ssm:GetParameter` on `/shop/*`.
- Use separate roles per team when multi-tenant, with namespaced `SecretStore` objects.
@diagram flow
caption: Auth path
nodes:
  - "ESO service account|external-secrets|app"
  - "IAM role|read shop/* secrets|warn"
  - "Secrets Manager|GetSecretValue|ext"
@h Policy and store
```json title="ESO read policy"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      "Resource": "arn:aws:secretsmanager:us-east-1:111122223333:secret:shop/*"
    },
    {
      "Effect": "Allow",
      "Action": "kms:Decrypt",
      "Resource": "arn:aws:kms:us-east-1:111122223333:key/11111111-2222-3333-4444-555555555555"
    }
  ]
}
```
```yaml title="ClusterSecretStore using a service account (IRSA)"
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: aws-secrets
spec:
  provider:
    aws:
      service: SecretsManager
      region: us-east-1
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
```
:::note
With Pod Identity, omit the `auth` block so ESO uses the default AWS credential chain; confirm support in your ESO version.
:::
@check
Why scope the policy to a prefix? || A compromised operator then reads only the intended secrets, not the whole account.
@end

@concept ExternalSecret resources
@plain
An `ExternalSecret` names remote keys and the Kubernetes Secret to produce.
@problem
You need specific properties (like `username` and `password` from one JSON secret) mapped into specific keys.
@does
- `data` maps single keys: `remoteRef.key` and optional `property` for JSON fields.
- `dataFrom` with `extract` imports all keys of a JSON secret.
- `target.template` can compose strings, such as a full connection URL.
- Pods consume the Secret with `envFrom` or a volume. Volume mounts update on refresh; environment variables need a pod restart (use Reloader or a rollout trigger).
@diagram flow
caption: JSON secret to Kubernetes keys
nodes:
  - "shop/db secret|username, password|ext"
  - "ExternalSecret|maps properties|app"
  - "Secret db-credentials|DB_USER, DB_PASS|env"
  - "Deployment|envFrom|ok"
@h Example
```yaml title="Map a Secrets Manager secret to a Secret"
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: db-credentials
  namespace: shop
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets
  target:
    name: db-credentials
    creationPolicy: Owner
    template:
      data:
        DATABASE_URL: "postgres://{{ .username }}:{{ .password }}@shop-db.example.internal:5432/shop"
  dataFrom:
    - extract:
        key: shop/db
```
```bash title="Create the source secret" nocheck
aws secretsmanager create-secret --name shop/db \
  --secret-string '{"username":"shop","password":"CHANGE_ME"}'
kubectl -n shop get externalsecret db-credentials
```
@check
Why do environment variables not follow secret rotation automatically? || Environment values are set at container start; only mounted files update in place.
@end

@concept Rotation and reload
@plain
Secrets Manager can rotate credentials automatically with a Lambda. ESO then copies the new value, and applications must pick it up.
@problem
Rotation is useless if pods keep using the old password until the next deploy, or if the rotation window causes connection failures.
@does
- Secrets Manager rotation for RDS uses either single user or alternating users strategy; alternating users avoids downtime.
- Set ESO `refreshInterval` shorter than your rotation tolerance (for example 5 to 15 minutes) and watch API cost per request.
- Use **Stakater Reloader** or annotation-based rollouts to restart pods on Secret change.
- Applications that read secret files on each connection or support credential refresh avoid restarts.
@diagram seq
caption: A rotation cycle
actors: ["Secrets Manager|rotates|ext", "ESO|refresh|cp", "Secret|k8s object|env", "Reloader|restarts pods|app"]
steps:
  - "0>0: new password version | resp"
  - "1>0: read AWSCURRENT | req"
  - "1>2: update Secret | tls"
  - "3>2: sees change | req"
  - "3>3: rollout restart | resp"
@h Enable rotation
```bash title="Rotation with the RDS managed master secret" nocheck
aws secretsmanager rotate-secret --secret-id shop/db \
  --rotation-lambda-arn arn:aws:lambda:us-east-1:111122223333:function:SecretsManagerRDSRotation \
  --rotation-rules AutomaticallyAfterDays=30
```
```yaml title="Reloader annotation on a Deployment"
metadata:
  annotations:
    reloader.stakater.com/auto: "true"
```
@check
What triggers a pod restart after a Secret changes? || A tool such as Reloader that watches Secrets and performs a rollout.
@end

@concept Alternatives and trade-offs
@plain
ESO is one option. The AWS Secrets and Configuration Provider (ASCP) with the Secrets Store CSI driver mounts secrets directly into pods without creating a Kubernetes Secret.
@problem
Teams must choose between convenience and exposure.
@does
- **ESO**: creates Kubernetes Secrets, works with env vars, many providers; the value exists in etcd.
- **CSI driver + ASCP**: mounts files from Secrets Manager or Parameter Store; optional sync to Secrets; the pod's own identity fetches, so per-pod scoping is natural.
- **Sealed Secrets or SOPS**: encrypted values committed to Git; good for GitOps but rotation is manual.
- Use one approach per platform, document it, and ban plaintext secrets in manifests and CI variables.
@diagram cmp
caption: Options
cards:
  - {h: "External Secrets Operator", kind: app, items: ["Sync to Secret objects", "Provider neutral"]}
  - {h: "CSI driver and ASCP", kind: ok, items: ["Files in the pod", "Per pod IAM scope"]}
  - {h: "SOPS or Sealed Secrets", kind: info, items: ["Encrypted in Git", "Manual rotation"]}
@choose Which approach
ESO | many apps need ordinary Secrets and env vars | secrets must never exist in etcd
CSI driver and ASCP | secrets should never be Kubernetes objects | you need env vars and cannot restart on change
SOPS | GitOps with a small number of static secrets | you need automatic rotation
@end
