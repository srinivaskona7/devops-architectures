---
title: EKS networking with the VPC CNI
minutes: 50
objectives:
  - Explain how pods receive VPC IP addresses and what limits pod density
  - Enable prefix delegation and custom networking when IPs run short
  - Apply security groups for pods and network policies
---
EKS uses the Amazon VPC CNI plugin. Pods get real VPC IP addresses, which makes networking fast and simple to reason about but ties pod count to ENI limits and subnet size.
@concept How the VPC CNI assigns IPs
@plain
Each node has one or more ENIs. Each ENI has secondary private IPs. The CNI daemon (`aws-node`) hands one of those IPs to every pod on the node.
@problem
Overlay networks add encapsulation and hide pod identity from VPC tools. Using native VPC IPs lets security groups, flow logs and routing treat pods like instances.
@does
- Pods on the same node and across nodes communicate with no overlay; the VPC routes pod IPs.
- The IP warm pool keeps spare IPs ready (`WARM_IP_TARGET`, `WARM_ENI_TARGET`, `MINIMUM_IP_TARGET`).
- Max pods per node depends on instance type: `ENIs x (IPs per ENI - 1) + 2`. Use the AWS `max-pods-calculator.sh` for exact values.
- Subnets must have enough free IPs; every pod consumes one.
@diagram layers
caption: Node networking
layers:
  - {label: "Subnet 10.20.0.0/19", nodes: ["Node primary IP|10.20.1.5|cp"]}
  - {label: "ENIs on node", nodes: ["eth0|primary ENI|info", "eth1|secondary ENI|info"]}
  - {label: "Secondary IPs", nodes: ["Pod A|10.20.1.21|app", "Pod B|10.20.1.22|app", "Pod C|10.20.1.45|app"]}
@h Check settings
```bash title="Inspect the CNI" lab
kubectl -n kube-system get ds aws-node -o jsonpath='{.spec.template.spec.containers[0].env}' | tr ',' '\n' | grep -E 'WARM|PREFIX|MINIMUM' || true
kubectl get pods -A -o wide | awk '{print $8}' | sort | uniq -c | sort -rn | head
kubectl -n kube-system logs ds/aws-node -c aws-node --tail=20
```
@check
Why can a pod fail with "failed to assign an IP address"? || The subnet or the node's ENI limits have no free IPs left.
@end

@concept Prefix delegation
@plain
Instead of assigning single IPs to an ENI, EKS assigns /28 prefixes (16 addresses each), multiplying how many pods a node can run.
@problem
Small instance types hit pod limits (a t3.medium supports only 17 pods) long before CPU or memory runs out.
@does
- Set `ENABLE_PREFIX_DELEGATION=true` on the `aws-node` DaemonSet; requires Nitro instances.
- Max pods rises (the recommended cap is 110 for instances under 30 vCPUs and 250 above, check current guidance).
- Prefixes need contiguous /28 blocks; fragmented subnets may fail. Use **subnet CIDR reservations** to reserve prefix space.
- New nodes must set `--max-pods` accordingly; managed node groups and Karpenter compute this with the right setting.
@diagram cmp
caption: Per IP versus prefix mode
cards:
  - {h: "Secondary IP mode", kind: warn, items: ["One IP per pod", "Low pod density on small nodes"]}
  - {h: "Prefix delegation", kind: ok, items: ["/28 blocks per ENI slot", "Up to 110 or more pods per node", "Needs contiguous subnet space"]}
@h Enable
```bash title="Turn on prefix mode" nocheck
kubectl set env ds/aws-node -n kube-system ENABLE_PREFIX_DELEGATION=true WARM_PREFIX_TARGET=1
aws eks update-addon --cluster-name shop-prod --addon-name vpc-cni \
  --configuration-values '{"env":{"ENABLE_PREFIX_DELEGATION":"true","WARM_PREFIX_TARGET":"1"}}'
```
:::note
Existing nodes keep their old limits. Replace nodes after the change.
:::
@check
What does a /28 prefix provide? || 16 IPv4 addresses for pods on one ENI slot.
@end

