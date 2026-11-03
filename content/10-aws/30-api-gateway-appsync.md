---
title: API Gateway and AppSync
minutes: 55
objectives:
  - Choose between REST API, HTTP API, WebSocket API and AppSync
  - Secure and throttle an API with authorizers, usage plans and WAF
  - Deploy stages safely and troubleshoot common integration errors
---
API Gateway and AppSync put a managed, scalable front door on Lambda, containers and other backends. This section covers choosing the right product and operating it.

@concept The API products compared
@plain
API Gateway offers **REST APIs**, **HTTP APIs** and **WebSocket APIs**. AppSync offers managed **GraphQL**.
@problem
Teams pick a product by habit and then find a needed feature missing, or pay for features they never use.
@does
- **HTTP API**: lower cost and latency, JWT authorizers, Lambda and HTTP integrations, simple routes. The default for most new work.
- **REST API**: more features such as usage plans with API keys, request validation, WAF integration, resource policies, caching, private endpoints and per-method settings.
- **WebSocket API**: persistent two-way connections with route selection by message content.
- **AppSync**: GraphQL with resolvers to DynamoDB, Lambda, HTTP, OpenSearch and RDS, plus real-time subscriptions.
- Feature sets change, so check the current feature comparison before deciding.
@diagram cmp
caption: Four API products
cards:
  - {h: "HTTP API", kind: ok, items: ["Cheapest and fastest", "JWT and Lambda authorizers", "Most new APIs"]}
  - {h: "REST API", kind: app, items: ["Usage plans and keys", "WAF and caching", "Private endpoints"]}
  - {h: "WebSocket API", kind: info, items: ["Two-way messaging", "Connection IDs", "Chat and live feeds"]}
  - {h: "AppSync", kind: cp, items: ["GraphQL", "Subscriptions", "Resolvers to data sources"]}
@choose Which API front door
HTTP API | simple proxy to Lambda or a service and JWT auth | you need API keys, usage plans or WAF directly on the API
REST API | you need usage plans, WAF, caching or private APIs | you only need a cheap proxy
AppSync | clients need flexible queries and live subscriptions | a simple fixed REST contract is enough
@check
Which product gives usage plans with API keys? || The REST API type.
@end

@concept Integrations and request flow
@plain
An **integration** connects a route to a backend. The gateway receives the request, authorises it, applies throttling, calls the backend and returns the answer.
@problem
Backends should not each implement authentication, throttling and TLS themselves.
@does
- Lambda proxy integration passes the whole request as an event and expects a response object with `statusCode`, `headers` and `body`.
- HTTP proxy integration forwards to a public URL. Private integrations reach an ALB, NLB or Cloud Map service through a **VPC link**.
- AWS service integrations call services such as SQS or Step Functions directly without Lambda.
- Maximum integration timeout is limited (about 29 seconds by default for REST; check the current quota). Long work should be asynchronous.
@diagram flow
caption: Request path
numbered: true
nodes:
  - "Client|HTTPS|ext"
  - "API Gateway|route and authorise|cp"
  - "Integration|Lambda, VPC link, service|info"
  - "Backend|your code|app"
@h HTTP API in Terraform
```hcl title="http-api.tf"
resource "aws_apigatewayv2_api" "orders" {
  name          = "orders"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.orders.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.orders.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "get_orders" {
  api_id    = aws_apigatewayv2_api.orders.id
  route_key = "GET /orders"
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "$default"
  auto_deploy = true
}
```
@check
Why do long jobs not belong behind a synchronous API integration? || The integration timeout is short, so return 202 and process asynchronously.
@end

@concept Authentication and authorisation
@plain
API Gateway can verify callers with IAM, Cognito or JWT tokens, or call your own Lambda **authorizer**.
@problem
An open API invites abuse. You need identity checked before the backend runs.
@does
- **IAM auth**: callers sign with SigV4. Good for service to service.
- **JWT authorizer** (HTTP API): validates issuer, audience and signature of tokens from Cognito, IAM Identity Center or any OIDC provider, no code needed.
- **Lambda authorizer**: your function returns an IAM policy; results can be cached for a TTL.
- **Mutual TLS** is available for custom domains where clients present certificates.
- Pass the verified claims to the backend; do not trust client-provided identity headers.
@diagram seq
caption: JWT authorizer
actors: ["Client|has token|ext", "HTTP API|JWT authorizer|cp", "IdP|JWKS keys|ext", "Lambda|backend|app"]
steps:
  - "0>1: request with bearer token | req"
  - "1>2: fetch signing keys cached | tls"
  - "1>1: check issuer audience expiry | warn"
  - "1>3: invoke with claims | req"
  - "3>0: response | resp"
@h Add a JWT authorizer
```hcl title="jwt.tf"
resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.orders.id
  authorizer_type  = "JWT"
  name             = "oidc"
  identity_sources = ["$request.header.Authorization"]
  jwt_configuration {
    audience = ["orders-api"]
    issuer   = "https://idp.example.com/"
  }
}
```
@end

@concept Throttling, usage plans and WAF
@plain
Throttling limits request rates. On REST APIs, **usage plans** attach rate and quota limits to API keys. **WAF** blocks malicious traffic.
@problem
One client or attacker can exhaust backend capacity or run up cost.
@does
- Account-level and stage-level throttling use a token bucket of rate and burst (check the current default quotas).
- Per-route throttling is available for HTTP APIs and per-method for REST APIs.
- API keys identify clients for metering; they are not a security mechanism on their own.
- Attach AWS WAF to a REST API stage, or put CloudFront with WAF in front of any API.
- Clients should retry 429 with exponential backoff and jitter.
@diagram layers
caption: Defence layers
layers:
  - {label: "Edge", nodes: ["WAF|rules and rate limits|bad", "CloudFront|optional|ext"]}
  - {label: "Gateway", nodes: ["Authorizer|who are you|cp", "Throttle|rate and burst|warn"]}
  - {label: "Backend", nodes: ["Lambda or service|concurrency cap|app"]}
