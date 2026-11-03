---
title: AWS Service Catalog
minutes: 40
objectives:
  - Publish approved products as portfolios built from CloudFormation or Terraform
  - Control launch with launch constraints, template constraints and tag options
  - Share portfolios across an Organization and manage product versions
---
Service Catalog lets a platform team publish approved infrastructure patterns that other teams launch on their own, without granting them broad permissions.

@concept Portfolios and products
@plain
A **product** is an approved template (for example a standard S3 bucket or a three-tier stack). A **portfolio** groups products and decides who can launch them.
@problem
Developers either wait for tickets or receive wide permissions and build non-compliant resources.
@does
- Products are CloudFormation templates, or Terraform configurations through the Terraform Open Source or Terraform Cloud engine (check the current engine support).
- Each product has versions, so you can ship fixes and deprecate old ones.
- Access is granted to IAM users, groups or roles at portfolio level.
- Launches create a **provisioned product** that can be updated, terminated and tracked.
@diagram flow
caption: Catalog flow
numbered: true
nodes:
  - "Platform team|publishes products|cp"
  - "Portfolio|access list|info"
  - "Developer|launches product|app"
  - "Provisioned product|stack in account|ok"
@h Define a product
```hcl title="catalog.tf"
resource "aws_servicecatalog_portfolio" "platform" {
  name          = "platform-approved"
  description   = "Approved building blocks"
  provider_name = "platform-team"
}

resource "aws_servicecatalog_product" "bucket" {
  name  = "secure-bucket"
  owner = "platform-team"
  type  = "CLOUD_FORMATION_TEMPLATE"
  provisioning_artifact_parameters {
    name         = "v1"
    type         = "CLOUD_FORMATION_TEMPLATE"
    template_url = "https://example-artifacts.s3.amazonaws.com/secure-bucket-v1.yaml"
  }
}

resource "aws_servicecatalog_product_portfolio_association" "bucket" {
  portfolio_id = aws_servicecatalog_portfolio.platform.id
  product_id   = aws_servicecatalog_product.bucket.id
}
```
@check
What is a provisioned product? || The running instance created when a user launches a product.
@end

@concept Launch constraints and least privilege
@plain
A **launch constraint** names an IAM role that Service Catalog assumes to create the resources, so the end user needs no permissions beyond launching.
@problem
Without it, the user would need create rights for every resource in the template, defeating governance.
@does
- The launch role holds only what the product needs.
- The user needs `servicecatalog:*` style permissions for launching and access to the portfolio, but not the underlying service actions.
- Auditing: CloudTrail shows the launching user and the assumed role.
- Constrain the role with a permissions boundary and trust only `servicecatalog.amazonaws.com`.
@diagram seq
caption: Launch with a role
actors: ["Developer|limited IAM|app", "Service Catalog|portfolio check|cp", "Launch role|product permissions|warn"]
steps:
  - "0>1: launch product | req"
  - "1>2: assume launch role | tls"
  - "2>2: CloudFormation creates resources | req"
  - "1>0: product ready | resp"
@h Launch role trust
```json title="launch-trust.json"
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "servicecatalog.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
```
@check
Why does a launch constraint help least privilege? || The user needs no direct create permissions. The service assumes a scoped role.
@end

@concept Template constraints and parameters
@plain
**Template constraints** restrict the parameter values users may pick, for example instance sizes or Regions.
@problem
A flexible template lets users choose an expensive or non-compliant option.
@does
- Rules use conditions on parameters, such as `InstanceType` in an approved list.
- Combined with `AllowedValues` and `AllowedPattern` in the template itself.
- Use **tag options** to enforce tag keys and values chosen from a list.
- Service Catalog applies portfolio tags automatically to launched resources.
@diagram cmp
caption: Guardrails
cards:
  - {h: "Template constraint", kind: warn, items: ["Limits parameter values", "Allowed instance sizes", "Allowed Regions"]}
  - {h: "Tag options", kind: info, items: ["Required tag keys", "Allowed values list", "Cost allocation"]}
@h Rule
```json title="template-rule.json"
{
  "Rules": {
    "SmallOnly": {
      "Assertions": [{
        "Assert": {"Fn::Contains": [["t3.small", "t3.medium"], {"Ref": "InstanceType"}]},
        "AssertDescription": "Only t3.small or t3.medium are allowed"
      }]
    }
  }
}
```
@end

