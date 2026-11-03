---
title: Module sources, versioning and the registry
minutes: 45
objectives:
  - Choose a module source such as local path, Git tag or registry and pin it correctly
  - Version and release internal modules safely with semantic versioning
  - Use community modules wisely and manage upgrades
---
Once a module is shared, its version matters more than its code. This section covers where modules come from and how to change them without breaking consumers.

@concept Module sources
@plain
The `source` argument says where Terraform downloads a module from during `init`: a local path, a Git repository, a registry, an S3 bucket and more.
@problem
Teams need one way to reuse code within a repo and another across repositories and organisations.
@does
- Local: `./modules/network` (always the current checkout, no version).
- Git: `git::https://github.com/acme/terraform-aws-network.git?ref=v1.4.0` (tag, branch or commit).
- Registry: `terraform-aws-modules/vpc/aws` with a separate `version` argument.
- `terraform init` copies modules into `.terraform/modules`; `terraform get` refreshes them.
- Monorepo subdirectory: `git::https://...//modules/network?ref=v1.4.0` (double slash).
@diagram cmp
caption: Source types
cards:
  - {h: "Local path", kind: info, items: ["Fast iteration", "No versions"]}
  - {h: "Git tag", kind: ok, items: ["Immutable with a tag", "Needs repo access in CI"]}
  - {h: "Registry", kind: ok, items: ["Semantic versions", "Public or private registry"]}
@h Examples
```hcl title="Three sources"
module "local" {
  source = "./modules/network"
}

module "git" {
  source = "git::https://github.com/acme/terraform-aws-network.git?ref=v1.4.0"
}

module "registry" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"
}
```
@end

@concept Pinning versions
@plain
Always pin a module to a version or tag. Unpinned modules change when the source repository changes.
@problem
If production tracks `main`, an unrelated merge in the module repo changes your next plan, and you cannot reproduce last week's run.
@does
- Registry modules use `version` constraints; Git modules use `?ref=` with a **tag** or commit SHA, not a moving branch.
- Use exact versions for production roots and `~>` ranges only where you review upgrades.
- Dependency tools such as Renovate and Dependabot open upgrade pull requests for module and provider versions.
- Read the changelog and the plan in that pull request.
@diagram flow
caption: Upgrade through a reviewed pull request
numbered: true
nodes:
  - "Module repo tags v1.5.0|release|app"
  - "Renovate opens PR|bumps the ref|info"
  - "CI plan|shows effects|cp"
  - "Review and merge|applied by pipeline|ok"
@check
Why is ?ref=main a bad pin? || A branch moves, so the same code can produce different plans over time.
@end

@concept Semantic versioning for modules
@plain
Version numbers MAJOR.MINOR.PATCH tell consumers the risk: patch fixes bugs, minor adds backward compatible features, major may break callers.
@problem
Consumers need to know whether upgrading will change their infrastructure.
@does
- **Breaking** changes: removing or renaming a variable or output, changing a default that alters resources, renaming resources without a `moved` block, raising the minimum provider major version.
- **Minor**: adding an optional variable with a default that changes nothing, adding an output.
- Add `moved` blocks inside the module so internal renames do not destroy resources for callers.
- Record changes in a CHANGELOG and tag releases.
@diagram cmp
caption: What each part signals
cards:
  - {h: "PATCH 1.4.1", kind: ok, items: ["Bug fix", "No interface change"]}
  - {h: "MINOR 1.5.0", kind: info, items: ["New optional input or output", "Existing plans unchanged"]}
  - {h: "MAJOR 2.0.0", kind: warn, items: ["Breaking change", "Upgrade notes required"]}
@h Release routine
```bash title="Tagging a module release" lab
git tag -a v1.5.0 -m "Add optional flow logs"
git push origin v1.5.0
git ls-remote --tags origin | tail -3
```
@end

