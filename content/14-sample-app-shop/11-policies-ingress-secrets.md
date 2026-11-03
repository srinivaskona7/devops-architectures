---
title: Scaling, safety, network policy, ingress and external secrets
minutes: 55
objectives:
  - Add an HPA and PDB with numbers that match the capacity estimate
  - Apply default-deny NetworkPolicies and allow only the needed flows
  - Expose the web tier with an ALB Ingress and read secrets with External Secrets
---
These manifests live in `deploy/base` too. They are what separates a demo from something you can leave running on a weekend.

@concept HorizontalPodAutoscaler
@plain
The HPA adds or removes pod replicas when average CPU use crosses a target.
@problem
A fixed replica count is either too low on sale day or wasteful at night.
@does
- Targets 70 percent of the CPU request. With a 100m request, scaling starts when average use passes 70m.
- Bounds are set per overlay: dev 1 to 2, staging 2 to 4, prod 3 to 9.
- Formula: desired = ceil(current x currentUsage / target). For 3 pods at 140m average against a 70m target, desired = ceil(3 x 140 / 70) = 6.
- Requires metrics-server (an EKS add-on or Helm chart). Scale-down waits 5 minutes by default (stabilization) to avoid flapping.
@diagram flow
caption: HPA control loop
nodes:
  - "metrics-server|pod CPU|info"
  - "HPA|compares to 70 percent|cp"
  - "Deployment|replicas changed|app"
  - "New pods|ready then serve|ok"
@h base/hpa.yaml
```yaml title="deploy/base/hpa.yaml"
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: orders
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: orders
  minReplicas: 3
  maxReplicas: 9
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: {type: Utilization, averageUtilization: 70}
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: catalog
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: catalog
  minReplicas: 3
  maxReplicas: 9
  metrics:
    - type: Resource
      resource:
        name: cpu
        target: {type: Utilization, averageUtilization: 70}
```
```python title="HPA arithmetic" lab
import math
current, usage, target = 3, 140, 70
print("desired replicas =", math.ceil(current * usage / target))
```
@end

@concept PodDisruptionBudget
@plain
A PDB tells Kubernetes how many pods of an app may be down at once during voluntary disruptions like node drains.
@problem
During a node upgrade, a drain could evict all replicas that happen to sit on the same node and cause an outage.
@does
- `minAvailable: 2` for three replicas allows one pod to be evicted at a time.
- Applies to drains, cluster upgrades and autoscaler scale-down; it does not stop crashes or node failures.
- A PDB with `minAvailable` equal to replicas blocks drains forever. Avoid it.
- Recall the lesson: after a drain, check nodes are uncordoned (managed node group updates handle this; manual drains need `kubectl uncordon`).
@diagram flow
caption: Drain respects the budget
nodes:
  - "kubectl drain node|or upgrade|warn"
  - "Eviction API|asks PDB|cp"
  - "PDB minAvailable 2|allows 1 at a time|info"
  - "Pod moves|then next node|ok"
@h base/pdb.yaml
```yaml title="deploy/base/pdb.yaml"
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: orders
spec:
  minAvailable: 2
  selector:
    matchLabels: {app: orders}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: payments
spec:
  minAvailable: 2
  selector:
    matchLabels: {app: payments}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: catalog
spec:
  minAvailable: 2
  selector:
    matchLabels: {app: catalog}
---
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: web
spec:
  minAvailable: 2
  selector:
    matchLabels: {app: web}
```
:::warn
In dev with one replica, set `minAvailable: 0` or use `maxUnavailable: 1` in the overlay, otherwise node drains hang on the single pod.
:::
@end

@concept Default-deny NetworkPolicy
@plain
A NetworkPolicy that selects every pod and allows nothing. Then add rules for each permitted connection.
@problem
By default every pod can reach every other pod. One compromised container could then reach payments or the database port.
@does
- `podSelector: {}` with both `Ingress` and `Egress` policy types denies everything for the namespace.
- Allow DNS egress to CoreDNS in `kube-system` (UDP and TCP 53), or nothing resolves.
- Needs a CNI that enforces policies. The Amazon VPC CNI supports network policies when enabled; check the current add-on docs. Calico and Cilium are alternatives.
- Test every rule; wrong policies fail silently as timeouts.
@diagram flow
caption: Deny first, then allow
nodes:
  - "default-deny|ingress and egress|bad"
  - "allow DNS|to kube-system|info"
  - "allow web to services|port 8000|ok"
  - "allow to databases|5432 and 6379|ok"
