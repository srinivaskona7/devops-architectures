---
title: HCP Terraform, Atlantis and large-scale patterns
minutes: 60
objectives:
  - Compare HCP Terraform and Atlantis as ways to run Terraform from pull requests
  - Configure Atlantis projects and workflows for a monorepo
  - Choose a repository layout and size state to limit blast radius
---
Running Terraform from laptops does not scale. A shared runner with locking, review and policy turns infrastructure changes into a normal pull request flow.

@concept HCP Terraform workspaces and runs
@plain
HCP Terraform (the managed service from HashiCorp, earlier called Terraform Cloud) stores state, runs plans and applies remotely and shows the history in a UI.
@problem
Every team otherwise builds its own state bucket, locking, runners, approvals and audit trail.
@does
- A **workspace** holds state, variables and run history for one stack.
- A **run** is plan then optional policy check then apply. Runs queue, so there are no concurrent writes.
- Triggers: VCS-connected (pull request speculative plans, merge applies), CLI-driven, or API-driven.
- Variables and sets can be shared across workspaces; mark secrets sensitive.
- Pricing and free tier limits change; check the current HashiCorp pricing page.
@diagram flow
caption: A VCS-driven run
numbered: true
nodes:
  - "Pull request|code change|app"
  - "Speculative plan|shown on the PR|info"
  - "Merge|to main|cp"
  - "Apply|after approval|ok"
@h Selecting HCP Terraform in code
```hcl title="cloud block" nocheck
terraform {
  cloud {
    organization = "acme"

    workspaces {
      name = "prod-network"
    }
  }
}
```
@end

@concept HCP Terraform security, agents and policy
@plain
HCP can reach your private network through **agents** and can enforce policy before apply.
@problem
Cloud-hosted runners cannot reach a private cluster API or an internal Git server, and teams want guardrails without reading every plan.
@does
- **Agents** are containers you run in your own network; they pull jobs from HCP over outbound HTTPS only.
- **Dynamic provider credentials** let a run assume an AWS role with OIDC, so no long-lived keys are stored.
- **Policy as code** uses Sentinel or OPA; policies run after the plan and can block the apply.
- **Run tasks** call external tools such as scanners or cost checks.
@diagram flow
caption: Agent in your VPC
nodes:
  - "HCP Terraform|queues the run|ext"
  - "Agent pod|in your cluster, outbound only|app"
  - "AWS and private APIs|reached from inside|ok"
@check
Why do agents only need outbound connections? || They poll HCP for jobs, so no inbound firewall rule is opened into your network.
@end

@concept Atlantis in a pull request flow
@plain
Atlantis is an open source server you host. It listens to pull request webhooks, runs `terraform plan` and posts the output as a comment, then applies when you comment `atlantis apply`.
@problem
You want pull request based Terraform with locking and no SaaS, or you must keep everything inside your network.
@does
- Plans on every push to a pull request when files change.
- Locks the directory and workspace while a pull request is open, so two pull requests cannot change the same stack.
- Apply requirements such as `approved` and `mergeable` gate the apply comment.
- Runs as a pod; the official Helm chart is `runatlantis/atlantis`. Give it an IAM role through IRSA and store the webhook secret in a Kubernetes secret.
@diagram seq
caption: Comment driven apply
actors: ["Engineer|pull request|app", "Git host|webhooks|ext", "Atlantis|runs terraform|cp"]
steps:
  - "0>1: push commit | req"
  - "1>2: webhook | req"
  - "2>1: comment with plan | resp"
  - "0>1: comment atlantis apply | req"
  - "1>2: webhook | req"
  - "2>1: apply output | resp"
@h Commands in the pull request
```text title="Comments" nocheck
atlantis plan -d envs/prod
atlantis apply -d envs/prod
atlantis unlock
```
@end

@concept atlantis.yaml for a monorepo
@plain
The repo file `atlantis.yaml` lists projects, the folder each one lives in and when to autoplan.
@problem
In a monorepo with 40 stacks, you must plan only the stacks that a change touches, including those that use a changed module.
@does
- `projects` entries have `name`, `dir`, optional `workspace` and `autoplan.when_modified` globs.
- Add the module paths to `when_modified` so a module change replans dependents, for example `../../modules/**/*.tf`.
- `workflows` define custom plan and apply steps, such as init with a backend config or running a scanner.
- Server side `repos.yaml` decides which repos may use custom workflows; keep that restricted for security.
@diagram flow
caption: A change finds its stacks
nodes:
  - "Changed files|in the pull request|info"
  - "when_modified globs|match per project|cp"
  - "Projects planned|only the affected ones|ok"
