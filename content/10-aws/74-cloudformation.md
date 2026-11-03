---
title: CloudFormation stacks, change sets and drift
minutes: 55
objectives:
  - Write a CloudFormation template with parameters, conditions, outputs and intrinsic functions
  - Preview and apply updates safely with change sets and stack policies
  - Detect drift and use StackSets for multi-account deployment
---
CloudFormation is AWS's native infrastructure as code. Even if you use Terraform, you will meet it in Control Tower, Service Catalog, SAM and CDK.

@concept Templates and stacks
@plain
A **template** (YAML or JSON) declares resources. A **stack** is the deployed instance of a template, managed as one unit.
@problem
Clicking resources in the console cannot be reviewed, repeated or rolled back.
@does
- Sections: `Parameters`, `Mappings`, `Conditions`, `Resources` (required), `Outputs`, `Rules`.
- Creating, updating or deleting the stack changes all its resources together; failure rolls back by default.
- Each resource has a logical ID and a physical ID. Renaming a logical ID replaces the resource.
- Stacks live in one account and Region.
@diagram flow
caption: Template to resources
nodes:
  - "Template|YAML or JSON|info"
  - "CloudFormation|plan and call APIs|cp"
  - "Stack|managed unit|app"
  - "Resources|S3, VPC, IAM|ok"
@h A bucket template
```yaml title="bucket.yaml" nocheck
AWSTemplateFormatVersion: "2010-09-09"
Parameters:
  Env:
    Type: String
    AllowedValues: [dev, prod]
Conditions:
  IsProd: !Equals [!Ref Env, prod]
Resources:
  Data:
    Type: AWS::S3::Bucket
    DeletionPolicy: Retain
    Properties:
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: aws:kms
      VersioningConfiguration:
        Status: !If [IsProd, Enabled, Suspended]
Outputs:
  BucketName:
    Value: !Ref Data
    Export:
      Name: !Sub "${AWS::StackName}-bucket"
```
```bash title="Deploy" nocheck
aws cloudformation deploy --template-file bucket.yaml --stack-name data-dev --parameter-overrides Env=dev
```
@check
What happens if you rename a resource's logical ID? || CloudFormation creates a new resource and deletes the old one.
@end

@concept Intrinsic functions and pseudo parameters
@plain
Intrinsic functions such as `!Ref`, `!GetAtt`, `!Sub`, `!Join`, `!Select` and `!ImportValue` compute values at deploy time.
@problem
Templates must reference other resources and account facts without hard coding.
@does
- `!Ref` returns an ID or parameter value; `!GetAtt` returns an attribute such as an ARN.
- `!Sub` substitutes `${Var}` and pseudo parameters like `${AWS::Region}`, `${AWS::AccountId}`, `${AWS::StackName}`.
- `Fn::ImportValue` reads exports of another stack; this creates a hard dependency that blocks changing the export.
- `Fn::ForEach` (with the LanguageExtensions transform) loops, and SSM parameter types read values at deploy time.
- Dynamic references `{{resolve:ssm:/path}}` and `{{resolve:secretsmanager:...}}` avoid putting secrets in templates.
@diagram flow
caption: References
nodes:
  - "Role|IAM resource|app"
  - "GetAtt Arn|attribute|info"
  - "Function|uses role|ok"
@h Lambda using a role
```yaml title="function.yaml" nocheck
Resources:
  Role:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal: {Service: lambda.amazonaws.com}
            Action: sts:AssumeRole
      ManagedPolicyArns:
        - arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
  Fn:
    Type: AWS::Lambda::Function
    Properties:
      FunctionName: !Sub "${AWS::StackName}-fn"
      Runtime: python3.12
      Handler: index.handler
      Role: !GetAtt Role.Arn
      Code:
        ZipFile: |
          def handler(event, context):
              return "ok"
```
@end

@concept Change sets and stack policies
@plain
A **change set** shows exactly what an update will add, modify, replace or remove before you apply it. A **stack policy** blocks updates to protected resources.
@problem
A small template edit can silently replace a database and lose data.
@does
- Review the `Replacement` column: `True` means the resource is recreated.
- Apply change sets in CI after a human or policy review.
- Stack policy denies `Update:Replace` and `Update:Delete` on critical resources.
- `DeletionPolicy: Retain` or `Snapshot` and `UpdateReplacePolicy` protect data.
- **Termination protection** stops accidental stack deletion.
@diagram flow
caption: Safe update
numbered: true
nodes:
  - "Edit template|pull request|app"
  - "Create change set|preview|info"
  - "Review|replacement true?|warn"
  - "Execute|apply|ok"
@h Preview with CLI
```bash title="Change set" nocheck
aws cloudformation create-change-set --stack-name data-prod --change-set-name pr-42 \
  --template-body file://bucket.yaml --parameters ParameterKey=Env,ParameterValue=prod
aws cloudformation describe-change-set --stack-name data-prod --change-set-name pr-42 \
  --query 'Changes[].ResourceChange.[LogicalResourceId,Action,Replacement]' --output table
aws cloudformation execute-change-set --stack-name data-prod --change-set-name pr-42
```
@check
Which column warns that an update recreates a resource? || Replacement set to True.
@end

