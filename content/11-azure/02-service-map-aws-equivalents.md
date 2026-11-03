---
title: Azure service map and AWS equivalents
minutes: 45
objectives:
  - Translate common AWS services into their Azure counterparts
  - Spot the places where the two clouds behave differently
  - Pick the Azure service for each tier of a typical web application
---
You already know AWS. This page is a translation table with the traps marked. Later pages go deep on each area.

@concept Compute map
@plain
Azure has the same compute shapes as AWS: virtual machines, scale groups, containers, functions and managed Kubernetes.
@problem
Searching the Azure catalogue by name alone wastes time because the names differ.
@does
- EC2 maps to **Virtual Machines**; Auto Scaling groups to **VM Scale Sets**.
- EKS maps to **AKS**; ECS and Fargate map loosely to **Azure Container Apps** and **Container Instances**.
- Lambda maps to **Azure Functions**; Elastic Beanstalk to **App Service**; AWS Batch to **Azure Batch**.
- **Main difference**: App Service and Container Apps are used far more often as the default web platform than Beanstalk or ECS in many AWS shops.
@diagram cmp
caption: Compute equivalents
cards:
  - {h: "AWS", kind: warn, items: ["EC2", "Auto Scaling group", "EKS", "ECS and Fargate", "Lambda"]}
  - {h: "Azure", kind: info, items: ["Virtual Machines", "VM Scale Sets", "AKS", "Container Apps", "Functions"]}
@h List what you can run
```bash title="Compute services in your subscription" lab
az provider list --query "[?contains(namespace,'Microsoft.Compute') || contains(namespace,'Microsoft.ContainerService') || contains(namespace,'Microsoft.App')].namespace" -o tsv
```
@check
Which Azure service is the managed Kubernetes equivalent of EKS? || AKS.
@end

@concept Networking map
@plain
A VPC is a VNet, a security group is mostly a network security group, and load balancing is split across four services.
@problem
Network designs carried over from AWS fail on small differences such as subnet scope and route behaviour.
@does
- VPC is **Virtual Network**; Route 53 is **Azure DNS** and **Traffic Manager**; ALB is **Application Gateway**; NLB is **Load Balancer**; CloudFront is **Front Door**.
- NAT gateway is **NAT Gateway**; Transit Gateway is **Virtual WAN** or hub VNet with peering; PrivateLink is **Private Link**; Network Firewall is **Azure Firewall**.
- **Main difference**: subnets span all zones in a region, there are no route-table-per-AZ designs, and NSGs can attach to subnets and to NICs.
@diagram cmp
caption: Network equivalents
cards:
  - {h: "AWS", kind: warn, items: ["VPC", "Security group and NACL", "ALB and NLB", "CloudFront", "Transit Gateway"]}
  - {h: "Azure", kind: info, items: ["Virtual Network", "NSG", "App Gateway and Load Balancer", "Front Door", "Virtual WAN"]}
@h Quick inventory
```bash title="Networks in the subscription" lab
az network vnet list --query '[].{name:name,rg:resourceGroup,space:addressSpace.addressPrefixes[0]}' -o table
```
@end

@concept Storage and database map
@plain
Object, file and block storage all exist, and the managed databases cover SQL, open source engines, NoSQL and cache.
@problem
Choosing the wrong data service early is expensive to reverse.
@does
- S3 is **Blob Storage** inside a **storage account**; EFS is **Azure Files** (NFS or SMB); EBS is **Managed Disks**.
- RDS SQL Server is **Azure SQL**; RDS PostgreSQL and MySQL are **Flexible Server**; DynamoDB is **Cosmos DB**; ElastiCache is **Azure Cache for Redis** (check the current Managed Redis offering).
- **Main difference**: the storage account is a mandatory wrapper that holds blobs, files, queues and tables with shared settings, so there is no direct equivalent of a bucket as top-level resource.
@diagram cmp
caption: Data equivalents
cards:
  - {h: "AWS", kind: warn, items: ["S3", "EFS", "EBS", "RDS", "DynamoDB", "ElastiCache"]}
  - {h: "Azure", kind: info, items: ["Blob in a storage account", "Azure Files", "Managed Disks", "Azure SQL, Flexible Server", "Cosmos DB", "Azure Cache for Redis"]}
