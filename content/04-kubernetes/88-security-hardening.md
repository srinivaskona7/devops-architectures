---
title: Security hardening
minutes: 60
objectives:
  - Audit a cluster against the CIS Kubernetes Benchmark
  - Apply seccomp, AppArmor and runtime detection with Falco
  - Enforce supply chain admission, encrypt secrets at rest and enable audit logging
---
Hardening is a set of layers. Each layer assumes the previous one can fail. This page covers the controls that sit around the cluster, the node and the workload.

@concept CIS Benchmark and kube-bench
@plain
The CIS Kubernetes Benchmark is a checklist of secure settings for the control plane, etcd, kubelet and policies. kube-bench runs the checks automatically.
@problem
Hundreds of flags and file permissions are easy to get wrong and hard to review by hand.
@does
- kube-bench runs as a Job on a node and reports PASS, FAIL, WARN with remediation text per check.
- Pick the benchmark that matches your platform (generic, EKS, GKE, AKS) with `--benchmark`.
- On managed control planes (EKS, Gardener) you can only check what you own: worker nodes, kubelet and workloads. The provider covers the rest.
- Treat findings as input, not as absolute truth. Record accepted risks.
@diagram flow
caption: Audit loop
nodes:
  - "Run kube-bench|Job on node|app"
  - "Report|PASS FAIL WARN|info"
  - "Fix or accept|record decision|warn"
  - "Re-run in CI|track drift|ok"
@h Run it
```bash title="kube-bench as a Job" lab
kubectl apply -f https://raw.githubusercontent.com/aquasecurity/kube-bench/main/job.yaml
kubectl logs job/kube-bench | grep -E '^\[(FAIL|WARN)\]' | head -20
kubectl delete job kube-bench
```
:::note
The job manifest depends on the platform. Use the variant for EKS or others from the kube-bench repository.
:::
@end

@concept Node and kubelet hardening
@plain
The kubelet exposes an API on each node. Closing it down and keeping nodes minimal limits what an attacker can do after reaching a node.
@problem
An open kubelet read-write port or anonymous access can lead to code execution in any Pod on the node.
@does
- Kubelet settings: `authentication.anonymous.enabled: false`, `authorization.mode: Webhook`, `readOnlyPort: 0`, `protectKernelDefaults: true`, `rotateCertificates: true`.
- Use a minimal, immutable node OS (Bottlerocket, Flatcar, Garden Linux in Gardener) and no SSH where possible.
- IMDS on AWS: require IMDSv2 and a hop limit of 1 so Pods cannot reach node credentials; use IRSA or Pod Identity instead.
- Patch nodes by replacing them, not in place.
@diagram layers
caption: Defence on the node
layers:
  - {label: "Workload", nodes: ["Pod security|restricted profile|ok"]}
  - {label: "Kubelet", nodes: ["No anonymous|webhook authz|cp", "No read-only port|port 0|cp"]}
  - {label: "Host", nodes: ["Immutable OS|few packages|info", "IMDSv2 hop limit 1|no creds from Pods|info"]}
@h Kubelet configuration
```yaml title="Hardened KubeletConfiguration" nocheck
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
authentication:
  anonymous:
    enabled: false
  webhook:
    enabled: true
authorization:
  mode: Webhook
readOnlyPort: 0
protectKernelDefaults: true
rotateCertificates: true
serverTLSBootstrap: true
```
@check
Why limit the IMDS hop limit to 1? || A Pod network adds a hop, so Pods cannot reach node credentials while the node itself still can.
@end

@concept Seccomp and AppArmor
@plain
Seccomp filters which Linux system calls a container may make. AppArmor restricts file, network and capability access by profile.
@problem
By default a container may call hundreds of syscalls, many unneeded and some used in kernel exploits.
@does
- `securityContext.seccompProfile.type: RuntimeDefault` applies the container runtime default profile. It is required by the Pod Security restricted level.
- `Localhost` uses a custom profile stored on the node; the Security Profiles Operator can distribute and record profiles.
- AppArmor: since Kubernetes 1.30 use the `securityContext.appArmorProfile` field (older versions used annotations). Requires AppArmor on the node OS. On SELinux hosts use `seLinuxOptions`.
- Roll out in stages, test for denied syscalls in staging first.
@diagram flow
caption: Syscall filtering
nodes:
  - "Process in container|calls ptrace|app"
  - "seccomp filter|RuntimeDefault|cp"
  - "Allowed|read, write, open|ok"
  - "Blocked|returns EPERM|bad"
@h Pod example
```yaml title="Pod with seccomp and AppArmor"
apiVersion: v1
kind: Pod
metadata:
  name: hardened
spec:
  securityContext:
    runAsNonRoot: true
    runAsUser: 10001
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: registry.example.com/shop/api:1.8.3
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        capabilities:
          drop: ["ALL"]
        appArmorProfile:
          type: RuntimeDefault
```
@end

@concept Runtime security with Falco
@plain
Falco watches system calls and Kubernetes audit events and raises alerts when behaviour matches a rule, such as a shell opened inside a container.
@problem
Admission checks stop bad configuration, not a running exploited process. You need detection at runtime.
@does
- Uses a kernel driver (modern eBPF probe) to observe events with container and Pod metadata.
- Default rules: shell in container, write below /etc, reading sensitive files, unexpected outbound connections, privilege escalation.
- Falcosidekick forwards alerts to Slack, SIEM, webhooks. Falco Talon can respond (for example label or delete the Pod).
- Tune rules for noise; start in alert-only mode. Alternatives with similar goals: Tetragon, Tracee.
@diagram flow
caption: Detection path
nodes:
  - "Process spawns sh|inside Pod|bad"
  - "Falco rule matches|shell in container|warn"
  - "Falcosidekick|routes alert|info"
  - "SIEM or chat|on-call|ok"
