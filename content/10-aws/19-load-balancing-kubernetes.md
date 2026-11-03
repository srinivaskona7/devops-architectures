---
title: Load balancing for Kubernetes and operations
minutes: 45
objectives:
  - Provision ALBs and NLBs from Kubernetes with the AWS Load Balancer Controller
  - Use IP target mode, readiness gates and pod draining for zero downtime
  - Monitor and troubleshoot load balancers with metrics, logs and health states
---
On EKS the AWS Load Balancer Controller turns Ingress and Service objects into real ALBs and NLBs. Understanding target modes and draining avoids dropped requests during rollouts.

@concept AWS Load Balancer Controller
@plain
The **AWS Load Balancer Controller** runs in your cluster, watches Ingress and Service objects and creates ALBs, NLBs, listeners and target groups.
@problem
The in-tree cloud provider only creates Classic or basic NLBs. The controller adds ALB Ingress support, IP targets and fine control through annotations.
@does
- Install with Helm; give it a role through IRSA or Pod Identity with the published IAM policy.
- `Ingress` with `ingressClassName: alb` creates an ALB. `Service` of type `LoadBalancer` with `loadBalancerClass: service.k8s.aws/nlb` creates an NLB.
- Subnets are discovered through `kubernetes.io/role/elb` and `kubernetes.io/role/internal-elb` tags.
- **IngressGroup** (`alb.ingress.kubernetes.io/group.name`) merges many Ingresses into one ALB to save cost.
@diagram flow
caption: From Ingress to ALB
numbered: true
nodes:
  - "Ingress applied|annotations and rules|app"
  - "Controller reconciles|calls elbv2 APIs|cp"
  - "ALB and target group|created|info"
  - "Pods registered|IP targets|env"
  - "Traffic flows|ok|ok"
@h Ingress example
```yaml title="ingress.yaml"
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: shop
  namespace: shop
  annotations:
    alb.ingress.kubernetes.io/scheme: internet-facing
    alb.ingress.kubernetes.io/target-type: ip
    alb.ingress.kubernetes.io/group.name: public
    alb.ingress.kubernetes.io/listen-ports: '[{"HTTPS":443}]'
    alb.ingress.kubernetes.io/certificate-arn: arn:aws:acm:eu-west-1:111122223333:certificate/example
    alb.ingress.kubernetes.io/healthcheck-path: /healthz
    alb.ingress.kubernetes.io/wafv2-acl-arn: arn:aws:wafv2:eu-west-1:111122223333:regional/webacl/web/example
spec:
  ingressClassName: alb
  rules:
    - host: shop.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: shop
                port:
                  number: 80
```
```bash title="Install" lab
helm repo add eks https://aws.github.io/eks-charts && helm repo update
helm install aws-load-balancer-controller eks/aws-load-balancer-controller -n kube-system \
  --set clusterName=prod --set serviceAccount.create=false --set serviceAccount.name=aws-load-balancer-controller
kubectl -n kube-system rollout status deploy/aws-load-balancer-controller
```
@check
How can many Ingresses share one ALB? || Give them the same alb.ingress.kubernetes.io/group.name annotation.
@end

@concept Instance mode versus IP mode
@plain
The target group can register nodes (instance mode, via NodePort) or pod IPs directly (IP mode).
@problem
Instance mode adds a hop through kube-proxy and node port, and traffic may be forwarded to a pod on another node, hiding client IPs and losing balance.
@does
- **IP mode**: ALB or NLB sends straight to pod IPs from the VPC CNI. Fewer hops, accurate health per pod, works with pod readiness gates. Needs VPC-routable pod IPs.
- **Instance mode**: works with any CNI; relies on NodePort and `externalTrafficPolicy`.
- With `externalTrafficPolicy: Local` health checks target only nodes with ready pods, which preserves the client IP for NLB instance mode.
@diagram cmp
caption: Target modes
cards:
  - {h: "IP mode", kind: ok, items: ["Direct to pod", "One hop fewer", "Needs VPC CNI addressing"]}
  - {h: "Instance mode", kind: warn, items: ["Via NodePort", "Extra hop", "Works with overlay CNIs"]}
@h NLB service
```yaml title="nlb-service.yaml"
apiVersion: v1
kind: Service
metadata:
  name: mqtt
  namespace: shop
  annotations:
    service.beta.kubernetes.io/aws-load-balancer-nlb-target-type: ip
    service.beta.kubernetes.io/aws-load-balancer-scheme: internal
spec:
  type: LoadBalancer
  loadBalancerClass: service.k8s.aws/nlb
  selector:
    app: mqtt
  ports:
    - port: 1883
      targetPort: 1883
```
:::note
`service.k8s.aws/nlb` is the controller's default class (verified against the controller documentation on 2026-10-31). If the class on a Service is one the controller does not recognise, the controller ignores that Service, even when the older `aws-load-balancer-type` annotation is present. The class can be changed with the controller flag `--load-balancer-class`.
:::
@end

