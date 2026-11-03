---
title: Service map, gcloud and the resource hierarchy
minutes: 50
objectives:
  - Map common AWS services to their Google Cloud equivalents and name the key differences
  - Set up gcloud configurations and Application Default Credentials correctly
  - Explain organization, folders, projects and billing accounts and how they differ from AWS accounts
---
If you know AWS, Google Cloud is mostly familiar with a few structural differences. The biggest one is the project, which replaces the AWS account as the unit of isolation, and a global VPC that spans regions.

@concept Service map from AWS to Google Cloud
@plain
Almost every AWS building block has a Google Cloud counterpart. The names differ and a few designs differ in important ways.
@problem
Engineers who know AWS lose time hunting for the right product name, and then misjudge how it behaves.
@does
- **Compute**: EC2 is Compute Engine, ECS/Fargate is Cloud Run, EKS is GKE, Lambda is Cloud Run functions (formerly Cloud Functions).
- **Network**: VPC is a global VPC, ALB is the Application Load Balancer, Route 53 is Cloud DNS, WAF/Shield is Cloud Armor, Transit Gateway is Network Connectivity Center.
- **Data**: S3 is Cloud Storage, RDS is Cloud SQL, Aurora is AlloyDB, DynamoDB is Bigtable or Firestore, ElastiCache is Memorystore, Redshift is BigQuery.
- **Ops**: CloudWatch is Cloud Logging and Cloud Monitoring, X-Ray is Cloud Trace, ECR is Artifact Registry, Secrets Manager is Secret Manager, KMS is Cloud KMS, SQS/SNS is Pub/Sub.
- **Main difference**: the mapping is approximate. Spanner has no direct AWS equivalent, and BigQuery is serverless with no cluster to size.
@diagram cmp
caption: Same job, different names
cards:
  - {h: "AWS", kind: info, items: ["EC2, EKS, Lambda", "S3, RDS, DynamoDB", "CloudWatch, ECR, KMS"]}
  - {h: "Google Cloud", kind: app, items: ["Compute Engine, GKE, Cloud Run", "Cloud Storage, Cloud SQL, Bigtable", "Cloud Monitoring, Artifact Registry, Cloud KMS"]}
@h Quick lookup table
| AWS | Google Cloud | Main difference |
|---|---|---|
| Account | Project | Projects sit in folders and are cheap to create |
| VPC (regional) | VPC (global) | One VPC, subnets are regional |
| ALB | Global external Application LB | One anycast IP serves all regions |
| IAM role on EC2 | Service account | A service account is both identity and resource |
| Organizations SCP | Organization Policy | Constraints plus IAM deny policies |
@check
Which Google Cloud object is closest to an AWS account? || The project.
@end

@concept The gcloud CLI and named configurations
@plain
`gcloud` is the main command line tool. A **configuration** stores the account, project, region and zone so you can switch context quickly.
@problem
Running commands against the wrong project is the most common and costly mistake, just as with AWS profiles.
@does
- `gcloud config configurations create` makes a named set of properties, similar to an AWS CLI profile.
- `gcloud auth login` signs you in as a user; `gcloud config set project` selects the default project.
- Every command accepts `--project` to override, which is safer in scripts.
- Output formats `--format=json`, `value(...)` and `table(...)` plus `--filter` replace most `jq` use.
- **AWS equivalent**: `aws configure --profile` and `AWS_PROFILE`. Main difference: gcloud also has a built-in filter and projection language.
@diagram flow
caption: Context selection for every command
nodes:
  - "Configuration|account, project, region|info"
  - "gcloud command|uses active settings|app"
  - "--project flag|overrides when given|warn"
  - "Google API|call is authorised|cp"
@h Set up and inspect
```bash title="Named configurations" lab
gcloud config configurations create shop-dev
gcloud config set account you@example.com
gcloud config set project shop-dev-123456
gcloud config set compute/region europe-west1
gcloud config set compute/zone europe-west1-b
gcloud config configurations list
gcloud projects list --format="table(projectId,name,lifecycleState)" --filter="labels.env=dev"
```
:::tip
Show the active project in your shell prompt. Many teams also add a confirmation step for production configurations.
:::
@end

