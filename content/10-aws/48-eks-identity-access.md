---
title: EKS identity and access
minutes: 55
objectives:
  - Grant humans and pipelines cluster access with access entries instead of aws-auth
  - Give pods AWS permissions with IRSA or EKS Pod Identity
  - Choose between IRSA and Pod Identity and troubleshoot both
---
Two separate questions: who may call the Kubernetes API (people, CI, nodes) and which AWS permissions do pods get. EKS answers the first with access entries and the second with IRSA or Pod Identity.

@concept How authentication reaches Kubernetes
@plain
`kubectl` on EKS signs a request with your IAM credentials (`aws eks get-token`). The EKS authenticator checks the signature, finds which Kubernetes identity your IAM principal maps to, and Kubernetes RBAC then decides what you can do.
@problem
Kubernetes has no user database. EKS must bridge IAM identities (roles, users, SSO sessions) to Kubernetes users and groups safely.
@does
- Authentication: IAM. Authorisation: Kubernetes RBAC (or an EKS access policy that maps to it).
- The kubeconfig from `aws eks update-kubeconfig` uses an `exec` credential plugin calling `aws eks get-token`.
- IAM Identity Center roles appear as IAM roles named `AWSReservedSSO_<permission-set>_<hash>`.
- Tokens are short-lived (about 15 minutes) and are renewed automatically.
@diagram seq
caption: A kubectl call on EKS
actors: ["kubectl|your laptop|app", "EKS API|authenticator|cp", "IAM|STS verify|ext", "RBAC|authorisation|env"]
steps:
  - "0>0: aws eks get-token | req"
  - "0>1: request with token | tls"
  - "1>2: validate signature | tls"
  - "1>3: map to user and groups | req"
  - "3>0: allowed or forbidden | resp"
@h Inspect your identity
```bash title="Who am I" lab
aws sts get-caller-identity
aws eks get-token --cluster-name shop-prod --query status.expirationTimestamp
kubectl auth whoami
kubectl auth can-i --list --namespace shop | head
```
@check
Where do Kubernetes users come from on EKS? || From IAM principals mapped through access entries or aws-auth; Kubernetes itself has no user store.
@end

@concept Access entries
@plain
An **access entry** is an EKS API object that maps an IAM principal to Kubernetes permissions. Predefined **access policies** such as `AmazonEKSClusterAdminPolicy` or `AmazonEKSViewPolicy` can be scoped to namespaces.
@problem
The older `aws-auth` ConfigMap was easy to break: a YAML typo could lock out every administrator, and editing it required Kubernetes access to begin with.
@does
- Manage entries with the AWS API, CLI, Terraform or CloudFormation, with IAM-level audit in CloudTrail.
- Authentication mode on the cluster: `CONFIG_MAP`, `API_AND_CONFIG_MAP`, or `API`. New clusters should use `API`.
- Attach EKS access policies (`AmazonEKSAdminPolicy`, `AmazonEKSEditPolicy`, `AmazonEKSViewPolicy`, `AmazonEKSClusterAdminPolicy`) or map the principal to your own RBAC groups with `--kubernetes-groups`.
- The cluster creator no longer receives a hidden admin; set `bootstrapClusterCreatorAdminPermissions` deliberately.
@diagram flow
caption: Granting a team access
numbered: true
nodes:
  - "IAM role|platform-engineers via SSO|app"
  - "Access entry|principal to cluster|info"
  - "Access policy|Edit scoped to namespace shop|ok"
  - "Kubernetes API|authorised calls|cp"
@h Create entries
```bash title="Admin and namespace-scoped access" nocheck
aws eks update-cluster-config --name shop-prod \
  --access-config authenticationMode=API
aws eks create-access-entry --cluster-name shop-prod \
  --principal-arn arn:aws:iam::111122223333:role/PlatformAdmin
aws eks associate-access-policy --cluster-name shop-prod \
  --principal-arn arn:aws:iam::111122223333:role/PlatformAdmin \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy \
  --access-scope type=cluster
aws eks associate-access-policy --cluster-name shop-prod \
  --principal-arn arn:aws:iam::111122223333:role/ShopDev \
  --policy-arn arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy \
  --access-scope type=namespace,namespaces=shop
```
```hcl title="Terraform"
resource "aws_eks_access_entry" "dev" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_iam_role.shop_dev.arn
}

resource "aws_eks_access_policy_association" "dev" {
  cluster_name  = aws_eks_cluster.this.name
  principal_arn = aws_iam_role.shop_dev.arn
  policy_arn    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSEditPolicy"

  access_scope {
    type       = "namespace"
    namespaces = ["shop"]
  }
}
```
:::warn
Switching to `API` mode is one way: you cannot return to `CONFIG_MAP`. Create entries for every role in aws-auth first (including node roles if you use self-managed nodes).
:::
@check
Which authentication mode is recommended for new clusters? || API, which uses access entries only.
@end

