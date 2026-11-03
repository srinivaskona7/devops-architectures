---
title: RBAC and identity for workloads
minutes: 50
objectives:
  - Write least privilege Roles and bindings and test them
  - Use ServiceAccounts and cloud identity (IRSA, Pod Identity) for workloads
  - Audit and reduce excess permissions
---
RBAC answers one question: may this identity do this verb on this resource. Most clusters are over-permissioned because RBAC is written once and never reviewed.

@concept RBAC building blocks
@plain
Four objects: **Role** (permissions in a namespace), **ClusterRole** (cluster-wide or reusable permissions), **RoleBinding** and **ClusterRoleBinding** (attach a role to subjects).
@problem
Giving everyone `cluster-admin` is easy and dangerous. You need a way to grant exactly what a person or workload requires.
@does
- A rule lists `apiGroups`, `resources`, optional `resourceNames` and `verbs` (`get`, `list`, `watch`, `create`, `update`, `patch`, `delete`, `deletecollection`).
- Subjects are `User`, `Group` or `ServiceAccount`. Users and groups come from authentication (OIDC claims, certificates).
- A RoleBinding can reference a ClusterRole but still limits it to its own namespace, a good way to reuse `view` or `edit`.
- RBAC is additive and has no deny.
@diagram flow
caption: From subject to permission
nodes:
  - "Subject|user, group, SA|ext"
  - "RoleBinding|in namespace shop|info"
  - "Role|rules|cp"
  - "Allowed verbs|on resources|ok"
@h A least privilege Role
```yaml title="rbac.yaml"
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deploy-manager
  namespace: shop
rules:
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "list", "watch", "patch"]
  - apiGroups: [""]
    resources: ["pods", "pods/log"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: shop-devs
  namespace: shop
subjects:
  - kind: Group
    name: oidc:shop-developers
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: deploy-manager
  apiGroup: rbac.authorization.k8s.io
```
@end

@concept ClusterRoles, aggregation and built-ins
@plain
Kubernetes ships `cluster-admin`, `admin`, `edit` and `view`. Aggregated ClusterRoles let CRDs add themselves to them with labels.
@problem
Writing a role per team from nothing is slow, and new CRDs would otherwise be invisible to `view` or `edit`.
@does
- `view`: read most objects except Secrets. `edit`: read and write most objects including Secrets. `admin`: edit plus RBAC within a namespace. `cluster-admin`: everything.
- Label a ClusterRole with `rbac.authorization.k8s.io/aggregate-to-view: "true"` to include it into `view` automatically; operators use this.
- `edit` can read Secrets, so it can effectively reach any ServiceAccount token-bearing identity in that namespace. Treat it as privileged.
- Never bind `system:authenticated` or `system:anonymous` to broad roles.
@diagram cmp
caption: Built-in roles
cards:
  - {h: "view", kind: ok, items: ["Read most, no Secrets"]}
  - {h: "edit", kind: warn, items: ["Write most, reads Secrets"]}
  - {h: "admin", kind: warn, items: ["Edit plus namespace RBAC"]}
  - {h: "cluster-admin", kind: bad, items: ["Everything everywhere"]}
@h Reuse a built-in in one namespace
```bash title="Bind view to a group" lab
kubectl create rolebinding auditors --clusterrole=view --group=oidc:auditors -n shop
kubectl get clusterrole view -o yaml | head -30
kubectl get clusterrolebinding -o wide | grep cluster-admin
```
@check
Why is `edit` risky? || It can read Secrets, including tokens and passwords used by other workloads in the namespace.
@end

@concept ServiceAccounts
@plain
A ServiceAccount is the identity of a workload inside Kubernetes. Pods run as one and use it to call the API.
@problem
Pods that share the namespace `default` ServiceAccount share permissions, so one compromise spreads.
@does
- Create one ServiceAccount per workload and bind only the rights it needs.
- The `default` ServiceAccount should have no bindings; set `automountServiceAccountToken: false` if the app never calls the API.
- The username is `system:serviceaccount:<namespace>:<name>`.
- Tokens are short lived and bound to the Pod. For external callers use `kubectl create token` for a time-limited token.
@diagram flow
caption: A controller Pod reading ConfigMaps
nodes:
  - "Pod|serviceAccountName: reader|app"
  - "Projected token|JWT, expires|info"
  - "API server|authn then RBAC|cp"
  - "Allowed|get configmaps|ok"
@h Workload identity manifest
```yaml title="serviceaccount.yaml"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reader
  namespace: shop
automountServiceAccountToken: true
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: configmap-reader
  namespace: shop
rules:
  - apiGroups: [""]
    resources: ["configmaps"]
    resourceNames: ["web-config"]
    verbs: ["get", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: reader-binding
  namespace: shop
subjects:
  - kind: ServiceAccount
    name: reader
    namespace: shop
roleRef:
  kind: Role
  name: configmap-reader
  apiGroup: rbac.authorization.k8s.io
```
@end

