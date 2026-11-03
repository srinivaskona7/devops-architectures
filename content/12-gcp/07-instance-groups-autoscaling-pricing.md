---
title: Managed instance groups, autoscaling and pricing models
minutes: 55
objectives:
  - Run a fleet with managed instance groups, autohealing and rolling updates
  - Configure autoscaling policies and use Spot VMs safely
  - Compare on-demand, sustained use, committed use and Spot pricing
---
Managed instance groups (MIGs) are the building block of scalable VM workloads on Google Cloud, playing the role of Auto Scaling groups on AWS.

@concept Managed instance groups
@plain
A **MIG** keeps a set of identical VMs created from an instance template and recreates any that fail.
@problem
Hand-managed fleets do not heal, scale or roll out changes consistently.
@does
- Zonal MIGs live in one zone. **Regional MIGs** spread VMs over up to three zones and are the production default.
- Features: autohealing from a health check, autoscaling, rolling updates, stateful configuration for disks and IPs, and named ports for load balancers.
- Distribution policy can be even or balanced, and target shape controls zone spreading.
- **AWS equivalent**: Auto Scaling group. Main difference: MIGs are fully separate from load balancer target groups; the backend service refers to the MIG.
@diagram layers
caption: Regional MIG
layers:
  - {label: "Template", nodes: ["Instance template|shop-api-tpl-v1|cp"]}
  - {label: "Regional MIG", nodes: ["Zone b|VMs|vm", "Zone c|VMs|vm", "Zone d|VMs|vm"]}
  - {label: "Front end", nodes: ["Backend service|load balancer|info"]}
@h Create
```bash title="Regional MIG" lab
gcloud compute instance-groups managed create shop-api-mig --region=europe-west1 \
  --template=shop-api-tpl-v1 --size=3 --target-distribution-shape=EVEN
gcloud compute instance-groups managed set-named-ports shop-api-mig --region=europe-west1 --named-ports=http:8080
gcloud compute instance-groups managed list-instances shop-api-mig --region=europe-west1
```
@check
Which MIG type survives a zone failure? || A regional MIG.
@end

@concept Autohealing and rolling updates
@plain
**Autohealing** recreates VMs that fail an application health check. A **rolling update** replaces VMs with a new template gradually.
@problem
A running VM with a hung app looks healthy to the hypervisor, and updates must not take everything down.
@does
- Attach an HTTP health check with an `--initial-delay` long enough for boot.
- Update policy: type `PROACTIVE` or `OPPORTUNISTIC`, `maxSurge`, `maxUnavailable`, and `minimalAction` (replace or restart).
- Roll back by applying the previous template.
- Canary updates set a target size for the new version only.
- **AWS equivalent**: ASG instance refresh and ELB health checks. Main difference: surge and unavailable limits are first-class options and canary versions are supported natively.
@diagram flow
caption: Rolling replacement
numbered: true
nodes:
  - "Surge|create new VMs|info"
  - "Wait healthy|health check passes|ok"
  - "Delete old|within maxUnavailable|warn"
  - "Done|all on new template|app"
@h Roll out a template
```bash title="Rolling update" lab
gcloud compute instance-groups managed set-autohealing shop-api-mig --region=europe-west1 \
  --health-check=shop-hc --initial-delay=120
gcloud compute instance-groups managed rolling-action start-update shop-api-mig --region=europe-west1 \
  --version=template=shop-api-tpl-v2 --max-surge=3 --max-unavailable=0
```
@end

@concept Autoscaling
@plain
The **autoscaler** changes the number of VMs in a MIG based on signals such as CPU, load balancer utilization, or a Cloud Monitoring metric.
@problem
Fixed capacity is either too expensive or too small.
@does
- Policies: `--target-cpu-utilization`, `--target-load-balancing-utilization`, custom metric targets, and schedules.
- `--min-num-replicas` and `--max-num-replicas` bound the size. The `--cool-down-period` sets how long before a new VM's metrics are counted.
- Scale-in controls limit how fast it shrinks.
- Predictive autoscaling forecasts CPU trends and scales ahead of time; check availability.
- **AWS equivalent**: ASG target tracking and scheduled actions. Main difference: the autoscaler is an object attached to the MIG with a combined multi-signal recommendation (largest wins).
@diagram flow
caption: Autoscaler loop
nodes:
  - "Metric|CPU or LB utilization|info"
  - "Autoscaler|computes size|cp"
  - "MIG|resize|app"
  - "New VMs|after cool-down|vm"
