---
title: Well-Architected framework and the three-tier shop
minutes: 45
objectives:
  - Name the six pillars and the questions each asks
  - Run a Well-Architected review and track improvements
  - Describe the reference three-tier EKS application used in this section
---
The AWS Well-Architected Framework is a structured way to ask whether a workload is built well. It is not a certification and not a checklist to pass; it is a review that finds risks and ranks them.

@concept The six pillars
@plain
Six pillars group the questions: Operational Excellence, Security, Reliability, Performance Efficiency, Cost Optimization and Sustainability.
@problem
Teams optimise what hurts today (an outage, a bill) and ignore the other dimensions until they fail.
@does
- **Operational Excellence**: run and improve with automation, small changes and learning from failure.
- **Security**: protect data, identity and infrastructure; detect and respond.
- **Reliability**: recover from failure and meet demand; design for failure.
- **Performance Efficiency**: use the right resources and keep them right as needs change.
- **Cost Optimization**: deliver value at the lowest price point; know where money goes.
- **Sustainability**: reduce environmental impact through efficient use.
- Trade-offs are explicit: more redundancy costs more; more controls slow delivery.
@diagram cmp
caption: One line per pillar
cards:
  - {h: "Operational Excellence", kind: info, items: ["IaC, CI/CD, runbooks", "Observability"]}
  - {h: "Security", kind: bad, items: ["Identity, encryption", "Detection and response"]}
  - {h: "Reliability", kind: ok, items: ["Multi-AZ, backups", "Tested recovery"]}
  - {h: "Performance", kind: app, items: ["Right sizing", "Caching and scaling"]}
  - {h: "Cost", kind: warn, items: ["Tagging, budgets", "Commitments and Spot"]}
  - {h: "Sustainability", kind: env, items: ["Graviton, efficient scaling", "Less idle capacity"]}
@h Tooling
```bash title="Workload reviews from the CLI" nocheck
aws wellarchitected list-workloads --query 'WorkloadSummaries[].[WorkloadName,RiskCounts]'
aws wellarchitected list-lens-reviews --workload-id 0123456789abcdef0123456789abcdef
```
@check
Is Well-Architected a pass or fail audit? || No; it is a review that identifies and prioritises risks and trade-offs.
@end

@concept How a review works
@plain
You pick a workload, answer the lens questions with your team, see high and medium risk items, and create an improvement plan.
@problem
Reviews that are one-off documents get stale; the value is in repeating them.
@does
- The **AWS Well-Architected Tool** stores workloads, answers, risks and milestones; lenses include the Framework, Serverless, SaaS, Container Build, and others.
- Review at design time, before launch, and at least yearly or after major changes.
- Work in small sessions with the people who run the system, not only architects.
- Convert each high risk item into a ticket with an owner and date.
- Use Trusted Advisor, Config and Security Hub for automated evidence.
@diagram flow
caption: Review cycle
numbered: true
nodes:
  - "Define workload|scope and owners|plain"
  - "Answer questions|honest and brief|info"
  - "List risks|high and medium|warn"
  - "Improvement plan|tickets and dates|app"
  - "Milestone|compare next review|ok"
@h Check automated signals
```bash title="Trusted Advisor checks via Support API (Business support or higher)" nocheck
aws support describe-trusted-advisor-checks --language en --query 'checks[?category==`security`].[id,name]' --output table
```
@check
How often should you repeat a review? || At least yearly and after major architecture changes.
@end

@concept The reference application
@plain
Throughout this section the example is a shop with a web tier, an API tier and a data tier, running on EKS in a three-AZ VPC.
@problem
Principles are abstract until they are applied to a concrete system with real services.
@does
- **Edge**: Route 53, CloudFront, WAF, ACM.
- **Web tier**: ALB in public subnets, `web` pods in private subnets.
- **API tier**: `orders`, `catalog` pods, Pod Identity for AWS access, ExternalDNS, cert-manager.
- **Data tier**: Aurora PostgreSQL, ElastiCache, DynamoDB for sessions, S3 for media, in isolated subnets.
- **Platform**: EKS on managed node group plus Karpenter, ECR, CloudWatch, GuardDuty, Security Hub.
@diagram layers
caption: Shop architecture
layers:
  - {label: "Edge", nodes: ["Route 53|DNS|ext", "CloudFront and WAF|cache and filter|warn"]}
  - {label: "Web and API tiers (EKS, private subnets)", nodes: ["ALB|public subnets|cp", "web pods|3 AZs|app", "orders and catalog pods|3 AZs|app"]}
  - {label: "Data tier (isolated subnets)", nodes: ["Aurora PostgreSQL|writer plus readers|ok", "ElastiCache|Valkey Multi-AZ|ok", "DynamoDB and S3|managed|ok"]}
  - {label: "Platform", nodes: ["ECR|images|info", "CloudWatch|logs and metrics|info", "GuardDuty and Security Hub|detection|info"]}
