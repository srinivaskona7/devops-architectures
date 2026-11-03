---
title: kubectl mastery
minutes: 55
objectives:
  - Extract exactly the fields you need with jsonpath and custom columns
  - Debug Pods and nodes with kubectl debug and ephemeral containers
  - Extend kubectl with plugins and krew and manage many contexts safely
---
kubectl is the main tool of every Kubernetes engineer. A few advanced features turn long pipelines of grep and awk into single reliable commands and make work on many clusters safer.

@concept Output formats and server-side printing
@plain
`-o` changes how kubectl prints an object. Besides `yaml` and `json`, there are `wide`, `name`, `jsonpath`, `custom-columns` and `go-template`.
@problem
Default tables hide fields you need, and scraping them with awk breaks when columns change.
@does
- `-o wide` adds node, IP and image columns. `-o name` prints `kind/name`, ideal for loops.
- `kubectl get` asks the server for a Table, so columns can include custom printer columns of CRDs.
- `--sort-by=.metadata.creationTimestamp` sorts using a jsonpath. `--no-headers` helps scripts.
- `-l` filters by label and `--field-selector` by a few supported fields, such as `status.phase` or `spec.nodeName`.
@diagram flow
caption: Choosing an output format
nodes:
  - "Human reading|wide or default|info"
  - "Quick field|jsonpath|app"
  - "Report table|custom-columns|app"
  - "Pipe to tools|json with jq|ok"
@h Everyday forms
```bash title="Sorting, selecting, naming" lab
kubectl get pods -A -o wide --sort-by=.metadata.creationTimestamp | tail -5
kubectl get pods -A --field-selector=status.phase!=Running,status.phase!=Succeeded
kubectl get deploy -n shop -o name
kubectl get pods -n shop -l app=api,tier=backend --show-labels
```
@end

@concept JSONPath
@plain
JSONPath is a small query language over the object JSON. kubectl wraps it in braces: `{.metadata.name}`.
@problem
You need one value, such as every image in the cluster or a node's internal IP, without parsing a table.
@does
- `{.items[*].metadata.name}` takes a field from all items. `{range .items[*]}...{end}` loops and lets you add newlines with `{"\n"}`.
- Filters: `{.items[?(@.status.phase=="Running")].metadata.name}`.
- Dots in keys are escaped: `{.data.tls\.crt}` reads the key `tls.crt` of a Secret.
- kubectl's jsonpath has no regex or arithmetic. For more power use `-o json | jq`.
@diagram flow
caption: A jsonpath expression step by step
nodes:
  - "items|list of Pods|plain"
  - "range|loop over each|info"
  - "spec.containers|inner list|app"
  - "image|printed per line|ok"
@h Useful queries
```bash title="Images in use and a decoded secret key" lab
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{.spec.containers[*].image}{"\n"}{end}' | head
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.status.addresses[?(@.type=="InternalIP")].address}{"\n"}{end}'
kubectl get secret tls-cert -n shop -o jsonpath='{.data.tls\.crt}' | base64 -d | openssl x509 -noout -enddate
```
@check
How do you read a Secret key named tls.crt in jsonpath? || Escape the dot, {.data.tls\.crt}, and base64-decode the result.
@end

@concept Custom columns and templates
@plain
`-o custom-columns=HEADER:path,...` makes a tidy table from any fields. `go-template` gives loops and conditions when jsonpath is not enough.
@problem
Operations reports need a stable, readable layout such as Pod name, node and restarts, and ad hoc scripts drift over time.
@does
- Each column is `NAME:.json.path`. Use `[*]` to join list values with commas.
- `custom-columns-file=cols.txt` stores a layout for reuse in a team repository.
- `go-template` supports `if`, `range`, `printf` and the `index` function for keys with dots.
@diagram cmp
caption: Which formatter for which job
cards:
  - {h: "custom-columns", kind: ok, items: ["Fixed table layout", "Easy to read and share", "No conditions"]}
  - {h: "jsonpath", kind: info, items: ["Single values and loops", "Filters on lists", "No arithmetic"]}
  - {h: "go-template", kind: warn, items: ["Full logic", "Harder to read", "Last resort before jq"]}
