---
title: Core services 41 to 45, analytics and delivery
minutes: 60
objectives:
  - Compare warehouses, serverless SQL, registries, CI/CD and native IaC
  - State when to choose each service
  - List the limits to verify in the current docs
---
Analytics services answer questions over data, and delivery services ship software. Each service below is one concept with names for all three clouds.

@concept Group at a glance
@plain
Warehouse for loaded data, serverless SQL for files, registry and pipelines for delivery. This page maps five services across AWS, Azure and Google Cloud so the same idea can be found under each cloud's name.
@problem
Each cloud names the same idea differently, so teams lose time translating docs and comparing offers.
@does
- Gives the three product names for each service in one table.
- Shows what each service is for, when to choose it and what to check in the current docs.
- Gives a CLI example for each cloud, marked as an illustration to adapt.
@diagram layers
caption: Data and delivery
layers:
  - {label: "Services on this page", nodes: ["Data warehouse|Redshift|app", "Serverless SQL on object storage|Athena|info", "Container registry|ECR|env", "Managed CI/CD|CodeBuild and CodePipeline|ok", "Native infrastructure as code|CloudFormation or CDK|cp"]}
@h Names side by side
| # | Service | AWS | Azure | GCP |
|---|---|---|---|---|
| 41 | Data warehouse | Redshift | Synapse or Fabric | BigQuery |
| 42 | Serverless SQL on object storage | Athena | Synapse serverless SQL | BigQuery external tables |
| 43 | Container registry | ECR | ACR | Artifact Registry |
| 44 | Managed CI/CD | CodeBuild and CodePipeline | Azure DevOps Pipelines | Cloud Build and Cloud Deploy |
| 45 | Native infrastructure as code | CloudFormation or CDK | Bicep or ARM templates | Deployment Manager or Infrastructure Manager |
@check
Why compare by capability instead of by product name? || Names differ, but the problem each service solves is the same.
@end

@concept 41. Data warehouse
@plain
A database designed for large analytical queries over many rows, rather than many small transactions.
@problem
Operational databases slow down and fail under large reports.
@does
- **Names**: AWS Redshift; Azure Synapse or Fabric; GCP BigQuery.
- **What it is**: Stores data by column, parallelises queries, and separates storage from compute to varying degrees.
- **Choose it when**: BI dashboards and reports; Large aggregations; Data marts.
- **Check in the current docs**: Cost models differ between provisioned capacity and per-scan billing, so check the current docs; Azure's analytics products are changing, so verify Synapse versus Fabric; Partitioning and clustering reduce cost.
@diagram cmp
caption: Data warehouse on the three clouds
cards:
  - {h: "Redshift", kind: warn, items: ["Provisioned or serverless clusters, Spectrum"]}
  - {h: "Synapse or Fabric", kind: info, items: ["Synapse dedicated pools, Fabric warehouse"]}
  - {h: "BigQuery", kind: ok, items: ["Datasets, partitioned tables, slots or on-demand"]}
@h Example
A daily sales report scans one partition instead of the full table, cutting bytes read.
@h CLI on each cloud
```bash title="AWS CLI, Data warehouse" nocheck
aws redshift-serverless create-namespace --namespace-name analytics
```
```bash title="Azure CLI, Data warehouse" nocheck
az synapse workspace create --name demo-syn-123 --resource-group rg-demo --storage-account stdemo123 --file-system fs --sql-admin-login-user sqladmin --sql-admin-login-password CHANGE_ME_NOW
```
```bash title="gcloud, Data warehouse" nocheck
bq mk --dataset --location=EU demo_dataset
```
@check
Why partition large tables? || Queries read only the needed slices, lowering cost and time.
@end

@concept 42. Serverless SQL on object storage
@plain
Run SQL directly on files in object storage without loading them into a database.
@problem
Loading data first adds delay and cost for occasional queries.
@does
- **Names**: AWS Athena; Azure Synapse serverless SQL; GCP BigQuery external tables.
- **What it is**: Reads formats such as Parquet and CSV in place, billed mainly by data scanned.
- **Choose it when**: Ad hoc log analysis; Data lake exploration; Infrequent queries.
- **Check in the current docs**: Use columnar formats and partitions to cut scan cost; Schema is defined by a catalog, which must be kept current; Performance is lower than a loaded warehouse.
@diagram cmp
caption: Serverless SQL on object storage on the three clouds
cards:
  - {h: "Athena", kind: warn, items: ["Glue catalog, workgroups, Parquet"]}
  - {h: "Synapse serverless SQL", kind: info, items: ["OPENROWSET over storage"]}
  - {h: "BigQuery external tables", kind: ok, items: ["External tables over Cloud Storage"]}
@h Example
Converting CSV logs to partitioned Parquet reduced bytes scanned per query by an order of magnitude in a typical case, so measure on your data.
@h CLI on each cloud
```bash title="AWS CLI, Serverless SQL on object storage" nocheck
aws athena start-query-execution --query-string 'SELECT count(*) FROM logs' --work-group primary --result-configuration OutputLocation=s3://demo-bucket-123456/athena/
```
```bash title="Azure CLI, Serverless SQL on object storage" nocheck
az synapse sql pool list --workspace-name demo-syn-123 --resource-group rg-demo
```
```bash title="gcloud, Serverless SQL on object storage" nocheck
bq mk --external_table_definition=gs://demo-bucket-123456/logs/*.parquet@PARQUET demo_dataset.logs_ext
```
@check
How cut scan cost? || Use columnar formats and partitions.
@end

