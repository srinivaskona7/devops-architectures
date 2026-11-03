---
title: Lambda execution model and scaling
minutes: 55
objectives:
  - Explain how Lambda runs code in execution environments and what a cold start is
  - Size memory and timeout and calculate the cost of an invocation pattern
  - Control concurrency with reserved and provisioned concurrency
---
Lambda runs your function code on demand without servers to manage. Understanding the execution environment lifecycle explains almost every performance and cost surprise.

@concept The execution environment lifecycle
@plain
Lambda creates an isolated **execution environment** (a Firecracker micro VM) for your function, runs your code in it, and reuses it for later requests until it is retired.
@problem
You want code to run only when needed, but starting a fresh runtime for every request would be slow and expensive.
@does
- **Init phase**: download code, start the runtime, run code outside the handler. Happens once per environment.
- **Invoke phase**: your handler runs. A warm environment skips init.
- **Shutdown phase**: the environment is frozen or retired at an unpredictable time. Never rely on it staying alive.
- One environment handles one request at a time. Parallel requests need parallel environments.
@diagram flow
caption: Phases of one environment
numbered: true
nodes:
  - "Init|download code and start runtime|warn"
  - "Invoke|handler runs|app"
  - "Freeze|idle between requests|info"
  - "Reuse or retire|next request or shutdown|cp"
@h Reuse state outside the handler
```python title="handler.py"
import json
import boto3

# runs once per environment (init phase)
s3 = boto3.client("s3")

def handler(event, context):
    # runs on every invoke
    return {"statusCode": 200, "body": json.dumps({"request": context.aws_request_id})}
```
@check
Where should you create SDK clients? || Outside the handler so warm invocations reuse them.
@end

@concept Cold starts
@plain
A **cold start** is the extra latency of the init phase when no warm environment is available.
@problem
Users notice a slow first request after idle time or during a traffic burst that needs new environments.
@does
- Affected by runtime (compiled or lightweight runtimes start faster than a JVM), package size, memory (more memory means more CPU), VPC is no longer a major cost, and heavy imports.
- Only a small share of invocations are cold in steady traffic; bursts and deployments create more.
- Mitigate with smaller packages, lazy imports, SnapStart for supported runtimes, or provisioned concurrency.
- Measure it: the `Init Duration` field in the REPORT log line appears only on cold starts.
@diagram seq
caption: Cold versus warm request
actors: ["Client|caller|ext", "Lambda service|router|cp", "Environment|your code|app"]
steps:
  - "0>1: invoke | req"
  - "1>2: create environment and init | warn"
  - "2>1: handler result | resp"
  - "0>1: second invoke | req"
  - "1>2: reuse warm environment | req"
@h Find cold starts in Logs Insights
```bash title="Count cold starts" nocheck
aws logs start-query --log-group-name /aws/lambda/orders \
  --start-time $(date -d '-1 hour' +%s) --end-time $(date +%s) \
  --query-string 'filter @type="REPORT" | stats count(*) as total, count(@initDuration) as cold, avg(@initDuration) as avgInitMs'
```
:::tip
Optimise the p99 first. Average latency hides cold starts.
:::
@end

@concept Memory, CPU and timeout
@plain
You pick memory from 128 MB up to 10,240 MB. CPU and network scale in proportion to memory. The timeout can be up to 15 minutes.
@problem
Too little memory makes a function slow and sometimes more expensive. Too much wastes money.
@does
- Billing is **GB-seconds**: memory in GB times billed duration in seconds, plus a per-request charge. Duration is billed in 1 ms increments.
- A CPU-bound function often costs the same or less at higher memory because it finishes faster.
- Find the best setting by testing several memory sizes, or use AWS Compute Optimizer recommendations or the open source Lambda Power Tuning tool.
- Set the timeout just above realistic maximum runtime so runaway calls stop early.
@diagram cmp
caption: Memory trade-off
cards:
  - {h: "Low memory", kind: warn, items: ["Less CPU", "Longer duration", "Risk of out of memory"]}
  - {h: "Right sized", kind: ok, items: ["Lowest cost per request", "Predictable latency", "Tuned by measurement"]}
  - {h: "High memory", kind: info, items: ["More CPU and network", "Faster for heavy work", "Pay for unused headroom"]}
@h Worked cost example
Example using illustrative prices of $0.0000166667 per GB-second and $0.20 per million requests (check current regional pricing and the free tier). A function at 512 MB runs 200 ms and is called 5 million times a month.

- GB-seconds = 5,000,000 x 0.5 GB x 0.2 s = 500,000
- Compute = 500,000 x 0.0000166667 = about $8.33
- Requests = 5 x $0.20 = $1.00
- Total = about $9.33 per month before free tier.
@check
What two numbers multiply to give GB-seconds? || Memory in GB and billed duration in seconds, per invocation, summed over all invocations.
@end

