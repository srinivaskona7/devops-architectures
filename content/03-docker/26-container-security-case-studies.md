---
title: Container security case studies and escape techniques
minutes: 65
objectives:
  - Explain the main container escape paths and the misconfigurations behind them
  - Map each technique to concrete mitigations
  - Review a runtime configuration with an attacker's checklist
---
Containers are isolated by the shared kernel plus configuration, not by a hypervisor. Almost every real escape starts with a dangerous setting or a kernel or runtime bug. This page describes the techniques at a conceptual level so you can recognise and prevent them. Test only in your own lab.

@concept The threat model
@plain
A container shares the host kernel. Isolation comes from namespaces, cgroups, capabilities, seccomp, LSMs and the runtime. An attacker in a container tries to cross one of these boundaries.
@problem
Teams assume "it is in a container, so it is safe" and then grant extra rights for convenience.
@does
- Attack surfaces: kernel (syscalls), runtime (runc, containerd), configuration (privileged, mounts, capabilities), orchestration (API, service account tokens), and the supply chain.
- Layers of defence: non-root user, dropped capabilities, seccomp, AppArmor or SELinux, read-only filesystem, user namespaces, sandboxed runtimes (gVisor, Kata) for hostile code.
- Assume breach: limit what a compromised container can reach.
@diagram layers
caption: Boundaries an attacker must cross
layers:
  - {label: "Inside container", nodes: ["Application bug|initial foothold|bad"]}
  - {label: "Container boundary", nodes: ["Namespaces|views|info", "Capabilities and seccomp|syscalls|info", "AppArmor or SELinux|files|info", "User namespace|ID mapping|info"]}
  - {label: "Host", nodes: ["Kernel|shared|cp", "Runtime and daemon|root|cp", "Other containers and cloud creds|targets|ext"]}
@check
Why is a container weaker than a VM as a security boundary? || It shares the host kernel, so a kernel or runtime flaw can cross the boundary.
@end

@concept Case 1, privileged containers
@plain
`--privileged` (or `privileged: true` in Kubernetes) removes most isolation: all capabilities, all devices, no seccomp, no AppArmor.
@problem
It is used to make something work quickly (Docker-in-Docker, mounting disks), and then stays.
@does
- Technique (conceptual): with all devices visible, the container can mount the host's disk device or write to the host's kernel interfaces, giving access to the host filesystem.
- Mitigation: never allow privileged in application namespaces. Enforce Pod Security `baseline` or `restricted`. Use admission policy to deny `privileged`, `hostPID`, `hostNetwork`.
- Alternatives: add only the one capability needed, use rootless BuildKit or Kaniko instead of Docker-in-Docker, use device plugins for devices.
@diagram flow
caption: Why privileged is dangerous
nodes:
  - "privileged true|all caps, all devices|bad"
  - "Host devices visible|disks and kernel interfaces|bad"
  - "Host filesystem reachable|escape|bad"
  - "Policy denies it|baseline or restricted|ok"
@h Detect in a cluster
```bash title="Find privileged Pods" lab
kubectl get pods -A -o json | python3 -c '
import sys, json
for p in json.load(sys.stdin)["items"]:
    for c in p["spec"]["containers"]:
        sc = c.get("securityContext") or {}
        if sc.get("privileged"):
            print(p["metadata"]["namespace"], p["metadata"]["name"], c["name"])
'
```
@end

@concept Case 2, the Docker socket
@plain
Mounting `/var/run/docker.sock` into a container hands that container control of the Docker daemon, which runs as root on the host.
@problem
CI jobs and tools (monitoring, build agents) mount the socket to run or inspect containers.
@does
- Technique (conceptual): whoever can talk to the daemon can start a new container with the host filesystem mounted, which is equivalent to root on the host.
- Same risk applies to the containerd socket and Podman's socket.
- Mitigation: do not mount the socket; use rootless builders, a socket proxy that allows read-only endpoints, or remote build services. In Kubernetes block `hostPath` of `/var/run` with policy.
- If unavoidable, isolate such workloads on dedicated, disposable nodes.
@diagram flow
caption: Socket equals root
nodes:
  - "Container with docker.sock|compromised|bad"
  - "Docker daemon|runs as root|cp"
  - "New container|host / mounted|bad"
  - "Alternative|rootless build, socket proxy|ok"
@h Find users of the socket
```bash title="Search for socket mounts" lab
docker ps -q | xargs -I{} docker inspect {} --format '{{.Name}} {{range .Mounts}}{{.Source}} {{end}}' | grep -i docker.sock
kubectl get pods -A -o json | grep -c '/var/run/docker.sock'
```
@check
Why is access to the Docker socket equal to root on the host? || The daemon runs as root and can create containers that mount the host filesystem.
@end

