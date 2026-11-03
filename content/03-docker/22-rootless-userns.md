---
title: Rootless containers and user namespaces
minutes: 50
objectives:
  - Explain how user namespaces map container root to an unprivileged host user
  - Run Docker and Podman rootless and know their limits
  - Use user namespaces for Kubernetes Pods
---
Root inside a container is not meant to be root on the host. User namespaces make that true by remapping user IDs, which limits the damage of an escape.
@concept User namespaces
@plain
A user namespace gives a process its own view of user and group IDs. UID 0 inside can map to an ordinary UID outside.
@problem
Without remapping, container root is host root with fewer capabilities, so any escape bug yields full control.
@does
- A mapping line has three numbers: inside ID, outside ID, length. `0 100000 65536` maps inside 0 to outside 100000, up to 65536 IDs.
- Files owned by inside UID 0 appear as outside UID 100000 on disk.
- Capabilities granted inside the namespace apply only to resources owned by that namespace, not to the host.
- Mappings come from `/etc/subuid` and `/etc/subgid` for rootless tools.
@diagram layers
caption: ID mapping
layers:
  - {label: "Inside the container", nodes: ["UID 0 root|process|app", "UID 1000|app user|app"]}
  - {label: "Mapping", nodes: ["0 to 100000|length 65536|info"]}
  - {label: "On the host", nodes: ["UID 100000|unprivileged|ok", "UID 101000|unprivileged|ok"]}
@h See it
```bash title="Inspect a user namespace" lab
unshare --user --map-root-user sh -c 'id; cat /proc/self/uid_map'
grep "$USER" /etc/subuid /etc/subgid
podman unshare cat /proc/self/uid_map
```
@check
What does the mapping 0 100000 65536 mean? || Inside IDs 0 to 65535 correspond to outside IDs 100000 to 165535.
@end

@concept Rootful versus rootless runtimes
@plain
Rootless means the container engine itself runs as a normal user. Rootful engines have a root daemon but can still run non-root containers.
@problem
A compromise of a root daemon or a socket mounted into a container is a compromise of the host.
@does
- Rootless: daemon and containers belong to your user; storage under `~/.local/share`; no host root needed to install (after one-time setup of subuid).
- Rootful with userns-remap: `dockerd` setting `"userns-remap": "default"` maps container root to a subordinate range.
- Do not confuse with `USER app` in the image: that is non-root inside a container which may still map to host root in rootful mode.
- Best combination: non-root user in the image and a rootless or remapped runtime.
@diagram cmp
caption: Three levels
cards:
  - {h: "Rootful, root in container", kind: bad, items: ["Container root is host UID 0", "Escape gives root"]}
  - {h: "Rootful, USER app", kind: warn, items: ["Process non-root", "Daemon still root"]}
  - {h: "Rootless", kind: ok, items: ["Engine unprivileged", "Container root maps to your user", "Escape gives your user"]}
@h Rootless Docker
```bash title="Install and use rootless Docker (Linux)" lab
dockerd-rootless-setuptool.sh install
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/docker.sock
docker info --format '{{.SecurityOptions}}'
docker run --rm alpine id
```
@end

@concept Limits and workarounds
@plain
Rootless mode cannot do everything root can. Knowing the limits avoids surprises.
@problem
Teams enable rootless and then find ports, networking or volumes behaving differently.
@does
- Ports below 1024 need `sysctl net.ipv4.ip_unprivileged_port_start=80` or a proxy.
- Networking uses slirp4netns or pasta in user space, so throughput is lower and source IPs may be masked. Newer setups use pasta, which is faster; check your version.
- No `--privileged` in the traditional sense; cgroup v2 delegation is needed for resource limits (systemd user sessions).
- Overlay storage requires kernel support for rootless overlayfs (kernel 5.11+) or fuse-overlayfs.
- Bind-mount ownership: files appear owned by a high UID; use `--userns=keep-id` (Podman) to map your user.
@diagram flow
caption: Rootless network path
nodes:
  - "Container|10.0.2.100|app"
  - "slirp4netns or pasta|user-space NAT|warn"
  - "Host network|your user|info"
  - "Internet|ok|ext"