@h Network layout
```hcl title="Three-AZ VPC with tiered subnets"
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 5.0"

  name = "shop-prod"
  cidr = "10.20.0.0/16"
  azs  = ["us-east-1a", "us-east-1b", "us-east-1c"]

  public_subnets   = ["10.20.0.0/24", "10.20.1.0/24", "10.20.2.0/24"]
  private_subnets  = ["10.20.16.0/20", "10.20.32.0/20", "10.20.48.0/20"]
  database_subnets = ["10.20.64.0/24", "10.20.65.0/24", "10.20.66.0/24"]

  enable_nat_gateway     = true
  one_nat_gateway_per_az = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = 1 }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = 1, "karpenter.sh/discovery" = "shop-prod" }
}
```
@check
Where do database instances live? || In isolated database subnets with no route to the internet.
@end

@concept Operational excellence applied
@plain
Make every change small, automated, observable and reversible.
@problem
Manual changes cause outages and cannot be reviewed or repeated.
@does
- Infrastructure as code (Terraform) and GitOps (Argo CD or Flux) with pull requests.
- CI pipeline: build image, scan, push to ECR with immutable tag, deploy to staging, run smoke tests, promote.
- Observability: logs, metrics, traces, SLOs with alerts on symptoms.
- Runbooks linked from alarms; game days; blameless post-incident reviews.
- Progressive delivery (rolling, canary) with automatic rollback on SLO breach.
@diagram flow
caption: Change pipeline
numbered: true
nodes:
  - "Pull request|reviewed IaC and code|plain"
  - "CI|test, scan, build|app"
  - "Staging|smoke tests|info"
  - "Production|canary then full|warn"
  - "Observe|SLO guard and rollback|ok"
@h Argo CD application
```yaml title="GitOps app for the shop"
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: shop-prod
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/example/shop-config.git
    targetRevision: main
    path: overlays/prod
  destination:
    server: https://kubernetes.default.svc
    namespace: shop
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```
@check
Why prefer pull requests for infrastructure changes? || They give review, history and the ability to revert a known state.
@end

@concept Security applied
@plain
Apply least privilege and defence in depth at each tier.
@problem
A single compromised pod or leaked key should not expose the database or the account.
@does
- Identity: SSO for people, Pod Identity for pods, no long-lived keys, permission boundaries, SCPs.
- Network: private subnets, security groups for pods, default-deny NetworkPolicies, VPC endpoints, WAF and Shield at the edge.
- Data: KMS everywhere, TLS in transit, Secrets Manager via External Secrets, S3 block public access.
- Detection: CloudTrail, Config, GuardDuty with EKS protections, Security Hub, Inspector for images.
- Response: runbooks and automated quarantine for high severity findings.
@diagram layers
caption: Controls mapped to layers
layers:
  - {label: "People", nodes: ["Identity Center|MFA, groups|ok"]}
  - {label: "Platform", nodes: ["SCPs|guardrails|warn", "Access entries|RBAC|info"]}
  - {label: "Workload", nodes: ["Pod Identity|no keys|ok", "NetworkPolicy|default deny|ok"]}
  - {label: "Data", nodes: ["KMS and TLS|encryption|ok"]}
@h Pod security
```yaml title="Pod Security Admission labels on the namespace"
apiVersion: v1
kind: Namespace
metadata:
  name: shop
  labels:
    pod-security.kubernetes.io/enforce: restricted
    pod-security.kubernetes.io/audit: restricted
    pod-security.kubernetes.io/warn: restricted
```
@check
Which Kubernetes mechanism enforces non-root, no privileged pods per namespace? || Pod Security Admission, with the restricted profile.
@end
