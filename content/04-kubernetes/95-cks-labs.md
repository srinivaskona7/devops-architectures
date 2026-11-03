---
title: CKS exam labs
minutes: 80
objectives:
  - Practise the CKS domains with timed hands-on tasks
  - Harden workloads, RBAC, network policy and the supply chain under time pressure
  - Detect and respond to runtime threats and read audit logs
---
The CKS focuses on securing clusters and workloads. These labs follow the exam domains. Check the current CKS curriculum and allowed tools on the CNCF site, since the tool list changes between versions.

@concept Lab 1, Pod security and securityContext (8 minutes)
@plain
Make a Pod meet the restricted Pod Security Standard and enforce it on a namespace.
@problem
Insecure defaults let containers run as root with extra capabilities.
@does
- Task: label namespace `secure` with `pod-security.kubernetes.io/enforce=restricted`.
- Task: fix a Pod so it is admitted: `runAsNonRoot`, `allowPrivilegeEscalation: false`, drop ALL capabilities, `seccompProfile: RuntimeDefault`.
- Task: set `readOnlyRootFilesystem` and mount an `emptyDir` for `/tmp`.
- Use `--dry-run=server` to see warnings before applying.
@diagram flow
caption: Namespace enforcement
nodes:
  - "Label namespace|enforce restricted|cp"
  - "Apply Pod|admission checks|info"
  - "Violation|rejected with reasons|bad"
  - "Fixed Pod|admitted|ok"
@h Solution
```bash title="Lab 1 commands" lab
kubectl create ns secure
kubectl label ns secure pod-security.kubernetes.io/enforce=restricted pod-security.kubernetes.io/warn=restricted
kubectl run bad --image=nginx:1.27 -n secure --dry-run=server
```
```yaml title="A compliant Pod"
apiVersion: v1
kind: Pod
metadata:
  name: good
  namespace: secure
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 101
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: web
      image: nginxinc/nginx-unprivileged:1.27
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
      volumeMounts:
        - {name: tmp, mountPath: /tmp}
  volumes:
    - name: tmp
      emptyDir: {}
```
@check
Which Pod Security level requires seccomp RuntimeDefault? || restricted. Baseline allows unset seccomp but forbids unconfined.
@end

@concept Lab 2, RBAC least privilege (8 minutes)
@plain
Find and remove over-broad permissions and prove the result with `can-i`.
@problem
Wildcard roles and cluster-admin bindings are the most common cluster compromise path.
@does
- Task: list who can `get secrets` cluster-wide (`kubectl who-can` or `auth can-i --list`).
- Task: replace a ClusterRoleBinding to `cluster-admin` for ServiceAccount `ci` with a namespaced Role allowing only `deployments` update in `apps`.
- Task: disable token automount for a ServiceAccount that does not use the API.
- Check for `system:masters` group use and anonymous access.
@diagram flow
caption: Reduce permissions
nodes:
  - "Find bindings|cluster-admin, wildcards|warn"
  - "Write narrow Role|verbs and resources|info"
  - "Replace binding|namespace scope|app"
  - "Verify can-i|allowed and denied|ok"
@h Solution
```bash title="Lab 2 commands" lab
kubectl get clusterrolebindings -o json | python3 -c 'import sys,json; [print(i["metadata"]["name"], [s.get("name") for s in i.get("subjects",[])]) for i in json.load(sys.stdin)["items"] if i["roleRef"]["name"]=="cluster-admin"]'
kubectl create role deploy-updater --verb=get,list,update,patch --resource=deployments.apps -n apps
kubectl create rolebinding ci-deploy --role=deploy-updater --serviceaccount=apps:ci -n apps
kubectl auth can-i delete secrets --as=system:serviceaccount:apps:ci -n apps
kubectl patch sa ci -n apps -p '{"automountServiceAccountToken": false}'
```
@end

@concept Lab 3, NetworkPolicy default deny (8 minutes)
@plain
Isolate a namespace with default deny, then open only the flows you need, including DNS.
@problem
By default every Pod can talk to every other Pod, so one compromised Pod can reach databases.
@does
- Task: default deny ingress and egress in namespace `shop`.
- Task: allow `web` to reach `api` on 8080 and everything to reach CoreDNS on UDP and TCP 53.
- Task: block access to the cloud metadata address `169.254.169.254` using an egress `ipBlock` with `except`.
- Test with `kubectl exec` and `nc -zv -w 2`.
@diagram flow
caption: Allow list model
nodes:
  - "Default deny|all traffic blocked|bad"
  - "Allow DNS|to kube-dns|ok"
  - "Allow web to api|8080|ok"
  - "Metadata blocked|169.254.169.254|warn"
