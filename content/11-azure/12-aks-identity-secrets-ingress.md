---
title: AKS identity, secrets and ingress
minutes: 60
objectives:
  - Give pods Azure access with Workload Identity and no secrets
  - Mount Key Vault secrets into pods with the CSI driver
  - Choose an ingress option and publish a service with TLS
---
The Shop pods need to read secrets, talk to PostgreSQL and be reached from the internet. This page wires those paths safely.

@concept Workload Identity on AKS
@plain
A Kubernetes ServiceAccount is linked to an Entra managed identity. The pod gets a projected token and exchanges it for an Entra token.
@problem
Pods need to call Azure services without client secrets in Kubernetes Secrets.
@does
- **AWS equivalent**: IAM Roles for Service Accounts (IRSA) or EKS Pod Identity.
- **Main difference**: the cluster needs the OIDC issuer and workload identity add-on. You create a federated credential on a user-assigned managed identity with subject `system:serviceaccount:<ns>:<sa>`. The pod needs label `azure.workload.identity/use: "true"`. Pod Identity (the older AAD pod identity) is retired.
- SDK `DefaultAzureCredential` picks up the environment variables injected by the webhook.
@diagram seq
caption: Pod to Azure access
actors: ["Pod|projected SA token|app", "Entra ID|federated credential|cp", "Key Vault|or other service|env"]
steps:
  - "0>1: exchange SA token | tls"
  - "1>0: access token | resp"
  - "0>2: call with token | req"
  - "2>0: data | resp"
@h Wire it up
```bash title="Identity and federation" lab
OIDC=$(az aks show -g rg-shop-prod -n aks-shop-prod --query oidcIssuerProfile.issuerUrl -o tsv)
az identity create -g rg-shop-prod -n id-shop-api
az identity federated-credential create -g rg-shop-prod --identity-name id-shop-api -n fc-shop-api \
  --issuer "$OIDC" --subject system:serviceaccount:shop:api --audiences api://AzureADTokenExchange
az identity show -g rg-shop-prod -n id-shop-api --query clientId -o tsv
```
```yaml title="serviceaccount-api.yaml"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: api
  namespace: shop
  annotations:
    azure.workload.identity/client-id: 00000000-0000-0000-0000-000000000001
  labels:
    azure.workload.identity/use: "true"
```
@check
Which pod label opts in to workload identity token injection? || azure.workload.identity/use set to "true".
@end

@concept Azure Key Vault
@plain
**Key Vault** stores secrets, keys and certificates with access control, audit logs and optional HSM backing.
@problem
Secrets in Git, environment files and chat are the usual cause of leaks.
@does
- **AWS equivalent**: Secrets Manager plus KMS plus ACM certificates in one service.
- **Main difference**: use the **RBAC permission model** (not legacy access policies), e.g. `Key Vault Secrets User`. Enable soft delete and purge protection. Standard and Premium (HSM) tiers; Managed HSM is a separate service.
- Private endpoint plus `privatelink.vaultcore.azure.net` DNS.
- Versioned secrets with expiry and rotation events through Event Grid.
@diagram layers
caption: Key Vault contents
layers:
  - {label: "Objects", nodes: ["Secrets|passwords, tokens|app", "Keys|RSA, EC, wrap and sign|app", "Certificates|issue and renew|app"]}
  - {label: "Controls", nodes: ["RBAC|data plane roles|cp", "Network rules|private endpoint|cp", "Soft delete and purge protection|recovery|ok"]}
@h Create and store a secret
```bash title="Key Vault" lab
az keyvault create -g rg-shop-prod -n kv-shop-prod-001 --enable-rbac-authorization true --enable-purge-protection true --public-network-access Disabled
az role assignment create --assignee-object-id "$(az identity show -g rg-shop-prod -n id-shop-api --query principalId -o tsv)" \
  --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope "$(az keyvault show -n kv-shop-prod-001 --query id -o tsv)"
az keyvault secret set --vault-name kv-shop-prod-001 -n pg-password --value "$PG_ADMIN_PASSWORD"
```
@end

