---
title: Environments and configuration
minutes: 40
objectives:
  - Design dev, staging and production environments with the right level of parity
  - Separate configuration and secrets from the build artifact
  - Use namespaces, accounts and infrastructure as code to keep environments consistent
---
An **environment** is a place where your software runs with its own data, configuration and access rules. Good environment design lets you test realistically without risking production.

@concept The environment ladder
@plain
Changes move upward through environments: a developer machine, shared development, test or staging, and production. Each step is more realistic and more controlled.
@problem
Testing straight in production risks customers. Testing only on laptops misses problems from real networks, data volumes and configuration.
@does
- **Local**: fast feedback for one developer (containers, kind, minikube).
- **Dev / integration**: shared, changes often, may be unstable.
- **Staging / pre-production**: close copy of production for final checks, load and rehearsal of deployments.
- **Production**: real users, strictest access. Some teams add per-pull-request preview environments that exist only while the PR is open.
@diagram flow
caption: Promotion through environments
nodes:
  - "Local|developer laptop|app"
  - "Dev|integration, unstable|env"
  - "Staging|production-like|warn"
  - "Production|real users|ok"
@h Cluster layout options
```bash title="Separating environments with namespaces and clusters" lab
kubectl create namespace shop-dev --dry-run=client -o yaml
kubectl create namespace shop-staging --dry-run=client -o yaml
echo "production should be a separate cluster and cloud account for strong isolation"
```
@check
Why use a preview environment per pull request? || Reviewers can test the change in isolation before it merges.
@end

@concept Environment parity
@plain
Parity means non-production environments behave like production in the ways that matter: versions, topology, configuration shape and (safe) data.
@problem
"Works on my machine" and "works in staging" failures come from differences: another database version, no TLS, one replica instead of three.
@does
- Use the same artifact, same base images and same deployment method in every environment.
- Differences should be explicit and small: scale, size, credentials, data.
- Run the same database engine and major version; avoid substituting SQLite for Postgres.
- Cost trade-off: staging can run smaller, but configure the same number of zones or replicas when testing resilience.
@diagram cmp
caption: What must match and what may differ
cards:
  - {h: "Keep identical", kind: ok, items: ["Container image digest", "Database engine and version", "Deployment tooling", "Network policy shape"]}
  - {h: "May differ", kind: info, items: ["Replica counts and node sizes", "Credentials and endpoints", "Data volume (use masked data)"]}
@h Compare environments
```bash title="Diff what runs in two clusters" lab
kubectl --context staging get deploy -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image --no-headers 2>/dev/null | sort > /tmp/staging.txt
kubectl --context prod get deploy -A -o custom-columns=NS:.metadata.namespace,NAME:.metadata.name,IMAGE:.spec.template.spec.containers[0].image --no-headers 2>/dev/null | sort > /tmp/prod.txt
diff /tmp/staging.txt /tmp/prod.txt | head || true
```
@check
Which should always be identical between staging and production? || The deployed artifact (image digest) and the way it is deployed.
@end

@concept Configuration and the twelve-factor approach
@plain
Configuration is everything that changes between environments: URLs, credentials, feature settings. It should live outside the build artifact and be injected at deploy or run time.
@problem
If configuration is baked into the image, you need a different build per environment, so what you tested is not what you deploy.
@does
- Store config in environment variables, ConfigMaps or a config service; keep secrets in a secrets manager.
- One build, many deploys: promote the same image with different values.
- Keep configuration in Git (with secrets encrypted or referenced) so changes are reviewed and auditable.
- Validate config at startup and fail fast with clear errors.
@diagram layers
caption: Build once, configure per environment
layers:
  - {label: "Artifact", nodes: ["Image sha256|identical everywhere|app"]}
  - {label: "Config", nodes: ["values-dev.yaml|env", "values-staging.yaml|env", "values-prod.yaml|env"]}
  - {label: "Secrets", nodes: ["External secrets|from AWS Secrets Manager or Vault|warn"]}
@h Helm values per environment
```yaml title="values-prod.yaml"
replicaCount: 4
image:
  repository: registry.example.com/shop/api
  digest: sha256:3f1c0e9d5a7b4c2e8f6a1d9b0c3e5f7a2b4d6c8e0f1a3b5c7d9e1f2a4b6c8d0e
config:
  logLevel: info
  paymentsUrl: https://payments.example.com
resources:
  requests: {cpu: 500m, memory: 512Mi}
  limits: {memory: 512Mi}
```
```bash title="Deploy the same chart per environment" lab
helm template shop ./chart -f values-staging.yaml 2>/dev/null | head -5
helm upgrade --install shop ./chart -n shop-staging -f values-staging.yaml --dry-run 2>/dev/null | head -5
```
@check
Why is baking config into images a problem? || It forces different builds per environment, so the tested artifact differs from the deployed one.
@end

