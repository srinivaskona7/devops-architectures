---
title: Batch and ML on Kubernetes
minutes: 50
objectives:
  - Design reliable Jobs and indexed parallel processing
  - Run GPU workloads with the device plugin model and node pools
  - Orchestrate multi-step and distributed training jobs
---
Batch and machine learning workloads are bursty, resource hungry and often need special hardware. Kubernetes handles them well with the right primitives.

@concept Jobs, completions and failure handling
@plain
A Job runs Pods until a number of them finish successfully. It retries failed Pods up to a limit.
@problem
Plain Pods are not rescheduled after completion or failure semantics are unclear. Deployments restart finished processes forever.
@does
- `completions` and `parallelism` define total and concurrent Pods. `backoffLimit` caps retries, `activeDeadlineSeconds` caps total runtime.
- `restartPolicy` must be `Never` or `OnFailure`.
- `ttlSecondsAfterFinished` removes finished Jobs. Without it they accumulate.
- `podFailurePolicy` lets you fail fast on certain exit codes or ignore disruptions (preemption, drain).
- `backoffLimitPerIndex` (for indexed jobs) isolates failures to individual indexes; check the current docs for status in your version.
@diagram flow
caption: Job result
nodes:
  - "Pod runs|exit code|app"
  - "Exit 0|counts as success|ok"
  - "Exit 1|retry with backoff|warn"
  - "backoffLimit reached|Job Failed|bad"
@h Example
```yaml title="Job with failure policy"
apiVersion: batch/v1
kind: Job
metadata:
  name: nightly-report
  namespace: batch
spec:
  backoffLimit: 4
  activeDeadlineSeconds: 3600
  ttlSecondsAfterFinished: 86400
  podFailurePolicy:
    rules:
      - action: FailJob
        onExitCodes:
          containerName: report
          operator: In
          values: [42]
      - action: Ignore
        onPodConditions:
          - type: DisruptionTarget
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: report
          image: registry.example.com/batch/report:2.1
          resources:
            requests: {cpu: "1", memory: 2Gi}
```
@check
Why use the Ignore action for DisruptionTarget? || Evictions and preemption are not application faults, so they should not consume the retry budget.
@end

@concept Indexed Jobs and work queues
@plain
Indexed completion mode gives every Pod a number in `JOB_COMPLETION_INDEX`. Each Pod processes its own slice of the data.
@problem
Splitting a big task needs a coordinator or message queue, which adds components.
@does
- `completionMode: Indexed` with `completions: 100` and `parallelism: 10` runs 100 indexes, 10 at once.
- The Pod reads the index from the env var or annotation and picks its shard, for example file number or key range.
- For dynamic work, use a queue (SQS, RabbitMQ, Redis) with workers and KEDA scaling on queue depth.
- Make tasks idempotent so retries are safe.
@diagram flow
caption: Sharding by index
nodes:
  - "Dataset|1000 files|ext"
  - "Indexed Job|100 indexes|cp"
  - "Pod index 7|files 70 to 79|app"
  - "Output bucket|results|ok"
@h Example
```yaml title="Indexed job"
apiVersion: batch/v1
kind: Job
metadata:
  name: thumbnail
spec:
  completionMode: Indexed
  completions: 20
  parallelism: 5
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "echo processing shard $JOB_COMPLETION_INDEX"]
```
@end

@concept CronJobs done properly
@plain
A CronJob creates Jobs on a schedule. It has settings that control overlap, missed runs and history.
@problem
Default settings can run overlapping jobs, silently skip runs, or fill the namespace with old Jobs.
@does
- `concurrencyPolicy`: `Allow`, `Forbid` or `Replace`. Use `Forbid` for most data jobs.
- `startingDeadlineSeconds` bounds how late a missed run may still start. If more than 100 runs are missed the controller stops scheduling.
- `timeZone` (GA) sets the zone; otherwise the controller's local time (usually UTC).
- `successfulJobsHistoryLimit` and `failedJobsHistoryLimit` keep a few for debugging.
- `suspend: true` pauses it, useful during incidents.
@diagram flow
caption: CronJob to Pod
nodes:
  - "Schedule|0 2 * * *|plain"
  - "CronJob controller|creates Job|cp"
  - "Job|retries and limits|info"
  - "Pod|does the work|app"
@h Example
```yaml title="Safe CronJob"
apiVersion: batch/v1
kind: CronJob
metadata:
  name: cleanup
  namespace: batch
spec:
  schedule: "0 2 * * *"
  timeZone: Asia/Kolkata
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 600
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: cleanup
              image: busybox:1.36
              command: ["sh", "-c", "echo cleaning"]
```
@check
Which concurrencyPolicy avoids two overlapping runs? || Forbid skips a new run while the previous one is still active.
@end

