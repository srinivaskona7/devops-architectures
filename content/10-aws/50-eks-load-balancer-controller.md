---
title: AWS Load Balancer Controller and ingress
minutes: 50
objectives:
  - Install the AWS Load Balancer Controller with the right IAM permissions
  - Expose services with ALB Ingress and NLB Services
  - Use target types, health checks and certificate annotations correctly
---
Kubernetes asks for a load balancer; on EKS the AWS Load Balancer Controller (LBC) turns that request into a real ALB or NLB. It replaces the legacy in-tree controller.

@concept What the controller does
@plain
The LBC watches `Ingress` and `Service` objects. For an Ingress with the `alb` class it builds an Application Load Balancer; for a Service of type `LoadBalancer` with the right annotation it builds a Network Load Balancer.
@problem
Without it, Services create old Classic Load Balancers, and there is no native way to get path routing, WAF, or direct-to-pod targets.
@does
- Runs as a Deployment in `kube-system`, with IAM permissions to manage ELB, security groups and target groups.
- Discovers subnets by tag: `kubernetes.io/role/elb` for internet-facing, `kubernetes.io/role/internal-elb` for internal.
- Registers pods directly (`target-type: ip`) or nodes via NodePort (`instance`).
- Manages security groups and can share one ALB across many Ingress resources through `IngressGroup`.
@diagram flow
caption: From Ingress to load balancer
numbered: true
nodes:
  - "Ingress or Service|annotations|app"
  - "LB Controller|watches API|cp"
  - "ELB API|creates ALB or NLB|ext"
  - "Target group|pod IPs registered|ok"
@h Install
```bash title="Install with Helm" nocheck
curl -o iam-policy.json https://raw.githubusercontent.com/kubernetes-sigs/aws-load-balancer-controller/main/docs/install/iam_policy.json
aws iam create-policy --policy-name AWSLoadBalancerControllerIAMPolicy --policy-document file://iam-policy.json
eksctl create iamserviceaccount --cluster shop-prod --namespace kube-system \
  --name aws-load-balancer-controller \
  --attach-policy-arn arn:aws:iam::111122223333:policy/AWSLoadBalancerControllerIAMPolicy --approve
helm repo add eks https://aws.github.io/eks-charts && helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system \
  --set clusterName=shop-prod --set serviceAccount.create=false \
  --set serviceAccount.name=aws-load-balancer-controller
```
@check
Which subnet tag selects internet-facing load balancer subnets? || kubernetes.io/role/elb=1.
@end

@concept ALB Ingress
@plain
An Ingress with `ingressClassName: alb` creates an ALB with listeners and rules from the Ingress paths and annotations.
@problem
You want one HTTPS entry point with host and path routing, TLS from ACM, and optional WAF, without running your own proxy.
@does
- `alb.ingress.kubernetes.io/scheme: internet-facing | internal`.
- `target-type: ip` sends traffic directly to pod IPs, skipping NodePort hops; requires VPC CNI.
- `listen-ports`, `certificate-arn`, `ssl-redirect` configure HTTPS; ACM supplies and renews the certificate.
- `healthcheck-path`, `success-codes` control target health.
- `wafv2-acl-arn` attaches a WAF web ACL.
- `group.name` merges several Ingress objects into one ALB to save cost.
@diagram flow
caption: Internet to pod with an ALB
nodes:
  - "User|HTTPS|ext"
  - "ALB|TLS from ACM, WAF|cp"
  - "Target group|ip targets|info"
  - "Pods|port 8080|app"
@h Ingress
```yaml title="Shop Ingress"
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  namespace: shop
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTP":80},{"HTTPS":443}]'
    alb.ingress.kubernetes.io/ssl-redirect: "443"
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:us-east-1:111122223333:certificate/11111111-2222-3333-4444-555555555555
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/group.name: shop-public
spec:
  ingressClassName: alb
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: orders
                port:
                  number: 80
          - path: /
            pathType: Prefix
            backend:
              service:
                name: web
                port:
                  number: 80
```
@check
Why prefer target-type ip? || The ALB talks straight to pods, avoiding the extra NodePort hop and giving even load distribution.
@end

