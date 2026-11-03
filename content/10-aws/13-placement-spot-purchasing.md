---
title: Placement groups, Spot and purchasing options
minutes: 50
objectives:
  - Choose between cluster, spread and partition placement groups
  - Run fault-tolerant workloads on Spot safely and handle interruptions
  - Combine On-Demand, Savings Plans and Reserved Instances to cut cost
---
Where instances sit and how you pay for them both change cost and resilience. Spot and commitments together can cut compute spend considerably, but only with careful design.

@concept Placement groups
@plain
A **placement group** influences how EC2 places instances on the underlying hardware.
@problem
Tightly coupled workloads need low latency between nodes; critical replicas need to avoid sharing hardware.
@does
- **Cluster**: instances packed close in one AZ for low latency and high throughput between them. Best for HPC; increases correlated failure risk.
- **Spread**: each instance on distinct hardware; limited number per AZ (check current quota). Good for a few critical instances.
- **Partition**: instances split into partitions that do not share hardware; fits Kafka, Cassandra, HDFS.
- Launch all cluster members together and use the same instance type to reduce capacity errors.
@diagram cmp
caption: Placement strategies
cards:
  - {h: "Cluster", kind: info, items: ["Lowest latency", "One AZ", "Shared failure domain"]}
  - {h: "Spread", kind: ok, items: ["Distinct hardware", "Few instances", "Survives host loss"]}
  - {h: "Partition", kind: app, items: ["Groups on separate racks", "Large distributed stores"]}
@h Create
```bash title="Placement groups" lab
aws ec2 create-placement-group --group-name hpc --strategy cluster
aws ec2 create-placement-group --group-name kafka --strategy partition --partition-count 3
aws ec2 run-instances --image-id ami-0123456789abcdef0 --instance-type c7i.8xlarge --count 4 --placement GroupName=hpc
```
:::note
In Kubernetes, topology spread constraints on `topology.kubernetes.io/zone` and `kubernetes.io/hostname` achieve spread at the pod level.
:::
@end

@concept On-Demand and capacity reservations
@plain
**On-Demand** is pay-per-second with no commitment. **Capacity Reservations** guarantee that capacity exists in an AZ, whether or not you run instances.
@problem
In rare capacity shortages, a launch can fail with `InsufficientInstanceCapacity`, which is unacceptable for disaster-recovery or event-day scaling.
@does
- On-Demand is the baseline price against which discounts are calculated.
- Capacity Reservations are billed at On-Demand rate while active, and are matched by instance attributes. Savings Plans and Regional Reserved Instances discount their price.
- **On-Demand Capacity Reservations for ML (Capacity Blocks)** exist for scheduled GPU capacity; check availability.
- For resilience, diversify instance types and AZs rather than relying on one type.
@diagram flow
caption: Guaranteeing capacity
nodes:
  - "Create reservation|AZ, type, count|cp"
  - "Instances launch into it|automatic matching|app"
  - "Billed whether used or not|On-Demand rate|warn"
  - "Cover with Savings Plan|discount|ok"
@h Create a reservation
```bash title="Reserve capacity" lab
aws ec2 create-capacity-reservation --instance-type m7g.large --instance-platform Linux/UNIX \
  --availability-zone eu-west-1a --instance-count 3 --instance-match-criteria open
aws ec2 describe-capacity-reservations --query 'CapacityReservations[].[CapacityReservationId,AvailableInstanceCount,State]'
```
@check
What does a Capacity Reservation guarantee that a Savings Plan does not? || That the capacity is available in a given AZ; a Savings Plan is only a billing discount.
@end

@concept Spot Instances
@plain
**Spot** uses spare EC2 capacity at a large discount, with the catch that AWS can take it back with a two-minute warning.
@problem
Steady On-Demand pricing is expensive for stateless, batch and CI workloads that could tolerate interruption.
@does
- Price is set by AWS (no bidding); you can set a maximum price but usually leave it at the On-Demand price.
- Interruption notice appears at `spot/instance-action` in the metadata and as an EventBridge event, about two minutes before reclaim. Rebalance recommendations may arrive earlier.
- **Diversify** across many instance types and AZs, and use the `price-capacity-optimized` allocation strategy.
- Good fits: stateless web tiers behind a load balancer, workers, CI runners, batch, stream processors with checkpoints. Poor fits: single-instance databases, long non-checkpointed jobs.
@diagram seq
caption: Spot interruption handling
actors: ["AWS EC2|capacity manager|cp", "Instance|metadata and agent|app", "Orchestrator|ASG or Karpenter|env"]
steps:
  - "0>1: interruption notice, about 2 minutes | bad"
  - "1>2: drain node, deregister from load balancer | req"
  - "2>1: pods rescheduled elsewhere | resp"
  - "0>1: instance terminated | bad"
  - "note 1..2: replacement launched from another pool"