@h Data resources
```bash title="What data services exist" lab
az storage account list -o table
az postgres flexible-server list -o table
```
@end

@concept Identity and security map
@plain
IAM splits into two systems on Azure: Entra ID for who you are and Azure RBAC for what you can do to resources.
@problem
AWS engineers look for IAM roles and policies and cannot find a single place in Azure.
@does
- IAM users and Identity Center map to **Entra ID**; IAM roles for services map to **managed identities**; IAM policies map to **RBAC role assignments** (plus Policy for guardrails).
- KMS and Secrets Manager map to **Key Vault**; ACM maps to Key Vault certificates; GuardDuty and Security Hub map to **Microsoft Defender for Cloud**.
- **Main difference**: Azure roles are assigned to a principal at a scope, rather than a policy document attached to an identity.
@diagram cmp
caption: Security equivalents
cards:
  - {h: "AWS", kind: warn, items: ["IAM user, Identity Center", "IAM role", "IAM policy", "KMS, Secrets Manager", "GuardDuty"]}
  - {h: "Azure", kind: info, items: ["Entra ID user", "Managed identity", "RBAC role assignment", "Key Vault", "Defender for Cloud"]}
@h Who am I
```bash title="Current identity" lab
az ad signed-in-user show --query '{upn:userPrincipalName,id:id}' -o json
az role assignment list --assignee $(az ad signed-in-user show --query id -o tsv) --all -o table
```
@end

@concept Monitoring and DevOps map
@plain
CloudWatch is replaced by Azure Monitor with Log Analytics, and the CodeSuite is replaced by Azure DevOps or GitHub Actions.
@problem
Teams re-create observability from scratch when they could use built-in services.
@does
- CloudWatch Metrics is **Azure Monitor Metrics**; CloudWatch Logs is **Log Analytics** queried with KQL; X-Ray is **Application Insights**.
- CloudTrail is the **Activity Log**; Config is **Azure Policy** and Resource Graph.
- CodeBuild, CodePipeline and CodeDeploy map to **Azure Pipelines** or **GitHub Actions**; ECR maps to **ACR**.
- CloudFormation maps to **ARM and Bicep**; Terraform works on both.
- Prometheus and Grafana can be fully managed with **Azure Monitor managed service for Prometheus** and **Azure Managed Grafana**.
@diagram cmp
caption: Operations equivalents
cards:
  - {h: "AWS", kind: warn, items: ["CloudWatch", "CloudTrail", "Config", "CodePipeline", "ECR", "CloudFormation"]}
  - {h: "Azure", kind: info, items: ["Azure Monitor", "Activity Log", "Policy and Resource Graph", "Pipelines or Actions", "ACR", "Bicep"]}
@h Resource Graph query
```bash title="Cross-subscription inventory" lab
az graph query -q "resources | summarize count() by type | order by count_ desc | take 10" -o table
```
@end

@concept Behavioural differences that bite
@plain
Several defaults differ from AWS even when the service names line up.
@problem
Assuming AWS behaviour leads to open ports, broken routing and surprise bills.
@does
- **Outbound internet**: new VNets give default outbound access, which Microsoft is retiring for new subnets in favour of explicit outbound (NAT Gateway or similar). Check the current announcement for your date.
- **Subnets and zones**: a subnet is regional and spans zones. In AWS a subnet lives in one AZ.
- **Public IPs**: Standard SKU IPs are secure by default and closed until an NSG allows traffic.
- **Metadata identity**: managed identities use an IMDS endpoint, similar to instance profiles.
- **Cost**: Azure charges for stopped but allocated VMs until you deallocate them.
- **IAM scope**: role assignments propagate down the tree and can take minutes to apply.
@diagram flow
caption: Check these before copying an AWS design
nodes:
  - "Subnet scope|regional, not per zone|warn"
  - "Outbound traffic|explicit NAT recommended|warn"
  - "VM billing|deallocate to stop compute cost|warn"
  - "RBAC delay|allow a few minutes|warn"
