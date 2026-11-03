---
title: Bootstrapping with kubeadm, the hard way
minutes: 55
objectives:
  - Explain every component and certificate needed to build a cluster
  - Bootstrap a control plane and join workers with kubeadm
  - Understand what managed services such as EKS and Gardener do for you
---
Building a cluster by hand once removes the mystery. Even if you never run kubeadm in production, you learn what managed control planes provide and where failures come from.

@concept What a cluster is made of
@plain
A cluster is a handful of programs plus certificates that let them trust one another: etcd, kube-apiserver, kube-controller-manager, kube-scheduler on the control plane and kubelet, container runtime and CNI on each node.
@problem
When a managed cluster misbehaves you must know which part is involved.
@does
- Control plane components usually run as static Pods defined in `/etc/kubernetes/manifests` and watched by the kubelet.
- Everything talks to the API server; only the API server talks to etcd.
- Cluster state: PKI in `/etc/kubernetes/pki`, kubeconfig files for admin, controller manager, scheduler and kubelet.
- Add-ons: CoreDNS and kube-proxy (or a replacement) plus a CNI.
@diagram layers
caption: Components of a kubeadm cluster
layers:
  - {label: "Control plane node", nodes: ["etcd|state|db", "kube-apiserver|front door|cp", "controller-manager|loops|cp", "scheduler|placement|cp"]}
  - {label: "Every node", nodes: ["kubelet|runs Pods|app", "containerd|runtime|app", "CNI|networking|info", "kube-proxy|Services|info"]}
@h Look at an existing control plane
```bash title="Static Pod manifests (on a control plane node)" lab
ls /etc/kubernetes/manifests /etc/kubernetes/pki
sudo crictl ps | head
kubectl get pods -n kube-system -o wide
```
@end

@concept Prepare nodes
@plain
Before kubeadm runs, each machine needs a supported OS, a container runtime, the kubelet, kubeadm and kubectl, and a few kernel settings.
@problem
Most failed installs come from missing prerequisites such as swap, cgroup driver mismatch or blocked ports.
@does
- Disable swap (or configure the kubelet to tolerate it deliberately) and load `overlay` and `br_netfilter`; set `net.ipv4.ip_forward=1`.
- Install containerd with `SystemdCgroup = true` to match the kubelet's systemd cgroup driver.
- Install `kubelet`, `kubeadm`, `kubectl` from the pkgs.k8s.io repository for your minor version, and hold the packages.
- Open ports: 6443 API, 2379-2380 etcd, 10250 kubelet, plus CNI ports. Unique hostnames and MAC addresses.
@diagram flow
caption: Node preparation
numbered: true
nodes:
  - "OS and kernel|modules, sysctl, no swap|plain"
  - "containerd|SystemdCgroup true|info"
  - "kubeadm kubelet kubectl|pinned version|app"
  - "Ports open|6443 10250 etc|ok"
@h Commands
```bash title="Prepare an Ubuntu node (outline)" nocheck
sudo swapoff -a && sudo sed -i '/ swap / s/^/#/' /etc/fstab
printf 'overlay\nbr_netfilter\n' | sudo tee /etc/modules-load.d/k8s.conf
sudo modprobe overlay br_netfilter
echo 'net.ipv4.ip_forward=1' | sudo tee /etc/sysctl.d/k8s.conf && sudo sysctl --system
sudo apt-get install -y containerd kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
```
@check
Which cgroup driver should containerd and kubelet share? || systemd on systemd-based hosts. A mismatch causes unstable Pods and kubelet errors.
@end

@concept kubeadm init, phase by phase
@plain
`kubeadm init` runs ordered phases: preflight checks, certificates, kubeconfigs, static Pod manifests, wait for the control plane, upload config, bootstrap tokens and add-ons.
@problem
Knowing the phases lets you debug a failed init and repeat a single step.
@does
- Use a config file for repeatability: `kubeadm init --config kubeadm.yaml`.
- `controlPlaneEndpoint` should be a stable DNS name or load balancer for HA later.
- `podSubnet` must match your CNI configuration; `serviceSubnet` must not overlap with networks.
- `kubeadm init phase NAME` runs individual phases; `kubeadm reset` cleans up a failed attempt.
- Output includes the admin kubeconfig and the `join` command with token and CA cert hash.
@diagram flow
caption: Phases of init
numbered: true
nodes:
  - "preflight|checks|plain"
  - "certs|CA and component certs|info"
  - "kubeconfig|admin, scheduler, controller|info"
  - "control-plane|static Pods, etcd|cp"
  - "addons|CoreDNS, kube-proxy|ok"
@h Config file
```yaml title="kubeadm.yaml" nocheck
apiVersion: kubeadm.k8s.io/v1beta4
kind: ClusterConfiguration
kubernetesVersion: v{{v.kubernetes_latest_patch}}
controlPlaneEndpoint: api.lab.example.com:6443
networking:
  podSubnet: 10.244.0.0/16
  serviceSubnet: 10.96.0.0/12
apiServer:
  certSANs: ["api.lab.example.com"]
---
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
cgroupDriver: systemd
```
:::note
Use the kubeadm config API version that your kubeadm release documents (`kubeadm config print init-defaults`).
:::
@end

