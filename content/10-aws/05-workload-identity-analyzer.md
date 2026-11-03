---
title: Workload identity for Kubernetes and Access Analyzer
minutes: 45
objectives:
  - Give pods AWS permissions with IRSA and EKS Pod Identity and choose between them
  - Scope roles per service account and verify what a pod actually assumes
  - Use IAM Access Analyzer and CloudTrail to find and remove excess access
---
Pods are the most common place long-lived AWS keys leak. Both IRSA and Pod Identity give each Kubernetes service account its own short-lived role, which also works for Kyma workloads that call AWS APIs through OIDC federation.

@concept Why pods need their own identity
@plain
If a pod uses the node's instance role, every pod on that node gets the same permissions. Pod-level identity gives each service account only the role it needs.
@problem
One compromised pod with node credentials can read S3, pull secrets and call any API the node can, across all workloads on the node.
@does
- Node role should be minimal: join the cluster, pull images, nothing else.
- Each workload gets a role mapped to its Kubernetes **service account**.
- Credentials are temporary and delivered by a token file or an agent, not stored in a Secret.
@diagram cmp
caption: Node role versus pod role
cards:
  - {h: "Node instance role", kind: bad, items: ["Shared by all pods", "Large blast radius", "Reachable through IMDS"]}
  - {h: "IRSA", kind: ok, items: ["Per service account", "OIDC web identity", "Works anywhere with an OIDC issuer"]}
  - {h: "Pod Identity", kind: ok, items: ["Per service account", "Managed by an EKS agent", "EKS native"]}
@end

@concept IRSA mechanics
@plain
**IAM Roles for Service Accounts** uses the cluster's OIDC issuer. Kubernetes projects a signed token into the pod, and the AWS SDK exchanges it for role credentials.
@problem
Before IRSA, teams used kube2iam-style proxies or node roles. IRSA uses standard OIDC federation with no extra agent.
@does
- Create an IAM OIDC provider for the cluster's issuer URL.
- The role trust policy allows `sts:AssumeRoleWithWebIdentity` with `sub` equal to `system:serviceaccount:<namespace>:<name>` and `aud` equal to `sts.amazonaws.com`.
- Annotate the service account with `eks.amazonaws.com/role-arn`. A mutating webhook injects `AWS_ROLE_ARN` and `AWS_WEB_IDENTITY_TOKEN_FILE` and a projected token volume.
- Use a recent SDK that supports the web identity provider in its credential chain.
@diagram seq
caption: IRSA credential exchange
actors: ["Pod|SDK in app|app", "kubelet|projects token|cp", "STS|AssumeRoleWithWebIdentity|ext"]
steps:
  - "1>0: projected service account JWT file | resp"
  - "0>2: exchange JWT for role | req"
  - "note 2..2: verify issuer, sub, aud against trust policy"
  - "2>0: temporary credentials, refreshed before expiry | resp"
@h Trust policy and service account
```json title="irsa-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"Federated": "arn:aws:iam::111122223333:oidc-provider/oidc.eks.eu-west-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE"},
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringEquals": {
          "oidc.eks.eu-west-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE:sub": "system:serviceaccount:shop:orders",
          "oidc.eks.eu-west-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE:aud": "sts.amazonaws.com"
        }
      }
    }
  ]
}
```
```yaml title="serviceaccount.yaml"
apiVersion: v1
kind: ServiceAccount
metadata:
  name: orders
  namespace: shop
  annotations:
    eks.amazonaws.com/role-arn: arn:aws:iam::111122223333:role/shop-orders
```
```bash title="Verify inside the pod" lab
kubectl -n shop exec deploy/orders -- env | grep AWS_
kubectl -n shop exec deploy/orders -- aws sts get-caller-identity
```
:::note
The `sub` condition is what isolates workloads. Without it, any service account in the cluster could assume the role.
:::
@check
What does the webhook inject into the pod for IRSA? || AWS_ROLE_ARN, AWS_WEB_IDENTITY_TOKEN_FILE and a projected service account token volume.
@end

@concept EKS Pod Identity
@plain
**EKS Pod Identity** associates an IAM role with a service account through the EKS API. An agent on each node serves credentials to the pods.
@problem
IRSA needs an OIDC provider per cluster, a trust policy that embeds the cluster's issuer ID, and edits to every role when you add clusters. That is awkward at scale.
@does
- Install the **EKS Pod Identity Agent** add-on (a DaemonSet).
- The role trust principal is the service `pods.eks.amazonaws.com` with actions `sts:AssumeRole` and `sts:TagSession`. The same role can be reused across clusters.
- Create an association: cluster, namespace, service account, role. No annotation is needed on the service account.
- Credentials are tagged with cluster, namespace and service account names, enabling ABAC policies.
- Works on EKS clusters with EC2 nodes; check the current documentation for support on other compute types and for SDK version requirements.
@diagram flow
caption: Pod Identity setup
numbered: true
nodes:
  - "Add-on|eks-pod-identity-agent|cp"
  - "Role|trust pods.eks.amazonaws.com|info"
  - "Association|namespace and service account|env"
  - "Pod starts|SDK container credentials|app"
  - "Agent returns|temporary credentials|ok"
