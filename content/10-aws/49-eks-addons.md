---
title: EKS add-ons CoreDNS, kube-proxy and storage CSI
minutes: 50
objectives:
  - Manage EKS add-ons with versions and configuration values
  - Tune CoreDNS and understand kube-proxy modes
  - Provision persistent storage with the EBS and EFS CSI drivers
---
A bare EKS cluster needs networking, DNS and storage components before it is useful. EKS manages them as add-ons so AWS tests versions against each Kubernetes release.

@concept What EKS add-ons are
@plain
An add-on is a packaged operational component (VPC CNI, CoreDNS, kube-proxy, EBS CSI, Pod Identity Agent, metrics-server and more) that EKS installs and can update for you.
@problem
Installing these with raw manifests or Helm leaves you to track version compatibility on every cluster upgrade.
@does
- Install and upgrade with `aws eks create-addon` and `update-addon`; list versions compatible with your Kubernetes version using `describe-addon-versions`.
- `--configuration-values` accepts a JSON or YAML document validated by a schema (`describe-addon-configuration`).
- `--resolve-conflicts OVERWRITE|PRESERVE` decides what happens to fields you changed manually.
- Self-managed fields can be adopted by importing an existing install.
- Some add-ons need an IAM role (IRSA or Pod Identity), supplied with `--pod-identity-associations` or `--service-account-role-arn`.
@diagram flow
caption: Add-on lifecycle
numbered: true
nodes:
  - "List versions|describe-addon-versions|plain"
  - "Create or update|create-addon|app"
  - "Resolve conflicts|OVERWRITE or PRESERVE|warn"
  - "Verify|rollout status|ok"
@h Manage
```bash title="Add-on commands" lab
aws eks describe-addon-versions --kubernetes-version {{v.eks_to}} --addon-name coredns \
  --query 'addons[0].addonVersions[0:3].[addonVersion,compatibilities[0].defaultVersion]'
aws eks list-addons --cluster-name shop-prod
aws eks describe-addon --cluster-name shop-prod --addon-name vpc-cni \
  --query 'addon.[addonVersion,status]'
aws eks describe-addon-configuration --addon-name coredns --addon-version v1.11.3-eksbuild.2 \
  --query configurationSchema --output text | head -c 600
```
@check
What does resolve-conflicts PRESERVE do? || It keeps fields you changed manually rather than overwriting them with the add-on defaults.
@end

@concept CoreDNS
@plain
CoreDNS answers every in-cluster DNS lookup, such as `orders.shop.svc.cluster.local`, and forwards other names to the VPC resolver.
@problem
If DNS is slow or overloaded, every service call becomes slow, and "it's always DNS" outages are common.
@does
- Runs as a Deployment with two replicas by default; scale with `autoscaling` configuration or cluster-proportional-autoscaler.
- Pods use `ndots:5`, so a name such as `api.example.com` triggers several failing searches first; use fully qualified names with a trailing dot or lower `ndots` in `dnsConfig` for chatty workloads.
- The VPC resolver (`.2` address) has a per-ENI limit of 1024 packets per second; spread CoreDNS across nodes and consider **NodeLocal DNSCache**.
- Customise through the Corefile in the `coredns` ConfigMap or add-on configuration.
@diagram flow
caption: Resolving a name
nodes:
  - "Pod|orders.shop|app"
  - "CoreDNS|cluster.local zone|cp"
  - "Service IP|answer|ok"
  - "VPC resolver|external names|ext"
@h Tune
```yaml title="CoreDNS add-on configuration values"
replicaCount: 3
resources:
  limits:
    memory: 170Mi
  requests:
    cpu: 100m
    memory: 70Mi
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: topology.kubernetes.io/zone
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        k8s-app: kube-dns
```
```bash title="Apply and test" nocheck
aws eks update-addon --cluster-name shop-prod --addon-name coredns \
  --configuration-values file://coredns.yaml --resolve-conflicts OVERWRITE
kubectl run dnstest --rm -it --image=busybox:1.36 --restart=Never -- nslookup kubernetes.default
```
@check
Why does ndots:5 slow external lookups? || Names with fewer than five dots are tried with each search domain first, creating extra failing queries.
@end

@concept kube-proxy
@plain
kube-proxy programs each node so that a Service IP reaches one of its pods, using iptables rules or IPVS.
@problem
Pods need stable virtual IPs for services even though pod IPs change constantly.
@does
- Default mode is `iptables`; rule count grows with services and endpoints, which slows updates in very large clusters.
- `ipvs` mode scales better with thousands of services (check the current add-on support).
- Keep kube-proxy's minor version within the supported skew of the control plane and update it during cluster upgrades.
- Services use `externalTrafficPolicy: Local` to preserve client IPs and skip an extra hop.
@diagram flow
caption: Service virtual IP to a pod
nodes:
  - "Pod|calls 172.20.10.5|app"
  - "iptables or IPVS|DNAT on the node|info"
  - "Endpoint|pod 10.20.3.17|ok"
@h Inspect
```bash title="See rules and version" lab
kubectl -n kube-system get ds kube-proxy -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
kubectl -n kube-system get cm kube-proxy-config -o jsonpath='{.data.config}' | grep -E 'mode|iptables'
kubectl get svc,endpointslices -n shop
```
@check
What changes in kube-proxy when a pod is replaced? || The endpoint list changes and rules on every node are updated to the new pod IP.
@end