@h Examples
```bash title="Readable tables" lab
kubectl get pods -n shop -o custom-columns=POD:.metadata.name,NODE:.spec.nodeName,RESTARTS:.status.containerStatuses[*].restartCount,IMAGE:.spec.containers[*].image
kubectl get nodes -o custom-columns=NAME:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory,TAINTS:.spec.taints[*].key
kubectl get pods -n shop -o go-template='{{range .items}}{{.metadata.name}}{{"\n"}}{{end}}'
```
@end

@concept kubectl debug and ephemeral containers
@plain
`kubectl debug` adds a temporary container with debugging tools to a running Pod, or copies a Pod, or starts a privileged Pod on a node.
@problem
Production images are minimal or distroless and have no shell, so `kubectl exec` cannot help.
@does
- Ephemeral container: `kubectl debug -it POD --image=nicolaka/netshoot --target=app` shares the process namespace of the target container. They cannot be removed, and the Pod keeps them until it is recreated.
- Copy: `--copy-to=NAME` creates a clone, where you can change the image or command (`--set-image`) without touching the original.
- Node: `kubectl debug node/NODE -it --image=busybox` starts a Pod in the host namespaces with the node filesystem at `/host`.
- RBAC needs `pods/ephemeralcontainers` update permission; Pod Security may block privileged node debugging. Newer releases add debugging profiles (`--profile`); check the current docs.
@diagram flow
caption: Three ways to debug
nodes:
  - "Running Pod|no shell|bad"
  - "Ephemeral container|attached, shares processes|app"
  - "Copy of Pod|safe experiments|info"
  - "Node debug|host view at /host|warn"
@h Commands
```bash title="Debug without changing the app" lab
kubectl debug -it POD -n shop --image=nicolaka/netshoot --target=api -- bash
kubectl debug POD -n shop -it --copy-to=api-dbg --set-image=api=busybox:1.36 -- sh
kubectl debug node/NODE -it --image=busybox:1.36 -- chroot /host sh
kubectl delete pod api-dbg -n shop
```
:::warn
Node debugging gives root on the host. In Gardener or Kyma clusters follow your team's access policy and delete the debug Pod afterwards.
:::
@end

@concept Contexts, kubeconfig and safe switching
@plain
A kubeconfig holds clusters, users and contexts. A context is a named triple of cluster, user and default namespace.
@problem
With Kyma, EKS and Gardener clusters at once, one command in the wrong context can change production.
@does
- `KUBECONFIG=a.yaml:b.yaml` merges files for one session; `kubectl config view --flatten --minify` exports one context.
- Prefer one kubeconfig per cluster and an environment variable per terminal, rather than a global current-context.
- `kubectx` and `kubens` switch quickly. Show the context in your shell prompt.
- Always pass `--context` in scripts. Use `kubectl auth whoami` (recent versions) and `kubectl auth can-i` to confirm identity and rights.
- Exec credential plugins (`aws eks get-token`, `kubelogin` for OIDC) fetch short lived tokens, so kubeconfig files hold no long-lived secret.
@diagram flow
caption: Resolving a command to a cluster
nodes:
  - "KUBECONFIG|file list|plain"
  - "current-context|or --context|info"
  - "Cluster and user|endpoint and credential|app"
  - "Exec plugin|short-lived token|ok"
@h Commands
```bash title="Work safely with contexts" lab
kubectl config get-contexts
kubectl --context=prod-eks get ns | head -3
kubectl config view --minify --flatten > /tmp/one-cluster.yaml
KUBECONFIG=/tmp/one-cluster.yaml kubectl auth can-i delete deploy -n shop
```
@check
Why pass --context in scripts? || The current-context can change between runs or terminals, and an explicit context prevents running against the wrong cluster.
@end