@concept Concurrency and throttling
@plain
**Concurrency** is the number of environments serving requests at the same moment. It is roughly requests per second multiplied by average duration in seconds.
@problem
Without limits, one noisy function can use all the account concurrency and starve others, or overwhelm a database.
@does
- Account quota per Region (check the current quota; it starts at a default and can be raised).
- **Reserved concurrency** guarantees capacity for a function and also caps it. Use it to protect downstream systems.
- Over the limit, synchronous callers get a 429 `TooManyRequestsException`; asynchronous events retry for a while; stream and queue pollers slow down.
- Scaling rate is limited per function; check the current quota for burst behaviour.
@diagram flow
caption: Concurrency pools
nodes:
  - "Account limit|shared by all functions|cp"
  - "Reserved|set aside for orders|ok"
  - "Unreserved pool|everything else|info"
  - "Throttle|429 or retry|bad"
@h Reserve and cap
```bash title="Set reserved concurrency" nocheck
aws lambda put-function-concurrency --function-name orders --reserved-concurrent-executions 50
aws lambda get-function-concurrency --function-name orders
```
Example: 100 requests per second at 0.3 s average needs about 100 x 0.3 = 30 concurrent environments.
@check
How do you estimate required concurrency? || Requests per second times average duration in seconds.
@end

@concept Provisioned concurrency
@plain
**Provisioned concurrency** keeps a chosen number of environments initialised and ready, so those requests avoid cold starts.
@problem
Latency-sensitive APIs cannot accept occasional multi-second first requests.
@does
- Attached to a published version or alias, not to `$LATEST`.
- You pay for the provisioned capacity while it is configured, plus a lower duration rate while serving.
- Requests above the provisioned number spill to normal on-demand environments, which can be cold.
- Can be scaled with Application Auto Scaling on a schedule or on utilisation.
@diagram flow
caption: Provisioned plus on-demand
nodes:
  - "Alias live|points to version 12|cp"
  - "Provisioned 10|always warm|ok"
  - "Spill over|on demand, may be cold|warn"
@h Configure with Terraform
```hcl title="provisioned.tf"
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.orders.function_name
  function_version = aws_lambda_function.orders.version
}

resource "aws_lambda_provisioned_concurrency_config" "orders" {
  function_name                     = aws_lambda_function.orders.function_name
  qualifier                         = aws_lambda_alias.live.name
  provisioned_concurrent_executions = 10
}
```
:::warn
Provisioned concurrency costs money while idle. Use a schedule if the traffic is only in office hours.
:::
@end

@concept Versions and aliases
@plain
Publishing creates an immutable **version** of code and configuration. An **alias** is a named pointer to a version, and can split traffic between two versions.
@problem
Deploying to `$LATEST` changes live behaviour instantly and gives no safe rollback.
@does
- Versions are numbered and cannot be changed.
- Aliases such as `live` are what event sources and API Gateway call.
- An alias can send a weight such as 10 percent to a new version for a canary release. CodeDeploy automates the shift and rollback.
- Rolling back is moving the alias to the previous version.
@diagram flow
caption: Weighted alias shift
numbered: true
nodes:
  - "Publish v13|immutable|app"
  - "Alias weight 10|v12 90 and v13 10|warn"
  - "Watch alarms|errors and latency|info"
  - "Alias to v13|100 percent|ok"
@h Weighted alias
```bash title="Canary" nocheck
aws lambda publish-version --function-name orders
aws lambda update-alias --function-name orders --name live \
  --function-version 12 --routing-config 'AdditionalVersionWeights={"13"=0.1}'
```
@check
What does a function URL or API call normally target, `$LATEST` or an alias? || An alias, so deployments are controlled and reversible.
@end

@concept Execution role and resource policy
@plain
Two different policies apply. The **execution role** says what the function may call. The **resource-based policy** says who may invoke the function.
@problem
People confuse the two and either grant too much or get access denied for the wrong reason.
@does
- The execution role has a trust policy for `lambda.amazonaws.com` and permissions for logs and your data sources.
- The resource policy grants principals such as `apigateway.amazonaws.com` or `events.amazonaws.com` permission to invoke, restricted with `SourceArn`.
- Without `SourceArn`, a service principal permission could be used by any account's resource of that type (confused deputy).
@diagram layers
caption: Two policy directions
layers:
  - {label: "Who can call me", nodes: ["Resource policy|invoke permission|cp"]}
  - {label: "My function", nodes: ["Handler|your code|app"]}
  - {label: "What I can call", nodes: ["Execution role|DynamoDB, S3, logs|info"]}
@h Invoke permission
```json title="Role permissions"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["dynamodb:GetItem", "dynamodb:PutItem"],
      "Resource": "arn:aws:dynamodb:eu-west-1:111122223333:table/orders"
    }
  ]
}
```
```bash title="Allow API Gateway to invoke" nocheck
aws lambda add-permission --function-name orders --statement-id apigw \
  --action lambda:InvokeFunction --principal apigateway.amazonaws.com \
  --source-arn arn:aws:execute-api:eu-west-1:111122223333:abc123/*/GET/orders
```
@end
