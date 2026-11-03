---
title: Image policy, supply chain and runtime security
minutes: 50
objectives:
  - Enforce trusted registries, digests and signatures at admission
  - Use SBOMs and vulnerability scanning in the delivery path
  - Detect runtime threats with eBPF tools and audit logs
---
Securing the cluster starts before the Pod: which image runs, who built it and what it contains. It continues after the Pod starts: what it actually does.

@concept Image provenance and registries
@plain
Pull only from registries you control, reference images by digest, and keep the build chain trustworthy.
@problem
Mutable tags such as `1.0` or `latest` can point to different content tomorrow, and public images can be tampered with or typosquatted.
@does
- Use a private registry (ECR, Harbor, Artifactory) as the only allowed source, with a pull-through cache for public images.
- Reference by digest: `image: ghcr.io/example/api@sha256:...`. Tags are for humans; digests are for production.
- Build from minimal base images (distroless, Chainguard, Alpine) to shrink attack surface.
- `imagePullSecrets` or node IAM (ECR) gives pull access; never embed registry passwords in images.
@diagram flow
caption: Trusted path of an image
nodes:
  - "Source commit|reviewed|info"
  - "CI build|reproducible|app"
  - "Registry|private, immutable tags|ext"
  - "Cluster pull|by digest|ok"
@h Restrict registries
```yaml title="allowed-registries.yaml"
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: allowed-registries
spec:
  validationFailureAction: Enforce
  rules:
    - name: only-internal-registry
      match:
        any:
          - resources:
              kinds: ["Pod"]
      validate:
        message: "Images must come from 111122223333.dkr.ecr.eu-west-1.amazonaws.com."
        pattern:
          spec:
            containers:
              - image: "111122223333.dkr.ecr.eu-west-1.amazonaws.com/*"
```
@end

@concept Signing and verification
@plain
Signing proves who built an image and that it has not changed. Admission verifies the signature before the Pod runs.
@problem
Network access to a registry is not proof the image came from your pipeline.
@does
- **Cosign** (Sigstore) signs images and attestations; keyless mode uses short-lived certificates tied to the CI identity (OIDC) and records in a transparency log (Rekor).
- Sign in CI after build and scan: `cosign sign IMAGE@DIGEST`.
- Verify in the cluster with Kyverno `verifyImages`, Sigstore policy-controller or Ratify (on Azure and others).
- Attestations (SLSA provenance, SBOM, vulnerability scan result) can also be required.
@diagram seq
caption: Keyless sign and verify
actors: ["CI job|GitHub Actions|app", "Fulcio and Rekor|Sigstore|ext", "Registry|OCI|ext", "Admission|Kyverno|cp"]
steps:
  - "0>1: OIDC token, request cert | tls"
  - "1>0: short-lived cert, log entry | resp"
  - "0>2: push signature | req"
  - "3>2: fetch signature | req"
  - "3>1: verify identity and log | tls"
@h Verify signatures
```yaml title="verify-images.yaml"
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-signed-images
spec:
  validationFailureAction: Enforce
  webhookTimeoutSeconds: 30
  rules:
    - name: cosign-keyless
      match:
        any:
          - resources:
              kinds: ["Pod"]
      verifyImages:
        - imageReferences: ["ghcr.io/example/*"]
          mutateDigest: true
          attestors:
            - entries:
                - keyless:
                    issuer: https://token.actions.githubusercontent.com
                    subject: https://github.com/example/*
                    rekor:
                      url: https://rekor.sigstore.dev
```
@check
What does `mutateDigest: true` give you? || Admission rewrites the tag to the verified digest, so the Pod runs exactly what was verified.
@end

@concept SBOMs and vulnerability scanning
@plain
An SBOM lists every package in an image. Scanners compare that list against vulnerability databases.
@problem
You cannot patch what you cannot see, and new CVEs appear after an image has shipped.
@does
- Generate SBOMs with Syft or BuildKit attestations; scan with Trivy, Grype or registry-native scanning (ECR Inspector).
- Scan in CI (fail on critical, fixable findings) and continuously in the registry or cluster (Trivy Operator creates `VulnerabilityReport` objects).
- Prioritise reachable and fixable vulnerabilities; use VEX statements to record not-affected decisions.
- Rebuild base images on a schedule so patches flow without code changes.
@diagram flow
caption: Scanning points
nodes:
  - "Build|SBOM created|app"
  - "CI scan|gate on severity|warn"
  - "Registry scan|new CVEs later|info"
  - "Cluster scan|what is running|info"
