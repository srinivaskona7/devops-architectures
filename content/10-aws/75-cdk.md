---
title: AWS CDK constructs and pipelines
minutes: 50
objectives:
  - Explain apps, stacks and the three construct levels
  - Synthesize, diff and deploy a CDK app and understand bootstrapping
  - Test constructs and package reusable platform patterns
---
The AWS Cloud Development Kit lets you define infrastructure in TypeScript, Python, Java, C# or Go and synthesizes CloudFormation templates.

@concept What CDK is
@plain
CDK is a framework where you write code that creates objects called **constructs**. Running `cdk synth` turns them into CloudFormation templates, and `cdk deploy` applies them.
@problem
YAML templates have no loops, types, functions or unit tests, so large estates become copy and paste.
@does
- Languages: TypeScript (primary), Python, Java, .NET, Go.
- A CDK **app** contains one or more **stacks**; each stack becomes a CloudFormation stack.
- You get real programming constructs, IDE completion and package sharing.
- The result is still CloudFormation, so rollback, drift detection and change sets all apply.
@diagram flow
caption: CDK pipeline
numbered: true
nodes:
  - "Code|TypeScript or Python|app"
  - "cdk synth|CloudFormation template|info"
  - "cdk deploy|create change set|cp"
  - "CloudFormation|stack|ok"
@h A small app in Python
```python title="app.py"
import aws_cdk as cdk
from aws_cdk import aws_s3 as s3, aws_lambda as _lambda

class ShopStack(cdk.Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        bucket = s3.Bucket(self, "Uploads",
                           versioned=True,
                           encryption=s3.BucketEncryption.S3_MANAGED,
                           block_public_access=s3.BlockPublicAccess.BLOCK_ALL)
        fn = _lambda.Function(self, "Resize",
                              runtime=_lambda.Runtime.PYTHON_3_12,
                              handler="index.handler",
                              code=_lambda.Code.from_asset("lambda"))
        bucket.grant_read(fn)

app = cdk.App()
ShopStack(app, "Shop", env=cdk.Environment(account="111122223333", region="eu-west-1"))
app.synth()
```
@check
What does cdk synth produce? || CloudFormation templates (a cloud assembly).
@end

@concept Construct levels L1, L2 and L3
@plain
**L1** constructs map one to one to CloudFormation resources (`CfnBucket`). **L2** add sensible defaults and helper methods. **L3** (patterns) combine several resources into a solution.
@problem
Raw resources need lots of repeated wiring such as IAM policies and security groups.
@does
- L1: names start with `Cfn`, generated from the CloudFormation spec; use as an escape hatch.
- L2: `s3.Bucket`, `lambda.Function`; grant methods such as `bucket.grantRead(fn)` create least-privilege IAM automatically.
- L3 or patterns: for example `ApplicationLoadBalancedFargateService` creates cluster, service, ALB and roles.
- Your platform team can publish its own L3 constructs with company defaults.
@diagram layers
caption: Construct levels
layers:
  - {label: "L3 patterns", nodes: ["Load balanced Fargate service|many resources|ok"]}
  - {label: "L2 resources", nodes: ["Bucket, Function, Table|defaults and grants|app"]}
  - {label: "L1", nodes: ["CfnBucket|1 to 1 with CloudFormation|info"]}
@h Escape hatch
```python title="escape.py"
from aws_cdk import Stack, aws_s3 as s3
from constructs import Construct


class DataStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        bucket = s3.Bucket(self, "Data", versioned=True)
        # drop to the L1 resource only for a property the L2 construct does not expose
        cfn_bucket = bucket.node.default_child
        cfn_bucket.add_property_override("ObjectLockEnabled", True)
```
@check
Which level should you reach for first? || L2, dropping to L1 only when a feature is missing.
@end

@concept Bootstrapping and environments
@plain
Before first deploy, `cdk bootstrap` creates a **CDKToolkit** stack in each account and Region with an assets bucket, ECR repository and roles.
@problem
CDK must upload Lambda code and Docker images before CloudFormation can use them, and needs roles to deploy.
@does
- Bootstrap once per account and Region: `cdk bootstrap aws://111122223333/eu-west-1`.
- Creates deploy, file publishing, image publishing and lookup roles; cross-account deployments trust the pipeline account.
- Modern bootstrap supports least-privilege customisation and permission boundaries.
- Environment-agnostic stacks cannot look up VPCs or AZs; set `env` for those.
@diagram flow
caption: Bootstrapped account
nodes:
  - "CDKToolkit stack|per account and Region|cp"
  - "Assets bucket|code and templates|ok"
  - "ECR repo|images|ok"
  - "Roles|deploy and publish|warn"
@h Commands
```bash title="Bootstrap and deploy" nocheck
cdk bootstrap aws://111122223333/eu-west-1
cdk diff
cdk deploy Shop --require-approval broadening
```
@end