@concept GPUs and device plugins
@plain
GPUs are exposed to Kubernetes as extended resources such as `nvidia.com/gpu` by a device plugin. Pods request them in `limits`.
@problem
The scheduler knows only CPU and memory natively. Special hardware must be advertised and allocated exclusively.
@does
- The NVIDIA GPU Operator installs drivers, container toolkit, device plugin and DCGM exporter. Managed offerings (EKS accelerated AMIs, GKE) may include some parts.
- Whole GPUs are not shared by default. Sharing options: time slicing, MIG (partitions on supported cards), MPS. Check vendor docs.
- Use dedicated node pools with taints (`nvidia.com/gpu:NoSchedule`) so that non-GPU Pods avoid expensive nodes.
- Dynamic Resource Allocation (DRA) is the newer, more flexible API for devices; check its status in your version.
@diagram layers
caption: GPU stack
layers:
  - {label: "Workload", nodes: ["Pod|limits nvidia.com/gpu 1|app"]}
  - {label: "Kubernetes", nodes: ["Device plugin|advertises GPUs|cp", "Scheduler|counts GPU resource|cp"]}
  - {label: "Node", nodes: ["Container toolkit|injects devices|info", "Driver|kernel module|info", "GPU|hardware|ext"]}
@h Request a GPU
```yaml title="GPU Pod"
apiVersion: v1
kind: Pod
metadata:
  name: gpu-check
spec:
  restartPolicy: Never
  tolerations:
    - key: nvidia.com/gpu
      operator: Exists
      effect: NoSchedule
  containers:
    - name: smi
      image: nvidia/cuda:12.4.1-base-ubuntu22.04
      command: ["nvidia-smi"]
      resources:
        limits:
          nvidia.com/gpu: 1
```
@end

@concept Distributed training and JobSet
@plain
Training across many Pods needs them to start together and find each other. Operators and JobSet provide this.
@problem
A plain Job may start 3 of 8 workers and the cluster fills with Pods that wait forever (partial allocation deadlock).
@does
- **JobSet** (Kubernetes SIG) models groups of Jobs, such as one driver plus many workers, with startup order and failure policy.
- **Kubeflow Training Operator** offers PyTorchJob, TFJob and others; **KubeRay** manages Ray clusters and jobs.
- Gang scheduling comes from Kueue (all or nothing admission) or schedulers such as Volcano.
- Use topology-aware placement and fast networking (EFA on AWS) for large jobs.
- Checkpoint to object storage so a preempted job can resume.
@diagram flow
caption: Gang admitted then started
nodes:
  - "Submit PyTorchJob|1 master, 7 workers|app"
  - "Kueue quota check|all 8 or none|cp"
  - "Pods start together|rendezvous|info"
  - "Checkpoints|object storage|ext"
@h Shape
```yaml title="JobSet with driver and workers" nocheck
apiVersion: jobset.x-k8s.io/v1alpha2
kind: JobSet
metadata:
  name: train
spec:
  replicatedJobs:
    - name: workers
      replicas: 1
      template:
        spec:
          parallelism: 4
          completions: 4
          template:
            spec:
              restartPolicy: Never
              containers:
                - name: trainer
                  image: registry.example.com/ml/train:1.0
                  resources:
                    limits:
                      nvidia.com/gpu: 1
```
@check
What problem does gang scheduling solve? || Jobs that need all workers at once otherwise hold partial resources and may never start.
@end

@concept Cost and capacity for batch
@plain
Batch is the best candidate for spot or preemptible capacity, scale-to-zero node pools and bin-packing.
@problem
Idle GPU or large nodes cost a lot. Batch runs at night should not need always-on capacity.
@does
- Use node autoscaling (Cluster Autoscaler or Karpenter) with separate pools; scale to zero when no Jobs run.
- Tolerate spot interruptions: retries, checkpoints, `podFailurePolicy` ignoring disruptions.
- Priority classes: batch below services with `preemptionPolicy: Never`.
- Set realistic requests; measure with `kubectl top`, Prometheus and cost tools (OpenCost).
- Use `ResourceQuota` per namespace to cap runaway fan-out.
@diagram cmp
caption: Capacity types
cards:
  - {h: "On-demand", kind: info, items: ["Steady services", "Higher price"]}
  - {h: "Spot", kind: ok, items: ["Batch and CI", "Can be interrupted", "Needs retry design"]}
  - {h: "Reserved", kind: warn, items: ["Known baseline", "Commitment risk"]}
@h Karpenter pool for batch (shape)
```yaml title="NodePool for batch on spot" nocheck
apiVersion: karpenter.sh/v1
kind: NodePool
metadata:
  name: batch-spot
spec:
  template:
    spec:
      requirements:
        - key: karpenter.sh/capacity-type
          operator: In
          values: ["spot"]
      taints:
        - key: workload
          value: batch
          effect: NoSchedule
      nodeClassRef:
        group: karpenter.k8s.aws
        kind: EC2NodeClass
        name: default
  disruption:
    consolidationPolicy: WhenEmptyOrUnderutilized
    consolidateAfter: 1m
  limits:
    cpu: "400"
```
@end
