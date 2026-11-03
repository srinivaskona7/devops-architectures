---
title: Azure and Google Cloud SDK basics
minutes: 40
objectives:
  - Authenticate to Azure with DefaultAzureCredential and list resources
  - Use the Azure management and storage SDKs
  - Authenticate to Google Cloud with application default credentials
  - Compare the three cloud SDKs so skills carry over
---
Most teams end up multi cloud at the edges. The three Python SDKs share the same ideas: a credential chain, a client per service, paging, and long running operations. Learn them once, then map the names.

@concept Azure credentials with DefaultAzureCredential
@plain
`DefaultAzureCredential` from the `azure-identity` package tries several sources in order, much like boto3's chain: environment variables, workload identity, managed identity, then developer logins such as the Azure CLI.
@problem
A script should run unchanged on a laptop, in a pipeline and on an Azure VM or AKS pod, without storing a client secret in code.
@does
- Environment: `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET` or a certificate.
- Workload identity in AKS and managed identity on VMs and App Service need no secrets.
- `az login` supplies a developer credential locally.
- The credential object is passed to every client.
@diagram flow
caption: Credential chain order
nodes:
  - "Environment variables|service principal|env"
  - "Workload identity|AKS pods|app"
  - "Managed identity|VMs and apps|ok"
  - "Azure CLI login|developer laptop|info"
@h Example
```python title="azure_auth.py" nocheck
from azure.identity import DefaultAzureCredential
from azure.mgmt.resource import SubscriptionClient

cred = DefaultAzureCredential()
subs = SubscriptionClient(cred)
for s in subs.subscriptions.list():
    print(s.subscription_id, s.display_name, s.state)
```
@check
Why prefer managed identity over a client secret? || There is no secret to store or rotate; Azure issues short lived tokens to the resource.
@end

@concept Azure management SDK and resource listing
@plain
The `azure-mgmt-*` packages manage resources: `azure-mgmt-resource` for groups, `azure-mgmt-compute` for VMs, `azure-mgmt-network`, `azure-mgmt-storage` and so on. Each client takes a credential and a subscription id.
@problem
Portal clicking cannot enforce tags or find orphaned disks across many subscriptions.
@does
- Operations are grouped: `compute.virtual_machines.list_all()`, `compute.disks.list()`.
- List calls return a pager (`ItemPaged`) that fetches pages lazily; just iterate.
- Create and delete calls return a **poller**; call `.result()` to wait.
- Resource properties include `tags`, a dictionary or `None`.
@diagram layers
caption: Azure management layout
layers:
  - {label: "Identity", nodes: ["Credential|DefaultAzureCredential|cp"]}
  - {label: "Clients", nodes: ["ResourceManagementClient|groups|app", "ComputeManagementClient|VMs and disks|app", "NetworkManagementClient|VNets and IPs|app"]}
  - {label: "Scope", nodes: ["Subscription|billing and access boundary|env", "Resource group|lifecycle container|env"]}
@h Unattached disks
```python title="azure_orphan_disks.py" nocheck
import os

from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient

sub_id = os.environ["AZURE_SUBSCRIPTION_ID"]
compute = ComputeManagementClient(DefaultAzureCredential(), sub_id)

for disk in compute.disks.list():
    if disk.disk_state == "Unattached" and disk.managed_by is None:
        print(disk.name, disk.disk_size_gb, "GB", disk.location, disk.tags or {})
```
@check
What does .result() do on a poller? || It blocks until the long running operation finishes and returns its outcome.
@end

@concept Azure Blob Storage and pollers
@plain
`azure-storage-blob` talks to storage accounts. A `BlobServiceClient` leads to container clients and blob clients. Long operations such as creating a VM return a poller.
@problem
Operations like VM creation take minutes; blocking calls without a handle give no way to check progress or time out.
@does
- `BlobServiceClient(account_url, credential=cred)` using Entra ID instead of account keys.
- `container.list_blobs(name_starts_with="logs/")` iterates lazily.
- `blob.upload_blob(data, overwrite=True)` and `download_blob().readall()`.
- Pollers expose `.status()`, `.done()` and `.result(timeout=...)`.
@diagram flow
caption: From account to blob
nodes:
  - "BlobServiceClient|account URL|app"
  - "ContainerClient|one container|info"
  - "BlobClient|one blob|env"
  - "Upload or download|stream or bytes|ok"
@h Example
```python title="azure_blob.py" nocheck
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient

svc = BlobServiceClient("https://opsreports.blob.core.windows.net", credential=DefaultAzureCredential())
container = svc.get_container_client("reports")
container.upload_blob("weekly/2026-w10.csv", b"name,cost\nweb,12\n", overwrite=True)
for blob in container.list_blobs(name_starts_with="weekly/"):
    print(blob.name, blob.size)
```
@check
Why use credential= instead of an account key? || Entra ID tokens are short lived and scoped by role, unlike an all powerful key.
@end

