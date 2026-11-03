---
title: Virtual machines, scale sets, disks and Bastion
minutes: 55
objectives:
  - Choose VM sizes and understand availability zones versus availability sets
  - Run elastic fleets with VM Scale Sets and flexible orchestration
  - Reduce cost with Spot, reservations and savings plans and reach VMs safely with Bastion
---
VMs are still the base of node pools, build agents and lift-and-shift workloads. These pages cover the parts you tune most.

@concept VM sizes and families
@plain
A VM size name encodes the family, vCPU count, features and generation, for example `Standard_D4s_v5`.
@problem
Hundreds of sizes make it easy to pick one that is too large, or one that lacks the disk or network feature you need.
@does
- **AWS equivalent**: EC2 instance types.
- **Main difference**: letters mean D general purpose, E memory optimised, F compute optimised, B burstable, L storage, N GPU. Suffix `s` means premium storage capable, `d` local temp disk, `a` AMD, `p` Arm (Cobalt). Check the current docs for which generation is latest.
- The temp disk is ephemeral and not for data.
- vCPU quotas are per family per region per subscription.
@diagram cmp
caption: Common families
cards:
  - {h: "D series", kind: app, items: ["General purpose", "Balanced CPU and memory", "Default for AKS nodes"]}
  - {h: "E series", kind: info, items: ["Memory optimised", "Databases and caches"]}
  - {h: "B series", kind: warn, items: ["Burstable CPU", "Dev and small tools"]}
@h Discover sizes
```bash title="List sizes and quota" lab
az vm list-skus -l westeurope --resource-type virtualMachines --size Standard_D --query "[?restrictions==\`[]\`].name" -o tsv | head
az vm list-usage -l westeurope -o table | head -20
```
@check
What does the s in Standard_D4s_v5 indicate? || Premium storage capability.
@end

@concept Creating and securing a VM
@plain
A VM is a compute resource plus a network interface, an OS disk and usually a public or private IP.
@problem
Default creation commands open ports or use passwords if you are not careful.
@does
- **AWS equivalent**: `aws ec2 run-instances`.
- **Main difference**: you create separate NIC, disk and IP objects (the CLI does this for you). Use SSH keys, no public IP, and the Entra ID login extension for access control by RBAC (`Virtual Machine Administrator Login`).
- Images are referenced as `publisher:offer:sku:version` or via Compute Gallery.
- Trusted launch (secure boot and vTPM) is the default for newer images.
@diagram flow
caption: Objects created with a VM
nodes:
  - "VM|size and image|app"
  - "NIC|private IP, NSG|info"
  - "OS disk|managed disk|env"
  - "Identity|managed identity|cp"
@h Create a private VM
```bash title="az vm create" lab
az vm create -g rg-lab -n vm1 --image Ubuntu2204 --size Standard_D2s_v5 \
  --vnet-name vnet-hub --subnet snet-aks --public-ip-address "" \
  --admin-username azureuser --generate-ssh-keys --assign-identity
az vm show -g rg-lab -n vm1 -d --query '{ip:privateIps,state:powerState}' -o json
```
:::tip
`Ubuntu2204` is an alias; check `az vm image list` for current aliases and consider pinning to a Compute Gallery image.
:::
@end

@concept Availability zones and availability sets
@plain
**Zones** place VMs in separate datacentres. An **availability set** spreads VMs over fault and update domains inside one datacentre.
@problem
Hardware failures and maintenance must not take all instances down together.
@does
- **AWS equivalent**: placing instances in several AZs; partition and spread placement groups.
- **Main difference**: choose either a zone or an availability set for a VM, not both. Zones give the stronger SLA and are the default choice where supported. Availability sets are for regions without zones or legacy designs.
- A zonal VM is pinned to a zone and its disks follow. Zone-redundant services spread automatically.
- Load balancers must be Standard SKU to front zonal VMs.
@diagram layers
caption: Resilience options
layers:
  - {label: "Zones", nodes: ["VM in zone 1|separate datacentre|app", "VM in zone 2|separate datacentre|app", "VM in zone 3|separate datacentre|app"]}
  - {label: "Availability set", nodes: ["Fault domains|power and network|info", "Update domains|rolling maintenance|info"]}