@h Port and ID tips
```bash title="Common fixes" lab
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
podman run --rm --userns=keep-id -v "$PWD":/work:Z -w /work alpine ls -ln
loginctl enable-linger "$USER"   # keep rootless services running after logout
```
@check
Why do bind-mounted files look owned by a strange UID in rootless mode? || The container user maps to a subordinate UID on the host. keep-id or chown mapping aligns it with your user.
@end

@concept Dockerfile practices for rootless and non-root
@plain
Images should run as a fixed non-root user and avoid needing root for startup, so they work in rootless engines and restricted Kubernetes namespaces.
@problem
Images that write to root-owned paths or bind port 80 fail under PodSecurity restricted or rootless runtimes.
@does
- Create a user with a numeric UID (`USER 10001`) so Kubernetes `runAsNonRoot` can verify it.
- Make writable paths owned by that UID or use `emptyDir` mounts; set `HOME`.
- Listen on ports above 1024 and map them with the Service.
- Avoid `sudo`, setuid binaries and capabilities.
- Test with `docker run --user 10001 --read-only --cap-drop ALL`.
@diagram flow
caption: Hardened run test
nodes:
  - "Image with USER 10001|numeric|app"
  - "Run read-only, no caps|test flags|warn"
  - "Writes only to tmp and data|mounts|info"
  - "Passes restricted policy|ok|ok"
@h Test
```bash title="Run like Kubernetes would" lab
docker run --rm --user 10001:10001 --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges -p 8080:8080 registry.example.com/shop/api:1.8.3
```
@end

@concept User namespaces in Kubernetes
@plain
Kubernetes can run Pods in their own user namespace with `hostUsers: false`, so root in a container is unprivileged on the node.
@problem
Many images still need root inside the container (package managers, legacy apps) and Pod Security cannot always forbid that.
@does
- Set `spec.hostUsers: false` on the Pod. The kubelet allocates a non-overlapping ID range per Pod.
- Needs node support: Linux 6.3+ (idmapped mounts for common volume types), containerd 2.0+ or CRI-O with support, runc/crun recent enough. Beta and enabled by default in recent Kubernetes versions; check the current docs and your managed platform's support.
- Allows capabilities such as CAP_NET_ADMIN inside the Pod without them applying to the host.
- Reduces impact of CVEs that rely on container root equals host root.
@diagram flow
caption: Pod with its own user namespace
nodes:
  - "Pod hostUsers false|spec|app"
  - "Kubelet|allocates ID range|cp"
  - "Runtime|creates userns, idmapped mounts|info"
  - "Container root|unprivileged on node|ok"
@h Pod example
```yaml title="Pod in a user namespace"
apiVersion: v1
kind: Pod
metadata:
  name: userns-demo
spec:
  hostUsers: false
  containers:
    - name: sh
      image: busybox:1.36
      command: ["sh", "-c", "id; cat /proc/self/uid_map; sleep 3600"]
```
```bash title="Check it" lab
kubectl apply -f userns.yaml
kubectl logs userns-demo
```
@check
What does hostUsers false change? || The Pod gets its own user namespace, so UID 0 inside maps to a high unprivileged UID on the node.
@end

@concept Verifying isolation in practice
@plain
After enabling rootless or user namespaces, prove it from the host side. Trust the evidence, not the setting.
@problem
A configuration flag that is silently ignored gives a false sense of safety.
@does
- Start a container as root and read its process owner on the host with `ps`. With remapping it is a high UID, not root.
- Check `/proc/PID/uid_map` and `/proc/PID/status` (`CapEff`) for the container process.
- Try a harmless privileged action inside (mounting a filesystem) and confirm it fails.
- Record the result in a runbook and repeat after runtime upgrades.
@diagram flow
caption: Evidence checks
nodes:
  - "Start container as root|sleep 300|app"
  - "ps on host|shows owner UID|info"
  - "uid_map|mapping lines|info"
  - "Try a mount|should fail|ok"
@h Commands
```bash title="Host-side proof" lab
docker run -d --name probe alpine sleep 300
pid=$(docker inspect -f '{{.State.Pid}}' probe)
ps -o user,pid,cmd -p "$pid"
cat /proc/$pid/uid_map
grep CapEff /proc/$pid/status
docker exec probe sh -c 'mount -t tmpfs none /mnt' ; echo "exit=$?"
docker rm -f probe
```
@check
What host-side output proves container root is remapped? || ps shows the sleep process owned by a high, unprivileged UID and uid_map has a non-identity mapping.
@end
