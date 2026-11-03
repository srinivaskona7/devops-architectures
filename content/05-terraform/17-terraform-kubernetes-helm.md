---
title: Terraform for Kubernetes and Helm
minutes: 55
objectives:
  - Configure the Kubernetes and Helm providers against an EKS cluster without a chicken and egg problem
  - Decide what Terraform should own inside a cluster and what belongs to GitOps
  - Manage CRDs, namespaces and Helm releases safely
---
Terraform builds the cluster well. It can also create objects inside the cluster, but the boundary needs care or plans become slow and fragile.

@concept Kubernetes and Helm provider authentication
@plain
The Kubernetes and Helm providers need the API server address and a token. For EKS you take them from the cluster and ask the AWS CLI for a short-lived token each time.
@problem
Hard-coded kubeconfig files break in CI. A static token expires. The provider must authenticate fresh on every run.
@does
- `exec` auth runs `aws eks get-token`, so the token is always valid and no secret is stored.
- Endpoint and CA come from a data source or from module outputs.
- The Helm provider repeats the same settings in its own `kubernetes` block. In Helm provider 3.x this became an attribute; check the current docs for your version.
- The CI role needs `eks:DescribeCluster` and an EKS access entry with Kubernetes permissions.
@diagram flow
caption: Provider gets a token on every run
nodes:
  - "Terraform|plan or apply|app"
  - "aws eks get-token|short-lived token|info"
  - "EKS API server|checks access entry|cp"
  - "Cluster objects|namespaces, releases|ok"
@h Provider configuration
```hcl title="providers.tf"
data "aws_eks_cluster" "this" {
  name = var.cluster_name
}

provider "kubernetes" {
  host                   = data.aws_eks_cluster.this.endpoint
  cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

  exec {
    api_version = "client.authentication.k8s.io/v1beta1"
    command     = "aws"
    args        = ["eks", "get-token", "--cluster-name", var.cluster_name]
  }
}

provider "helm" {
  kubernetes {
    host                   = data.aws_eks_cluster.this.endpoint
    cluster_ca_certificate = base64decode(data.aws_eks_cluster.this.certificate_authority[0].data)

    exec {
      api_version = "client.authentication.k8s.io/v1beta1"
      command     = "aws"
      args        = ["eks", "get-token", "--cluster-name", var.cluster_name]
    }
  }
}
```
@check
Why use exec instead of a stored token? || The token lives about 15 minutes, so a stored one expires; exec fetches a fresh one on each run and nothing secret is saved.
@end

@concept The cluster and its providers in one state
@plain
If one configuration creates the EKS cluster and also configures the Kubernetes provider from that same cluster, the provider has no address on the first plan.
@problem
Provider blocks are evaluated early. Values that are only known after apply produce errors such as an invalid host or a connection to localhost.
@does
- Best fix: two stacks. Stack one creates the cluster. Stack two reads it with a data source and creates in-cluster objects.
- Workaround: `terraform apply -target=module.eks` first, then a full apply. Acceptable for bootstrap, poor as a routine.
- Never destroy the cluster and the objects in the same run; the provider disappears before it deletes its resources.
- Keep the stacks small: cluster, then addons, then apps.
@diagram flow
caption: Split the stacks to remove the cycle
numbered: true
nodes:
  - "Stack 1|VPC and EKS|app"
  - "State output|name, endpoint|info"
  - "Stack 2|reads cluster by data source|cp"
  - "In-cluster objects|helm releases, namespaces|ok"
@h Recovering from a bad first apply
```bash title="Bootstrap with targeting" lab
terraform apply -target=module.eks
terraform apply
```
:::warn
`-target` is for recovery and bootstrap. Using it routinely hides dependencies and leaves partial state.
:::
@end

@concept Namespaces, RBAC and quotas with the Kubernetes provider
@plain
Typed resources such as `kubernetes_namespace_v1` let Terraform create the objects every team needs on day one.
@problem
Each new team needs a namespace, a quota and a role binding. Doing it by hand drifts quickly.
@does
- Create the namespace, a `ResourceQuota` and a `LimitRange`, and bind a group to a role.
- Use `for_each` over a map of teams, so adding a team is one new map entry.
- Resource names in newer provider versions end in `_v1`; check the provider docs for the exact type names.
- Labels such as `pod-security.kubernetes.io/enforce` set the Pod Security level per namespace.
@diagram flow
caption: One map entry per team
nodes:
  - "teams map|name, cpu, memory|info"
  - "Namespace|with security labels|app"
  - "ResourceQuota|caps usage|cp"
  - "RoleBinding|team group gets edit|ok"
@h Per-team namespaces
```hcl title="teams.tf"
variable "teams" {
  type = map(object({
    cpu    = string
    memory = string
  }))
  default = {
    payments = { cpu = "20", memory = "64Gi" }
    search   = { cpu = "10", memory = "32Gi" }
  }
}

resource "kubernetes_namespace_v1" "team" {
  for_each = var.teams

  metadata {
    name = each.key
    labels = {
      "pod-security.kubernetes.io/enforce" = "baseline"
    }
  }
}

resource "kubernetes_resource_quota_v1" "team" {
  for_each = var.teams

  metadata {
    name      = "compute"
    namespace = kubernetes_namespace_v1.team[each.key].metadata[0].name
  }

  spec {
    hard = {
      "requests.cpu"    = each.value.cpu
      "requests.memory" = each.value.memory
    }
  }
}
```
@end