@h Deallocate versus stop
```bash title="Stop paying for compute" lab
az vm stop --resource-group rg-lab --name vm1
az vm deallocate --resource-group rg-lab --name vm1
az vm get-instance-view -g rg-lab -n vm1 --query 'instanceView.statuses[].displayStatus' -o tsv
```
@check
Which command stops compute billing, stop or deallocate? || Deallocate. A stopped but allocated VM is still billed for compute.
@end

@concept Reading the Azure documentation like an AWS engineer
@plain
Learn a handful of Azure terms and the documentation becomes easy to navigate.
@problem
Azure docs mix old and new product names, which makes searches confusing.
@does
- **SKU** means a tier or size of a service (for example Basic, Standard, Premium).
- **Provider namespace** is the `Microsoft.*` prefix in resource IDs.
- **Scope** is where something is assigned: tenant, management group, subscription, resource group, resource.
- **Azure AD** is the old name of Entra ID; commands called `az ad` still use it.
- **Landing zone** is a preconfigured subscription pattern, not an AWS Control Tower account.
- The Cloud Adoption Framework and Well-Architected Framework are the Azure design guides.
@diagram flow
caption: Terms to remember
nodes:
  - "Scope|where it applies|info"
  - "SKU|size or tier|info"
  - "Provider|Microsoft dot something|info"
  - "Landing zone|ready subscription pattern|ok"
@h Find the right SKU names
```bash title="Discover" lab
az aks get-versions --location westeurope -o table
az vm list-sizes --location westeurope --query "[?contains(name,'D4s_v5')].{name:name,cpu:numberOfCores,mem:memoryInMb}" -o table
```
@end

@concept Budgets, cost analysis and tags
@plain
**Cost Management** shows spend by subscription, group, tag and service. A **budget** sends alerts, or triggers an action group, at set thresholds.
@problem
Cloud bills surprise teams because nobody sees spend until the invoice.
@does
- **AWS equivalent**: Cost Explorer, AWS Budgets, cost allocation tags.
- **Main difference**: Cost Management is built into every scope (management group, subscription, resource group). Budgets alert at actual or forecast thresholds. Cost data can lag by hours, and tag coverage depends on the resource type; check the current docs. Scheduled exports write CSV to storage for FinOps tooling.
- Allocate shared AKS costs with namespace cost analysis, an AKS add-on; check its current status.
- Stop dev clusters out of hours with `az aks stop`.
@diagram flow
caption: Cost loop
nodes:
  - "Tags|app, env, owner|info"
  - "Cost analysis|group by tag|cp"
  - "Budget|80 and 100 percent|warn"
  - "Action|email, webhook, shutdown|ok"
@h Budget and stop a dev cluster
```bash title="Budget and AKS stop" lab
az consumption budget create --budget-name shop-prod-monthly --category cost --amount 3000 --time-grain monthly \
  --start-date 2026-11-01 --end-date 2027-10-31 --resource-group rg-shop-prod 2>/dev/null || echo "check az consumption budget help for current parameters"
az aks stop -g rg-shop-dev -n aks-shop-dev
az aks start -g rg-shop-dev -n aks-shop-dev
```
:::note
Budget CLI support changes. If the command fails, create the budget in the portal or with the Bicep resource `Microsoft.Consumption/budgets`.
:::
@check
Does a budget stop spending by itself? || No. It alerts or triggers an action you define.
@end
