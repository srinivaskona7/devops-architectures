---
title: Self-hosted runners and Actions Runner Controller
minutes: 45
objectives:
  - Decide when self-hosted runners are worth their operating cost
  - Run ephemeral runners on Kubernetes with Actions Runner Controller
  - Build container images in CI without a privileged Docker daemon
---
Self-hosted runners put job execution inside your network and on your hardware. On Kubernetes, Actions Runner Controller (ARC) makes them elastic and disposable.

@concept When to self-host
@plain
Self-hosting means you run the runner agent on machines you manage. It connects out to GitHub, picks up jobs and reports results.
@problem
Hosted runners cannot reach private clusters, internal artifact stores or special hardware, and heavy use gets expensive.
@does
- Gives access to private VPC resources such as an EKS private endpoint or an internal registry.
- Allows custom sizes, GPUs, arm builds and large persistent caches.
- Moves security duty to you: patching, isolation and cleanup.
- Never attach self-hosted runners to public repositories that accept fork pull requests. Strangers could run code on your network.
@diagram cmp
caption: Decision aid
cards:
  - {h: "Stay hosted", kind: ok, items: ["Public internet targets", "Modest build volume", "No private network need"]}
  - {h: "Self-host", kind: warn, items: ["Private clusters and databases", "High volume or special hardware", "Team can operate them"]}
  - {h: "Never", kind: bad, items: ["Persistent runners for public forks", "Shared runners across trust levels"]}
@h Registering a classic runner
```bash title="Download and configure a runner (token is short-lived)" lab nocheck
mkdir actions-runner && cd actions-runner
# download the package shown on the repository Settings, Actions, Runners page
./config.sh --url https://github.com/my-org/shop --token <REGISTRATION_TOKEN> \
  --labels vpc-prod --ephemeral
./run.sh
```
@check
Why are public forks a danger for self-hosted runners? || Pull request code from anyone could run on a machine inside your network.
@end

@concept Ephemeral runners
@plain
An ephemeral runner accepts exactly one job and then unregisters and disappears. A new clean one is created for the next job.
@problem
Persistent runners accumulate files, caches, credentials and malware between jobs. One job can influence all later jobs.
@does
- The `--ephemeral` option, or the equivalent in controllers, makes the runner exit after one job.
- Pair with autoscaling so capacity follows the queue.
- Each job sees a clean filesystem, like a hosted runner.
- Cache outside the runner (remote cache, registry cache) to keep builds fast.
@diagram flow
caption: Life of an ephemeral runner
numbered: true
nodes:
  - "Job queued|workflow starts|plain"
  - "Runner created|pod or VM|app"
  - "Runs one job|clean environment|info"
  - "Destroyed|no state left|ok"
@h Check which runners exist
```bash title="List runners with the GitHub CLI" lab
gh api /repos/my-org/shop/actions/runners --jq '.runners[] | [.name,.status,.busy] | @tsv'
gh api /orgs/my-org/actions/runner-groups --jq '.runner_groups[].name'
```
:::tip
Use runner groups at the organisation level to restrict which repositories may use which runners.
:::
@end

@concept Actions Runner Controller on Kubernetes
@plain
ARC is a Kubernetes operator from GitHub that creates runner pods when jobs are waiting and removes them afterwards. It uses runner scale sets.
@problem
Managing a fleet of VMs for runners means manual scaling, patching and idle cost.
@does
- A **controller** pod watches for work. A **listener** per scale set talks to GitHub and requests more runners.
- Each job gets a fresh pod. `minRunners` and `maxRunners` bound the scale.
- The scale set name is what you put in `runs-on`.
- Install with Helm using OCI charts. Check the current docs for chart versions and values.
@diagram layers
caption: ARC components in a cluster
layers:
  - {label: "arc-systems namespace", nodes: ["Controller|manages scale sets|cp", "Listener|polls GitHub for jobs|info"]}
  - {label: "arc-runners namespace", nodes: ["Runner pod|one job|app", "Runner pod|one job|app", "Runner pod|one job|app"]}
  - {label: "Outside", nodes: ["GitHub|job queue|ext"]}
@h Install
```bash title="Helm install of controller and a scale set" lab
helm install arc --namespace arc-systems --create-namespace \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller
helm install shop-runners --namespace arc-runners --create-namespace \
  --set githubConfigUrl="https://github.com/my-org" \
  --set githubConfigSecret.github_token="$GITHUB_PAT" \
  --set minRunners=0 --set maxRunners=20 \
  oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set
```
```yaml title="Workflow using the scale set name"
name: build
on: [push]
jobs:
  build:
    runs-on: shop-runners
    steps:
      - uses: actions/checkout@v4
      - run: echo "running in a pod"
```
@check
What does a workflow put in runs-on to use an ARC scale set? || The scale set installation name.
@end

@concept ARC configuration and authentication
@plain
ARC needs credentials to talk to GitHub. A GitHub App is preferred to a personal access token for organisations. The runner pod spec is customised through Helm values.
@problem
A personal token tied to one person breaks when they leave, and has wide scope. Default runner pods may lack the tools or limits you need.
@does
- A **GitHub App** with the runner permissions is installed on the organisation, and its app ID, installation ID and private key go into a Kubernetes secret.
- Values set resources, node selectors, tolerations, service accounts and extra volumes through the `template.spec`.
- Give runner pods an IAM role with IRSA or EKS Pod Identity if the job needs AWS, in addition to or instead of OIDC from the workflow.
- Run runner pods on a dedicated node group so jobs cannot disturb services.
@diagram flow
caption: Credentials in an ARC setup
nodes:
  - "GitHub App|installed on org|ext"
  - "Secret|app id and private key|cp"
  - "Controller|registers runners|app"
  - "Runner pod|service account with IAM role|env"
