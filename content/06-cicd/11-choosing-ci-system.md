---
title: Choosing a CI/CD system
minutes: 40
objectives:
  - Compare GitHub Actions, Jenkins, GitLab CI, CircleCI and Kubernetes-native engines on concrete criteria
  - Apply a decision matrix to your own constraints
  - Plan a migration without a big bang
---
There is no best tool, only a best fit for your repositories, network, team skills and compliance rules. Decide with criteria, not preference.

@concept The decision matrix
@plain
A matrix scores each tool on the criteria that matter to you. This one summarises typical strengths. Treat entries as general tendencies and verify against current product docs and your plan.
@problem
Tool choice is often driven by habit or by whoever spoke last. That locks in cost and maintenance for years.
@does
- Compare hosting model, ease of start, flexibility, private network access, ecosystem, operating effort and cost model.
- Weight the rows by your needs, then compare totals and risks.
- Remember that two tools often coexist: a CI tool builds, and a GitOps tool deploys.
@diagram cmp
caption: Typical tendencies, not benchmarks
cards:
  - {h: "GitHub Actions", kind: ok, items: ["Hosted, tied to GitHub", "Huge marketplace", "Pinning needed for safety", "Per-minute billing"]}
  - {h: "Jenkins", kind: warn, items: ["Self-run, most flexible", "Plugin ecosystem", "You own upgrades and security", "Free software, people cost"]}
  - {h: "GitLab CI", kind: app, items: ["Integrated in GitLab", "Strong built-in security and registry", "Self-managed or SaaS"]}
  - {h: "CircleCI", kind: info, items: ["Hosted, Git host agnostic", "Fast caching and splitting", "Credit-based pricing"]}
  - {h: "Tekton or Argo Workflows", kind: cp, items: ["Run in your cluster", "Pipelines are CRDs", "Most to build and operate"]}
@h Capture your criteria as data
```yaml title="Weighted scoring sheet (fill in your scores 1 to 5)"
criteria:
  - {name: Private network access, weight: 5}
  - {name: Operating effort, weight: 4}
  - {name: Ecosystem and reuse, weight: 3}
  - {name: Compliance and audit, weight: 4}
  - {name: Cost at our volume, weight: 3}
tools: [github-actions, jenkins, gitlab-ci, circleci, tekton]
scores:
  github-actions: [3, 4, 5, 4, 3]
  jenkins: [5, 2, 4, 3, 3]
  gitlab-ci: [4, 3, 4, 5, 3]
  circleci: [3, 4, 3, 3, 3]
  tekton: [5, 1, 2, 3, 4]
```
```python title="Compute the weighted totals" lab
weights = [5, 4, 3, 4, 3]
scores = {
    "github-actions": [3, 4, 5, 4, 3],
    "jenkins": [5, 2, 4, 3, 3],
    "gitlab-ci": [4, 3, 4, 5, 3],
    "circleci": [3, 4, 3, 3, 3],
    "tekton": [5, 1, 2, 3, 4],
}
for tool, s in sorted(scores.items(), key=lambda kv: -sum(w * x for w, x in zip(weights, kv[1]))):
    print(tool, sum(w * x for w, x in zip(weights, s)))
```
:::note
The scores are an example, not a verdict. Your weights change the answer.
:::
@check
Why should the matrix weights come first? || Otherwise the scores reflect preference rather than the constraints you actually have.
@end

@concept Hosting model and operating effort
@plain
Hosted services take away servers and upgrades but bring cost per minute and less network control. Self-managed systems give control at the price of operating them.
@problem
A small team running its own Jenkins spends days on upgrades, plugins and disk space instead of delivering.
@does
- Hosted: GitHub Actions, GitLab.com, CircleCI. Operations are the vendor's job.
- Self-managed: Jenkins, GitLab self-managed, Tekton, Argo Workflows. You patch, scale and back them up.
- Hybrid: hosted control plane with self-hosted runners (Actions with ARC, GitLab runners, CircleCI runner) gives private access with less to run.
@diagram layers
caption: Where the effort sits
layers:
  - {label: "You operate everything", nodes: ["Jenkins|controller, agents, plugins|warn", "Tekton and Argo Workflows|cluster operators|warn"]}
  - {label: "You operate execution", nodes: ["Actions with ARC|runners only|info", "GitLab runners|runners only|info"]}
  - {label: "Vendor operates", nodes: ["GitHub-hosted runners|managed|ok", "CircleCI cloud|managed|ok"]}
@h Hybrid example
```yaml title="Hosted control plane, private execution"
name: deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: [self-hosted, linux, vpc-prod]
    steps:
      - uses: actions/checkout@v4
      - run: kubectl -n shop rollout status deploy/shop
```
@check
What does the hybrid model give you? || Private network access with the vendor handling the control plane.
@end

@concept Ecosystem, lock-in and portability
@plain
Every tool has its own YAML or Groovy dialect. Moving between them is costly if all logic lives in that dialect.
@problem
Years of pipeline code in one tool's syntax become a migration project when pricing, policy or company direction changes.
@does
- Keep real logic in scripts, Makefiles, Dagger-style code pipelines or containers that any CI can call.
- Keep the CI file thin: checkout, cache, call script, publish.
- Use standard formats at the boundaries: OCI images, JUnit XML, SARIF, SBOM, OIDC.
- Abstract deployments with GitOps so the CI tool only produces an image and a Git commit.
@diagram flow
caption: Portable pipeline layering
nodes:
  - "CI file|thin glue|plain"
  - "Scripts and Makefile|real logic|app"
  - "Container tools|pinned images|info"
  - "Standard outputs|OCI, JUnit, SARIF|ok"