@concept Application Default Credentials
@plain
**Application Default Credentials (ADC)** is how Google client libraries and tools such as Terraform find credentials automatically.
@problem
Code should not contain keys, yet it must run the same on a laptop, on GKE and in CI.
@does
- Lookup order: the `GOOGLE_APPLICATION_CREDENTIALS` file, then the local ADC file created by `gcloud auth application-default login`, then the attached service account from the metadata server.
- `gcloud auth login` and ADC are separate. Logging in to gcloud does not set up ADC for your code.
- For local use of a service account, prefer impersonation over downloaded keys.
- **AWS equivalent**: the default credential provider chain. Main difference: on Google Cloud the final fallback is the metadata server of the VM, pod or Cloud Run service.
@diagram flow
caption: ADC lookup order
numbered: true
nodes:
  - "Env variable|GOOGLE_APPLICATION_CREDENTIALS|info"
  - "Local ADC file|from application-default login|info"
  - "Metadata server|attached service account|ok"
@h Local ADC with impersonation
```bash title="ADC for development" lab
gcloud auth application-default login
gcloud auth application-default set-quota-project shop-dev-123456
# Use a service account without a key file
gcloud auth application-default login \
  --impersonate-service-account=tf-deployer@shop-dev-123456.iam.gserviceaccount.com
```
@check
Does gcloud auth login configure ADC for your Python code? || No. You need gcloud auth application-default login.
@end

@concept Regions, zones and multi-region locations
@plain
A **region** is a geographic area such as `europe-west1`. A **zone** is an isolated location inside it, such as `europe-west1-b`. Some services also offer **multi-region** locations such as `EU` or `US`.
@problem
You need to place workloads for latency, data residency and failure isolation.
@does
- Regions typically have three zones. Zone names are per project, so do not assume letters mean the same hardware.
- Zonal resources: VMs, zonal disks. Regional: subnets, regional MIGs, regional GKE clusters. Global: VPC, global load balancers, images.
- Multi-region buckets and BigQuery datasets replicate across regions inside one geography.
- **AWS equivalent**: regions and AZs. Main difference: many more resource types are global, and Google does not charge for traffic between zones of a region in the same way as AWS; check current pricing.
@diagram layers
caption: Scope of resources
layers:
  - {label: "Global", nodes: ["VPC network|routes, firewall|cp", "Global LB|anycast IP|cp"]}
  - {label: "Regional", nodes: ["Subnet|CIDR range|info", "Regional GKE|control plane|app", "Cloud SQL HA|primary and standby|app"]}
  - {label: "Zonal", nodes: ["VM|one zone|vm", "Zonal disk|one zone|db"]}
@h List locations
```bash title="Regions and zones" lab
gcloud compute regions list --format="value(name)"
gcloud compute zones list --filter="region:europe-west1" --format="value(name,status)"
```
@end

@concept Enabling APIs
@plain
Each Google Cloud service is an API that must be enabled in a project before use.
@problem
A new project has almost nothing turned on, so first calls fail with a "has not been used in project" error.
@does
- `gcloud services enable` turns on an API per project. Billing must be linked for most.
- `gcloud services list --enabled` shows what is active; disabling APIs reduces attack surface.
- Automation should enable APIs explicitly (Terraform `google_project_service`).
- **AWS equivalent**: none, as AWS services are available by default (opt-in regions aside). Main difference: this is a deliberate extra step.
@diagram flow
caption: From new project to usable service
nodes:
  - "New project|no APIs|plain"
  - "Link billing|required|warn"
  - "Enable API|container.googleapis.com|info"
  - "Use service|create cluster|ok"
