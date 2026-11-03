---
title: Amazon Bedrock and SageMaker for platform teams
minutes: 45
objectives:
  - Distinguish Bedrock managed foundation models from SageMaker model building and hosting
  - Secure and govern generative AI access with IAM, VPC endpoints, guardrails and logging
  - Plan cost, quotas and operations for AI workloads as a platform team
---
Platform teams are increasingly asked to host AI workloads safely. This section covers what Bedrock and SageMaker provide and what the platform must govern. It is an overview for operators, not a data science course.

@concept Bedrock and SageMaker compared
@plain
**Amazon Bedrock** gives API access to foundation models from several providers. **Amazon SageMaker** is a platform to build, train, tune and host your own models.
@problem
Teams do not know whether to call a managed model API or run their own endpoints.
@does
- Bedrock: serverless, pay per token (on-demand) or provisioned throughput; models from several providers; features include Knowledge Bases (RAG), Agents, Guardrails and model evaluation. Check the current model list and regions.
- SageMaker: notebooks, training jobs, pipelines, model registry, real-time, serverless and batch inference endpoints.
- Bedrock suits applications that use existing models; SageMaker suits custom models or strict hosting control.
- Both can be used together, for example SageMaker for a fine-tuned model and Bedrock for a general one.
@diagram cmp
caption: Which AI service
cards:
  - {h: "Bedrock", kind: ok, items: ["Managed model APIs", "Per token pricing", "Guardrails and RAG"]}
  - {h: "SageMaker", kind: cp, items: ["Build and train", "Host your own endpoints", "MLOps pipelines"]}
@choose AI platform
Bedrock | you need text, image or embedding models behind an API | you must control model weights and hosting
SageMaker | you train or fine-tune custom models | a managed model API already fits
Both | custom model plus a general assistant | a single model serves the use case
@h Call a model
```python title="converse.py"
import boto3

bedrock = boto3.client("bedrock-runtime", region_name="eu-west-1")
response = bedrock.converse(
    modelId="REPLACE_WITH_MODEL_ID",
    messages=[{"role": "user", "content": [{"text": "Summarise this runbook in three bullets."}]}],
    inferenceConfig={"maxTokens": 300, "temperature": 0.2},
)
print(response["output"]["message"]["content"][0]["text"])
```
@check
Which service bills per token? || Bedrock on-demand inference.
@end

@concept Access control for Bedrock
@plain
Bedrock access is controlled by IAM. Model access must also be enabled, and IAM policies restrict which models each role may invoke.
@problem
Open access lets any workload call any model, which creates cost and data governance risk.
@does
- Allow `bedrock:InvokeModel` and `bedrock:Converse` on specific model ARNs only.
- Use SCPs to block Bedrock in Regions or accounts that should not use it.
- Use VPC interface endpoints (`bedrock-runtime`) so traffic stays private, with endpoint policies.
- Model invocation logging to CloudWatch Logs or S3 captures prompts and responses; handle as sensitive data.
@diagram layers
caption: Controls
layers:
  - {label: "Org", nodes: ["SCP|allowed Regions and accounts|bad"]}
  - {label: "Identity", nodes: ["IAM role policy|specific model ARNs|cp"]}
  - {label: "Network", nodes: ["VPC endpoint|private path and policy|info"]}
  - {label: "Audit", nodes: ["Invocation logging|prompts and cost|ok"]}
@h Least privilege policy
```json title="bedrock-policy.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel", "bedrock:Converse"],
    "Resource": "arn:aws:bedrock:eu-west-1::foundation-model/REPLACE_WITH_MODEL_ID"
  }]
}
```
@end

@concept Guardrails, RAG and agents
@plain
**Guardrails** filter inputs and outputs. **Knowledge Bases** add retrieval from your documents (RAG). **Agents** let models call tools.
@problem
Raw models can leak sensitive data, produce harmful text or answer without company knowledge.
@does
- Guardrails: denied topics, content filters, PII redaction, word filters and contextual grounding checks.
- Knowledge Bases: ingest documents from S3 to a vector store (OpenSearch Serverless, Aurora pgvector, and others) and retrieve relevant chunks at query time.
- Agents: orchestrate API calls with action groups defined by OpenAPI schemas; give them narrow IAM roles.
- Treat model output as untrusted input in downstream systems.
@diagram flow
caption: RAG request
numbered: true
nodes:
  - "User question|app|ext"
  - "Retrieve|vector store|info"
  - "Model with guardrail|answer|cp"
  - "Response|filtered|ok"
@h Guardrail
```bash title="Create guardrail" nocheck
aws bedrock create-guardrail --name shop-guardrail \
  --blocked-input-messaging "Request blocked" --blocked-outputs-messaging "Response blocked" \
  --sensitive-information-policy-config '{"piiEntitiesConfig":[{"type":"EMAIL","action":"ANONYMIZE"}]}'
```
@check
Why treat model output as untrusted? || It can be wrong or manipulated, so validate it before using it in other systems.
@end