@h Same script, any CI
```bash title="ci/build.sh" lab
#!/usr/bin/env bash
set -euo pipefail
TAG="${1:?usage: build.sh TAG}"
make lint test
docker build -t "shop:${TAG}" .
```
:::tip
If every pipeline line is `./ci/something.sh`, switching CI products becomes a matter of rewriting twenty lines, not twenty thousand.
:::
@end

@concept Security and compliance fit
@plain
Different systems offer different built-in controls: audit logs, protected environments, approvals, secrets management and SSO. Match them to your compliance obligations.
@problem
Discovering after adoption that a tool cannot restrict who deploys to production, or cannot keep audit logs for the required period, forces rework.
@does
- Check: SSO and SCIM, fine-grained permissions, audit log export, approval gates, secret scoping, OIDC to cloud, runner isolation.
- GitHub environments, GitLab protected environments and Jenkins folder permissions each solve approvals differently.
- Plan-level limits exist for several features. Verify them for your plan before relying on them.
@diagram cmp
caption: Questions to ask any vendor
cards:
  - {h: "Identity", kind: info, items: ["SSO and group mapping", "Service accounts"]}
  - {h: "Control", kind: warn, items: ["Approvals", "Protected branches and environments"]}
  - {h: "Evidence", kind: ok, items: ["Audit log retention", "Export to your SIEM"]}
@h Auditing example
```bash title="Pull recent audit events (enterprise features, check your plan)" lab nocheck
gh api /orgs/my-org/audit-log --paginate -f phrase='action:workflows' --jq '.[].action' | sort | uniq -c
```
@check
Which feature binds a production deploy to an approval? || Environments with required reviewers in GitHub, protected environments in GitLab, or input steps in Jenkins.
@end

@concept Cost models
@plain
Hosted tools charge per minute, per credit or per seat. Self-managed tools charge for compute and for people. The cheaper option depends on volume and utilisation.
@problem
Comparing sticker prices misses idle runners, operator time and the cost of waiting for slow builds.
@does
- Estimate minutes: runs per day times average duration times jobs per run.
- Add runner size multipliers for larger or macOS runners. Check the current price lists.
- For self-managed, add node cost, storage, egress and a fraction of an engineer.
- Developer wait time is a cost too: ten minutes saved on 50 engineers' daily builds is substantial.
@diagram flow
caption: Build a cost estimate
nodes:
  - "Measure minutes|per month|info"
  - "Price per minute|by runner type|app"
  - "Add operations|nodes and people|warn"
  - "Compare|total cost of ownership|ok"
@h Quick estimate
```python title="Monthly minutes and cost (prices are placeholders)" lab
runs_per_day = 120
jobs_per_run = 4
avg_minutes = 6
workdays = 21
price_per_minute = 0.008     # placeholder, take the real figure from the price list
minutes = runs_per_day * jobs_per_run * avg_minutes * workdays
print("minutes", minutes)
print("cost", round(minutes * price_per_minute, 2))
```
@check
What cost is often forgotten for self-hosting? || Operator time, idle capacity and developer wait time.
@end

@concept A pragmatic recommendation
@plain
For a team on GitHub that deploys to EKS, the common modern pattern is GitHub Actions for CI, runners in the VPC if private access is needed, OIDC to AWS, and Argo CD or Flux for deployment.
@problem
Overbuilding the platform delays value. Under-building leaves manual steps and secrets in places they should not be.
@does
- Start hosted. Add self-hosted runners only for a proven need.
- Keep Jenkins where large investments exist, but freeze new custom plugins and move deploys to GitOps.
- Use GitLab CI naturally if you already run GitLab.
- Use Argo Workflows or Tekton for data or platform jobs that should live inside the cluster.
@diagram flow
caption: A common modern split
nodes:
  - "Git host|pull request and review|plain"
  - "CI|build, test, scan, push image|app"
  - "Config repo|new image digest|info"
  - "Argo CD or Flux|sync to EKS|ok"
@h Responsibility split
```yaml title="CI only updates the config repository"
name: promote
on:
  workflow_run:
    workflows: [build]
    types: [completed]
permissions:
  contents: read
jobs:
  bump:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    runs-on: ubuntu-latest
    steps:
      - run: echo "open a pull request in the config repo with the new image digest"
```
@end

@concept Migrating between systems
@plain
Migrate in slices, not all at once. Run the old and new pipelines side by side, compare results, then cut over service by service.
@problem
Big-bang migrations stall releases and hide differences until the cutover day.
@does
- Inventory pipelines and group them by pattern; a handful of templates usually covers most.
- Convert the template first, then pilot with one low-risk service.
- Tools such as GitHub Actions Importer help translate Jenkins, GitLab and CircleCI pipelines. Check current docs for supported sources.
- Run both for a period, compare duration, flakiness and outputs, then decommission.
@diagram flow
caption: Slice-by-slice migration
numbered: true
nodes:
  - "Inventory|group by pattern|plain"
  - "Template|convert once|app"
  - "Pilot service|run in parallel|warn"
  - "Cut over|then retire old job|ok"
@h Audit what you have
```bash title="Dry run of the importer" lab nocheck
gh extension install github/gh-actions-importer
gh actions-importer audit jenkins --output-dir audit
gh actions-importer dry-run jenkins --source-url https://jenkins.example.com/job/shop --output-dir out
```
@check
What is the safest way to switch a service to the new CI? || Run both pipelines side by side, compare, then cut over and retire the old one.
@end
