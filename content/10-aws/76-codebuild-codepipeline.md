---
title: CodeBuild and CodePipeline
minutes: 50
objectives:
  - Write a buildspec and run CodeBuild with caching, secrets and a least-privilege role
  - Model a release flow in CodePipeline with stages, approvals and cross-account deployment
  - Trigger pipelines from source events and troubleshoot failures
---
CodeBuild is a managed build service. CodePipeline orchestrates stages from source to production. Together they give an AWS-native CI/CD path.

@concept CodeBuild projects
@plain
A **CodeBuild project** runs commands from a `buildspec` in a fresh container and bills by the build minute.
@problem
Self-hosted CI servers need patching, scaling and idle capacity.
@does
- Choose a compute type, an AWS-provided or custom image, and a service role.
- Source: CodeConnections (GitHub, Bitbucket, GitLab), CodeCommit, S3.
- Outputs: artifacts to S3, test and coverage reports, logs in CloudWatch.
- Build in a VPC to reach private resources; compute can be on-demand EC2 or Lambda for short builds; check the current compute options.
- Also runs GitHub Actions self-hosted runners in recent versions; check the current docs.
@diagram flow
caption: A build
numbered: true
nodes:
  - "Source|git commit|ext"
  - "CodeBuild|container runs buildspec|cp"
  - "Artifacts|S3|ok"
  - "Reports and logs|CloudWatch|info"
@h Project in Terraform
```hcl title="codebuild.tf"
resource "aws_codebuild_project" "app" {
  name         = "app-build"
  service_role = aws_iam_role.codebuild.arn
  artifacts {
    type = "CODEPIPELINE"
  }
  environment {
    compute_type    = "BUILD_GENERAL1_SMALL"
    image           = "aws/codebuild/amazonlinux2-x86_64-standard:5.0"
    type            = "LINUX_CONTAINER"
    privileged_mode = true
  }
  source {
    type = "CODEPIPELINE"
  }
}
```
:::note
Privileged mode is needed only to run Docker inside the build. Leave it off otherwise.
:::
@check
How is CodeBuild billed? || By build minutes at the chosen compute size.
@end

@concept The buildspec
@plain
`buildspec.yml` defines phases, environment variables, artifacts and cache.
@problem
Builds must be repeatable and versioned alongside the code.
@does
- Phases: `install`, `pre_build`, `build`, `post_build`; a failing phase stops the build (post_build still runs).
- `env.parameter-store` and `env.secrets-manager` inject secrets at runtime without exposing them in the project.
- `cache` paths (S3 or local) speed up dependency downloads.
- `reports` upload JUnit or coverage data.
@diagram flow
caption: Phases
nodes:
  - "install|tools|info"
  - "pre_build|login and tests|info"
  - "build|compile and package|app"
  - "post_build|push and notify|ok"
@h Example
```yaml title="buildspec.yml"
version: 0.2
env:
  parameter-store:
    NPM_TOKEN: /ci/npm-token
phases:
  install:
    runtime-versions:
      nodejs: 20
  pre_build:
    commands:
      - npm ci
      - npm test
  build:
    commands:
      - npm run build
artifacts:
  files:
    - "dist/**/*"
cache:
  paths:
    - node_modules/**/*
reports:
  unit:
    files:
      - "junit.xml"
    file-format: JUNITXML
```
@check
Which phase still runs after a failed build phase? || post_build.
@end

@concept Building and pushing container images
@plain
CodeBuild commonly builds a Docker image and pushes it to ECR with an immutable tag.
@problem
Images pushed with a mutable `latest` tag cannot be traced or rolled back.
@does
- Tag with the commit SHA from `CODEBUILD_RESOLVED_SOURCE_VERSION`.
- Authenticate with `aws ecr get-login-password`.
- Scan on push in ECR and enable immutable tags.
- Output an `imagedefinitions.json` file so CodePipeline can deploy to ECS.
@diagram flow
caption: Image build
nodes:
  - "Dockerfile|app|app"
  - "CodeBuild|docker build|cp"
  - "ECR|tag by commit|ok"
  - "ECS or EKS|deploy|info"
@h Commands
```bash title="Build and push" nocheck
TAG=${CODEBUILD_RESOLVED_SOURCE_VERSION:0:8}
aws ecr get-login-password | docker login --username AWS --password-stdin 111122223333.dkr.ecr.eu-west-1.amazonaws.com
docker build -t 111122223333.dkr.ecr.eu-west-1.amazonaws.com/web:$TAG .
docker push 111122223333.dkr.ecr.eu-west-1.amazonaws.com/web:$TAG
printf '[{"name":"web","imageUri":"%s"}]' "111122223333.dkr.ecr.eu-west-1.amazonaws.com/web:$TAG" > imagedefinitions.json
```
@end

