---
title: Docker troubleshooting scenarios 1 to 8
minutes: 60
objectives:
  - Diagnose build, start, networking, storage and permission failures from symptoms
  - Use the right command to confirm each cause
  - Apply a fix and prove it
---
Each scenario states the symptom, how to confirm the cause and the fix. Resist changing several things at once.

@concept Scenario 1, container exits immediately
@plain
`docker run` starts a container and it stops within a second. A container lives only as long as its main process.
@problem
It is unclear whether the app crashed, the command is wrong or the process daemonised.
@does
- Symptom: `Exited (0)` or `Exited (1)` right after start.
- Confirm: `docker ps -a`, `docker logs`, `docker inspect --format '{{.State.ExitCode}} {{.State.Error}}'`, check `ENTRYPOINT` and `CMD`.
- Causes: the process finishes (a script that ends), a daemon forks to background, missing config, wrong user permissions.
- Fix: run the process in the foreground (`nginx -g 'daemon off;'`), fix config, and use `docker run -it --entrypoint sh IMAGE` to explore.
@diagram flow
caption: Exit triage
nodes:
  - "Exited|docker ps -a|bad"
  - "Exit code and logs|inspect, logs|info"
  - "Foreground process?|CMD and ENTRYPOINT|warn"
  - "Fix and rerun|stays up|ok"
@h Commands
```bash title="Find out why" lab
docker ps -a --filter status=exited --format '{{.Names}} {{.Status}}' | head
docker logs --tail 50 myapp
docker inspect myapp --format 'exit={{.State.ExitCode}} oom={{.State.OOMKilled}} err={{.State.Error}}'
docker run -it --rm --entrypoint sh registry.example.com/shop/api:1.8.3
```
@check
What keeps a container running? || Its main process (PID 1). When that process exits, the container stops.
@end

@concept Scenario 2, exit code 137 and OOM
@plain
The container dies with exit code 137. That is 128 plus signal 9 (SIGKILL), often from the out-of-memory killer.
@problem
The app disappears without a stack trace.
@does
- Symptom: `Exited (137)`; `docker inspect` shows `OOMKilled=true` if the memory limit was hit; `dmesg` shows `Out of memory: Killed process`.
- Confirm: `docker stats`, the `--memory` setting, and runtime memory settings (JVM heap, Node `--max-old-space-size`).
- Fix: raise the limit, reduce usage, set the runtime heap relative to the container limit (`-XX:MaxRAMPercentage`), and fix leaks.
- 137 can also be a manual `docker kill` or a stop that timed out; check `OOMKilled`.
@diagram flow
caption: Reading 137
nodes:
  - "Exit 137|SIGKILL|bad"
  - "OOMKilled true?|inspect|info"
  - "Yes|limit or leak|warn"
  - "No|killed by stop timeout or user|plain"
@h Commands
```bash title="Memory checks" lab
docker inspect myapp --format '{{.State.OOMKilled}} {{.HostConfig.Memory}}'
docker stats --no-stream
dmesg -T | grep -i -E 'oom|killed process' | tail
```
@end

@concept Scenario 3, port already allocated or unreachable
@plain
`docker run -p 8080:80` fails with "port is already allocated", or the port is published but nothing answers.
@problem
Two layers use ports: the host and the container, and the app may listen on the wrong interface.
@does
- Symptom A: `Bind for 0.0.0.0:8080 failed: port is already allocated` - another container or process uses it. Confirm with `lsof -i :8080` or `docker ps`.
- Symptom B: connection reset or empty reply - the app listens on `127.0.0.1` inside the container. It must bind `0.0.0.0`.
- Symptom C: published port works locally but not from other machines - host firewall or binding to `127.0.0.1:8080:80`.
- Fix: choose another host port, bind the app to all interfaces, adjust firewall.
@diagram flow
caption: Port path
nodes:
  - "Client|host:8080|plain"
  - "Docker publish|0.0.0.0:8080|info"
  - "Container port 80|app must bind 0.0.0.0|warn"
  - "Response|ok|ok"
@h Commands
```bash title="Port checks" lab
lsof -nP -iTCP:8080 -sTCP:LISTEN
docker port web
docker exec web ss -tlnp
curl -v http://localhost:8080/
```
@check
Why can an app listening on 127.0.0.1 inside a container be unreachable? || Published ports forward to the container's own IP, not its loopback, so the app must listen on 0.0.0.0.
@end

@concept Scenario 4, DNS and name resolution inside containers
@plain
Containers cannot resolve external names, or cannot resolve other containers by name.
@problem
Behaviour differs between the default bridge, user-defined networks, VPNs and corporate resolvers.
@does
- Symptom: `Temporary failure in name resolution`, `could not resolve host`.
- Confirm: `docker exec c cat /etc/resolv.conf`; `nslookup name` inside; test the host resolver; on user-defined networks the embedded DNS is 127.0.0.11.
- Causes: host DNS is `127.0.0.53` (systemd-resolved), VPN changes resolvers, container on the default bridge using names, corporate DNS blocks.
- Fix: set `"dns": ["10.0.0.2"]` in `/etc/docker/daemon.json` or `--dns`, use a user-defined network for name resolution, restart Docker after VPN changes.
@diagram flow
caption: Resolution path
nodes:
  - "App lookup|name|app"
  - "Embedded DNS|127.0.0.11|cp"
  - "Host resolver|daemon dns setting|info"
  - "Upstream DNS|corporate or public|ext"
