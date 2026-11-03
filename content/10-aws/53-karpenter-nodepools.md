---
title: Karpenter provisioning and NodePools
minutes: 55
objectives:
  - Explain how Karpenter provisions nodes directly from pending pods
  - Write NodePool and EC2NodeClass resources with sane constraints
  - Control Spot usage, limits, taints and disruption budgets
---
Karpenter is a node autoscaler for Kubernetes. Instead of resizing Auto Scaling groups, it looks at unschedulable pods and launches the best-fitting EC2 instances directly through the EC2 Fleet API.
@concept Karpenter versus Cluster Autoscaler
@plain
The Cluster Autoscaler changes the size of pre-defined node groups. Karpenter has no node groups: it reads pod requirements and creates nodes of any suitable instance type.
@problem
Node groups force you to guess instance types in advance, scale slowly, and strand capacity when pod shapes change.
@does
- Watches pending pods, batches them, and picks instance types that satisfy CPU, memory, GPU, zone, architecture and labels.
- Launches in about a minute or less, depending on AMI and pod startup.
- Removes or replaces nodes when they are empty, underused or drifted.
- Karpenter itself runs on a small managed node group or Fargate, not on nodes it controls.
@diagram flow
caption: The provisioning loop
numbered: true
nodes:
  - "Pending pods|cannot schedule|warn"
  - "Karpenter|solves bin packing|cp"
  - "EC2 Fleet|launches instances|ext"
  - "Node joins|pods scheduled|ok"
@h Install
```bash title="Helm install (check chart version in the docs)" nocheck
helm upgrade --install karpenter oci://public.ecr.aws/karpenter/karpenter \
  --version "${KARPENTER_VERSION}" --namespace kube-system \
  --set settings.clusterName=shop-prod \
  --set settings.interruptionQueue=shop-prod \
  --set controller.resources.requests.cpu=1 --set controller.resources.requests.memory=1Gi \
  --wait
kubectl get nodepools,ec2nodeclasses
```
@check
Where should the Karpenter controller itself run? || On a small managed node group or Fargate, outside the capacity it provisions.
@end

@concept EC2NodeClass
@plain
An `EC2NodeClass` describes AWS-specific settings for nodes: AMI, subnets, security groups, IAM role, block devices and metadata options.
@problem
NodePools should stay cloud-neutral, but each node still needs concrete AWS configuration.
@does
- `amiSelectorTerms` pick the AMI by alias such as `al2023@latest`, or pin a version for production (`al2023@v20250101`).
- `subnetSelectorTerms` and `securityGroupSelectorTerms` find resources by tag `karpenter.sh/discovery`.
- `role` is the node IAM role name (an access entry of type `EC2_LINUX` is created for it).
- `metadataOptions` enforce IMDSv2 and hop limit 1; `blockDeviceMappings` size encrypted gp3 root volumes.
- `userData` allows extra kubelet configuration.
@diagram layers
caption: How the pieces relate
layers:
  - {label: "Scheduling intent", nodes: ["Pod requests|cpu, memory, zone|app"]}
  - {label: "Karpenter CRDs", nodes: ["NodePool|what is allowed|cp", "EC2NodeClass|AMI, subnets, SG, role|cp"]}
  - {label: "AWS", nodes: ["EC2 instance|launched|ext"]}
@h Example
```yaml title="EC2NodeClass default"
apiVersion: karpenter.k8s.aws/v1
kind: EC2NodeClass
metadata:
  name: default
spec:
  role: KarpenterNodeRole-shop-prod
  amiSelectorTerms:
    - alias: al2023@latest
  subnetSelectorTerms:
    - tags:
        karpenter.sh/discovery: shop-prod
  securityGroupSelectorTerms:
    - tags:
        karpenter.sh/discovery: shop-prod
  metadataOptions:
    httpTokens: required
    httpPutResponseHopLimit: 1
  blockDeviceMappings:
    - deviceName: /dev/xvda
      ebs:
        volumeSize: 50Gi
        volumeType: gp3
        encrypted: true
```
:::tip
Pin an AMI version in production and roll it deliberately; `@latest` means any new AMI triggers drift replacement across the fleet.
:::
@check
How does Karpenter find subnets? || By tag selectors in EC2NodeClass, usually `karpenter.sh/discovery`.
@end