@h Install and rule
```bash title="Install with Helm" lab
helm repo add falcosecurity https://falcosecurity.github.io/charts
helm upgrade --install falco falcosecurity/falco -n falco --create-namespace --set driver.kind=modern_ebpf
kubectl logs -n falco -l app.kubernetes.io/name=falco --tail=5
```
```yaml title="Custom Falco rule" nocheck
- rule: Shell in shop namespace
  desc: Interactive shell in a shop Pod
  condition: spawned_process and container and k8s.ns.name = "shop" and proc.name in (sh, bash)
  output: "Shell in %k8s.ns.name/%k8s.pod.name (user=%user.name cmd=%proc.cmdline)"
  priority: WARNING
```
@check
What does Falco add that admission policy does not? || Detection of what processes actually do after start, not only the Pod configuration at creation.
@end

@concept Supply chain admission
@plain
Admission policies can require that images come from approved registries, are signed, and have attestations such as an SBOM, before they may run.
@problem
A compromised or unknown image runs with whatever rights the Pod has.
@does
- Sign images with cosign in CI (keyless via OIDC or a key). Verify at admission with Kyverno `verifyImages`, Sigstore policy-controller or Ratify.
- Pin by digest. Block `latest`. Restrict registries with ValidatingAdmissionPolicy (CEL) which needs no webhook.
- Scan images for CVEs in CI and continuously in the registry or cluster (Trivy Operator).
- Start in audit mode (`Audit` or `validationFailureAction: Audit`) to see impact.
@diagram flow
caption: From build to cluster
nodes:
  - "CI build|image digest|app"
  - "Sign and attest|cosign|info"
  - "Registry|stores signature|ext"
  - "Admission verifies|Kyverno|cp"
  - "Pod admitted|or denied|ok"
@h Policies
```yaml title="Allow only the company registry (CEL)"
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicy
metadata:
  name: approved-registry
spec:
  failurePolicy: Fail
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: "object.spec.containers.all(c, c.image.startsWith('registry.example.com/'))"
      message: "Images must come from registry.example.com"
---
apiVersion: admissionregistration.k8s.io/v1
kind: ValidatingAdmissionPolicyBinding
metadata:
  name: approved-registry
spec:
  policyName: approved-registry
  validationActions: ["Audit", "Warn"]
  matchResources:
    namespaceSelector:
      matchLabels:
        env: prod
```
@end

@concept Encrypting Secrets at rest
@plain
By default Secrets are only base64 encoded in etcd. Encryption at rest makes the API server encrypt them before writing.
@problem
Anyone with etcd or backup access reads every Secret in clear text.
@does
- An `EncryptionConfiguration` lists resources and providers in order. The first provider encrypts; all are tried for reading.
- Providers: `aescbc`, `secretbox`, `aesgcm` with local keys, and `kms` v2 which wraps data keys using an external KMS (AWS KMS and others). KMS is the recommended choice.
- After enabling, rewrite old data: `kubectl get secrets -A -o json | kubectl replace -f -`.
- EKS: enable envelope encryption with a KMS key at cluster creation or later. Gardener supports encryption of Secrets and other resources through shoot configuration; check the current docs.
- Encryption protects etcd and backups, not users who may read Secrets through the API (use RBAC).
@diagram seq
caption: Write path with KMS
actors: ["API server|encrypt|cp", "KMS plugin|local socket|info", "etcd|stores ciphertext|db"]
steps:
  - "0>1: wrap data key | req"
  - "1>0: encrypted key | resp"
  - "0>2: write ciphertext | tls"
@h Config
```yaml title="EncryptionConfiguration with KMS v2" nocheck
apiVersion: apiserver.config.k8s.io/v1
kind: EncryptionConfiguration
resources:
  - resources: ["secrets"]
    providers:
      - kms:
          apiVersion: v2
          name: aws-kms
          endpoint: unix:///var/run/kmsplugin/socket.sock
          timeout: 3s
      - identity: {}
```
@check
Why keep identity last in the provider list? || It lets the server still read old unencrypted data during migration, but new writes use the first provider.
@end

@concept Audit logging
@plain
Audit logs record who did what to which object and when. The API server writes them according to an audit policy.
@problem
After an incident you must answer who deleted the Deployment or read a Secret. Without audit logs there is no answer.
@does
- Levels per rule: `None`, `Metadata`, `Request`, `RequestResponse`. Use `Metadata` for Secrets to avoid logging their contents.
- Stages include `RequestReceived` (often omitted) and `ResponseComplete`.
- Output to a file with rotation or a webhook backend. On EKS enable the `audit` control plane log type to CloudWatch; Gardener and Kyma operators can configure audit policy through the shoot.
- Ship to a log system and alert on `exec`, `secrets` reads by unusual users, RBAC changes, and anonymous access.
@diagram flow
caption: Audit pipeline
nodes:
  - "kubectl delete|user alice|plain"
  - "API server|policy decides level|cp"
  - "Log backend|file, CloudWatch, webhook|info"
  - "SIEM alert|unexpected delete|warn"
@h Policy
```yaml title="Audit policy" nocheck
apiVersion: audit.k8s.io/v1
kind: Policy
omitStages: ["RequestReceived"]
rules:
  - level: None
    users: ["system:kube-proxy"]
    verbs: ["watch"]
  - level: Metadata
    resources:
      - group: ""
        resources: ["secrets", "configmaps", "tokenreviews"]
  - level: RequestResponse
    resources:
      - group: "rbac.authorization.k8s.io"
  - level: Request
    verbs: ["create", "update", "patch", "delete"]
  - level: Metadata
```
@end
