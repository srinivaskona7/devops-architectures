---
title: Artifact Registry, Secret Manager and Cloud KMS
minutes: 50
objectives:
  - Store and scan container images and packages in Artifact Registry with cleanup policies
  - Keep secrets in Secret Manager and deliver them to workloads without long-lived keys
  - Use Cloud KMS keys and customer-managed encryption keys with rotation
---
Images, secrets and keys are the three artifacts every pipeline touches. Google Cloud keeps them in separate services with IAM at each level.

@concept Artifact Registry repositories
@plain
**Artifact Registry** stores container images and language packages (Maven, npm, Python, Apt, Yum, Go, generic). Each repository has a format and a location.
@problem
You need a private, regional, access-controlled home for build artifacts close to the clusters that pull them.
@does
- Image path: `LOCATION-docker.pkg.dev/PROJECT/REPO/IMAGE:TAG`.
- Repository modes: standard, **remote** (pull-through cache for Docker Hub and others) and **virtual** (one URL over several repositories).
- Access by IAM roles `roles/artifactregistry.reader` and `writer` at project or repository level. GKE nodes need the reader role on the node service account.
- Container Registry (gcr.io) is shut down; use Artifact Registry.
- **AWS equivalent**: ECR plus CodeArtifact. Main difference: one service handles images and packages, with remote and virtual repositories.
@diagram flow
caption: Build to deploy
nodes:
  - "Build|Cloud Build or CI|app"
  - "Artifact Registry|europe-west1|db"
  - "GKE node|pulls image|vm"
  - "Pod|runs|ok"
@h Create and push
```bash title="Repository" lab
gcloud artifacts repositories create shop --repository-format=docker --location=europe-west1 \
  --description="Shop images" --immutable-tags
gcloud auth configure-docker europe-west1-docker.pkg.dev
docker build -t europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:1.0.0 .
docker push europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:1.0.0
```
@check
What does a remote repository do? || It caches images from an upstream registry such as Docker Hub.
@end

@concept Cleanup policies and vulnerability scanning
@plain
**Cleanup policies** delete old versions automatically. **Artifact Analysis** scans images for known vulnerabilities and stores metadata.
@problem
Registries grow without bound, and vulnerable images reach production unnoticed.
@does
- A cleanup policy file lists rules with `action: DELETE` or `KEEP`, conditions on tag prefix, age and version counts. Use `--dry-run` first.
- Enable the Container Scanning API for automatic scanning on push; results show severity and fixes. Continuous analysis re-scans as new CVEs appear.
- Combine with Binary Authorization to block images with critical findings, by attesting in the pipeline.
- **AWS equivalent**: ECR lifecycle policies and ECR scanning. Main difference: scanning results are available through the Artifact Analysis API for use in policy.
@diagram flow
caption: Registry hygiene
nodes:
  - "Push|image arrives|app"
  - "Scan|Artifact Analysis|info"
  - "Policy|attest or block|cp"
  - "Cleanup|delete old versions|warn"
@h Cleanup policy
```json title="cleanup.json"
[
  {
    "name": "delete-untagged-after-7d",
    "action": {"type": "Delete"},
    "condition": {"tagState": "untagged", "olderThan": "604800s"}
  },
  {
    "name": "keep-last-10-release",
    "action": {"type": "Keep"},
    "mostRecentVersions": {"keepCount": 10}
  }
]
```
```bash title="Apply with dry run first" lab
gcloud artifacts repositories set-cleanup-policies shop --location=europe-west1 --policy=cleanup.json --dry-run
gcloud artifacts docker images list europe-west1-docker.pkg.dev/shop-dev-123456/shop --include-tags
```
@end

@concept Secret Manager
@plain
**Secret Manager** stores secrets as versioned payloads with IAM access control and audit logging.
@problem
Secrets in environment files, images and Git leak and cannot be rotated safely.
@does
- A **secret** has **versions**. Applications read `latest` or a pinned version. Disable and destroy old versions.
- Regional or automatic replication; choose user-managed replication for residency.
- Grant `roles/secretmanager.secretAccessor` to the workload identity, per secret.
- Rotation: set a rotation period and a Pub/Sub topic; your function creates the new version.
- **AWS equivalent**: Secrets Manager. Main difference: secrets are versioned blobs without built-in rotation Lambdas; rotation is event driven.
@diagram flow
caption: Reading a secret
nodes:
  - "Workload|service account|app"
  - "IAM check|secretAccessor|cp"
  - "Secret Manager|version latest|db"
  - "Audit log|access recorded|info"
@h Create and read
```bash title="Secrets" lab
printf 'S3cr3t-pass' | gcloud secrets create shop-db-password --data-file=- --replication-policy=automatic
gcloud secrets add-iam-policy-binding shop-db-password \
  --member="serviceAccount:shop-api@shop-dev-123456.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
gcloud secrets versions access latest --secret=shop-db-password
```
:::danger
Never print secrets to CI logs. Avoid passing them on command lines in shared hosts.
:::
@check
Which role reads secret payloads? || roles/secretmanager.secretAccessor.
@end

@concept Secrets in GKE Pods
@plain
Pods can receive Secret Manager values through the **Secret Manager add-on for GKE** (CSI driver), the External Secrets Operator, or the application's own client library.
@problem
Kubernetes Secrets are only base64 encoded and stored in etcd, and copying secrets by hand does not scale.
@does
- Secret Manager add-on: enable on the cluster, then use a `SecretProviderClass` with provider `gke` and mount the secret as a file in the Pod. Access uses Workload Identity Federation for GKE.
- External Secrets Operator: syncs a Secret Manager secret into a Kubernetes Secret; useful when apps need env vars.
- Application-layer encryption of Secrets at rest with a Cloud KMS key is an option (database encryption).
- **AWS equivalent**: Secrets Store CSI driver with ASCP, or External Secrets. Main difference: the add-on is managed and maintained by Google.
@diagram flow
caption: CSI mount
nodes:
  - "SecretProviderClass|references secret|info"
  - "CSI driver|fetch with KSA identity|cp"
  - "Secret Manager|payload|db"
  - "Pod volume|file /secrets/db|app"
