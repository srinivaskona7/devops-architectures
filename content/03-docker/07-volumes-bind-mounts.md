---
title: Volumes, bind mounts and tmpfs
minutes: 40
objectives:
  - Choose between named volumes, bind mounts and tmpfs for a workload
  - Back up and restore volume data and avoid common permission errors
  - Map Docker storage ideas to Kubernetes volumes and PersistentVolumeClaims
---
A container's writable layer disappears with the container. Anything you need to keep, such as a database, uploads or caches, must live outside it.

@concept Why containers lose data
@plain
The writable layer belongs to one container. Remove the container and the layer is deleted with it.
@problem
Teams run a database in a container, recreate it for an upgrade, and find the tables empty.
@does
- Data written without a mount stays in the container layer under `/var/lib/docker/overlay2`.
- `docker rm` and `docker compose down` delete that layer. Named volumes survive unless you add `-v` to `down`.
- Writes to the layer also go through overlayfs, which is slower than a volume.
- Rule: the image is immutable code, the volume is state.
@diagram cmp
caption: Where data can live
cards:
  - {h: "Container layer", kind: bad, items: ["Deleted with the container", "Slower writes", "Fine for scratch only"]}
  - {h: "Named volume", kind: ok, items: ["Managed by Docker", "Survives rm", "Best for databases"]}
  - {h: "Bind mount", kind: info, items: ["A host path you choose", "Great for dev source code", "Host dependent"]}
  - {h: "tmpfs", kind: warn, items: ["RAM only", "Gone on stop", "Good for secrets and temp files"]}
@h Prove it
```bash title="Data in the layer is lost" lab
docker run --name t1 alpine:3.20 sh -c 'echo important > /data.txt'
docker rm t1
docker run --rm alpine:3.20 cat /data.txt 2>&1 | head -1    # file not found
```
@end

@concept Named volumes
@plain
A named volume is storage managed by Docker. You refer to it by name and Docker decides where it lives on the host.
@problem
You need durable storage that does not depend on a host path layout and that you can share between containers.
@does
- Create implicitly with `-v pgdata:/var/lib/postgresql/data` or explicitly with `docker volume create`.
- An empty volume is populated from the image's files at that path on first use.
- `docker volume ls`, `inspect` (shows Mountpoint), `rm`, `prune`.
- Drivers allow NFS, EFS or cloud disks through plugins or local driver options.
@diagram flow
caption: A volume outlives the containers that use it
nodes:
  - "Container v1|postgres 16|app"
  - "Volume pgdata|on the host|ok"
  - "Container v2|postgres 16.4|app"
@h Postgres that keeps its data
```bash title="Upgrade a container, keep data" lab
docker volume create pgdata
docker run -d --name pg -e POSTGRES_PASSWORD=dev -v pgdata:/var/lib/postgresql/data postgres:16
sleep 8; docker exec pg psql -U postgres -c "create table t(i int); insert into t values (1);"
docker rm -f pg
docker run -d --name pg -e POSTGRES_PASSWORD=dev -v pgdata:/var/lib/postgresql/data postgres:16
sleep 8; docker exec pg psql -U postgres -c "select * from t;"
docker rm -f pg; docker volume rm pgdata
```
@check
Does docker rm delete named volumes? || No. Only anonymous volumes with rm -v, or an explicit docker volume rm, remove them.
@end

@concept Bind mounts
@plain
A bind mount maps an exact host file or directory into the container. Both sides see the same files immediately.
@problem
During development you want to edit code on your laptop and see it run in the container without rebuilding.
@does
- `-v "$PWD":/app` or the clearer `--mount type=bind,src=$PWD,dst=/app`.
- `--mount` fails if the host path is missing; `-v` silently creates a root-owned directory.
- Add `,readonly` to prevent the container changing host files.
- On macOS file sharing crosses a VM, so heavy I/O (node_modules) is slow; keep dependencies in a volume.
@diagram flow
caption: Live reload through a bind mount
nodes:
  - "Editor|you save main.py|plain"
  - "Host folder|./src|env"
  - "Container /app|same files|app"
  - "uvicorn --reload|restarts|ok"
