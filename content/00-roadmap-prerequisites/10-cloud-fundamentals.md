---
title: Cloud fundamentals
minutes: 40
objectives:
  - Explain the shared responsibility model and what you must still secure
  - Describe regions and availability zones and compute availability for redundant designs
  - Compare on demand, reserved and spot pricing and estimate a simple bill
---
Examples use AWS names. Azure, Google Cloud and SAP BTP have equivalents. Prices and limits change, so every number marked as an example must be checked against the current provider pricing page.

@concept What cloud computing is
@plain
Cloud computing is renting computing resources over the network, paying for what you use, and getting them in minutes through an API.
@problem
Buying servers takes weeks, must be sized for the peak, and sits idle the rest of the time. Teams wait on hardware instead of shipping.
@does
- Five traits: on demand self service, broad network access, pooled resources, rapid elasticity, measured service.
- Service models: IaaS (virtual machines, networks), PaaS (managed runtime or database), SaaS (finished software).
- Everything is an API call, which is why infrastructure as code works.
@diagram layers
caption: Who manages what in each model
layers:
  - {label: "You manage most", nodes: ["IaaS|EC2, VPC, EBS: you patch the OS|app"]}
  - {label: "Shared", nodes: ["PaaS|RDS, Elastic Beanstalk, Kyma runtime: you manage app and data|env"]}
  - {label: "Provider manages most", nodes: ["SaaS|email, CRM: you manage users and data|ok"]}
@h Everything is an API
```bash title="Create and delete a resource with the AWS CLI" nocheck
aws sts get-caller-identity                               # who am I
aws s3api create-bucket --bucket my-unique-lab-bucket-12345 --region us-east-1
aws s3 ls
aws s3api delete-bucket --bucket my-unique-lab-bucket-12345    # always clean up
```
@check
Which model leaves OS patching to you? || IaaS.
@end

@concept The shared responsibility model
@plain
The provider secures the cloud itself: buildings, hardware, hypervisors. You secure what you put in it: data, identities, configuration and, for virtual machines, the operating system.
@problem
Most cloud breaches come from customer configuration, such as a public bucket or an over-permissive role, not from the provider being hacked. Assuming the provider handles it is the root mistake.
@does
- The line moves with the service. For a managed database the provider patches the engine, but you still own users, network rules, encryption choices and backups you rely on.
- For Kubernetes services (EKS, Kyma) the provider runs the control plane; you own workloads, RBAC, network policies and images.
@diagram cmp
caption: Typical split of duties
cards:
  - {h: "Provider", kind: ok, items: ["Data centers and power", "Hardware and hypervisor", "Managed service software"]}
  - {h: "You", kind: warn, items: ["IAM and access keys", "Network and security group rules", "Data classification and encryption", "Guest OS and application patches"]}
@h Spot a mistake
```bash title="Find public S3 exposure" nocheck
aws s3api get-public-access-block --bucket my-bucket
aws iam list-users --query 'Users[].UserName'
aws iam generate-credential-report >/dev/null && aws iam get-credential-report --query Content --output text | base64 -d | head -3
```
:::warn
Turn on account level S3 Block Public Access and require MFA on the root user and all humans.
:::
@end

@concept Regions and availability zones
@plain
A **region** is a geographic area such as Mumbai (ap-south-1). Each region has several **availability zones** (AZs), which are separate data centers with independent power and networking, connected by fast links.
@problem
One data center can lose power, flood or fail a network device. Spreading across zones keeps the service alive; spreading across regions protects against a regional event and serves users nearby.
@does
- Resources like subnets live in one AZ; a region-level service (S3, DynamoDB) spans AZs for you.
- Cross-AZ traffic costs money and adds a little latency; cross-region more of both.
- Data residency laws may fix the region you can use.
@diagram layers
caption: Region, zones and subnets
layers:
  - {label: "Region ap-south-1", nodes: ["VPC 10.0.0.0/16|spans all zones|env"]}
  - {label: "Zones", nodes: ["Zone a|subnet 10.0.1.0/24|app", "Zone b|subnet 10.0.2.0/24|app", "Zone c|subnet 10.0.3.0/24|app"]}
@h List them
```bash title="Regions and zones" nocheck
aws ec2 describe-regions --query 'Regions[].RegionName' --output text
aws ec2 describe-availability-zones --region ap-south-1 --query 'AvailabilityZones[].ZoneName'
kubectl get nodes -L topology.kubernetes.io/zone       # which zone each node is in
```
@check
Why spread Kubernetes nodes over three AZs? || A zone failure then removes only about a third of capacity and pods can be rescheduled.
@end

@concept Availability, redundancy and the math
@plain
Availability is the share of time a service works. Redundancy raises it, but only when failures are independent and failover works.
@problem
Teams promise "five nines" without computing what their design can deliver.
@does
- A component with 99.9 percent availability is down about 43.2 minutes per 30 day month (0.001 times 43200).
- Components in **series** multiply: two 99.9 percent parts in a chain give 0.999 x 0.999 = 0.998001, about 1050 minutes of downtime a year.
- Components in **parallel** fail only if all fail: 1 minus (0.001 x 0.001) = 0.999999, about half a minute a year, assuming perfect failover and independence.
- Real systems fall short because of shared dependencies, slow failover and human error.
@diagram cmp
caption: Series versus parallel (computed below)
cards:
  - {h: "Series, A then B", kind: bad, items: ["0.999 x 0.999 = 0.998001", "About 1050 minutes down per year"]}
  - {h: "Parallel, A or B", kind: ok, items: ["1 - 0.001 x 0.001 = 0.999999", "About 0.53 minutes down per year"]}