@concept helm_release for platform add-ons
@plain
`helm_release` installs a chart as a Terraform resource. It suits platform add-ons such as the AWS Load Balancer Controller, cert-manager or metrics-server.
@problem
These add-ons need IAM roles and cluster values that only Terraform knows, such as the cluster name and the IRSA role ARN.
@does
- Pin `version` of the chart; never track latest.
- Pass values with `values = [file(...)]` or `yamlencode(...)` and `set` for single values from other resources.
- `atomic = true` rolls back on failure; `wait = true` waits for readiness; set `timeout`.
- Helm state lives in the cluster as release secrets; Terraform stores a copy of rendered values, so do not put secrets in values.
@diagram flow
caption: Terraform wires IAM into the chart
nodes:
  - "IAM role for service account|created by Terraform|cp"
  - "helm_release|chart pinned to a version|app"
  - "Controller pod|uses the role|ok"
@h Load Balancer Controller release
```hcl title="lbc.tf"
resource "helm_release" "aws_lbc" {
  name       = "aws-load-balancer-controller"
  namespace  = "kube-system"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = "1.8.1"
  atomic     = true
  timeout    = 600

  values = [yamlencode({
    clusterName = var.cluster_name
    serviceAccount = {
      name = "aws-load-balancer-controller"
      annotations = {
        "eks.amazonaws.com/role-arn" = aws_iam_role.lbc.arn
      }
    }
  })]
}
```
:::note
The chart version above is only an example. Look up the current version of the chart before use.
:::
@check
What does atomic = true do? || If the install or upgrade fails, Helm rolls the release back instead of leaving it half applied.
@end

@concept CRDs and kubernetes_manifest
@plain
`kubernetes_manifest` applies any YAML object, including custom resources, by turning it into an HCL object.
@problem
Typed resources do not exist for every CRD such as a ClusterIssuer or a Karpenter NodePool.
@does
- The provider needs the CRD to exist and the cluster to be reachable at **plan** time, to read the schema. Installing the CRD in the same apply fails on a fresh cluster.
- Install CRDs through the chart in one stack, then create custom resources in a later stack or run.
- Alternative: `kubectl_manifest` from the community `alekc/kubectl` provider applies raw YAML without needing the schema at plan time.
- Or leave custom resources to GitOps, which is the usual answer.
@diagram cmp
caption: Three ways to create a custom resource
cards:
  - {h: "kubernetes_manifest", kind: warn, items: ["Official provider", "Needs CRD at plan time", "Two-step on new clusters"]}
  - {h: "kubectl_manifest", kind: ok, items: ["Community provider", "Raw YAML, no schema", "Applies in one run"]}
  - {h: "GitOps", kind: ok, items: ["Argo CD or Flux applies it", "Terraform not involved", "Best for apps"]}
@h A ClusterIssuer
```hcl title="issuer.tf"
resource "kubernetes_manifest" "issuer" {
  manifest = {
    apiVersion = "cert-manager.io/v1"
    kind       = "ClusterIssuer"
    metadata   = { name = "letsencrypt" }
    spec = {
      acme = {
        server = "https://acme-v02.api.letsencrypt.org/directory"
        email  = "platform@example.com"
        privateKeySecretRef = { name = "letsencrypt-key" }
        solvers = [{ http01 = { ingress = { ingressClassName = "nginx" } } }]
      }
    }
  }

  depends_on = [helm_release.cert_manager]
}
```
@end

@concept Terraform or GitOps for in-cluster objects
@plain
Both can create objects in a cluster. The question is who owns which layer.
@problem
When both manage the same object they fight, and changes arrive from two places with two review flows.
@does
- Terraform: things with cloud ties and a slow rate of change such as the cluster, IAM roles, the first Argo CD install, namespaces for platform.
- GitOps: everything that changes with application releases, including Helm releases of workloads.
- One owner per object. Never let both manage the same resource.
- Terraform output values (role ARNs, subnet IDs) can be handed to GitOps through a ConfigMap or an Argo CD cluster secret label.
@diagram layers
caption: Ownership by layer
layers:
  - {label: "Terraform", nodes: ["VPC and EKS|cloud resources|cp", "IAM roles|IRSA, Pod Identity|cp", "Argo CD bootstrap|one release|cp"]}
  - {label: "GitOps", nodes: ["Platform add-ons|ingress, monitoring|app", "Applications|every release|app"]}
@choose Who should manage it
Terraform helm_release | Add-ons tied to IAM or cluster values, small team, no GitOps yet | Large numbers of apps that change daily
Argo CD or Flux | Anything released often, many teams | Resources needing Terraform-only values with no handoff
@check
Why must one owner manage each object? || Two controllers reconcile to different desired states and keep overwriting each other, causing drift and noisy plans.
@end

@concept Safe upgrades, drift and the plan cost of many objects
@plain
Every Kubernetes object in state is refreshed on each plan, which costs one API call each. Large in-cluster states make plans slow.
@problem
Plans that take ten minutes slow everyone and tempt people to skip review.
@does
- Keep in-cluster Terraform small, ideally under a few hundred objects.
- Use `ignore_changes` for fields controllers modify, such as HPA-managed replicas.
- Upgrade a chart by bumping `version` in a reviewed change and reading the plan diff of values.
- Use `terraform plan -refresh=false` only for quick checks, never before apply in automation.
- `helm_release` drift: someone ran `helm upgrade` by hand. The next plan shows the difference; decide who is right and revert.
@diagram flow
caption: Chart upgrade workflow
numbered: true
nodes:
  - "Bump version|pull request|app"
  - "Plan diff|values and chart changes|info"
  - "Staging apply|watch the release|warn"
  - "Production apply|same pull request|ok"
@h Ignore a controller-owned field
```hcl title="ignore replicas" nocheck
resource "kubernetes_deployment_v1" "api" {
  # ...
  lifecycle {
    ignore_changes = [spec[0].replicas]
  }
}
```
@end
