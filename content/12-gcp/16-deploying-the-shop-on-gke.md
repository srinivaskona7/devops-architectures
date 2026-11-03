---
title: Deploying the Shop on GKE
minutes: 90
objectives:
  - Provision the Shop infrastructure on Google Cloud with private Cloud SQL, Memorystore and an Autopilot cluster
  - Deploy the web, API, Postgres client and Redis configuration using Workload Identity and the Gateway API
  - Roll out, observe, upgrade and tear down the Shop with a clear mapping to the AWS version
---
The Shop is a containerised web app with a web front end, an API, a Postgres database and a Redis cache. On AWS it runs on EKS with RDS and ElastiCache. Here the same design runs on GKE Autopilot with Cloud SQL and Memorystore.

@concept Shop architecture on Google Cloud
@plain
The web and API run as Deployments on GKE Autopilot. Postgres is Cloud SQL and Redis is Memorystore, both on private IPs in the same VPC. A global external Application Load Balancer fronts the cluster through a Gateway.
@problem
You want the same application on a second cloud with a clear component map, so you can compare operations and cost.
@does
- Edge: Cloud DNS, Certificate Manager, Cloud Armor, global Application LB.
- Compute: GKE Autopilot regional cluster, Pods for `web` and `api`.
- Data: Cloud SQL for PostgreSQL (HA, private IP), Memorystore for Redis.
- Identity: Workload Identity Federation for GKE and Secret Manager.
- **AWS equivalent**: Route 53, ACM, WAF, ALB, EKS, RDS, ElastiCache, IRSA, Secrets Manager. Main difference: the load balancer is global and projects replace accounts.
@diagram layers
caption: Shop on Google Cloud
layers:
  - {label: "Edge", nodes: ["Cloud DNS|shop.example.com|ext", "Cloud Armor|WAF|bad", "Global LB|Gateway|cp"]}
  - {label: "GKE Autopilot", nodes: ["web|Deployment|app", "api|Deployment|app"]}
  - {label: "Data", nodes: ["Cloud SQL|PostgreSQL private IP|db", "Memorystore|Redis|warn"]}
@h Component map
| Layer | AWS | Google Cloud |
|---|---|---|
| Ingress | ALB Ingress | Gateway API and global Application LB |
| Pods | EKS | GKE Autopilot |
| Database | RDS PostgreSQL | Cloud SQL for PostgreSQL |
| Cache | ElastiCache Redis | Memorystore for Redis |
| Pod identity | IRSA | Workload Identity Federation for GKE |
| Images | ECR | Artifact Registry |
@check
Which Google service replaces ElastiCache? || Memorystore.
@end

@concept Prepare the project, network and private service access
@plain
Create the project, enable APIs, build the VPC, and reserve a range for private services access so Cloud SQL and Memorystore can have private IPs.
@problem
Managed databases do not live in your subnet; they connect through a peering or Private Service Connect.
@does
- Reserve a range with `gcloud compute addresses create --purpose=VPC_PEERING`, then create the service networking connection.
- Memorystore for Redis with `PRIVATE_SERVICE_ACCESS` uses the same range.
- Create Cloud NAT for egress from private nodes.
- **AWS equivalent**: DB subnet groups and security groups. Main difference: connectivity is a peering to Google's producer network.
@diagram flow
caption: Order of work
numbered: true
nodes:
  - "Project and APIs|billing linked|cp"
  - "VPC and subnet|pod ranges|info"
  - "Private services range|VPC peering|warn"
  - "NAT|egress|ok"
@h Commands
```bash title="Network for the Shop" lab
export PROJECT=shop-dev-123456 REGION=europe-west1
gcloud config set project $PROJECT
gcloud compute networks create shop-net --subnet-mode=custom
gcloud compute networks subnets create shop-ew1 --network=shop-net --region=$REGION --range=10.10.0.0/20 \
  --secondary-range=pods=10.64.0.0/14,services=10.68.0.0/20 --enable-private-ip-google-access
gcloud compute addresses create google-managed-services --global --purpose=VPC_PEERING \
  --prefix-length=20 --network=shop-net
gcloud services vpc-peerings connect --service=servicenetworking.googleapis.com \
  --ranges=google-managed-services --network=shop-net
gcloud compute routers create shop-router --network=shop-net --region=$REGION
gcloud compute routers nats create shop-nat --router=shop-router --region=$REGION \
  --auto-allocate-nat-external-ips --nat-all-subnet-ip-ranges
```
@end