@h Calculate
```python title="Availability calculator" lab
a = 0.999
series = a * a
parallel = 1 - (1 - a) ** 2
year = 365 * 24 * 60
print("series  ", series, round((1 - series) * year, 1), "min/yr")
print("parallel", parallel, round((1 - parallel) * year, 2), "min/yr")
for target in (0.99, 0.999, 0.9999):
    print(target, "allows", round((1 - target) * 30 * 24 * 60, 1), "min per 30 days")
```
@check
Two 99.95 percent services are called in series. What is the availability? || 0.9995 x 0.9995 = 0.99900025, about 99.9 percent.
@end

@concept Pricing models
@plain
You pay per second or hour for compute, per gigabyte per month for storage, and per gigabyte for data leaving. Commitment and flexibility change the rate.
@problem
Running everything on demand is the most flexible and the most expensive. Overcommitting wastes money on capacity you do not use.
@does
- **On demand**: no commitment, full price.
- **Savings plans and reserved**: commit to a spend or instance family for one or three years for a discount, often a large one (check current rates).
- **Spot**: spare capacity at a deep discount, but it can be reclaimed with short notice. Suits stateless, restartable work.
- Example arithmetic with an invented rate of $0.10 per hour: on demand for 730 hours is $73.00; with an assumed 40 percent discount it is $43.80; with an assumed 70 percent spot discount it is $21.90.
@diagram flow
caption: Match commitment to how predictable the load is
nodes:
  - "Steady baseline|always on|ok"
  - "Savings plan or reserved|1 to 3 year commitment|info"
  - "Variable load|on demand|app"
  - "Batch, CI, stateless|spot instances|warn"
@choose Pricing choice
On demand | new or unpredictable workloads | steady 24x7 load
Savings plan or reserved | the stable baseline you will run for a year | a workload you may delete soon
Spot | fault tolerant, restartable work such as CI runners | databases and single replicas
@h Estimate
```python title="Monthly cost estimate" lab
hours = 730
rate = 0.10                      # example only, look up the real price
for name, discount in [("on demand", 0), ("savings plan", 0.40), ("spot", 0.70)]:
    print(f"{name:13s} ${hours * rate * (1 - discount):7.2f}")
print("100 nodes, on demand:", hours * rate * 100)
```
@end

@concept Hidden costs and cost control
@plain
Compute is only part of the bill. Data transfer, idle resources, NAT gateways, load balancers and storage snapshots add up quietly.
@problem
A forgotten cluster or a chatty cross-AZ service can double a bill before anyone looks.
@does
- Data in is mostly free, data out to the internet and across AZs or regions costs per gigabyte.
- NAT gateways charge per hour plus per gigabyte processed.
- Object storage: 1000 GB at an example $0.023 per GB month is $23.00 a month, $276.00 a year. Lifecycle rules move cold data to cheaper classes.
- Tags (team, environment, owner) make costs attributable. Budgets and alerts catch surprises early.
@diagram cmp
caption: Where surprises come from
cards:
  - {h: "Idle", kind: warn, items: ["Stopped VMs still pay for disks", "Unattached volumes and IPs"]}
  - {h: "Transfer", kind: bad, items: ["Cross-AZ chatter", "NAT gateway data processing"]}
  - {h: "Sprawl", kind: info, items: ["Old snapshots", "Dev clusters left running"]}
@h Guard rails
```bash title="Find waste" nocheck
aws ec2 describe-volumes --filters Name=status,Values=available --query 'Volumes[].[VolumeId,Size]'
aws ec2 describe-addresses --query 'Addresses[?AssociationId==null].PublicIp'
aws budgets describe-budgets --account-id 123456789012
```
:::tip
Tag every resource on creation and enforce it with policy. Untagged spend is nobody's spend.
:::
@check
Name two charges that do not depend on CPU use. || Examples are NAT gateway hourly and per GB fees, and cross-AZ data transfer.
@end

@concept Choosing services and avoiding lock in
@plain
Managed services trade control for time saved. The decision should be deliberate: what do you gain, and what is the cost of leaving?
@problem
Running your own database on VMs gives control but makes you the on-call team for patches and backups. Using proprietary features everywhere makes a later move expensive.
@does
- Prefer managed for undifferentiated work (databases, queues, load balancers) unless a requirement forbids it.
- Portability comes from standard interfaces: Kubernetes, PostgreSQL, S3-compatible APIs, Terraform modules.
- Document the exit path for each critical dependency; do not pay to be portable in places where it brings no value.
@diagram flow
caption: A simple decision path
nodes:
  - "Need a capability|database, queue, cache|plain"
  - "Managed service exists|and meets compliance|info"
  - "Use managed|keep config in code|ok"
  - "Else self-host|own patches and backups|warn"
@h Record the decision
```yaml title="decision-record.yaml"
decision: Use managed PostgreSQL for the orders service
options: [self-hosted on EC2, RDS PostgreSQL, Aurora]
chosen: RDS PostgreSQL
reasons:
  - automated backups and point in time recovery
  - standard engine keeps exit possible
exit_path: pg_dump and restore to any PostgreSQL 16 host
review_date: 2027-04-01
```
@check
What keeps an RDS PostgreSQL choice portable? || It uses the standard PostgreSQL engine, so a dump and restore moves it elsewhere.
@end