@h Dev run
```bash title="Mount source read only" lab
docker run --rm -p 8000:8000 \
  --mount type=bind,src="$PWD",dst=/app,readonly \
  shop-api:dev uvicorn main:app --host 0.0.0.0 --reload
```
:::warn
Never bind mount `/var/run/docker.sock` or `/` into a container you do not fully trust. It grants control of the host.
:::
@end

@concept tmpfs and read-only roots
@plain
A tmpfs mount lives in RAM. Combined with a read-only root filesystem, it gives an app a writable scratch area while the image stays untouchable.
@problem
Apps write temp files and PID files. On a read-only root they crash; making everything writable weakens security.
@does
- `--read-only --tmpfs /tmp:rw,size=64m,mode=1777`.
- Memory used counts toward the container memory limit.
- Kubernetes equivalent: `readOnlyRootFilesystem: true` plus an `emptyDir` with `medium: Memory`.
@diagram layers
caption: Read-only image with small writable windows
layers:
  - {label: "Writable", nodes: ["/tmp tmpfs|RAM, 64 MB|warn", "/var/lib/app volume|state|ok"]}
  - {label: "Read only", nodes: ["Application code|image layers|app", "OS libraries|image layers|app"]}
@h Run
```bash title="Read-only root with tmpfs" lab
docker run --rm --read-only --tmpfs /tmp:rw,size=16m alpine:3.20 sh -c 'echo ok > /tmp/a && echo tmp ok; touch /etc/x 2>&1 | head -1'
```
@end

@concept Permissions and ownership
@plain
Files in a volume carry numeric user IDs. If the container runs as UID 10001 but the files belong to root, writes fail with permission denied.
@problem
This is the most common error after moving to non-root images or to Kubernetes volumes.
@does
- Docker copies image ownership into a fresh named volume, so `chown` the folder in the Dockerfile before it is first mounted.
- For bind mounts, match UIDs with `--user "$(id -u):$(id -g)"`.
- In Kubernetes use `securityContext.fsGroup` so mounted volumes become group writable.
@diagram flow
caption: Diagnosing a permission denied on a volume
numbered: true
nodes:
  - "Error|permission denied|bad"
  - "Who am I|docker exec id|info"
  - "Who owns it|ls -ln path|info"
  - "Fix|chown, --user or fsGroup|ok"
@h Diagnose
```bash title="Compare IDs" lab
docker run --rm -v appdata:/data alpine:3.20 sh -c 'ls -lnd /data; id'
docker run --rm -v appdata:/data alpine:3.20 chown -R 10001:10001 /data     # fix once
```
@end

@concept Backup, restore and Kubernetes mapping
@plain
A volume is only a directory, so you can archive it with a throwaway container that mounts it.
@problem
Volumes are invisible in your file manager, so teams forget to back them up until a host fails.
@does
- Backup: run `tar` in a helper container with the volume read-only.
- For databases prefer logical dumps (`pg_dump`) or snapshots for consistency.
- Kubernetes maps: named volume to PersistentVolumeClaim, bind mount to hostPath (avoid), tmpfs to emptyDir Memory, configs to ConfigMap volumes.
@diagram flow
caption: Archive a volume with a helper container
nodes:
  - "Volume|pgdata|ok"
  - "Helper alpine|tar czf|app"
  - "Host folder|backup.tgz|env"
@h Commands
```bash title="Backup and restore a volume" lab
docker run --rm -v pgdata:/data:ro -v "$PWD":/backup alpine:3.20 tar czf /backup/pgdata.tgz -C /data .
docker volume create pgdata-restored
docker run --rm -v pgdata-restored:/data -v "$PWD":/backup alpine:3.20 tar xzf /backup/pgdata.tgz -C /data
```
@check
Which Kubernetes object replaces a Docker named volume for a database? || A PersistentVolumeClaim, usually through a StatefulSet volumeClaimTemplate.
@end
