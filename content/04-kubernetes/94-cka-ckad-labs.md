---
title: CKA and CKAD exam labs
minutes: 90
objectives:
  - Complete typical CKA and CKAD tasks quickly with imperative commands
  - Practise timed tasks on cluster operations, workloads, networking and storage
  - Build a personal speed routine for the terminal exam
---
The CKA and CKAD are hands-on exams in a terminal. Speed comes from imperative commands, `kubectl explain`, and knowing where to find examples in the allowed documentation. Check the current exam curriculum and allowed resources on the CNCF site before you sit it.

@concept Exam setup and speed routine
@plain
Spend the first minute preparing the shell, then work from imperative commands that generate YAML.
@problem
Typing full manifests wastes minutes you do not have.
@does
- Aliases are usually pre-set (`k`, completion), but verify. `export do="--dry-run=client -o yaml"` generates manifests.
- Always switch context as instructed in each question (`kubectl config use-context NAME`).
- Use `kubectl explain pod.spec.containers --recursive | less` and the allowed docs for snippets.
- Time budget: skip long questions first, flag and return. Partial credit exists.
- Verify each result (`get`, `describe`, `curl` inside a Pod) before moving on.
@diagram flow
caption: Per task routine
numbered: true
nodes:
  - "Read and set context|first line|plain"
  - "Generate YAML|dry-run client|info"
  - "Edit and apply|vim or sed|app"
  - "Verify|get, describe, logs|ok"
@h Setup commands
```bash title="First minute" lab
alias k=kubectl
export do="--dry-run=client -o yaml"
source <(kubectl completion bash); complete -o default -F __start_kubectl k
echo "set expandtab tabstop=2 shiftwidth=2" >> ~/.vimrc
k run web --image=nginx:1.27 $do > web.yaml
```
@check
Why use --dry-run=client -o yaml? || It generates a correct manifest skeleton without creating anything, so you edit instead of typing from scratch.
@end

@concept Lab 1, workloads and rollouts (10 minutes)
@plain
Create, scale, update and roll back a Deployment, and expose it. A core skill for both exams.
@problem
Slow, error prone handling of the most common tasks.
@does
- Task: create Deployment `web` with image `nginx:1.26`, 3 replicas, in namespace `lab1`. Update to `nginx:1.27` and record the change. Roll back. Expose on port 80 as ClusterIP service `web-svc`.
- Task: set CPU request 100m and memory limit 128Mi.
- Task: scale to 5 and verify the ReplicaSet.
- Check: `k rollout history`, `k get endpoints`.
@diagram flow
caption: Lab 1 flow
numbered: true
nodes:
  - "Create namespace and Deployment|imperative|app"
  - "Update image|rollout|info"
  - "Roll back|undo|warn"
  - "Expose|ClusterIP|ok"
@h Solution
```bash title="Lab 1 answer" lab
k create ns lab1
k create deploy web --image=nginx:1.26 --replicas=3 -n lab1
k set image deploy/web nginx=nginx:1.27 -n lab1
k annotate deploy/web kubernetes.io/change-cause="update to 1.27" -n lab1
k rollout status deploy/web -n lab1
k rollout undo deploy/web -n lab1
k set resources deploy/web -n lab1 --requests=cpu=100m --limits=memory=128Mi
k scale deploy/web --replicas=5 -n lab1
k expose deploy/web --name=web-svc --port=80 -n lab1
k get endpoints web-svc -n lab1
```
@end

@concept Lab 2, config, secrets and probes (10 minutes)
@plain
Inject configuration from ConfigMaps and Secrets and add health probes.
@problem
Config tasks combine several objects, and a typo breaks the Pod silently.
@does
- Task: create ConfigMap `app-cfg` with `MODE=prod` and Secret `app-sec` with `PASSWORD=s3cret`.
- Task: Pod `app` (busybox) that reads `MODE` as env and mounts the Secret at `/etc/sec`.
- Task: add a readiness probe `httpGet /` on port 80 to an nginx Pod.
- Verify with `k exec app -- env | grep MODE` and `k exec app -- cat /etc/sec/PASSWORD`.
@diagram layers
caption: What the Pod receives
layers:
  - {label: "Objects", nodes: ["ConfigMap app-cfg|MODE|info", "Secret app-sec|PASSWORD|warn"]}
  - {label: "Pod app", nodes: ["Env MODE|from ConfigMap|app", "Volume /etc/sec|from Secret|app"]}
@h Solution
```bash title="Lab 2 answer" lab
k create cm app-cfg --from-literal=MODE=prod
k create secret generic app-sec --from-literal=PASSWORD=s3cret
cat > app.yaml <<'EOF'
apiVersion: v1
kind: Pod
metadata:
  name: app
spec:
  containers:
    - name: app
      image: busybox:1.36
      command: ["sleep", "3600"]
      envFrom:
        - configMapRef: {name: app-cfg}
      volumeMounts:
        - {name: sec, mountPath: /etc/sec, readOnly: true}
  volumes:
    - name: sec
      secret: {secretName: app-sec}
EOF
k apply -f app.yaml && k exec app -- sh -c 'echo $MODE; cat /etc/sec/PASSWORD'
```
@check
What is the difference between envFrom and env with valueFrom? || envFrom imports all keys of a source as variables; valueFrom picks a single key and lets you rename it.
@end