@concept Create Cloud SQL, Memorystore and the cluster
@plain
Provision the data stores first, then the Autopilot cluster in the same VPC.
@problem
The application needs its dependencies ready, with private addressing and secrets stored safely.
@does
- Cloud SQL: PostgreSQL 16, regional HA, private IP only, backups and PITR on.
- Memorystore: Standard tier Redis with in-transit encryption.
- GKE Autopilot: regional, private nodes, release channel Regular, Gateway API enabled by default on recent versions (check your version).
- Store the DB password in Secret Manager.
- **AWS equivalent**: Terraform modules for RDS, ElastiCache and EKS. Main difference: fewer resources, since the cluster has no node group to define.
@diagram flow
caption: Data first, then compute
nodes:
  - "Cloud SQL|private IP|db"
  - "Memorystore|private IP|warn"
  - "Secret Manager|DB password|info"
  - "GKE Autopilot|regional|cp"
@h Provision
```bash title="Data stores and cluster" lab
gcloud sql instances create shop-pg --database-version=POSTGRES_16 --edition=ENTERPRISE \
  --tier=db-custom-2-7680 --region=$REGION --availability-type=REGIONAL \
  --network=projects/$PROJECT/global/networks/shop-net --no-assign-ip --enable-point-in-time-recovery
gcloud sql databases create shop --instance=shop-pg
DB_PASS=$(openssl rand -base64 24)
gcloud sql users create shop_app --instance=shop-pg --password="$DB_PASS"
printf '%s' "$DB_PASS" | gcloud secrets create shop-db-password --data-file=-
gcloud redis instances create shop-cache --region=$REGION --tier=STANDARD --size=1 \
  --network=shop-net --connect-mode=PRIVATE_SERVICE_ACCESS
gcloud container clusters create-auto shop-auto --region=$REGION --network=shop-net --subnetwork=shop-ew1 \
  --cluster-secondary-range-name=pods --services-secondary-range-name=services \
  --enable-private-nodes --release-channel=regular
gcloud container clusters get-credentials shop-auto --region=$REGION
```
:::warn
Some flags and defaults change between gcloud releases. Run each command with `--help` if a flag is rejected.
:::
@check
Why store the DB password in Secret Manager rather than a manifest? || So it is access controlled, versioned, audited and never committed to Git.
@end

@concept Image build and Workload Identity for the Shop
@plain
Build the images into Artifact Registry. Give the API Pods access to Secret Manager and Cloud SQL through their Kubernetes service account, without any key.
@problem
Pods need to read secrets and connect to Cloud SQL, and shared node credentials would be too broad.
@does
- Create a KSA `shop-api` in namespace `shop` and grant IAM roles directly to it: `roles/secretmanager.secretAccessor` on the secret and `roles/cloudsql.client`.
- Connect to Cloud SQL private IP directly, or use the Cloud SQL Auth Proxy sidecar for IAM authentication.
- Build with Cloud Build or GitHub Actions (see the CI/CD file).
- **AWS equivalent**: ECR plus IRSA role. Main difference: the IAM principal is a federated identity string, not a role to assume.
@diagram seq
caption: API reads its secret
actors: ["api Pod|KSA shop-api|app", "Workload pool|federated identity|cp", "Secret Manager|db password|db"]
steps:
  - "0>1: Pod token exchange | tls"
  - "1>0: federated token | resp"
  - "0>2: access secret version | req"
  - "2>0: payload | resp"