@concept The aws-auth ConfigMap (legacy)
@plain
`aws-auth` in `kube-system` listed `mapRoles` and `mapUsers` entries. It still exists on older clusters and you will meet it while migrating.
@problem
You need to read and migrate it without locking yourself out.
@does
- `mapRoles` maps role ARNs to usernames and groups (for example `system:masters`).
- Nodes in self-managed groups needed a `system:nodes` entry; managed node groups add it automatically.
- Migration: set mode `API_AND_CONFIG_MAP`, create equivalent access entries, test, then switch to `API`.
- Never edit it live without a backup: `kubectl get cm aws-auth -n kube-system -o yaml > aws-auth.bak`.
@diagram flow
caption: Safe migration path
numbered: true
nodes:
  - "Backup aws-auth|yaml copy|plain"
  - "API_AND_CONFIG_MAP|both active|info"
  - "Create entries|one per principal|app"
  - "Test with each role|can-i|warn"
  - "Switch to API|final|ok"
@h Example
```yaml title="aws-auth ConfigMap (legacy format)"
apiVersion: v1
kind: ConfigMap
metadata:
  name: aws-auth
  namespace: kube-system
data:
  mapRoles: |
    - rolearn: arn:aws:iam::111122223333:role/PlatformAdmin
      username: platform-admin
      groups:
        - system:masters
```
@check
Why migrate away from aws-auth? || It is error-prone, needs Kubernetes access to edit, and a typo can lock everyone out; access entries are API managed and audited.
@end

@concept IRSA, IAM Roles for Service Accounts
@plain
IRSA lets a Kubernetes service account assume an IAM role. The cluster's OIDC issuer signs a projected token; AWS STS trusts that issuer and swaps the token for temporary credentials.
@problem
Giving the node role all permissions means every pod gets them. Static access keys in secrets leak and never rotate.
@does
- Requires an IAM OIDC provider for the cluster issuer URL.
- The role trust policy conditions on the service account: `system:serviceaccount:<namespace>:<name>` in the `sub` claim, and `sts.amazonaws.com` in `aud`.
- The service account is annotated with `eks.amazonaws.com/role-arn`; a mutating webhook injects `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE` into pods.
- AWS SDKs use the credential chain automatically.
@diagram seq
caption: How a pod obtains credentials through IRSA
actors: ["Pod|SDK|app", "Projected token|JWT from kubelet|env", "STS|AssumeRoleWithWebIdentity|ext", "S3|target service|ok"]
steps:
  - "0>1: read token file | req"
  - "0>2: AssumeRoleWithWebIdentity | tls"
  - "2>0: temporary credentials | resp"
  - "0>3: API call | req"
@h Trust policy and service account
```json title="Trust policy for the orders role"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::111122223333:oidc-provider/oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE:sub": "system:serviceaccount:shop:orders",
          "oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
```
```yaml title="ServiceAccount"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: orders
  namespace: shop
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::111122223333:role/shop-orders
```
```bash title="Create it with eksctl" nocheck
eksctl create iamserviceaccount --cluster shop-prod --namespace shop --name orders \
  --attach-policy-arn arn:aws:iam::111122223333:policy/shop-orders-ddb --approve
```
:::danger
A trust policy without the `sub` condition lets any service account in the cluster assume the role. Always scope it to namespace and name.
:::
@check
Which claim restricts a role to one service account? || The token `sub` claim, formatted `system:serviceaccount:<ns>:<name>`.
@end

@concept EKS Pod Identity
@plain
Pod Identity is the newer, simpler mechanism. An agent on each node serves credentials to pods; you link a role to a service account with an EKS API call, not an OIDC trust policy per cluster.
@problem
IRSA needs an OIDC provider per cluster, a trust policy that embeds the issuer URL, and rewrites when you rebuild a cluster. It also hits IAM OIDC provider quotas across many clusters.
@does
- Install the **EKS Pod Identity Agent** add-on (a DaemonSet).
- The role trusts the service principal `pods.eks.amazonaws.com` with actions `sts:AssumeRole` and `sts:TagSession`; the same role works for any cluster.
- Create an association: cluster, namespace, service account, role. No annotation on the service account.
- Session tags (cluster, namespace, service account) enable ABAC policies.
- Not available on Fargate or for the cluster's own controllers that require IRSA in some add-ons; check the current support list. Cross-account use works by role chaining.
@diagram flow
caption: Pod Identity path
nodes:
  - "Pod|SDK calls container credentials endpoint|app"
  - "Pod Identity Agent|on every node|env"
  - "EKS Auth API|AssumeRoleForPodIdentity|cp"
  - "IAM role|temporary credentials|ok"