@concept Custom networking and IPv6
@plain
When the main subnets are exhausted, custom networking places pod ENIs in a secondary CIDR (like 100.64.0.0/16). IPv6 clusters avoid the problem entirely.
@problem
Corporate VPC ranges are often small. Running out of IPs blocks scaling although nodes have capacity.
@does
- Add a secondary CIDR to the VPC and create subnets per AZ.
- Define an `ENIConfig` per AZ and set `AWS_VPC_K8S_CNI_CUSTOM_NETWORK_CFG=true`, `ENI_CONFIG_LABEL_DEF=topology.kubernetes.io/zone`.
- With custom networking the primary ENI is not used for pods, which lowers pod capacity per node; combine with prefix delegation.
- **IPv6 clusters** give every pod a unique IPv6 address and avoid exhaustion; outbound IPv4 goes through NAT64/egress-only gateways. Choose at cluster creation; it cannot be changed later.
@diagram flow
caption: Pod IPs from a secondary CIDR
nodes:
  - "Primary CIDR|10.20.0.0/16|plain"
  - "Secondary CIDR|100.64.0.0/16|info"
  - "ENIConfig per AZ|subnet and SG|app"
  - "Pods|use secondary IPs|ok"
@h ENIConfig
```yaml title="ENIConfig for us-east-1a"
apiVersion: crd.k8s.amazonaws.com/v1alpha1
kind: ENIConfig
metadata:
  name: us-east-1a
spec:
  subnet: subnet-0aaa1111bbb22222c
  securityGroups:
    - sg-0123456789abcdef0
```
@check
Can an existing IPv4 cluster be converted to IPv6? || No; the IP family is fixed at creation.
@end

@concept Security groups for pods
@plain
Normally all pods on a node share the node's security group. This feature lets a pod have its own security group through a dedicated branch ENI.
@problem
Database security groups allow the node group's SG, which means every pod on those nodes can reach the database.
@does
- Enable `ENABLE_POD_ENI=true` on `aws-node`; supported Nitro instance types provide trunk ENIs.
- Create a `SecurityGroupPolicy` that selects pods by label or service account and lists security group IDs.
- The database SG then allows only the pod SG, giving pod-level segmentation without Kubernetes network policy.
- Pods with SGs consume trunk/branch ENI capacity and start slower; set `POD_SECURITY_GROUP_ENFORCING_MODE` per your needs.
@diagram flow
caption: Pod specific SG to a database
nodes:
  - "Pod label app=orders|SecurityGroupPolicy|app"
  - "Branch ENI|SG orders-pods|info"
  - "RDS SG|allows only orders-pods|warn"
  - "Database|port 5432|cp"
@h Policy
```yaml title="SecurityGroupPolicy"
apiVersion: vpcresources.k8s.aws/v1beta1
kind: SecurityGroupPolicy
metadata:
  name: orders-sg
  namespace: shop
spec:
  podSelector:
    matchLabels:
      app: orders
  securityGroups:
    groupIds:
      - sg-0aaa1111bbb22222c
```
```bash title="Enable the feature" nocheck
kubectl set env daemonset aws-node -n kube-system ENABLE_POD_ENI=true
kubectl -n kube-system rollout status ds/aws-node
```
@check
What problem does SecurityGroupPolicy solve? || It lets individual pods carry their own security group instead of sharing the node's.
@end

@concept Network policy and service networking
@plain
The VPC CNI can enforce Kubernetes `NetworkPolicy` using eBPF on supported versions. Service traffic goes through kube-proxy (iptables or IPVS).
@problem
By default every pod can reach every other pod. In multi-team clusters you need default-deny with explicit allows.
@does
- Enable with `enableNetworkPolicy: "true"` in the VPC CNI add-on configuration (check the minimum version).
- Start with a default-deny policy per namespace, then allow ingress from known namespaces and egress to DNS and the database.
- Network policy covers pod to pod; it does not control egress to arbitrary AWS APIs by name. Use SGs or a firewall for that.
- Alternatively use Cilium as the CNI in chaining mode (support and operation differ, review AWS guidance).
@diagram flow
caption: Default deny with allow rules
nodes:
  - "Default deny|all ingress|bad"
  - "Allow from ingress ns|port 8080|ok"
  - "Allow DNS egress|port 53 to CoreDNS|ok"
  - "Allow DB egress|port 5432|ok"
@h Policy
```yaml title="Deny all, allow from the ingress namespace"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: shop
spec:
  podSelector: {}
  policyTypes: ["Ingress"]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-ingress-ns
  namespace: shop
spec:
  podSelector:
    matchLabels:
      app: web
  policyTypes: ["Ingress"]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ingress
      ports:
        - port: 8080
```
@check
What is the first policy to apply in a namespace? || A default-deny policy, followed by explicit allows.
@end