@concept Key Vault CSI driver
@plain
The Secrets Store CSI driver with the Azure provider mounts Key Vault secrets as files in a pod and can sync them to Kubernetes Secrets.
@problem
Applications read configuration from files or environment variables, not from the Key Vault API.
@does
- **AWS equivalent**: Secrets Store CSI driver with the AWS provider, or External Secrets Operator.
- **Main difference**: enabled as an AKS add-on (`azure-keyvault-secrets-provider`). A `SecretProviderClass` names the vault and objects; authentication uses workload identity. Rotation is optional and polls on an interval.
- A mounted volume is required for the sync to a Kubernetes Secret to happen.
- External Secrets Operator is a popular alternative with GitOps.
@diagram flow
caption: Secret to pod
nodes:
  - "Key Vault|secret pg-password|env"
  - "CSI driver|workload identity auth|cp"
  - "Volume mount|file in the pod|info"
  - "Pod|reads the file|app"
@h Enable and use
```bash title="Add-on" lab
az aks enable-addons -g rg-shop-prod -n aks-shop-prod --addons azure-keyvault-secrets-provider --enable-secret-rotation
```
```yaml title="secretproviderclass.yaml"
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: shop-kv
  namespace: shop
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    clientID: 00000000-0000-0000-0000-000000000001
    keyvaultName: kv-shop-prod-001
    tenantId: 00000000-0000-0000-0000-000000000002
    objects: |
      array:
        - |
          objectName: pg-password
          objectType: secret
  secretObjects:
    - secretName: pg-secret
      type: Opaque
      data:
        - objectName: pg-password
          key: password
```
@check
What must a pod do for a synced Kubernetes Secret to appear? || Mount the CSI volume that references the SecretProviderClass.
@end

@concept Ingress options on AKS
@plain
Several ways exist to bring HTTP traffic into AKS: a Service of type LoadBalancer, the managed NGINX app routing add-on, Application Gateway for Containers, Istio gateway, or your own controller.
@problem
Each option differs in features, cost, WAF support and who operates it.
@does
- **AWS equivalent**: AWS Load Balancer Controller (ALB and NLB), NGINX ingress.
- **Main difference**: the **application routing add-on** is a managed NGINX with Key Vault and Azure DNS integration. **Application Gateway for Containers** is the evolution of AGIC, uses the Gateway API and talks to pods directly. AGIC (Application Gateway Ingress Controller) is the older model; check the current guidance before choosing.
- Ingress NGINX community project has announced retirement; check the current state and Kubernetes Gateway API migration docs.
- Pair any option with Front Door for global WAF.
@diagram cmp
caption: Options
cards:
  - {h: "App routing add-on", kind: info, items: ["Managed NGINX", "Ingress API", "Key Vault certs, DNS"]}
  - {h: "App Gateway for Containers", kind: ok, items: ["Gateway API", "WAF capable", "Direct to pods"]}
  - {h: "Service LoadBalancer", kind: warn, items: ["Layer 4 only", "One IP per service", "Simple TCP"]}
@choose Pick ingress
App routing add-on | a managed NGINX is enough for standard HTTP routing | you need a WAF at the cluster edge
Application Gateway for Containers | Gateway API, WAF and fast updates | you need non-HTTP protocols
Service of type LoadBalancer | raw TCP or UDP | you want host and path routing
Istio or Envoy gateway | service mesh and advanced traffic policy | the team has no mesh experience
@end

@concept Application Gateway for Containers
@plain
**Application Gateway for Containers (AGC)** is a layer 7 service managed by Azure that is configured through Kubernetes Gateway API objects, with the data plane outside your cluster.
@problem
AGIC reconfigured a regular Application Gateway slowly and shared its capacity with other apps. Teams wanted faster updates and standard APIs.
@does
- **AWS equivalent**: AWS Load Balancer Controller with ALB targeting pods by IP (Gateway API support evolves).
- **Main difference**: three parts: the **ALB Controller** in the cluster, the **Traffic Controller** Azure resource and an association with a delegated subnet (`Microsoft.ServiceNetworking/trafficControllers`). Supports traffic splitting, header rewrites, mTLS and WAF; check current feature status.
- It uses workload identity for the controller.
- Replaces AGIC for new designs.
@diagram flow
caption: AGC architecture
nodes:
  - "Client|HTTPS|ext"
  - "AGC frontend|managed outside cluster|cp"
  - "Gateway and HTTPRoute|Gateway API objects|info"
  - "Pods|direct pod targets|app"