@h Set it up
```json title="Trust policy for Pod Identity"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Service": "pods.eks.amazonaws.com"},
      "Action": ["sts:AssumeRole", "sts:TagSession"]
    }
  ]
}
```
```bash title="Agent and association" nocheck
aws eks create-addon --cluster-name shop-prod --addon-name eks-pod-identity-agent
aws eks create-pod-identity-association --cluster-name shop-prod \
  --namespace shop --service-account orders \
  --role-arn arn:aws:iam::111122223333:role/shop-orders
aws eks list-pod-identity-associations --cluster-name shop-prod
```
@check
What is the trust principal for Pod Identity roles? || The service principal pods.eks.amazonaws.com.
@end

@concept IRSA versus Pod Identity and troubleshooting
@plain
Both give pods temporary role credentials. Prefer Pod Identity on new EC2-based clusters, keep IRSA where Pod Identity is not supported (Fargate, some add-ons, other clusters).
@problem
Teams mix both and then cannot tell why a pod gets `AccessDenied` or uses the node role.
@does
- IRSA works on EC2, Fargate and non-EKS clusters via OIDC. Pod Identity works on EC2 nodes only.
- SDK too old? Credentials fall back to the node role (IMDS). Update the SDK and set `hop limit 1` on IMDS so pods cannot use it.
- Debug checklist: service account name and namespace, annotation or association, trust policy, token mounted, role permissions, permission boundaries, SCPs.
- Use `aws sts get-caller-identity` inside the pod to see the effective role.
@diagram cmp
caption: Comparison
cards:
  - {h: "IRSA", kind: app, items: ["OIDC provider per cluster", "Works on Fargate", "Trust policy has issuer URL"]}
  - {h: "Pod Identity", kind: ok, items: ["Agent add-on", "Reusable roles across clusters", "Session tags for ABAC", "EC2 nodes only"]}
@choose Which to use
Pod Identity | new EC2 or Karpenter based clusters, many clusters | the workload runs on Fargate
IRSA | Fargate, or a component that documents IRSA only | you want to avoid per-cluster OIDC trust
@h Debug in the pod
```bash title="Effective identity" lab
kubectl -n shop exec deploy/orders -- env | grep -E 'AWS_(ROLE|WEB|CONTAINER)'
kubectl -n shop exec deploy/orders -- aws sts get-caller-identity
kubectl -n shop get sa orders -o yaml | grep role-arn
```
:::tip
Block pods from the node's instance profile: launch templates with `HttpPutResponseHopLimit=1` and `HttpTokens=required` for IMDSv2.
:::
@check
How can a pod accidentally use the node role? || By falling back to IMDS when the SDK does not find IRSA or Pod Identity credentials.
@end

@concept Kubernetes RBAC on top of IAM
@plain
Access entries map principals to groups; RBAC binds those groups to Roles and ClusterRoles. Keep roles narrow and namespaced.
@problem
Giving `system:masters` to everyone makes audit logs meaningless and increases blast radius.
@does
- Use `ClusterRole` for reusable rules and `RoleBinding` to apply them per namespace.
- Bind to **groups**, not individual users, so offboarding is an IAM change.
- Avoid wildcards on verbs and resources; separate read-only, deploy and admin duties.
- Combine with admission controls (Pod Security Admission, Kyverno or Gatekeeper) to restrict what workloads can do.
@diagram flow
caption: From IAM role to permissions
nodes:
  - "IAM role|ShopDev|app"
  - "Access entry|group shop-devs|info"
  - "RoleBinding|namespace shop|env"
  - "Role|get, list, patch deployments|ok"
@h Bind a group
```yaml title="Role and binding for the shop-devs group"
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: deployer
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
  name: deployer-shop-devs
  namespace: shop
subjects:
  - kind: Group
    name: shop-devs
    apiGroup: rbac.authorization.k8s.io
roleRef:
  kind: Role
  name: deployer
  apiGroup: rbac.authorization.k8s.io
```
```bash title="Create the entry with the group" nocheck
aws eks create-access-entry --cluster-name shop-prod \
  --principal-arn arn:aws:iam::111122223333:role/ShopDev \
  --kubernetes-groups shop-devs
```
@check
Why bind roles to groups? || Membership then follows the IAM role, so removing access is one change in IAM.
@end
