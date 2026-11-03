---
title: AMIs and image pipelines
minutes: 40
objectives:
  - Explain what an AMI contains and how to share and copy it
  - Build hardened images with Packer or EC2 Image Builder
  - Manage AMI lifecycle, deprecation and EKS-optimized images
---
An **AMI** is the template an instance boots from. A reproducible image pipeline means every node in your fleet starts from a known, patched and tested base.
@concept What an AMI is
@plain
An **Amazon Machine Image** bundles a root volume snapshot, launch permissions and a block device mapping. You launch instances from it in the same Region.
@problem
Installing and configuring software on each new instance is slow and drifts; a golden image makes a boot predictable.
@does
- AMIs are Regional; copy them to other Regions or accounts. Backed by EBS snapshots.
- Choose architecture (x86_64 or arm64), virtualization, boot mode (UEFI or legacy) and IMDS defaults when you register.
- AWS-published AMIs: Amazon Linux 2023, Bottlerocket (container optimised), Ubuntu, Windows and others; SSM public parameters list the current ID.
- Launch permissions: private, specific accounts, organization units, or public. Block public AMI sharing in the account settings.
@diagram flow
caption: From instance to image
numbered: true
nodes:
  - "Base AMI|Amazon Linux or Bottlerocket|plain"
  - "Customise|packages and hardening|app"
  - "Create AMI|snapshots volumes|cp"
  - "Copy and share|Regions and accounts|info"
  - "Launch fleet|from template|ok"
@h Look up and share
```bash title="AMI commands" lab
aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 --query Parameter.Value --output text
aws ec2 describe-images --owners self --query 'Images[].[ImageId,Name,CreationDate]' --output table
aws ec2 modify-image-attribute --image-id ami-0123456789abcdef0 --launch-permission 'Add=[{OrganizationArn=arn:aws:organizations::111122223333:organization/o-exampleorgid}]'
aws ec2 enable-image-block-public-access --image-block-public-access-state block-new-sharing
```
@check
Can you launch an AMI in another Region directly? || No. Copy it to that Region first.
@end

@concept Packer
@plain
**Packer** builds machine images from code. It launches a temporary instance, runs provisioners, snapshots it as an AMI and cleans up.
@problem
Hand-built images cannot be reviewed or reproduced.
@does
- HCL2 configuration with an `amazon-ebs` source and provisioners (shell, Ansible).
- Run in CI; tag the AMI with commit, base AMI and build date.
- Use a temporary security group and IAM role; keep secrets out of the image.
@diagram flow
caption: Packer build
nodes:
  - "packer build|from CI|cp"
  - "Temporary instance|provision scripts|app"
  - "AMI|tagged and encrypted|ok"
  - "Terminated|build instance removed|plain"
@h Template
```hcl title="image.pkr.hcl"
packer {
  required_plugins {
    amazon = {
      source  = "github.com/hashicorp/amazon"
      version = ">= 1.3.0"
    }
  }
}

source "amazon-ebs" "base" {
  region        = "eu-west-1"
  instance_type = "m7g.large"
  ssh_username  = "ec2-user"
  ami_name      = "platform-base-{{timestamp}}"
  source_ami_filter {
    filters = {
      name                = "al2023-ami-2023*-arm64"
      root-device-type    = "ebs"
      virtualization-type = "hvm"
    }
    owners      = ["amazon"]
    most_recent = true
  }
  encrypt_boot = true
  tags = {
    built_by = "packer"
  }
}

build {
  sources = ["source.amazon-ebs.base"]
  provisioner "shell" {
    inline = ["sudo dnf -y update", "sudo dnf -y install amazon-cloudwatch-agent"]
  }
}
```
@end

@concept EC2 Image Builder
@plain
**EC2 Image Builder** is the managed AWS pipeline for images: recipes, components, tests, distribution and scheduled rebuilds.
@problem
You want automatic rebuilds when the base image gets patched, with tests and distribution, without running build servers.
@does
- A **recipe** has a parent image and ordered **components** (build and test steps, YAML documents).
- **Pipeline** schedule or event triggers a build; **infrastructure configuration** sets the build instance profile and subnet.
- **Distribution** copies AMIs to Regions and shares with accounts, and publishes the AMI ID to an SSM parameter for launch templates to read.
- Integrates with Inspector for vulnerability scanning.
@diagram layers
caption: Image Builder pieces
layers:
  - {label: "Definition", nodes: ["Recipe|parent image and components|app", "Components|YAML build and test steps|app"]}
  - {label: "Execution", nodes: ["Pipeline|schedule or on new base|cp", "Infra config|instance profile and subnet|env"]}
  - {label: "Output", nodes: ["Distribution|Regions and accounts|info", "SSM parameter|latest AMI ID|ok"]}