@h Spread across zones
```bash title="Zonal VMs" lab
for z in 1 2 3; do
  az vm create -g rg-lab -n web-$z --zone $z --image Ubuntu2204 --size Standard_D2s_v5 \
    --vnet-name vnet-hub --subnet snet-aks --public-ip-address "" --generate-ssh-keys
done
```
@check
Can one VM be in both a zone and an availability set? || No. Choose one.
@end

@concept VM Scale Sets
@plain
A **VM Scale Set (VMSS)** manages a group of identical or mixed VMs with autoscale, rolling upgrades and zone spreading.
@problem
Running many similar VMs by hand does not scale or heal.
@does
- **AWS equivalent**: Auto Scaling group.
- **Main difference**: two orchestration modes. **Flexible** is the recommended mode and can span zones, mix sizes and attach standard VMs. **Uniform** uses a single model and is what AKS used historically. Check current docs; Uniform is being steered away from for new designs.
- Autoscale rules use Azure Monitor metrics or schedules.
- Upgrade policy: manual, automatic or rolling with health extension.
@diagram flow
caption: Scale set control loop
nodes:
  - "Metric or schedule|CPU, queue length|info"
  - "Autoscale setting|min, max, rules|cp"
  - "Scale set|flexible orchestration|env"
  - "Instances|across zones|app"
@h Create and autoscale
```bash title="Scale set" lab
az vmss create -g rg-lab -n vmss-web --image Ubuntu2204 --vm-sku Standard_D2s_v5 --instance-count 3 \
  --zones 1 2 3 --orchestration-mode Flexible --upgrade-policy-mode Automatic --admin-username azureuser --generate-ssh-keys
az monitor autoscale create -g rg-lab --resource vmss-web --resource-type Microsoft.Compute/virtualMachineScaleSets \
  --min-count 3 --max-count 10 --count 3 -n as-web
az monitor autoscale rule create -g rg-lab --autoscale-name as-web --condition "Percentage CPU > 70 avg 5m" --scale out 2
```
@end

@concept Managed disks
@plain
**Managed disks** are block volumes that Azure stores and replicates for you. Pick a type by performance and cost.
@problem
The disk type decides IOPS, throughput, latency and monthly price, and the wrong one throttles databases.
@does
- **AWS equivalent**: EBS volumes.
- **Main difference**: types are Standard HDD, Standard SSD, Premium SSD, Premium SSD v2 and Ultra Disk. Premium SSD v2 and Ultra let you tune size, IOPS and throughput independently, like gp3 and io2. Redundancy is LRS or ZRS (ZRS on supported types).
- Disks attach to one VM (shared disks exist for clusters). Snapshots are incremental.
- Encryption at rest is on by default with platform keys; customer-managed keys via disk encryption sets.
@diagram cmp
caption: Disk types
cards:
  - {h: "Standard HDD or SSD", kind: info, items: ["Dev, backup, light use", "Lowest cost"]}
  - {h: "Premium SSD", kind: app, items: ["Production default", "Fixed performance tiers by size"]}
  - {h: "Premium SSD v2 and Ultra", kind: cp, items: ["Tune IOPS and throughput", "Databases and logs"]}
@h Create and attach
```bash title="Disk" lab
az disk create -g rg-lab -n data1 --size-gb 256 --sku Premium_LRS --zone 1
az vm disk attach -g rg-lab --vm-name web-1 --name data1
az snapshot create -g rg-lab -n data1-snap --source data1 --incremental true
```
@check
Which disk types let you set IOPS independent of size? || Premium SSD v2 and Ultra Disk.
@end

@concept Spot VMs
@plain
**Spot VMs** use spare capacity at a deep discount and can be evicted when Azure needs the capacity back.
@problem
Batch jobs, CI agents and stateless workers do not need guaranteed capacity but pay for it anyway.
@does
- **AWS equivalent**: EC2 Spot Instances.
- **Main difference**: you pick an eviction policy (Deallocate or Delete) and an optional max price (`-1` means up to the pay-as-you-go price). Eviction notice comes through Scheduled Events about 30 seconds before. There is no persistent request object like an AWS Spot request.
- Spot node pools in AKS carry a taint so only tolerant pods land there.
- Use mixed scale sets with a base of regular VMs.
@diagram flow
caption: Spot lifecycle
nodes:
  - "Spot VM|discounted|ok"
  - "Capacity needed|Azure reclaims|warn"
  - "Scheduled event|about 30 s notice|info"
  - "Evicted|deallocated or deleted|bad"
