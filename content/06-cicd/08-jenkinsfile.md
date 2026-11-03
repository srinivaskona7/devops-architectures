---
title: Jenkinsfile declarative and scripted
minutes: 50
objectives:
  - Write a declarative Jenkinsfile with stages, parallel branches and conditions
  - Use post actions, parameters, options and input for gated deploys
  - Know when scripted pipeline syntax is still needed
---
The Jenkinsfile is the pipeline as code for Jenkins. Declarative syntax is the recommended default.

@concept Declarative pipeline structure
@plain
A declarative Jenkinsfile has a fixed shape: `pipeline { agent ... stages { stage ... steps ... } post ... }`. The structure is validated before the build starts.
@problem
Free-form scripts make pipelines inconsistent between teams and fail late. Declarative syntax gives a predictable layout that can be linted and understood by anyone.
@does
- `agent` says where to run. `stages` holds ordered `stage` blocks. `steps` lists the actions.
- `environment`, `options`, `parameters`, `triggers`, `tools` configure the run.
- `post` runs after stages depending on result.
- Syntax errors are reported at start, before any step runs.
@diagram layers
caption: Shape of a declarative pipeline
layers:
  - {label: "Top level", nodes: ["agent|where it runs|cp", "environment|variables|cp", "options|timeout, retention|cp"]}
  - {label: "stages", nodes: ["Build|stage|app", "Test|stage|app", "Deploy|stage|env"]}
  - {label: "post", nodes: ["always|cleanup|info", "failure|notify|bad", "success|promote|ok"]}
@h Complete example
```groovy title="Jenkinsfile" nocheck
pipeline {
  agent { label 'linux' }
  options {
    timeout(time: 30, unit: 'MINUTES')
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30'))
  }
  environment {
    IMAGE = "111122223333.dkr.ecr.eu-west-1.amazonaws.com/shop"
    TAG   = "${env.GIT_COMMIT.take(7)}"
  }
  stages {
    stage('Test') {
      steps { sh 'make test' }
    }
    stage('Build') {
      steps { sh 'docker build -t $IMAGE:$TAG .' }
    }
  }
  post {
    always  { cleanWs() }
    failure { echo 'build failed' }
  }
}
```
@check
When is a declarative Jenkinsfile validated? || Before the run starts, so structural errors fail immediately.
@end

@concept Stages, parallel and when
@plain
Stages run in order. `parallel` runs several branches at once, and `when` decides whether a stage runs at all.
@problem
Serial pipelines are slow, and running a deploy on every feature branch is unwanted.
@does
- `parallel { stage('Unit') {...} stage('Lint') {...} }` runs branches on separate executors.
- `failFast true` stops the others as soon as one fails.
- `when { branch 'main' }`, `when { changeRequest() }`, `when { tag 'v*' }`, `when { expression { ... } }` and `anyOf`, `allOf`, `not` combine conditions.
- `beforeAgent true` avoids allocating an agent for a stage that will be skipped.
@diagram flow
caption: Parallel checks, then conditional deploy
nodes:
  - "Checkout|stage|plain"
  - "Unit and Lint|parallel|app"
  - "Build image|stage|info"
  - "Deploy|only on main|ok"
@h Parallel and when
```groovy title="Fragment" nocheck
stage('Checks') {
  failFast true
  parallel {
    stage('Unit') { steps { sh 'make unit' } }
    stage('Lint') { steps { sh 'make lint' } }
  }
}
stage('Deploy') {
  when { branch 'main'; beforeAgent true }
  steps { sh './ci/deploy.sh staging' }
}
```
@check
What does beforeAgent do? || It evaluates the when condition before allocating an agent, saving resources for skipped stages.
@end

@concept Parameters, input and approvals
@plain
`parameters` lets a person fill in values when starting a run. The `input` step pauses the pipeline until someone approves, optionally with a value.
@problem
Production deploys often need a human check or a choice such as which environment, without leaving a build agent reserved.
@does
- Types include `string`, `choice`, `booleanParam` and `password` (use credentials instead for secrets).
- `input` inside a stage with `agent none` waits without holding an executor. Use `submitter` to limit who may approve.
- Always wrap waits in `timeout` so abandoned approvals expire.
@diagram seq
caption: Approval gate in a pipeline
actors: ["Pipeline|build|app", "Jenkins UI|input step|cp", "Approver|human|ext"]
steps:
  - "0>1: pause at input | req"
  - "1>2: approval requested | req"
  - "2>1: approve | resp"
  - "1>0: continue to deploy | resp"
@h Gate with a timeout
```groovy title="Approval before production" nocheck
stage('Approve') {
  agent none
  steps {
    timeout(time: 1, unit: 'HOURS') {
      input message: 'Deploy to production?', submitter: 'release-managers'
    }
  }
}
```
@end

