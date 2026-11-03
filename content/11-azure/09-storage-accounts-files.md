---
title: Storage accounts, blob tiers, redundancy and Azure Files
minutes: 55
objectives:
  - Explain the storage account model and its services compared with S3
  - Choose redundancy, access tiers and lifecycle rules
  - Secure storage with Entra, SAS, private endpoints and use Azure Files for shared volumes
---
Azure Storage is one account wrapper with blobs, files, queues and tables inside. Most security and cost choices are made once, at account level.

@concept The storage account
@plain
A **storage account** is a namespace and a security boundary that holds Blob containers, file shares, queues and tables.
@problem
You need durable storage with one place for network rules, encryption and redundancy settings.
@does
- **AWS equivalent**: S3 buckets (blobs), EFS (files), SQS (queues, simple), DynamoDB (tables, simple), all in one account object.
- **Main difference**: the account name is globally unique, 3 to 24 lowercase letters and digits, and sets the DNS name `<name>.blob.core.windows.net`. Redundancy, firewall, TLS version and access methods are account-level.
- Use `StorageV2` (general purpose v2). Premium accounts exist for block blobs, file shares and page blobs.
- Hierarchical namespace turns on Data Lake Storage Gen2 semantics.
@diagram layers
caption: Inside an account
layers:
  - {label: "Account settings", nodes: ["Redundancy|LRS ZRS GRS|cp", "Network rules|firewall, private endpoint|cp", "Encryption|keys and TLS|cp"]}
  - {label: "Services", nodes: ["Blob|containers and objects|app", "Files|SMB and NFS shares|app", "Queue|messages|app", "Table|key value|app"]}
@h Create a hardened account
```bash title="Storage account" lab
az storage account create -g rg-shop-prod -n stshopprod --location westeurope --sku Standard_ZRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false --https-only true --allow-shared-key-access false
az storage container create --account-name stshopprod --name uploads --auth-mode login
```
@check
What does the account name decide? || The globally unique DNS name of its endpoints.
@end

@concept Redundancy LRS ZRS GRS
@plain
Redundancy sets how many copies exist and where. **LRS** keeps three copies in one datacentre, **ZRS** across three zones, **GRS** adds an async copy in the paired region, and **GZRS** combines ZRS with a paired-region copy.
@problem
Durability and availability needs vary, and higher redundancy costs more.
@does
- **AWS equivalent**: S3 stores across at least three AZs by default; cross-region replication is opt-in. Azure LRS is the closest to One Zone storage, ZRS to standard S3.
- **Main difference**: with GRS the secondary is read-only only when you choose RA-GRS or RA-GZRS. Failover is customer-initiated and can lose recent writes (RPO is typically under 15 minutes, no SLA guarantee; check current docs).
- Change redundancy later with a conversion; some paths need a migration.
@diagram cmp
caption: Redundancy options
cards:
  - {h: "LRS", kind: warn, items: ["3 copies, one datacentre", "Cheapest", "No zone or region protection"]}
  - {h: "ZRS", kind: ok, items: ["3 zones in the region", "Default for production"]}
  - {h: "GRS and GZRS", kind: cp, items: ["Async copy in paired region", "RA variants allow reads", "Customer failover"]}
@h Change redundancy
```bash title="Redundancy" lab
az storage account update -g rg-shop-prod -n stshopprod --sku Standard_GZRS
az storage account show -g rg-shop-prod -n stshopprod --query '{sku:sku.name,status:statusOfPrimary}' -o json
```
@end

@concept Blob access tiers and lifecycle management
@plain
Blobs are stored in tiers: **Hot**, **Cool**, **Cold** and **Archive**. A lifecycle policy moves or deletes blobs automatically by age or last access.
@problem
Storing old logs and backups on hot storage is expensive.
@does
- **AWS equivalent**: S3 storage classes and S3 Lifecycle rules.
- **Main difference**: Hot to Cold are online; Archive is offline and needs rehydration (hours) before reading. Early deletion fees apply to Cool, Cold and Archive for minimum durations; check the current docs for the numbers. There is no automatic tiering by access pattern equivalent to Intelligent-Tiering, but last access time tracking can drive lifecycle rules.
- Rules filter by prefix and blob type and act on `daysAfterModificationGreaterThan` and more.
@diagram flow
caption: Typical aging
nodes:
  - "Hot|first 30 days|warn"
  - "Cool|to 90 days|info"
  - "Cold or Archive|retention|env"
  - "Delete|after 7 years|bad"
@h Lifecycle policy
```json title="lifecycle.json"
{
  "rules": [
    {
      "name": "age-logs",
      "enabled": true,
      "type": "Lifecycle",
      "definition": {
        "filters": {"blobTypes": ["blockBlob"], "prefixMatch": ["logs/"]},
        "actions": {
          "baseBlob": {
            "tierToCool": {"daysAfterModificationGreaterThan": 30},
            "tierToArchive": {"daysAfterModificationGreaterThan": 180},
            "delete": {"daysAfterModificationGreaterThan": 2555}
          }
        }
      }
    }
  ]
}
```
```bash title="Apply" lab
az storage account management-policy create --account-name stshopprod -g rg-shop-prod --policy @lifecycle.json
```
@check
Can you read an Archive blob immediately? || No. You must rehydrate it to an online tier first.
@end

