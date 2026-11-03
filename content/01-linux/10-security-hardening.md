---
title: Security hardening
minutes: 50
objectives:
  - Lock down SSH and sudo so access is key based, audited and least privilege
  - Explain how SELinux and AppArmor confine a process even when it runs as root
  - Use auditd, a host firewall and automatic patching to detect and reduce exposure
---
Hardening means removing what a server does not need and watching what remains. Every node under your Kubernetes cluster and every build agent is a Linux host, so these habits apply directly to EC2 workers, bastions and CI runners.

@concept Defence in depth for a single host
@plain
No single control stops every attack, so you stack several. If one layer fails, the next one limits the damage.
@problem
A server with only a firewall is fully open once one service is exploited. A server with only strong passwords is open once a password leaks. Real incidents chain several small weaknesses.
@does
- **Reduce the surface**: remove packages, close ports, disable unused services.
- **Control access**: keys not passwords, named users, least privilege through sudo.
- **Contain**: mandatory access control (SELinux or AppArmor), systemd sandboxing, containers.
- **Detect and recover**: audit logs, central log shipping, patching, tested backups.
@diagram layers
caption: Layers of host protection from the outside in
layers:
  - {label: "Network", nodes: ["Security group|cloud firewall|ext", "nftables|host firewall|cp"]}
  - {label: "Access", nodes: ["SSH keys|no passwords|app", "sudo|least privilege|app"]}
  - {label: "Containment", nodes: ["SELinux or AppArmor|confine processes|ok", "systemd sandbox|per service limits|ok"]}
  - {label: "Detection", nodes: ["auditd|who did what|info", "central logs|survive a compromise|info"]}
@h A quick baseline check
```bash title="What is exposed on this host" lab
ss -tulpn | head -15                       # listening sockets and their owning process
systemctl list-unit-files --state=enabled | head -20   # what starts at boot
sudo find / -xdev -perm -4000 -type f 2>/dev/null | head   # setuid binaries
awk -F: '$3 == 0 {print $1}' /etc/passwd   # accounts with UID 0 (should be only root)
```
@check
Why keep logs on another host? || An attacker with root can edit local logs, so a remote copy keeps the evidence.
@end

@concept Hardening SSH
@plain
SSH is the door into almost every Linux server. The defaults are reasonable, but a few settings turn it from "guessable" into "key holders only".
@problem
Public servers receive constant password-guessing attempts. Root login over SSH, shared accounts and old algorithms make a single leaked secret a full compromise.
@does
- Disable password login and direct root login; require public keys.
- Limit who may connect with `AllowGroups` and limit retries with `MaxAuthTries`.
- Use drop-in files in `/etc/ssh/sshd_config.d/` instead of editing the packaged file.
- Always validate with `sshd -t` and keep an existing session open while you test a new one.
@diagram flow
caption: Safe way to change sshd settings
numbered: true
nodes:
  - "Edit drop-in|sshd_config.d/10-hardening.conf|app"
  - "Validate|sshd -t|info"
  - "Reload|systemctl reload sshd|env"
  - "Test new session|keep the old one open|warn"
  - "Close old session|only after success|ok"
@h Hardening drop-in
```text title="/etc/ssh/sshd_config.d/10-hardening.conf"
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AllowGroups ssh-users
MaxAuthTries 3
LoginGraceTime 30
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowAgentForwarding no
```
```bash title="Validate and apply" lab
sudo sshd -t && echo "config ok"            # syntax check, silent on success apart from our echo
sudo sshd -T | grep -Ei 'permitrootlogin|passwordauth'   # effective values after all includes
sudo systemctl reload ssh || sudo systemctl reload sshd   # unit name differs by distribution
```
:::warn
Changing SSH settings on a remote host without a second open session is how engineers lock themselves out. On cloud instances, also keep the console or Session Manager as a way back in.
:::
@check
Why use sshd -T instead of reading the file? || It prints the effective configuration after all Include files and defaults, which is what the daemon really uses.
@end

@concept SSH keys, agents and certificates
@plain
An SSH key pair is a private file you keep and a public file you share. The server holds your public key and challenges you to prove you own the private one. SSH **certificates** go further: a certificate authority signs your key for a limited time.
@problem
Copying public keys to hundreds of `authorized_keys` files does not scale, and old keys of people who left are never removed. Long lived keys also stay valid if stolen.
@does
- Prefer `ed25519` keys; protect the private key with a passphrase and `ssh-agent`.
- A user certificate carries a validity window and principals (allowed login names). Servers trust only the CA public key via `TrustedUserCAKeys`.
- On AWS, EC2 Instance Connect and Session Manager remove the need to distribute keys at all.
@diagram seq
caption: Login with a short lived SSH certificate
actors: ["Engineer|laptop|app", "SSH CA|signs keys|cp", "Server|trusts the CA|env"]
steps:
  - "0>1: authenticate with SSO | tls"
  - "1>0: certificate valid 8 hours | resp"
  - "0>2: ssh with key and certificate | req"
  - "note 2..2: checks CA signature, principal and expiry"
  - "2>0: session opened | resp"
