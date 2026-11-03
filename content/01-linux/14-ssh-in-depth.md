---
title: SSH in depth
minutes: 50
objectives:
  - Generate and manage keys and use the agent safely
  - Use SSH certificates, bastion hosts and ProxyJump
  - Build local, remote and dynamic tunnels
  - Harden sshd and verify the result
---
SSH is the door to almost every server you run. These concepts move from daily use to a hardened, auditable setup. Option names are from OpenSSH; check `man ssh_config` and `man sshd_config` on your version.

@concept How SSH authenticates
@plain
SSH first sets up an encrypted channel and checks the **server host key**, then proves who you are, usually with a **key pair**: a private key that never leaves your machine and a public key placed on the server.
@problem
Passwords can be guessed, phished and reused. Keys cannot be guessed over the network, and a server only ever holds the public half.
@does
- First connection: the client stores the server's host key fingerprint in `~/.ssh/known_hosts`. A later mismatch triggers a loud warning, which may be a rebuilt server or an attacker.
- User authentication: the server sends a challenge that only the private key holder can sign.
- Your public key goes into `~/.ssh/authorized_keys` on the target.
@diagram seq
caption: Public key login
actors: ["Client|has private key|app", "Server|has authorized_keys|cp"]
steps:
  - "0>1: connect, offer key exchange | req"
  - "1>0: host key, signed | tls"
  - "note 0..0: compare with known_hosts"
  - "0>1: user public key | req"
  - "1>0: challenge | req"
  - "0>1: signature | tls"
  - "1>0: access granted | resp"
@h Keys
```bash title="Create and install a key" lab
ssh-keygen -t ed25519 -C "laptop-2026" -f ~/.ssh/id_ed25519_lab     # asks for a passphrase, use one
ssh-keygen -lf ~/.ssh/id_ed25519_lab.pub                              # fingerprint
ssh-copy-id -i ~/.ssh/id_ed25519_lab.pub user@server.example          # appends to authorized_keys
ssh -i ~/.ssh/id_ed25519_lab user@server.example hostname
```
:::tip
Ed25519 is a good default today. Always protect the private key with a passphrase.
:::
@check
What is in authorized_keys on the server? || Public keys allowed to log in as that user; never private keys.
@end

@concept ssh-agent and client configuration
@plain
The **agent** holds your decrypted private key in memory so you type the passphrase once. `~/.ssh/config` stores per-host settings so commands stay short.
@problem
Typing long commands and passphrases leads people to remove passphrases or write scripts with copied options.
@does
- `ssh-add` loads keys; `ssh-add -l` lists them; on macOS `UseKeychain` and `AddKeysToAgent` integrate with the keychain.
- Config blocks match by `Host` pattern. First match wins for each option, so put specific hosts before `Host *`.
- `ControlMaster` and `ControlPersist` reuse one connection for many sessions, making repeated commands fast.
@diagram flow
caption: Passphrase once, many logins
nodes:
  - "ssh-add|decrypt key once|info"
  - "ssh-agent|keeps key in memory|cp"
  - "ssh host|agent signs challenges|app"
  - "Server|accepts|ok"
@h Config
```bash title="~/.ssh/config example" nocheck
Host prod-*
  User deploy
  IdentityFile ~/.ssh/id_ed25519_lab
  IdentitiesOnly yes
  ServerAliveInterval 30

Host *
  AddKeysToAgent yes
  ControlMaster auto
  ControlPath ~/.ssh/cm-%C
  ControlPersist 10m
```
```bash title="Agent commands" lab
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519_lab
ssh-add -l
ssh -G prod-web1 | grep -E '^(user|identityfile|hostname) '    # show the effective config
```
@check
Why IdentitiesOnly yes? || It stops the client offering every agent key, which can hit the server's attempt limit.
@end

@concept Bastion hosts and ProxyJump
@plain
A **bastion** (jump host) is the single hardened server reachable from outside. Everything else sits in a private network and is reached through it.
@problem
Exposing every server's SSH port widens the attack surface and makes auditing who logged in where very hard.
@does
- `ssh -J bastion target` (ProxyJump) connects through the bastion without giving the bastion your private key; the end to end session stays encrypted between you and the target.
- Put it in config with `ProxyJump bastion`.
- Alternatives that avoid open ports: AWS Systems Manager Session Manager and EC2 Instance Connect Endpoint (check current docs).
@diagram flow
caption: Reaching a private server through a bastion
nodes:
  - "Laptop|your key|app"
  - "Bastion|public subnet, hardened|cp"
  - "Private server|no public IP|env"
@h Usage
```bash title="Jump host config and use" nocheck
# ~/.ssh/config
# Host bastion
#   HostName bastion.example.com
#   User ops
# Host app-*
#   ProxyJump bastion
ssh -J ops@bastion.example.com deploy@10.0.16.20 uptime
scp -J ops@bastion.example.com ./file deploy@10.0.16.20:/tmp/
```
:::warn
Prefer ProxyJump to agent forwarding. Agent forwarding lets root on the bastion use your agent while you are connected.
:::
@end

@concept Agent forwarding and its risk
@plain
Agent forwarding (`-A`) lets a remote host ask your local agent to sign challenges, so you can hop onward without copying keys.
@problem
It solves "I need to git pull from the server using my key" but exposes your identity to anyone with root on that server.
@does
- The remote end gets a socket that relays signature requests to your agent while connected.
- A malicious root user can use it to log in elsewhere as you.
- Safer options: ProxyJump for hops, deploy keys or short-lived credentials for the server's own needs, `ssh-add -c` to confirm each use.
@diagram cmp
caption: Forwarding versus jumping
cards:
  - {h: "Agent forwarding", kind: bad, items: ["Remote root can use your agent", "Convenient, risky on shared hosts"]}
  - {h: "ProxyJump", kind: ok, items: ["Bastion only relays bytes", "No key exposure"]}