@h SecretProviderClass
```yaml title="spc.yaml"
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: shop-secrets
  namespace: shop
spec:
  provider: gke
  parameters:
    secrets: |
      - resourceName: "projects/shop-dev-123456/secrets/shop-db-password/versions/latest"
        path: "db-password"
```
```bash title="Enable add-on" lab
gcloud container clusters update shop-std --region=europe-west1 --enable-secret-manager
```
@end

@concept Cloud KMS keys and rotation
@plain
**Cloud KMS** creates and manages cryptographic keys inside **key rings** at a location. Keys hold versions; the key material never leaves the service unless you choose to export under policy.
@problem
You need to encrypt, sign and control keys with separation of duty and audit.
@does
- Hierarchy: project, location, key ring (cannot be deleted), crypto key, key version.
- Purposes: symmetric encrypt/decrypt, asymmetric sign/decrypt, MAC. Protection levels: software, HSM (Cloud HSM), external (Cloud EKM).
- Automatic rotation with `--rotation-period` creates new primary versions; old ones remain for decryption.
- Roles: `cryptoKeyEncrypterDecrypter` for use, `cloudkms.admin` for management; keep these separate.
- **AWS equivalent**: AWS KMS and CloudHSM. Main difference: key rings group keys for IAM and cannot be removed.
@diagram layers
caption: KMS hierarchy
layers:
  - {label: "Location", nodes: ["europe-west1|key ring home|info"]}
  - {label: "Key ring", nodes: ["shop-ring|cannot be deleted|cp"]}
  - {label: "Keys", nodes: ["db-key|rotates every 90 days|app", "storage-key|HSM protected|app"]}
@h Create
```bash title="Key ring and key" lab
gcloud kms keyrings create shop-ring --location=europe-west1
gcloud kms keys create db-key --keyring=shop-ring --location=europe-west1 --purpose=encryption \
  --rotation-period=90d --next-rotation-time=2027-02-01T00:00:00Z
echo -n "hello" | gcloud kms encrypt --key=db-key --keyring=shop-ring --location=europe-west1 \
  --plaintext-file=- --ciphertext-file=hello.enc
```
@check
Can a key ring be deleted? || No. Key rings and keys cannot be deleted, only key versions can be destroyed.
@end

@concept Customer-managed encryption keys
@plain
By default Google encrypts all data at rest with Google-managed keys. With **CMEK** you choose a KMS key to protect a service's data.
@problem
Compliance or policy may require control over key lifecycle and the ability to revoke access.
@does
- Supported by Cloud Storage, Compute disks, Cloud SQL, BigQuery, GKE (boot disks, Secrets), Artifact Registry and more. Check the service list.
- Grant the service's **service agent** `roles/cloudkms.cryptoKeyEncrypterDecrypter` on the key. Disabling the key makes data unreadable.
- Org policies `gcp.restrictNonCmekServices` and `gcp.restrictCmekCryptoKeyProjects` enforce use.
- **Cloud KMS Autokey** can create keys on demand for resources; check the current status.
- **AWS equivalent**: SSE-KMS with a customer managed key. Main difference: key and data are in the same location, and service agents need explicit grants.
@diagram flow
caption: CMEK on a bucket
nodes:
  - "Bucket|default KMS key|db"
  - "Service agent|has encrypter role|cp"
  - "Cloud KMS|db-key|app"
  - "Object|encrypted at rest|ok"
@h Bucket with CMEK
```bash title="CMEK" lab
PROJECT_NUMBER=$(gcloud projects describe shop-dev-123456 --format="value(projectNumber)")
gcloud kms keys add-iam-policy-binding db-key --keyring=shop-ring --location=europe-west1 \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com" \
  --role="roles/cloudkms.cryptoKeyEncrypterDecrypter"
gcloud storage buckets create gs://shop-secure-123 --location=europe-west1 \
  --default-encryption-key=projects/shop-dev-123456/locations/europe-west1/keyRings/shop-ring/cryptoKeys/db-key
```
@end

@concept Certificate Authority Service and Certificate Manager
@plain
**Certificate Authority Service** runs private CAs. **Certificate Manager** deploys public TLS certificates to load balancers.
@problem
Internal mTLS, signed workload identities and public cert renewals all need managed certificate lifecycle.
@does
- CA Service: create a CA pool, a root and subordinate CAs backed by KMS or HSM, and issue certificates by API. Tiers DevOps and Enterprise differ in throughput and features.
- Used by Cloud Service Mesh, GKE and cert-manager (Google CAS issuer).
- Certificate Manager issues Google-managed public certificates through DNS authorization, including wildcards, and maps them to Gateways and proxies.
- **AWS equivalent**: AWS Private CA and ACM. Main difference: private CA pools are an explicit unit for policy.
@diagram flow
caption: Private CA use
nodes:
  - "Root CA|offline style|cp"
  - "Subordinate CA|in CA pool|info"
  - "cert-manager|requests certs|app"
  - "Pod|mTLS certificate|ok"
@h Pool and CA
```bash title="CA Service" lab
gcloud privateca pools create shop-pool --location=europe-west1 --tier=devops
gcloud privateca roots create shop-root --pool=shop-pool --location=europe-west1 \
  --subject="CN=Shop Root,O=Example" --key-algorithm=ec-p256-sha256 --max-chain-length=1
```
:::note
Check pricing before creating CAs; they are billed per month.
:::
@end
