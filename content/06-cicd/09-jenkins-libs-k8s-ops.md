---
title: Jenkins libraries, Kubernetes agents and operations
minutes: 50
objectives:
  - Share pipeline code with Jenkins shared libraries
  - Run builds in Kubernetes pod agents with safe credentials handling
  - Operate Jenkins with JCasC, plugin hygiene, scaling and backups
---
This section turns a Jenkins install into a maintainable platform rather than a pet server.

@concept Shared libraries
@plain
A shared library is a Git repository of Groovy code that pipelines import. It holds common steps so teams do not copy pipeline logic.
@problem
Fifty Jenkinsfiles each containing the same 80 lines of Docker and deployment code mean fifty fixes whenever something changes.
@does
- Layout: `vars/` contains global steps (`vars/buildImage.groovy` becomes `buildImage()`), `src/` contains classes, `resources/` holds files.
- Configure the library name and default version once in Jenkins (global or folder level) and import with `@Library('platform-lib@v2') _`.
- Pin to a tag to control rollout. Trusted global libraries run outside the Groovy sandbox, so restrict who can edit them.
@diagram layers
caption: Library layout and use
layers:
  - {label: "Library repo", nodes: ["vars/buildImage.groovy|global step|app", "src/org/acme/Util.groovy|classes|app", "resources/|templates, scripts|info"]}
  - {label: "Jenkinsfile", nodes: ["@Library platform-lib at v2|import|cp", "buildImage name: shop|call|ok"]}
@h Define and use
```groovy title="vars/buildImage.groovy" nocheck
def call(Map cfg) {
  String tag = cfg.tag ?: env.GIT_COMMIT.take(7)
  sh "docker build -t ${cfg.registry}/${cfg.name}:${tag} ."
  sh "docker push ${cfg.registry}/${cfg.name}:${tag}"
  return tag
}
```
```groovy title="Jenkinsfile using it" nocheck
@Library('platform-lib@v2') _
pipeline {
  agent any
  stages {
    stage('Image') {
      steps {
        script { buildImage(registry: '111122223333.dkr.ecr.eu-west-1.amazonaws.com', name: 'shop') }
      }
    }
  }
}
```
@check
Where do global steps live in a library? || In the vars directory, one file per step with a call method.
@end

@concept Kubernetes pod agents
@plain
With the Kubernetes plugin, each build creates a pod with the containers it needs, runs the steps and deletes the pod. A pod template describes the containers.
@problem
Static agents sit idle, drift from their original state and have one fixed toolset. Builds of different stacks need different images.
@does
- A pod has a `jnlp` container (the agent) plus tool containers such as `maven`, `kaniko` or `kubectl`.
- `container('name') { sh '...' }` runs a step inside the chosen container. All containers share the workspace volume.
- Resource requests set pod size, and the cluster autoscaler adds nodes as builds queue.
- Pods are clean every time, which removes workspace cleanup concerns.
@diagram flow
caption: Build pod lifecycle
numbered: true
nodes:
  - "Build starts|needs label k8s|plain"
  - "Plugin creates pod|API call to cluster|cp"
  - "Steps run|in chosen containers|app"
  - "Pod deleted|no leftovers|ok"
@h Pod template in a Jenkinsfile
```groovy title="Declarative agent with inline pod YAML" nocheck
pipeline {
  agent {
    kubernetes {
      yaml '''
        apiVersion: v1
        kind: Pod
        spec:
          containers:
            - name: golang
              image: golang:1.23
              command: ["sleep"]
              args: ["infinity"]
              resources:
                requests: {cpu: "1", memory: 2Gi}
            - name: kubectl
              image: bitnami/kubectl:latest
              command: ["sleep"]
              args: ["infinity"]
      '''
    }
  }
  stages {
    stage('Test') {
      steps { container('golang') { sh 'go test ./...' } }
    }
  }
}
```
:::note
Pin real image versions in production rather than latest.
:::
@check
How do you run a step in a specific tool container of the pod? || Wrap it in container('name') { ... }.
@end

@concept Credentials in Jenkins
@plain
The credentials store keeps secrets (text, username and password, SSH keys, files, certificates) encrypted on the controller. Pipelines request them by ID and the plugin masks them in logs.
@problem
Passwords typed into Jenkinsfiles end up in Git, and secrets echoed into logs are visible to everyone who can read the build.
@does
- `withCredentials([string(credentialsId: 'x', variable: 'TOKEN')]) { ... }` exposes the secret only inside the block, masked in the log.
- Scope credentials to a folder so only that team's jobs can use them.
- Prefer external stores (HashiCorp Vault, AWS Secrets Manager plugins) and short-lived cloud credentials such as IAM roles for service accounts on the agent pod.
- Never use Groovy string interpolation with secrets: `sh "echo $TOKEN"` leaks it to process arguments. Use single quotes `sh 'echo $TOKEN'`.
@diagram flow
caption: Secret scope during a build
nodes:
  - "Credentials store|encrypted, folder scoped|db"
  - "withCredentials|temporary variable|cp"
  - "sh step|single quoted, masked|app"
  - "Block ends|variable gone|ok"
@h Using a credential safely
```groovy title="Token inside a block" nocheck
withCredentials([string(credentialsId: 'github-token', variable: 'GH_TOKEN')]) {
  sh 'gh release create "$TAG" --notes "Automated"'   // single quotes: the shell reads the variable
}
```
@check
Why use single quotes with secrets in sh? || Groovy would otherwise expand the secret into the command text before the shell runs, exposing it in logs and processes.
@end