@h Check
```bash title="See whether forwarding is on" lab
ssh -G somehost 2>/dev/null | grep -i forwardagent       # default is no
ssh-add -l                                               # on a remote shell, a forwarded key shows up here
ssh-add -c ~/.ssh/id_ed25519_lab                         # ask for confirmation on each use
```
@check
Which is safer for reaching a private host, ProxyJump or -A? || ProxyJump.
@end

@concept SSH certificates
@plain
An **SSH certificate** is a public key signed by a certificate authority you control, with an identity, allowed usernames and an expiry. Servers trust the CA instead of individual keys.
@problem
Copying keys into thousands of `authorized_keys` files cannot be audited or revoked quickly, and leavers keep access until someone finds every copy.
@does
- Servers set `TrustedUserCAKeys` once; any certificate signed by that CA and valid for the user is accepted.
- Certificates are short lived (for example 8 hours), so revocation is mostly expiry.
- Host certificates remove the trust on first use warning for clients.
- Tools such as HashiCorp Vault and Smallstep automate issuance after SSO login.
@diagram seq
caption: Short lived certificate login
actors: ["User|laptop|app", "CA|signs after SSO|cp", "Server|trusts the CA|env"]
steps:
  - "0>1: login with SSO, send public key | req"
  - "1>0: certificate valid 8 hours | tls"
  - "0>2: ssh with certificate | tls"
  - "2>0: access, no authorized_keys | resp"
@h Make one
```bash title="Create a CA and sign a user key" lab
cd /tmp && ssh-keygen -t ed25519 -N '' -f ca_key -C lab-ca
ssh-keygen -t ed25519 -N '' -f user_key -C alice
ssh-keygen -s ca_key -I alice-laptop -n alice,deploy -V +8h user_key.pub
ssh-keygen -L -f user_key-cert.pub | head -12
# server side, in sshd_config:  TrustedUserCAKeys /etc/ssh/ca_key.pub
```
@check
How does a certificate login revoke access? || It expires, so a short validity period limits exposure; a revocation list is also possible.
@end

@concept Tunnels and port forwarding
@plain
SSH can carry other TCP traffic inside its encrypted connection. **Local** forwarding brings a remote port to your laptop, **remote** forwarding opens a port on the server, and **dynamic** forwarding makes a SOCKS proxy.
@problem
You need to reach a private database or web UI without opening it to the internet.
@does
- `-L 5433:db.internal:5432` makes `localhost:5433` reach the database via the SSH host.
- `-R 8080:localhost:3000` exposes your local port 3000 on the server's port 8080 (the server needs `GatewayPorts` for outside access).
- `-D 1080` gives a SOCKS5 proxy that sends browser traffic through the host.
- `-N` skips running a shell; `-f` backgrounds the connection.
@diagram flow
caption: Local forward to a private database
nodes:
  - "psql localhost:5433|your laptop|app"
  - "SSH tunnel|encrypted|cp"
  - "Bastion|public subnet|env"
  - "db.internal:5432|private database|ok"
@h Tunnel recipes
```bash title="Forwarding examples" nocheck
ssh -N -f -L 5433:db.internal:5432 ops@bastion.example.com
psql -h localhost -p 5433 -U app shop
ssh -D 1080 -N ops@bastion.example.com          # then set a SOCKS5 proxy to localhost:1080
ssh -R 9000:localhost:3000 ops@bastion.example.com     # share a local dev server
ss -ltnp | grep -E '5433|1080'                  # confirm the local listeners
```
:::note
For Kubernetes, `kubectl port-forward` does the same job for a pod or service.
:::
@end

@concept Hardening sshd
@plain
Hardening means turning off what you do not use: passwords, root login, old algorithms, and unneeded forwarding, then verifying the effective configuration.
@problem
Any internet-facing SSH server receives constant password guessing. A single weak account is enough.
@does
- Key-only: `PasswordAuthentication no`, `KbdInteractiveAuthentication no`, `PermitRootLogin no`.
- Limit who: `AllowGroups ssh-users`, `MaxAuthTries 3`, `LoginGraceTime 30`.
- Reduce features: `X11Forwarding no`, `AllowAgentForwarding no`, `AllowTcpForwarding` as needed.
- Always validate with `sshd -t` and keep a second session open before reloading, otherwise a typo can lock you out.
- Add `fail2ban` or rate limits in the firewall, and consider a non-default port only as noise reduction, not security.
@diagram flow
caption: A safe change procedure
numbered: true
nodes:
  - "Edit drop-in|sshd_config.d/10-hardening.conf|app"
  - "sshd -t|syntax check|info"
  - "Keep session open|safety net|warn"
  - "Reload|systemctl reload sshd|cp"
  - "Test new login|from a second terminal|ok"
@h Config and checks
```bash title="/etc/ssh/sshd_config.d/10-hardening.conf" nocheck
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
AllowGroups ssh-users
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowAgentForwarding no
ClientAliveInterval 300
ClientAliveCountMax 2
```
```bash title="Validate before reloading" lab
sudo sshd -t && echo "config ok"
sudo sshd -T | grep -E '^(passwordauthentication|permitrootlogin|maxauthtries|allowgroups) '
sudo systemctl reload sshd          # the unit is named ssh on Debian and Ubuntu
sudo journalctl -u sshd --since "10 min ago" --no-pager | grep -i 'failed' | tail -5
```
@check
Why keep an existing session open when reloading sshd? || If the new config blocks logins you can still fix it from the open session.
@end