@h Stage throttling
```bash title="Set default route throttling" nocheck
aws apigatewayv2 update-stage --api-id abc123 --stage-name '$default' \
  --default-route-settings ThrottlingBurstLimit=200,ThrottlingRateLimit=100
```
@check
Is an API key a good way to authenticate users? || No. It identifies a client for metering. Use IAM or JWT for authentication.
@end

@concept Stages, deployments and custom domains
@plain
A **stage** is a named, deployed version of an API such as `prod`. A **custom domain** with an ACM certificate maps your own hostname to stages.
@problem
You need different environments and a stable URL that does not change when the API is redeployed.
@does
- REST APIs need an explicit deployment to a stage; HTTP APIs can auto-deploy.
- Stage variables and Lambda aliases support canary releases; REST stages have canary settings with a traffic percentage.
- Custom domains use a certificate in the same Region (regional) or in us-east-1 (edge optimised), then a Route 53 alias record. Base path mappings pick API and stage.
- Enable access logs with a JSON format and set retention.
@diagram flow
caption: Domain to stage
nodes:
  - "api.example.com|Route 53 alias|ext"
  - "Custom domain|ACM certificate|cp"
  - "Mapping|base path to stage|info"
  - "Stage prod|deployed API|app"
@h Access logs
```hcl title="stage-logs.tf"
resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.orders.id
  name        = "prod"
  auto_deploy = true
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    format          = jsonencode({ requestId = "$context.requestId", status = "$context.status", ip = "$context.identity.sourceIp", latency = "$context.responseLatency" })
  }
}
```
@end

@concept Private APIs and VPC links
@plain
A **private REST API** is reachable only through an interface VPC endpoint. A **VPC link** lets any API call private backends.
@problem
Internal services must not be exposed to the internet, but you still want one managed gateway.
@does
- Private REST API: resource policy limits access to specific VPC endpoints.
- HTTP API VPC link to a private ALB, NLB or Cloud Map namespace; the link runs ENIs in your subnets.
- Backends need security groups that allow traffic from the VPC link group.
- For internal east-west traffic between many services, also consider VPC Lattice.
@diagram flow
caption: Public API to private service
nodes:
  - "Internet client|HTTPS|ext"
  - "HTTP API|managed|cp"
  - "VPC link|ENIs in your subnets|info"
  - "Internal ALB|private|app"
@h Create a link
```bash title="VPC link" nocheck
aws apigatewayv2 create-vpc-link --name internal \
  --subnet-ids subnet-0aaa subnet-0bbb --security-group-ids sg-0123456789abcdef0
```
@check
What does a VPC link need to reach a private ALB? || ENIs in your subnets and a security group allowed by the ALB or targets.
@end

@concept AppSync and GraphQL
@plain
**AppSync** is managed GraphQL. Clients ask for exactly the fields they need in one call, and can subscribe to changes.
@problem
Mobile and web clients make many REST calls and receive too much or too little data.
@does
- A schema defines types, queries, mutations and subscriptions.
- **Resolvers** map fields to data sources. JavaScript resolvers run in AppSync without a Lambda for DynamoDB and HTTP sources.
- Auth modes: API key, IAM, Cognito, OIDC, Lambda. You can mix modes per field.
- Subscriptions push updates over WebSockets. Merged APIs combine schemas from several teams.
@diagram flow
caption: A GraphQL query
nodes:
  - "Client|one query|ext"
  - "AppSync|schema and auth|cp"
  - "Resolvers|per field|info"
  - "DynamoDB and Lambda|data sources|app"
@h Minimal schema
```graphql title="schema.graphql" nocheck
type Order { id: ID! status: String! total: Float }
type Query { getOrder(id: ID!): Order }
type Mutation { setStatus(id: ID!, status: String!): Order }
type Subscription { onStatus(id: ID!): Order @aws_subscribe(mutations: ["setStatus"]) }
```
@end

@concept Troubleshooting API errors
@plain
Most API Gateway failures come from a short list: permissions, timeouts, malformed responses and throttling.
@problem
The client sees a vague 500, 502, 503 or 504 and it is not obvious which hop failed.
@does
- **403**: authorizer denied, WAF blocked, missing resource policy, or wrong host.
- **429**: throttled by API Gateway or the backend.
- **500 Internal server error** with Lambda proxy: Lambda response was not in the expected shape, or the invoke permission is missing.
- **502**: backend returned an invalid response or connection failed. **504**: integration timeout.
- Turn on access logs and execution logs for the stage, and use X-Ray. Compare gateway latency with `integrationLatency`.
@diagram flow
caption: Where to look
numbered: true
nodes:
  - "Status code|403, 429, 5xx|warn"
  - "Access log|status and latency|info"
  - "Integration log|backend response|info"
  - "Backend log|Lambda or service|app"
@h Query the logs
```bash title="Errors in the last hour" nocheck
aws logs start-query --log-group-name /aws/apigw/orders \
  --start-time $(date -d '-1 hour' +%s) --end-time $(date +%s) \
  --query-string 'fields @timestamp, status, routeKey, integrationLatency | filter status >= 500 | sort @timestamp desc | limit 20'
```
@check
A Lambda proxy returns a plain string and API Gateway gives 500. Why? || The proxy integration expects a structured response with statusCode and body.
@end