@h Spot VM and Spot node pool
```bash title="Spot" lab
az vm create -g rg-lab -n spot1 --image Ubuntu2204 --size Standard_D4s_v5 --priority Spot \
  --eviction-policy Deallocate --max-price -1 --generate-ssh-keys
az aks nodepool add -g rg-shop-prod --cluster-name aks-shop-prod -n spot --priority Spot \
  --eviction-policy Delete --spot-max-price -1 --enable-cluster-autoscaler --min-count 0 --max-count 5 --node-vm-size Standard_D4s_v5
```
@end

@concept Reservations and savings plans
@plain
Commit to usage for one or three years in return for a lower hourly price. **Reservations** fix a VM family and region. **Savings plans** commit a spend per hour across services.
@problem
Always-on production VMs at pay-as-you-go prices waste money.
@does
- **AWS equivalent**: Reserved Instances and Savings Plans (Compute).
- **Main difference**: Azure reservations can be scoped to a single subscription, a resource group or shared across a billing scope, and size flexibility works within a family group. Savings plans apply across VMs, AKS nodes, Functions premium and more. There is also Azure Hybrid Benefit for existing Windows and SQL licences, and a Linux variant for RHEL and SUSE.
- Reservations apply to the VM compute, not disks or network.
- Exchange and refund rules change; check the current docs.
@diagram cmp
caption: Which commitment
cards:
  - {h: "Reservation", kind: info, items: ["Specific VM family and region", "Highest discount", "Less flexible"]}
  - {h: "Savings plan", kind: ok, items: ["Hourly spend commitment", "Across sizes and regions", "More flexible"]}
  - {h: "Pay as you go", kind: warn, items: ["No commitment", "Highest price", "Use for variable load"]}
@h See recommendations
```bash title="Advisor cost recommendations" lab
az advisor recommendation list --category Cost --query "[].{impact:impact,problem:shortDescription.problem}" -o table
az consumption reservation summary list --grain monthly --reservation-order-id 00000000-0000-0000-0000-000000000000 -o table
```
:::note
Prices for Spot, reservations and plans change. Use the Azure pricing calculator for current numbers.
:::
@check
What does a savings plan commit you to? || A fixed hourly spend, applied across eligible services.
@end

@concept Azure Bastion
@plain
**Azure Bastion** is a managed jump host. You open an SSH or RDP session to a private VM from the portal or CLI over TLS, with no public IP on the VM.
@problem
Opening port 22 or 3389 to the internet is a leading breach cause, and running your own jump box means patching it.
@does
- **AWS equivalent**: SSM Session Manager or EC2 Instance Connect Endpoint.
- **Main difference**: Bastion is a billed resource that lives in `AzureBastionSubnet` (/26 or larger) and uses a Standard public IP. SKUs Developer, Basic, Standard and Premium add features such as native client and shareable links; check the current docs.
- Access is controlled with RBAC (Reader on VM, NIC, Bastion) plus the VM login.
- Native client tunnels work with `az network bastion ssh` and `tunnel`.
@diagram flow
caption: Session through Bastion
nodes:
  - "Engineer|az login and MFA|ext"
  - "Azure Bastion|AzureBastionSubnet|cp"
  - "Private VM|no public IP|app"
  - "Audit|session logs|info"
@h Create and connect
```bash title="Bastion" lab
az network vnet subnet create -g rg-net --vnet-name vnet-hub -n AzureBastionSubnet --address-prefixes 10.10.33.0/26
az network public-ip create -g rg-net -n pip-bastion --sku Standard
az network bastion create -g rg-net -n bas-hub --vnet-name vnet-hub --public-ip-address pip-bastion --sku Standard --enable-tunneling true
az network bastion ssh -g rg-net -n bas-hub --target-resource-id "$(az vm show -g rg-lab -n vm1 --query id -o tsv)" --auth-type ssh-key --username azureuser --ssh-key ~/.ssh/id_rsa
```
@end