@concept kubectl plugins
@plain
Any executable on your PATH named `kubectl-NAME` is a plugin and runs as `kubectl NAME`.
@problem
Teams repeat the same multi-step commands and want them to look native.
@does
- Dashes in the file name become subcommands: `kubectl-foo-bar` runs with `kubectl foo bar`.
- `kubectl plugin list` shows the discovered plugins and warns about shadowed ones.
- Plugins can be bash, Go or Python. They read the same `KUBECONFIG` and receive the arguments.
- Built-in commands cannot be overridden.
@diagram flow
caption: Plugin lookup
nodes:
  - "kubectl foo bar|you type|plain"
  - "Search PATH|kubectl-foo-bar|info"
  - "Executable runs|args passed through|app"
@h A tiny plugin
```bash title="kubectl-restarts, top restarting Pods" lab
cat > /tmp/kubectl-restarts <<'EOF'
#!/usr/bin/env bash
kubectl get pods "$@" --no-headers -o custom-columns=NS:.metadata.namespace,POD:.metadata.name,R:.status.containerStatuses[0].restartCount | sort -k3 -nr | head -10
EOF
chmod +x /tmp/kubectl-restarts
PATH=$PATH:/tmp kubectl restarts -A
```
@end

@concept krew and useful plugins
@plain
krew is the plugin manager for kubectl. It installs community plugins from an index with `kubectl krew install`.
@problem
Finding, installing and updating plugins by hand is slow and unsafe.
@does
- `kubectl krew search`, `install`, `upgrade` and `list` manage plugins in `~/.krew`.
- Popular ones: `ctx`, `ns`, `neat` (clean YAML), `tree` (owner hierarchy), `who-can` (RBAC), `view-secret`, `stern` style log tailing, `resource-capacity`, `df-pv`.
- Plugins run with your credentials, so install only from trusted sources and review them in sensitive environments.
- Check your organisation's policy on the default index.
@diagram flow
caption: Install flow
nodes:
  - "krew index|plugin manifests|ext"
  - "kubectl krew install|download and verify|info"
  - "~/.krew/bin|on PATH|app"
  - "kubectl plugin|ready|ok"
@h Try it
```bash title="Install and use plugins" lab
kubectl krew install ctx ns neat tree who-can
kubectl tree deployment api -n shop
kubectl who-can delete pods -n shop
kubectl get deploy api -n shop -o yaml | kubectl neat
```
@end

@concept Apply, diff, patch and wait
@plain
Beyond `apply`, kubectl has verbs to preview, change a single field and wait for conditions, which make scripts and pipelines reliable.
@problem
Pipelines that apply and immediately continue race against the cluster, and blind edits cause outages.
@does
- `kubectl diff -f` shows what would change; it exits with 1 if there are differences.
- `kubectl patch --type=merge|json|strategic` edits fields. Strategic merge understands lists with keys; JSON patch uses `op/path/value`.
- `kubectl wait --for=condition=Available deploy/api --timeout=120s` blocks until true; `--for=delete` and `--for=jsonpath=...` are also supported.
- `kubectl rollout status` follows a rollout and fails on timeout.
- `--dry-run=server` validates against admission without persisting.
@diagram flow
caption: Safe change pipeline
nodes:
  - "dry-run=server|validate|info"
  - "diff|review changes|warn"
  - "apply|server-side|app"
  - "wait or rollout status|confirm|ok"
@h Commands
```bash title="Safe change sequence" lab
kubectl apply -f deploy.yaml --dry-run=server
kubectl diff -f deploy.yaml || true
kubectl apply -f deploy.yaml
kubectl rollout status deploy/api -n shop --timeout=180s
kubectl wait --for=condition=Available deploy/api -n shop --timeout=60s
kubectl patch deploy api -n shop --type=json -p='[{"op":"replace","path":"/spec/replicas","value":3}]'
```
@check
What does kubectl diff return when there are changes? || Exit code 1, so scripts can tell that a difference exists. Exit code above 1 means an error.
@end