@h ASG with mixed instances
```hcl title="spot-asg.tf"
resource "aws_autoscaling_group" "workers" {
  name                = "workers"
  min_size            = 2
  max_size            = 20
  vpc_zone_identifier = var.private_subnet_ids

  mixed_instances_policy {
    instances_distribution {
      on_demand_base_capacity                  = 2
      on_demand_percentage_above_base_capacity = 0
      spot_allocation_strategy                 = "price-capacity-optimized"
    }
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.worker.id
        version            = "$Latest"
      }
      override { instance_type = "m6i.large" }
      override { instance_type = "m6a.large" }
      override { instance_type = "m7g.large" }
      override { instance_type = "c6i.xlarge" }
    }
  }
}
```
```bash title="Watch for interruption" lab
curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/spot/instance-action
aws ec2 describe-spot-price-history --instance-types m7g.large --product-descriptions "Linux/UNIX" --max-items 5
```
@end

@concept Savings Plans and Reserved Instances
@plain
**Savings Plans** are a commitment to spend a fixed amount per hour for one or three years in return for a lower rate. **Reserved Instances** commit to specific instance attributes.
@problem
Always-on baseline capacity paid at On-Demand price is the largest avoidable cost.
@does
- **Compute Savings Plans**: apply to EC2 any family, Region, OS, tenancy, plus Fargate and Lambda. Most flexible.
- **EC2 Instance Savings Plans**: tied to a family in a Region, deeper discount.
- Payment options: all upfront, partial, no upfront. Terms: one or three years. Check the current discount ranges.
- Reserved Instances: Standard (can be sold on a marketplace) and Convertible; also needed for RDS and other services where Savings Plans do not apply.
- Commit to the stable floor of usage, not the peak; the commitment is owed even if you use less.
- Plans are purchased in the management account and shared across the organization by default.
@diagram layers
caption: Layer the purchase options
layers:
  - {label: "Spiky", nodes: ["On-Demand|peak above everything|warn"]}
  - {label: "Variable fault-tolerant", nodes: ["Spot|stateless and batch|app"]}
  - {label: "Stable baseline", nodes: ["Savings Plans|committed hourly spend|ok"]}
@h Explore
```bash title="Cost Explorer recommendations" lab
aws ce get-savings-plans-purchase-recommendation --savings-plans-type COMPUTE_SP \
  --term-in-years ONE_YEAR --payment-option NO_UPFRONT --lookback-period-in-days THIRTY_DAYS \
  --query 'SavingsPlansPurchaseRecommendation.SavingsPlansPurchaseRecommendationSummary'
aws ce get-savings-plans-coverage --time-period Start=2026-10-01,End=2026-10-31
```
@choose Purchasing option
On-Demand | unknown or short-lived load | steady 24/7 baseline
Spot | stateless, interruptible work | single stateful instance
Compute Savings Plan | steady baseline with changing instance types | usage you may stop within the term
EC2 Instance Savings Plan | long-lived known family | you plan to move to another family soon
Capacity Reservation | must-have capacity in an AZ | flexible workloads that can retry elsewhere
@check
Should you buy a Savings Plan for your peak hourly spend? || No. Commit to the steady minimum; cover peaks with On-Demand or Spot.
@end

@concept Tenancy, Dedicated Hosts and licences
@plain
By default instances share physical hosts with other customers (shared tenancy). Dedicated options give you hardware not shared.
@problem
Some software licences are per socket or per core, and some compliance regimes demand single-tenant hardware.
@does
- **Dedicated Instances**: run on hardware dedicated to your account; AWS manages placement.
- **Dedicated Hosts**: a whole physical server you control, giving visibility of sockets and cores for BYOL.
- **License Manager** tracks licence counts across accounts.
- Shared tenancy on Nitro is strongly isolated; dedicated tenancy is rarely needed otherwise.
@diagram cmp
caption: Tenancy
cards:
  - {h: "Shared", kind: ok, items: ["Default", "Cheapest"]}
  - {h: "Dedicated Instance", kind: info, items: ["Your hardware only", "AWS picks the host"]}
  - {h: "Dedicated Host", kind: warn, items: ["You see sockets and cores", "BYOL licensing"]}
@end
