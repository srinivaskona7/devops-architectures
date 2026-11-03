---
title: Jenkins architecture
minutes: 45
objectives:
  - Describe the controller and agent model and what each one does
  - Run Jenkins on Kubernetes with a persistent home volume
  - Trigger builds from webhooks and understand job types
---
Jenkins is the long-standing open source automation server. It is extremely flexible and widely deployed, and it needs more operating care than a hosted service.

@concept Controller and agents
@plain
The **controller** (formerly master) hosts the web UI, stores configuration and schedules builds. **Agents** are the machines or pods that actually run the build steps.
@problem
Running builds on the controller makes it slow and risky: a bad build could read credentials or crash the scheduler that every team depends on.
@does
- The controller keeps job definitions, build history, credentials and plugins in `JENKINS_HOME`.
- Agents connect to the controller using WebSocket or inbound TCP (JNLP) or are started over SSH.
- Set the controller to zero executors so builds never run on it.
- Labels on agents let a pipeline ask for `agent { label 'linux && docker' }`.
@diagram layers
caption: Jenkins components
layers:
  - {label: "Controller", nodes: ["Web UI and API|users and webhooks|cp", "Scheduler|queue and executors|cp", "JENKINS_HOME|config, jobs, credentials|db"]}
  - {label: "Agents", nodes: ["Linux agent|label linux|app", "Kubernetes pod agent|created per build|app", "Windows agent|label windows|app"]}
  - {label: "Targets", nodes: ["Registry|push images|ext", "EKS|deploy|env"]}
@h Controller with no executors
```bash title="Check nodes and executors via the API" lab nocheck
curl -s -u "$JENKINS_USER:$JENKINS_TOKEN" \
  "https://jenkins.example.com/computer/api/json?tree=computer[displayName,numExecutors,offline]"
```
@check
Why set the controller to zero executors? || Builds then cannot run on it, protecting its credentials and keeping the scheduler responsive.
@end

@concept Executors, queue and workspaces
@plain
An **executor** is one build slot on a node. The **queue** holds builds waiting for a free slot with a matching label. Each build gets a **workspace**, a directory where its files live.
@problem
Without these controls, builds fight for CPU and disk, or two builds overwrite each other's files.
@does
- Number of executors on a node is its parallel capacity. For container agents, usually one build per pod.
- The queue shows why a build waits, for example "waiting for next available executor".
- Workspaces are reused on static agents. Clean them (`cleanWs()`) to avoid stale files.
- Builds of the same job can be limited with `disableConcurrentBuilds()`.
@diagram flow
caption: A build moves through the scheduler
numbered: true
nodes:
  - "Trigger|webhook or timer|plain"
  - "Queue|waits for a matching label|warn"
  - "Executor|slot on an agent|app"
  - "Workspace|checkout and build|info"
  - "Result|stored in controller|ok"
@h Pipeline options for concurrency
```groovy title="Jenkinsfile fragment" nocheck
options {
  disableConcurrentBuilds()
  timeout(time: 30, unit: 'MINUTES')
  buildDiscarder(logRotator(numToKeepStr: '30'))
}
```
@end

@concept Job types
@plain
Jenkins offers freestyle jobs (configured in the UI), Pipeline jobs (a script), Multibranch pipelines (one job per branch or pull request found in a repository) and organisation folders (scan a whole GitHub or GitLab organisation).
@problem
Freestyle jobs hold their logic in the UI, which cannot be reviewed or versioned. Teams need one pipeline definition that applies to every branch automatically.
@does
- **Pipeline** jobs run a Jenkinsfile, stored in the repository or pasted in the UI.
- **Multibranch** scans a repository, creates a sub-job for each branch with a Jenkinsfile and removes it when the branch is deleted.
- **Organisation folder** discovers repositories in an organisation and builds each.
- Prefer multibranch or organisation folders defined as code with the Job DSL or JCasC.
@diagram cmp
caption: Which job type to use
cards:
  - {h: "Freestyle", kind: bad, items: ["Logic in the UI", "Hard to version", "Avoid for new work"]}
  - {h: "Pipeline", kind: info, items: ["Jenkinsfile script", "Single branch", "Good for utilities"]}
  - {h: "Multibranch", kind: ok, items: ["Builds every branch and PR", "Auto-clean on delete", "Default for services"]}
@h Job DSL for a multibranch job
```groovy title="Job DSL seed script" nocheck
multibranchPipelineJob('shop') {
  branchSources {
    github {
      id('shop-source')
      repoOwner('my-org')
      repository('shop')
      scanCredentialsId('github-app')
    }
  }
  orphanedItemStrategy {
    discardOldItems { numToKeep(10) }
  }
}
```
@check
What does a multibranch pipeline do when a branch is deleted? || It removes the branch job according to the orphaned item strategy.
@end

@concept Triggering builds
@plain
Builds start by webhook from Git, by a timer (cron syntax), by another job, or by a person. Webhooks give the fastest and cheapest result.
@problem
Polling the repository every minute from hundreds of jobs overloads both Jenkins and the Git server, and still adds delay.
@does
- GitHub, GitLab and Bitbucket plugins expose endpoints such as `/github-webhook/` or `/multibranch-webhook-trigger/invoke`.
- Webhook endpoints must be reachable from the Git server, so protect them with a shared secret or a reverse proxy.
- `triggers { cron('H 2 * * 1-5') }` uses `H` to spread load by hashing the job name.
- Use `pollSCM` only as a fallback.
@diagram seq
caption: Webhook starts a build
actors: ["Git server|GitHub|ext", "Jenkins|controller|cp", "Agent|build pod|app"]
steps:
  - "0>1: push event webhook | req"
  - "note 1..1: scan repo, find change"
  - "1>2: schedule build | req"
  - "2>1: result | resp"
  - "1>0: commit status | resp"
