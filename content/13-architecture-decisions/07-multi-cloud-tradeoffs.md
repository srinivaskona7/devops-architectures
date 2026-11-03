---
title: Multi-cloud trade-offs
minutes: 50
objectives:
  - Distinguish multi-cloud, hybrid and portable designs and their real costs
  - Judge when a second cloud is justified and when it is not
  - Reduce lock-in with open interfaces and a clear exit plan
---
Using more than one cloud is sometimes necessary and often expensive. Decide it for a reason you can write down.

@concept Terms: multi-cloud, hybrid, portable
@plain
Multi-cloud means using two or more public clouds. Hybrid means public cloud plus your own data center. Portable means the workload can move with little change.
@problem
The words are used loosely, so teams argue past each other about very different designs.
@does
- Multi-cloud by accident: different teams or acquisitions chose different clouds.
- Multi-cloud by design: each workload on the cloud best for it, or one workload spread for resilience.
- Hybrid: regulation, latency to factory floors or existing hardware keep part on-premises.
- Portable: containers, open databases and infrastructure as code lower the cost of moving, but never to zero.
@diagram cmp
caption: Four postures
cards:
  - {h: "Single cloud", kind: ok, items: ["Deepest integration", "Simplest operations", "Highest lock-in"]}
  - {h: "Multi-cloud by workload", kind: info, items: ["Best service per job", "Two skill sets", "Cross-cloud data costs"]}
  - {h: "Active-active across clouds", kind: bad, items: ["Provider outage protection", "Lowest common denominator", "Highest complexity"]}
  - {h: "Hybrid", kind: warn, items: ["Keeps on-premises", "Needs strong links", "Two operating models"]}
@check
What is hybrid? || Public cloud together with your own data center.
@end

@concept Valid reasons for a second cloud
@plain
There are a few good reasons and many weak ones.
@problem
Weak reasons produce double cost with little benefit.
@does
- Good: regulatory or customer requirement, an acquisition, a best-in-class service that matters to the business, data residency in a country where only one provider is present, a negotiated commercial position.
- Weak: "avoid lock-in" with no exit plan, "resilience" without ever testing a cross-cloud failover, "everyone does it".
- A provider-wide outage is rare compared with application bugs and bad deployments, so zone and region design usually gives more resilience per unit of money.
@diagram flow
caption: Test the reason
numbered: true
nodes:
  - "Reason|write it down|plain"
  - "Alternative|can one cloud meet it|info"
  - "Cost|people, data transfer, tools|warn"
  - "Decision|ADR with review date|ok"
@choose Second cloud
Add a second cloud | a hard requirement or unique service exists | the only reason is fear of lock-in
Stay single cloud, design for exit | most products | a regulator mandates diversity
Hybrid | data must stay on premises | you have no one to run the hardware
@check
Is fear of lock-in alone a strong reason? || No, it needs a concrete requirement and a tested exit plan.
@end

@concept The hidden costs
@plain
Each extra cloud multiplies people, process and data movement costs.
@problem
Licence costs are visible. Skill, tooling and egress costs show up later.
@does
- Skills: identity, networking, security and observability differ on each cloud.
- Tools: pipelines, policy, cost reporting and monitoring must span both, or be duplicated.
- Data gravity: moving data out is billed as egress, and chatty services across clouds add latency.
- Lowest common denominator: using only features both clouds share forfeits the reason for choosing a cloud.
@diagram layers
caption: What multiplies
layers:
  - {label: "People", nodes: ["Two skill sets|training and hiring|warn"]}
  - {label: "Platform", nodes: ["Two IAM models|different policy languages|warn", "Two networks|extra links|warn"]}
  - {label: "Data", nodes: ["Egress charges|per GB out|bad", "Latency|between clouds|bad"]}
@h Egress arithmetic
Replicating 5 TB a month between clouds at an example 0.09 per GB egress: 5 x 1024 x 0.09 = 460.80 per month, or 5,529.60 a year, before any link or transfer service cost. Prices vary; check current rates.
```python title="egress.py"
print(round(5 * 1024 * 0.09, 2), round(5 * 1024 * 0.09 * 12, 2))
```
@check
Why can multi-cloud raise cost even if prices are lower? || Egress, duplicate tooling and extra skills outweigh unit savings.
@end

