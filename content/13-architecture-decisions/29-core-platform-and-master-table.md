---
title: Core services 46 to 50, platform operations and master table
minutes: 60
objectives:
  - Compare fleet tools, API management, cost tools, image builders and quotas
  - State when to choose each service
  - List the limits to verify in the current docs
---
These services keep a platform patched, governed, affordable and within limits. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
Patch, publish, measure, build and check limits. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Platform operations
layers:
  - {label: "Services on this page", nodes: ["Configuration and fleet management|Systems Manager|app", "API management|API Gateway|info", "Cost management|Cost Explorer and Budgets|env", "Image builders|EC2 Image Builder|ok", "Service quotas and limits|Service Quotas|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 46 | Configuration and fleet management | Systems Manager | Azure Arc and Automanage | VM Manager |
| 47 | API management | API Gateway | API Management | API Gateway or Apigee |
| 48 | Cost management | Cost Explorer and Budgets | Cost Management | Billing reports and Budgets |
| 49 | Image builders | EC2 Image Builder | Azure Image Builder | Packer on Compute Engine or Image Builder |
| 50 | Service quotas and limits | Service Quotas | Quotas and limits | Quotas |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 46. Configuration and fleet management
@plain
Tools to patch, inventory and run commands across many machines without logging in to each.
@problem
Manual patching of hundreds of servers is slow and inconsistent.
@does
- **Names**: AWS Systems Manager; Azure Azure Arc and Automanage; GCP VM Manager.
- **What it is**: Provides agents, patch schedules, inventory, remote commands and secure sessions.
- **Choose it when**: Patch compliance; Managing hybrid servers; Session access without open SSH.
- **Check in the current docs**: Agents must be installed and permitted; Product branding changes, so check the current docs; Patch windows need testing.
@diagram cmp
caption: Configuration and fleet management on the three clouds
cards:
  - {h: "Systems Manager", kind: warn, items: ["Patch Manager, Session Manager, Run Command"]}
  - {h: "Azure Arc and Automanage", kind: info, items: ["Azure Arc, Update Manager, Automanage"]}
  - {h: "VM Manager", kind: ok, items: ["OS patch management, OS inventory"]}
@h Example
A monthly patch window patches the test group first, then production a week later.
@h CLI on each cloud
```bash title="AWS CLI, Configuration and fleet management" nocheck
aws ssm send-command --document-name AWS-RunShellScript --targets Key=tag:env,Values=dev --parameters commands='uptime'
```
```bash title="Azure CLI, Configuration and fleet management" nocheck
az connectedmachine list --resource-group rg-demo
```
```bash title="gcloud, Configuration and fleet management" nocheck
gcloud compute os-config patch-deployments list
```
@check
Why patch test first? || To catch breakage before production.
@end

@concept 47. API management
@plain
A front door for APIs that handles authentication, throttling, versioning and analytics.
@problem
Each service reimplementing keys, quotas and monitoring is wasteful and inconsistent.
@does
- **Names**: AWS API Gateway; Azure API Management; GCP API Gateway or Apigee.
- **What it is**: Publishes routes, validates tokens, applies rate limits and transformations, and offers developer portals in fuller products.
- **Choose it when**: Public or partner APIs; Throttling and usage plans; Central policy enforcement.
- **Check in the current docs**: Payload size and timeout limits apply, so check the current docs; Full lifecycle products such as Apigee and API Management cost more; Gateway can become a bottleneck or single point of failure.
@diagram cmp
caption: API management on the three clouds
cards:
  - {h: "API Gateway", kind: warn, items: ["REST, HTTP and WebSocket APIs, usage plans"]}
  - {h: "API Management", kind: info, items: ["API Management tiers, policies"]}
  - {h: "API Gateway or Apigee", kind: ok, items: ["API Gateway for serverless, Apigee for full management"]}
@h Example
A partner API enforces 100 requests per minute per key and logs usage per partner.
@h CLI on each cloud
```bash title="AWS CLI, API management" nocheck
aws apigatewayv2 create-api --name shop-api --protocol-type HTTP
```
```bash title="Azure CLI, API management" nocheck
az apim create --resource-group rg-demo --name demo-apim-123 --publisher-email ops@example.com --publisher-name Demo --sku-name Consumption
```
```bash title="gcloud, API management" nocheck
gcloud api-gateway apis create shop-api
```
@check
What does throttling protect? || The backend from overload by clients.
@end

@concept 48. Cost management
@plain
Tools that show where money goes and warn when spending exceeds plans.
@problem
Cloud bills surprise teams that cannot see cost by owner.
@does
- **Names**: AWS Cost Explorer and Budgets; Azure Cost Management; GCP Billing reports and Budgets.
- **What it is**: Breaks costs down by tag or label, forecasts, sets budgets and exports detailed usage.
- **Choose it when**: Every account from day one; Showback and chargeback; Anomaly detection.
- **Check in the current docs**: Tags and labels only help if enforced; Data can lag by hours or a day; Commitment discounts need analysis, so check the current docs.
@diagram cmp
caption: Cost management on the three clouds
cards:
  - {h: "Cost Explorer and Budgets", kind: warn, items: ["Budgets, Cost Explorer, CUR exports"]}
  - {h: "Cost Management", kind: info, items: ["Budgets, cost analysis, exports"]}
  - {h: "Billing reports and Budgets", kind: ok, items: ["Budgets, billing export to BigQuery"]}
@h Example
A budget of 1000 per month alerts at 80 percent, which is 800, and at 100 percent.
@h CLI on each cloud
```bash title="AWS CLI, Cost management" nocheck
aws budgets describe-budgets --account-id 111122223333
```
```bash title="Azure CLI, Cost management" nocheck
az consumption budget list
```
```bash title="gcloud, Cost management" nocheck
gcloud billing budgets list --billing-account=000000-AAAAAA-BBBBBB
```
@check
Why enforce tags? || Cost can then be assigned to owners.
@end

@concept 49. Image builders
@plain
Pipelines that create hardened, patched machine images ready to launch.
@problem
Installing software at boot is slow and drifts between servers.
@does
- **Names**: AWS EC2 Image Builder; Azure Azure Image Builder; GCP Packer on Compute Engine or Image Builder.
- **What it is**: Builds images from a base, runs scripts and tests, and publishes versions.
- **Choose it when**: Immutable infrastructure; Golden images with security baselines; Faster scaling.
- **Check in the current docs**: Image pipelines must be scheduled to pick up patches; Share and replicate images across regions; Packer is a portable choice across clouds.
@diagram cmp
caption: Image builders on the three clouds
cards:
  - {h: "EC2 Image Builder", kind: warn, items: ["Image pipelines, recipes, components"]}
  - {h: "Azure Image Builder", kind: info, items: ["Image templates, Azure Compute Gallery"]}
  - {h: "Packer on Compute Engine or Image Builder", kind: ok, items: ["Packer builders for Compute Engine"]}
@h Example
A weekly pipeline builds a patched image, tests it, and publishes a new version used by the next rollout.
@h CLI on each cloud
```bash title="AWS CLI, Image builders" nocheck
aws imagebuilder list-image-pipelines
```
```bash title="Azure CLI, Image builders" nocheck
az image builder list --resource-group rg-demo
```
```bash title="gcloud, Image builders" nocheck
packer build -var project_id=demo-project gce.pkr.hcl
```
@check
Why rebuild images regularly? || To include current security patches.
@end

@concept 50. Service quotas and limits
@plain
Soft and hard ceilings that clouds place on resources, such as vCPUs or API calls.
@problem
Launches fail at the worst moment when a limit is reached.
@does
- **Names**: AWS Service Quotas; Azure Quotas and limits; GCP Quotas.
- **What it is**: Show current usage, defaults and request increases, and alert near limits.
- **Choose it when**: Before launches and migrations; Capacity planning; Disaster recovery regions.
- **Check in the current docs**: Limits differ per region and need requests in the standby region too; Some limits are hard and cannot be raised; Check the current docs for values.
@diagram cmp
caption: Service quotas and limits on the three clouds
cards:
  - {h: "Service Quotas", kind: warn, items: ["Service Quotas console and CLI"]}
  - {h: "Quotas and limits", kind: info, items: ["Quota blades per subscription and region"]}
  - {h: "Quotas", kind: ok, items: ["Quotas page and Cloud Quotas API"]}
@h Example
Before a failover test the team confirms the standby region has the same vCPU quota as production.
@h CLI on each cloud
```bash title="AWS CLI, Service quotas and limits" nocheck
aws service-quotas list-service-quotas --service-code ec2 --query 'Quotas[0:5].[QuotaName,Value]'
```
```bash title="Azure CLI, Service quotas and limits" nocheck
az vm list-usage --location westeurope --output table
```
```bash title="gcloud, Service quotas and limits" nocheck
gcloud compute regions describe europe-west1 --format='yaml(quotas)'
```
@check
Why check quotas in the DR region? || Failover may need capacity that was never requested there.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Untagged resources that cannot be costed.
- Quotas not raised in the DR region.
- Gateways as single points of failure.
- Always confirm limits, prices and regional availability in the current documentation before committing.
@diagram flow
caption: A safe habit before adopting any service
nodes:
  - "Define need|workload, size, latency|plain"
  - "Map services|three cloud names|info"
  - "Check docs|limits, price, regions|warn"
  - "Prototype|measure on real data|app"
  - "Decide|record in an ADR|ok"
@h Habit as a checklist
```yaml title="service-evaluation.yaml" nocheck
service: Configuration and fleet management
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

@concept Master map of all 50 services
@plain
One table that lists every service in this section with its AWS, Azure and Google Cloud names.
@problem
Translating between clouds by memory is slow and error-prone.
@does
- Use the table to find the equivalent product quickly, then open the matching entry for details.
- Names reflect common usage and may change, so confirm in the current docs.
@diagram layers
caption: The 50 services in families
layers:
  - {label: "Compute and storage", nodes: ["Compute|1 to 5|app", "Storage|6 to 10|env"]}
  - {label: "Data and network", nodes: ["Databases|11 to 15|info", "Networking|16 to 25|cp"]}
  - {label: "Security and observability", nodes: ["Identity and security|26 to 32|warn", "Observability|33 to 36|ok"]}
  - {label: "Integration and platform", nodes: ["Messaging and data|37 to 42|app", "DevOps and platform|43 to 50|plain"]}
@h Master table
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 1 | Virtual machines | EC2 | Virtual Machines | Compute Engine |
| 2 | Autoscaled VM groups | Auto Scaling Groups | VM Scale Sets | Managed Instance Groups |
| 3 | Managed Kubernetes | EKS | AKS | GKE |
| 4 | Serverless containers | Fargate or App Runner | Container Apps | Cloud Run |
| 5 | Functions | Lambda | Functions | Cloud Functions |
| 6 | Object storage | S3 | Blob Storage | Cloud Storage |
| 7 | Block storage | EBS | Managed Disks | Persistent Disk or Hyperdisk |
| 8 | Shared file storage | EFS | Azure Files | Filestore |
| 9 | Archive tiers | S3 Glacier | Blob Archive tier | Cloud Storage Archive class |
| 10 | Backup | AWS Backup | Azure Backup | Backup and DR Service |
| 11 | Managed relational database | RDS | Azure SQL or Flexible Server | Cloud SQL |
| 12 | Cloud-native relational database | Aurora | Azure SQL Hyperscale | AlloyDB |
| 13 | Key-value and document database | DynamoDB | Cosmos DB | Firestore or Bigtable |
| 14 | In-memory cache | ElastiCache | Azure Cache for Redis | Memorystore |
| 15 | Global relational database | Aurora DSQL or Aurora Global Database | Cosmos DB or SQL Hyperscale geo-replicas | Spanner |
| 16 | Virtual network | VPC | VNet | VPC |
| 17 | Layer-7 load balancer | Application Load Balancer | Application Gateway | External Application Load Balancer |
| 18 | Layer-4 load balancer | Network Load Balancer | Load Balancer | Network Load Balancer |
| 19 | DNS | Route 53 | Azure DNS | Cloud DNS |
| 20 | CDN | CloudFront | Front Door or Azure CDN | Cloud CDN |
| 21 | Private connectivity to services | PrivateLink | Private Link | Private Service Connect |
| 22 | Hybrid connectivity | Direct Connect or Site-to-Site VPN | ExpressRoute or VPN Gateway | Cloud Interconnect or Cloud VPN |
| 23 | Hub networking | Transit Gateway | Virtual WAN or hub VNet | Network Connectivity Center |
| 24 | NAT egress | NAT Gateway | NAT Gateway | Cloud NAT |
| 25 | Web firewall and DDoS protection | WAF and Shield | Web Application Firewall and DDoS Protection | Cloud Armor |
| 26 | Identity and access | IAM | Entra ID and Azure RBAC | Cloud IAM |
| 27 | Workload identity | IRSA or EKS Pod Identity | Workload Identity | Workload Identity Federation |
| 28 | Key management | KMS | Key Vault keys | Cloud KMS |
| 29 | Secrets | Secrets Manager | Key Vault secrets | Secret Manager |
| 30 | Threat detection | GuardDuty | Defender for Cloud | Security Command Center |
| 31 | Audit logs | CloudTrail | Activity Log | Cloud Audit Logs |
| 32 | Policy and governance | Organizations SCPs and Config | Azure Policy | Organization Policy |
| 33 | Metrics and alarms | CloudWatch | Azure Monitor | Cloud Monitoring |
| 34 | Logs | CloudWatch Logs | Log Analytics | Cloud Logging |
| 35 | Tracing | X-Ray | Application Insights | Cloud Trace |
| 36 | Managed Prometheus and Grafana | Amazon Managed Service for Prometheus and Managed Grafana | Azure Monitor managed Prometheus and Managed Grafana | Google Cloud Managed Service for Prometheus |
| 37 | Queues | SQS | Queue Storage or Service Bus | Cloud Tasks or Pub/Sub |
| 38 | Publish and subscribe | SNS | Event Grid | Pub/Sub |
| 39 | Streaming | Kinesis or MSK | Event Hubs | Pub/Sub or Managed Service for Apache Kafka |
| 40 | Workflow orchestration | Step Functions | Logic Apps or Durable Functions | Workflows |
| 41 | Data warehouse | Redshift | Synapse or Fabric | BigQuery |
| 42 | Serverless SQL on object storage | Athena | Synapse serverless SQL | BigQuery external tables |
| 43 | Container registry | ECR | ACR | Artifact Registry |
| 44 | Managed CI/CD | CodeBuild and CodePipeline | Azure DevOps Pipelines | Cloud Build and Cloud Deploy |
| 45 | Native infrastructure as code | CloudFormation or CDK | Bicep or ARM templates | Deployment Manager or Infrastructure Manager |
| 46 | Configuration and fleet management | Systems Manager | Azure Arc and Automanage | VM Manager |
| 47 | API management | API Gateway | API Management | API Gateway or Apigee |
| 48 | Cost management | Cost Explorer and Budgets | Cost Management | Billing reports and Budgets |
| 49 | Image builders | EC2 Image Builder | Azure Image Builder | Packer on Compute Engine or Image Builder |
| 50 | Service quotas and limits | Service Quotas | Quotas and limits | Quotas |
@check
Which service family holds IAM and KMS? || Identity and security.
@end