@h Key handling
```bash title="Create, sign and inspect keys" lab
ssh-keygen -t ed25519 -C "alice@laptop" -f /tmp/demo_key -N ""      # demo key without a passphrase
ssh-keygen -t ed25519 -f /tmp/demo_ca -N "" -C "demo-ca"             # a throwaway CA
ssh-keygen -s /tmp/demo_ca -I alice -n deploy -V +8h /tmp/demo_key.pub   # sign for 8 hours
ssh-keygen -L -f /tmp/demo_key-cert.pub | head -12                   # show principals and validity
ssh-keygen -lf /tmp/demo_key.pub                                     # fingerprint
```
@check
What limits a stolen SSH certificate? || Its validity window and the principals it lists; after expiry the server rejects it without any cleanup.
@end

@concept sudo and least privilege
@plain
`sudo` lets an approved user run specific commands as another user, usually root, and records each use. The aim is that nobody works as root all day.
@problem
Sharing the root password gives no accountability and no limits. A blanket `ALL=(ALL) ALL` rule turns every compromised account into root.
@does
- Rules live in `/etc/sudoers` and `/etc/sudoers.d/`. Always edit with `visudo`, which checks syntax before saving.
- Grant exact commands to groups, not users, and avoid wildcards that let arguments be abused.
- `sudo -l` shows what you may run; the log lines go to the journal or `/var/log/auth.log`.
- Editors and shells launched through sudo can escape; prefer `sudoedit` for file changes.
@diagram cmp
caption: Broad versus narrow sudo rules
cards:
  - {h: "Too broad", kind: bad, items: ["NOPASSWD ALL for a whole group", "Every member is root without a prompt", "No useful audit trail"]}
  - {h: "Narrow", kind: ok, items: ["Exact command and path", "Group based, reviewed in Git", "Logged with the real user name"]}
@h Example drop-in
```bash title="Create and validate a rule" lab
echo '%ops ALL=(root) /usr/bin/systemctl restart shop, /usr/bin/journalctl -u shop' | sudo tee /etc/sudoers.d/ops-shop
sudo chmod 440 /etc/sudoers.d/ops-shop
sudo visudo -cf /etc/sudoers.d/ops-shop     # syntax check of just this file
sudo -l -U alice                            # what alice may run
```
:::tip
Never use `NOPASSWD: ALL` on interactive accounts. For automation, grant a service account only the exact commands it needs.
:::
@check
Why edit with visudo? || A syntax error in sudoers can disable sudo for everyone; visudo validates before it saves.
@end

@concept SELinux in practice
@plain
**SELinux** labels every process and file and then checks each access against a policy. Even root can only do what the policy allows for its label. It is the default on RHEL, Fedora and Amazon Linux 2023.
@problem
Standard Unix permissions trust the user. If a web server running as `nginx` is exploited, the attacker can read anything `nginx` can read. SELinux limits that to what a web server legitimately needs.
@does
- Modes: **enforcing** (blocks and logs), **permissive** (logs only, for debugging), **disabled**.
- Files have a context such as `httpd_sys_content_t`; processes have a domain such as `httpd_t`.
- When something is denied, the audit log has an AVC entry. `ausearch` and `sealert` explain it.
- Fix with the correct label (`semanage fcontext` + `restorecon`) or a boolean (`setsebool`), not by disabling SELinux.
@diagram flow
caption: Troubleshooting an SELinux denial
numbered: true
nodes:
  - "App fails|permission denied despite correct chmod|bad"
  - "Check mode|getenforce|info"
  - "Read AVC|ausearch -m avc -ts recent|app"
  - "Fix label or boolean|restorecon or setsebool|ok"
  - "Retest|stay in enforcing mode|ok"
@h Commands
```bash title="Inspect and fix SELinux" lab
getenforce                                  # Enforcing, Permissive or Disabled
ls -Z /var/www/html | head -3               # file contexts
ps -eZ | grep -E 'nginx|httpd' | head -2    # process domains
sudo ausearch -m avc -ts recent | head -5   # recent denials
sudo semanage fcontext -a -t httpd_sys_content_t "/srv/site(/.*)?"   # persistent label rule
sudo restorecon -Rv /srv/site               # apply the label
sudo setsebool -P httpd_can_network_connect on   # allow outbound connections, persistently
```
:::danger
`setenforce 0` and `SELINUX=disabled` are not fixes. They remove a whole protection layer from the host. Use permissive mode only briefly to collect denials.
:::
@check
What is the difference between chmod and an SELinux label? || chmod is discretionary and decided by the owner; the label is enforced by system policy and applies even to root.
@end

