---
title: Debugging containers part one
minutes: 45
objectives:
  - Read container state, exit codes and logs to find why a container stopped
  - Use docker inspect and docker events to answer configuration questions quickly
  - Exec into running containers and run one off containers to reproduce problems
---
Most container incidents fall into a few shapes: it will not start, it starts and exits, it runs but misbehaves, or it cannot reach something. A fixed order of questions finds the cause fast.

@concept A debugging order
@plain
Ask the same questions in the same order: is it running, why did it stop, what did it say, what is its configuration, what can it reach.
@problem
Random commands waste time during an incident. A checklist converts panic into a procedure.
@does
- `docker ps -a`: state and exit code.
- `docker logs`: what the app printed.
- `docker inspect`: the exact configuration the engine used.
- `docker exec`: look from inside.
- `docker events`, `docker stats`, `docker top`: engine and resource view.
@diagram flow
caption: Triage order for a misbehaving container
numbered: true
nodes:
  - "State|docker ps -a|info"
  - "Logs|docker logs|info"
  - "Config|docker inspect|env"
  - "Inside|docker exec|app"
  - "Outside|network and host|warn"
@h Starter commands
```bash title="First minute" lab
docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' | head
docker logs --tail 50 --timestamps api
docker inspect api --format 'state={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}'
docker top api
docker stats --no-stream api
```
@end

@concept Exit codes
@plain
When a container stops, its exit code says why. Codes above 128 mean the process was killed by signal number code minus 128.
@problem
"Container exited" tells you nothing. The code separates an application error from a kill, an out of memory event and a missing command.
@does
- `0`: clean exit; for a long running service this usually means it forgot to stay in the foreground.
- `1`: generic application error. `2`: shell misuse or wrong arguments.
- `125`: docker run itself failed. `126`: command found but not executable. `127`: command not found.
- `137`: SIGKILL (128+9), often OOM. `139`: SIGSEGV. `143`: SIGTERM (128+15), a normal stop.
@diagram cmp
caption: Reading exit codes
cards:
  - {h: "0 and 143", kind: ok, items: ["Clean exit or normal stop", "0 on a service = process ended", "143 = SIGTERM received"]}
  - {h: "1, 2", kind: warn, items: ["Application error", "Read the last log lines"]}
  - {h: "126, 127", kind: bad, items: ["Not executable or not found", "Wrong CMD, missing file, wrong architecture"]}
  - {h: "137, 139", kind: bad, items: ["137 = killed, check OOMKilled", "139 = segmentation fault"]}
@h Reproduce each
```bash title="See common exit codes" lab
docker run --name e127 alpine:3.20 /nope; echo "code=$?"
docker run --name e1 alpine:3.20 sh -c 'exit 1'; echo "code=$?"
docker run --name e137 --memory 8m alpine:3.20 sh -c 'x=$(head -c 50000000 /dev/zero | tr "\0" a)'; docker inspect -f 'oom={{.State.OOMKilled}} code={{.State.ExitCode}}' e137
docker rm e127 e1 e137
```
@check
What does exit code 137 with OOMKilled false suggest? || An external SIGKILL, such as docker kill, a failed liveness probe or the stop timeout expiring, not a memory limit.
@end

@concept Logs
@plain
Containers should write logs to stdout and stderr. The engine captures them and `docker logs` or `kubectl logs` reads them.
@problem
Logs written to files inside the container vanish with it and cannot be collected. Unbounded logs also fill the host disk.
@does
- `docker logs -f --since 10m --tail 100 -t NAME`.
- The default `json-file` driver has no size limit; set `max-size` and `max-file` in `daemon.json` or per container.
- `docker logs` does not work with some drivers (for example `awslogs` in older versions); use the destination service.
- Symlink app log files to `/dev/stdout` and `/dev/stderr`, as the official nginx image does.
- Log structured JSON so Loki, CloudWatch or ELK can parse fields.
@diagram flow
caption: Where logs travel
nodes:
  - "App writes stdout|one line one event|app"
  - "Logging driver|json-file or awslogs|info"
  - "Agent|Fluent Bit or CloudWatch agent|cp"
  - "Backend|Loki, ELK, CloudWatch|ok"
@h Limit log size
```bash title="Rotate logs per container" lab
docker run -d --name noisy --log-driver json-file --log-opt max-size=10m --log-opt max-file=3 alpine:3.20 sh -c 'while true; do echo tick; sleep 1; done'
docker logs --since 10s noisy | tail -3
docker inspect noisy --format '{{.HostConfig.LogConfig}}'
docker rm -f noisy
```
```json title="/etc/docker/daemon.json default for all containers"
{
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
```
@end

