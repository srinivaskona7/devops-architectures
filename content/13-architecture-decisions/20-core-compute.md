---
title: Core services 1 to 5, compute
minutes: 60
objectives:
  - Read the cross-cloud map and pick the right compute service
  - State when to choose each service
  - List the limits to verify in the current docs
---
Compute is the first layer of the map, from raw machines up to functions. Each service below is one concept with names for all three clouds.

@concept How to read the map
@plain
The map lists fifty cloud services in the same order every time: AWS name, Azure name, Google Cloud name, then what it is, when to choose it, what to check and a CLI example.
@problem
Engineers who know one cloud struggle to find the equivalent product in another, and product names change over time.
@does
- Each concept is one capability, such as object storage, not one product.
- Treat the names as a starting point. Equivalent does not mean identical, because limits, defaults and billing differ.
- Claims about limits point you to the current documentation rather than quoting numbers that may change.
- CLI blocks are illustrations with placeholder names. Replace identifiers and run them only in a sandbox account.
@diagram flow
caption: Reading one entry of the map
numbered: true
nodes:
  - "Capability|what you need|plain"
  - "Three names|AWS, Azure, GCP|info"
  - "When to choose|fit and misfit|ok"
  - "Gotchas|verify in docs|warn"
  - "CLI|try in a sandbox|app"
@h Template used for each service
```text title="entry layout" nocheck
Capability name
  AWS product / Azure product / GCP product
  In plain words, the problem, what it does
  Choose it when ... ; check in the current docs ...
  One CLI example per cloud
```
@check
Does equivalent mean identical? || No, limits, defaults and prices differ, so check the docs.
@end

@concept 1. Virtual machines
@plain
A virtual machine is a rented slice of a physical server that behaves like your own computer, with its own operating system, disk and network address.
@problem
Some software cannot be containerised or needs full control of the operating system, kernel or licensing, and buying hardware is slow.
@does
- **Names**: AWS EC2; Azure Virtual Machines; GCP Compute Engine.
- **What it is**: Rent CPU, memory and disk by the second or hour, from small shared sizes to large GPU or memory-optimised machines.
- **Choose it when**: Lift-and-shift of existing servers and licensed software; Workloads needing a custom kernel, GPU, or special agents; Stateful single-node tools such as a bastion or build agent.
- **Check in the current docs**: Instance families and sizes differ by cloud and region, so check the current docs for availability; Quotas on vCPUs per region apply by default and can block a launch; Public IPs, disk types and spot or preemptible discounts are billed and behave differently on each cloud.
@diagram cmp
caption: Virtual machines on the three clouds
cards:
  - {h: "EC2", kind: warn, items: ["Nitro-based instances, AMIs, security groups"]}
  - {h: "Virtual Machines", kind: info, items: ["Sizes like B and D series, images, NSGs"]}
  - {h: "Compute Engine", kind: ok, items: ["Machine families such as E2 and N2, images, firewall rules"]}
@h Example
A team moves a licensed reporting server to a single VM in the same region as its database, with a daily snapshot for recovery.
@h CLI on each cloud
```bash title="AWS CLI, Virtual machines" nocheck
aws ec2 run-instances --image-id ami-0123456789abcdef0 --instance-type t3.micro --subnet-id subnet-0abc1234 --count 1 --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=web1}]'
```
```bash title="Azure CLI, Virtual machines" nocheck
az vm create --resource-group rg-demo --name web1 --image Ubuntu2204 --size Standard_B1s --admin-username azureuser --generate-ssh-keys
```
```bash title="gcloud, Virtual machines" nocheck
gcloud compute instances create web1 --zone=europe-west1-b --machine-type=e2-micro --image-family=debian-12 --image-project=debian-cloud
```
@check
Which VM quota commonly blocks a first launch? || The regional vCPU quota, which you can raise through each cloud's quota process.
@end

@concept 2. Autoscaled VM groups
@plain
A group that keeps a chosen number of identical VMs running and adds or removes machines as load changes.
@problem
A single VM is a single point of failure and cannot follow traffic, so capacity is either wasted or too small.
@does
- **Names**: AWS Auto Scaling Groups; Azure VM Scale Sets; GCP Managed Instance Groups.
- **What it is**: Create VMs from one template, replace unhealthy ones, spread them across zones, and scale on metrics or schedules.
- **Choose it when**: Stateless web or worker tiers on VMs; Immutable image rollouts with rolling replacement; Workloads that need zone spread behind a load balancer.
- **Check in the current docs**: Scaling policies and cooldown or stabilisation settings differ per cloud, so tune and test them; Health checks decide replacement, so a wrong check can cause a restart loop; Templates are versioned objects, and old versions must be cleaned up.
@diagram cmp
caption: Autoscaled VM groups on the three clouds
cards:
  - {h: "Auto Scaling Groups", kind: warn, items: ["Launch templates, target tracking, instance refresh"]}
  - {h: "VM Scale Sets", kind: info, items: ["Uniform or flexible orchestration, autoscale rules"]}
  - {h: "Managed Instance Groups", kind: ok, items: ["Instance templates, autohealing, regional groups"]}