@h Scan and generate
```bash title="Trivy and Syft" lab
trivy image --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 ghcr.io/example/api:1.4.2
syft ghcr.io/example/api:1.4.2 -o spdx-json > sbom.spdx.json
cosign attest --predicate sbom.spdx.json --type spdxjson ghcr.io/example/api@sha256:0123
trivy k8s --report summary --namespace shop
kubectl get vulnerabilityreports -n shop
```
@end

@concept Runtime security
@plain
Runtime tools watch what containers actually do and alert on unexpected behaviour: shells in containers, unexpected network calls, writes to sensitive files.
@problem
Admission controls cannot stop an attack that exploits a running, correctly signed application.
@does
- **Falco** (eBPF) applies rules to syscalls: "shell spawned in container", "read of /etc/shadow", "outbound connection to unexpected IP". Alerts go to SIEM or chat.
- **Tetragon** and **Tracee** (eBPF) add process lineage and can enforce (kill) on policy.
- **Cilium Hubble** shows network flows; GuardDuty EKS Runtime Monitoring provides a managed agent on AWS.
- Combine with read-only root filesystem and dropped capabilities so fewer attacks succeed at all.
@diagram flow
caption: From syscall to alert
nodes:
  - "Container process|syscall|app"
  - "eBPF probe|kernel events|cp"
  - "Rules engine|Falco, Tetragon|warn"
  - "Alert or block|SIEM, chat, kill|bad"
@h Custom Falco rule
```yaml title="falco-rule.yaml"
- rule: Shell in app container
  desc: A shell started inside a production container
  condition: >
    evt.type in (execve, execveat) and evt.dir=<
    and container.id != host
    and proc.name in (bash, sh, zsh)
    and k8s.ns.name = "shop"
  output: >
    Shell in container (user=%user.name pod=%k8s.pod.name ns=%k8s.ns.name
    cmd=%proc.cmdline image=%container.image.repository)
  priority: WARNING
  tags: [container, shell]
```
@end

@concept Audit logs and detection
@plain
Kubernetes audit logs record every API request: who, what, when and the result. They are the main record for investigations.
@problem
After an incident you must answer who read the Secret or changed the Deployment.
@does
- Audit policy sets level per resource: `None`, `Metadata`, `Request`, `RequestResponse`. Log Secrets at `Metadata` so values are not stored in logs.
- Managed services ship audit logs to their own sinks (EKS to CloudWatch Logs, Gardener to the shoot's logging stack). Enable it and set retention.
- Useful detections: `exec` into Pods, creation of privileged Pods or ClusterRoleBindings, access by anonymous or unusual users, Secret reads by non-system identities.
- Forward to a SIEM and alert on high-risk verbs.
@diagram layers
caption: Detection stack
layers:
  - {label: "Sources", nodes: ["API audit log|who did what|info", "Falco events|process level|info", "Flow logs|network|info"]}
  - {label: "Pipeline", nodes: ["Log shipper|Fluent Bit|app"]}
  - {label: "Response", nodes: ["SIEM and alerts|triage|ok"]}
@h Enable and query on EKS
```bash title="EKS audit logging" nocheck
aws eks update-cluster-config --name prod \
  --logging '{"clusterLogging":[{"types":["api","audit","authenticator"],"enabled":true}]}'
aws logs start-query --log-group-name /aws/eks/prod/cluster \
  --start-time $(date -d '-1 hour' +%s) --end-time $(date +%s) \
  --query-string 'fields @timestamp, user.username, verb, objectRef.resource | filter verb = "create" and objectRef.subresource = "exec"'
```
@end

@concept A layered security checklist
@plain
No single control is enough. Combine identity, admission, network and runtime layers and verify them regularly.
@problem
Teams add one tool, feel safe and leave gaps elsewhere.
@does
- Identity: OIDC for humans, least privilege RBAC, no long-lived keys, cloud identity for Pods.
- Config: Pod Security `restricted`, secrets from a store, encryption at rest.
- Network: default deny, mesh mTLS, egress control.
- Supply chain: private registry, signed digests, scans, SBOMs.
- Runtime and ops: eBPF detection, audit logs, patched nodes through regular node rotation, benchmark scans (CIS with kube-bench, Kubescape).
@diagram layers
caption: Defence in depth
layers:
  - {label: "Build", nodes: ["Signed minimal images|supply chain|ok"]}
  - {label: "Admit", nodes: ["RBAC and policy|who and what|ok", "Pod Security|restricted|ok"]}
  - {label: "Run", nodes: ["NetworkPolicy and mTLS|segmentation|ok", "Runtime detection|Falco|ok"]}
  - {label: "Operate", nodes: ["Audit and patching|continuous|ok"]}
@h Benchmark scans
```bash title="Posture checks" lab
kubescape scan framework nsa --namespace shop
kube-bench run --targets node
trivy k8s --compliance k8s-pss-restricted-0.1 --report summary cluster
```
@end