@concept Zero-downtime deployments
@plain
Pods must leave the load balancer before they stop, and join it only when ready. Several timers make this work.
@problem
Without coordination, a terminating pod keeps receiving requests for seconds because the load balancer has not yet deregistered it, causing 502 and 504 errors.
@does
- Enable the **pod readiness gate** (label the namespace `elbv2.k8s.aws/pod-readiness-gate-inject=enabled`) so a rollout waits until the pod is healthy in the target group.
- On termination: Kubernetes sends SIGTERM; the controller starts deregistration; the load balancer drains for `deregistration_delay`. Add a `preStop` sleep of about 10 to 20 seconds so the app keeps serving while deregistration propagates.
- Make `terminationGracePeriodSeconds` greater than preStop plus shutdown time.
- Set the target group deregistration delay lower than default 300 seconds for short requests, via the annotation `alb.ingress.kubernetes.io/target-group-attributes`.
@diagram seq
caption: Pod termination with draining
actors: ["Kubernetes|API and kubelet|cp", "Controller|deregisters target|app", "ALB|draining|info", "Pod|your app|env"]
steps:
  - "0>1: pod deleting, remove from endpoints | req"
  - "1>2: deregister target | req"
  - "2>3: stops new requests, keeps existing | resp"
  - "0>3: preStop sleep then SIGTERM | req"
  - "3>0: exits after finishing requests | resp"
@h Deployment snippet
```yaml title="graceful-deployment.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shop
  namespace: shop
spec:
  replicas: 3
  selector:
    matchLabels: {app: shop}
  template:
    metadata:
      labels: {app: shop}
    spec:
      terminationGracePeriodSeconds: 60
      containers:
        - name: shop
          image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:1.0
          lifecycle:
            preStop:
              exec:
                command: ["sleep", "15"]
          readinessProbe:
            httpGet: {path: /healthz, port: 8080}
```
```bash title="Enable readiness gate" lab
kubectl label namespace shop elbv2.k8s.aws/pod-readiness-gate-inject=enabled
kubectl -n shop get pods -o wide
```
@check
Why a preStop sleep? || The load balancer needs seconds to stop sending new requests, so the pod must keep serving until deregistration takes effect.
@end

@concept Health checks in depth
@plain
A target is healthy when it passes a configured number of consecutive probes, unhealthy after a number of failures. Settings control how quickly the load balancer reacts.
@problem
Too sensitive and healthy targets flap; too slow and failures reach users.
@does
- ALB: protocol, path, port, interval (5 to 300 seconds), timeout, healthy and unhealthy thresholds, matcher for success codes.
- Use a lightweight `/healthz` that checks the process and critical dependencies lightly; do not run expensive queries every few seconds across all targets.
- If all targets in a target group are unhealthy the ALB **fails open** and routes to all of them (check the current documentation for details per type).
- Target group health and **application load balancer health at the DNS level** (minimum healthy targets) can influence DNS failover through Route 53 integration.
@diagram flow
caption: Health state transitions
nodes:
  - "initial|registered|info"
  - "healthy|passes threshold|ok"
  - "unhealthy|fails threshold|bad"
  - "draining|being removed|warn"
@h Inspect and tune
```bash title="Health check tuning" lab
aws elbv2 modify-target-group --target-group-arn arn:aws:elasticloadbalancing:eu-west-1:111122223333:targetgroup/api/0123456789abcdef \
  --health-check-path /healthz --health-check-interval-seconds 10 --healthy-threshold-count 2 --unhealthy-threshold-count 3
aws elbv2 describe-target-health --target-group-arn arn:aws:elasticloadbalancing:eu-west-1:111122223333:targetgroup/api/0123456789abcdef
```
@end

@concept Monitoring and troubleshooting
@plain
Metrics, access logs and a few common error codes quickly show whether a problem is the client, the load balancer or the target.
@problem
A 5xx at the edge could come from many layers; knowing which one produced it saves hours.
@does
- ELB-generated: `HTTPCode_ELB_5XX_Count` (502 bad gateway, 503 no healthy targets, 504 timeout). Target-generated: `HTTPCode_Target_5XX_Count`. 460 means the client closed the connection early.
- Latency: `TargetResponseTime`. Capacity: `ActiveConnectionCount`, `ConsumedLCUs`. Health: `HealthyHostCount`, `UnHealthyHostCount`.
- Access logs to S3 (also connection logs) include `elb_status_code`, `target_status_code` and `target_processing_time`; query with Athena.
- 502 often means the target closed a connection (keep-alive timeout shorter than the ALB idle timeout); set the app keep-alive above 60 seconds.
@diagram cmp
caption: Reading 5xx codes
cards:
  - {h: "502", kind: bad, items: ["Target closed or sent invalid response", "Check app keep-alive timeout"]}
  - {h: "503", kind: warn, items: ["No healthy targets", "Check health check and security group"]}
  - {h: "504", kind: warn, items: ["Target did not answer in time", "Check idle timeout and app latency"]}
@h Alarm
```bash title="Alarm on ELB 5xx" lab
aws cloudwatch put-metric-alarm --alarm-name web-elb-5xx --namespace AWS/ApplicationELB \
  --metric-name HTTPCode_ELB_5XX_Count --dimensions Name=LoadBalancer,Value=app/web/0123456789abcdef \
  --statistic Sum --period 60 --evaluation-periods 3 --threshold 10 --comparison-operator GreaterThanThreshold \
  --treat-missing-data notBreaching --alarm-actions arn:aws:sns:eu-west-1:111122223333:oncall
```
:::tip
For 502s that appear at random after idle periods, compare the application keep-alive timeout with the ALB idle timeout first.
:::
@check
What is the first thing to check for a 503 from an ALB? || Whether the target group has any healthy targets.
@end
