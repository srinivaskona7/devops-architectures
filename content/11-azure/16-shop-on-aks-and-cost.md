---
title: Deploying the Shop on AKS and managing cost
minutes: 65
objectives:
  - Lay out the Shop architecture on AKS with PostgreSQL and Redis as managed services
  - Deploy the API and web tiers with workload identity, probes and a Gateway route
  - Roll out safely and control spend with budgets and Advisor
---
This page ties the whole section together. The Shop is a containerised web app with an API, PostgreSQL and Redis. Names used here match the earlier pages.

@concept Target architecture
@plain
Web and API run as pods in AKS. PostgreSQL Flexible Server and Azure Cache for Redis are managed services reached over private endpoints. Front Door is the public entry.
@problem
Moving from a laptop or a single cluster to a production layout needs clear boundaries for network, identity and data.
@does
- **AWS equivalent**: CloudFront, ALB, EKS, RDS PostgreSQL, ElastiCache, ECR, Secrets Manager.
- **Main difference**: Azure uses one VNet with delegated and private endpoint subnets, ACR instead of ECR, Key Vault instead of Secrets Manager and workload identity instead of IRSA.
- Public traffic flows Front Door, Application Gateway for Containers, web and API pods. Data never has a public address.
- Everything is one resource group per environment, except shared ACR and monitoring.
@diagram flow
caption: Request path for the Shop
nodes:
  - "Front Door|WAF and TLS|ext"
  - "App Gateway for Containers|Gateway API|cp"
  - "web and api pods|AKS user pool|app"
  - "PostgreSQL and Redis|private endpoints|env"
@h Resource inventory
```bash title="What should exist" lab
az resource list -g rg-shop-prod --query '[].{name:name,type:type}' -o table
az aks show -g rg-shop-prod -n aks-shop-prod --query '{version:kubernetesVersion,plugin:networkProfile.networkPlugin,mode:networkProfile.networkPluginMode}' -o json
```
@check
Which Azure service replaces ECR in this design? || Azure Container Registry.
@end

@concept Foundation with the CLI
@plain
Create the resource group, VNet with subnets, ACR and Log Analytics before the cluster.
@problem
Clusters built before their network and registry end up with wrong subnets and manual fixes.
@does
- **AWS equivalent**: a VPC module, ECR repository and CloudWatch log groups.
- **Main difference**: subnets are regional. Plan one for AKS nodes, one delegated to PostgreSQL, one for private endpoints and one for the application gateway association.
- Use the same region and the `app` and `env` tags everywhere so cost reports work.
@diagram layers
caption: Subnets for the Shop
layers:
  - {label: "vnet-shop 10.20.0.0/16", nodes: ["snet-aks 10.20.0.0/20|nodes|app", "snet-pg 10.20.16.0/24|delegated|env", "snet-pe 10.20.17.0/24|private endpoints|env", "snet-agc 10.20.18.0/24|delegated to AGC|cp"]}
@h Create it
```bash title="Foundation" lab
RG=rg-shop-prod; LOC=westeurope
az group create -n $RG -l $LOC --tags app=shop env=prod owner=platform
az network vnet create -g $RG -n vnet-shop --address-prefixes 10.20.0.0/16 --subnet-name snet-aks --subnet-prefixes 10.20.0.0/20
az network vnet subnet create -g $RG --vnet-name vnet-shop -n snet-pg --address-prefixes 10.20.16.0/24 --delegations Microsoft.DBforPostgreSQL/flexibleServers
az network vnet subnet create -g $RG --vnet-name vnet-shop -n snet-pe --address-prefixes 10.20.17.0/24
az network vnet subnet create -g $RG --vnet-name vnet-shop -n snet-agc --address-prefixes 10.20.18.0/24 --delegations Microsoft.ServiceNetworking/trafficControllers
az acr create -g rg-shared -n acrshopexample --sku Premium
```
@end

@concept The AKS cluster for the Shop
@plain
A Standard-tier cluster with CNI Overlay, Cilium, zones, Entra authentication, workload identity, Key Vault CSI and monitoring.
@problem
Each baseline setting is easy to forget and hard to change after creation.
@does
- **AWS equivalent**: an EKS cluster with managed node groups, IRSA and add-ons.
- **Main difference**: the key creation-time choices are the network plugin and dataplane, private cluster mode and outbound type. Others, such as add-ons and Entra settings, can be updated later.
- Attach ACR at creation to avoid ImagePullBackOff.
- Consider Automatic for a smaller team; the commands below target Standard.
@diagram flow
caption: Cluster baseline
nodes:
  - "Network|overlay and Cilium|info"
  - "Identity|Entra, Azure RBAC, workload identity|cp"
  - "Add-ons|Key Vault CSI, monitoring, policy|env"
  - "Pools|system and apps across zones|app"