@h Values fragment
```yaml title="values.yaml for the scale set"
githubConfigUrl: https://github.com/my-org
githubConfigSecret: arc-github-app
minRunners: 0
maxRunners: 20
template:
  spec:
    serviceAccountName: runner
    nodeSelector:
      workload: ci
    tolerations:
      - key: ci
        operator: Equal
        value: "true"
        effect: NoSchedule
    containers:
      - name: runner
        image: ghcr.io/actions/actions-runner:latest
        command: ["/home/runner/run.sh"]
        resources:
          requests: {cpu: "2", memory: 4Gi}
          limits: {memory: 8Gi}
```
:::note
Pin the runner image tag instead of latest in production, and check the current docs for the exact value layout.
:::
@end

@concept Building images without a privileged daemon
@plain
Running `docker build` inside a pod normally needs a Docker daemon and elevated privileges. Daemonless builders such as BuildKit rootless, Kaniko-style tools or remote builders avoid mounting the host socket.
@problem
Mounting `/var/run/docker.sock` or using `privileged: true` lets a job take over the node. In a shared cluster that is an escape route.
@does
- **Remote BuildKit** (a BuildKit service in the cluster, or Docker build cloud) keeps builds off the runner.
- **Rootless BuildKit** runs as a normal user with user namespaces where the kernel allows it.
- ARC also supports a Docker-in-Docker mode, which still needs privileged containers.
- Cache layers to a registry with `--cache-to type=registry` so builds stay fast on fresh pods.
@diagram cmp
caption: Options for container builds in CI
cards:
  - {h: "Host socket", kind: bad, items: ["Fast and simple", "Job controls the node", "Avoid in shared clusters"]}
  - {h: "Docker in Docker", kind: warn, items: ["Needs privileged pod", "Isolated daemon per job", "Contained but powerful"]}
  - {h: "Rootless or remote BuildKit", kind: ok, items: ["No node access", "Registry cache", "Preferred"]}
@h Registry cache with buildx
```yaml title="Build and push with registry cache" nocheck
- uses: docker/setup-buildx-action@v3
- uses: docker/build-push-action@v6
  with:
    context: .
    push: true
    tags: 111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:${{ github.sha }}
    cache-from: type=registry,ref=111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:buildcache
    cache-to: type=registry,ref=111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop:buildcache,mode=max
```
@check
Why avoid mounting the Docker socket into CI pods? || The job could then start privileged containers on the node and escape.
@end

@concept Hardening runners
@plain
A runner holds credentials and executes arbitrary code from the repository. Hardening limits what a malicious job can do and what it can reach.
@problem
A compromised build is a pivot point. If the runner can reach everything, so can the attacker.
@does
- Separate runner groups by trust level: untrusted pull request builds and trusted deploy jobs never share runners.
- Network policies and security groups allow only needed egress: registry, GitHub, package mirrors.
- Block access to the cloud metadata service from job pods, or require IMDSv2 with hop limit 1.
- Run as non-root, drop capabilities, use read-only root filesystems where the tools allow.
- Keep the runner image minimal and rebuild it regularly.
@diagram layers
caption: Isolation layers for CI workloads
layers:
  - {label: "Trust", nodes: ["PR build pool|no deploy credentials|warn", "Deploy pool|OIDC and short-lived roles|ok"]}
  - {label: "Network", nodes: ["Egress allow list|registry and GitHub|cp", "No metadata access|IMDSv2 hop limit 1|cp"]}
  - {label: "Pod", nodes: ["Non-root|dropped capabilities|info", "Ephemeral|destroyed after job|info"]}
@h Deny-by-default egress for runners
```yaml title="NetworkPolicy for the runner namespace" nocheck
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata: {name: runner-egress, namespace: arc-runners}
spec:
  podSelector: {}
  policyTypes: [Egress]
  egress:
    - to:
        - ipBlock: {cidr: 0.0.0.0/0, except: [169.254.169.254/32, 10.0.0.0/8]}
      ports: [{port: 443, protocol: TCP}]
    - ports: [{port: 53, protocol: UDP}]
```
:::warn
The policy above is an illustration. A real one lists the private ranges and endpoints you must reach, since the 10.0.0.0/8 exception also blocks your own services.
:::
@end

@concept Cost and capacity of runners
@plain
Hosted runners bill by the minute, self-hosted cost compute and people time. Knowing your minutes and queue time shows which is cheaper.
@problem
Teams move to self-hosting to save money and then find idle nodes and operations work erase the saving. Or they stay hosted while paying for hours of waste.
@does
- Measure monthly minutes per workflow, then rank. A few workflows usually dominate.
- Spot or interruptible instances suit CI because jobs can retry, with ARC running on a Karpenter-managed node pool.
- `minRunners: 0` saves money but adds start latency. Keep a small warm pool for busy hours.
- Reduce minutes first by caching, path filters and cancelling superseded runs.
@diagram flow
caption: Cost reduction order
nodes:
  - "Measure|minutes per workflow|info"
  - "Cut waste|cache, filters, cancel|ok"
  - "Right-size|runner CPU and memory|app"
  - "Spot capacity|ARC on interruptible nodes|env"
@h Find expensive workflows
```bash title="Run time per workflow" lab
gh run list --limit 200 --json workflowName,startedAt,updatedAt \
  --jq 'group_by(.workflowName)[] | {wf: .[0].workflowName, runs: length}'
```
@check
What is the first step before self-hosting to save money? || Measure where minutes go and cut waste with caching, filters and cancellation.
@end
