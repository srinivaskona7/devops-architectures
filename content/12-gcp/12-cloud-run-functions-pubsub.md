---
title: Cloud Run, Cloud Run functions and Pub/Sub
minutes: 60
objectives:
  - Deploy containers to Cloud Run with revisions, traffic splitting and networking
  - Compare Cloud Run services, jobs and functions and choose between them and GKE
  - Build asynchronous flows with Pub/Sub topics, subscriptions, dead-letter topics and Eventarc
---
Serverless on Google Cloud is container first. Cloud Run is the centre, and functions, jobs and event triggers all run on the same platform.

@concept Cloud Run services
@plain
**Cloud Run** runs stateless containers that listen for HTTP requests (or gRPC), scales them from zero to many, and bills by usage.
@problem
Small and medium services do not justify running and patching a cluster.
@does
- You deploy an image; Cloud Run creates a **revision** and routes traffic to it. Each instance handles many concurrent requests (default 80, configurable up to 1000).
- Settings: CPU and memory, min and max instances, request timeout (up to 60 minutes), CPU always allocated or only during requests, startup CPU boost, execution environment gen2.
- Service identity is a service account; secrets and Cloud SQL connections are mounted by flags.
- **AWS equivalent**: App Runner or ECS Fargate. Main difference: scales to zero, has request-based billing, and traffic splits per revision.
@diagram flow
caption: Request to revision
nodes:
  - "Client|HTTPS URL|ext"
  - "Cloud Run service|traffic split|cp"
  - "Revision 5|current|app"
  - "Instances|autoscaled 0 to N|vm"
@h Deploy
```bash title="Cloud Run deploy" lab
gcloud run deploy shop-web --image=europe-west1-docker.pkg.dev/shop-dev-123456/shop/web:1.0.0 \
  --region=europe-west1 --service-account=shop-api@shop-dev-123456.iam.gserviceaccount.com \
  --min-instances=1 --max-instances=20 --concurrency=80 --cpu=1 --memory=512Mi \
  --set-secrets=DB_PASSWORD=shop-db-password:latest --no-allow-unauthenticated
gcloud run services describe shop-web --region=europe-west1 --format="value(status.url)"
```
@check
What does concurrency control? || How many requests one instance handles at the same time.
@end

@concept Revisions and traffic splitting
@plain
Every deploy makes an immutable **revision**. Traffic can be split by percentage between revisions, and revisions can have tags with their own URL.
@problem
You want canaries and instant rollback without a separate deployment tool.
@does
- `--no-traffic --tag=canary` deploys without serving production traffic, and gives a test URL.
- `update-traffic --to-revisions=A=90,B=10` splits traffic. `--to-latest` follows the newest revision.
- Rollback is a traffic change, not a rebuild.
- Gradual rollouts can be automated by Cloud Deploy for Cloud Run.
- **AWS equivalent**: CodeDeploy canary for ECS or Lambda aliases with weights. Main difference: it is built into the service.
@diagram flow
caption: Canary rollout
nodes:
  - "Deploy rev 6|no traffic, tagged|info"
  - "10 percent|watch errors|warn"
  - "100 percent|promote|ok"
  - "Rollback|send to rev 5|bad"
@h Canary
```bash title="Traffic commands" lab
gcloud run deploy shop-web --image=europe-west1-docker.pkg.dev/shop-dev-123456/shop/web:1.1.0 \
  --region=europe-west1 --no-traffic --tag=canary
gcloud run services update-traffic shop-web --region=europe-west1 --to-tags=canary=10
gcloud run services update-traffic shop-web --region=europe-west1 --to-latest
```
@end

@concept Cloud Run networking and ingress
@plain
Cloud Run services get a `run.app` URL, can be placed behind a load balancer, and can reach private VPC resources through Direct VPC egress or a Serverless VPC Access connector.
@problem
Services need to be public or internal and to reach private databases.
@does
- Ingress settings: all, internal, internal and Cloud Load Balancing. Use the last with a global external Application LB for Cloud Armor, CDN and custom domains.
- Authentication: IAM (`roles/run.invoker`) with identity tokens or public with `allUsers`.
- **Direct VPC egress** assigns instance IPs from a subnet; no connector VMs to manage. Connectors still work. Check the current docs for limits.
- **AWS equivalent**: App Runner VPC connector or Lambda in a VPC. Main difference: Direct VPC egress avoids extra infrastructure.
@diagram flow
caption: Private service behind a load balancer
nodes:
  - "Internet|users|ext"
  - "Global LB and Armor|serverless NEG|cp"
  - "Cloud Run|ingress internal-and-lb|app"
  - "Cloud SQL|private IP via VPC egress|db"
@h Settings
```bash title="Ingress and VPC egress" lab
gcloud run services update shop-web --region=europe-west1 --ingress=internal-and-cloud-load-balancing \
  --network=shop-net --subnet=shop-ew1 --vpc-egress=private-ranges-only
gcloud run services add-iam-policy-binding shop-web --region=europe-west1 \
  --member="serviceAccount:caller@shop-dev-123456.iam.gserviceaccount.com" --role="roles/run.invoker"
```
@check
Which role allows a caller to invoke a private Cloud Run service? || roles/run.invoker.
@end

