---
title: GuardDuty, Security Hub and Inspector
minutes: 50
objectives:
  - Enable threat detection with GuardDuty including EKS audit and runtime monitoring
  - Aggregate findings in Security Hub and automate response with EventBridge
  - Scan workloads continuously with Amazon Inspector
---
Detection services answer: what is happening, what is vulnerable, and how do we respond. On AWS they are separate services that feed one another.

@concept GuardDuty
@plain
GuardDuty analyses CloudTrail events, VPC flow logs and DNS logs with threat intelligence and machine learning, and reports suspicious behaviour as findings.
@problem
Compromised credentials, crypto mining and data exfiltration look like normal API calls unless something correlates them.
@does
- Enabled per Region and account; designate a delegated administrator and auto-enable members across the Organization.
- No agents for core data sources. Optional protection plans: S3, EKS audit logs, EKS and ECS runtime monitoring, Lambda, RDS login activity, malware scanning of EBS.
- Findings have severity (low, medium, high), a type like `UnauthorizedAccess:IAMUser/InstanceCredentialExfiltration`, and affected resources.
- Billed by volume of analysed events (30 day free trial).
@diagram flow
caption: Sources to findings
nodes:
  - "CloudTrail, flow logs, DNS|read independently|info"
  - "GuardDuty|threat intelligence and ML|cp"
  - "Finding|severity and resource|warn"
  - "EventBridge|alert or automate|ok"
@h Enable
```bash title="Enable GuardDuty with EKS protection" nocheck
DET=$(aws guardduty create-detector --enable --query DetectorId --output text)
aws guardduty update-detector --detector-id "$DET" \
  --features '[{"Name":"EKS_AUDIT_LOGS","Status":"ENABLED"},{"Name":"S3_DATA_EVENTS","Status":"ENABLED"},{"Name":"EKS_RUNTIME_MONITORING","Status":"ENABLED","AdditionalConfiguration":[{"Name":"EKS_ADDON_MANAGEMENT","Status":"ENABLED"}]}]'
aws guardduty list-findings --detector-id "$DET" --finding-criteria '{"Criterion":{"severity":{"Gte":7}}}'
```
@check
Does GuardDuty need agents on instances for its core detection? || No; it reads CloudTrail, flow and DNS logs directly.
@end

@concept GuardDuty for EKS
@plain
Two protections cover Kubernetes: **EKS audit log monitoring** (analyses the API audit stream) and **runtime monitoring** (an agent add-on watching processes, files and network inside nodes).
@problem
Attacks inside a cluster such as a container escape, a reverse shell or an anonymous API access do not appear in AWS API logs.
@does
- Audit log findings include `Policy:Kubernetes/AnonymousAccessGranted`, `PrivilegeEscalation:Kubernetes/PrivilegedContainer`.
- Runtime findings include `CryptoCurrency:Runtime/BitcoinTool.B`, `Execution:Runtime/ReverseShell`.
- Runtime monitoring installs the `aws-guardduty-agent` EKS add-on; it needs node resources and a VPC endpoint for private clusters.
- Route findings to a response runbook: isolate the pod with a deny-all NetworkPolicy, snapshot, and rotate credentials.
@diagram layers
caption: Two views
layers:
  - {label: "Control plane", nodes: ["Audit log monitoring|API calls and RBAC|cp"]}
  - {label: "Data plane", nodes: ["Runtime agent|process, file, network|app"]}
  - {label: "Output", nodes: ["Findings|Security Hub and EventBridge|ok"]}
@h Isolate a pod
```yaml title="Quarantine NetworkPolicy applied by response automation"
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: quarantine
  namespace: shop
spec:
  podSelector:
    matchLabels:
      quarantine: "true"
  policyTypes: ["Ingress", "Egress"]
```
```bash title="Label a suspicious pod" nocheck
kubectl -n shop label pod orders-7d9c quarantine=true --overwrite
```
@check
Which GuardDuty feature sees a reverse shell inside a container? || EKS runtime monitoring.
@end