@concept Diff, deploy and context
@plain
`cdk diff` compares your code against the deployed stack. **Context** caches lookups such as VPC IDs in `cdk.context.json`.
@problem
Without a preview, a refactor can replace resources unexpectedly, and lookups that change between runs make builds non-repeatable.
@does
- Commit `cdk.context.json` so synthesis is deterministic.
- `--require-approval broadening` pauses when IAM or security group access widens.
- Changing a construct ID changes the logical ID, which replaces the resource. Use `overrideLogicalId` or keep IDs stable.
- `cdk watch` hot-swaps Lambda or ECS changes in development. Not for production.
@diagram flow
caption: Review before applying
nodes:
  - "Code change|pull request|app"
  - "cdk diff|resources and IAM|info"
  - "Approval|broadening changes|warn"
  - "Deploy|execute|ok"
@h Pin context
```json title="cdk.context.json"
{
  "vpc-provider:account=111122223333:filter.vpc-id=vpc-0abc123:region=eu-west-1:returnAsymmetricSubnets=true": {
    "vpcId": "vpc-0abc123"
  }
}
```
@check
Why commit cdk.context.json? || Lookups stay stable so builds are repeatable.
@end

@concept Testing and aspects
@plain
You can unit test synthesized templates, and use **Aspects** to enforce rules across all constructs.
@problem
Infrastructure mistakes are found in production unless they are tested like application code.
@does
- **Assertions** module: check the template contains a resource with given properties, or snapshot test.
- **Aspects** visit every construct; use them to add tags, enforce encryption or block public buckets.
- `cdk-nag` applies rule packs such as AWS Solutions checks.
- Integration tests with the integ-tests library deploy to a real account.
@diagram flow
caption: Test layers
nodes:
  - "Unit assertions|template matches|info"
  - "Aspects and cdk-nag|policy rules|warn"
  - "Integration test|real deploy|app"
@h Assertion test
```python title="test_shop.py"
import aws_cdk as cdk
from aws_cdk.assertions import Template
from shop.shop_stack import ShopStack

def test_bucket_is_encrypted():
    app = cdk.App()
    template = Template.from_stack(ShopStack(app, "Test"))
    template.has_resource_properties("AWS::S3::Bucket", {
        "BucketEncryption": {"ServerSideEncryptionConfiguration": [{"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]}
    })
```
@end

@concept CDK Pipelines
@plain
**CDK Pipelines** creates a self-mutating CodePipeline that builds, tests and deploys your CDK app across stages and accounts.
@problem
Hand-written deployment pipelines drift from the infrastructure they deploy.
@does
- Pipeline stages: Source, Build (synth), UpdatePipeline (self-mutate), Assets, then your deployment waves.
- Add manual approval or validation steps between environments.
- Cross-account deployment uses the bootstrapped roles, with cross-account KMS for artifacts.
- Alternative: run `cdk deploy` from GitHub Actions or another CI with OIDC.
@diagram flow
caption: Self mutating pipeline
numbered: true
nodes:
  - "Source|repo push|ext"
  - "Synth|build and test|app"
  - "Self mutate|update pipeline|warn"
  - "Dev then Prod|stages|ok"
@h Pipeline skeleton
```python title="pipeline.py"
from aws_cdk import pipelines, Stack

class PipelineStack(Stack):
    def __init__(self, scope, id, **kwargs):
        super().__init__(scope, id, **kwargs)
        pipeline = pipelines.CodePipeline(self, "Pipeline",
            synth=pipelines.ShellStep("Synth",
                input=pipelines.CodePipelineSource.connection("org/shop", "main",
                    connection_arn="arn:aws:codeconnections:eu-west-1:111122223333:connection/abc"),
                commands=["pip install -r requirements.txt", "npx cdk synth"]))
```
@check
What does the self mutate stage do? || Updates the pipeline itself when its definition in code changes.
@end

@concept Sharing constructs and CDK vs Terraform
@plain
Publish well-tested constructs as packages so teams reuse your standards. Choose CDK or Terraform by team skills and estate.
@problem
Every team re-solves the same patterns differently, and tool choice debates stall projects.
@does
- Package constructs with `jsii` for multiple languages, or publish a single language to a private registry such as CodeArtifact.
- Version constructs with semantic versioning and a changelog; use snapshot tests.
- CDK strengths: AWS-first, types, CloudFormation rollback, strong L2 defaults. Terraform strengths: multi-cloud, large provider ecosystem, plan output, state portability.
- CDK for Terraform (CDKTF) exists, but check its current status before adopting it.
- Mixed estates are fine: bridge them with SSM parameters.
@diagram cmp
caption: Tool choice
cards:
  - {h: "CDK", kind: app, items: ["AWS only", "Real languages", "CloudFormation engine"]}
  - {h: "Terraform", kind: cp, items: ["Multi-cloud", "Plan and state", "Large module ecosystem"]}
@choose IaC tool
CDK | AWS-centric dev teams who like code | you must manage many non-AWS providers
Terraform | multi-cloud or platform team standard | your team wants L3 patterns with generated IAM
CloudFormation | you use SAM, StackSets or Service Catalog | you need loops and abstractions
@end