@concept Post actions and notifications
@plain
The `post` section runs after a stage or the whole pipeline, depending on outcome: `always`, `success`, `failure`, `unstable`, `aborted`, `changed`, `cleanup`.
@problem
Cleanup and notification code duplicated at the end of every stage is skipped when something fails in the middle.
@does
- `always` publishes test reports and archives logs.
- `failure` notifies chat or opens an issue. `changed` fires when the status differs from the previous run.
- `cleanup` runs last, after all other post conditions, even if they fail.
- `junit`, `archiveArtifacts` and `recordIssues` store results.
@diagram cmp
caption: Which post condition for what
cards:
  - {h: "always", kind: info, items: ["junit reports", "cleanWs()"]}
  - {h: "failure", kind: bad, items: ["Slack message", "Link to log"]}
  - {h: "success", kind: ok, items: ["Tag release", "Trigger deploy job"]}
  - {h: "cleanup", kind: warn, items: ["Runs last", "Remove temp resources"]}
@h Post block
```groovy title="Reports and notification" nocheck
post {
  always {
    junit allowEmptyResults: true, testResults: '**/target/surefire-reports/*.xml'
    archiveArtifacts artifacts: 'build/**', allowEmptyArchive: true
  }
  failure {
    slackSend channel: '#ci', message: "FAILED ${env.JOB_NAME} #${env.BUILD_NUMBER} ${env.BUILD_URL}"
  }
  cleanup { cleanWs() }
}
```
@check
Which post condition runs even when other post conditions fail? || cleanup.
@end

@concept Scripted pipeline
@plain
Scripted pipeline is plain Groovy with `node { stage(...) { ... } }`. It has no fixed structure and gives full programming freedom.
@problem
Some logic does not fit declarative blocks: loops that create stages dynamically, complex try and catch flows, or computed matrices.
@does
- Use `node('label') { ... }` to get an agent and `stage` as a labelled block.
- Use normal Groovy `for`, `if`, `try/catch/finally`.
- You can embed scripted code in declarative with a `script { }` block. Keep those blocks short.
- Declarative is easier to maintain and gets better tooling. Use scripted for libraries and rare dynamic cases.
@diagram cmp
caption: Declarative versus scripted
cards:
  - {h: "Declarative", kind: ok, items: ["Fixed structure", "Validated early", "Default choice"]}
  - {h: "Scripted", kind: warn, items: ["Full Groovy", "Dynamic stages", "Harder to read and lint"]}
@h Dynamic parallel stages
```groovy title="Scripted pipeline generating a stage per service" nocheck
def services = ['orders', 'billing', 'catalog']
def branches = services.collectEntries { svc ->
  [(svc): {
    stage("Test ${svc}") {
      sh "make -C services/${svc} test"
    }
  }]
}
node('linux') {
  checkout scm
  parallel branches
}
```
@end

@concept Stash, artifacts and test reports
@plain
`stash` saves files from one stage for use in another stage on a different agent. `archiveArtifacts` keeps files with the build. `junit` publishes test results to the UI.
@problem
Stages that run on different agents do not share a workspace, so build outputs vanish between them.
@does
- `stash name: 'bin', includes: 'build/**'` then `unstash 'bin'` later. Stashes are meant for small files and last for the build only.
- `archiveArtifacts` makes files downloadable from the build page. Large artifacts belong in a repository such as S3 or an OCI registry.
- `junit` gives trends and failing test lists.
@diagram flow
caption: Passing files between agents
nodes:
  - "Build stage|agent A|app"
  - "stash bin|small files|info"
  - "Controller storage|for this build|cp"
  - "Test stage|agent B unstash|ok"
@h Stash and unstash
```groovy title="Move build output to another agent" nocheck
stage('Build') {
  agent { label 'linux' }
  steps {
    sh 'make build'
    stash name: 'bin', includes: 'build/**'
  }
}
stage('Smoke') {
  agent { label 'linux' }
  steps {
    unstash 'bin'
    sh './build/shop --version'
  }
}
```
@check
Why not stash a multi-gigabyte image? || Stashes travel through the controller and are meant for small files. Push big artifacts to a registry or object storage.
@end

@concept Linting and testing Jenkinsfiles
@plain
You can validate a Jenkinsfile without running it, and replay or test pipeline code against a real controller.
@problem
Finding syntax mistakes by pushing and waiting is slow, and a broken Jenkinsfile on main blocks the whole team.
@does
- The declarative linter is available over HTTP at `/pipeline-model-converter/validate` and from the CLI.
- **Replay** lets you edit and rerun the last build's script from the UI without committing.
- Shared library code can be unit tested with the JenkinsPipelineUnit framework.
- Run the linter as a pre-commit hook or a CI step in the repository.
@diagram flow
caption: Catch errors before they reach main
nodes:
  - "Edit Jenkinsfile|local|plain"
  - "Linter|declarative validate|info"
  - "Replay|try variants in UI|warn"
  - "Commit|merge|ok"
@h Linter call
```bash title="Validate a Jenkinsfile" lab nocheck
curl -s -X POST -u "$JENKINS_USER:$JENKINS_TOKEN" \
  -F "jenkinsfile=<Jenkinsfile" \
  https://jenkins.example.com/pipeline-model-converter/validate
```
:::tip
A response of "Jenkinsfile successfully validated." means the declarative structure is fine. It does not check your shell commands.
:::
@end