@h Build and grant
```bash title="Image and identity" lab
gcloud artifacts repositories create shop --repository-format=docker --location=$REGION
gcloud builds submit ./api --tag=$REGION-docker.pkg.dev/$PROJECT/shop/api:1.0.0
gcloud builds submit ./web --tag=$REGION-docker.pkg.dev/$PROJECT/shop/web:1.0.0
PROJECT_NUMBER=$(gcloud projects describe $PROJECT --format="value(projectNumber)")
MEMBER="principal://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${PROJECT}.svc.id.goog/subject/ns/shop/sa/shop-api"
gcloud secrets add-iam-policy-binding shop-db-password --member="$MEMBER" --role=roles/secretmanager.secretAccessor
gcloud projects add-iam-policy-binding $PROJECT --member="$MEMBER" --role=roles/cloudsql.client
```
@end

@concept Kubernetes manifests for the Shop
@plain
The API and web run as Deployments with probes, resource requests (which Autopilot bills), a Service each, and configuration through environment variables and a mounted secret.
@problem
Autopilot schedules based on resource requests, so missing requests lead to defaults you did not choose.
@does
- Set `requests` equal to what you need; Autopilot may adjust to its minimums and ratios.
- Use readiness probes that the load balancer health check also respects; the API exposes `/healthz` on 8080.
- Spread replicas across zones with `topologySpreadConstraints`.
- Redis and Postgres hosts are placed in a ConfigMap; the password comes from the CSI secret mount.
- **AWS equivalent**: the same manifests used on EKS. Main difference: only the ServiceAccount, Ingress and storage details change.
@diagram flow
caption: Objects
nodes:
  - "Namespace shop|isolation|env"
  - "Deployment api|3 replicas|app"
  - "Service api|ClusterIP|info"
  - "ConfigMap and secret|host, password|warn"
@h API Deployment
```yaml title="api.yaml"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: shop-api
  namespace: shop
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: shop-config
  namespace: shop
data:
  DB_HOST: "10.20.0.3"
  DB_NAME: "shop"
  DB_USER: "shop_app"
  REDIS_HOST: "10.20.1.4"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      serviceAccountName: shop-api
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: api
      containers:
        - name: api
          image: europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:1.0.0
          ports:
            - containerPort: 8080
          envFrom:
            - configMapRef:
                name: shop-config
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
          volumeMounts:
            - name: secrets
              mountPath: /var/run/secrets/shop
              readOnly: true
      volumes:
        - name: secrets
          csi:
            driver: secrets-store-gke.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: shop-secrets
---
apiVersion: v1
kind: Service
metadata:
  name: api
  namespace: shop
spec:
  selector:
    app: api
  ports:
    - port: 8080
      targetPort: 8080
```
@check
Why set resource requests on Autopilot? || They determine scheduling and what you are billed.
@end

@concept Expose the Shop with Gateway, certificate and Cloud Armor
@plain
A Gateway creates the global load balancer, an HTTPRoute sends `/api` to the API and everything else to the web, and a policy attaches Cloud Armor.
@problem
Users need HTTPS on one hostname with routing, a managed certificate, and edge protection.
@does
- Reserve a global static IP and point DNS to it.
- Create a Certificate Manager certificate and map, and reference it on the Gateway.
- Use `GCPBackendPolicy` to attach a Cloud Armor policy and tune timeouts for the API Service. Check the current API version for the policy.
- Add an HTTP to HTTPS redirect route.
- **AWS equivalent**: ALB with ACM and WAF. Main difference: policy attachments are separate custom resources.
@diagram flow
caption: Public path
nodes:
  - "DNS A record|static IP|ext"
  - "Gateway|HTTPS, cert map|cp"
  - "HTTPRoute|/api and /|info"
  - "Services|api and web|app"
@h Policy attached to the API Service
```yaml title="backend-policy.yaml"
apiVersion: networking.gke.io/v1
kind: GCPBackendPolicy
metadata:
  name: api-policy
  namespace: shop
spec:
  default:
    securityPolicy: shop-waf
    timeoutSec: 30
  targetRef:
    group: ""
    kind: Service
    name: api
```
```bash title="Static IP and certificate" lab
gcloud compute addresses create shop-ip --global
gcloud certificate-manager dns-authorizations create shop-auth --domain=shop.example.com
gcloud certificate-manager certificates create shop-cert --domains=shop.example.com --dns-authorizations=shop-auth
gcloud certificate-manager maps create shop-map
gcloud certificate-manager maps entries create shop-entry --map=shop-map --hostname=shop.example.com --certificates=shop-cert
kubectl apply -f gateway.yaml -f backend-policy.yaml
kubectl -n shop get gateway,httproute
```
:::note
Reuse the Gateway and HTTPRoute from the GKE in depth file, and attach the certificate map to the Gateway with the annotation `networking.gke.io/certmap`. Verify current field names in the docs.
:::
@end