@concept Security Hub
@plain
Security Hub collects findings from GuardDuty, Inspector, Macie, Config, IAM Access Analyzer and partners into one format and one dashboard, and runs compliance checks against standards.
@problem
Ten tools with ten consoles mean nobody looks at any of them. You need one prioritised list.
@does
- **Standards**: AWS Foundational Security Best Practices, CIS AWS Foundations, PCI DSS, NIST 800-53.
- **AWS Security Finding Format (ASFF)** normalises findings; filters and insights group them.
- Cross-account and cross-Region aggregation to a delegated administrator.
- Automation rules update or suppress findings; custom actions send findings to EventBridge.
- Newer Security Hub capabilities add correlation and exposure analysis (check the current feature set).
@diagram flow
caption: Aggregation
nodes:
  - "GuardDuty, Inspector, Macie, Config|producers|info"
  - "Security Hub|normalise and score|cp"
  - "Delegated admin|org-wide view|app"
  - "Tickets and chat|via EventBridge|ok"
@h Commands
```bash title="Enable standards and list failed controls" nocheck
aws securityhub enable-security-hub --enable-default-standards
aws securityhub get-findings \
  --filters '{"ComplianceStatus":[{"Value":"FAILED","Comparison":"EQUALS"}],"SeverityLabel":[{"Value":"CRITICAL","Comparison":"EQUALS"}]}' \
  --max-items 5 --query 'Findings[].[Title,Resources[0].Id]' --output table
```
@check
What is ASFF? || The AWS Security Finding Format, a common schema for findings from different tools.
@end

@concept Amazon Inspector
@plain
Inspector scans EC2 instances, ECR container images and Lambda functions for software vulnerabilities and unintended network exposure.
@problem
New CVEs are published daily; a point-in-time scan misses them.
@does
- Agentless or SSM-based scanning for EC2; ECR enhanced scanning for images; Lambda code and package scanning.
- Continuous: re-evaluates when new CVEs arrive or software changes.
- Risk score blends CVSS, exploitability and network reachability.
- Findings include the package, fixed version and remediation.
- Suppression rules and delegated administration support organisation-wide use.
@diagram flow
caption: Where Inspector looks
nodes:
  - "EC2 nodes|packages|app"
  - "ECR images|OS and language libs|app"
  - "Lambda|dependencies and code|app"
  - "Inspector|risk score|cp"
  - "Security Hub|findings|ok"
@h CLI
```bash title="Enable and list critical findings" nocheck
aws inspector2 enable --resource-types EC2 ECR LAMBDA
aws inspector2 list-findings --filter-criteria '{"severity":[{"comparison":"EQUALS","value":"CRITICAL"}]}' \
  --max-results 5 --query 'findings[].[title,packageVulnerabilityDetails.vulnerabilityId]' --output table
```
@check
What makes Inspector scanning continuous? || It re-evaluates resources when new vulnerabilities are published, not only at scan time.
@end

@concept Automated response with EventBridge
@plain
EventBridge rules match findings and trigger Lambda, SSM Automation, Step Functions or notifications.
@problem
A high-severity finding at night should not wait for someone to read a dashboard.
@does
- Match on `source: aws.guardduty` and severity above a threshold, then send to SNS/Chatbot and open a ticket.
- Safe auto-remediation: disable an access key, attach a deny policy, isolate an instance with a quarantine security group, block a bucket public access.
- Always log the action and keep a human approval step for destructive changes.
- Test with GuardDuty sample findings (`create-sample-findings`).
@diagram flow
caption: Finding to action
numbered: true
nodes:
  - "Finding|GuardDuty high|warn"
  - "EventBridge rule|pattern match|info"
  - "Lambda or SSM|remediate|app"
  - "Notify|chat and ticket|ok"
@h Rule
```json title="EventBridge pattern for high severity GuardDuty findings"
{
  "source": ["aws.guardduty"],
  "detail-type": ["GuardDuty Finding"],
  "detail": {"severity": [{"numeric": [">=", 7]}]}
}
```
```bash title="Test with sample findings" nocheck
aws guardduty create-sample-findings --detector-id "$DET" --finding-types "UnauthorizedAccess:EC2/SSHBruteForce"
```
@check
How can you test automation safely? || Generate GuardDuty sample findings and watch the rule fire.
@end
