---
title: AWS Step Functions
minutes: 50
objectives:
  - Model a workflow as a state machine in Amazon States Language
  - Choose between Standard and Express workflows
  - Add retries, catches, parallel and map states for reliable orchestration
---
Step Functions coordinates work across services with a visual state machine, built in retries and a durable execution history.

@concept What a state machine is
@plain
A **state machine** is a JSON definition of steps (states), the order between them and the data passed along. Each run is an **execution**.
@problem
Long processes with many steps, retries and branches become tangled in application code and are hard to see when they fail.
@does
- Written in **Amazon States Language** (ASL), a JSON format.
- State types: `Task`, `Choice`, `Parallel`, `Map`, `Wait`, `Pass`, `Succeed`, `Fail`.
- The state input and output are JSON. `InputPath`, `Parameters`, `ResultSelector`, `ResultPath` and `OutputPath` shape data; JSONata is also supported (check the current docs).
- The console shows each execution graphically with inputs and outputs.
@diagram flow
caption: Order workflow
numbered: true
nodes:
  - "Validate|Lambda task|app"
  - "Charge|payment task|app"
  - "Reserve stock|service task|app"
  - "Notify|SNS publish|ok"
@h A small definition
```json title="order.asl.json"
{
  "Comment": "Order flow",
  "StartAt": "Validate",
  "States": {
    "Validate": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {"FunctionName": "validate-order", "Payload.$": "$"},
      "OutputPath": "$.Payload",
      "Next": "Charge"
    },
    "Charge": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {"FunctionName": "charge", "Payload.$": "$"},
      "OutputPath": "$.Payload",
      "End": true
    }
  }
}
```
@check
What language defines a Step Functions workflow? || Amazon States Language, a JSON format.
@end

@concept Standard versus Express workflows
@plain
**Standard** workflows run up to a year with exactly-once step semantics. **Express** workflows run up to five minutes at very high rates with at-least-once semantics.
@problem
Human approval flows and high-volume event processing have opposite needs.
@does
- Standard: billed per state transition; full execution history stored; supports `.waitForTaskToken` and long waits.
- Express: billed by requests and duration; history goes to CloudWatch Logs; good for streaming data transformation and microservice orchestration; asynchronous or synchronous start.
- Make Express steps idempotent because they may run more than once.
- Check the current duration limits and pricing.
@diagram cmp
caption: Workflow types
cards:
  - {h: "Standard", kind: cp, items: ["Up to one year", "Exactly once steps", "Audit history", "Pay per transition"]}
  - {h: "Express", kind: app, items: ["Up to 5 minutes", "At least once", "Very high rate", "Pay for duration"]}
@choose Which workflow type
Standard | long running, human approval, audit needs | millions of short events per hour with tight cost
Express | high volume short processing, API backends | you need to wait days or need exactly-once
@check
Which type needs idempotent steps because they may repeat? || Express.
@end

@concept Service integrations and patterns
@plain
Step Functions can call over 200 AWS services directly (SDK integrations) without Lambda glue code.
@problem
Lambda functions that only call another API add cost, latency and code to maintain.
@does
- **Request Response**: call and move on.
- **Run a Job (`.sync`)**: wait until the job finishes, for ECS tasks, Glue jobs, CodeBuild, Batch and others.
- **Wait for callback (`.waitForTaskToken`)**: pause until an external system returns the token. Use for human approval.
- Direct integrations include DynamoDB, SQS, SNS, EventBridge, ECS, Bedrock and more; check the current list.
@diagram flow
caption: Waiting for a job
nodes:
  - "State|ecs runTask sync|cp"
  - "ECS task|runs|app"
  - "Complete|state resumes|ok"
@h Run an ECS task and wait
```json title="ecs-sync.json"
{
  "StartAt": "RunBatch",
  "States": {
    "RunBatch": {
      "Type": "Task",
      "Resource": "arn:aws:states:::ecs:runTask.sync",
      "Parameters": {
        "LaunchType": "FARGATE",
        "Cluster": "arn:aws:ecs:eu-west-1:111122223333:cluster/batch",
        "TaskDefinition": "arn:aws:ecs:eu-west-1:111122223333:task-definition/etl:7"
      },
      "End": true
    }
  }
}
```
@end

@concept Errors, retries and catch
@plain
Each Task can declare how to **Retry** on named errors and where to go on failure with **Catch**.
@problem
Transient failures are normal in distributed systems. Without declared handling, one blip fails the whole process.
@does
- `Retry`: `ErrorEquals`, `IntervalSeconds`, `MaxAttempts`, `BackoffRate`, optional `JitterStrategy`.
- `Catch`: route to a compensation or notification state, saving the error in `ResultPath`.
- Built-in error names such as `States.ALL`, `States.Timeout`, `States.TaskFailed`.
- `TimeoutSeconds` and `HeartbeatSeconds` stop stuck tasks.
- Backoff example: interval 2 s, rate 2 and MaxAttempts 3 gives waits of 2, 4 and 8 seconds, total 14 seconds.
@diagram flow
caption: Retry then compensate
nodes:
  - "Task|charge card|app"
  - "Retry|backoff and jitter|warn"
  - "Catch|go to refund state|bad"
  - "Notify failure|SNS|info"
