---
title: Pod security
minutes: 45
objectives:
  - Write a hardened securityContext
  - Apply Pod Security Standards with namespace labels
  - Explain capabilities, seccomp, AppArmor and user namespaces
---
A container is a Linux process with isolation, not a virtual machine. Pod security reduces what a compromised process can do to the node and to its neighbours.

@concept securityContext
@plain
`securityContext` sets user, group, filesystem, capability and privilege options on a Pod or container.
@problem
By default containers often run as root with a writable filesystem and many kernel capabilities, which makes breakouts easier.
@does
- `runAsNonRoot: true` with `runAsUser` refuses to start a container whose user is root.
- `allowPrivilegeEscalation: false` blocks setuid binaries gaining privileges.
- `readOnlyRootFilesystem: true` forces writes into explicit volumes.
- `capabilities: drop: ["ALL"]` then add back only what is needed (for example `NET_BIND_SERVICE`).
- `seccompProfile: RuntimeDefault` filters dangerous syscalls.
- `fsGroup` sets group ownership of mounted volumes.
@diagram layers
caption: Layers of container restriction
layers:
  - {label: "Identity", nodes: ["runAsNonRoot|no uid 0|ok", "runAsUser|fixed uid|ok"]}
  - {label: "Privileges", nodes: ["drop ALL capabilities|least|ok", "no privilege escalation|setuid blocked|ok"]}
  - {label: "Filesystem and syscalls", nodes: ["readOnlyRootFilesystem|immutable|ok", "seccomp RuntimeDefault|syscall filter|ok"]}
@h Hardened Deployment
```yaml title="hardened.yaml"
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  replicas: 2
  selector:
    matchLabels:
      app: api
  template:
    metadata:
      labels:
        app: api
    spec:
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: api
          image: ghcr.io/example/api:1.4.2
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
@end

@concept Pod Security Standards
@plain
Three built-in policy levels define what a Pod may do: **privileged** (anything), **baseline** (blocks known escalations) and **restricted** (current hardening best practice).
@problem
PodSecurityPolicy was removed in 1.25. You still need a simple, built-in guard rail.
@does
- **Baseline** forbids host namespaces, privileged containers, most host paths and dangerous capabilities.
- **Restricted** adds non-root, no privilege escalation, drop ALL capabilities (only `NET_BIND_SERVICE` may be added), seccomp `RuntimeDefault` or `Localhost`, and limited volume types.
- Applied per namespace by the built-in **Pod Security Admission** controller.
- Standards check Pods, and Pod templates in workload objects are checked for warnings.
@diagram cmp
caption: The three levels
cards:
  - {h: "privileged", kind: bad, items: ["No restrictions", "System components only"]}
  - {h: "baseline", kind: warn, items: ["Blocks known escalations", "Easy to adopt"]}
  - {h: "restricted", kind: ok, items: ["Non-root, drop ALL, seccomp", "Target for apps"]}
@h Enforce per namespace
```yaml title="psa-namespace.yaml"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/enforce-version: latest
    pod-security.kubernetes.io/warn: restricted
    pod-security.kubernetes.io/audit: restricted
```
@check
What are the three Pod Security Admission modes? || `enforce` rejects violations, `audit` records them in the audit log, `warn` shows a warning to the user.
@end

@concept Rolling out Pod Security safely
@plain
Start with warn and audit, fix what they report, then enforce.
@problem
Turning on `enforce` for existing namespaces breaks workloads that run as root.
@does
- Label the namespace with `warn` and `audit` first and run `kubectl label --dry-run=server` to see what would fail.
- Use `AdmissionConfiguration` for cluster defaults and exemptions (for example system namespaces); on managed clusters check what the provider already sets.
- Existing running Pods are not killed by enforce; new ones are rejected.
- For exceptions use a dedicated namespace with a weaker level, not a weaker cluster default.
@diagram flow
caption: Gradual adoption
numbered: true
nodes:
  - "Dry run label|see violations|info"
  - "warn and audit|collect findings|warn"
  - "Fix workloads|securityContext|app"
  - "enforce|block new violations|ok"
@h Dry run
```bash title="What would break" lab
kubectl label --dry-run=server --overwrite ns shop pod-security.kubernetes.io/enforce=restricted
kubectl label ns shop pod-security.kubernetes.io/warn=restricted pod-security.kubernetes.io/audit=restricted --overwrite
kubectl get ns --show-labels | grep pod-security
```
@end

@concept Capabilities, seccomp and AppArmor
@plain
Linux splits root power into capabilities, filters syscalls with seccomp and confines files and network with AppArmor or SELinux.
@problem
Even a non-root process can be dangerous with extra capabilities, and a root process in a container is only as safe as the kernel filters around it.
@does
- Capabilities like `NET_ADMIN`, `SYS_ADMIN`, `SYS_PTRACE` allow network, mount and process control; avoid them.
- `RuntimeDefault` seccomp blocks around 40+ rarely-needed syscalls with little compatibility cost; custom `Localhost` profiles can be generated from observed behaviour (Security Profiles Operator).
- AppArmor is set via `securityContext.appArmorProfile` (stable in 1.31); SELinux via `seLinuxOptions` on supporting distributions.
- `privileged: true` removes almost all isolation; only node-level agents should use it.
@diagram flow
caption: Defence in depth for a syscall
nodes:
  - "Process|in container|app"
  - "Capabilities|may it do this|warn"
  - "seccomp|is syscall allowed|warn"
  - "AppArmor or SELinux|is path allowed|warn"
  - "Kernel|executes|ok"
@h AppArmor and seccomp
```yaml title="apparmor-seccomp.yaml"
apiVersion: v1
kind: Pod
metadata:
  name: confined
spec:
  securityContext:
    seccompProfile:
      type: RuntimeDefault
    appArmorProfile:
      type: RuntimeDefault
  containers:
    - name: app
      image: busybox:1.36
      command: ["sleep", "3600"]
      securityContext:
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
```
@end

@concept Isolation beyond defaults
@plain
When tenants are untrusted, add stronger boundaries: sandboxed runtimes, user namespaces or dedicated nodes.
@problem
Containers share the host kernel; a kernel bug can cross the boundary.
@does
- **RuntimeClass** selects a sandboxing runtime such as gVisor or Kata Containers (microVM) for specific Pods.
- **User namespaces** (`hostUsers: false`, stable in 1.33) map container root to an unprivileged host UID, shrinking the impact of a breakout.
- Dedicated node pools with taints for sensitive workloads; no shared nodes between trust levels.
- Avoid `hostNetwork`, `hostPID`, `hostIPC` and `hostPath`; do not mount the container runtime socket.
@diagram cmp
caption: Isolation options
cards:
  - {h: "Default runc", kind: warn, items: ["Shared kernel", "Fastest"]}
  - {h: "User namespaces", kind: info, items: ["Root mapped to unprivileged", "Same kernel"]}
  - {h: "gVisor or Kata", kind: ok, items: ["Extra kernel or VM layer", "Some overhead"]}
@h Sandboxed Pod
```yaml title="runtimeclass.yaml"
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
---
apiVersion: v1
kind: Pod
metadata:
  name: untrusted
spec:
  runtimeClassName: gvisor
  hostUsers: false
  containers:
    - name: app
      image: busybox:1.36
      command: ["sleep", "3600"]
```
@end