@concept Reducing lock-in without going multi-cloud
@plain
You can keep options open on one cloud by choosing open interfaces for the parts that are costly to move.
@problem
Total avoidance of provider features is impractical, but some lock-in is far costlier than others.
@does
- Prefer open standards: Kubernetes, PostgreSQL and MySQL, S3-compatible object APIs, OpenTelemetry, Prometheus, Terraform or OpenTofu, OCI images.
- Accept deep integration where payoff is high, such as identity and serverless glue, and record it.
- Keep data exportable: regular dumps in open formats.
- Estimate switching cost: engineers x weeks, data transfer, retraining, risk.
@diagram layers
caption: Portability by layer
layers:
  - {label: "Portable", nodes: ["OCI images|run anywhere|ok", "SQL engines|PostgreSQL, MySQL|ok", "OpenTelemetry|telemetry|ok"]}
  - {label: "Mostly portable", nodes: ["Kubernetes|add-ons differ|info", "Terraform|providers differ|info"]}
  - {label: "Locked in", nodes: ["Proprietary databases|API specific|warn", "Event services|semantics differ|warn"]}
@h Exit cost estimate
```yaml title="exit-estimate.yaml" nocheck
engineers: 6
weeks: 20
loaded_cost_per_engineer_week_usd: 4000
data_transfer_tb: 200
egress_per_gb_usd: 0.09
```
Labour 6 x 20 x 4000 = 480,000. Data 200 x 1024 x 0.09 = 18,432. Total about 498,432 before parallel run costs. A number like this makes the lock-in conversation concrete.
@check
Name three portable technologies. || Containers, PostgreSQL or MySQL, OpenTelemetry (also Terraform, Prometheus).
@end

@concept Patterns for multi-cloud when you need it
@plain
If a second cloud is justified, choose a pattern that limits coupling.
@problem
Ad hoc spread creates chatty cross-cloud calls and unclear ownership.
@does
- **Workload split**: each application lives wholly in one cloud, with clean APIs between them.
- **Data on one side, compute near it**: avoid moving large data.
- **Burst or backup target**: a second cloud for backups or batch bursts.
- **Common control plane**: one identity provider, one CI/CD, one observability stack across clouds.
- Use federation for access, never copied long-lived keys.
@diagram flow
caption: Common control plane
nodes:
  - "Identity provider|single sign-on|cp"
  - "CI/CD|one pipeline|app"
  - "Cloud A workloads|apps|info"
  - "Cloud B workloads|apps|info"
  - "Observability|one view|ok"
@h Federation for pipelines
```yaml title="github-oidc.yml" nocheck
permissions:
  id-token: write
  contents: read
jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::111122223333:role/deploy
          aws-region: eu-west-1
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: projects/123/locations/global/workloadIdentityPools/gh/providers/github
          service_account: deployer@demo-project.iam.gserviceaccount.com
```
@check
What replaces copied cloud keys in pipelines? || Federated short-lived credentials through OIDC.
@end

@concept Hybrid cloud and edge
@plain
Some workloads stay near the data or the user: factories, hospitals, branches.
@problem
Latency, data rules or sunk hardware keep part of the estate outside public cloud.
@does
- Link with VPN first, dedicated circuits for steady volume, two for resilience.
- Extend cloud management to on-premises: Azure Arc, Google Distributed Cloud, AWS Outposts or EKS Anywhere. Check current product status.
- Keep one identity source and one set of policies.
- Plan DNS and address space jointly.
@diagram flow
caption: Hybrid link
nodes:
  - "On-premises|data center or branch|env"
  - "VPN and dedicated link|two paths|cp"
  - "Cloud hub|routing|info"
  - "Workloads|cloud services|app"
@check
Why keep two links in a hybrid design? || One may fail and a single link is a single point of failure.
@end

@concept Making and recording the decision
@plain
Turn the analysis into an ADR with a trigger to revisit.
@problem
Cloud strategy debates return every year without new information.
@does
- Write the requirement, options, costs, risks, chosen posture and review date.
- Define measurable triggers: price change over 20 percent, new regulation, service retirement.
- Keep an exit plan with data export tested yearly.
@diagram flow
caption: Decision loop
nodes:
  - "Requirement|why more than one cloud|plain"
  - "Options|single, split, hybrid|info"
  - "ADR|costs and risks|app"
  - "Review|on trigger or yearly|ok"
@h ADR extract
```markdown title="0012-cloud-posture.md" nocheck
Decision: primary cloud A, analytics on cloud B, no active-active.
Why: analytics service on B saves one team about 3 months of work.
Cost: 2 skill sets, about 4 TB per month transfer.
Trigger to revisit: transfer cost above 1000 USD per month or a service retirement.
```
@check
What makes a cloud-strategy ADR useful later? || Measurable triggers and a review date.
@end
