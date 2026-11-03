---
title: Jobs and CronJobs
minutes: 35
objectives:
  - Run finite work with retries, parallelism and cleanup
  - Write a CronJob with safe concurrency and deadlines
  - Debug Jobs that never finish or run twice
---
Not everything runs forever. Migrations, reports, backups and batch pipelines are finite work that Kubernetes can retry and clean up.

@concept Jobs
@plain
A Job creates Pods and keeps retrying until a set number of them finish successfully.
@problem
A bare Pod that fails once stays failed, and a Deployment would restart a finished task forever.
@does
- `restartPolicy` must be `OnFailure` or `Never`.
- `completions` is how many successes are needed, `parallelism` how many Pods run at once.
- `backoffLimit` (default 6) caps retries with exponential delay; `activeDeadlineSeconds` caps total runtime.
- `ttlSecondsAfterFinished` deletes the finished Job and its Pods, otherwise they stay for log inspection.
@diagram flow
caption: A Job succeeding after a retry
nodes:
  - "Job|completions 1|app"
  - "Pod 1|fails|bad"
  - "Pod 2|retry after backoff|warn"
  - "Complete|Succeeded|ok"
@h A migration Job
```yaml title="job.yaml"
apiVersion: batch/v1
kind: Job
metadata:
  name: db-migrate
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 600
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: migrate
          image: ghcr.io/example/api:1.4.2
          command: ["./migrate", "--up"]
```
@end

@concept Parallel and indexed Jobs
@plain
Jobs can split work across many Pods, either with a shared queue or with each Pod getting a fixed index.
@problem
Processing a thousand files in one Pod is slow. Starting a thousand separate Jobs is untidy.
@does
- **Indexed completion mode** gives each Pod `JOB_COMPLETION_INDEX` (0 to completions-1) so it picks its slice.
- `completions: 10` with `parallelism: 3` runs three at a time until ten succeed.
- Work queue pattern: leave `completions` unset; Pods pull from a queue and the Job ends when one succeeds and all have exited.
- `podFailurePolicy` can fail the Job at once on a given exit code or ignore disruptions such as preemption.
@diagram layers
caption: Ten items, three at a time
layers:
  - {label: "Job", nodes: ["completions 10|parallelism 3|app"]}
  - {label: "Running now", nodes: ["index 0|processing|ok", "index 1|processing|ok", "index 2|processing|ok"]}
  - {label: "Waiting", nodes: ["index 3 to 9|queued|plain"]}
@h Indexed Job
```yaml title="indexed-job.yaml"
apiVersion: batch/v1
kind: Job
metadata:
  name: shard-process
spec:
  completionMode: Indexed
  completions: 10
  parallelism: 3
  backoffLimitPerIndex: 1
  maxFailedIndexes: 2
  podFailurePolicy:
    rules:
      - action: FailJob
        onExitCodes:
          operator: In
          values: [42]
      - action: Ignore
        onPodConditions:
          - type: DisruptionTarget
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: worker
          image: busybox:1.36
          command: ["sh", "-c", "echo processing shard $JOB_COMPLETION_INDEX"]
```
@check
How does a Pod know which slice to process? || In Indexed mode it reads the `JOB_COMPLETION_INDEX` environment variable.
@end

@concept CronJobs
@plain
A CronJob creates a Job on a schedule written in cron syntax.
@problem
Recurring tasks like backups or cleanups need a scheduler that is part of the cluster and not tied to one server.
@does
- `schedule` uses five-field cron, in the controller manager's time zone unless `timeZone` is set (stable since 1.27).
- `concurrencyPolicy`: `Allow` (default), `Forbid` skips if the last run is still going, `Replace` stops the old one.
- `startingDeadlineSeconds` lets a missed run start late; without it, a missed run is skipped.
- `successfulJobsHistoryLimit` and `failedJobsHistoryLimit` keep a few Jobs for debugging.
@diagram flow
caption: From schedule to Pod
nodes:
  - "CronJob|0 2 * * *|app"
  - "Job|created at 02 00|info"
  - "Pod|runs the task|ok"
@h Nightly backup
```yaml title="cronjob.yaml"
apiVersion: batch/v1
kind: CronJob
metadata:
  name: nightly-backup
spec:
  schedule: "0 2 * * *"
  timeZone: Etc/UTC
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 900
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 3
  jobTemplate:
    spec:
      backoffLimit: 2
      activeDeadlineSeconds: 3600
      ttlSecondsAfterFinished: 86400
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: backup
              image: ghcr.io/example/backup:2.1
              args: ["--target", "s3://backups/shop"]
```
@end

@concept Operating Jobs
@plain
Jobs are easy to write and hard to observe. Know the commands that show why they stall.
@problem
A CronJob that silently stopped producing Jobs is only noticed when the backup is needed.
@does
- Jobs are at-least-once. Your task must be idempotent because a Pod can run twice.
- Suspend a CronJob with `spec.suspend: true` during maintenance.
- Trigger a one-off run with `kubectl create job --from=cronjob/NAME`.
- A CronJob that missed more than 100 schedules stops and logs an error, which needs a fix and a manual run.
- Alert on `kube_job_failed` and on time since the last success (kube-state-metrics).
@diagram flow
caption: Investigating a failed Job
numbered: true
nodes:
  - "get job|conditions|info"
  - "get pods -l job-name|find the Pod|info"
  - "logs|read the error|info"
  - "Fix and rerun|from cronjob|ok"
@h Commands
```bash title="Run and inspect" lab
kubectl create job manual-backup --from=cronjob/nightly-backup
kubectl get jobs,pods -l job-name=manual-backup
kubectl logs job/manual-backup
kubectl patch cronjob nightly-backup -p '{"spec":{"suspend":true}}'
kubectl wait --for=condition=complete job/manual-backup --timeout=300s
```
:::warn
`Forbid` concurrency with a Job that hangs blocks all future runs. Always set `activeDeadlineSeconds`.
:::
@check
Why must Job code be idempotent? || Kubernetes guarantees at least once, not exactly once; retries or overlapping runs can repeat work.
@end

@concept Batch at scale with queues
@plain
For large batch loads, Kubernetes Jobs combine with queueing and quotas so one team cannot starve the rest.
@problem
Thousands of Jobs submitted together overwhelm the scheduler and autoscaler and block other workloads.
@does
- **Kueue** admits Jobs against quotas and queues them until capacity exists.
- Set `suspend: true` on Jobs so a queue controller starts them when ready.
- Use PriorityClasses so batch work yields to services via preemption.
- Run batch on a spot or preemptible node pool with a toleration so costs stay low.
- Prefer Argo Workflows, Tekton or Airflow when you need dependency graphs between steps.
@diagram flow
caption: Queue in front of the cluster
nodes:
  - "Jobs submitted|suspended|plain"
  - "Kueue queue|quota check|cp"
  - "Admitted|unsuspended|ok"
  - "Autoscaler adds nodes|if needed|info"
@h Suspended Job for a queue
```yaml title="queued-job.yaml"
apiVersion: batch/v1
kind: Job
metadata:
  name: nightly-report
  labels:
    kueue.x-k8s.io/queue-name: team-a
spec:
  suspend: true
  template:
    spec:
      restartPolicy: Never
      tolerations:
        - {key: workload, operator: Equal, value: batch, effect: NoSchedule}
      containers:
        - name: report
          image: busybox:1.36
          command: ["sh", "-c", "sleep 5"]
          resources:
            requests: {cpu: "1", memory: 512Mi}
```
@end