@concept Verify, observe and roll out
@plain
After deployment, check health end to end, enable monitoring, and roll out new versions with a rolling update and a canary.
@problem
A deployed app is not a healthy app. You need proof and a safe update path.
@does
- Check the LB: `kubectl -n shop describe gateway shop-gw`, then `curl -I https://shop.example.com/api/healthz`.
- Managed Prometheus scrapes `/metrics` through `PodMonitoring`; create the alert from the observability file.
- Roll out with `kubectl set image` and `kubectl rollout status`; undo with `kubectl rollout undo`.
- For canary, add a second backend with weights on the HTTPRoute.
- **AWS equivalent**: the same kubectl workflow on EKS. Main difference: Gateway weights replace ALB weighted target groups.
@diagram flow
caption: Rollout loop
nodes:
  - "Set new image|1.1.0|app"
  - "Rolling update|surge pods|info"
  - "Check SLO|errors and latency|warn"
  - "Undo if needed|rollout undo|bad"
@h Commands
```bash title="Roll out and verify" lab
kubectl -n shop set image deployment/api api=europe-west1-docker.pkg.dev/shop-dev-123456/shop/api:1.1.0
kubectl -n shop rollout status deployment/api --timeout=180s
kubectl -n shop get pods -o wide
curl -fsS https://shop.example.com/api/healthz
kubectl -n shop rollout undo deployment/api
```
```yaml title="canary-route.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: api-canary
  namespace: shop
spec:
  parentRefs:
    - name: shop-gw
  hostnames: ["shop.example.com"]
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /api
      backendRefs:
        - name: api
          port: 8080
          weight: 95
        - name: api-v2
          port: 8080
          weight: 5
```
@check
How do you roll back a bad Deployment image? || kubectl rollout undo, then investigate.
@end

@concept Upgrades, cost and teardown for the Shop
@plain
Day-two work is keeping the cluster current, watching cost, and removing the stack cleanly when finished.
@problem
Demo stacks left running cost money, and unplanned upgrades surprise teams.
@does
- Upgrades: the release channel upgrades the control plane and Autopilot nodes. Use maintenance windows, exclusions and PDBs for the Shop Pods.
- Cost: Autopilot bills per Pod requests; Cloud SQL HA doubles instance cost; Memorystore Standard bills per GB. Use budgets and labels (`app=shop`).
- Teardown: delete the cluster, Memorystore, Cloud SQL (remove deletion protection), the private services connection, then the network. Terraform destroy handles the order.
- **AWS equivalent**: EKS upgrades and Terraform destroy. Main difference: Google upgrades automatically, and the peering must be removed before deleting the VPC.
@diagram flow
caption: Teardown order
numbered: true
nodes:
  - "Gateway and Pods|release LB|warn"
  - "Cluster|delete|bad"
  - "Cloud SQL and Redis|delete|bad"
  - "Peering then VPC|last|info"
@h Cleanup commands
```bash title="Teardown" lab
kubectl delete namespace shop
gcloud container clusters delete shop-auto --region=$REGION --quiet
gcloud redis instances delete shop-cache --region=$REGION --quiet
gcloud sql instances patch shop-pg --no-deletion-protection --quiet
gcloud sql instances delete shop-pg --quiet
gcloud services vpc-peerings delete --service=servicenetworking.googleapis.com --network=shop-net --quiet
gcloud compute addresses delete google-managed-services --global --quiet
gcloud compute networks delete shop-net --quiet
```
:::danger
These commands delete data. Confirm the project and take a backup first.
:::
@end