@concept Case 3, dangerous capabilities and host mounts
@plain
Individual capabilities such as SYS_ADMIN, SYS_PTRACE, NET_ADMIN, DAC_READ_SEARCH and SYS_MODULE enable specific attacks. Mounts of host paths expose host data.
@problem
Granting one capability "just for the app" can be nearly as bad as privileged.
@does
- `SYS_ADMIN` allows mounting and many namespace operations; combined with weak seccomp it has led to escapes.
- `SYS_PTRACE` with `hostPID` allows inspecting host processes; `SYS_MODULE` allows loading kernel modules; `DAC_READ_SEARCH` was used in the "shocker" file-handle technique to read host files.
- Host mounts: `/`, `/etc`, `/proc`, `/sys`, `/var/lib/kubelet`, `/var/lib/docker` expose secrets and runtime state; writable `hostPath` allows persistence.
- Mitigation: `cap_drop: ALL` and add back only what is proven needed; deny `hostPath` except for approved paths and read-only; keep default seccomp.
@diagram cmp
caption: Capability risk
cards:
  - {h: "SYS_ADMIN", kind: bad, items: ["Mount and namespace ops", "Treat as near privileged"]}
  - {h: "SYS_PTRACE with hostPID", kind: bad, items: ["Inspect host processes"]}
  - {h: "NET_RAW", kind: warn, items: ["Packet crafting", "Default in Docker, dropped in restricted"]}
  - {h: "NET_BIND_SERVICE", kind: ok, items: ["Low ports", "Often the only one needed"]}
@h Safe runtime flags
```bash title="Run with minimum rights" lab
docker run --rm --cap-drop ALL --cap-add NET_BIND_SERVICE --security-opt no-new-privileges --read-only --pids-limit 200 --memory 256m nginx:1.27
docker inspect --format '{{.HostConfig.CapAdd}} {{.HostConfig.Privileged}}' $(docker ps -q) | sort | uniq -c
```
@end

@concept Case 4, runc and runtime vulnerabilities
@plain
The runtime that sets up containers (runc, containerd) is code running as root. Bugs there can let a malicious image or container overwrite host files.
@problem
You cannot fix these with configuration alone; they need patching.
@does
- Notable history: CVE-2019-5736 (container could overwrite the host runc binary through `/proc/self/exe`), and CVE-2024-21626 "Leaky Vessels" (a leaked file descriptor allowed access to the host filesystem through a crafted working directory). Several 2025 runc advisories concerned mount handling. Read the current advisories for exact versions.
- Mitigation: patch runc, containerd and the kernel promptly (node image rotation), run images from trusted sources, use user namespaces and sandboxed runtimes for untrusted workloads.
- Track: subscribe to vendor security feeds (Gardener, EKS AMI release notes, Bottlerocket).
@diagram flow
caption: Patch pipeline
nodes:
  - "Advisory published|runc or kernel|warn"
  - "New node image|provider release|info"
  - "Rolling node replacement|drain with PDB|app"
  - "Verify version|runc --version|ok"
@h Check versions
```bash title="Runtime versions on nodes" lab
kubectl get nodes -o custom-columns=NAME:.metadata.name,RUNTIME:.status.nodeInfo.containerRuntimeVersion,KERNEL:.status.nodeInfo.kernelVersion,OS:.status.nodeInfo.osImage
```
:::note
Look up the fixed versions in the official advisory for the CVE, not in this text, since backports differ by distribution.
:::
@check
Why can a configuration policy not stop a runtime vulnerability? || The flaw is in the code that sets up the container, so only patching the runtime or the kernel fixes it.
@end

@concept Case 5, kernel exploits and cgroup escapes
@plain
Because the kernel is shared, a kernel bug reachable from a container can break out of it. Some classic escapes abuse cgroup v1 release agents when the container is privileged.
@problem
A single unpatched kernel affects every container on the node.
@does
- Examples: Dirty COW (2016), Dirty Pipe (CVE-2022-0847), and cgroup v1 `release_agent` abuse (CVE-2022-0492 required missing checks combined with certain capabilities).
- Mitigation: keep nodes patched, use seccomp default (blocks risky syscalls), AppArmor/SELinux, cgroup v2, user namespaces, and a minimal host OS.
- For hostile code (multi-tenant platforms, CI for untrusted pull requests) use gVisor, Kata Containers or Firecracker microVMs, which put another kernel boundary in place.
@diagram cmp
caption: Isolation options
cards:
  - {h: "runc container", kind: warn, items: ["Shared kernel", "Fast", "Fine for trusted code"]}
  - {h: "gVisor", kind: info, items: ["User-space kernel", "Fewer host syscalls", "Some compatibility gaps"]}
  - {h: "Kata or microVM", kind: ok, items: ["Own kernel per Pod", "Strongest", "Overhead and nested virt needs"]}
@h RuntimeClass in Kubernetes
```yaml title="Use a sandboxed runtime for untrusted workloads"
apiVersion: node.k8s.io/v1
kind: RuntimeClass
metadata:
  name: gvisor
handler: runsc
---
apiVersion: v1
kind: Pod
metadata:
  name: untrusted-build
spec:
  runtimeClassName: gvisor
  containers:
    - name: build
      image: busybox:1.36
      command: ["sleep", "3600"]
```
@end