@concept Sharing across accounts
@plain
Portfolios can be shared with accounts or an entire Organization so every account sees the same catalog.
@problem
Copying products by hand to each account causes version drift.
@does
- Share from the management or delegated administrator account to accounts, OUs or the Organization.
- Imported portfolios in recipient accounts stay in sync with the source; recipients add their own access.
- Share launch roles by name: the role must exist in each recipient account (create it with a StackSet).
- Product updates propagate; users choose when to update provisioned products.
@diagram flow
caption: Hub portfolio
nodes:
  - "Hub account|source portfolio|cp"
  - "Share to OU|Organizations|info"
  - "Member accounts|imported portfolio|app"
@h Share to an Organization
```bash title="Share portfolio" nocheck
aws servicecatalog create-portfolio-share --portfolio-id port-abc123def456 \
  --organization-node Type=ORGANIZATION,Value=o-exampleorgid
```
@check
What must exist in each recipient account for a shared launch role? || A role with the same name.
@end

@concept Versions, updates and lifecycle
@plain
Each product has numbered versions. Users update provisioned products to a newer version through a change set.
@problem
Bug fixes and security improvements must reach existing deployments without surprise replacements.
@does
- Mark old versions inactive so new launches cannot choose them.
- Updates use CloudFormation change sets; review replacements for stateful resources.
- Notifications through SNS on provisioned product events.
- Use **provisioning artifacts** from Git via CI: validate with cfn-lint, then publish a new version automatically.
@diagram flow
caption: Version rollout
numbered: true
nodes:
  - "Template change|Git|app"
  - "CI validates|lint and test|info"
  - "New version|published|cp"
  - "Users update|change set|ok"
@h Create a version
```bash title="New version" nocheck
aws servicecatalog create-provisioning-artifact --product-id prod-abc123def456 \
  --parameters 'Name=v2,Type=CLOUD_FORMATION_TEMPLATE,Info={LoadTemplateFromURL=https://example-artifacts.s3.amazonaws.com/secure-bucket-v2.yaml}'
```
@end

@concept Service Catalog versus other approaches
@plain
Service Catalog sits between a free-for-all and fully central ticket-based provisioning.
@problem
Teams need to decide whether a catalog, a module registry or a self-service portal best fits their culture.
@does
- Catalog: console and API self-service with IAM controls, native to AWS and Control Tower.
- Terraform module registry plus pipeline: developer-friendly Git workflow, policy as code with Sentinel or OPA.
- Backstage or an internal portal can sit on top of either.
- Many organizations use Service Catalog for guarded foundational products and Terraform for application stacks.
@diagram cmp
caption: Options
cards:
  - {h: "Service Catalog", kind: cp, items: ["IAM based access", "Launch roles", "Console self-service"]}
  - {h: "Module registry", kind: app, items: ["Git workflow", "Policy as code", "Developer first"]}
@choose Self-service model
Service Catalog | non-engineers or many accounts need guarded launches | a pure Git workflow already works
Module registry with pipeline | engineers own infrastructure in Git | users lack Git or CI access
Internal portal over both | you want one front door | no platform team exists
@check
When prefer Service Catalog? || When you want guarded self-service launches with launch roles and portfolios across accounts.
@end

@concept AppRegistry and governance
@plain
**AWS Service Catalog AppRegistry** groups resources into applications with metadata, so cost, compliance and ownership roll up to an application.
@problem
Resources belong to apps, but accounts see flat lists of resources.
@does
- Create an application, associate CloudFormation stacks or tag-based resources, and attach attribute groups (owner, tier, data classification).
- The `awsApplication` tag is added automatically to associated resources, useful for cost allocation.
- Integrates with Systems Manager application manager and myApplications.
- Use with Budgets and cost allocation tags.
@diagram flow
caption: Application grouping
nodes:
  - "Application|shop|cp"
  - "Attribute group|owner and tier|info"
  - "Resources|stacks and tags|app"
@h Create an application
```bash title="AppRegistry" nocheck
aws servicecatalog-appregistry create-application --name shop --description "Shop platform"
```
@end