@h base/network-policies.yaml (first part)
```yaml title="deploy/base/network-policies.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels: {kubernetes.io/metadata.name: kube-system}
      ports:
        - {protocol: UDP, port: 53}
        - {protocol: TCP, port: 53}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: web-ingress
spec:
  podSelector:
    matchLabels: {app: web}
  policyTypes: [Ingress, Egress]
  ingress:
    - ports:
        - {protocol: TCP, port: 8080}
  egress:
    - to:
        - podSelector:
            matchExpressions:
              - {key: app, operator: In, values: [catalog, cart, orders]}
      ports:
        - {protocol: TCP, port: 8000}
```
@end

@concept NetworkPolicies between services and to data
@plain
Allow-rules that say exactly who calls whom, following the architecture diagram.
@problem
Too-wide rules defeat the purpose, and too-narrow rules cause mysterious timeouts at 2 am.
@does
- Catalog accepts calls from web and orders. Cart accepts web. Orders accepts web and payments (webhook result). Payments accepts orders and the ingress controller path for webhooks.
- Egress for services to the database uses the VPC CIDR on 5432 and 6379 (the managed databases are outside the cluster, so selectors do not apply; use `ipBlock`).
- Payments additionally has egress to the gateway on 443; in non-prod the mock gateway is a pod.
- Prometheus scraping needs an ingress rule from the `monitoring` namespace.
@diagram layers
caption: Allowed flows
layers:
  - {label: "Callers", nodes: ["web|8080 in|ext", "Prometheus|monitoring ns|info"]}
  - {label: "Services", nodes: ["catalog|from web, orders|app", "cart|from web|app", "orders|from web, payments|app", "payments|from orders, webhook|warn"]}
  - {label: "Data and external", nodes: ["RDS 5432|VPC CIDR|cp", "Redis 6379|VPC CIDR|cp", "UPI provider 443|internet|ext"]}
@h Rules for orders and payments
```yaml title="deploy/base/network-policies-services.yaml"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: orders
spec:
  podSelector:
    matchLabels: {app: orders}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector:
            matchExpressions:
              - {key: app, operator: In, values: [web, payments]}
        - namespaceSelector:
            matchLabels: {kubernetes.io/metadata.name: monitoring}
      ports:
        - {protocol: TCP, port: 8000}
  egress:
    - to:
        - podSelector:
            matchExpressions:
              - {key: app, operator: In, values: [catalog, payments]}
      ports:
        - {protocol: TCP, port: 8000}
    - to:
        - ipBlock: {cidr: 10.20.0.0/16}
      ports:
        - {protocol: TCP, port: 5432}
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: payments
spec:
  podSelector:
    matchLabels: {app: payments}
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - podSelector:
            matchLabels: {app: orders}
        - namespaceSelector:
            matchLabels: {kubernetes.io/metadata.name: monitoring}
      ports:
        - {protocol: TCP, port: 8000}
  egress:
    - to:
        - podSelector:
            matchLabels: {app: orders}
        - podSelector:
            matchLabels: {app: upi-mock}
      ports:
        - {protocol: TCP, port: 8000}
    - to:
        - ipBlock: {cidr: 10.20.0.0/16}
      ports:
        - {protocol: TCP, port: 5432}
    - to:
        - ipBlock: {cidr: 0.0.0.0/0}
      ports:
        - {protocol: TCP, port: 443}
```
:::note
Add the matching Ingress rule for the controller (ALB in IP mode connects from the VPC CIDR) when the webhook path is exposed. Test with `kubectl exec` and `curl` from a pod that should and one that should not be allowed.
:::
@end

@concept Ingress through the AWS Load Balancer Controller
@plain
An Ingress object makes the controller create an Application Load Balancer with HTTPS and send traffic straight to the web pods.
@problem
A Service of type LoadBalancer creates a classic or network load balancer per Service; one ALB with path rules is cheaper and carries TLS and WAF.
@does
- Annotations: `alb.ingress.kubernetes.io/scheme: internet-facing`, `target-type: ip`, `certificate-arn` (ACM), `ssl-redirect`, and health check path `/healthz`.
- Public subnets must carry the `kubernetes.io/role/elb` tag (done in Terraform).
- Rules: `/` goes to web. A second path `/webhooks/upi` goes to payments, and only that path is exposed.
- Attach AWS WAF with the web ACL annotation if required by your security review. See the Kubernetes folder for Ingress and the AWS folder for ALB and ACM.
@diagram flow
caption: Internet to pods
nodes:
  - "Customer|HTTPS|ext"
  - "ALB|ACM certificate, WAF|info"
  - "Target group|pod IPs|cp"
  - "web pods|8080|app"