@h Create
```bash title="AKS for the Shop" lab
SUBNET=$(az network vnet subnet show -g rg-shop-prod --vnet-name vnet-shop -n snet-aks --query id -o tsv)
az aks create -g rg-shop-prod -n aks-shop-prod --tier standard --location westeurope \
  --network-plugin azure --network-plugin-mode overlay --network-dataplane cilium --pod-cidr 192.168.0.0/16 \
  --vnet-subnet-id "$SUBNET" --zones 1 2 3 --node-count 3 --node-vm-size Standard_D4s_v5 \
  --enable-aad --enable-azure-rbac --enable-oidc-issuer --enable-workload-identity \
  --enable-addons azure-keyvault-secrets-provider,monitoring --attach-acr acrshopexample \
  --auto-upgrade-channel patch --generate-ssh-keys
```
:::note
Flags move between CLI versions. Run `az aks create --help` and compare before using this in automation. For repeatable builds use the Terraform or Bicep from the previous page.
:::
@check
Which settings cannot be changed easily after cluster creation? || The network plugin and dataplane, and the private cluster choice.
@end

@concept Data tier and private connectivity
@plain
Create PostgreSQL in its delegated subnet and Redis behind a private endpoint, with matching private DNS zones linked to the VNet.
@problem
Databases with public endpoints are the first thing attackers scan for.
@does
- **AWS equivalent**: RDS in private subnets and ElastiCache in a subnet group.
- **Main difference**: PostgreSQL with private access has its own private DNS zone requirement, and Redis uses a private endpoint plus `privatelink.redis.cache.windows.net`.
- Store the admin password in Key Vault; applications use Entra tokens for PostgreSQL where the driver supports it, and a Key Vault secret for Redis if token auth is not used.
- Verify name resolution from a pod, not from your laptop.
@diagram flow
caption: Private data tier
nodes:
  - "api pod|workload identity|app"
  - "Private DNS|postgres and redis zones|info"
  - "PostgreSQL|snet-pg, zone redundant HA|env"
  - "Redis|private endpoint in snet-pe|env"
@h Create Postgres and Redis endpoints
```bash title="Data" lab
az postgres flexible-server create -g rg-shop-prod -n pg-shop-prod -l westeurope --tier GeneralPurpose --sku-name Standard_D2ds_v5 \
  --vnet vnet-shop --subnet snet-pg --private-dns-zone privatelink.postgres.database.azure.com \
  --high-availability ZoneRedundant --admin-user shopadmin --admin-password "$PG_ADMIN_PASSWORD" --version 16
az redis create -g rg-shop-prod -n redis-shop-prod -l westeurope --sku Premium --vm-size P1
az network private-endpoint create -g rg-shop-prod -n pe-redis --vnet-name vnet-shop --subnet snet-pe \
  --private-connection-resource-id "$(az redis show -g rg-shop-prod -n redis-shop-prod --query id -o tsv)" --group-id redisCache --connection-name redis
```
```bash title="Test DNS from inside the cluster" lab
kubectl run dnscheck -n shop --rm -it --restart=Never --image=busybox:1.36 -- nslookup pg-shop-prod.postgres.database.azure.com
```
@end

@concept Application manifests
@plain
Two Deployments (web and api) with probes, resource requests, a PodDisruptionBudget, a ServiceAccount for workload identity and secrets from Key Vault.
@problem
Poorly specified pods get evicted during upgrades or scheduled onto the wrong nodes.
@does
- **AWS equivalent**: Kubernetes manifests that you would use on EKS with IRSA instead of workload identity.
- **Main difference**: the ServiceAccount carries `azure.workload.identity/client-id`, the pod template has label `azure.workload.identity/use: "true"` and the Key Vault CSI volume uses the same identity.
- Spread replicas across zones with `topologySpreadConstraints`.
- Images are referenced by digest from ACR.
@diagram layers
caption: Pod specification
layers:
  - {label: "Identity", nodes: ["ServiceAccount api|client id annotation|cp"]}
  - {label: "Pod", nodes: ["api container|probes and limits|app", "CSI volume|pg-password|info"]}
  - {label: "Resilience", nodes: ["3 replicas|spread over zones|ok", "PDB|maxUnavailable 1|ok"]}
@h API Deployment
```yaml title="api-deployment.yaml"
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
        azure.workload.identity/use: "true"
    spec:
      serviceAccountName: api
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: api
      containers:
        - name: api
          image: acrshopexample.azurecr.io/shop/api:1.0.0
          ports:
            - containerPort: 8080
          env:
            - name: PGHOST
              value: pg-shop-prod.postgres.database.azure.com
            - name: REDIS_HOST
              value: redis-shop-prod.redis.cache.windows.net
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: pg-secret
                  key: password
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              memory: 512Mi
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8080
            initialDelaySeconds: 15
          securityContext:
            runAsNonRoot: true
            readOnlyRootFilesystem: true
            allowPrivilegeEscalation: false
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: kv
              mountPath: /mnt/secrets
              readOnly: true
      volumes:
        - name: kv
          csi:
            driver: secrets-store.csi.k8s.io
            readOnly: true
            volumeAttributes:
              secretProviderClass: shop-kv
```
@check
Which pod feature makes the synced pg-secret appear? || The CSI volume that references the SecretProviderClass.
@end