@concept docker inspect and format templates
@plain
`docker inspect` prints everything the engine knows about an object as JSON. Go templates or `jq` pull out just the part you need.
@problem
Questions like "which image digest is this running", "what environment does it have", or "what IP and mounts" are answered in seconds with inspect, rather than hunting through Compose files.
@does
- `--format '{{.Config.Env}}'` environment, `{{.HostConfig.Binds}}` bind mounts, `{{.NetworkSettings.Networks}}` IPs.
- `{{json .State}}` piped to `jq` for readability.
- Works on images, networks and volumes too.
- Compare running state with intent: wrong tag, wrong env value, missing mount.
@diagram layers
caption: Main sections of docker inspect output
layers:
  - {label: "Container", nodes: ["State|status, exit code, health|ok", "Config|image, cmd, env, user, labels|app"]}
  - {label: "Host side", nodes: ["HostConfig|limits, mounts, restart policy|env", "NetworkSettings|IPs, ports, networks|info"]}
@h Handy extractions
```bash title="Inspect recipes" lab
docker inspect api -f '{{.Image}} {{.Config.Image}}'
docker inspect api -f '{{range .Config.Env}}{{println .}}{{end}}' | sort
docker inspect api -f '{{range .Mounts}}{{.Type}} {{.Source}} -> {{.Destination}}{{println}}{{end}}'
docker inspect api -f '{{range $n,$v := .NetworkSettings.Networks}}{{$n}} {{$v.IPAddress}}{{println}}{{end}}'
docker inspect api | jq '.[0].HostConfig | {Memory, NanoCpus, ReadonlyRootfs, CapDrop, RestartPolicy}'
```
@end

@concept docker exec and one off containers
@plain
`docker exec` starts an extra process inside a running container's namespaces. `docker run` creates a new container, handy to reproduce a problem with the same image.
@problem
You need to see the container's view: files, DNS, environment, listening ports. And sometimes the app crash-loops so quickly that there is nothing running to exec into.
@does
- `docker exec -it api sh` (use `bash` if present). Add `-u 0` for root, `-e VAR=1` to add env.
- For a crash loop: `docker run --rm -it --entrypoint sh IMAGE` starts a shell instead of the app.
- `docker cp api:/app/log.txt .` copies files out; `docker diff api` lists changed files.
- `docker commit` snapshots a debug state for investigation, never for production.
@diagram cmp
caption: exec versus run
cards:
  - {h: "docker exec", kind: info, items: ["Inside the existing container", "Same filesystem, network, env", "Needs it running"]}
  - {h: "docker run --entrypoint sh", kind: ok, items: ["New container, same image", "Works when the app crashes at start", "Compare with a clean environment"]}
@h Crash loop recipe
```bash title="Reproduce a startup failure" lab
docker run --rm -it --entrypoint sh shop-api:dev
# inside the container
id; env | sort | head; ls -la /app; python -c "import main"      # does the import fail
exit
docker cp api:/app/config.yaml ./config.from-container.yaml
```
@end

@concept Networking checks from inside
@plain
Most "service is down" reports are really DNS, port, route or firewall problems. A short set of probes inside the container tells which.
@problem
Slim images lack `curl`, `ping`, `nslookup` and `ss`, so engineers install tools into running containers, which is slow and changes the thing under test.
@does
- DNS: `getent hosts db` (works anywhere with glibc), `nslookup db`.
- Port: `nc -vz db 5432`, or bash `</dev/tcp/db/5432`.
- HTTP: `curl -sv http://api:8000/healthz`, or `wget -qO- ...` on Alpine.
- Listening ports in the container: `ss -ltnp` or `cat /proc/net/tcp`.
- If tools are missing, attach a toolbox container to the same network namespace (next section).
@diagram flow
caption: Narrowing a connectivity failure
numbered: true
nodes:
  - "DNS resolves?|getent hosts db|info"
  - "Port open?|nc -vz db 5432|info"
  - "Protocol works?|curl or psql|app"
  - "Policy or firewall?|network, SG, NetworkPolicy|warn"
@h Without installing anything
```bash title="Probe with shell built ins" lab
docker exec api sh -c 'getent hosts db || echo "dns fail"'
docker exec api bash -c 'timeout 3 bash -c "</dev/tcp/db/5432" && echo open || echo closed'
docker exec api python -c "import socket; print(socket.gethostbyname('db'))"
docker exec api cat /etc/resolv.conf
docker network inspect shop_default --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```
@end