@concept Cloud identity for Pods
@plain
Pods call AWS, Azure or Google APIs by exchanging their Kubernetes token for short-lived cloud credentials, with no stored keys.
@problem
Access keys in Secrets are long lived, copied around and rarely rotated.
@does
- **IRSA** (IAM Roles for Service Accounts): the cluster's OIDC provider is trusted by IAM; a ServiceAccount annotation names the role, and the AWS SDK exchanges the projected token for credentials.
- **EKS Pod Identity**: an agent on nodes delivers credentials; association is created with the EKS API, no per-cluster OIDC trust edits.
- Always scope the role to one service, and the trust policy to one namespace and ServiceAccount.
- Azure Workload Identity and GKE Workload Identity use the same federated token model.
- On Kyma, SAP BTP service bindings and IAS-based app identity play a similar role for BTP services.
@diagram seq
caption: IRSA token exchange
actors: ["Pod SDK|app|app", "STS|AWS|ext", "S3|AWS|ext"]
steps:
  - "0>1: AssumeRoleWithWebIdentity + SA token | tls"
  - "1>0: temporary credentials | resp"
  - "0>2: GetObject | req"
  - "2>0: data | resp"
@h IRSA ServiceAccount
```yaml title="irsa.yaml"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: uploader
  namespace: shop
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::111122223333:role/shop-uploader
```
```bash title="Pod Identity association" nocheck
aws eks create-pod-identity-association \
  --cluster-name prod --namespace shop --service-account uploader \
  --role-arn arn:aws:iam::111122223333:role/shop-uploader
```
@check
What does the IAM trust policy for IRSA limit? || Which OIDC subject (namespace and ServiceAccount) can assume the role.
@end

@concept Testing and auditing RBAC
@plain
You can ask the API server what an identity may do, and use tools to find dangerous or unused permissions.
@problem
Permissions accumulate. Without checks, a leaked token has more power than anyone intended.
@does
- `kubectl auth can-i VERB RESOURCE --as=USER -n NS` and `--list`.
- Escalation rights to watch: `create pods` (can mount Secrets and run privileged), `get/list secrets`, `impersonate`, `escalate`, `bind` on roles, `create serviceaccounts/token`, wildcard `*`.
- Tools: `kubectl-who-can`, `rbac-lookup`, `rakkess`, KubiScan, Kubescape and Trivy for RBAC findings.
- Review `cluster-admin` bindings quarterly; expire access via short-lived OIDC sessions rather than long-lived certificates.
@diagram flow
caption: RBAC review loop
numbered: true
nodes:
  - "List bindings|who has what|info"
  - "Find high risk verbs|secrets, pods, *|warn"
  - "Reduce|narrow rules|ok"
  - "Test|can-i|ok"
@h Commands
```bash title="Audit permissions" lab
kubectl auth can-i --list --as=system:serviceaccount:shop:reader -n shop
kubectl auth can-i create pods --as=system:serviceaccount:shop:reader -n shop
kubectl get clusterrolebindings -o json | grep -B3 -A10 '"name": "cluster-admin"' | head -40
kubectl who-can get secrets -n shop
kubectl rakkess --as system:serviceaccount:shop:reader -n shop
```
:::danger
`create pods` in a namespace is close to `get secrets`, because a Pod can mount any Secret there. Count it as a privileged permission.
:::
@end

@concept Kubernetes access for people
@plain
Humans should reach clusters through your identity provider with short sessions and group-based roles, not shared kubeconfigs with client certificates.
@problem
A kubeconfig with an admin certificate never expires and cannot be revoked per person.
@does
- OIDC with your IdP (Astra Connect, SAP IAS, Entra ID, Okta): groups in the token map to ClusterRoleBindings.
- EKS: access entries and access policies map IAM principals to Kubernetes permissions; the older `aws-auth` ConfigMap is deprecated.
- Kyma: cluster access via kubeconfig with OIDC (kubelogin) against SAP IAS or similar; use groups rather than named users.
- Break-glass: a separate, audited, short-lived admin path.
- Impersonation (`--as`) is itself a privilege, so grant it narrowly.
@diagram flow
caption: OIDC login for kubectl
nodes:
  - "kubectl|exec plugin|ext"
  - "Browser login|IdP, MFA|ext"
  - "ID token|groups claim|info"
  - "API server|maps groups to roles|cp"
@h EKS access entry
```bash title="Grant a group read access on EKS" nocheck
aws eks create-access-entry --cluster-name prod \
  --principal-arn arn:aws:iam::111122223333:role/platform-readonly
aws eks associate-access-policy --cluster-name prod \
  --principal-arn arn:aws:iam::111122223333:role/platform-readonly \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSViewPolicy \
  --access-scope type=cluster
```
@end