@h Commands
```bash title="DNS checks" lab
docker exec web cat /etc/resolv.conf
docker run --rm busybox nslookup example.com
docker network inspect bridge --format '{{.Options}}'
docker run --rm --dns 1.1.1.1 busybox nslookup example.com
```
@end

@concept Scenario 5, permission denied on volumes
@plain
The app cannot write to a mounted directory: `permission denied`, even though it works without the mount.
@problem
Numeric user IDs inside the container do not match the file owner on the host or volume.
@does
- Symptom: `EACCES`, `permission denied` on bind mounts or new volumes; SELinux hosts show `Permission denied` despite correct ownership.
- Confirm: `docker exec c id`, `ls -ln` on the mount path from inside, host `ls -ln`.
- Fix: run with `--user $(id -u):$(id -g)`, `chown` the host path to the container UID, in Dockerfile create the directory with the right owner before `VOLUME`; on SELinux add `:z` or `:Z` to the mount; rootless Podman uses `--userns=keep-id`.
- Named volumes copy image ownership on first use; bind mounts never do.
@diagram flow
caption: UID mismatch
nodes:
  - "Container user|UID 10001|app"
  - "Mounted path|owned by UID 1000|warn"
  - "Write denied|EACCES|bad"
  - "Align IDs|chown or --user|ok"
@h Commands
```bash title="Ownership checks" lab
docker exec web id
docker exec web ls -ln /data
ls -ln ./data
docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/data:/data" alpine touch /data/ok
```
@check
Which mount type copies image ownership into a new volume? || Named volumes do on first use when empty. Bind mounts keep the host's ownership.
@end

@concept Scenario 6, disk full and image bloat
@plain
Builds or pulls fail with `no space left on device`, or the Docker data directory grows without bound.
@problem
Old images, stopped containers, build cache and large container logs accumulate.
@does
- Symptom: `no space left on device`, slow builds, `/var/lib/docker` large.
- Confirm: `docker system df -v`, `du -sh /var/lib/docker/*`, `docker ps -s` for container layers, and large JSON logs in `/var/lib/docker/containers/*/*-json.log`.
- Fix: `docker system prune`, `docker builder prune --keep-storage 10GB`, `docker image prune -a --filter until=168h`; set log rotation (`max-size`, `max-file`) in `daemon.json` or use another log driver.
- Careful: `docker volume prune` deletes unused volumes including data.
@diagram flow
caption: Where space goes
nodes:
  - "Images|unused tags|warn"
  - "Build cache|BuildKit|warn"
  - "Container logs|json-file|bad"
  - "Volumes|data|info"
@h Commands
```bash title="Free space safely" lab
docker system df
docker builder prune --keep-storage 10GB -f
docker image prune -a --filter "until=168h" -f
cat /etc/docker/daemon.json
```
```json title="Log rotation in daemon.json"
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
```
:::warn
`docker system prune --volumes` removes unused volumes. Check what is unused before you run it.
:::
@end

@concept Scenario 7, build fails with cache or context problems
@plain
Builds are slow because the context is huge, or they pick up stale layers, or fail with `file not found` for a COPY.
@problem
The build context (the directory sent to the builder) differs from what you expect.
@does
- Symptom: "Sending build context" of hundreds of MB; `COPY failed: file not found in build context`.
- Confirm: size of the context (`du -sh .`), `.dockerignore` content, relative paths (COPY paths are relative to the context, not the Dockerfile) and `-f` usage.
- Fix: add `.dockerignore` (node_modules, .git, build outputs), run the build from the right directory, use `--no-cache` only to diagnose stale layers, and `docker build --progress=plain` to see each step.
- Remember that a base image tag like `latest` may have changed; pin it.
@diagram flow
caption: Context problems
nodes:
  - "Large context|slow upload|warn"
  - "COPY path wrong|outside the context|bad"
  - "Stale cache|old base or step|warn"
  - "Dockerignore, pin, plain progress|ok"
@h Commands
```bash title="Diagnose a build" lab
du -sh . ; cat .dockerignore
docker build --progress=plain -t app:dbg . 2>&1 | head -40
docker build --no-cache --pull -t app:fresh .
docker buildx du | head
```
@check
Relative to what are COPY source paths resolved? || The build context directory, not the location of the Dockerfile.
@end

@concept Scenario 8, cannot pull or push images
@plain
`docker pull` or `docker push` fails with unauthorized, denied, manifest unknown or TLS errors.
@problem
Credentials, repository names, tags, certificates and platform architectures all matter.
@does
- `unauthorized` or `denied`: run `docker login REGISTRY`; check that the credential helper holds a current token (ECR tokens expire after 12 hours); confirm repository permissions.
- `manifest unknown`: tag or name does not exist; list tags. `no matching manifest for linux/arm64`: the image is amd64 only; use `--platform linux/amd64` or build multi-arch.
- `x509: certificate signed by unknown authority`: add the registry CA to the Docker trust store (`/etc/docker/certs.d/REGISTRY/ca.crt`); do not disable verification.
- Rate limits: authenticate or mirror.
@diagram flow
caption: Reading pull errors
nodes:
  - "unauthorized|login or permission|warn"
  - "manifest unknown|tag or platform|warn"
  - "x509 error|CA trust|bad"
  - "toomanyrequests|auth or mirror|info"
@h Commands
```bash title="Registry checks" lab
docker login registry.example.com
docker manifest inspect registry.example.com/shop/api:1.8.3 | head -20
docker pull --platform linux/amd64 registry.example.com/shop/api:1.8.3
aws ecr get-login-password --region eu-central-1 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.eu-central-1.amazonaws.com
```
@end
