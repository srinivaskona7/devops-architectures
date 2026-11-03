---
title: Rightsizing, Spot and efficient compute
minutes: 50
objectives:
  - Rightsize EC2, EKS pods and databases using measured utilisation
  - Run stateless workloads on Spot safely with diversification and interruption handling
  - Use Graviton, gp3 and storage choices to reduce unit cost
---
The cheapest resource is the one you do not run. Rightsizing removes waste first; then Spot and efficient hardware lower the price of what remains.

@concept Rightsizing EC2 and databases
@plain
Rightsizing matches instance size to measured usage. Many instances run at under 20 percent CPU.
@problem
Sizes chosen at launch "to be safe" persist for years.
@does
- **AWS Compute Optimizer** recommends instance types for EC2, EBS volumes, Lambda, ECS on Fargate and Auto Scaling groups using at least 30 hours of metrics (extended lookback is available).
- **Cost Explorer rightsizing** lists idle and underused instances.
- For RDS, use Performance Insights and CloudWatch: CPU, memory (FreeableMemory), connections, IOPS.
- Memory metrics for EC2 need the CloudWatch agent; without it, recommendations ignore memory.
- Change one step at a time and compare p99 latency before and after.
@diagram flow
caption: Safe rightsizing loop
numbered: true
nodes:
  - "Measure|30 to 90 days|info"
  - "Recommend|Compute Optimizer|app"
  - "Change one size|off-peak|warn"
  - "Verify SLOs|latency and errors|ok"
@h Recommendations
```bash title="Underprovisioned and overprovisioned EC2" lab
aws compute-optimizer get-ec2-instance-recommendations \
  --query 'instanceRecommendations[?finding==`OVER_PROVISIONED`].[instanceArn,currentInstanceType,recommendationOptions[0].instanceType]' --output table
```
@check
Why install the CloudWatch agent for rightsizing? || EC2 does not report memory by default, so recommendations without it ignore memory use.
@end

@concept Rightsizing Kubernetes requests
@plain
Pod requests drive node count. Inflated requests waste nodes; low requests cause throttling and eviction.
@problem
Teams copy YAML with requests of 1 CPU and 2 GiB, then use 50m and 300 MiB.
@does
- Measure real usage with Prometheus or Container Insights (p95 CPU, max memory over 2 weeks).
- **Vertical Pod Autoscaler** in recommendation mode (`updateMode: "Off"`) suggests values without restarting pods.
- **Goldilocks** shows VPA recommendations per namespace.
- Set CPU request near typical usage; avoid CPU limits unless needed (they throttle); set memory limit equal to request.
- Re-check after load changes. Cluster-wide, compare requested versus used CPU: high gaps mean waste.
@diagram cmp
caption: Request mistakes
cards:
  - {h: "Too high", kind: warn, items: ["More nodes", "Low utilisation"]}
  - {h: "Too low", kind: bad, items: ["CPU throttling", "OOM kills"]}
  - {h: "Just right", kind: ok, items: ["p95 usage plus buffer", "Reviewed regularly"]}
@h VPA in recommend-only mode
```yaml title="VPA that only recommends"
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: orders
  namespace: shop
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: orders
  updatePolicy:
    updateMode: "Off"
```
```bash title="Read recommendations" nocheck
kubectl -n shop get vpa orders -o jsonpath='{.status.recommendation.containerRecommendations}'
kubectl top pods -n shop --containers
```
@check
What does updateMode Off do? || It computes recommendations without changing running pods.
@end

@concept Spot instances
@plain
Spot instances use spare EC2 capacity at a large discount, but AWS can reclaim them with two minutes' notice.
@problem
Stateless workers do not need guaranteed capacity, yet are billed at on-demand prices.
@does
- Good fits: stateless web replicas (with spread), batch jobs, CI runners, data processing, dev and test.
- Bad fits: databases, single replica services, long jobs without checkpointing.
- Diversify: many instance types, sizes and AZs; Spot placement score helps choose.
- Handle interruption: draining on notice, PDBs, replicas in several pools, checkpoints, SQS for work.
- Spot price is stable and no longer needs bidding; set only a max price if needed.
@diagram flow
caption: Safe Spot architecture
nodes:
  - "On-demand baseline|minimum capacity|cp"
  - "Spot pool|diversified types|info"
  - "Interruption notice|2 minutes|warn"
  - "Graceful drain|replacement launched|ok"