@concept CodePipeline stages and actions
@plain
A **pipeline** is a series of **stages**, each with **actions** (source, build, test, approval, deploy, invoke) that pass **artifacts** forward.
@problem
Releases need a visible, gated, auditable path from commit to production.
@does
- V2 pipelines support variables, triggers with Git tag and branch filters, and stage-level conditions; check the current features.
- Actions in a stage can run in parallel using `runOrder`.
- Manual approval actions notify through SNS.
- Artifacts are stored in an S3 artifact bucket, encrypted with KMS.
@diagram flow
caption: Release pipeline
numbered: true
nodes:
  - "Source|GitHub main|ext"
  - "Build|CodeBuild|cp"
  - "Staging deploy|auto|app"
  - "Approve|human gate|warn"
  - "Production deploy|CodeDeploy or CloudFormation|ok"
@h Pipeline skeleton
```hcl title="pipeline.tf"
resource "aws_codepipeline" "app" {
  name          = "app"
  role_arn      = aws_iam_role.pipeline.arn
  pipeline_type = "V2"
  artifact_store {
    location = aws_s3_bucket.artifacts.bucket
    type     = "S3"
  }
  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeStarSourceConnection"
      version          = "1"
      output_artifacts = ["src"]
      configuration = {
        ConnectionArn    = aws_codestarconnections_connection.github.arn
        FullRepositoryId = "org/app"
        BranchName       = "main"
      }
    }
  }
  stage {
    name = "Build"
    action {
      name             = "Build"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      input_artifacts  = ["src"]
      output_artifacts = ["build"]
      configuration = {
        ProjectName = aws_codebuild_project.app.name
      }
    }
  }
}
```
@check
How are artifacts passed between stages? || Through an encrypted S3 artifact store.
@end

@concept Cross-account and cross-Region deployment
@plain
Pipelines usually live in a tooling account and deploy into workload accounts by assuming roles there.
@problem
Giving every workload account its own pipeline is expensive, and shared admin credentials are risky.
@does
- Artifact bucket uses a customer managed KMS key whose policy allows the target account roles.
- The action's `role_arn` is a deploy role in the target account that trusts the pipeline role.
- Keep the deployment role scoped to what the stage deploys.
- Cross-Region pipelines need an artifact bucket in each Region.
@diagram flow
caption: Tooling account to workload account
nodes:
  - "Tooling account|pipeline and artifacts|cp"
  - "AssumeRole|deploy role|warn"
  - "Prod account|CloudFormation, ECS|ok"
@h Trust policy for the deploy role
```json title="deploy-role-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"AWS": "arn:aws:iam::222233334444:role/pipeline-role"},
    "Action": "sts:AssumeRole"
  }]
}
```
@end

@concept Triggers, approvals and notifications
@plain
Pipelines start on source changes and can pause for approval, with events sent to chat or email.
@problem
Unwatched pipelines fail silently and ungated ones deploy mistakes straight to production.
@does
- Triggers filter by branch, tag and file paths (V2).
- Approval actions can include a URL and comment; only IAM principals with the approval permission can respond.
- Notification rules send pipeline events to SNS or AWS Chatbot.
- EventBridge pipeline execution state change events allow custom automation.
@diagram flow
caption: Notify on failure
nodes:
  - "Pipeline|state change|cp"
  - "EventBridge|rule FAILED|info"
  - "SNS or Chatbot|message|ok"
@h Rule
```hcl title="notify.tf"
resource "aws_cloudwatch_event_rule" "pipeline_failed" {
  name = "pipeline-failed"
  event_pattern = jsonencode({
    source        = ["aws.codepipeline"]
    "detail-type" = ["CodePipeline Pipeline Execution State Change"]
    detail        = { state = ["FAILED"] }
  })
}
```
@check
Who can approve a manual approval action? || Principals whose IAM policy allows codepipeline:PutApprovalResult on it.
@end

@concept Troubleshooting builds and pipelines
@plain
Failures cluster around permissions, missing artifacts, network access and buildspec errors.
@problem
Pipelines fail with terse messages that hide the actual cause.
@does
- `AccessDenied` on S3 or KMS: the service role or the artifact bucket key policy.
- `YAML_FILE_ERROR`: buildspec syntax error; lint locally.
- Build cannot reach the internet in a VPC: needs NAT or endpoints.
- Docker rate limit pulling base images: use ECR pull-through cache.
- Use the action's execution details and the CodeBuild logs; retry only the failed stage when safe.
@diagram flow
caption: Triage
numbered: true
nodes:
  - "Stage failed|which action|warn"
  - "Build logs|CloudWatch|info"
  - "Role and key policy|IAM and KMS|cp"
  - "Network|NAT or endpoints|env"
@h Fetch last build log
```bash title="Latest build" lab
ID=$(aws codebuild list-builds-for-project --project-name app-build --query 'ids[0]' --output text)
aws codebuild batch-get-builds --ids "$ID" --query 'builds[0].[buildStatus,currentPhase,phases[?phaseStatus==`FAILED`].contexts[].message]'
```
@end
