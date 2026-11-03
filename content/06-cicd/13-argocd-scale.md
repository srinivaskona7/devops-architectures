---
title: Argo CD at scale
minutes: 50
objectives:
  - Generate many Applications with ApplicationSets and organise them with app-of-apps
  - Manage multiple clusters and restrict access with projects and RBAC
  - Configure SSO and handle secrets in a GitOps workflow
---
One Application per service per environment per cluster quickly becomes hundreds of objects. These features keep that manageable and secure.

@concept ApplicationSet
@plain
An `ApplicationSet` is a template plus **generators**. The generators produce a list of parameter sets, and the controller creates one Application for each.
@problem
Writing and maintaining a copy of the Application YAML for every cluster or service is repetitive and error prone.
@does
- **List** generator: fixed items. **Cluster** generator: every cluster registered in Argo CD. **Git** generator: directories or files in a repository. **Matrix** and **Merge** combine generators. Pull request generator creates preview apps.
- Template fields use `{{name}}`-style parameters from the generator.
- Applications are created, updated and deleted as the generator output changes.
@diagram flow
caption: Generators produce Applications
nodes:
  - "Generator|clusters or directories|info"
  - "ApplicationSet|template|cp"
  - "Application per item|one each|app"
  - "Clusters|synced independently|env"
@h One Application per directory
```yaml title="applicationset.yaml"
apiVersion: argoproj.io/v1alpha1
kind: ApplicationSet
metadata:
  name: shop-services
  namespace: argocd
spec:
  generators:
    - git:
        repoURL: https://github.com/my-org/shop-config.git
        revision: main
        directories:
          - path: apps/*/overlays/prod
  template:
    metadata:
      name: '{{path[1]}}-prod'
    spec:
      project: shop
      source:
        repoURL: https://github.com/my-org/shop-config.git
        targetRevision: main
        path: '{{path}}'
      destination:
        server: https://kubernetes.default.svc
        namespace: '{{path[1]}}'
      syncPolicy:
        automated: {prune: true, selfHeal: true}
```
@check
What does the Git directory generator produce per directory? || One set of parameters, so one Application per matching directory.
@end

@concept App of apps
@plain
The app-of-apps pattern uses one root Application whose source directory contains other Application manifests. Syncing the root creates all the child apps.
@problem
Bootstrapping a new cluster by applying dozens of Application files by hand is slow and inconsistent.
@does
- The root app points at a folder of Application YAML. Children can be platform add-ons (ingress, cert-manager, monitoring) and team apps.
- Use sync waves on children to order them, for example CRDs and cert-manager first.
- ApplicationSets can replace the folder of files when the apps follow a pattern. Many teams use both.
@diagram layers
caption: Bootstrapping a cluster from one root
layers:
  - {label: "Root", nodes: ["root Application|points at apps/ folder|cp"]}
  - {label: "Platform", nodes: ["cert-manager|wave 0|info", "ingress-nginx|wave 1|info", "monitoring|wave 2|info"]}
  - {label: "Workloads", nodes: ["shop|team app|app", "billing|team app|app"]}
@h Root application
```yaml title="bootstrap/root.yaml"
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: root
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/my-org/platform-config.git
    targetRevision: main
    path: clusters/prod/apps
  destination:
    server: https://kubernetes.default.svc
    namespace: argocd
  syncPolicy:
    automated: {prune: true, selfHeal: true}
```
```bash title="Bootstrap a new cluster" lab
kubectl apply -n argocd -f bootstrap/root.yaml
argocd app list
```
@check
What is created when the root app syncs? || The child Application resources it contains, which in turn deploy their own sources.
@end

@concept Multi-cluster management
@plain
One Argo CD can deploy to many clusters. You register each target cluster, which stores a credential as a Secret, and then set `destination.server` or `destination.name`.
@problem
Running one Argo CD per cluster multiplies upkeep. A central one gives a single view but concentrates risk.
@does
- `argocd cluster add <context>` creates a service account in the target and stores its token. For EKS, the credential uses an IAM role, via an `argocd-k8s-auth` exec config. Check the current docs.
- Labels on cluster secrets feed the Cluster generator, for example `env=prod`, `region=eu-west-1`.
- Alternative: one Argo CD per cluster or per environment tier, with the platform repo bootstrapping each. This limits blast radius.
@diagram cmp
caption: Hub and spoke versus per-cluster
cards:
  - {h: "Central hub", kind: info, items: ["One UI and policy", "Holds credentials to all clusters", "Single point of failure"]}
  - {h: "Per cluster", kind: ok, items: ["Smaller blast radius", "No cross-cluster credentials", "More instances to run"]}
@h Registering a cluster
```bash title="Add an EKS cluster" lab
aws eks update-kubeconfig --name prod-eu --alias prod-eu --region eu-west-1
argocd cluster add prod-eu --label env=prod --label region=eu-west-1
argocd cluster list
```
:::warn
A central Argo CD with cluster-admin to every cluster is a very valuable target. Restrict what it can do with AppProjects, protect its API and enable SSO with MFA.
:::
@end

@concept AppProjects
@plain
An `AppProject` limits which repositories an application may use, which clusters and namespaces it may deploy to, and which resource kinds it may create.
@problem
Without projects, any team with access to Argo CD could deploy anything anywhere, including cluster-wide resources.
@does
- `sourceRepos`, `destinations`, `clusterResourceWhitelist`, `namespaceResourceBlacklist` restrict scope.
- Project roles define permissions and tokens for CI, scoped to that project.
- Sync windows allow or deny syncing during certain times, for change freezes.
@diagram flow
caption: Project guardrails
nodes:
  - "Application|asks to deploy|app"
  - "AppProject|checks repo, cluster, kind|cp"
  - "Allowed|inside scope|ok"
  - "Denied|outside scope|bad"