@concept Certificates and PKI
@plain
Components authenticate with X.509 client certificates signed by cluster CAs. kubeadm creates a cluster CA, an etcd CA and a front-proxy CA.
@problem
kubeadm certificates expire after one year. An expired certificate takes the API server down with confusing errors.
@does
- CA certificates last 10 years; leaf certificates (apiserver, kubelet client, etcd) 1 year and are renewed automatically during `kubeadm upgrade`.
- `kubeadm certs check-expiration` shows dates. `kubeadm certs renew all` renews them; then restart the static Pods.
- Kubelet client and server certificates can rotate automatically (`rotateCertificates`, `serverTLSBootstrap` with approved CSRs).
- Inspect with `openssl x509 -in file -noout -text`.
@diagram layers
caption: Three CAs
layers:
  - {label: "Cluster CA", nodes: ["apiserver cert|serving|cp", "kubelet client cert|apiserver to kubelet|cp", "admin client cert|kubeconfig|app"]}
  - {label: "etcd CA", nodes: ["etcd server and peer|2379 2380|db", "apiserver-etcd-client|to etcd|cp"]}
  - {label: "Front proxy CA", nodes: ["front-proxy-client|aggregated APIs|info"]}
@h Commands
```bash title="Check and renew" lab
sudo kubeadm certs check-expiration
sudo kubeadm certs renew all
sudo openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -subject -enddate
```
@check
What happens when the API server certificate expires? || Clients and components fail TLS verification and the cluster appears down until certificates are renewed and Pods restarted.
@end

@concept Joining workers and extra control planes
@plain
Nodes join using a bootstrap token and the hash of the cluster CA. The kubelet then requests its own certificate.
@problem
Without a safe join protocol an attacker could join a rogue node or impersonate the API server.
@does
- `kubeadm join ENDPOINT --token T --discovery-token-ca-cert-hash sha256:H` for workers.
- Tokens expire after 24 hours; `kubeadm token create --print-join-command` makes a new one.
- Extra control plane nodes add `--control-plane --certificate-key K`, where the key decrypts certificates uploaded with `kubeadm init --upload-certs` (valid 2 hours).
- Without a CNI, nodes join but stay `NotReady`.
@diagram seq
caption: Worker join
actors: ["Worker|kubeadm join|app", "API server|cluster-info|cp", "Kubelet|TLS bootstrap|info"]
steps:
  - "0>1: fetch cluster-info | req"
  - "0>0: verify CA hash | warn"
  - "2>1: CSR with token | tls"
  - "1>2: signed certificate | resp"
@h Commands
```bash title="Join" lab
kubeadm token create --print-join-command
kubectl get nodes -o wide
kubectl get csr
```
@end

@concept Install the CNI and verify
@plain
After init, install a CNI so that Pods get IPs and CoreDNS can start. Then verify with a small workload.
@problem
A cluster that shows Ready nodes can still have broken DNS or Pod-to-Pod traffic.
@does
- Apply the CNI manifest or Helm chart with the Pod CIDR you set at init.
- Check `kubectl get pods -n kube-system` until all are Running.
- Test: DNS lookup, Pod to Pod across nodes, Service access, NodePort.
- Run `kubectl get --raw /readyz?verbose` and conformance tools such as sonobuoy for a deeper check.
@diagram flow
caption: Smoke test
nodes:
  - "CNI applied|agents Running|app"
  - "DNS lookup|kubernetes.default|info"
  - "Pod to Pod|across nodes|info"
  - "Service and NodePort|reachable|ok"
@h Smoke tests
```bash title="Cluster smoke test" lab
kubectl create deploy web --image=nginx:1.27 --replicas=3
kubectl expose deploy web --port=80
kubectl run t --rm -it --restart=Never --image=busybox:1.36 -- wget -qO- http://web
kubectl run d --rm -it --restart=Never --image=busybox:1.36 -- nslookup kubernetes.default
kubectl delete deploy,svc web
```
@check
Why are nodes NotReady right after init? || No CNI is installed yet, so the kubelet reports the network as not ready.
@end

@concept What managed services do for you
@plain
EKS and Gardener run and patch the control plane, etcd and certificates. You manage nodes (or let the service manage them), add-ons and workloads.
@problem
Without this comparison you may assume a managed cluster protects things it does not.
@does
- EKS: managed API servers and etcd across AZs, control plane upgrades by API call, managed node groups, add-ons (CoreDNS, VPC CNI, kube-proxy, EBS CSI). You own node AMIs, IAM mapping, add-on upgrades.
- Gardener: a seed cluster hosts each shoot's control plane as Pods; worker pools are defined in the Shoot; maintenance windows apply updates.
- You cannot SSH into the control plane, so debugging relies on events, metrics and provider logs.
- Self-managed gives full control but you own etcd backups, certificate renewal and upgrades.
@diagram cmp
caption: Who owns what
cards:
  - {h: "kubeadm", kind: warn, items: ["You run control plane", "You back up etcd", "You renew certificates", "You upgrade everything"]}
  - {h: "EKS", kind: info, items: ["AWS runs control plane", "You run add-ons", "You choose node model"]}
  - {h: "Gardener shoot", kind: ok, items: ["Control plane in the seed", "Declared as a Shoot", "Maintenance windows"]}
@end