@h Example
```yaml title="atlantis.yaml"
version: 3
automerge: false
projects:
  - name: prod-network
    dir: envs/prod/network
    autoplan:
      enabled: true
      when_modified: ["*.tf", "../../../modules/network/**/*.tf"]
    apply_requirements: [approved, mergeable]
  - name: prod-eks
    dir: envs/prod/eks
    autoplan:
      enabled: true
      when_modified: ["*.tf", "../../../modules/eks/**/*.tf"]
    apply_requirements: [approved, mergeable]
```
:::note
Some settings such as `apply_requirements` may be restricted by server config. Check the current Atlantis docs for your version.
:::
@check
How does a module change trigger plans? || Add the module path to each dependent project's when_modified list.
@end

@concept HCP Terraform or Atlantis or plain CI
@plain
Three ways to run Terraform from Git. They differ in who operates the runner and how much comes built in.
@problem
Picking wrongly gives either operating burden or lock-in you did not want.
@does
- HCP Terraform: managed state, UI, policy, SSO, agents. Cost per resource or seat; vendor service.
- Atlantis: free, self-hosted, simple pull request model. You run it, secure it and upgrade it.
- Plain CI (GitHub Actions with OIDC): most flexible and uses what you have. You write locking, plan comments and approvals yourself.
- OpenTofu is supported by Atlantis and by many CI recipes; HCP Terraform runs Terraform only.
@diagram cmp
caption: Trade-offs
cards:
  - {h: "HCP Terraform", kind: ok, items: ["Managed, policy built in", "Paid at scale", "Terraform only"]}
  - {h: "Atlantis", kind: warn, items: ["Self-hosted and free", "You operate it", "PR comment workflow"]}
  - {h: "Plain CI", kind: info, items: ["Full flexibility", "Build locks and comments", "Reuses your runners"]}
@choose Which runner fits
HCP Terraform | Many teams, wants policy and audit with little operating work | Strict no-SaaS rule or OpenTofu
Atlantis | Self-hosted, pull request flow, small platform team | No one to operate another service
Plain CI | Already standardised on GitHub Actions or GitLab CI | Dozens of stacks needing locking and queueing
@end

@concept Monorepo or polyrepo for infrastructure
@plain
Do all stacks and modules live in one repository, or does each team or stack get its own?
@problem
A wrong choice causes either giant pull requests and slow CI, or version drift and copy-pasted code.
@does
- **Monorepo**: one place, atomic changes across stacks, easy search, shared tooling. Needs path-based CI and CODEOWNERS.
- **Polyrepo**: clear ownership and permissions per repo, fast CI. Modules must be versioned and consumed by tag; drift between repos needs automation such as Renovate.
- A common compromise: one repo for shared **modules** (versioned with tags) and one repo per team for **live** stacks.
- Whatever you choose, state is split per stack, not per repo.
@diagram cmp
caption: Layout options
cards:
  - {h: "Monorepo", kind: ok, items: ["Atomic cross-stack change", "Needs path filters", "One permission scope"]}
  - {h: "Polyrepo", kind: warn, items: ["Clear team ownership", "Module versions drift", "Many pipelines"]}
  - {h: "Modules repo plus live repos", kind: ok, items: ["Tagged modules", "Teams own live code", "Renovate bumps versions"]}
@h Suggested live layout
```text title="Live repository" nocheck
live/
  prod/
    eu-west-1/
      network/
      eks/
      data/
  staging/
    eu-west-1/
      network/
      eks/
```
@end

@concept Stacks, dependency graphs and blast radius
@plain
**Blast radius** is how much one bad apply can damage. Split infrastructure into layers that change at different speeds so a mistake in one cannot reach the rest.
@problem
One state for everything means every plan touches everything, takes long and one error can delete the database.
@does
- Layers by rate of change: foundations (accounts, DNS), network, platform (EKS), data, applications.
- Each layer is its own state. Higher layers read lower ones through outputs, data sources or a parameter store; dependencies flow one way and form a graph without cycles.
- Run order is the topological order of this graph. Tools such as Terragrunt `run-all`, Terraform Stacks in HCP (check current docs) or a CI matrix encode it.
- Add guards: `prevent_destroy` on data, separate IAM roles per layer, and manual approval for lower layers.
- Rule of thumb: if a plan lists more than a few hundred resources, split it.
@diagram layers
caption: Layers and the direction of dependency
layers:
  - {label: "Applications", nodes: ["Helm and GitOps|changes daily|app"]}
  - {label: "Data", nodes: ["RDS, S3, queues|prevent_destroy|warn"]}
  - {label: "Platform", nodes: ["EKS and add-ons|weekly|cp"]}
  - {label: "Network", nodes: ["VPC, subnets, NAT|rarely|info"]}
  - {label: "Foundations", nodes: ["Accounts, DNS, state bucket|almost never|ok"]}
@check
Why must dependencies flow in one direction? || Cycles between stacks make apply order impossible and destroy needs the reverse order; one-way flow keeps both defined.
@end