@concept Data protection
@plain
Soft delete, versioning, change feed and immutability protect blobs from accidents and ransomware.
@problem
A bad script or compromised key can delete or overwrite data permanently.
@does
- **AWS equivalent**: S3 versioning, Object Lock, MFA delete.
- **Main difference**: **soft delete** for blobs, containers and file shares is separate and keeps deleted items for a set number of days. **Versioning** keeps older versions. **Immutable storage** (time-based retention or legal hold, WORM) is set per container or version.
- **Point-in-time restore** needs versioning, change feed and soft delete together.
- Backup vaults can protect blobs, disks and databases outside the account.
@diagram layers
caption: Protection stack
layers:
  - {label: "Prevent", nodes: ["Immutability policy|WORM|ok", "Resource lock|stop account delete|ok"]}
  - {label: "Recover", nodes: ["Soft delete|undelete in days|info", "Versioning|previous versions|info", "Point in time restore|needs change feed|info"]}
@h Enable
```bash title="Blob protection" lab
az storage account blob-service-properties update -g rg-shop-prod --account-name stshopprod \
  --enable-delete-retention true --delete-retention-days 14 --enable-versioning true \
  --enable-container-delete-retention true --container-delete-retention-days 14
```
@end

@concept Access control SAS keys and Entra
@plain
You can authorise requests with Entra ID and RBAC, with a **shared key**, or with a **Shared Access Signature (SAS)** that grants limited access to a URL.
@problem
Account keys are all-powerful and never expire on their own. Giving them to apps or users is dangerous.
@does
- **AWS equivalent**: IAM and bucket policies, and S3 presigned URLs for SAS.
- **Main difference**: three SAS types. **User delegation SAS** is signed with Entra credentials and is the safest. **Service SAS** and **account SAS** are signed with the account key. A SAS cannot be revoked individually unless tied to a stored access policy; keep lifetimes short.
- Best practice: disable shared key access, use RBAC (`Storage Blob Data Contributor`) and managed identity.
@diagram cmp
caption: Access methods
cards:
  - {h: "Entra and RBAC", kind: ok, items: ["Managed identity", "Per user audit", "Preferred"]}
  - {h: "User delegation SAS", kind: info, items: ["Time limited URL", "Signed by Entra", "Share with outsiders"]}
  - {h: "Account key", kind: bad, items: ["Full control", "No identity", "Disable it"]}
@h Generate a user delegation SAS
```bash title="SAS" lab
EXP=$(date -u -v+1H '+%Y-%m-%dT%H:%MZ' 2>/dev/null || date -u -d '+1 hour' '+%Y-%m-%dT%H:%MZ')
az storage blob generate-sas --account-name stshopprod -c uploads -n report.pdf --permissions r \
  --expiry "$EXP" --https-only --auth-mode login --as-user --full-uri
```
:::warn
Anyone holding a SAS URL has its permissions until it expires. Never log it and keep the lifetime short.
:::
@check
Which SAS type avoids using the account key? || The user delegation SAS.
@end

@concept Private endpoints and firewalls for storage
@plain
Storage can be closed to the public network, with access through private endpoints, selected VNets or specific IPs.
@problem
The default storage endpoint is reachable from the internet by anyone who has credentials.
@does
- **AWS equivalent**: S3 bucket policy with VPC endpoint conditions, S3 Block Public Access.
- **Main difference**: one private endpoint per sub-service (`blob`, `file`, `queue`, `table`, `dfs`). Network rules default action `Deny` with exceptions such as `AzureServices` bypass. Needs the matching `privatelink.*` DNS zone.
- Private endpoint access is evaluated with RBAC and auth like any request.
- Resource instance rules allow trusted Azure services by resource ID.
@diagram flow
caption: Locked down account
nodes:
  - "Public access|disabled|bad"
  - "Private endpoint|blob subresource|cp"
  - "Private DNS|privatelink.blob|info"
  - "Pods and VMs|managed identity|app"
@h Lock down
```bash title="Network rules" lab
az storage account update -g rg-shop-prod -n stshopprod --default-action Deny --bypass AzureServices
az storage account network-rule add -g rg-shop-prod --account-name stshopprod --ip-address 203.0.113.10
az storage account show -g rg-shop-prod -n stshopprod --query networkRuleSet -o json
```
@end

@concept Azure Files
@plain
**Azure Files** gives managed file shares over SMB or NFS, mounted by VMs and Kubernetes pods.
@problem
Some workloads need a shared POSIX or Windows file system, not object storage.
@does
- **AWS equivalent**: EFS for NFS, FSx for Windows for SMB.
- **Main difference**: shares live in a storage account. Standard shares use HDD or SSD pay-as-used tiers; Premium shares (SSD) are provisioned. NFS needs Premium and no encryption-in-transit key via TLS-less mount, so it needs a private endpoint or service endpoint; check the current docs.
- SMB supports Entra Kerberos or AD authentication.
- On AKS the built-in CSI driver (`file.csi.azure.com`) mounts shares as ReadWriteMany volumes.
@diagram flow
caption: Share to pod
nodes:
  - "Storage account|file service|env"
  - "File share|SMB or NFS|info"
  - "CSI driver|file.csi.azure.com|cp"
  - "Pods|ReadWriteMany|app"
@h Share and PVC
```bash title="Create share" lab
az storage share-rm create --storage-account stshopprod -g rg-shop-prod --name media --quota 100 --enabled-protocols SMB
```
```yaml title="pvc-files.yaml"
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: media
  namespace: shop
spec:
  accessModes: ["ReadWriteMany"]
  storageClassName: azurefile-csi
  resources:
    requests:
      storage: 100Gi
```
@check
Which AKS storage class gives ReadWriteMany by default, a disk or Azure Files? || Azure Files. Azure Disk is ReadWriteOnce.
@end
