---
title: Building packages and running repositories
minutes: 45
objectives:
  - Explain what a package contains and why distributions use them
  - Build a simple deb and an rpm package
  - Create and sign a package repository and consume it safely
  - Use fpm and CI to automate packaging
---
Containers did not replace packages. Base images, agents on nodes, CLIs and kernel modules are still delivered as deb or rpm. Knowing how to build and publish them lets you ship software to VMs with the same discipline as images.

@concept What a package is
@plain
A package is an archive of files plus metadata: name, version, dependencies and scripts to run on install and removal. The package manager tracks what it installed so it can upgrade and remove cleanly.
@problem
Copying files by hand leaves no record of what is installed, cannot resolve dependencies and breaks on upgrade.
@does
- **deb** (Debian, Ubuntu) uses `dpkg` and `apt`. **rpm** (RHEL, Fedora, Amazon Linux, SUSE) uses `rpm` and `dnf` or `zypper`.
- Metadata: version, architecture, dependencies, maintainer scripts (preinst, postinst, prerm, postrm).
- Tools query the database: which package owns this file, what files does it have.
@diagram flow
caption: Low level and high level tools
nodes:
  - "apt or dnf|resolves dependencies, downloads|app"
  - "dpkg or rpm|installs files, tracks database|cp"
  - "Filesystem|files placed|env"
@h Query
```bash title="Inspect installed packages" lab
dpkg -S /bin/ls 2>/dev/null || rpm -qf /bin/ls          # which package owns it
dpkg -L coreutils 2>/dev/null | head -5 || rpm -ql coreutils | head -5
dpkg -s bash 2>/dev/null | grep -E 'Version|Depends' || rpm -qi bash | head -5
```
@check
Which tool resolves dependencies, dpkg or apt? || apt; dpkg installs a given file without fetching dependencies.
@end

@concept Versioning and dependencies
@plain
Package versions follow a scheme the manager can compare. Dependencies state which other packages and versions must be present.
@problem
Without rules, an upgrade could install an incompatible library, and users cannot tell whether a rebuilt package is newer.
@does
- Debian: `upstream-revision`, for example `1.4.2-1`. RPM: `version-release`, for example `1.4.2-1.el9`. A rebuild increases only the revision.
- Semantic versioning (major.minor.patch) is the upstream convention: major breaks compatibility, minor adds features, patch fixes bugs.
- Pre-releases need care in dpkg: use `~` (so `1.0~rc1` sorts before `1.0`).
@diagram cmp
caption: Version fields
cards:
  - {h: "Upstream version", kind: info, items: ["1.4.2 comes from the project", "Changes with new releases"]}
  - {h: "Package revision", kind: app, items: ["-1, -2 ... for packaging fixes", "Resets on new upstream version"]}
@h Compare versions
```bash title="How the manager orders versions" lab
dpkg --compare-versions 1.0~rc1 lt 1.0 && echo "1.0~rc1 < 1.0"
dpkg --compare-versions 1.10 gt 1.9 && echo "1.10 > 1.9 (numeric, not text)"
sort -V <<< $'1.9\n1.10\n1.2' | tr '\n' ' '
```
@end

@concept Building a deb package with a control file
@plain
A minimal deb needs a directory tree mirroring the install paths and a `DEBIAN/control` file. `dpkg-deb --build` turns it into a package.
@problem
You want to ship an internal tool or a systemd unit to many machines in a repeatable way.
@does
- The tree under `pkg/` maps to `/`: `pkg/usr/local/bin/hello` installs to `/usr/local/bin/hello`.
- `control` fields: Package, Version, Architecture, Maintainer, Depends, Description.
- Permissions in the tree become permissions on install, so set them before building.
- For real distribution packages use `debhelper` and `dpkg-buildpackage`; the minimal method is fine for internal tools.
@diagram flow
caption: Minimal deb build
numbered: true
nodes:
  - "Tree|files under pkg/|plain"
  - "control file|metadata|info"
  - "dpkg-deb --build|creates .deb|app"
  - "dpkg -i|installs it|ok"
@h Build one
```bash title="hello_1.0-1_all.deb" lab
mkdir -p /tmp/pkg/usr/local/bin /tmp/pkg/DEBIAN && cd /tmp
printf '#!/bin/sh\necho "hello from a package"\n' > pkg/usr/local/bin/hello && chmod 755 pkg/usr/local/bin/hello
cat > pkg/DEBIAN/control <<'EOF'
Package: hello-lab
Version: 1.0-1
Architecture: all
Maintainer: Ops Team <ops@example.com>
Description: Demo package for the lab
EOF
dpkg-deb --build --root-owner-group pkg hello-lab_1.0-1_all.deb
dpkg-deb -I hello-lab_1.0-1_all.deb | head -8
sudo dpkg -i hello-lab_1.0-1_all.deb && hello && sudo apt-get remove -y hello-lab
```
@check
Where does pkg/usr/local/bin/hello install? || /usr/local/bin/hello.
@end

@concept Building an rpm package with a spec file
@plain
An rpm is described by a **spec file**: metadata, build steps, a file list and a changelog. `rpmbuild` follows the steps in a clean build root.
@problem
Without a declared recipe, builds depend on whatever happens to be on the builder machine.
@does
- Sections: `%prep` unpack, `%build` compile, `%install` copy into `%{buildroot}`, `%files` list what is shipped.
- Build in a clean environment with `mock` or a container so the result is reproducible.
- Sign packages with a GPG key so clients can verify them.
@diagram flow
caption: Spec to package
nodes:
  - "hello.spec|recipe|plain"
  - "rpmbuild -bb|prep, build, install|app"
  - "buildroot|staging area|env"
  - "hello.rpm|result|ok"
