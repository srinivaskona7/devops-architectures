---
title: EC2 instance families and the Nitro system
minutes: 40
objectives:
  - Read an instance type name and pick a family for a workload
  - Explain what Nitro changes for performance and security
  - Choose between x86, Graviton and accelerated instances
---
**EC2** gives you virtual machines. Every EKS node, many databases and most build agents are EC2 instances, so choosing and sizing them well affects both cost and reliability.

@concept Reading an instance type
@plain
A name like `m7g.2xlarge` encodes the family (`m`), generation (`7`), extra attributes (`g`) and size (`2xlarge`).
@problem
There are hundreds of types. Without the naming scheme you cannot compare them or search quickly.
@does
- Family letter: `t` burstable, `m` general purpose, `c` compute, `r` memory, `x` large memory, `i` storage, `p`/`g` GPU, `inf`/`trn` ML accelerators.
- Attribute letters: `g` Graviton (Arm), `a` AMD, `i` Intel, `d` local NVMe disk, `n` enhanced networking, `e` extra memory or storage, `flex` flexible price/performance.
- Size doubles resources at each step: large, xlarge, 2xlarge, 4xlarge and so on, then `metal` for bare metal.
- Use `describe-instance-types` for vCPU, memory, network and EBS limits instead of memorising them.
@diagram flow
caption: Anatomy of m7g.2xlarge
nodes:
  - "m|general purpose family|app"
  - "7|generation|info"
  - "g|Graviton processor|env"
  - "2xlarge|size, 8 vCPU|ok"
@h Query types
```bash title="Find candidates" lab
aws ec2 describe-instance-types --filters Name=vcpu-info.default-vcpus,Values=4 Name=memory-info.size-in-mib,Values=16384 \
  --query 'InstanceTypes[].[InstanceType,NetworkInfo.NetworkPerformance,ProcessorInfo.SupportedArchitectures[0]]' --output table | head -20
aws ec2 describe-instance-types --instance-types m7g.2xlarge \
  --query 'InstanceTypes[0].[VCpuInfo.DefaultVCpus,MemoryInfo.SizeInMiB,EbsInfo.EbsOptimizedInfo.MaximumBandwidthInMbps,NetworkInfo.MaximumNetworkInterfaces,NetworkInfo.Ipv4AddressesPerInterface]'
```
@check
What does the g in m7g mean? || The instance uses an AWS Graviton (Arm) processor.
@end

@concept Choosing a family
@plain
Match the bottleneck of your workload to the family: CPU, memory, storage speed or GPU.
@problem
Oversizing wastes money; undersizing causes throttling and latency.
@does
- **General purpose (m)**: balanced; default for many web and Kubernetes nodes.
- **Compute (c)**: CPU-bound services, batch, encoding, high request rates.
- **Memory (r, x)**: caches, in-memory databases, JVM-heavy services.
- **Storage (i, d)**: local NVMe for databases and search with high IOPS.
- **Accelerated (p, g, inf, trn)**: ML training, inference, graphics.
- **Burstable (t)**: low baseline with credits; good for dev and idle services. With `unlimited` mode extra CPU is billed.
@diagram cmp
caption: Which family for which bottleneck
cards:
  - {h: "CPU bound", kind: app, items: ["c family", "Compression, encoding, proxies"]}
  - {h: "Memory bound", kind: info, items: ["r and x families", "Caches, JVM, analytics"]}
  - {h: "IO bound", kind: env, items: ["i and d families", "NVMe for databases"]}
  - {h: "Light and spiky", kind: warn, items: ["t family", "Watch CPU credits"]}
@h Measure first
```bash title="See what you use" lab
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUUtilization \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 --statistics Average Maximum \
  --start-time "$(date -u -v-7d +%Y-%m-%dT%H:%M:%SZ)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 3600 | head -30
aws compute-optimizer get-ec2-instance-recommendations --query 'instanceRecommendations[].[instanceArn,finding]' --output table | head
```
:::tip
Compute Optimizer (opt in) gives right-sizing recommendations from CloudWatch data.
:::
@end

@concept The Nitro system
@plain
**Nitro** is the AWS hypervisor and hardware platform. Dedicated Nitro cards handle networking, storage and management, leaving almost all of the host CPU to your instance.
@problem
Older virtualisation shared host CPU with the hypervisor and I/O emulation, causing overhead and jitter, and giving the hypervisor access to your memory.
@does
- Nitro cards offload VPC networking, EBS and instance storage encryption, and monitoring.
- Nitro Security Chip locks down firmware; AWS operators have no technical means to access instance memory.
- Enables bare metal (`.metal`) instances and consistent performance.
- **Nitro Enclaves** carve out an isolated VM with no network, storage or admin access for processing secrets.
- Most current generations are Nitro based; some older types are not.
@diagram layers
caption: Division of labour on a Nitro host
layers:
  - {label: "Your instance", nodes: ["OS and application|nearly all host CPU|app"]}
  - {label: "Nitro hypervisor", nodes: ["Light hypervisor|CPU and memory only|cp"]}
  - {label: "Nitro cards", nodes: ["VPC networking|ENA|info", "EBS and NVMe|encryption inline|info", "Security chip|firmware root of trust|ok"]}
