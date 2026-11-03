---
title: Image hardening
minutes: 45
objectives:
  - Choose a minimal base such as slim, Alpine or distroless and know the trade offs
  - Scan images with Trivy and act on the results in CI
  - Drop capabilities, use a read only root filesystem and set seccomp for a hardened runtime
---
Every package in an image is something that can have a CVE, and every privilege granted to a container is something an attacker can use. Hardening is mostly about removing things.

@concept Minimal base images
@plain
The smaller the image, the fewer binaries an attacker can use and the fewer CVEs a scanner finds. Distroless images contain your app and runtime libraries but no shell or package manager.
@problem
A full Debian image ships hundreds of packages the app never uses, such as `curl`, `bash` and `apt`, which are exactly the tools used after a compromise.
@does
- **slim**: Debian without docs and extras; good default with glibc compatibility.
- **alpine**: tiny, uses musl and busybox; watch for native module and DNS quirks.
- **distroless** (`gcr.io/distroless/*`): `static`, `base`, `python3`, `nodejs22`; `:nonroot` variants run as UID 65532; `:debug` adds busybox.
- **Chainguard** and **Wolfi** images: minimal with frequent patches.
- **scratch**: empty; suits static Go binaries.
@diagram cmp
caption: Base image trade offs
cards:
  - {h: "debian full", kind: bad, items: ["Most tools and CVEs", "Easy to debug", "Largest"]}
  - {h: "slim or alpine", kind: warn, items: ["Smaller attack surface", "Shell present", "Check musl issues"]}
  - {h: "distroless", kind: ok, items: ["No shell, no apt", "Runs nonroot by default", "Debug with ephemeral containers"]}
  - {h: "scratch", kind: info, items: ["Only your static binary", "No CA certificates unless copied", "Go and Rust"]}
@h Distroless Node runtime
```dockerfile title="Dockerfile (Node on distroless)" nocheck
# syntax=docker/dockerfile:1
FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
RUN npm run build && npm prune --omit=dev

FROM gcr.io/distroless/nodejs22-debian12:nonroot
WORKDIR /app
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
EXPOSE 3000
CMD ["dist/server.js"]
```
:::note
The distroless Node image sets `node` as the entrypoint, so `CMD` is only the script path. There is no shell, so `sh -c` and shell form do not work in the final stage.
:::
@check
How do you debug a distroless container with no shell? || Use kubectl debug with an ephemeral container, or run the :debug image variant locally.
@end

@concept Vulnerability scanning with Trivy
@plain
A scanner compares the packages in an image against vulnerability databases (CVEs) and reports severity, the installed version and the fixed version.
@problem
Unscanned images quietly accumulate known vulnerabilities. Scanning only at release misses CVEs published later.
@does
- `trivy image IMAGE` scans OS packages and language dependencies (pip, npm, Go modules).
- `--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1` makes CI fail only on actionable findings.
- `trivy config .` checks Dockerfiles, Kubernetes YAML and Terraform; `trivy fs .` scans source dependencies.
- Rescan stored images on a schedule; the database changes daily. ECR can also scan on push (basic or Inspector enhanced scanning).
- Document accepted risks in a `.trivyignore` with an expiry note.
@diagram flow
caption: Scanning at three points
nodes:
  - "Pull request|trivy fs and config|info"
  - "Build|trivy image gate|warn"
  - "Registry and cluster|scheduled rescan|cp"
@h Run it
```bash title="Scan and gate" lab
trivy image --severity HIGH,CRITICAL --ignore-unfixed python:3.12-slim
trivy image --severity CRITICAL --exit-code 1 --ignore-unfixed shop-api:dev || echo "gate failed"
trivy config --severity HIGH,CRITICAL .
trivy image --format sarif -o trivy.sarif shop-api:dev        # upload to GitHub code scanning
```
```yaml title="GitHub Actions step"
- name: Scan image
  uses: aquasecurity/trivy-action@0.28.0
  with:
    image-ref: ghcr.io/${{ github.repository }}:sha-${{ github.sha }}
    severity: CRITICAL,HIGH
    ignore-unfixed: true
    exit-code: "1"
```
@end

@concept Reading scan results
@plain
Not every finding needs a fix today. Triage by whether the vulnerable code is reachable, a fix exists and the severity rating.
@problem
Hundreds of low value alerts cause teams to ignore the scanner and miss the one that matters.
@does
- Prefer upgrading the base image: many OS CVEs vanish with a rebuilt `python:3.12-slim`.
- `--ignore-unfixed` hides issues with no available fix; track them separately.
- Check CVSS and EPSS or the CISA KEV list to judge exploitation likelihood.
- VEX statements record "not affected" decisions in a machine readable way.
- Fix in order: critical with fix, high with fix, then batch the rest on base image refresh.
@diagram flow
caption: Triage order
numbered: true
nodes:
  - "Finding|CVE in package|warn"
  - "Fix available|upgrade or rebuild|info"
  - "Reachable and exploited|KEV or EPSS high|bad"
  - "Patch or document|VEX or ignore with expiry|ok"