@h Gateway and route
```yaml title="gateway-agc.yaml"
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: shop-gw
  namespace: shop
  annotations:
    alb.networking.azure.io/alb-name: alb-shop
    alb.networking.azure.io/alb-namespace: alb-infra
spec:
  gatewayClassName: azure-alb-external
  listeners:
    - name: https
      port: 443
      protocol: HTTPS
      tls:
        mode: Terminate
        certificateRefs:
          - name: shop-tls
      allowedRoutes:
        namespaces:
          from: Same
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: shop
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
    - backendRefs:
        - name: web
          port: 80
```
@check
Which Kubernetes API does AGC use for configuration? || The Gateway API.
@end

@concept TLS certificates with cert-manager and Key Vault
@plain
Certificates can come from Let's Encrypt via cert-manager, or be stored and renewed in Key Vault with an integrated CA.
@problem
Manual certificate renewal causes avoidable outages.
@does
- **AWS equivalent**: ACM certificates and cert-manager.
- **Main difference**: ACM issues certificates only for AWS services. In Azure, Front Door and App Service offer managed certificates, but for ingress inside AKS you normally use cert-manager or Key Vault certificates mounted through the CSI driver.
- cert-manager DNS-01 solver can use Azure DNS with workload identity.
- Terminate TLS at the edge (Front Door) and re-encrypt to the origin for defence in depth.
@diagram flow
caption: Automated renewal
nodes:
  - "Certificate resource|cert-manager|cp"
  - "ClusterIssuer|ACME and Azure DNS|info"
  - "Secret shop-tls|renewed automatically|ok"
  - "Gateway or Ingress|serves HTTPS|app"
@h ClusterIssuer with Azure DNS
```yaml title="clusterissuer.yaml"
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: platform@example.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - dns01:
          azureDNS:
            subscriptionID: 00000000-0000-0000-0000-000000000000
            resourceGroupName: rg-net
            hostedZoneName: example.com
            environment: AzurePublicCloud
            managedIdentity:
              clientID: 00000000-0000-0000-0000-000000000003
```
@end

@concept Application routing add-on with managed NGINX
@plain
The **application routing add-on** runs a managed NGINX ingress controller in the cluster and can fetch certificates from Key Vault and publish records to Azure DNS.
@problem
Installing and patching an ingress controller yourself adds another component to keep current.
@does
- **AWS equivalent**: the NGINX ingress controller or AWS Load Balancer Controller in Ingress mode.
- **Main difference**: Microsoft ships the controller version and CVE fixes, and you use the ingress class `webapprouting.kubernetes.azure.com`. Check the current docs, because the upstream NGINX project has announced retirement and Microsoft guidance may point to Gateway API based options.
- The controller gets an Azure load balancer IP, public or internal.
- Good for dev, test and simple production routing without WAF.
@diagram flow
caption: Managed ingress path
nodes:
  - "Client|HTTPS|ext"
  - "Azure Load Balancer|public or internal IP|cp"
  - "Managed NGINX|webapprouting class|info"
  - "Service and pods|shop web|app"
@h Enable and use
```bash title="Add-on" lab
az aks approuting enable -g rg-shop-prod -n aks-shop-prod
kubectl get pods -n app-routing-system
```
```yaml title="ingress-web.yaml"
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: web
  namespace: shop
spec:
  ingressClassName: webapprouting.kubernetes.azure.com
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
```
@check
Which ingress class does the app routing add-on use? || webapprouting.kubernetes.azure.com.
@end