@concept EBS CSI driver
@plain
The **EBS CSI driver** creates and attaches EBS volumes for PersistentVolumeClaims. In-tree volume plugins are removed, so every cluster needs this add-on for block storage.
@problem
Stateful apps need disks that survive pod restarts and follow the pod to the right AZ.
@does
- An EBS volume lives in **one AZ**; a pod using it can only run in that AZ. Use `volumeBindingMode: WaitForFirstConsumer` so the volume is created where the pod lands.
- The controller needs IAM permissions (`AmazonEBSCSIDriverPolicy`) through Pod Identity or IRSA, and the KMS key permission if you encrypt with a CMK.
- Supports gp3 (set IOPS and throughput), io2, expansion of volumes, and `VolumeSnapshot`.
- Reclaim policy `Delete` removes the EBS volume when the PVC goes; use `Retain` for important data.
@diagram seq
caption: Provisioning a volume
actors: ["PVC|shop-db-data|app", "CSI controller|provisioner|cp", "EC2 API|CreateVolume|ext", "Node|attach and mount|env"]
steps:
  - "0>1: claim created | req"
  - "1>2: CreateVolume gp3 in AZ | tls"
  - "2>1: volume id | resp"
  - "1>3: AttachVolume | req"
  - "3>0: mounted in pod | resp"
@h StorageClass
```yaml title="gp3 StorageClass"
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: gp3
provisioner: ebs.csi.aws.com
volumeBindingMode: WaitForFirstConsumer
allowVolumeExpansion: true
reclaimPolicy: Delete
parameters:
  type: gp3
  encrypted: "true"
  iops: "3000"
  throughput: "125"
```
```bash title="Install the add-on with Pod Identity" nocheck
aws eks create-addon --cluster-name shop-prod --addon-name aws-ebs-csi-driver \
  --pod-identity-associations serviceAccount=ebs-csi-controller-sa,roleArn=arn:aws:iam::111122223333:role/ebs-csi
```
@check
Why use WaitForFirstConsumer? || The volume is then created in the AZ where the pod is scheduled instead of an arbitrary AZ.
@end

@concept EFS CSI driver
@plain
Amazon EFS is a shared NFS file system that works across AZs. The EFS CSI driver mounts it in pods, including on Fargate.
@problem
Several pods in different AZs need the same files (uploads, shared models), which EBS cannot offer.
@does
- Supports `ReadWriteMany`; storage grows automatically; you pay per GB stored and throughput mode.
- Use **access points** to give each application its own root directory and POSIX identity.
- Mount targets must exist in each AZ, with a security group allowing TCP 2049 from the nodes.
- Dynamic provisioning creates one access point per PVC; encryption in transit is on by default for the mount helper.
@diagram flow
caption: Shared storage across AZs
nodes:
  - "Pod AZ a|mounts via NFS|app"
  - "Mount target a|port 2049|info"
  - "EFS file system|regional|cp"
  - "Pod AZ b|same files|app"
@h StorageClass
```yaml title="EFS StorageClass with access points"
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: efs
provisioner: efs.csi.aws.com
parameters:
  provisioningMode: efs-ap
  fileSystemId: fs-0123456789abcdef0
  directoryPerms: "700"
```
@check
Which volume type supports ReadWriteMany across AZs? || EFS; an EBS volume attaches to one node in one AZ.
@end

@concept Other useful add-ons
@plain
A few more add-ons round out a production cluster: metrics-server, the Pod Identity Agent, the CloudWatch Observability add-on, and the CSI snapshot controller.
@problem
Autoscaling, observability and backups depend on components that a new cluster lacks.
@does
- **metrics-server** feeds `kubectl top` and the Horizontal Pod Autoscaler.
- **amazon-cloudwatch-observability** installs the CloudWatch agent and Fluent Bit for Container Insights.
- **snapshot-controller** enables `VolumeSnapshot` for EBS backups.
- **aws-guardduty-agent** provides runtime threat detection if you use GuardDuty EKS Runtime Monitoring.
- Commit add-ons to Terraform so every cluster has an identical baseline.
@diagram layers
caption: A baseline add-on set
layers:
  - {label: "Networking", nodes: ["vpc-cni|pod IPs|cp", "kube-proxy|services|cp", "coredns|DNS|cp"]}
  - {label: "Storage", nodes: ["aws-ebs-csi-driver|block|env", "aws-efs-csi-driver|shared files|env", "snapshot-controller|backups|env"]}
  - {label: "Platform", nodes: ["eks-pod-identity-agent|IAM for pods|ok", "metrics-server|HPA|ok", "cloudwatch-observability|logs and metrics|ok"]}
@h Terraform
```hcl title="Add-ons in the EKS module"
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"
  # cluster arguments omitted

  cluster_addons = {
    coredns                = { most_recent = true }
    kube-proxy             = { most_recent = true }
    vpc-cni                = { most_recent = true, before_compute = true }
    eks-pod-identity-agent = { most_recent = true }
    metrics-server         = { most_recent = true }
  }
}
```
@check
Which add-on provides data for the HPA? || metrics-server.
@end