@h Cron with spread
```groovy title="Trigger section" nocheck
triggers {
  cron('H 2 * * 1-5')      // nightly, minute chosen by hash
}
```
:::tip
Always use `H` instead of a fixed minute such as `0`. Otherwise every nightly job starts at the same instant.
:::
@end

@concept Installing on Kubernetes
@plain
The official Helm chart deploys the controller as a StatefulSet-like workload with a persistent volume for `JENKINS_HOME`. Agents are created as separate pods by the Kubernetes plugin.
@problem
Hand-built Jenkins servers are snowflakes that nobody can recreate. Kubernetes with declarative configuration makes it repeatable.
@does
- The controller needs a PersistentVolume (EBS on EKS). It is a single instance, not horizontally scalable.
- Configuration is applied by JCasC (a ConfigMap) and plugins are listed in the chart values.
- An Ingress or load balancer with TLS exposes the UI. Agents talk back to the controller service inside the cluster.
- Check the Jenkins chart documentation for current values.
@diagram layers
caption: Jenkins on EKS
layers:
  - {label: "Edge", nodes: ["Ingress with TLS|jenkins.example.com|ext"]}
  - {label: "Namespace jenkins", nodes: ["Controller pod|one replica|cp", "ConfigMap|JCasC|info", "PVC on EBS|JENKINS_HOME|db"]}
  - {label: "Namespace jenkins-agents", nodes: ["Build pod|created per build|app", "Build pod|created per build|app"]}
@h Helm install
```bash title="Install the chart" lab
helm repo add jenkins https://charts.jenkins.io
helm repo update
helm install jenkins jenkins/jenkins --namespace jenkins --create-namespace \
  --values jenkins-values.yaml
kubectl -n jenkins get pods
kubectl -n jenkins get secret jenkins -o jsonpath='{.data.jenkins-admin-password}' | base64 -d
```
```yaml title="jenkins-values.yaml (excerpt)"
controller:
  numExecutors: 0
  resources:
    requests: {cpu: "1", memory: 2Gi}
    limits: {memory: 4Gi}
  installPlugins:
    - kubernetes
    - workflow-aggregator
    - git
    - configuration-as-code
    - credentials-binding
persistence:
  enabled: true
  size: 50Gi
  storageClass: gp3
```
@check
Can you run two active Jenkins controller replicas for scale? || No. The open source controller is a single active instance. Scale by adding agents or splitting into several controllers.
@end

@concept Authentication and authorization
@plain
Jenkins needs a **security realm** (who are you: local users, LDAP, OIDC or SAML) and an **authorization strategy** (what may you do).
@problem
An open Jenkins is a remote code execution service. Anyone who can configure a job can run commands on agents and read credentials.
@does
- Use OIDC or SAML single sign-on with your identity provider, and map groups to roles.
- Use the Role-Based Strategy or Matrix Authorization plugin. Grant the Overall/Administer permission to very few people.
- Disable anonymous read. Use API tokens, never passwords, for automation.
- Folder-level permissions let teams manage their own jobs only.
@diagram flow
caption: Request path for a signed-in user
nodes:
  - "Browser|user|plain"
  - "OIDC provider|identity|ext"
  - "Jenkins realm|group claims|cp"
  - "Role strategy|permissions per folder|ok"
@h JCasC security block
```yaml title="Security in configuration as code" nocheck
jenkins:
  securityRealm:
    oic:
      clientId: ${OIDC_CLIENT_ID}
      clientSecret: ${OIDC_CLIENT_SECRET}
      wellKnownOpenIDConfigurationUrl: https://idp.example.com/.well-known/openid-configuration
  authorizationStrategy:
    roleBased:
      roles:
        global:
          - name: admin
            permissions: ["Overall/Administer"]
            entries: [{group: jenkins-admins}]
```
:::note
Exact plugin keys differ by plugin version. Check the plugin documentation page and the JCasC reference at /configuration-as-code on your controller.
:::
@end

@concept Pipeline execution and durability
@plain
A Pipeline run is executed by the Groovy CPS engine on the controller, while steps such as `sh` run on agents. State is saved to disk so a run can survive a controller restart.
@problem
Heavy Groovy logic in a Jenkinsfile runs on the controller, not the agent, and can slow down every team's builds. Long runs should survive restarts.
@does
- Keep Groovy light. Do real work in `sh` steps, scripts or containers.
- Non-serialisable objects cannot be held across steps in CPS code, and methods annotated `@NonCPS` run without CPS safeguards.
- Durability settings trade speed for safety. Check the current docs for `PERFORMANCE_OPTIMIZED` and `MAX_SURVIVABILITY`.
- Resume works for steps like `sh` that run on the agent while the controller restarts.
@diagram flow
caption: Where each part runs
nodes:
  - "Groovy logic|controller CPS engine|cp"
  - "node block|reserves an agent executor|info"
  - "sh step|agent shell process|app"
  - "Results|written back to controller|ok"
@h Keep logic on the agent
```groovy title="Thin Groovy, real work in a script" nocheck
stage('Test') {
  steps {
    sh './ci/run-tests.sh'      // heavy work runs on the agent, not in Groovy
  }
}
```
@check
Where does Groovy pipeline code execute? || On the controller, which is why heavy computation there harms everyone.
@end