@concept SageMaker building blocks
@plain
SageMaker offers managed notebooks, training jobs, pipelines, a model registry and inference endpoints.
@problem
Data scientists need repeatable environments and a path from experiment to production.
@does
- **Training jobs** run containers on managed instances and write artifacts to S3; Spot training lowers cost with checkpoints.
- **Pipelines** define steps as a DAG; the **Model Registry** versions and approves models.
- **Endpoints**: real-time (always on), serverless (scales to zero), asynchronous (queue based) and batch transform.
- Run in a VPC with private subnets, KMS encryption and network isolation for sensitive data.
- Studio spaces replace notebook instances for most new work; check the current user experience.
@diagram flow
caption: Model lifecycle
numbered: true
nodes:
  - "Data in S3|training input|ok"
  - "Training job|managed compute|app"
  - "Model registry|approve version|cp"
  - "Endpoint|inference|info"
@h Endpoint config with autoscaling target
```hcl title="sagemaker.tf"
resource "aws_sagemaker_endpoint_configuration" "model" {
  name = "model-v3"
  production_variants {
    variant_name           = "primary"
    model_name             = aws_sagemaker_model.model.name
    initial_instance_count = 2
    instance_type          = "ml.m5.large"
  }
}

resource "aws_sagemaker_endpoint" "model" {
  name                 = "model"
  endpoint_config_name = aws_sagemaker_endpoint_configuration.model.name
}
```
@end

@concept Network and data security
@plain
Keep training data and endpoints private, encrypted and auditable.
@problem
Data used for training and prompting is often the most sensitive data in the company.
@does
- Private subnets and VPC endpoints for S3, ECR, CloudWatch and the SageMaker API.
- KMS customer managed keys for S3, EBS volumes and endpoints.
- IAM execution roles scoped to specific buckets and prefixes; separate roles per team.
- Data classification: do not send regulated data to a model or Region that policy does not allow; check provider data handling terms.
- Bedrock does not use your prompts to train base models by default; confirm in the current service terms.
@diagram flow
caption: Private AI path
nodes:
  - "App in private subnet|workload|app"
  - "VPC endpoint|bedrock-runtime|info"
  - "Bedrock or SageMaker|no internet path|cp"
@h Endpoint
```hcl title="bedrock-endpoint.tf"
resource "aws_vpc_endpoint" "bedrock" {
  vpc_id              = aws_vpc.app.id
  service_name        = "com.amazonaws.eu-west-1.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}
```
@check
How do workloads reach Bedrock without the internet? || Through an interface VPC endpoint for bedrock-runtime.
@end

@concept Cost and quota management
@plain
AI costs scale with tokens or instance hours. Quotas limit throughput.
@problem
A prompt loop or oversized endpoint can burn a monthly budget in days.
@does
- Bedrock token cost = (input tokens x input price + output tokens x output price) per request, multiplied by volume. Example: 2,000 input tokens and 500 output tokens at assumed prices of 3 and 15 dollars per million tokens is 2,000 x 3 / 1,000,000 + 500 x 15 / 1,000,000 = 0.006 + 0.0075 = 0.0135 dollars per request; check real prices.
- Set Budgets and anomaly detection; tag by application, use application inference profiles for cost attribution where available.
- Quotas: tokens or requests per minute per model and Region; request increases early.
- SageMaker: stop idle notebooks and endpoints, use serverless or async endpoints for spiky use, Savings Plans for steady use.
@diagram flow
caption: Cost control
nodes:
  - "Tag and attribute|application|info"
  - "Budget alarm|threshold|warn"
  - "Rate limits|app level|cp"
@h Verify arithmetic
```python title="cost.py"
input_tokens, output_tokens = 2000, 500
in_price, out_price = 3.0, 15.0  # dollars per million tokens, assumed
per_request = input_tokens * in_price / 1e6 + output_tokens * out_price / 1e6
print(per_request, per_request * 100000)
```
@end

@concept Operating AI workloads
@plain
Operate AI services like any production service, with extra attention to evaluation, drift and safety.
@problem
Model quality can degrade silently, and outputs are non-deterministic.
@does
- Monitor latency, errors, throttles and token usage in CloudWatch; trace calls with X-Ray or OpenTelemetry.
- Evaluate quality with fixed test sets before and after changing a model, prompt or retrieval setup.
- Version prompts and configuration in Git; roll out changes gradually.
- SageMaker Model Monitor detects data and model drift for hosted models.
- Plan fallbacks: retry with backoff, a cheaper model or a graceful degraded answer.
@diagram flow
caption: Release loop
numbered: true
nodes:
  - "Change|model or prompt|app"
  - "Evaluate|fixed test set|info"
  - "Canary|small traffic|warn"
  - "Promote|or roll back|ok"
@h Alarm on throttles
```hcl title="bedrock-alarm.tf"
resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "bedrock-throttles"
  namespace           = "AWS/Bedrock"
  metric_name         = "InvocationThrottles"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"
}
```
@check
Compute the per-request cost above for 100,000 requests. || 0.0135 x 100,000 = 1,350 dollars at the assumed prices.
@end