@concept Lab 3, scheduling and node tasks (10 minutes)
@plain
Control where Pods run with labels, taints, tolerations and affinity, and take a node out of service.
@problem
Scheduling questions have exact syntax that is easy to get wrong under pressure.
@does
- Task: label node `node01` with `disk=ssd`; run Pod `fast` with `nodeSelector`.
- Task: taint `node02` with `team=a:NoSchedule`; run a Pod that tolerates it.
- Task: drain `node01` safely, then uncordon it.
- Task: find a Pod that is Pending and explain why (`describe`).
@diagram flow
caption: Lab 3
nodes:
  - "Label node|disk=ssd|info"
  - "Pod with nodeSelector|lands on node01|app"
  - "Taint node02|NoSchedule|warn"
  - "Drain then uncordon|maintenance|ok"
@h Solution
```bash title="Lab 3 answer" lab
k label node node01 disk=ssd
k run fast --image=nginx:1.27 $do > fast.yaml   # add nodeSelector: {disk: ssd}
k taint node node02 team=a:NoSchedule
k drain node01 --ignore-daemonsets --delete-emptydir-data
k uncordon node01
k get pods -o wide
```
:::tip
After any drain, uncordon in the exam and in real life. On Gardener, confirm that the node really is schedulable afterwards.
:::
@end

@concept Lab 4, networking and Services (10 minutes)
@plain
Connect Pods through Services, restrict access with NetworkPolicy, and publish through Ingress or Gateway.
@problem
Network tasks need several objects to line up, and a wrong label means no traffic.
@does
- Task: create NetworkPolicy `db-allow` in `lab4` allowing ingress to Pods `app=db` only from Pods `app=api` on TCP 5432.
- Task: create a NodePort Service 30080 for a Deployment.
- Task: test DNS: `k run t --rm -it --image=busybox:1.36 --restart=Never -- nslookup web-svc.lab1`.
- Task: Ingress route `/shop` to service `web-svc` with `pathType: Prefix`.
@diagram flow
caption: Allowed path
nodes:
  - "api Pod|app=api|app"
  - "NetworkPolicy|allow 5432|cp"
  - "db Pod|app=db|ok"
  - "other Pod|denied|bad"
@h Solution
```yaml title="Lab 4 NetworkPolicy"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: db-allow
  namespace: lab4
spec:
  podSelector:
    matchLabels: {app: db}
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels: {app: api}
      ports:
        - protocol: TCP
          port: 5432
```
```bash title="Test it" lab
k run t --rm -it --image=busybox:1.36 --restart=Never -n lab4 -- nc -zv db 5432
```
@check
Does a NetworkPolicy do anything without a CNI that supports it? || No. The object is accepted but ignored unless the CNI enforces NetworkPolicy.
@end

@concept Lab 5, storage and RBAC (10 minutes)
@plain
Give a Pod persistent storage and give a ServiceAccount limited permissions.
@problem
Both topics have strict naming and binding rules that cause silent failures.
@does
- Task: PVC `data` 1Gi `ReadWriteOnce`; Pod mounting it at `/data`; write a file; delete the Pod; recreate and check the file persists.
- Task: ServiceAccount `reader` in `lab5` that may `get,list` Pods only in that namespace. Verify with `k auth can-i list pods --as=system:serviceaccount:lab5:reader -n lab5`.
- Task: Role and RoleBinding in YAML via `k create role` and `k create rolebinding`.
@diagram flow
caption: RBAC chain
nodes:
  - "ServiceAccount|reader|app"
  - "RoleBinding|binds subject to role|cp"
  - "Role|get list pods|info"
  - "can-i|verifies|ok"
@h Solution
```bash title="Lab 5 RBAC answer" lab
k create ns lab5
k create sa reader -n lab5
k create role pod-reader --verb=get,list --resource=pods -n lab5
k create rolebinding reader-binding --role=pod-reader --serviceaccount=lab5:reader -n lab5
k auth can-i list pods --as=system:serviceaccount:lab5:reader -n lab5
k auth can-i delete pods --as=system:serviceaccount:lab5:reader -n lab5
```
@end

@concept Lab 6, cluster tasks for CKA (15 minutes)
@plain
Administrator tasks: etcd backup, kubeadm upgrade, troubleshooting a NotReady node and static Pods.
@problem
These have the highest weight in the CKA and need exact steps.
@does
- Task: back up etcd to `/opt/backup/etcd.db` using the certificates in the static Pod manifest (see the HA page).
- Task: upgrade a control plane node by one minor with kubeadm: `kubeadm upgrade plan`, `apply`, then upgrade kubelet and restart it.
- Task: a node is NotReady: `systemctl status kubelet`, `journalctl -u kubelet`, check runtime and certificates.
- Task: create a static Pod by putting a manifest in `/etc/kubernetes/manifests` on a node.
@diagram flow
caption: NotReady node triage
nodes:
  - "Node NotReady|get nodes|bad"
  - "kubelet status|systemctl and journalctl|info"
  - "Runtime and CNI|crictl ps, config|info"
  - "Fix and verify|node Ready|ok"
@h Commands
```bash title="Node triage on the node itself" lab
systemctl status kubelet --no-pager
journalctl -u kubelet --no-pager -n 50
crictl ps -a | head
ls /etc/kubernetes/manifests
```
@check
Where do you put a static Pod manifest? || In the directory configured as staticPodPath in the kubelet config, normally /etc/kubernetes/manifests.
@end