@concept Configuration as code
@plain
The Configuration as Code plugin (JCasC) describes the whole controller configuration in YAML: security, agents, credentials, tools and global settings.
@problem
Click-configured controllers cannot be reviewed or rebuilt. A lost volume means weeks of recreation.
@does
- The YAML file path comes from `CASC_JENKINS_CONFIG`; the Helm chart mounts it from a ConfigMap.
- Secrets are referenced as `${SECRET_NAME}` and filled from environment variables or mounted files, never written into the YAML.
- On reload, JCasC makes the controller match the file. Validate before applying through the UI check function.
- Job definitions are created with the Job DSL plugin through the `jobs` section.
@diagram flow
caption: Rebuildable controller
nodes:
  - "Git repo|jenkins.yaml|app"
  - "ConfigMap|mounted in pod|info"
  - "JCasC plugin|applies on start|cp"
  - "Controller|matches the file|ok"
@h JCasC example
```yaml title="jenkins.yaml"
jenkins:
  systemMessage: "Managed by configuration as code"
  numExecutors: 0
  clouds:
    - kubernetes:
        name: eks
        namespace: jenkins-agents
        jenkinsUrl: http://jenkins.jenkins.svc:8080
        jenkinsTunnel: jenkins-agent.jenkins.svc:50000
unclassified:
  location:
    url: https://jenkins.example.com/
jobs:
  - script: >
      multibranchPipelineJob('shop') {
        branchSources { github { id('shop'); repoOwner('my-org'); repository('shop') } }
      }
```
@check
Where do secrets in JCasC come from? || Environment variables or files mounted from a Kubernetes secret, referenced as variables in the YAML.
@end

@concept Plugin hygiene
@plain
Plugins add features and are also the main source of Jenkins security advisories. Keeping a short, pinned, regularly updated list is core maintenance.
@problem
Hundreds of unreviewed plugins create upgrade conflicts, abandoned code and known vulnerabilities.
@does
- Install only what you need and remove unused ones. Fewer plugins means fewer advisories.
- Declare plugins in a file (`plugins.txt` or chart `installPlugins`) with pinned versions, and bake them into a custom controller image.
- Read the security advisories page and update the controller and plugins on a regular cadence, with a staging controller to test first.
- Prefer plugins marked as maintained and avoid ones with no release for years.
@diagram flow
caption: Controlled plugin updates
nodes:
  - "plugins.txt|pinned versions|app"
  - "Build image|jenkins-plugin-cli|info"
  - "Staging controller|smoke jobs|warn"
  - "Production|roll out|ok"
@h Pin and install
```text title="plugins.txt"
kubernetes:4301.v1234
workflow-aggregator:600.vabcd
git:5.7.0
configuration-as-code:1900.v1234
credentials-binding:687.v1234
```
```dockerfile title="Custom controller image" nocheck
FROM jenkins/jenkins:lts-jdk17
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt
```
:::note
The versions in plugins.txt above are placeholders. Take real versions from the update centre.
:::
@end

@concept Scaling and performance
@plain
One controller has limits on memory, build history and concurrent builds. You scale by moving work to agents, reducing controller load, and if needed splitting into several controllers.
@problem
A single overloaded controller slows or freezes every team, and its single point of failure affects all deploys.
@does
- Zero executors on the controller; autoscaling Kubernetes agents.
- Limit build history (`buildDiscarder`), use external log storage where supported, and avoid heavy Groovy and polling.
- Give the JVM sensible heap and use fast storage. Monitor with the Prometheus metrics plugin: queue length, executor use, and GC.
- Beyond a limit, split by business unit into several controllers, optionally with a central management layer. Check current CloudBees or community guidance for sizing.
@diagram cmp
caption: Scaling levers
cards:
  - {h: "Cheap", kind: ok, items: ["Zero executors on controller", "Discard old builds", "Webhooks not polling"]}
  - {h: "Medium", kind: warn, items: ["Autoscaled pod agents", "Tune JVM and disk", "Metrics and alerts"]}
  - {h: "Large", kind: bad, items: ["Several controllers by team", "More platform effort"]}
@h Metrics
```bash title="Watch queue and executors" lab nocheck
curl -s -u "$JENKINS_USER:$JENKINS_TOKEN" https://jenkins.example.com/prometheus/ \
  | grep -E 'jenkins_queue_size_value|jenkins_executor_in_use_value'
```
@check
What is the first scaling step for Jenkins? || Move all builds to agents and reduce controller load, before considering more controllers.
@end

@concept Backup and disaster recovery
@plain
The controller keeps state in `JENKINS_HOME`. A backup plan means you can restore job history, credentials and configuration after a failure.
@problem
Disks fail and upgrades go wrong. Without backups and a rehearsed restore, an outage becomes data loss.
@does
- Config in Git (JCasC, Job DSL, Jenkinsfiles) is the primary recovery path. What remains is history and secrets.
- Snapshot the EBS volume on a schedule (AWS Backup or the EBS CSI VolumeSnapshot), and back up the credentials encryption keys in `secrets/`.
- Test restores into a scratch namespace regularly.
- Stateless approach: treat build history as disposable, keep artifacts and test results in external systems.
@diagram flow
caption: Recovery layers
nodes:
  - "Git|JCasC and Jenkinsfiles|ok"
  - "Volume snapshot|EBS on schedule|info"
  - "Secrets backup|encryption keys|warn"
  - "Restore test|quarterly|app"
@h Volume snapshot
```yaml title="VolumeSnapshot of the Jenkins home" nocheck
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata: {name: jenkins-home-nightly, namespace: jenkins}
spec:
  volumeSnapshotClassName: ebs-csi
  source:
    persistentVolumeClaimName: jenkins
```
:::warn
A backup you have never restored is a hope, not a backup. Schedule a restore drill.
:::
@end
