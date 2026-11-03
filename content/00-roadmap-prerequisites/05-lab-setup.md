---
title: Lab setup and cost control
minutes: 15
objectives:
  - Install the local tools used in the labs
  - Set up a cloud account safely with budgets and least privilege
  - Know how to tear everything down
---
You can follow this whole path on a laptop, then add a cloud account for the AWS, Azure and Google sections.

@concept Local toolbox
@plain
A handful of command-line tools cover almost every lab: a container runtime, a local Kubernetes cluster, `kubectl`, Terraform, Git and Python.
@problem
Learners lose days to mismatched tool versions and half-finished installs, and then blame the concept instead of the setup.
@does
- Pins what is needed and gives one verification command per tool.
- Uses local Kubernetes (kind or minikube) so no cloud cost is needed to learn Kubernetes.
- Keeps versions in one file so the guide and your machine agree.
@diagram layers
caption: The local toolbox
layers:
  - {label: "Source", nodes: ["Git|history, pull requests|plain", "Editor|VS Code or similar|plain"]}
  - {label: "Build", nodes: ["Docker or Podman|build images|app", "Python|scripts, tests|ok"]}
  - {label: "Run", nodes: ["kind|local Kubernetes|env", "kubectl + Helm|talk to clusters|env"]}
  - {label: "Provision", nodes: ["Terraform|infrastructure|cp", "Cloud CLIs|aws, az, gcloud|vm"]}
@body
```bash title="Verify the toolbox" nocheck
git --version
docker --version          # or: podman --version
kubectl version --client
helm version --short
terraform version
python3 --version
kind version
aws --version             # optional until the AWS sections
```
@end

@concept Cloud accounts without surprises
@plain
Create separate accounts or projects for learning, protect the root login, and set a budget alert before creating anything.
@problem
The most common beginner incident is a forgotten resource billing for weeks, or a leaked access key used for crypto mining.
@does
- Enable multi-factor authentication on the root or owner identity, then stop using it for daily work.
- Create a budget with an email alert at a low threshold.
- Prefer short-lived credentials (SSO or OIDC) over long-lived access keys.
- Tag every lab resource so you can find and delete it.
@diagram flow
caption: Safe start order
numbered: true
nodes:
  - "Sign up|new, separate account|info"
  - "Secure|MFA on the owner|warn"
  - "Budget|alert at a low amount|bad"
  - "Daily user|SSO or limited role|app"
  - "Tag + destroy|clean up every session|ok"
@body
:::danger
Never commit access keys to Git. If one leaks, deactivate it immediately and review recent activity before anything else.
:::
@end

@concept The cost ladder and clean-up
@plain
Some things cost nothing, some cost a little, and a few cost a lot per hour even when idle. Know which is which before you click.
@problem
Managed Kubernetes control planes, NAT gateways, load balancers and large databases bill hourly. They are easy to forget because nothing looks busy.
@does
- Prefer local labs; use cloud only for the sections that need it.
- Always pair `apply` with `destroy`, and verify the console shows nothing left.
- Use a scheduled job or a calendar reminder to delete lab resources.
@diagram cmp
caption: What tends to cost money while idle
cards:
  - {h: "Usually cheap", kind: ok, items: ["Object storage, small amounts", "IAM, VPC, security groups", "Container registry, small"]}
  - {h: "Hourly even when idle", kind: warn, items: ["Managed Kubernetes control plane", "NAT gateways", "Load balancers"]}
  - {h: "Expensive if forgotten", kind: bad, items: ["Large instances and GPUs", "Multi-AZ databases", "Unattached disks and IPs"]}
@body
```bash title="Always finish a lab with" nocheck
terraform destroy
aws resourcegroupstaggingapi get-resources --tag-filters Key=project,Values=devops-path --query 'ResourceTagMappingList[].ResourceARN'
```
@end