@h Component document
```yaml title="harden-component.yaml"
name: harden
description: Basic hardening
schemaVersion: 1.0
phases:
  - name: build
    steps:
      - name: DisableRootSsh
        action: ExecuteBash
        inputs:
          commands:
            - sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
  - name: test
    steps:
      - name: CheckSshd
        action: ExecuteBash
        inputs:
          commands:
            - grep -q '^PermitRootLogin no' /etc/ssh/sshd_config
```
@choose Image tooling
EC2 Image Builder | managed, scheduled, AWS-native | multi-cloud images from one tool
Packer | one tool for many clouds and local testing | you want no build code to maintain
Bottlerocket | container hosts, immutable | you need general-purpose package management
@check
How does a launch template learn about a new AMI? || From an SSM parameter updated by the pipeline, resolved with resolve:ssm in the template.
@end

@concept EKS-optimized AMIs and Bottlerocket
@plain
EKS provides AMIs with kubelet and container runtime preinstalled. **Bottlerocket** is a minimal, immutable, container-focused OS.
@problem
General-purpose OS images contain much that a node never needs, increasing patch burden and attack surface.
@does
- Amazon Linux 2023 and Bottlerocket variants of the EKS-optimized AMI exist per Kubernetes version and architecture; look up the current ID via an SSM parameter under `/aws/service/eks/optimized-ami/`. Check supported OS families as they change.
- Bottlerocket updates as a whole image; configuration via TOML user data, no SSH by default (use the admin container through SSM).
- Managed node groups use these automatically and can roll to a new AMI version through an update.
- Custom AMIs for EKS must keep the bootstrap contract (nodeadm for AL2023).
@diagram flow
caption: Keeping nodes current
numbered: true
nodes:
  - "New EKS AMI release|upstream patches|ext"
  - "Pipeline rebuild|tests|cp"
  - "Template version|new AMI|info"
  - "Roll nodes|instance refresh or node group update|app"
  - "Verify|workloads healthy|ok"
@h Look up the recommended AMI
```bash title="Find the current EKS AMI" lab
aws ssm get-parameter --name /aws/service/eks/optimized-ami/{{v.eks_to}}/amazon-linux-2023/arm64/standard/recommended/image_id \
  --query Parameter.Value --output text
aws ssm get-parameter --name /aws/service/bottlerocket/aws-k8s-{{v.eks_to}}/arm64/latest/image_id --query Parameter.Value --output text
```
:::note
Replace {{v.eks_to}} with a Kubernetes version that EKS currently supports. Parameter names and available OS flavours change over time.
:::
@end

@concept AMI lifecycle and deprecation
@plain
Old AMIs accumulate snapshots, cost money, and may contain vulnerabilities. A lifecycle policy removes them.
@problem
Hundreds of forgotten images and snapshots cost storage and confuse people about which one is current.
@does
- Set a **deprecation time** so old AMIs are hidden from searches and warn users.
- **Data Lifecycle Manager** can create, copy, deprecate and delete AMIs on a schedule.
- Deregistering an AMI does not delete its snapshots; remove those as well.
- Tag by pipeline and date; keep the last few known-good versions for rollback.
@diagram flow
caption: Retiring an image
nodes:
  - "Current|used by templates|ok"
  - "Deprecated|hidden from search|warn"
  - "Deregistered|cannot launch|bad"
  - "Snapshots deleted|storage freed|plain"
@h Clean up
```bash title="Deprecate and deregister" lab
aws ec2 enable-image-deprecation --image-id ami-0123456789abcdef0 --deprecate-at 2026-12-31T00:00:00Z
aws ec2 deregister-image --image-id ami-0aaa
aws ec2 describe-snapshots --owner-ids self --filters Name=description,Values="*ami-0aaa*" --query 'Snapshots[].SnapshotId'
```
@end