@h Check hypervisor
```bash title="On an instance" lab
curl -s -H "X-aws-ec2-metadata-token: $(curl -s -X PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')" \
  http://169.254.169.254/latest/meta-data/instance-type
ls /sys/devices/virtual/dmi/id/ && cat /sys/devices/virtual/dmi/id/sys_vendor
aws ec2 describe-instance-types --instance-types c7i.large --query 'InstanceTypes[0].Hypervisor'
```
@check
What does Nitro give besides speed? || Hardware-enforced isolation, no operator access to instance memory, bare metal options and Enclaves.
@end

@concept Graviton and processor choices
@plain
**Graviton** instances use Arm processors designed by AWS. They usually offer better price per performance, but need Arm-compatible binaries and images.
@problem
x86 instances are the default but cost more for the same throughput in many workloads.
@does
- Containers must be built for `linux/arm64`; use multi-arch images (`docker buildx --platform linux/amd64,linux/arm64`).
- Interpreted languages and Java usually run unchanged; native dependencies need arm64 builds.
- Mixed node groups can run both architectures; schedule with `kubernetes.io/arch` node selectors.
- Test and measure with your own workload; the saving varies.
@diagram flow
caption: Moving a service to Graviton
numbered: true
nodes:
  - "Multi-arch image|amd64 and arm64|app"
  - "Test node group|Graviton spot or small|env"
  - "Benchmark|latency and cost per request|info"
  - "Shift traffic|gradually|cp"
  - "Standardise|ok|ok"
@h Multi-arch build and scheduling
```bash title="Build both architectures" lab
docker buildx build --platform linux/amd64,linux/arm64 -t 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:1.0 --push .
kubectl get nodes -L kubernetes.io/arch,node.kubernetes.io/instance-type
```
```yaml title="Pin to Graviton nodes"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: shop
spec:
  replicas: 2
  selector:
    matchLabels: {app: shop}
  template:
    metadata:
      labels: {app: shop}
    spec:
      nodeSelector:
        kubernetes.io/arch: arm64
      containers:
        - name: shop
          image: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:1.0
```
@end

@concept CPU, vCPU and burstable credits
@plain
A vCPU is a hardware thread (usually half a core on x86 with hyperthreading; a full core on Graviton). Burstable `t` instances earn credits when idle and spend them when busy.
@problem
Credit exhaustion silently throttles a `t` instance to its baseline, appearing as unexplained slowness.
@does
- `CPUCreditBalance` and `CPUSurplusCreditBalance` metrics show the state; `CPUUtilization` can mislead because it is relative to the credited share.
- `unlimited` mode lets the instance burn beyond credits for a charge; `standard` throttles.
- For steady workloads use `m` or `c` families rather than a large `t`.
- Dedicated Hosts and Instances exist for licensing or compliance; check the pricing and use cases.
@diagram flow
caption: How credits behave
nodes:
  - "Idle|earns credits|ok"
  - "Busy|spends credits|app"
  - "Balance zero|throttled to baseline|bad"
  - "Unlimited mode|pay for surplus|warn"
@h Watch credits
```bash title="Credit metric" lab
aws cloudwatch get-metric-statistics --namespace AWS/EC2 --metric-name CPUCreditBalance \
  --dimensions Name=InstanceId,Value=i-0123456789abcdef0 --statistics Minimum \
  --start-time "$(date -u -v-1d +%Y-%m-%dT%H:%M:%SZ)" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 3600
aws ec2 describe-instance-credit-specifications --instance-ids i-0123456789abcdef0
```
@check
Why can a t3 instance suddenly become slow? || Its CPU credit balance reached zero, so it is held at baseline performance.
@end

@concept Instance lifecycle and metadata
@plain
An instance moves through pending, running, stopping, stopped, and terminated states. The instance metadata service describes it from the inside.
@problem
Stop, hibernate, reboot and terminate behave differently regarding data, IP addresses and billing, and surprises cause data loss.
@does
- **Stop**: instance store data is lost, EBS volumes persist, public IPv4 changes unless an Elastic IP is attached; no instance-hour charge but EBS still billed.
- **Terminate**: root volume deleted by default (`DeleteOnTermination`). Enable termination protection on critical hosts.
- **Hibernate** saves RAM to an encrypted root volume (supported types only).
- Metadata paths: `instance-id`, `placement/availability-zone`, `iam/security-credentials/`, `spot/instance-action`; user data at `/latest/user-data`.
@diagram flow
caption: Instance states
nodes:
  - "pending|starting|info"
  - "running|billed per second|ok"
  - "stopped|EBS billed only|warn"
  - "terminated|gone, root volume deleted|bad"
@h Operate
```bash title="Lifecycle commands" lab
aws ec2 stop-instances --instance-ids i-0123456789abcdef0
aws ec2 start-instances --instance-ids i-0123456789abcdef0
aws ec2 modify-instance-attribute --instance-id i-0123456789abcdef0 --disable-api-termination
aws ec2 describe-instances --instance-ids i-0123456789abcdef0 --query 'Reservations[].Instances[].[State.Name,PrivateIpAddress,PublicIpAddress]'
```
:::warn
Instance store data is lost on stop and terminate, and when the underlying host fails. Never keep the only copy of data there.
:::
@end