@h A project for one team
```yaml title="appproject.yaml"
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: shop
  namespace: argocd
spec:
  description: Shop team
  sourceRepos:
    - https://github.com/my-org/shop-config.git
  destinations:
    - server: https://kubernetes.default.svc
      namespace: shop-*
  clusterResourceWhitelist: []
  syncWindows:
    - kind: deny
      schedule: "0 0 * * 5"
      duration: 48h
      applications: ["*-prod"]
```
@check
What does an empty clusterResourceWhitelist do? || It permits no cluster-scoped resources, so the team cannot create things like ClusterRoles.
@end

@concept RBAC in Argo CD
@plain
Argo CD has its own RBAC, separate from Kubernetes. Policies in the `argocd-rbac-cm` ConfigMap say which users or groups may get, sync, override or delete which applications.
@problem
Everyone with UI access should not be able to sync or delete production.
@does
- Policy lines are `p, subject, resource, action, object, effect` and role assignments are `g, group, role`.
- Set `policy.default` to read-only or empty, then add rules.
- Subjects map from SSO groups. Project-scoped roles use objects like `shop/*`.
- Test policies with `argocd admin settings rbac can`.
@diagram layers
caption: Who may do what
layers:
  - {label: "SSO groups", nodes: ["platform-admins|full|ok", "shop-devs|sync staging only|app", "viewers|read only|info"]}
  - {label: "Policies", nodes: ["role admin|all actions|cp", "role shop-dev|get and sync shop/*-staging|cp"]}
@h Policy file
```yaml title="argocd-rbac-cm"
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-rbac-cm
  namespace: argocd
data:
  policy.default: role:readonly
  policy.csv: |
    p, role:shop-dev, applications, get, shop/*, allow
    p, role:shop-dev, applications, sync, shop/*-staging, allow
    g, my-org:shop-devs, role:shop-dev
    g, my-org:platform-admins, role:admin
```
```bash title="Test a rule" lab
argocd admin settings rbac can role:shop-dev sync applications 'shop/shop-prod' \
  --policy-file policy.csv
```
@check
Who can sync production in the policy above? || Only role admin. shop-dev may sync apps ending in -staging.
@end

@concept SSO with OIDC
@plain
Argo CD can log users in through OIDC (directly or through Dex). Your identity provider supplies the user and group claims that the RBAC policy uses.
@problem
Shared local passwords cannot be revoked per person and give no audit trail.
@does
- Configure `oidc.config` in `argocd-cm` with issuer, client ID and a secret reference. Use `groups` claim scope.
- Dex can sit in front of providers that need it, such as GitHub or LDAP.
- Disable the built-in `admin` account once SSO works, and use the `argocd-secret` or external secret for the client secret.
- CLI login uses `argocd login --sso`.
@diagram seq
caption: Login through an identity provider
actors: ["Browser|user|ext", "Argo CD|API server|cp", "IdP|OIDC provider|ext"]
steps:
  - "0>1: open login | req"
  - "1>0: redirect to IdP | resp"
  - "0>2: authenticate with MFA | tls"
  - "2>1: code, then ID token with groups | tls"
  - "1>0: session with RBAC role | resp"
@h OIDC configuration
```yaml title="argocd-cm excerpt"
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  url: https://argocd.example.com
  admin.enabled: "false"
  oidc.config: |
    name: Company SSO
    issuer: https://idp.example.com
    clientID: argocd
    clientSecret: $oidc.clientSecret
    requestedScopes: [openid, profile, email, groups]
```
:::note
`$oidc.clientSecret` is read from the `argocd-secret` Secret. Keep the value out of Git.
:::
@end

@concept Secrets in GitOps
@plain
Git cannot hold plain Kubernetes Secrets. Instead you commit an encrypted form or a reference, and a controller turns it into a Secret in the cluster.
@problem
GitOps wants everything in Git, but credentials in Git are a breach. You need a pattern that keeps the workflow without exposing secrets.
@does
- **External Secrets Operator**: Git holds an `ExternalSecret` that names a key in AWS Secrets Manager or Parameter Store. The operator creates the Secret. Auth uses IRSA or Pod Identity.
- **Sealed Secrets**: encrypt with a cluster public key and commit the `SealedSecret`. Only the cluster can decrypt.
- **SOPS** with KMS: encrypt files in Git. Needs a plugin for Argo CD or a Flux feature.
- Avoid Argo CD plugins that put decrypted values into the repo server cache if you can use operators instead.
@diagram flow
caption: External Secrets pattern
nodes:
  - "Git|ExternalSecret reference|info"
  - "Argo CD|syncs the reference|cp"
  - "External Secrets Operator|reads from AWS|app"
  - "Secret in cluster|never in Git|ok"
@h ExternalSecret
```yaml title="Pull a database password from AWS Secrets Manager"
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: shop-db
  namespace: shop
spec:
  refreshInterval: 1h
  secretStoreRef:
    kind: ClusterSecretStore
    name: aws-secrets-manager
  target:
    name: shop-db
  data:
    - secretKey: password
      remoteRef:
        key: prod/shop/db
        property: password
```
@check
What does Git store when using External Secrets? || Only a reference to the secret in the external store, not the value.
@end