@concept Cloud Run jobs and Cloud Run functions
@plain
**Cloud Run jobs** run containers to completion (batch, migrations). **Cloud Run functions** (formerly Cloud Functions 2nd gen) deploy source code or functions that run on Cloud Run.
@problem
Not every task is a long-running HTTP server. Some are scheduled jobs or small event handlers.
@does
- Jobs: tasks and parallelism, retries, timeouts, run manually, on a schedule with Cloud Scheduler, or from a workflow.
- Functions: HTTP or event triggered (Pub/Sub, Cloud Storage, Firestore through Eventarc), runtimes for Node.js, Python, Go, Java and more. Built with Cloud Build and buildpacks.
- 1st gen Cloud Functions remains for existing users; use 2nd gen for new work.
- **AWS equivalent**: Lambda and AWS Batch or ECS RunTask. Main difference: functions are packaged as containers on the same platform as Cloud Run.
@diagram cmp
caption: Choosing the Cloud Run form
cards:
  - {h: "Service", kind: app, items: ["HTTP requests", "Scales to zero", "Revisions"]}
  - {h: "Job", kind: info, items: ["Runs to completion", "Parallel tasks", "Scheduled or manual"]}
  - {h: "Function", kind: ok, items: ["Source to container", "Event triggers", "Small handlers"]}
@h Job and function
```bash title="Job" lab
gcloud run jobs create shop-migrate --image=europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:1.0.0 \
  --region=europe-west1 --command=python --args=manage.py,migrate --max-retries=1 --task-timeout=10m
gcloud run jobs execute shop-migrate --region=europe-west1 --wait
gcloud functions deploy order-events --gen2 --runtime=python312 --region=europe-west1 \
  --source=./fn --entry-point=handle --trigger-topic=orders
```
@end

@concept Cloud Run versus GKE
@plain
Cloud Run and GKE both run containers. The choice is control versus operational effort.
@problem
Teams over-use Kubernetes for simple services, or outgrow serverless without a plan.
@does
- Cloud Run is a fit for stateless HTTP services, event handlers and jobs. It is limited for long-lived connections beyond the timeout, special networking, sidecar-heavy designs (supported but limited), and persistent volumes (some storage mounts exist).
- GKE is a fit for stateful sets, custom operators, service meshes, GPUs and many cooperating services.
- Mixed designs are common: web tier on Cloud Run, data services and batch on GKE.
- **AWS equivalent**: Fargate or App Runner versus EKS. Main difference: Cloud Run is closer to a Kubernetes Service with Knative semantics, with less to operate.
@diagram cmp
caption: Tradeoffs
cards:
  - {h: "Cloud Run", kind: ok, items: ["No cluster", "Scale to zero", "Per request billing"]}
  - {h: "GKE", kind: info, items: ["Full Kubernetes API", "Operators and mesh", "Stateful workloads"]}
@choose Where to run a service
Cloud Run | stateless HTTP, spiky traffic, small team | you need DaemonSets, operators or stable pod-to-pod mesh
GKE Autopilot | many services and Kubernetes tooling | a handful of simple services need minimal operations
GKE Standard | special hardware or node tuning | you have no cluster operators
@end

@concept Pub/Sub topics and subscriptions
@plain
**Pub/Sub** is a global messaging service. Publishers send to **topics**; **subscriptions** deliver messages to consumers.
@problem
Services need to be decoupled, buffer spikes and fan out events.
@does
- Delivery types: **pull**, **push** to an HTTPS endpoint (with an OIDC token), **BigQuery** subscription, and **Cloud Storage** subscription.
- At-least-once delivery by default; **exactly-once** delivery is an option on pull subscriptions in a region. Ordering is available with ordering keys.
- Retention up to 31 days; message replay by seeking to a snapshot or time.
- Ack deadline, retry policy with exponential backoff, and dead-letter topics.
- **AWS equivalent**: SNS plus SQS together. Main difference: one service covers both fan-out and queueing.
@diagram flow
caption: Fan out
nodes:
  - "Publisher|orders service|app"
  - "Topic orders|global|cp"
  - "Subscription billing|pull|info"
  - "Subscription analytics|BigQuery|db"
@h Create
```bash title="Topic and subscriptions" lab
gcloud pubsub topics create orders
gcloud pubsub topics create orders-dlq
gcloud pubsub subscriptions create orders-billing --topic=orders --ack-deadline=30 \
  --dead-letter-topic=orders-dlq --max-delivery-attempts=5 --enable-exactly-once-delivery
gcloud pubsub topics publish orders --message='{"id":1001}' --attribute=type=created
gcloud pubsub subscriptions pull orders-billing --auto-ack --limit=5
```
@check
What replaces SNS plus SQS on Google Cloud? || Pub/Sub topics with subscriptions.
@end

@concept Dead letters, push and Eventarc
@plain
Failed messages go to a **dead-letter topic**. **Push** subscriptions call an endpoint such as Cloud Run. **Eventarc** routes events from Google services and Pub/Sub to Cloud Run.
@problem
Poison messages block queues, and consumers need an event source from many services without polling.
@does
- Dead-letter: the Pub/Sub service account needs publisher on the DLQ topic and subscriber on the subscription.
- Push with an authenticated service account sends an OIDC token that Cloud Run validates via `roles/run.invoker`.
- Eventarc triggers filter by event type (for example a Cloud Storage object finalized or an Audit Log event) and deliver CloudEvents.
- **AWS equivalent**: SQS DLQ and EventBridge rules. Main difference: Eventarc uses CloudEvents and Pub/Sub under the hood.
@diagram flow
caption: Event to handler
nodes:
  - "Storage object finalized|source event|ext"
  - "Eventarc trigger|filter|cp"
  - "Cloud Run handler|CloudEvent POST|app"
  - "DLQ topic|after failures|warn"
@h Trigger
```bash title="Eventarc" lab
gcloud eventarc triggers create gcs-upload --location=europe-west1 \
  --destination-run-service=shop-web --destination-run-region=europe-west1 \
  --event-filters="type=google.cloud.storage.object.v1.finalized" \
  --event-filters="bucket=shop-assets-123" --service-account=shop-api@shop-dev-123456.iam.gserviceaccount.com
```
:::tip
Make handlers idempotent. Pub/Sub can redeliver and Eventarc can retry.
:::
@end