@concept Case 6, Kubernetes specific paths
@plain
In clusters, attackers also pivot with service account tokens, the kubelet API, the cloud metadata service and permissive RBAC.
@problem
A web shell in one Pod becomes cluster-wide control when tokens or roles are generous.
@does
- Tokens: Pods get a ServiceAccount token by default. If its role is broad, the attacker uses the API. Mitigate with `automountServiceAccountToken: false`, least-privilege RBAC, bound short-lived tokens.
- Metadata: Pods can reach `169.254.169.254` and steal node role credentials. Mitigate with IMDSv2 hop limit 1, NetworkPolicy egress blocks, IRSA or Pod Identity.
- Kubelet: anonymous or read-only ports expose Pod data. Mitigate with webhook authz and port 0.
- Create-Pod right: anyone who can create Pods can mount Secrets or hostPath unless admission blocks it. Treat `create pods` as a powerful permission.
- Misconfigured `exec` / `ephemeralcontainers` rights provide shells in other Pods.
@diagram flow
caption: Pivot path
nodes:
  - "Web shell in Pod|foothold|bad"
  - "Token or metadata|credentials|warn"
  - "API or cloud access|lateral move|bad"
  - "Least privilege and egress policy|stop|ok"
@h Quick audit
```bash title="Who can create pods or read secrets" lab
kubectl auth can-i create pods --as=system:serviceaccount:shop:default -n shop
kubectl auth can-i get secrets --as=system:serviceaccount:shop:default -n shop
kubectl get pods -A -o json | python3 -c 'import sys,json; [print(p["metadata"]["namespace"], p["metadata"]["name"]) for p in json.load(sys.stdin)["items"] if p["spec"].get("automountServiceAccountToken") is not False][:0]'
```
@check
Which Kubernetes permission is almost equivalent to node access if admission is lax? || create on pods, because a Pod can mount host paths, Secrets and use privileged settings unless policy blocks them.
@end

@concept Case 7, image and supply chain compromises
@plain
Malicious or vulnerable images, typosquatted names, leaked build secrets and compromised base images are a major real-world route into containers.
@problem
The attacker is already inside the trusted pipeline, so runtime isolation alone does not help.
@does
- Incidents: cryptominers in public images, secrets baked into layers, compromised CI tokens, and poisoned dependencies.
- Mitigation: pin by digest, use trusted registries and mirrors, scan in CI and continuously, generate SBOMs, sign and verify images, build with isolated credentials (BuildKit secrets), minimal base images.
- Detect: Falco or Tetragon for unexpected processes, outbound connections to mining pools, and writes to unusual paths.
- Rotate any secret that has ever been in an image layer.
@diagram flow
caption: Controls along the pipeline
nodes:
  - "Source and deps|lockfiles, review|info"
  - "Build|isolated, secrets mounted|app"
  - "Sign and scan|cosign, SBOM, trivy|cp"
  - "Admit and watch|policy, Falco|ok"
@h Find secrets in layers
```bash title="Look for leaked secrets" lab
docker history --no-trunc IMAGE | grep -i -E 'token|password|secret|key'
trivy image --scanners secret IMAGE
```
@end

@concept Reviewing a configuration like an attacker
@plain
A short checklist turns these cases into a repeatable review for any workload.
@problem
Reviews are ad hoc, so dangerous settings reappear.
@does
- Is it privileged? Does it add capabilities beyond the defaults? Is `allowPrivilegeEscalation` false?
- Does it run as non-root with a numeric UID, read-only root filesystem, seccomp RuntimeDefault?
- Any `hostPath`, `hostPID`, `hostNetwork`, `hostIPC`? Any runtime socket mounts?
- Is the ServiceAccount token needed, and is its role minimal? Is egress restricted?
- Is the image pinned, scanned and signed? Is the node kernel and runtime patched?
- Are untrusted workloads on a sandboxed runtime or separate nodes?
@diagram layers
caption: Checklist areas
layers:
  - {label: "Process", nodes: ["Non-root|numeric UID|ok", "No privilege escalation|flag false|ok"]}
  - {label: "Kernel interface", nodes: ["Caps dropped|ALL|ok", "seccomp and LSM|on|ok"]}
  - {label: "Host exposure", nodes: ["No host namespaces|none|ok", "No sockets or hostPath|none|ok"]}
  - {label: "Identity and supply", nodes: ["Token minimal|RBAC|ok", "Image pinned and signed|digest|ok"]}
@h Automated check
```bash title="Scan manifests and clusters" lab
kubectl get deploy -A -o yaml | kubesec scan /dev/stdin 2>/dev/null | head -20
trivy config k8s/
docker run --rm --net host --pid host --userns host --cap-add audit_control -v /var/lib:/var/lib:ro -v /etc:/etc:ro --label docker_bench_security docker/docker-bench-security 2>/dev/null | head -20
```
:::note
Tool names and options change. Check each tool's current documentation.
:::
@check
Name three host-exposure settings to deny by policy. || privileged, host namespaces (hostPID, hostNetwork, hostIPC), and hostPath or runtime socket mounts.
@end