@concept NLB Services
@plain
A Service of type `LoadBalancer` with the controller's annotations creates a Network Load Balancer for TCP, UDP or TLS traffic.
@problem
Non-HTTP protocols, static IPs, extremely low latency or PrivateLink exposure need layer 4, not an ALB.
@does
- Set `service.beta.kubernetes.io/aws-load-balancer-type: external` and `aws-load-balancer-nlb-target-type: ip`.
- `aws-load-balancer-scheme: internet-facing` or `internal`.
- NLB supports Elastic IPs per AZ (`aws-load-balancer-eip-allocations`) and security groups on the NLB.
- Preserve client IP with target-type ip by default; mind the proxy protocol option for ip-mode.
- Use `loadBalancerClass: service.k8s.aws/nlb` on modern versions.
@diagram flow
caption: TCP service through an NLB
nodes:
  - "Client|TCP 5432 or gRPC|ext"
  - "NLB|static IP per AZ|cp"
  - "Pods|ip targets|app"
@h Service
```yaml title="Internal NLB for a gRPC service"
apiVersion: v1
kind: Service
metadata:
  name: payments-grpc
  namespace: shop
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-scheme: internal
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
spec:
  type: LoadBalancer
  loadBalancerClass: service.k8s.aws/nlb
  selector:
    app: payments
  ports:
    - port: 443
      targetPort: 9090
      protocol: TCP
```
@check
When would you pick an NLB over an ALB? || For non-HTTP protocols, static IPs, or very high throughput with low latency.
@end

@concept Health checks, graceful shutdown and readiness gates
@plain
A load balancer sends traffic only to targets marked healthy. Deployments can drop requests if pods leave the target group late or join too early.
@problem
Rolling updates produce brief 502 and 504 errors when a terminating pod is still receiving requests from the ALB.
@does
- Add a **pod readiness gate** by labeling the namespace `elbv2.k8s.aws/pod-readiness-gate-inject=enabled`; the pod is Ready only once the target group reports it healthy.
- Add a `preStop` sleep (about 15 to 30 seconds) so the ALB deregisters the target before the app stops, and set `terminationGracePeriodSeconds` higher than that.
- Make the ALB deregistration delay (`deregistration_delay.timeout_seconds`) comparable to the shutdown time.
- Health check path must be cheap and not depend on downstream systems.
@diagram seq
caption: Safe pod termination behind an ALB
actors: ["Kubelet|node|cp", "Pod|app|app", "Controller|LBC|env", "ALB|target group|ext"]
steps:
  - "0>1: preStop sleep 20s | req"
  - "2>3: deregister target | req"
  - "3>1: stops sending traffic | resp"
  - "0>1: SIGTERM | req"
  - "1>0: exits cleanly | resp"
@h Config
```yaml title="Deployment fragment"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      terminationGracePeriodSeconds: 45
      containers:
        - name: web
          image: 111122223333.dkr.ecr.us-east-1.amazonaws.com/shop/web:1.4.2
          lifecycle:
            preStop:
              exec:
                command: ["sleep", "20"]
          readinessProbe:
            httpGet:
              path: /healthz
              port: 8080
```
```bash title="Enable readiness gates" nocheck
kubectl label namespace shop elbv2.k8s.aws/pod-readiness-gate-inject=enabled
```
@check
What causes 502s during rolling updates? || The pod stops before the load balancer has deregistered it, so requests still reach a dead target.
@end

@concept WAF, Shield, TLS and sharing ALBs
@plain
Security features attach to the ALB through annotations: AWS WAF for request filtering, ACM for certificates, and Shield for DDoS.
@problem
Public endpoints get scanned, scraped and attacked; terminating TLS and filtering at the edge keeps that away from your pods.
@does
- `alb.ingress.kubernetes.io/wafv2-acl-arn` attaches an existing web ACL.
- `alb.ingress.kubernetes.io/ssl-policy` selects a TLS policy (use a TLS 1.2+ policy).
- Shield Standard is automatic on ALB; Shield Advanced adds response support and cost protection.
- One ALB per team or per environment is cheaper and easier to manage than one per Ingress; use `group.name`, but be aware of blast radius and the rule limit per listener (check the current quota).
- Pair with ExternalDNS to publish the hostnames.
@diagram layers
caption: Edge protections
layers:
  - {label: "Edge", nodes: ["Route 53|DNS|ext", "Shield|DDoS|ok"]}
  - {label: "Load balancer", nodes: ["WAF web ACL|managed rules, rate limit|warn", "ALB listener 443|ACM certificate|cp"]}
  - {label: "Cluster", nodes: ["Target group|pods|app"]}
@h Annotations
```yaml title="WAF and TLS policy annotations"
metadata:
  annotations:
    alb.ingress.kubernetes.io/wafv2-acl-arn: arn:aws:wafv2:us-east-1:111122223333:regional/webacl/shop/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
    alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06
```
@check
Where does TLS terminate with an ALB? || At the ALB, using an ACM certificate; traffic to pods can be plain or re-encrypted.
@end