@h base/ingress.yaml
```yaml title="deploy/base/ingress.yaml"
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP":80},{"HTTPS":443}]'
    alb.ingress.kubernetes.io/ssl-redirect: "443"
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:ap-south-1:111111111111:certificate/replace-in-overlay
spec:
  ingressClassName: alb
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /webhooks/upi
            pathType: Exact
            backend:
              service: {name: payments, port: {number: 8000}}
          - path: /
            pathType: Prefix
            backend:
              service: {name: web, port: {number: 80}}
```
@end

@concept External Secrets operator
@plain
The External Secrets operator reads values from AWS Secrets Manager and creates normal Kubernetes Secrets, refreshing them on a schedule.
@problem
Committing Secrets to Git leaks them; creating them by hand is unrepeatable and unaudited.
@does
- A `ClusterSecretStore` points at Secrets Manager using the IRSA role created in Terraform (no keys).
- An `ExternalSecret` per service maps a Secrets Manager key such as `shop/prod/orders-db` to a Kubernetes Secret named `orders-db`.
- `refreshInterval: 1h` picks up rotated passwords; pods need a restart or a reloader to use new values for env-based secrets.
- Git holds only the mapping, never the value. See the Kubernetes and AWS folders for alternatives like the Secrets Store CSI driver.
@diagram seq
caption: From Secrets Manager to a pod
actors: ["ExternalSecret|in Git|plain", "ESO controller|operator|cp", "Secrets Manager|AWS|ext", "Secret|orders-db|app"]
steps:
  - "0>1: reconcile mapping | req"
  - "1>2: GetSecretValue via IRSA | tls"
  - "2>1: value | resp"
  - "1>3: create or update | req"
  - "note 3..3: pods read via envFrom"
@h base/external-secrets.yaml
```yaml title="deploy/base/external-secrets.yaml"
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: catalog-db
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets
  target:
    name: catalog-db
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: shop/ENV/catalog-db
        property: url
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: cart-redis
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets
  target:
    name: cart-redis
    creationPolicy: Owner
  data:
    - secretKey: REDIS_URL
      remoteRef:
        key: shop/ENV/redis
        property: url
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: orders-db
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets
  target:
    name: orders-db
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: shop/ENV/orders-db
        property: url
---
apiVersion: external-secrets.io/v1
kind: ExternalSecret
metadata:
  name: payments-secrets
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets
  target:
    name: payments-db
    creationPolicy: Owner
  data:
    - secretKey: DATABASE_URL
      remoteRef:
        key: shop/ENV/payments-db
        property: url
    - secretKey: WEBHOOK_SECRET
      remoteRef:
        key: shop/ENV/payments-webhook
        property: secret
```
:::tip
The placeholder `ENV` in the key is replaced per overlay with a Kustomize patch (dev, staging, prod). The API version `external-secrets.io/v1` depends on your operator release; check the current docs, older releases use `v1beta1`.
:::
@end

@concept Store definition and secret layout
@plain
One cluster-wide store object tells the operator how to log in to AWS. The secret names follow a strict convention.
@problem
Without a convention, nobody knows which secret belongs to which environment or service, and a prod secret can be read by dev.
@does
- Names: `shop/<env>/<service>-db`, `shop/<env>/payments-webhook`, `shop/<env>/redis`.
- Each cluster's role may read only `shop/<its env>/*`: the IAM policy resource is `arn:aws:secretsmanager:ap-south-1:<account>:secret:shop/prod/*`.
- Secrets Manager costs about 0.40 USD per secret per month plus API calls; roughly 8 secrets are about 3.20 USD per month.
- Rotation: RDS master secret rotates automatically; per-service passwords rotate through a scheduled Lambda or a manual runbook step.
@diagram flow
caption: Naming and access
nodes:
  - "shop/prod/orders-db|secret name|plain"
  - "IAM policy|shop/prod/* only|warn"
  - "ClusterSecretStore|IRSA auth|cp"
  - "Kubernetes Secret|orders-db|ok"
@h Store and policy
```yaml title="platform/secret-store.yaml"
apiVersion: external-secrets.io/v1
kind: ClusterSecretStore
metadata:
  name: aws-secrets
spec:
  provider:
    aws:
      service: SecretsManager
      region: ap-south-1
      auth:
        jwt:
          serviceAccountRef:
            name: external-secrets
            namespace: external-secrets
```
```json title="IAM policy for the operator role"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"],
      "Resource": "arn:aws:secretsmanager:ap-south-1:222222222222:secret:shop/prod/*"
    }
  ]
}
```
@end