@concept Ingress, TLS and Front Door
@plain
Application Gateway for Containers routes `/api` to the API and everything else to web. Front Door sits in front for the global edge, WAF and certificates.
@problem
Exposing a cluster directly leaves it without a WAF and without global failover.
@does
- **AWS equivalent**: CloudFront with WAF in front of an ALB.
- **Main difference**: Front Door Standard can use a public AGC frontend as origin; Premium adds private origins via Private Link. Lock the origin to the `AzureFrontDoor.Backend` service tag and check the `X-Azure-FDID` header.
- cert-manager issues the origin certificate; Front Door manages the public one.
- Use the Gateway and HTTPRoute shown on the ingress page.
@diagram seq
caption: Request to the Shop
actors: ["Browser|shop.example.com|ext", "Front Door|WAF and cache|cp", "AGC|Gateway API|cp", "api pod|port 8080|app"]
steps:
  - "0>1: HTTPS GET /api/products | tls"
  - "1>2: HTTPS to origin with FDID header | tls"
  - "2>3: route /api to api service | req"
  - "3>2: JSON | resp"
  - "2>1: response | resp"
  - "1>0: response cached or not | resp"
@h Point Front Door at the gateway
```bash title="Origin" lab
FQDN=$(kubectl get gateway shop-gw -n shop -o jsonpath='{.status.addresses[0].value}')
az afd origin create -g rg-net --profile-name fd-shop --origin-group-name og-web --origin-name aks \
  --host-name "$FQDN" --origin-host-header shop.example.com --http-port 80 --https-port 443 --priority 1 --weight 1000
curl -sI https://shop.example.com/api/healthz | head -3
```
@end

@concept Pipeline, rollout and verification
@plain
The pipeline builds the image in ACR, deploys the new digest and waits for the rollout. A failed rollout is reverted.
@problem
Without a rollout gate, a bad image reaches users before anyone notices.
@does
- **AWS equivalent**: CodePipeline with `kubectl rollout status` or Argo Rollouts on EKS.
- **Main difference**: authentication uses the federated GitHub or Azure DevOps identity; the identity needs `Azure Kubernetes Service RBAC Writer` on the namespace and `AcrPush` on the registry.
- Use `kubectl rollout status` with a timeout and `kubectl rollout undo` on failure.
- Observe the release with Container Insights logs and Prometheus metrics.
@diagram flow
caption: Release gate
nodes:
  - "Build|az acr build|app"
  - "Set image|digest pinned|info"
  - "rollout status|timeout 180s|warn"
  - "Undo or done|automatic revert|ok"
@h Deploy and verify
```bash title="Rollout" lab
DIGEST=$(az acr repository show -n acrshopexample --image shop/api:1.0.0 --query digest -o tsv)
kubectl -n shop set image deploy/api api=acrshopexample.azurecr.io/shop/api@"$DIGEST"
kubectl -n shop rollout status deploy/api --timeout=180s || kubectl -n shop rollout undo deploy/api
kubectl -n shop get pods -o wide
```
```text title="KQL to watch errors after a release" nocheck
ContainerLogV2
| where TimeGenerated > ago(15m) and PodNamespace == "shop" and PodName startswith "api"
| summarize errors=countif(LogMessage has "ERROR"), total=count() by bin(TimeGenerated, 1m)
```
@check
What does the pipeline do when the rollout does not finish in time? || It runs kubectl rollout undo to return to the previous revision.
@end

@concept Advisor and cost optimisation checklist
@plain
**Azure Advisor** gives recommendations for cost, reliability, security, performance and operations. Cost items include right-sizing, idle resources and reservation purchases.
@problem
Savings are scattered across hundreds of resources, and nobody has time to find them.
@does
- **AWS equivalent**: Cost Optimization Hub, Compute Optimizer, Trusted Advisor.
- **Main difference**: Advisor is free and covers all five pillars in one list. It reads usage over 7 to 30 days before suggesting changes.
- Checklist for the Shop: right-size node pools from real requests, use Spot for batch pools, buy a savings plan for the steady base, add lifecycle rules to blob logs, cap Log Analytics ingestion and use the Basic table plan for verbose logs, use serverless or auto-pause for non-production databases, and stop non-production clusters off hours.
- Review monthly with a named owner.
@diagram cmp
caption: Where the money goes
cards:
  - {h: "Usually large", kind: warn, items: ["AKS nodes", "PostgreSQL and Redis", "Log Analytics ingestion", "Azure Firewall and NAT"]}
  - {h: "Levers", kind: ok, items: ["Right-size and autoscale", "Spot and savings plan", "Log table plans", "Stop dev out of hours"]}
@h Review recommendations
```bash title="Advisor" lab
az advisor recommendation list --category Cost --query "[].{impact:impact,resource:resourceMetadata.resourceId,problem:shortDescription.problem}" -o table
az consumption usage list --start-date 2026-10-01 --end-date 2026-10-31 --query "[].{svc:consumedService,cost:pretaxCost}" -o table | head -20
```
@check
Name two ways to reduce the cost of a non-production AKS cluster. || Stop it outside working hours and use autoscaling or Spot node pools with small sizes.
@end
