---
title: Compute Engine machines, images and access
minutes: 50
objectives:
  - Choose a machine family and size for a workload
  - Build VMs from images and instance templates with a dedicated service account
  - Reach private VMs with OS Login and IAP TCP forwarding instead of public SSH
---
Compute Engine is the virtual machine service. If you run EC2 today the concepts carry over, with custom machine shapes and IAM-based access as the notable differences.

@concept Machine families and types
@plain
A **machine type** sets vCPU and memory. Types are grouped into families by purpose: general purpose, compute optimized, memory optimized, storage optimized and accelerator optimized.
@problem
Paying for the wrong CPU to memory ratio wastes money, and picking the wrong CPU platform hurts performance.
@does
- General purpose series: E2 (cost optimized), N2, N2D, N4, C3 and C4, Tau T2D (scale-out). Compute optimized: C2, H3. Memory optimized: M-series. Accelerators: A and G series with GPUs.
- Predefined shapes are named like `n2-standard-4`, with `standard`, `highmem` and `highcpu` ratios.
- **Custom machine types** and extended memory let you set vCPU and memory yourself within series limits.
- Availability differs by zone, so check the current docs and `gcloud compute machine-types list`.
- **AWS equivalent**: EC2 instance families. Main difference: you can build a custom vCPU and memory shape rather than choosing only fixed sizes.
@diagram cmp
caption: Families at a glance
cards:
  - {h: "General purpose", kind: app, items: ["E2, N2, N4, C3", "Web, APIs, small databases"]}
  - {h: "Compute optimized", kind: info, items: ["C2, H3", "High clock, HPC, games"]}
  - {h: "Memory optimized", kind: cp, items: ["M-series", "In-memory databases"]}
  - {h: "Accelerator", kind: warn, items: ["A and G series", "ML and graphics"]}
@h Inspect
```bash title="Machine types" lab
gcloud compute machine-types list --zones=europe-west1-b --filter="name~^n2-standard" \
  --format="table(name,guestCpus,memoryMb)"
gcloud compute instances create custom-vm --zone=europe-west1-b \
  --custom-vm-type=n2 --custom-cpu=6 --custom-memory=20GB
```
@check
What is a custom machine type for? || Setting your own vCPU and memory combination to avoid paying for unused resources.
@end

@concept Create a VM correctly
@plain
A secure VM has no external IP, uses a dedicated service account, a hardened image and a boot disk you can reproduce.
@problem
Defaults such as the default service account with wide scopes and a public IP create an unnecessary risk.
@does
- `--no-address` removes the external IP; use Cloud NAT and IAP.
- `--service-account` with `--scopes=cloud-platform` and IAM roles on the account limit what the VM can do.
- Shielded VM options (secure boot, vTPM, integrity monitoring) are available for supported images.
- Labels, metadata and startup scripts configure the machine.
- **AWS equivalent**: `run-instances` with an instance profile. Main difference: access scopes are legacy; control permissions through IAM roles.
@diagram flow
caption: A hardened instance
nodes:
  - "Image|hardened|info"
  - "Service account|least privilege|cp"
  - "Private subnet|no external IP|env"
  - "VM|shielded|app"
@h Create
```bash title="Private VM" lab
gcloud compute instances create shop-vm-1 --zone=europe-west1-b --machine-type=e2-medium \
  --subnet=shop-ew1 --no-address \
  --service-account=shop-api@shop-dev-123456.iam.gserviceaccount.com --scopes=cloud-platform \
  --image-family=debian-12 --image-project=debian-cloud \
  --shielded-secure-boot --shielded-vtpm --shielded-integrity-monitoring \
  --labels=env=dev,app=shop
```
@end

@concept Images and image families
@plain
An **image** is a boot disk template. An **image family** is a pointer to the latest non-deprecated image in a series.
@problem
Every VM needs a base operating system, and you want to roll out new golden images safely.
@does
- Public images come from projects such as `debian-cloud`, `ubuntu-os-cloud`, `rhel-cloud`, `cos-cloud`, `windows-cloud`.
- Create your own from a disk or snapshot, store it in a project, and share with IAM (`roles/compute.imageUser`).
- Deprecate old images with `gcloud compute images deprecate`.
- Images are global resources; they are not copied per region.
- **AWS equivalent**: AMIs. Main difference: images are global and families give a built-in "latest" pointer.
@diagram flow
caption: Golden image pipeline
nodes:
  - "Base image|Debian family|info"
  - "Build|Packer or script|app"
  - "Custom image|family shop-base|ok"
  - "Template|references family|cp"
@h Image from disk
```bash title="Custom image" lab
gcloud compute images create shop-base-20261101 --source-disk=shop-vm-1 \
  --source-disk-zone=europe-west1-b --family=shop-base
gcloud compute images describe-from-family shop-base --format="value(name,status)"
```
@end