@h Example
A web tier runs 2 to 6 instances across three zones behind a load balancer and scales on average CPU near 60 percent.
@h CLI on each cloud
```bash title="AWS CLI, Autoscaled VM groups" nocheck
aws autoscaling create-auto-scaling-group --auto-scaling-group-name web-asg --launch-template LaunchTemplateName=web-lt,Version='$Latest' --min-size 2 --max-size 6 --vpc-zone-identifier "subnet-aaa,subnet-bbb"
```
```bash title="Azure CLI, Autoscaled VM groups" nocheck
az vmss create --resource-group rg-demo --name web-vmss --image Ubuntu2204 --instance-count 2 --vm-sku Standard_B2s --admin-username azureuser --generate-ssh-keys
az monitor autoscale create --resource-group rg-demo --resource web-vmss --resource-type Microsoft.Compute/virtualMachineScaleSets --min-count 2 --max-count 6 --count 2
```
```bash title="gcloud, Autoscaled VM groups" nocheck
gcloud compute instance-groups managed create web-mig --zone=europe-west1-b --template=web-template --size=2
gcloud compute instance-groups managed set-autoscaling web-mig --zone=europe-west1-b --min-num-replicas=2 --max-num-replicas=6 --target-cpu-utilization=0.6
```
@check
What replaces an unhealthy VM in these groups? || The group itself, using its health check and template.
@end

@concept 3. Managed Kubernetes
@plain
The cloud runs the Kubernetes control plane for you, and you run your workloads on nodes it helps you manage.
@problem
Operating the API server, etcd and upgrades yourself is skilled, risky, round-the-clock work.
@does
- **Names**: AWS EKS; Azure AKS; GCP GKE.
- **What it is**: Provides a managed control plane with cloud integrations for identity, load balancers, storage and node pools.
- **Choose it when**: You already standardise on Kubernetes APIs and Helm or GitOps; Many services need shared scheduling, policies and portability; You need operators and custom controllers.
- **Check in the current docs**: Kubernetes version support windows are short, so plan upgrades and check the current docs; Control plane has a fee on some tiers and node, load balancer and egress costs on top; Add-on versions such as CNI and CSI drivers must be upgraded with the cluster.
@diagram cmp
caption: Managed Kubernetes on the three clouds
cards:
  - {h: "EKS", kind: warn, items: ["Managed node groups, Fargate profiles, Pod Identity"]}
  - {h: "AKS", kind: info, items: ["Node pools, Entra integration, managed upgrades"]}
  - {h: "GKE", kind: ok, items: ["Standard and Autopilot modes, release channels"]}
@h Example
A platform team runs one cluster per environment with node pools for general and GPU work, upgraded each quarter.
@h CLI on each cloud
```bash title="AWS CLI, Managed Kubernetes" nocheck
eksctl create cluster --name demo --region eu-west-1 --nodes 2
aws eks update-kubeconfig --name demo --region eu-west-1
```
```bash title="Azure CLI, Managed Kubernetes" nocheck
az aks create --resource-group rg-demo --name demo --node-count 2 --generate-ssh-keys
az aks get-credentials --resource-group rg-demo --name demo
```
```bash title="gcloud, Managed Kubernetes" nocheck
gcloud container clusters create-auto demo --region=europe-west1
gcloud container clusters get-credentials demo --region=europe-west1
```
@check
Who upgrades the control plane in a managed cluster? || The cloud performs it, but you choose the version and timing and must upgrade the nodes and add-ons.
@end

@concept 4. Serverless containers
@plain
You give the platform a container image and it runs, scales and routes traffic without you managing servers or a cluster.
@problem
Teams want container packaging but not the cost of running Kubernetes or VMs for simple services.
@does
- **Names**: AWS Fargate or App Runner; Azure Container Apps; GCP Cloud Run.
- **What it is**: Runs stateless containers with HTTPS endpoints, scale to zero on some platforms, and revision-based traffic splitting.
- **Choose it when**: Stateless HTTP APIs and workers with spiky traffic; Small teams without platform engineers; Event-driven container jobs.
- **Check in the current docs**: Request timeouts, concurrency and CPU rules differ, so check the current docs; Scale to zero causes cold starts that matter for latency; Fargate runs under ECS or EKS while App Runner is a separate simpler service.
@diagram cmp
caption: Serverless containers on the three clouds
cards:
  - {h: "Fargate or App Runner", kind: warn, items: ["Fargate tasks in ECS or EKS, App Runner services"]}
  - {h: "Container Apps", kind: info, items: ["Environments, revisions, KEDA scaling rules"]}
  - {h: "Cloud Run", kind: ok, items: ["Services and jobs, revisions, concurrency setting"]}