@concept NodePool requirements and limits
@plain
A `NodePool` states which nodes Karpenter may create: instance categories, sizes, architectures, capacity types, zones and a total resource cap.
@problem
Without constraints Karpenter may launch giant or exotic instances, or scale forever on a runaway deployment.
@does
- `requirements` use well-known labels: `karpenter.sh/capacity-type` (on-demand, spot), `kubernetes.io/arch`, `topology.kubernetes.io/zone`, `karpenter.k8s.aws/instance-category`, `instance-generation`, `instance-size`.
- Widen the instance list (many families and sizes) for better Spot availability and price.
- `limits` cap total CPU and memory in the pool; set them to your budget.
- `taints` and `labels` direct specific workloads to specific pools; `weight` orders pools.
- `expireAfter` recycles nodes after a lifetime (for example 720h), keeping AMIs fresh.
@diagram flow
caption: A pool narrows the search
nodes:
  - "All EC2 types|hundreds|plain"
  - "Requirements|category c m r, gen > 5|info"
  - "Pod needs|cpu, mem, zone|app"
  - "Cheapest fit|launched|ok"
@h NodePool
```yaml title="General purpose NodePool"
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: general
spec:
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["on-demand", "spot"]
        - key: kubernetes.io/arch
          operator: In
          values: ["amd64", "arm64"]
        - key: karpenter.k8s.aws/instance-category
          operator: In
          values: ["c", "m", "r"]
        - key: karpenter.k8s.aws/instance-generation
          operator: Gt
          values: ["5"]
      expireAfter: 720h
  limits:
    cpu: "200"
    memory: 800Gi
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
```
@check
What does the limits field protect against? || A runaway workload or bug creating unbounded nodes and cost.
@end

@concept Spot capacity and interruptions
@plain
Spot instances cost much less but can be reclaimed with a two-minute notice. Karpenter listens for interruption events and replaces nodes proactively.
@problem
Spot saves large amounts of money for stateless services, but naive use causes outages.
@does
- Set `settings.interruptionQueue` so Karpenter reads SQS messages from EventBridge (Spot interruption, rebalance recommendation, scheduled change, instance state change).
- It cordons, drains and launches a replacement as soon as it gets notice.
- Use many instance types for diversification; Karpenter uses the `price-capacity-optimized` strategy.
- Spread replicas across zones and nodes, set PDBs, and keep graceful shutdown under two minutes.
- Mix: baseline on-demand pool plus Spot pool for burst, selected via node selectors or tolerations.
@diagram seq
caption: Spot interruption handling
actors: ["EC2|Spot reclaim|ext", "EventBridge and SQS|notice|info", "Karpenter|controller|cp", "Pods|workloads|app"]
steps:
  - "0>1: 2 minute warning | req"
  - "1>2: message read | req"
  - "2>2: launch replacement | resp"
  - "2>3: cordon and drain | req"
  - "3>2: rescheduled | resp"
@h Spot only pool
```yaml title="Spot pool with taint"
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: spot-batch
spec:
  template:
    spec:
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
      taints:
        - key: workload
          value: batch
          effect: NoSchedule
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot"]
  limits:
    cpu: "100"
```
@check
How much warning does a Spot interruption give? || Two minutes.
@end

@concept Pod specs that help Karpenter
@plain
Karpenter packs pods based on their **requests**. Accurate requests, labels and topology rules lead to efficient nodes.
@problem
Pods without requests look free, cause overcommit, and make bin packing unpredictable.
@does
- Always set CPU and memory requests (and memory limits).
- Use `nodeSelector` or affinity on `karpenter.sh/nodepool` or capacity type to steer workloads.
- Use `topologySpreadConstraints` over zones so Karpenter launches in several zones.
- Annotate pods that must not be moved with `karpenter.sh/do-not-disrupt: "true"` (use sparingly; it blocks consolidation and upgrades).
- Use Vertical Pod Autoscaler recommendations or tooling (Goldilocks, Kubecost) to set requests.
@diagram cmp
caption: Spec habits
cards:
  - {h: "Do", kind: ok, items: ["Set realistic requests", "Spread over zones", "Use PDBs"]}
  - {h: "Avoid", kind: bad, items: ["No requests", "do-not-disrupt on everything", "Huge pods that fit nowhere"]}
@h Deployment
```yaml title="Web on the general pool"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
  namespace: shop
spec:
  replicas: 4
  selector:
    matchLabels:
      app: web
  template:
    metadata:
      labels:
        app: web
    spec:
      nodeSelector:
        karpenter.sh/nodepool: general
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: ScheduleAnyway
          labelSelector:
            matchLabels:
              app: web
      containers:
        - name: web
          image: nginx:1.27
          resources:
            requests: {cpu: 250m, memory: 256Mi}
            limits: {memory: 256Mi}
```
@check
What does Karpenter use to size nodes? || The resource requests of pending pods.
@end