@h Example
```bash title="~/rpmbuild/SPECS/hello.spec" nocheck
Name:       hello-lab
Version:    1.0
Release:    1%{?dist}
Summary:    Demo package
License:    MIT
BuildArch:  noarch

%description
Demo package for the lab.

%install
install -D -m 0755 %{_sourcedir}/hello %{buildroot}/usr/local/bin/hello

%files
/usr/local/bin/hello

%changelog
* Sat Oct 31 2026 Ops Team <ops@example.com> - 1.0-1
- First build
```
```bash title="Build" nocheck
mkdir -p ~/rpmbuild/{SOURCES,SPECS}
printf '#!/bin/sh\necho hello\n' > ~/rpmbuild/SOURCES/hello
rpmbuild -bb ~/rpmbuild/SPECS/hello.spec
rpm -qpl ~/rpmbuild/RPMS/noarch/hello-lab-1.0-1*.rpm
```
@end

@concept fpm and packaging in CI
@plain
`fpm` converts a directory, gem, Python package or tarball into deb or rpm with one command. It is popular for wrapping existing binaries, for example a Go program.
@problem
Writing a spec file and control file for each tool and format costs time when you only need to ship a binary and a unit file.
@does
- `fpm -s dir -t deb -n NAME -v VERSION --prefix / ./root=/` builds from a directory. Check `fpm --help` for the options in your installed version.
- A CI job builds the binary, packages it for each target, signs, uploads to a repository.
- Run package install tests in a clean container for each target OS before publishing.
@diagram flow
caption: A packaging pipeline
nodes:
  - "Commit tag v1.2.0|trigger|plain"
  - "Build binary|Go or Rust|app"
  - "fpm|deb and rpm|info"
  - "Install test|clean containers|warn"
  - "Publish|signed repository|ok"
@h Example job
```yaml title=".github/workflows/package.yml"
name: package
on:
  push:
    tags: ["v*"]
jobs:
  deb-rpm:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build binary
        run: |
          mkdir -p root/usr/local/bin
          GOOS=linux GOARCH=amd64 go build -o root/usr/local/bin/shopctl ./cmd/shopctl
      - name: Package
        run: |
          gem install fpm
          fpm -s dir -t deb -n shopctl -v "${GITHUB_REF_NAME#v}" -C root .
          fpm -s dir -t rpm -n shopctl -v "${GITHUB_REF_NAME#v}" -C root .
      - uses: actions/upload-artifact@v4
        with: {name: packages, path: "*.deb\n*.rpm"}
```
@check
Why test the package in a clean container? || The build machine hides missing dependencies that a fresh host would reveal.
@end

@concept Creating an APT repository
@plain
A repository is a directory of packages plus index files listing them, served over HTTP(S). Clients download the index, then the packages.
@problem
Sending .deb files by email or copying them to hosts gives no upgrade path, no signature check and no central version control.
@does
- Tools: `reprepro`, `aptly`, or a managed registry (Artifactory, Nexus, cloud package services). Check current docs for your registry.
- Required files: `Packages` (index), `Release` (hashes of indexes) and a signature (`Release.gpg` or `InRelease`).
- Clients trust a repository through a key in `/etc/apt/keyrings/` referenced by `signed-by=` in the source line. Do not use the deprecated `apt-key`.
@diagram layers
caption: Layout of a repository
layers:
  - {label: "Signed metadata", nodes: ["InRelease|signature plus hashes|cp"]}
  - {label: "Indexes", nodes: ["Packages.gz|list of packages|info"]}
  - {label: "Pool", nodes: ["shopctl_1.2.0_amd64.deb|files|app"]}
@h Minimal flat repository
```bash title="Create and use a local repository" lab
mkdir -p /tmp/repo && cp /tmp/hello-lab_1.0-1_all.deb /tmp/repo/ && cd /tmp/repo
dpkg-scanpackages . /dev/null 2>/dev/null | gzip -9c > Packages.gz
ls
echo 'deb [trusted=yes] file:/tmp/repo ./' | sudo tee /etc/apt/sources.list.d/lab.list
sudo apt-get update 2>&1 | tail -2 && apt-cache policy hello-lab | head -3
sudo rm /etc/apt/sources.list.d/lab.list
```
:::warn
`trusted=yes` disables signature checks and is for this lab only. Production repositories must be signed and referenced with `signed-by=`.
:::
@end

@concept Signing and trust
@plain
A package signature proves it came from the holder of a private key and was not altered. Clients check it against a public key they trust.
@problem
Without signatures, anyone who controls the network path or the mirror can substitute a malicious package, and your fleet will install it as root.
@does
- Create a dedicated GPG or similar signing key; keep the private key in a secrets manager or HSM and sign in CI.
- For rpm: `rpm --addsign` or `gpgcheck=1` plus `repo_gpgcheck=1` and `gpgkey=` in the .repo file.
- For apt: sign the Release file; distribute the public key via a trusted channel such as your configuration management.
- Rotate keys with an overlap and announce; consider reproducible builds so others can verify the artifacts.
@diagram flow
caption: Chain of trust for packages
nodes:
  - "CI builds|package|app"
  - "Signing key|private, in a vault|cp"
  - "Repository|signed metadata|env"
  - "Client|verifies with public key|ok"
@h Client side
```ini title="/etc/yum.repos.d/shop.repo"
[shop]
name=Shop tools
baseurl=https://packages.example.com/rpm/el9/$basearch
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey=https://packages.example.com/keys/shop.asc
```
```bash title="Check a signature" nocheck
rpm -K shopctl-1.2.0-1.x86_64.rpm
dpkg-sig --verify shopctl_1.2.0_amd64.deb 2>/dev/null
gpg --show-keys shop.asc
```
@check
What does gpgcheck=1 do? || The client refuses packages that do not have a valid signature from a trusted key.
@end