@concept AppArmor profiles
@plain
**AppArmor** is the mandatory access control used by Ubuntu, Debian and SUSE. Instead of labelling files it attaches a **profile** to a program that lists the paths, capabilities and network access it may use.
@problem
You want the same containment as SELinux with less to learn. Profiles are readable text tied to a program path, so a team can write one for its own service.
@does
- Modes: **enforce** and **complain** (log only).
- `aa-status` lists loaded profiles; `aa-genprof` and `aa-logprof` build profiles from observed behaviour.
- Docker applies a default profile `docker-default` to containers; Kubernetes can select profiles per container.
- Denials appear in the kernel log and journal as `apparmor="DENIED"`.
@diagram cmp
caption: SELinux compared with AppArmor
cards:
  - {h: "SELinux", kind: cp, items: ["Labels on files and processes", "Very fine grained, steeper learning", "RHEL, Fedora, Amazon Linux"]}
  - {h: "AppArmor", kind: app, items: ["Path based profiles per program", "Simpler to read and write", "Ubuntu, Debian, SUSE"]}
@h Commands
```bash title="Work with AppArmor" lab
sudo aa-status | head -12                    # loaded profiles and their modes
sudo aa-complain /usr/sbin/nginx             # switch one profile to complain mode
sudo aa-enforce /usr/sbin/nginx              # and back to enforce
sudo journalctl -k | grep -i 'apparmor="DENIED"' | tail -3
```
@check
Which log would you read to find out why a confined program was blocked? || The kernel log or journal for DENIED entries, then aa-logprof to adjust the profile.
@end

@concept Auditing with auditd
@plain
The Linux audit framework records security relevant events in the kernel: file access, command execution, account changes. `auditd` writes them to `/var/log/audit/audit.log`.
@problem
Without audit records you cannot answer "who changed `/etc/passwd` and when" after an incident, and compliance frameworks such as PCI DSS and SOC 2 expect evidence.
@does
- **Watch rules** (`-w`) record access to a file or directory. **Syscall rules** (`-a`) record calls such as `execve`.
- Tag rules with `-k key` so `ausearch -k key` finds them fast.
- Persistent rules go in `/etc/audit/rules.d/*.rules` and are loaded with `augenrules --load`.
- Ship events to a central system; keep rules focused because noisy rules fill disks.
@diagram flow
caption: From a kernel event to an investigation
nodes:
  - "Kernel event|file write, execve|plain"
  - "Audit rule|matches and tags with a key|info"
  - "auditd|writes audit.log|app"
  - "Central log store|searchable copy|ok"
@h Rules and searches
```bash title="Watch identity files" lab
sudo auditctl -w /etc/passwd -p wa -k identity       # write and attribute change on passwd
sudo auditctl -w /etc/sudoers.d/ -p wa -k sudoers
sudo auditctl -a always,exit -F arch=b64 -S execve -F euid=0 -k root_exec   # root commands
sudo auditctl -l                                      # active rules
sudo ausearch -k identity -i | tail -10               # readable events for that key
sudo aureport --auth --summary | head                 # login summary
```
@check
Why tag audit rules with -k? || The key lets you search quickly for one rule's events instead of scanning the whole log.
@end

@concept Host firewall and automatic patching
@plain
A host firewall decides which network connections reach the machine, and patching closes known holes. Both are routine work that should be automatic.
@problem
Cloud security groups protect the network edge, but a misconfigured group, or traffic from inside the VPC, can still reach a service that should be private. Most breaches use vulnerabilities for which a fix already existed.
@does
- Default deny inbound; allow only the ports the host serves (see the networking tools section for nftables).
- Enable unattended security updates (`unattended-upgrades` on Debian and Ubuntu, `dnf-automatic` on the Red Hat family).
- Kernel updates need a reboot; live patching tools or rolling node replacement in Kubernetes cover that.
- Immutable infrastructure goes further: replace servers with fresh images instead of patching them in place.
@diagram flow
caption: A patching loop that does not depend on memory
numbered: true
nodes:
  - "Fresh image|built weekly with updates|app"
  - "Scan|vulnerability scan of the image|info"
  - "Roll out|replace nodes gradually|env"
  - "Verify|health checks and alerts|ok"
@h Examples
```bash title="Enable automatic security updates" lab
# Debian and Ubuntu
sudo apt-get install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
# Red Hat family
sudo dnf install -y dnf-automatic
sudo systemctl enable --now dnf-automatic-install.timer
# what needs a reboot?
[ -f /var/run/reboot-required ] && cat /var/run/reboot-required || needs-restarting -r
```
:::note
On Kyma and EKS, prefer replacing nodes through the managed node group or Gardener worker rollout rather than patching individual workers by hand.
:::
@check
Why is replacing a node better than patching it for long lived fleets? || Every node then comes from a known, tested image, and drift between servers disappears.
@end