@concept Instance templates
@plain
An **instance template** stores a VM configuration (machine type, disk, network, metadata, service account) for creating many VMs or a managed instance group.
@problem
Hand-built VMs drift. You need repeatable configuration that autoscaling can use.
@does
- Templates are immutable. To change something create a new template and roll it into the group.
- Global templates can be used in any region; regional templates restrict to one region.
- Supports `--instance-template` for `instances create` and for managed instance groups.
- **AWS equivalent**: launch templates. Main difference: very similar; templates are immutable and not versioned in place.
@diagram flow
caption: Template to fleet
nodes:
  - "Instance template|immutable config|cp"
  - "Managed instance group|creates VMs|app"
  - "VM 1|from template|vm"
  - "VM 2|from template|vm"
@h Create
```bash title="Template" lab
gcloud compute instance-templates create shop-api-tpl-v1 --machine-type=e2-medium \
  --subnet=shop-ew1 --region=europe-west1 --no-address \
  --image-family=shop-base --service-account=shop-api@shop-dev-123456.iam.gserviceaccount.com \
  --scopes=cloud-platform --metadata-from-file=startup-script=startup.sh
```
@check
Can you edit an instance template in place? || No. Create a new template and update the group.
@end

@concept Metadata server and startup scripts
@plain
Every VM can query a local **metadata server** at `metadata.google.internal` for its attributes, tokens and custom metadata.
@problem
Software on the VM needs to discover its project, zone and credentials without baked-in config.
@does
- Requests need the header `Metadata-Flavor: Google`.
- Service account tokens come from `/computeMetadata/v1/instance/service-accounts/default/token`.
- Custom keys such as `startup-script` run at each boot; `shutdown-script` runs on a best-effort basis.
- Project-level and instance-level metadata are both available.
- **AWS equivalent**: IMDS and user data. Main difference: the header requirement is the built-in guard against SSRF, similar to IMDSv2.
@diagram seq
caption: Token from the metadata server
actors: ["App on VM|process|app", "Metadata server|169.254.169.254|cp"]
steps:
  - "0>1: GET token with Metadata-Flavor | req"
  - "1>0: short-lived access token | resp"
@h Try it on a VM
```bash title="Metadata queries" lab
curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/zone"
curl -s -H "Metadata-Flavor: Google" \
  "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email"
```
@end

@concept OS Login
@plain
**OS Login** maps IAM users to Linux accounts and manages SSH keys through IAM, so you do not edit metadata keys by hand.
@problem
Project-wide SSH keys in metadata are hard to audit and remove.
@does
- Enable with metadata `enable-oslogin=TRUE` or the org policy `compute.requireOsLogin`.
- Roles: `roles/compute.osLogin` (user) and `roles/compute.osAdminLogin` (sudo). External users need `roles/compute.osLoginExternalUser` at the organization.
- Add 2-step verification with `enable-oslogin-2fa`.
- Login events appear in audit logs and your username derives from your identity.
- **AWS equivalent**: EC2 Instance Connect or SSM Session Manager. Main difference: access is plain SSH controlled by IAM roles.
@diagram flow
caption: SSH with OS Login
nodes:
  - "Engineer|gcloud compute ssh|ext"
  - "IAM role|osLogin or osAdminLogin|cp"
  - "OS Login|creates user and key|info"
  - "VM|SSH session|app"
@h Enable and grant
```bash title="OS Login" lab
gcloud compute project-info add-metadata --metadata enable-oslogin=TRUE
gcloud projects add-iam-policy-binding shop-dev-123456 \
  --member="group:sre@example.com" --role="roles/compute.osAdminLogin"
gcloud compute os-login describe-profile
```
@check
Which role gives sudo through OS Login? || roles/compute.osAdminLogin.
@end

@concept Identity-Aware Proxy TCP forwarding
@plain
**IAP TCP forwarding** tunnels SSH, RDP or any TCP port to VMs that have no external IP, after checking IAM.
@problem
Bastion hosts and public SSH are a standing attack surface and an operations burden.
@does
- Your client connects to IAP over HTTPS, IAP checks `roles/iap.tunnelResourceAccessor` and connects to the VM from `35.235.240.0/20`.
- The firewall must allow that source range on the target port.
- `gcloud compute ssh --tunnel-through-iap` and `gcloud compute start-iap-tunnel` forward ports for databases and admin UIs.
- **AWS equivalent**: SSM Session Manager port forwarding. Main difference: it works at the TCP level without an agent on the VM.
@diagram seq
caption: Tunnel to a private VM
actors: ["Engineer|laptop|ext", "IAP|identity check|cp", "VM|no public IP|app"]
steps:
  - "0>1: HTTPS tunnel request | tls"
  - "note 1..1: check IAM and context"
  - "1>2: connect from IAP range | req"
  - "2>0: SSH session over tunnel | resp"
@h Connect
```bash title="IAP" lab
gcloud projects add-iam-policy-binding shop-dev-123456 \
  --member="group:sre@example.com" --role="roles/iap.tunnelResourceAccessor"
gcloud compute ssh shop-vm-1 --zone=europe-west1-b --tunnel-through-iap
gcloud compute start-iap-tunnel shop-vm-1 5432 --local-host-port=localhost:5432 --zone=europe-west1-b
```
:::tip
Use IAP together with OS Login and the org policy that blocks external IPs for a bastion-free setup.
:::
@end