@h Retry and catch
```json title="retry.json"
{
  "Type": "Task",
  "Resource": "arn:aws:states:::lambda:invoke",
  "Parameters": {"FunctionName": "charge", "Payload.$": "$"},
  "Retry": [
    {"ErrorEquals": ["Lambda.ServiceException", "Lambda.TooManyRequestsException"], "IntervalSeconds": 2, "MaxAttempts": 4, "BackoffRate": 2.0}
  ],
  "Catch": [
    {"ErrorEquals": ["States.ALL"], "ResultPath": "$.error", "Next": "Refund"}
  ],
  "TimeoutSeconds": 30,
  "Next": "Done"
}
```
@check
Sum the waits for interval 2 s, rate 2.0, 4 retries. || 2 + 4 + 8 + 16 = 30 seconds if all four retries occur.
@end

@concept Parallel, Map and Distributed Map
@plain
**Parallel** runs different branches at once. **Map** runs the same steps for each item of a list. **Distributed Map** processes huge datasets such as S3 objects in parallel child executions.
@problem
Sequential loops are slow, and a Lambda loop over a million files hits time limits.
@does
- Parallel waits for all branches; a failure fails the state unless caught.
- Map has `MaxConcurrency` to protect downstream systems.
- Distributed Map reads items from S3 (CSV, JSON, object lists) and starts many child workflow executions; check the current concurrency limits.
- Tolerated failure percentage lets a batch finish despite a few bad items.
@diagram flow
caption: Fan out and join
nodes:
  - "List of files|S3 inventory|info"
  - "Distributed Map|child executions|cp"
  - "Workers|process batches|app"
  - "Results|S3 summary|ok"
@h Map state
```json title="map.json"
{
  "Type": "Map",
  "ItemsPath": "$.items",
  "MaxConcurrency": 5,
  "ItemProcessor": {
    "ProcessorConfig": {"Mode": "INLINE"},
    "StartAt": "One",
    "States": {"One": {"Type": "Pass", "End": true}}
  },
  "End": true
}
```
@end

@concept Saga pattern and human approval
@plain
A **saga** undoes completed steps when a later step fails. Step Functions expresses this with Catch states that run compensation tasks.
@problem
Distributed transactions across services cannot use a database rollback.
@does
- Each forward step has a matching compensation (refund, release stock).
- Catch routes to compensations in reverse order.
- For approvals, a `.waitForTaskToken` task sends the token in an email or ticket; the approver calls `SendTaskSuccess` or `SendTaskFailure`.
- Add a task timeout so approvals do not wait forever.
@diagram flow
caption: Compensation path
nodes:
  - "Charge|done|ok"
  - "Reserve stock|fails|bad"
  - "Refund|compensate|warn"
  - "Fail state|report|bad"
@h Send approval
```bash title="Approve" nocheck
aws stepfunctions send-task-success --task-token "$TOKEN" --task-output '{"approved":true}'
```
@check
How does a human approval step pause a workflow? || A waitForTaskToken task hands out a token and resumes when SendTaskSuccess or SendTaskFailure is called with it.
@end

@concept Operating Step Functions
@plain
Operate workflows with logging, alarms, tracing and infrastructure as code.
@problem
A workflow that silently fails or loops costs money and loses business events.
@does
- Metrics: `ExecutionsFailed`, `ExecutionsTimedOut`, `ExecutionThrottled`, `ExecutionTime`.
- Turn on logging to CloudWatch Logs (always for Express) and X-Ray tracing.
- Use the Workflow Studio for design and **redrive** to resume a failed Standard execution from the failure point.
- The state machine role needs only the actions it calls.
- Cost: Standard billed per state transition. For example 1,000,000 executions of 10 transitions each is 10,000,000 transitions; check the current price per 1,000 transitions to price it.
@diagram flow
caption: Operational loop
nodes:
  - "Execution|runs|app"
  - "Logs and metrics|CloudWatch|info"
  - "Alarm|failed executions|warn"
  - "Redrive|from failure|ok"
@h Terraform
```hcl title="sfn.tf"
resource "aws_sfn_state_machine" "orders" {
  name       = "orders"
  role_arn   = aws_iam_role.sfn.arn
  definition = file("${path.module}/order.asl.json")
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = false
    level                  = "ERROR"
  }
}
```
@check
Which action restarts a failed Standard execution from its failed step? || Redrive.
@end