@concept The Terraform and OpenTofu registries
@plain
A registry hosts modules and providers with documentation and versions. The public Terraform Registry is registry.terraform.io; OpenTofu has registry.opentofu.org.
@problem
Finding, trusting and versioning shared code through Git URLs alone is clumsy.
@does
- Public modules follow the naming `terraform-<PROVIDER>-<NAME>` in a GitHub repository, and releases are tags like `v1.2.3`.
- Private registries exist in HCP Terraform and Terraform Enterprise, and in tools like GitLab and Artifactory. Check each product's current documentation.
- Provider mirrors and caches can be configured for air-gapped or rate-limited environments.
@diagram flow
caption: From repository to consumer
nodes:
  - "GitHub repo|terraform-aws-network|app"
  - "Tag v1.2.3|release|info"
  - "Registry|docs and versions|cp"
  - "Consumer|source plus version|ok"
@h Registry style call
```hcl title="Private or public registry"
module "network" {
  source  = "app.terraform.io/acme/network/aws"
  version = "1.2.3"
}
```
@end

@concept Community modules
@plain
Widely used modules, such as `terraform-aws-modules/vpc/aws`, `eks/aws` and `rds/aws`, cover most needs with many inputs.
@problem
Writing your own VPC or EKS module costs weeks and ongoing maintenance, but blindly adopting a huge module can lock you into its design.
@does
- Pros: tested by many users, documented, and maintained for new provider releases.
- Cons: large interfaces, major version changes with migration steps, and behaviours you must learn.
- Read the upgrade guide before bumping a major version, and always review the plan.
- Wrap them in a thin internal module only when you add organisational defaults (tags, encryption, logging); do not wrap just to rename.
@diagram cmp
caption: Build or adopt
cards:
  - {h: "Adopt community", kind: ok, items: ["Complex area like EKS", "Active maintainers"]}
  - {h: "Write your own", kind: info, items: ["Simple, specific needs", "Strong company standards"]}
  - {h: "Fork", kind: warn, items: ["You own all maintenance", "Last resort"]}
@choose Where to get a module
Community registry module | a complex area such as VPC or EKS with active maintenance | you need a tiny subset and the interface is huge
Internal module | company defaults and a narrow, stable need | an equal community module already fits
Raw resources | a one-off stack nobody else will reuse | the pattern repeats across teams
@end

@concept Composition patterns: facade and data-only modules
@plain
Teams often add a layer of internal modules that combine lower-level ones with company defaults, such as a "service" module that creates an ECR repo, IAM role and log group together.
@problem
Application teams should not need to know all details of AWS for every new service.
@does
- A **facade** module exposes 5 to 10 inputs and calls several resources or modules with standard settings.
- Keep a path to escape hatches: outputs expose enough that teams can add their own resources next to it.
- A data-only module returns lookups (shared VPC, account IDs, tags) and has no resources; use sparingly.
- Version each layer separately.
@diagram layers
caption: Layered modules
layers:
  - {label: "Platform facades", nodes: ["service|ECR, IAM, logs|cp", "database|RDS with standards|cp"]}
  - {label: "Building blocks", nodes: ["network|VPC|app", "eks|cluster|app", "iam-role|IRSA role|app"]}
  - {label: "Provider resources", nodes: ["aws_* resources|raw API objects|plain"]}
@h Facade example
```hcl title="service module call"
module "checkout" {
  source = "git::https://github.com/acme/tf-modules.git//service?ref=v2.3.0"

  name        = "checkout"
  environment = "prod"
  cpu         = 512
  memory      = 1024
}
```
@end

@concept Upgrading and refactoring modules safely
@plain
Changing a module changes every consumer. A safe release process keeps plans small and predictable.
@problem
A module refactor that renames resources would destroy and recreate production infrastructure for everyone.
@does
- Add `moved` blocks for each renamed resource inside the module.
- Test with `terraform test` and an example that runs plan against a real or mocked provider.
- Release a minor version and let consumers upgrade one environment at a time: dev first, production last.
- Deprecate before removing: keep the old variable for one major version with a warning in the description.
@diagram flow
caption: Roll a module change through environments
numbered: true
nodes:
  - "Release v1.6.0|moved blocks added|app"
  - "Dev|plan shows no changes|ok"
  - "Staging|apply and verify|info"
  - "Prod|last|warn"
@h Inside the module
```hcl title="moved.tf in the module"
moved {
  from = aws_subnet.private_a
  to   = aws_subnet.private["a"]
}
```
@check
Which block keeps a renamed resource from being destroyed? || A moved block mapping the old address to the new one.
@end