@concept Secrets management
@plain
Secrets are credentials: passwords, API keys, tokens and certificates. They need stricter handling than other config: no plain text in Git, tight access, rotation and audit.
@problem
Secrets committed to repositories leak through forks, logs and laptops. A single leaked key can compromise an entire cloud account.
@does
- Use a secrets manager (AWS Secrets Manager, Parameter Store, HashiCorp Vault) and fetch at run time, for example through External Secrets Operator or the CSI driver.
- Prefer short-lived, workload-bound identity (IRSA or EKS Pod Identity) over long-lived keys.
- Kubernetes Secrets are only base64 encoded; enable encryption at rest and restrict RBAC.
- Scan commits for secrets; rotate any key that ever appeared in Git.
@diagram seq
caption: A pod fetching a secret without a stored key
actors: ["Pod|service account|app", "AWS STS|issues temporary credentials|cp", "Secrets Manager|stores the secret|ext"]
steps:
  - "0>1: present projected service account token | tls"
  - "1>0: short-lived credentials | resp"
  - "0>2: GetSecretValue | req"
  - "2>0: secret value | resp"
@h A secret reference
```yaml title="External Secrets Operator"
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: shop-db
  namespace: shop
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: aws-secrets
    kind: ClusterSecretStore
  target:
    name: shop-db
  data:
    - secretKey: password
      remoteRef:
        key: prod/shop/db
        property: password
```
:::danger
If a secret was ever committed, deleting the file is not enough. It remains in Git history; revoke and rotate the credential immediately.
:::
@check
Are Kubernetes Secrets encrypted by default? || No. They are base64 encoded in etcd unless encryption at rest or an external KMS provider is configured.
@end

@concept Test data and data protection
@plain
Non-production environments need realistic data without exposing real customers. Use generated or masked data.
@problem
Copying production databases to staging puts personal data in places with weaker controls, which breaks privacy law such as GDPR and DPDP.
@does
- Generate synthetic data that matches shapes and volumes.
- When copying production, mask or tokenise personal fields, and restrict access.
- Keep seeds in version control so environments can be rebuilt on demand.
- Limit retention and clean up preview environment data automatically.
@diagram flow
caption: Safe data refresh
numbered: true
nodes:
  - "Production snapshot|restricted|warn"
  - "Mask and subset|remove PII|app"
  - "Load to staging|fresh weekly|env"
  - "Audit|who accessed|info"
@h Masking in SQL
```bash title="Mask personal fields after restore" lab
cat <<'SQL'
UPDATE customers
SET email = 'user' || id || '@example.test',
    phone = NULL,
    name  = 'Customer ' || id;
SQL
```
@check
Why use synthetic data? || It carries no personal information, so there is no privacy risk and tests are repeatable.
@end

@concept Infrastructure as code for environments
@plain
Define every environment in code (Terraform, Helm, Kustomize, GitOps), so creating or recreating one is a repeatable, reviewed operation.
@problem
Hand-built environments drift. Nobody remembers how staging was configured, so it differs from production in untracked ways.
@does
- Terraform modules create accounts, VPCs, clusters; Helm or Kustomize layer per-environment overlays.
- GitOps (Argo CD, Flux) syncs a Git directory per environment to a cluster and corrects drift.
- Ephemeral environments are created and destroyed on demand, which saves cost and proves the code can rebuild everything.
- Detect drift with plan or diff regularly.
@diagram flow
caption: Environment from code
nodes:
  - "Git|env folders|app"
  - "Terraform|accounts, cluster|cp"
  - "GitOps|syncs manifests|env"
  - "Running environment|matches Git|ok"
@h Layout
```text title="Repository layout for environments"
infra/
  modules/eks/
  envs/dev/main.tf
  envs/staging/main.tf
  envs/prod/main.tf
deploy/
  base/
  overlays/dev/
  overlays/staging/
  overlays/prod/
```
```bash title="Detect drift" lab
terraform -chdir=infra/envs/staging plan -detailed-exitcode 2>/dev/null; echo "exit 0 no change, 2 drift or changes"
kubectl diff -k deploy/overlays/staging 2>/dev/null | head
```
@check
What does GitOps add beyond running kubectl apply from a pipeline? || A controller continuously compares the cluster with Git and corrects drift.
@end