@h Enable what the Shop needs
```bash title="Enable APIs" lab
gcloud services enable container.googleapis.com compute.googleapis.com \
  artifactregistry.googleapis.com secretmanager.googleapis.com \
  sqladmin.googleapis.com redis.googleapis.com servicenetworking.googleapis.com \
  --project=shop-dev-123456
gcloud services list --enabled --project=shop-dev-123456 --format="value(config.name)"
```
:::note
Enabling an API can take a minute. Retry loops in automation help.
:::
@end

@concept Organization and folders
@plain
The **organization** is the root of your company's resources, tied to a Cloud Identity or Google Workspace domain. **Folders** group projects beneath it.
@problem
You need one place to apply policy, access and audit across hundreds of projects.
@does
- IAM allow policies, deny policies and organization policies set on a node are inherited by everything below.
- Folders can nest (the current limit is about ten levels; check the docs). Typical layout is folders by environment or business unit.
- Without an organization (a standalone project) you lose central policy, so create one early.
- **AWS equivalent**: AWS Organizations with OUs. Main difference: IAM itself is inherited down the hierarchy, whereas in AWS you use SCPs as guardrails and per-account IAM.
@diagram layers
caption: Resource hierarchy
layers:
  - {label: "Organization", nodes: ["example.com|policy root|cp"]}
  - {label: "Folders", nodes: ["Production|folder|env", "Non-production|folder|env", "Shared services|folder|env"]}
  - {label: "Projects", nodes: ["shop-prod|project|app", "shop-dev|project|app", "net-hub|project|info"]}
@h Create folders and projects
```bash title="Folders and projects" lab
gcloud organizations list
gcloud resource-manager folders create --display-name="Production" --organization=123456789012
gcloud projects create shop-prod-123456 --folder=111122223333 --labels=env=prod,app=shop
```
@check
Where do you attach a policy that must apply to every project? || On the organization node.
@end

@concept Projects
@plain
A **project** is the container for resources, APIs, IAM and billing. It has three identifiers: a name, a globally unique ID and a number.
@problem
You need blast-radius isolation, clear ownership and per-team cost tracking.
@does
- Project ID is permanent and unique across Google Cloud; the project number is used inside service account names.
- Deleting a project schedules removal (about 30 days to restore). Use a lien to prevent accidental deletion.
- Quotas and API enablement are per project, so a project per environment per app is common.
- **AWS equivalent**: the account. Main difference: projects are lightweight, created in seconds, and you do not need a separate login or role chain to enter them.
@diagram flow
caption: What a project binds together
nodes:
  - "Project|ID and number|cp"
  - "IAM|who can do what|info"
  - "APIs|enabled services|app"
  - "Billing|linked account|warn"
@h Liens and inspection
```bash title="Protect a project" lab
gcloud projects describe shop-prod-123456 --format="value(projectNumber,parent.id)"
gcloud alpha resource-manager liens create --project=shop-prod-123456 \
  --restrictions=resourcemanager.projects.delete --reason="Production shop"
```
:::warn
The lien command is in the alpha group at the time of writing. Check the current docs.
:::
@end

@concept Billing accounts
@plain
A **billing account** pays for the usage of the projects linked to it. A project has exactly one billing account at a time.
@problem
Finance wants a clean invoice, while engineering wants separate projects.
@does
- Roles `roles/billing.admin`, `roles/billing.user` (link projects) and `roles/billing.viewer` control access, and are separate from project roles.
- Unlinking billing stops paid resources, which is a quick way to stop runaway cost in a sandbox.
- Billing export to BigQuery gives line-level data; budgets and alerts are set per billing account.
- **AWS equivalent**: the management account payer with consolidated billing. Main difference: you can link and unlink any project freely, and a billing account is its own resource with its own IAM.
@diagram flow
caption: One billing account, many projects
nodes:
  - "Billing account|invoice and payment|warn"
  - "shop-prod|linked|app"
  - "shop-dev|linked|app"
  - "BigQuery export|usage lines|info"
@h Link a project
```bash title="Billing link" lab
gcloud billing accounts list
gcloud billing projects link shop-dev-123456 --billing-account=0A1B2C-3D4E5F-6A7B8C
gcloud billing projects describe shop-dev-123456
```
@end