@h Example
A small API ships as one image, scales from zero to many instances on request load, and splits 10 percent of traffic to a new revision.
@h CLI on each cloud
```bash title="AWS CLI, Serverless containers" nocheck
aws apprunner create-service --service-name web --source-configuration '{"ImageRepository":{"ImageIdentifier":"public.ecr.aws/nginx/nginx:latest","ImageRepositoryType":"ECR_PUBLIC","ImageConfiguration":{"Port":"80"}}}'
```
```bash title="Azure CLI, Serverless containers" nocheck
az containerapp create --name web --resource-group rg-demo --environment demo-env --image mcr.microsoft.com/k8se/quickstart:latest --target-port 80 --ingress external
```
```bash title="gcloud, Serverless containers" nocheck
gcloud run deploy web --image=us-docker.pkg.dev/cloudrun/container/hello --region=europe-west1 --allow-unauthenticated
```
@check
Why can scale to zero hurt? || The first request after idle waits for a cold start.
@end

@concept 5. Functions
@plain
Small pieces of code that run only when an event or request arrives, and you pay for execution time.
@problem
Running a server for a tiny task that fires a few times an hour wastes money and effort.
@does
- **Names**: AWS Lambda; Azure Functions; GCP Cloud Functions.
- **What it is**: Runs your handler in a managed runtime, scales per event, and integrates with queues, storage and HTTP triggers.
- **Choose it when**: Glue code between services and webhook handlers; Spiky or rare workloads; Scheduled jobs and file processing.
- **Check in the current docs**: Maximum run time, memory and payload size are limited, so check the current docs; Cold starts and concurrency limits can affect latency and downstream databases; Cloud Functions second generation is built on Cloud Run, so limits follow that model.
@diagram cmp
caption: Functions on the three clouds
cards:
  - {h: "Lambda", kind: warn, items: ["Event source mappings, layers, concurrency controls"]}
  - {h: "Functions", kind: info, items: ["Triggers and bindings, hosting plans"]}
  - {h: "Cloud Functions", kind: ok, items: ["Gen 2 functions, Eventarc triggers"]}
@h Example
An image upload to object storage triggers a function that creates a thumbnail and writes it back.
@h CLI on each cloud
```bash title="AWS CLI, Functions" nocheck
aws lambda create-function --function-name hello --runtime python3.12 --handler app.handler --role arn:aws:iam::111122223333:role/lambda-role --zip-file fileb://function.zip
```
```bash title="Azure CLI, Functions" nocheck
az functionapp create --resource-group rg-demo --name hello-func-123 --storage-account stdemo123 --consumption-plan-location westeurope --runtime python --functions-version 4 --os-type linux
```
```bash title="gcloud, Functions" nocheck
gcloud functions deploy hello --gen2 --runtime=python312 --region=europe-west1 --source=. --entry-point=hello_http --trigger-http --no-allow-unauthenticated
```
@check
When is a function a poor fit? || For long-running, steady, or latency-critical work where a container or VM is cheaper and simpler.
@end

@concept Common mistakes and how to avoid them
@plain
Most incidents with these services come from a small set of repeated mistakes rather than from product defects.
@problem
Teams copy a pattern from one cloud to another without checking how the details differ.
@does
- Do not run Kubernetes for one small stateless API.
- Do not choose functions for steady heavy compute.
- Forgetting regional vCPU quotas.
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
service: Virtual machines
need: describe the workload in one sentence
checked_limits: true
prototype_measured: true
adr_written: true
```
@check
What goes into the ADR after a prototype? || The need, the options compared, the measured result and the decision with its trade-offs.
@end

@concept How to choose
@plain
Choose a service by starting from the requirement, then the team skills, then the cloud already in use, and only then the feature list.
@problem
Picking by feature checklists or fashion leads to costly migrations and unused capability.
@does
- Prefer the managed service on the cloud you already use unless a requirement blocks it.
- Prefer open interfaces (SQL, Kubernetes, Kafka protocol, OpenTelemetry, PromQL) when portability matters.
- Prototype with real data, measure cost and latency, and write an ADR.
- Revisit the decision when scale or price changes.
@diagram flow
caption: A decision path for any service
numbered: true
nodes:
  - "Requirement|latency, scale, compliance|plain"
  - "Skills|what the team can run|info"
  - "Current cloud|reuse identity and network|env"
  - "Prototype|measure cost and speed|app"
  - "ADR|record and review|ok"
@choose Pick a default
Managed service on your cloud | small team, standard need | a hard requirement is missing
Open-source tool on Kubernetes | portability and skills exist | nobody can operate it
Another cloud's service | clear best-in-class need | data egress and latency are unacceptable
@check
What comes before the feature list? || The requirement, then team skills and current cloud.
@end