@concept Drift detection
@plain
**Drift** is when real resources differ from what the stack template says, usually because someone changed them by hand.
@problem
Manual hotfixes make environments differ and the next update may overwrite them or fail.
@does
- Run drift detection per stack; results list resources as `IN_SYNC`, `MODIFIED` or `DELETED` with property differences.
- Not all resource types or properties are supported.
- Fix by updating the template to match intent, or revert the resource, then update the stack. Use `resource import` to bring existing resources under management.
- Detect regularly and alert; prevent drift with SCPs that restrict console writes.
@diagram flow
caption: Drift cycle
nodes:
  - "Manual change|console edit|bad"
  - "Detect drift|stack scan|info"
  - "Decide|template or revert|warn"
  - "Update stack|back in sync|ok"
@h Detect
```bash title="Drift" lab
aws cloudformation detect-stack-drift --stack-name data-prod
aws cloudformation describe-stack-resource-drifts --stack-name data-prod \
  --stack-resource-drift-status-filters MODIFIED DELETED
```
@end

@concept Nested stacks, exports and StackSets
@plain
**Nested stacks** compose templates. **StackSets** deploy one template to many accounts and Regions.
@problem
Giant templates are slow and risky, and baseline resources are needed in every account.
@does
- Nested stack: a resource of type `AWS::CloudFormation::Stack` pointing to a template in S3; good for reuse in one deployment.
- Cross-stack references through exports are rigid; prefer SSM parameters for loosely coupled sharing.
- StackSets with **service-managed permissions** integrate with AWS Organizations and auto-deploy to new accounts in target OUs.
- Control rollout with failure tolerance and max concurrent accounts.
@diagram flow
caption: StackSet rollout
nodes:
  - "Template|baseline role and logging|info"
  - "StackSet|in management or delegated admin|cp"
  - "Target OU|auto deploy|env"
  - "Stack instances|per account and Region|ok"
@h Create service-managed StackSet
```bash title="StackSet" nocheck
aws cloudformation create-stack-set --stack-set-name baseline --template-body file://baseline.yaml \
  --permission-model SERVICE_MANAGED --auto-deployment Enabled=true,RetainStacksOnAccountRemoval=false \
  --capabilities CAPABILITY_NAMED_IAM
aws cloudformation create-stack-instances --stack-set-name baseline \
  --deployment-targets OrganizationalUnitIds=ou-abcd-11111111 --regions eu-west-1
```
@check
Why prefer SSM parameters over exports for sharing? || Exports lock the producing stack; parameters decouple lifecycles.
@end

@concept Custom resources, macros and hooks
@plain
Custom resources run your Lambda during stack operations. Macros transform templates. Hooks validate resources before provisioning.
@problem
Some tasks (look up an AMI, seed data) or policies (all buckets must be encrypted) are not supported by native resources.
@does
- Custom resource: Lambda receives Create, Update, Delete events and must return a response to the pre-signed URL or the stack hangs until timeout. `cfn-response` or CDK Provider framework handles this.
- Macros (like `AWS::Serverless` for SAM) rewrite templates.
- **CloudFormation Guard** and Hooks enforce rules at deploy time; cfn-lint checks templates in CI.
- Registry extensions add third-party resource types.
@diagram seq
caption: Custom resource flow
actors: ["CloudFormation|stack|cp", "Lambda|your code|app", "Response URL|pre-signed S3|ext"]
steps:
  - "0>1: Create event | req"
  - "1>1: do the work | req"
  - "1>2: send SUCCESS or FAILED | resp"
  - "2>0: stack continues | resp"
@h CI checks
```bash title="Lint and guard" nocheck
cfn-lint bucket.yaml
cfn-guard validate --data bucket.yaml --rules rules.guard
```
@end

@concept Troubleshooting stack failures
@plain
Most failures are permissions, quotas, name conflicts, dependency order or a rollback loop.
@problem
Stacks stuck in `ROLLBACK_FAILED` or `UPDATE_ROLLBACK_FAILED` block everyone.
@does
- Read the stack events, first failed resource at the bottom of the time order, for the real error.
- `CREATE_FAILED` rolls back and leaves the stack in `ROLLBACK_COMPLETE`; delete and recreate.
- `UPDATE_ROLLBACK_FAILED`: fix the cause (often a manually deleted resource) and use `continue-update-rollback`, optionally skipping resources.
- Use `--disable-rollback` in dev to keep failed resources for inspection.
- Always pass a service role with least privilege for deployments.
@diagram flow
caption: Debug order
numbered: true
nodes:
  - "Stack events|first failure|warn"
  - "Resource error|permission or quota|info"
  - "Fix cause|template or account|app"
  - "Continue or retry|rollback or update|ok"
@h Find the failure
```bash title="Failed events" lab
aws cloudformation describe-stack-events --stack-name data-prod \
  --query "StackEvents[?contains(ResourceStatus,'FAILED')].[Timestamp,LogicalResourceId,ResourceStatusReason]" --output table
```
@check
Which command resumes a stuck UPDATE_ROLLBACK_FAILED stack? || continue-update-rollback.
@end