@concept 43. Container registry
@plain
A private store for container images and sometimes other packages.
@problem
Pulling from public registries is rate-limited and unscanned.
@does
- **Names**: AWS ECR; Azure ACR; GCP Artifact Registry.
- **What it is**: Stores images with access control, scanning, replication and lifecycle cleanup.
- **Choose it when**: Private images; Vulnerability scanning; Close to the cluster.
- **Check in the current docs**: Storage grows without lifecycle rules; Cross-region pulls cost egress; Use immutable tags or digests for releases.
@diagram cmp
caption: Container registry on the three clouds
cards:
  - {h: "ECR", kind: warn, items: ["Repositories, image scanning, lifecycle policies"]}
  - {h: "ACR", kind: info, items: ["Registries with geo-replication, tasks"]}
  - {h: "Artifact Registry", kind: ok, items: ["Repositories for images and packages"]}
@h Example
A pipeline pushes an image tagged with the git commit and the cluster deploys by digest.
@h CLI on each cloud
```bash title="AWS CLI, Container registry" nocheck
aws ecr create-repository --repository-name shop/api
```
```bash title="Azure CLI, Container registry" nocheck
az acr create --resource-group rg-demo --name demoacr123 --sku Standard
```
```bash title="gcloud, Container registry" nocheck
gcloud artifacts repositories create shop --repository-format=docker --location=europe-west1
```
@check
Why deploy by digest? || A digest cannot change, a tag can.
@end

@concept 44. Managed CI/CD
@plain
Hosted services that build, test and deploy your code when it changes.
@problem
Running your own build servers costs maintenance effort.
@does
- **Names**: AWS CodeBuild and CodePipeline; Azure Azure DevOps Pipelines; GCP Cloud Build and Cloud Deploy.
- **What it is**: Runs pipelines on managed agents with integration to the cloud's identity and artifacts.
- **Choose it when**: Teams already on that cloud; Simple build and deploy flows; Tight identity integration.
- **Check in the current docs**: Product roadmaps change, so check the current docs for each service; Many teams prefer a cloud-neutral tool such as GitHub Actions; Build minutes and agent size are billed.
@diagram cmp
caption: Managed CI/CD on the three clouds
cards:
  - {h: "CodeBuild and CodePipeline", kind: warn, items: ["CodeBuild projects, CodePipeline stages"]}
  - {h: "Azure DevOps Pipelines", kind: info, items: ["Pipelines YAML, environments"]}
  - {h: "Cloud Build and Cloud Deploy", kind: ok, items: ["cloudbuild.yaml, delivery pipelines"]}
@h Example
A commit triggers build, test, image push and a staged rollout through dev and prod.
@h CLI on each cloud
```bash title="AWS CLI, Managed CI/CD" nocheck
aws codebuild list-projects
```
```bash title="Azure CLI, Managed CI/CD" nocheck
az pipelines list --organization https://dev.azure.com/demo-org --project shop
```
```bash title="gcloud, Managed CI/CD" nocheck
gcloud builds submit --tag europe-west1-docker.pkg.dev/demo-project/shop/api:v1 .
```
@check
Why consider a cloud-neutral CI tool? || It avoids lock-in and works across clouds.
@end

@concept 45. Native infrastructure as code
@plain
Each cloud's own way to describe resources in files and have the platform create them.
@problem
Clicking in a console is not repeatable or reviewable.
@does
- **Names**: AWS CloudFormation or CDK; Azure Bicep or ARM templates; GCP Deployment Manager or Infrastructure Manager.
- **What it is**: Declares desired resources, tracks state in the service, previews changes and rolls back on failure in some tools.
- **Choose it when**: Single-cloud shops; Day-zero feature coverage; Teams avoiding external state.
- **Check in the current docs**: Terraform or OpenTofu covers all three clouds, so compare before choosing; Deployment Manager has a deprecation notice, so check the current docs and prefer Infrastructure Manager; Stack and template size limits exist.
@diagram cmp
caption: Native infrastructure as code on the three clouds
cards:
  - {h: "CloudFormation or CDK", kind: warn, items: ["Stacks, change sets, CDK constructs"]}
  - {h: "Bicep or ARM templates", kind: info, items: ["Bicep modules, what-if"]}
  - {h: "Deployment Manager or Infrastructure Manager", kind: ok, items: ["Infrastructure Manager runs Terraform configs"]}
@h Example
A team writes Bicep modules, and a pipeline previews changes with what-if before approval.
@h CLI on each cloud
```bash title="AWS CLI, Native infrastructure as code" nocheck
aws cloudformation deploy --stack-name shop --template-file template.yaml
```
```bash title="Azure CLI, Native infrastructure as code" nocheck
az deployment group create --resource-group rg-demo --template-file main.bicep
```
```bash title="gcloud, Native infrastructure as code" nocheck
gcloud infra-manager deployments apply projects/demo-project/locations/europe-west1/deployments/shop --service-account=projects/demo-project/serviceAccounts/tf@demo-project.iam.gserviceaccount.com --local-source=. --input-values=env=dev
```
@check
Why preview changes before applying? || To catch destructive or unexpected changes.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Scanning unpartitioned data.
- Mutable image tags in production.
- Mixing several IaC tools without a rule.
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
service: Data warehouse
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