@h Create the role and association
```json title="pod-identity-trust.json"
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
```bash title="Associate" lab
aws eks create-addon --cluster-name prod --addon-name eks-pod-identity-agent
aws iam create-role --role-name shop-orders --assume-role-policy-document file://pod-identity-trust.json
aws eks create-pod-identity-association --cluster-name prod \
  --namespace shop --service-account orders --role-arn arn:aws:iam::111122223333:role/shop-orders
aws eks list-pod-identity-associations --cluster-name prod
```
@choose IRSA or Pod Identity
Pod Identity | new EKS clusters and many clusters sharing roles | non-EKS clusters or compute types it does not support
IRSA | clusters outside EKS, or Fargate where supported only via IRSA | you want to avoid per-cluster trust edits
Node role | never for workloads | any workload with real permissions
@end

@concept Scoping and ABAC for pods
@plain
Role design for pods follows the same rules as everywhere, with the extra goal of one role per workload, and policies that use session tags.
@problem
Sharing one role among many service accounts in a namespace undermines the isolation you set up.
@does
- One role per service account with only the actions and resources needed.
- With Pod Identity, session tags such as `eks-cluster-name`, `kubernetes-namespace` and `kubernetes-service-account` allow ABAC conditions like `aws:PrincipalTag/kubernetes-namespace`.
- Block the pod's access to node credentials with IMDS hop limit 1 once all pods have their own identity.
- Use network policy or egress controls to limit reach to the IMDS address as defence in depth.
@diagram layers
caption: Defence in depth for pod credentials
layers:
  - {label: "Identity", nodes: ["Role per service account|least privilege|ok", "Session tags|ABAC conditions|info"]}
  - {label: "Node", nodes: ["Minimal node role|join and pull only|ok", "IMDSv2 hop limit 1|pods cannot reach|ok"]}
  - {label: "Network", nodes: ["Egress policy|block 169.254.169.254 for pods|warn"]}
@h ABAC on namespace
```json title="namespace-scoped-s3.json"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::acme-apps/${aws:PrincipalTag/kubernetes-namespace}/*"
    }
  ]
}
```
@check
Why set IMDS hop limit to 1 on nodes? || A container adds a network hop, so pods cannot reach the metadata service and borrow the node role.
@end

@concept IAM Access Analyzer
@plain
**IAM Access Analyzer** finds resources shared outside your account or organization, unused access, and validates policies.
@problem
Bucket, role and key policies drift. People forget a public bucket or an old cross-account trust.
@does
- **External access analyzer**: findings for S3 buckets, IAM roles, KMS keys, SQS queues, Secrets Manager secrets, Lambda and more that grant access to principals outside the zone of trust (account or organization).
- **Unused access analyzer**: reports unused roles, access keys, passwords and permissions based on a tracking period you choose; this is a paid feature, check pricing.
- **Policy validation** and **custom policy checks** (for example "does this change grant new access?") can run in CI.
- **Policy generation** builds a least-privilege policy from CloudTrail.
@diagram flow
caption: Using Access Analyzer in the delivery process
numbered: true
nodes:
  - "Policy in PR|Terraform plan|plain"
  - "Validate|check-no-new-access|info"
  - "Deploy|apply|app"
  - "Analyzer scans|external and unused findings|cp"
  - "Archive or fix|ticket and remediate|ok"
@h CLI
```bash title="Analyzer in practice" lab
aws accessanalyzer create-analyzer --analyzer-name org --type ORGANIZATION
aws accessanalyzer list-findings-v2 --analyzer-arn arn:aws:access-analyzer:eu-west-1:111122223333:analyzer/org \
  --filter '{"status":{"eq":["ACTIVE"]}}' --query 'findings[].[resourceType,resource,findingType]' --output table
aws accessanalyzer validate-policy --policy-type IDENTITY_POLICY --policy-document file://s3-read-reports.json \
  --query 'findings[].[findingType,issueCode]'
```
:::tip
Run `validate-policy` in CI on every IAM change. It catches wrong action names and risky patterns before apply.
:::
@end

@concept Auditing IAM with CloudTrail
@plain
**CloudTrail** records API calls. It is the evidence for who assumed which role, which action was denied, and what a role really uses.
@problem
When access breaks or an incident occurs you need a timeline of identity events.
@does
- An organization trail delivers management events from all accounts to the log archive bucket. Enable log file validation.
- Useful events: `AssumeRole`, `AssumeRoleWithWebIdentity`, `ConsoleLogin`, `CreateAccessKey`, `AttachRolePolicy`, and any `errorCode` of `AccessDenied`.
- `userIdentity.sessionContext` shows the role and the original principal behind a session; the session name is your attribution key.
- Query with CloudTrail Lake or Athena over the S3 logs.
@diagram flow
caption: From API call to answer
nodes:
  - "API call|any principal|app"
  - "CloudTrail|management events|cp"
  - "S3 log archive|validated, immutable|ok"
  - "Athena or Lake|query by role and time|info"
@h Find denied calls and role assumptions
```bash title="Quick lookups" lab
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=AssumeRole \
  --max-results 5 --query 'Events[].[EventTime,Username]' --output table
aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=CreateAccessKey --max-results 10
```
```sql title="Athena over the trail table" nocheck
SELECT eventtime, useridentity.arn, eventname, errorcode
FROM cloudtrail_logs
WHERE errorcode = 'AccessDenied' AND eventtime > '2026-10-01'
ORDER BY eventtime DESC LIMIT 50;
```
@end