@h Node group on Spot
```yaml title="eksctl Spot managed node group"
apiVersion: eksctl.io/v1alpha5
kind: ClusterConfig
metadata:
  name: shop-prod
  region: us-east-1
managedNodeGroups:
  - name: spot-workers
    spot: true
    instanceTypes: ["m6i.large", "m5.large", "m6a.large", "m7i.large", "m5a.large"]
    minSize: 0
    maxSize: 20
    labels: {lifecycle: spot}
    taints:
      - key: spot
        value: "true"
        effect: NoSchedule
```
```bash title="Check placement scores" nocheck
aws ec2 get-spot-placement-scores --instance-types m6i.large m5.large m6a.large \
  --target-capacity 20 --region-names us-east-1 --single-availability-zone false
```
@check
How many minutes of notice does a Spot interruption give? || Two minutes.
@end

@concept Graviton, storage and other unit-cost levers
@plain
Cheaper hardware and better storage choices lower cost per unit of work without reducing capacity.
@problem
Older generations and over-provisioned storage silently cost more.
@does
- **Graviton** (arm64) offers better price-performance; many images are multi-arch. Build with `docker buildx --platform linux/amd64,linux/arm64` and let Karpenter pick.
- Prefer current generation instances (m7, c7 families), which are usually cheaper per unit.
- **gp3** is cheaper than gp2 and lets you tune IOPS and throughput; migrate volumes online with `modify-volume`.
- Delete unattached volumes, old snapshots, and unused AMIs.
- S3 Intelligent-Tiering and lifecycle rules reduce storage costs; delete incomplete multipart uploads.
- For Lambda and Fargate, ARM also reduces price.
@diagram flow
caption: Hardware upgrade path
nodes:
  - "Multi-arch image|amd64 and arm64|app"
  - "Karpenter allows arm64|NodePool requirement|cp"
  - "Run both|compare cost and latency|warn"
  - "Shift traffic|saves per vCPU|ok"
@h Convert gp2 to gp3
```bash title="List gp2 volumes and convert one" lab
aws ec2 describe-volumes --filters Name=volume-type,Values=gp2 --query 'Volumes[].[VolumeId,Size]' --output table
# aws ec2 modify-volume --volume-id vol-0123456789abcdef0 --volume-type gp3
```
```bash title="Multi-arch build" nocheck
docker buildx build --platform linux/amd64,linux/arm64 -t 111122223333.dkr.ecr.us-east-1.amazonaws.com/shop/web:1.4.3 --push .
```
@check
Why build multi-architecture images? || They let the same image run on cheaper Graviton nodes as well as x86.
@end

@concept Scheduling off-hours and scaling to zero
@plain
Development and test environments rarely need to run at night or on weekends.
@problem
A non-production cluster running 24/7 costs about three times what is needed.
@does
- Scale Karpenter-managed workloads to zero replicas (KEDA cron, CronJobs patching deployments); nodes drain and consolidate away.
- For managed node groups, schedule desired size to 0 with Auto Scaling scheduled actions.
- Stop RDS instances (up to seven days) or use Aurora Serverless v2 with low minimum; schedule with EventBridge Scheduler.
- AWS Instance Scheduler solution automates start and stop by tag.
- Keep the EKS control plane (fixed hourly cost) or use shared dev clusters per team.
@diagram flow
caption: Office-hours schedule
nodes:
  - "19:00 scale down|workloads to zero|warn"
  - "Karpenter|removes empty nodes|info"
  - "Night|minimum cost|ok"
  - "08:30 scale up|before the team arrives|app"
@h Scheduled node group scaling
```bash title="Scheduled actions for a dev node group ASG" nocheck
aws autoscaling put-scheduled-update-group-action --auto-scaling-group-name eks-dev-general \
  --scheduled-action-name night-off --recurrence "30 13 * * 1-5" --min-size 0 --desired-capacity 0
aws autoscaling put-scheduled-update-group-action --auto-scaling-group-name eks-dev-general \
  --scheduled-action-name morning-on --recurrence "0 3 * * 1-5" --min-size 2 --desired-capacity 2
```
@check
What cost remains when a dev cluster is scaled to zero nodes? || The EKS control plane fee, storage and other fixed resources.
@end