@h Useful queries
```bash title="Narrow the noise" lab
trivy image -f json shop-api:dev | jq -r '.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL") | [.VulnerabilityID,.PkgName,.InstalledVersion,.FixedVersion] | @tsv'
trivy image --scanners vuln,secret shop-api:dev      # also looks for embedded secrets
```
@end

@concept Capabilities, seccomp and no-new-privileges
@plain
Linux capabilities split root powers into about 40 pieces. A web app needs none of them, so drop them all and add back only what is proven necessary.
@problem
The Docker default set (14 capabilities, including `NET_RAW` and `SETUID`) is larger than most apps need, and each one widens what an exploit can do.
@does
- `--cap-drop ALL` then `--cap-add NET_BIND_SERVICE` only if binding ports below 1024.
- `--security-opt no-new-privileges` blocks gaining rights via setuid binaries.
- The default seccomp profile blocks dangerous syscalls; Kubernetes `seccompProfile: RuntimeDefault` applies the runtime default.
- Never use `--privileged` or add `SYS_ADMIN` casually.
@diagram layers
caption: Container privileges, from most to least
layers:
  - {label: "Danger", nodes: ["--privileged|all capabilities, all devices|bad", "SYS_ADMIN|near root on host|bad"]}
  - {label: "Default", nodes: ["14 default capabilities|Docker standard|warn"]}
  - {label: "Hardened", nodes: ["cap_drop ALL|no capabilities|ok", "no-new-privileges|no escalation|ok", "seccomp RuntimeDefault|syscall filter|ok"]}
@h Equivalent settings
```bash title="docker run" lab
docker run --rm --cap-drop ALL --security-opt no-new-privileges --read-only --tmpfs /tmp \
  --user 10001:10001 --pids-limit 100 --memory 256m shop-api:dev
```
```yaml title="Kubernetes securityContext"
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
    - name: api
      image: ghcr.io/acme/shop-api:sha-3f9c2ab
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

@concept Read-only root filesystem and secrets handling
@plain
If the root filesystem is read-only, an attacker cannot drop tools or modify binaries. Writable paths are explicit and small.
@problem
Malware and exploit chains usually write to disk first. Secrets baked into images or passed in environment variables end up in registries and process dumps.
@does
- `--read-only` plus `--tmpfs /tmp` and volumes for state. Test the app: it will reveal hidden writes (caches, pid files, `.pyc`).
- Set `PYTHONDONTWRITEBYTECODE=1`, point Node caches to `/tmp`.
- Never put secrets in `ENV`, `ARG`, or `COPY`. Use runtime secrets, mounted files or an external manager (AWS Secrets Manager with External Secrets Operator).
- Scan for leaked secrets (`trivy --scanners secret`, `gitleaks`) before pushing.
@diagram cmp
caption: Where to keep a secret
cards:
  - {h: "In the image", kind: bad, items: ["Extractable by anyone with pull access", "Stays in history"]}
  - {h: "In an env variable", kind: warn, items: ["Shown by inspect", "Inherited by children"]}
  - {h: "Mounted file or secret manager", kind: ok, items: ["Not in the image", "Rotatable", "Limited to the pod"]}
@h Test a read-only run
```bash title="Find hidden writes" lab
docker run -d --name ro --read-only -p 127.0.0.1:8000:8000 shop-api:dev
sleep 3; docker logs ro 2>&1 | grep -i 'read-only file system' || echo "no write errors"
docker diff ro               # lists any files the container changed (should be empty)
docker rm -f ro
```
@end

@concept Hardening checklist and CIS benchmark
@plain
A checklist turns the scattered hardening ideas into an auditable baseline. The CIS Docker Benchmark and the Kubernetes Pod Security Standards describe the same controls.
@problem
Teams harden one image well and forget the rest. A shared baseline makes every service meet the same minimum.
@does
- Image: pinned minimal base, non-root user, no secrets, healthcheck, scanned.
- Runtime: read-only root, `cap_drop ALL`, `no-new-privileges`, seccomp default, limits on memory, CPU and PIDs.
- Host: no docker.sock mounts, no `--privileged`, no host namespaces (`--pid=host`, `--network=host`) without a reason.
- Tools: `docker-bench-security` audits a Docker host; `kube-bench` and Pod Security `restricted` audit a cluster.
@diagram layers
caption: Hardening spans three layers
layers:
  - {label: "Image", nodes: ["Minimal base|fewer packages|ok", "Non-root user|UID 10001|ok", "No secrets|runtime injection|ok"]}
  - {label: "Runtime", nodes: ["Read only root|tmpfs for scratch|ok", "Capabilities dropped|seccomp default|ok", "Limits|memory, CPU, PIDs|ok"]}
  - {label: "Host and cluster", nodes: ["No docker.sock|no privileged|ok", "Pod Security restricted|admission enforced|ok"]}
@h Audit
```bash title="Run the benchmark" lab
docker run --rm --net host --pid host --userns host --cap-add audit_control \
  -v /var/lib:/var/lib:ro -v /var/run/docker.sock:/var/run/docker.sock:ro \
  -v /etc:/etc:ro docker/docker-bench-security
```
@end