@h Configure
```bash title="Autoscaler" lab
gcloud compute instance-groups managed set-autoscaling shop-api-mig --region=europe-west1 \
  --min-num-replicas=3 --max-num-replicas=12 --target-cpu-utilization=0.6 --cool-down-period=90
gcloud compute instance-groups managed describe shop-api-mig --region=europe-west1 --format="yaml(autoscaler,status)"
```
@check
If CPU and load balancer signals disagree, which size is used? || The larger recommendation.
@end

@concept Spot VMs
@plain
**Spot VMs** use spare capacity at a large discount and can be preempted at any time with a short warning.
@problem
Batch jobs, CI workers and stateless tiers do not need to pay full price.
@does
- Set `--provisioning-model=SPOT` and `--instance-termination-action=STOP` or `DELETE`.
- Preemption gives roughly 30 seconds notice; handle the ACPI signal or the metadata `preempted` flag.
- Spot has no maximum runtime. The older preemptible VMs capped at 24 hours.
- Discount varies by machine type; check the current price list. Not covered by an SLA.
- Spot nodes are also available in GKE node pools.
- **AWS equivalent**: Spot Instances. Main difference: there is no bidding. The price is a fixed discount that changes rarely.
@diagram flow
caption: Spot lifecycle
nodes:
  - "Spot VM|discounted|vm"
  - "Capacity needed|Google reclaims|warn"
  - "Notice|about 30 seconds|bad"
  - "Replaced by MIG|if recreated|ok"
@h Spot template
```bash title="Spot template" lab
gcloud compute instance-templates create shop-batch-spot --machine-type=e2-standard-4 \
  --provisioning-model=SPOT --instance-termination-action=DELETE --region=europe-west1 --no-address \
  --subnet=shop-ew1
```
:::warn
Never run state you cannot lose on Spot VMs without checkpoints.
:::
@end

@concept Sustained use discounts and committed use discounts
@plain
**Sustained use discounts (SUD)** apply automatically to some machine families for long monthly usage. **Committed use discounts (CUD)** give a lower price for a one or three year commitment.
@problem
On-demand price is the highest price. Steady workloads should pay less.
@does
- Resource-based CUDs commit to vCPU and memory in a region. **Flexible CUDs** commit to a spend amount across eligible machine families. Check the current docs for which products and families qualify.
- SUD applies to certain families such as N1 and N2 and is not applied with CUD on the same usage. E2 and newer series have no SUD.
- Commitments are billed whether used or not and cannot be cancelled.
- **AWS equivalent**: Savings Plans and Reserved Instances. Main difference: SUD is automatic and needs no purchase.
@diagram cmp
caption: Discount choices
cards:
  - {h: "On-demand", kind: warn, items: ["Highest price", "No commitment"]}
  - {h: "SUD", kind: info, items: ["Automatic", "Only certain families"]}
  - {h: "CUD", kind: ok, items: ["1 or 3 year", "Resource or spend based"]}
  - {h: "Spot", kind: bad, items: ["Largest discount", "Can be preempted"]}
@h Buy and list
```bash title="Commitments" lab
gcloud compute commitments create shop-cud-3y --region=europe-west1 --plan=36-month \
  --resources=vcpu=16,memory=64GB --type=GENERAL_PURPOSE_N2
gcloud compute commitments list --format="table(name,region,plan,status,endTimestamp)"
```
@check
Which discount needs no action from you? || Sustained use discounts, for eligible families.
@end

@concept Health checks, instance schedules and maintenance
@plain
Compute Engine can live-migrate VMs during host maintenance, restart them after crashes, and start or stop them on a schedule.
@problem
Maintenance events and idle development VMs affect availability and cost.
@does
- `--maintenance-policy=MIGRATE` is the default for standard VMs; GPU and Spot VMs use `TERMINATE`.
- `--restart-on-failure` restarts the VM when it crashes.
- **Instance schedules** are resource policies that start and stop VMs at set times, ideal for dev environments.
- **AWS equivalent**: Instance Scheduler solution and auto recovery. Main difference: live migration keeps most maintenance invisible to the VM.
@diagram flow
caption: Scheduled development VMs
nodes:
  - "Schedule policy|08:00 start, 20:00 stop|cp"
  - "VM with policy|attached|vm"
  - "Weekday cost|about half|ok"
@h Create a schedule
```bash title="Instance schedule" lab
gcloud compute resource-policies create instance-schedule dev-hours --region=europe-west1 \
  --vm-start-schedule="0 8 * * 1-5" --vm-stop-schedule="0 20 * * 1-5" --timezone="Asia/Kolkata"
gcloud compute instances add-resource-policies shop-vm-1 --zone=europe-west1-b --resource-policies=dev-hours
```
:::note
The service agent of Compute Engine needs permission to start and stop VMs. See the docs.
:::
@end