@h Solution
```yaml title="Default deny with DNS and metadata block"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny
  namespace: shop
spec:
  podSelector: {}
  policyTypes: [Ingress, Egress]
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-and-internet
  namespace: shop
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - {protocol: UDP, port: 53}
        - {protocol: TCP, port: 53}
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except: [169.254.169.254/32]
```
@check
Why must DNS be allowed explicitly after default deny? || Egress deny also blocks the Pod's DNS lookups to CoreDNS, so name resolution breaks.
@end

@concept Lab 4, image and supply chain checks (8 minutes)
@plain
Scan an image, restrict registries by admission and verify a signature.
@problem
Unscanned and unsigned images can bring known vulnerabilities and tampered code.
@does
- Task: scan with `trivy image --severity HIGH,CRITICAL nginx:1.27` and decide which findings matter.
- Task: pin deployments to digests and remove `latest`.
- Task: enforce allowed registries with a ValidatingAdmissionPolicy or Kyverno policy (see the hardening page).
- Task: verify a cosign signature with `cosign verify --key cosign.pub IMAGE`.
@diagram flow
caption: Gate before run
nodes:
  - "Scan|trivy|info"
  - "Pin digest|immutable|app"
  - "Verify signature|cosign|cp"
  - "Admit|policy|ok"
@h Commands
```bash title="Lab 4 commands" lab
trivy image --severity HIGH,CRITICAL --ignore-unfixed nginx:1.27
crane digest nginx:1.27
cosign verify --key cosign.pub registry.example.com/shop/api@sha256:0000000000000000000000000000000000000000000000000000000000000000
kubectl get pods -A -o jsonpath='{range .items[*]}{.spec.containers[*].image}{"\n"}{end}' | sort -u | grep -v '@sha256'
```
@end

@concept Lab 5, runtime detection and Falco (8 minutes)
@plain
Detect suspicious behaviour in a running container and trace it to a Pod.
@problem
A compromised container looks like a normal Pod until you watch its behaviour.
@does
- Task: open a shell in a Pod, read `/etc/shadow`, and find the Falco alerts for these actions.
- Task: write a Falco rule that alerts on a write below `/usr/bin` in any container.
- Task: from an alert, find the Pod, namespace and image, then isolate it with a deny NetworkPolicy and label.
- Capture evidence before deletion (logs, `kubectl get pod -o yaml`).
@diagram flow
caption: Respond to an alert
numbered: true
nodes:
  - "Alert|shell in container|bad"
  - "Identify Pod|namespace and image|info"
  - "Isolate|deny policy, label|warn"
  - "Collect evidence then remove|ok"
@h Commands
```bash title="Lab 5 commands" lab
kubectl exec -it victim -n shop -- sh -c 'cat /etc/shadow'
kubectl logs -n falco -l app.kubernetes.io/name=falco --tail=20 | grep -i 'shadow\|shell'
kubectl label pod victim -n shop quarantine=true
kubectl get pod victim -n shop -o yaml > /tmp/victim-evidence.yaml
```
@check
Why isolate before deleting a compromised Pod? || Deleting destroys evidence. A deny policy stops further damage while you collect logs and the Pod definition.
@end

@concept Lab 6, audit logs and secrets (8 minutes)
@plain
Write an audit policy, read audit events, and check that Secrets are encrypted at rest.
@problem
Without audit logs and encryption you cannot prove what happened or protect stored data.
@does
- Task: add an audit policy that logs Secret access at `Metadata` level and RBAC changes at `RequestResponse`.
- Task: search the log for who read a secret: `jq 'select(.objectRef.resource=="secrets")'`.
- Task: confirm encryption by reading the secret directly from etcd; the value should start with `k8s:enc:`.
- Task: rotate a leaked ServiceAccount token by deleting its Secret or using short-lived `kubectl create token`.
@diagram flow
caption: Prove encryption
nodes:
  - "Create secret|via API|app"
  - "etcdctl get|raw key|db"
  - "Prefix k8s:enc:|encrypted|ok"
  - "Plain text|not encrypted|bad"
@h Commands
```bash title="Lab 6 commands (control plane node)" lab
jq -c 'select(.objectRef.resource=="secrets") | {user:.user.username, verb:.verb, name:.objectRef.name}' /var/log/kubernetes/audit.log | head
kubectl create secret generic enc-test --from-literal=k=v -n default
ETCDCTL_API=3 etcdctl --endpoints=https://127.0.0.1:2379 --cacert=/etc/kubernetes/pki/etcd/ca.crt --cert=/etc/kubernetes/pki/etcd/server.crt --key=/etc/kubernetes/pki/etcd/server.key get /registry/secrets/default/enc-test | head -c 80
kubectl create token reader -n lab5 --duration=10m
```
@end
