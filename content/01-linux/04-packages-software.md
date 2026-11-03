---
title: Packages and software
minutes: 30
objectives:
  - Install, update, inspect and remove software with apt and dnf
  - Explain repositories, signing keys and why pinning matters
  - Build from source when no package exists, and know when not to
---
Most servers are made of packages. Knowing how packages, repositories and signatures work lets you build reproducible images and spot supply-chain risk.

@concept Package managers
@plain
A **package** is a program plus its metadata: version, files, and the other packages it needs. A **package manager** installs it, works out dependencies, and can remove or upgrade it cleanly.
@problem
Installing software by copying files makes it impossible to know what is on a machine, which libraries a program needs, or how to remove it without leaving debris.
@does
- Debian and Ubuntu use `.deb` files with `dpkg` underneath and `apt` on top. Red Hat, Fedora, Rocky and Amazon Linux use `.rpm` with `rpm` underneath and `dnf` on top.
- The manager keeps a database of every installed file, so you can ask which package owns a file.
- It resolves dependencies, verifies signatures, and records transactions you can inspect or undo.
@diagram cmp
caption: The two package families
cards:
  - {h: "Debian family (apt)", kind: app, items: ["Ubuntu, Debian", ".deb packages", "apt update, apt install"]}
  - {h: "Red Hat family (dnf)", kind: env, items: ["RHEL, Rocky, Alma, Fedora, Amazon Linux", ".rpm packages", "dnf install, dnf history"]}
@h Everyday commands
| Task | apt (Debian, Ubuntu) | dnf (RHEL family) |
|---|---|---|
| Refresh the package index | `sudo apt update` | `sudo dnf makecache` |
| Install | `sudo apt install nginx` | `sudo dnf install nginx` |
| Upgrade everything | `sudo apt upgrade` | `sudo dnf upgrade` |
| Remove | `sudo apt remove nginx` | `sudo dnf remove nginx` |
| Search | `apt search nginx` | `dnf search nginx` |
| Which package owns a file | `dpkg -S /usr/sbin/nginx` | `rpm -qf /usr/sbin/nginx` |
| List a package's files | `dpkg -L nginx` | `rpm -ql nginx` |
| Show installed version | `apt policy nginx` | `dnf info nginx` |
| Undo a transaction | not built in | `dnf history undo <id>` |
```bash title="Inspect before and after you install"
apt policy nginx                  # candidate version and which repository supplies it
apt-cache depends nginx | head    # what it pulls in
dpkg -l | wc -l                   # how many packages are installed
```
@check
Does apt update install anything? || No. It only refreshes the list of available packages; apt upgrade installs newer versions.
@end

@concept Repositories and signing keys
@plain
A **repository** is a signed catalogue of packages on a server. Your machine trusts it only if you have installed that repository's public **signing key**.
@problem
Packages run with high privilege. If anyone could publish packages your servers would install, an attacker could take over every machine that updates.
@does
- Each package or its index is signed. The manager verifies the signature with the repository key before installing.
- Third-party repositories (Docker, Kubernetes, HashiCorp, Elastic) need their key added deliberately.
- Scope each key to its own repository (`signed-by=`) instead of trusting it system-wide.
@diagram flow
caption: Why a signature protects the install
numbered: true
nodes:
  - "Publisher signs|with a private key|info"
  - "Mirror serves|any server can host it|plain"
  - "Your machine downloads|index and package|app"
  - "Verifies|against the public key you trust|warn"
  - "Installs|or refuses on mismatch|ok"
@h Adding a third-party repository safely
```bash title="Pattern for adding a signed repository (names are examples)" nocheck
# 1. fetch the key and store it as a dedicated keyring file
curl -fsSL https://example.com/repo/key.gpg | sudo gpg --dearmor -o /etc/apt/keyrings/example.gpg
# 2. reference that exact key from the source line, so it only vouches for this repository
echo "deb [signed-by=/etc/apt/keyrings/example.gpg] https://example.com/repo stable main" \
  | sudo tee /etc/apt/sources.list.d/example.list
sudo apt update && apt policy example-package
```
:::danger
Piping a download straight into a root shell (`curl ... | sudo bash`) runs unreviewed code with full privileges. Download the script first, read it, and prefer packages from signed repositories.
:::
@end

@concept Versions, pinning and updates
@plain
Servers should run known versions and receive security fixes on purpose, not by surprise. **Pinning** fixes a package at a version; **holding** stops it from upgrading.
@problem
An unplanned upgrade can change behaviour or break a service. Not upgrading leaves known vulnerabilities in place. Both are risks, so you need control.
@does
- Pin exact versions in images and in configuration management so builds are reproducible.
- Apply security updates quickly, and test the rest in staging first.
- `unattended-upgrades` (Debian family) or `dnf-automatic` (RHEL family) can install security fixes automatically.
- Hold a package when you must stay on one version: `apt-mark hold <name>`, `dnf versionlock add <name>`.
@diagram flow
caption: A safe patch flow
numbered: true
nodes:
  - "Advisory|CVE published|bad"
  - "Test|staging gets the update|info"
  - "Roll out|canary, then the fleet|app"
  - "Verify|health checks and metrics|ok"
@choose Update policy
Automatic security updates | a stateless fleet with fast rollback | a single stateful server you cannot restart safely
Scheduled patch windows | regulated or stateful systems | you cannot tolerate a growing vulnerability backlog
Immutable images rebuilt regularly | containers and autoscaling groups | the host cannot be replaced easily
@h Hands-on
```bash title="Control versions" lab
apt list --upgradable 2>/dev/null | head       # what would change
sudo apt install nginx=1.24.0-2ubuntu7         # install a specific version (use a version from apt policy)
sudo apt-mark hold nginx                       # stop it being upgraded
apt-mark showhold
sudo apt-mark unhold nginx
```
@end

@concept Building from source
@plain
When no package exists, or you need a special build option, you can compile the program yourself. The classic recipe is configure, make, install.
@problem
Source installs are invisible to the package manager, so they do not receive security updates and are hard to remove or reproduce.
@does
- Install a toolchain (compiler, `make`, headers), then `./configure --prefix=/opt/name && make && sudo make install`.
- Prefer a prefix such as `/opt` or `/usr/local` so it never overwrites packaged files.
- Better still, build once in a container, produce a package (`fpm`, `checkinstall`) or an image, and install that.
@diagram flow
caption: From source to something you can maintain
nodes:
  - "Source tarball|verify the checksum|info"
  - "Build|in a clean container|app"
  - "Package or image|versioned|env"
  - "Install|managed and removable|ok"
@h Verify what you download
```bash title="Checksum and signature habit" nocheck
curl -fsSLO https://example.com/tool-1.2.3.tar.gz
curl -fsSLO https://example.com/tool-1.2.3.tar.gz.sha256
sha256sum -c tool-1.2.3.tar.gz.sha256        # prints "tool-1.2.3.tar.gz: OK" on success
tar -xzf tool-1.2.3.tar.gz && cd tool-1.2.3
./configure --prefix=/opt/tool && make -j"$(nproc)" && sudo make install
```
@choose Package, container image or source
Distribution package | it exists and the version is acceptable | you need a newer feature than it offers
Vendor repository | the vendor signs and maintains packages | the vendor's repository is unmaintained
Container image | you want identical builds everywhere | the tool must be part of the host operating system
Source build | nothing else fits and you can maintain it | you cannot track security fixes yourself
@end