@concept Google Cloud application default credentials
@plain
**Application Default Credentials (ADC)** let Google client libraries find credentials automatically: an environment variable pointing to a key file, the credentials from `gcloud auth application-default login`, or the attached service account on GCE, GKE or Cloud Run.
@problem
Downloading service account JSON keys and copying them around is the main way Google Cloud credentials leak.
@does
- `google.auth.default()` returns `(credentials, project_id)`.
- `GOOGLE_APPLICATION_CREDENTIALS` points to a key file; avoid it where workload identity is available.
- GKE Workload Identity maps a Kubernetes service account to a Google service account without keys.
- Clients accept `project=` explicitly when ADC cannot infer it.
@diagram flow
caption: ADC lookup order
nodes:
  - "GOOGLE_APPLICATION_CREDENTIALS|key file path|warn"
  - "gcloud user credentials|local development|info"
  - "Attached service account|GCE, GKE, Cloud Run|ok"
@h Example
```python title="gcp_adc.py" nocheck
import google.auth

credentials, project = google.auth.default()
print("project:", project)
print("credential type:", type(credentials).__name__)
```
:::tip
Locally run `gcloud auth application-default login` once. It is separate from `gcloud auth login`, which only authenticates the CLI.
:::
@check
What is the safest ADC source in production? || An attached service account or Workload Identity, which needs no key file.
@end

@concept Google Cloud Storage and Compute clients
@plain
Google ships one library per service: `google-cloud-storage`, `google-cloud-compute`, `google-cloud-pubsub`, and so on. Each exposes a client class, and list calls return iterators that page for you.
@problem
Finding old buckets or unused disks across projects needs code, not clicks.
@does
- `storage.Client(project="p")`, then `client.list_buckets()`, `bucket.list_blobs(prefix="x/")`, `blob.upload_from_filename(path)`.
- `compute_v1.DisksClient().aggregated_list(project=...)` iterates zones and their disks.
- Calls raise `google.api_core.exceptions.NotFound`, `Forbidden`, `TooManyRequests`.
- Client libraries retry transient errors with defaults you can override via `retry=`.
@diagram flow
caption: Storage client chain
nodes:
  - "storage.Client|project and ADC|app"
  - "Bucket|list or get|info"
  - "Blob|object|env"
  - "upload or download|file or bytes|ok"
@h Examples
```python title="gcp_storage.py" nocheck
from google.cloud import compute_v1, storage

client = storage.Client(project="my-project")
for bucket in client.list_buckets():
    print(bucket.name, bucket.location, bucket.storage_class)

for blob in client.bucket("ops-reports").list_blobs(prefix="weekly/"):
    print(blob.name, blob.size)

disks = compute_v1.DisksClient()
for zone, scoped in disks.aggregated_list(project="my-project"):
    for d in scoped.disks:
        if not d.users:                     # not attached to any instance
            print(zone, d.name, d.size_gb)
```
@check
How do you find unattached disks in GCP? || A disk with an empty users list is not attached to any instance.
@end

@concept Mapping concepts across clouds
@plain
AWS, Azure and Google Cloud solve the same problems with different names. Knowing the map lets you read any SDK quickly.
@problem
Learning each SDK from zero is slow, and teams copy the wrong habits, such as keys in code, between clouds.
@does
- Identity: AWS roles and STS, Azure managed identity, Google service accounts with Workload Identity.
- Listing: AWS paginators, Azure `ItemPaged`, Google iterators; all lazy.
- Waiting: AWS waiters, Azure pollers, Google long running operations (`operation.result()`).
- Errors: `ClientError`, `HttpResponseError`, `google.api_core.exceptions`.
@diagram cmp
caption: The same ideas, three vocabularies
cards:
  - {h: "AWS boto3", kind: app, items: ["Provider chain, STS roles", "Paginators and waiters", "ClientError codes"]}
  - {h: "Azure SDK", kind: info, items: ["DefaultAzureCredential", "ItemPaged and pollers", "HttpResponseError"]}
  - {h: "Google Cloud", kind: ok, items: ["ADC and Workload Identity", "Iterators and operations", "api_core exceptions"]}
@h Keep cloud code behind an interface
```python title="cloud_neutral.py" lab
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IdleDisk:
    cloud: str
    name: str
    size_gb: int


class DiskLister(Protocol):
    def idle_disks(self) -> list[IdleDisk]: ...


class FakeAws:
    def idle_disks(self) -> list[IdleDisk]:
        return [IdleDisk("aws", "vol-1", 100)]


class FakeAzure:
    def idle_disks(self) -> list[IdleDisk]:
        return [IdleDisk("azure", "disk-a", 64)]


def total_waste(listers: list[DiskLister]) -> int:
    return sum(d.size_gb for l in listers for d in l.idle_disks())


print(total_waste([FakeAws(), FakeAzure()]), "GB idle")
```
@check
What is the Azure equivalent of a boto3 waiter? || A poller, whose result() waits for completion.
@end
