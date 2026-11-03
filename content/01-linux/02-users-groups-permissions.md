---
title: Users, groups and permissions
minutes: 40
objectives:
  - Read and change owners, groups and permission bits, in symbolic and octal form
  - Explain setuid, setgid, the sticky bit and umask
  - Give people exactly the access they need with sudo and ACLs
---
Linux decides what a process may do by asking **who it runs as** and comparing that identity with the owner, group and permission bits stored on each file. Almost every security rule in later chapters, from container users to Kubernetes pod security, builds on this model.

@concept Users and groups
@plain
Every process runs as a **user**, and every user belongs to one or more **groups**. The system knows users by number: a **UID** for the user and a **GID** for the group. Names are only labels for those numbers.
@problem
If every program ran with the same power, a bug in a web server could read your database passwords or delete the system. The system needs identities so it can limit what each program can touch.
@does
- User `root` has UID 0 and bypasses permission checks. Ordinary people usually start at UID 1000. Accounts for services (such as `nginx`) are *system users* with lower numbers and normally no login shell.
- `/etc/passwd` lists accounts, `/etc/group` lists groups, and `/etc/shadow` holds password hashes and is readable only by root.
- Each file stores an owner UID and a group GID, so a file's identity survives even if the account name changes.
@diagram flow
caption: How a process gets its identity and how a file check uses it
numbered: true
nodes:
  - "Login or service start|account chosen|info"
  - "Process runs as UID + GIDs|kernel stores numbers|app"
  - "Opens a file|asks the kernel|env"
  - "Kernel compares|UID/GID against file owner|warn"
  - "Allow or deny|permission bits decide|ok"
@h Looking at identities
```bash title="Who am I, who else exists"
id                           # uid, gid and every group you belong to
whoami
getent passwd | head -3      # name:x:UID:GID:comment:home:shell
getent group sudo            # members of the sudo group (wheel on RHEL family)
ls -ln /etc/shadow           # -n shows the numeric owner
```
@h Creating accounts
```bash title="Add a service user and a person" lab
sudo useradd --system --no-create-home --shell /usr/sbin/nologin shop   # service account
sudo useradd --create-home --shell /bin/bash asha                       # person
sudo usermod -aG docker asha        # -a APPENDS the group; without -a the user's other groups are replaced
sudo passwd -l shop                 # lock the password so nobody can log in as it
```
:::warn
`usermod -G` without `-a` replaces all supplementary groups. Forgetting the `-a` is a classic way to remove someone's access by accident.
:::
@check
What does the kernel actually store on a file, the owner's name or number? || The number (UID and GID). Names are looked up from /etc/passwd and /etc/group when you list files.
Why give a web server its own system user? || A compromised server can then only reach what that user may reach, not the whole system.
@end

@concept Permission bits
@plain
Each file has three sets of three switches: read, write and execute, for the **owner**, the **group** and **everyone else**. `ls -l` shows them as `-rwxr-x---`.
@problem
People need to share some files and protect others. Without a fine switch per audience, you would have to choose between everyone seeing a secret key or nobody being able to run a shared script.
@does
- `r` = 4, `w` = 2, `x` = 1, and each set adds up: `rwx` is 7, `r-x` is 5, `r--` is 4, `---` is 0.
- So `-rwxr-x---` is mode **750**: owner may do everything, the group may read and run, others get nothing.
- On a **directory**, `r` lists names, `w` creates or deletes entries, and `x` lets you enter it or reach files inside. A directory without `x` blocks access to everything below it.
- Root ignores these bits, and so do processes holding the right *capabilities* (see the kernel chapter).
@diagram flow
caption: Reading -rwxr-x--- as 750
nodes:
  - "-|file type|plain"
  - "rwx = 7|owner|ok"
  - "r-x = 5|group|info"
  - "--- = 0|everyone else|bad"
@h Changing permissions
```bash title="chmod and chown"
chmod 640 app.env                 # owner read/write, group read, others nothing
chmod u+x,g-w,o= deploy.sh        # symbolic: add x for owner, remove w from group, clear others
chmod -R u=rwX,g=rX,o= site/      # capital X sets x on directories and already-executable files only
sudo chown shop:shop /var/lib/shop
sudo chown -R root:root /etc/shop # -R follows into everything below; check the path first
stat -c '%A %a %U:%G %n' app.env  # mode in both forms, owner, name
```
| Mode | Typical use |
|---|---|
| 644 | Ordinary files that everyone may read |
| 755 | Programs, scripts and directories that everyone may enter |
| 600 | Private keys and credentials (SSH refuses a private key that others can read) |
| 640 | Config readable by a service group but not the world |
| 700 | A private directory such as `~/.ssh` |
@check
A directory is `rw-r--r--`. Why can you not `cd` into it? || It has no execute bit, and on a directory x is what allows entering it.
What is 640 in letters? || rw-r----- (owner read and write, group read, others none).
@end

@concept Special bits and umask
@plain
Three extra bits change how files and directories behave, and **umask** decides the permissions new files start with.
@problem
Sometimes an ordinary user must run one program with extra power (change their own password, which edits a root-owned file). Shared folders also need rules so one person cannot delete another's files. And new files should not be world-readable by accident.
@does
- **setuid** (4000) on a program makes it run as the *file's owner* rather than the caller. That is how `passwd` works. It is powerful and risky.
- **setgid** (2000) on a program runs with the file's group. On a *directory* it makes new files inherit the directory's group, which is the usual fix for team folders.
- **sticky** (1000) on a directory lets only a file's owner (or root) delete it. `/tmp` is mode 1777 for this reason.
- **umask** removes bits from the defaults of 666 for files and 777 for directories: umask 022 gives 644 and 755; umask 027 gives 640 and 750; umask 077 gives 600 and 700.
@diagram cmp
caption: What each special bit is for
cards:
  - {h: "setuid 4000", kind: bad, items: ["Program runs as its owner", "Example: passwd", "Audit these; ignored on scripts"]}
  - {h: "setgid 2000", kind: app, items: ["On a folder: new files inherit the group", "Fixes shared team directories", "Shown as s in the group triplet"]}
  - {h: "sticky 1000", kind: ok, items: ["Only the owner can delete a file", "Example: /tmp is 1777", "Shown as t at the end"]}
@h Hands-on
```bash title="Shared folder for a team, and a setuid audit" lab
sudo mkdir -p /srv/team && sudo chgrp developers /srv/team
sudo chmod 2775 /srv/team           # setgid + rwxrwxr-x: new files keep group "developers"
umask                               # show the current mask, commonly 0022
umask 027                           # new files 640, new directories 750 in this shell
find / -xdev -type f -perm -4000 2>/dev/null   # list every setuid program on this filesystem
```
:::note
Linux ignores setuid on shell scripts for safety, so use `sudo` rules or a proper service instead of trying to make a script setuid.
:::
@check
Why does a shared project directory usually get setgid? || So files created inside belong to the project group no matter who creates them, and teammates keep access.
What file mode does umask 077 give new files? || 600, since 666 minus 077 is 600.
@end

@concept sudo and least privilege
@plain
`sudo` lets a permitted user run one command with another user's rights, usually root, while logging who did it. **Least privilege** means giving each person or program only the access the job needs.
@problem
Logging in as root all the time is dangerous and leaves no record of who did what. Sharing the root password makes individual accountability impossible.
@does
- You authenticate as *yourself*, then `sudo` checks the rules in `/etc/sudoers` and `/etc/sudoers.d/`.
- Rules can limit which commands run and as whom, so automation can restart one service without full root.
- Edit with `visudo`, which refuses to save a file with a syntax error that would lock everyone out.
- Every use is recorded in the authentication log or the journal.
@diagram seq
caption: One sudo command, from request to audit
actors: ["Person|asha|app", "sudo|command|env", "sudoers|rules|cp", "Target command|runs as root|ok", "Audit log|journal|plain"]
steps:
  - "0>1: sudo systemctl restart shop"
  - "1>0: password for asha? | req"
  - "0>1: ******** | req"
  - "1>2: may asha run this? | req"
  - "2>1: yes, rule matched | tls"
  - "1>3: execute as root | tls"
  - "1>4: who, what, when | resp"
@h A narrow rule for automation
```text title="/etc/sudoers.d/deploy  (edit with: sudo visudo -f /etc/sudoers.d/deploy)"
# the deploy user may restart or inspect one service, and nothing else
deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart shop, /usr/bin/systemctl status shop
# members of the ops group may read the journal as anyone
%ops   ALL=(ALL)  /usr/bin/journalctl
```
```bash title="See what you are allowed to do"
sudo -l                        # list the rules that apply to you
sudo -u shop whoami            # run a command as another user
sudo journalctl _COMM=sudo -n 20   # recent sudo activity
```
@choose Giving someone access
Specific command in sudoers | automation or a person needs one or two actions | they need to explore the system freely
Membership of an admin group | a trusted admin needs broad rights | this is a service account or a shared login
Separate account per person | you need an audit trail | you plan to share one login for convenience
@check
Why use visudo instead of a normal editor? || It validates the syntax before saving; a broken sudoers file can lock all admins out.
@end

@concept Access control lists (ACLs)
@plain
An **ACL** adds extra permission entries to a file for specific people or groups, beyond the owner, group and everyone-else slots.
@problem
Basic permissions only have three audiences. If one contractor needs read access to a single folder, you would otherwise create a new group, add people, and risk exposing more than intended.
@does
- `setfacl -m u:alice:rwx path` grants one user; `g:auditors:r-x` grants one group.
- A **default ACL** on a directory is copied to everything created inside it.
- `getfacl` shows the full list; `ls -l` shows a `+` after the mode when an ACL exists.
- Needs a filesystem with ACL support, which ext4 and XFS provide by default.
@diagram cmp
caption: Classic permissions versus ACLs
cards:
  - {h: "Classic mode", kind: app, items: ["Owner, group, others", "Simple and fast to reason about", "A fourth audience needs a new group"]}
  - {h: "With ACLs", kind: ok, items: ["Named users and groups", "Default entries for new files", "Easy to lose track of; document them"]}
@h Hands-on
```bash title="Give one auditor read-only access" lab
sudo setfacl -m g:auditors:rX /srv/reports         # existing files
sudo setfacl -d -m g:auditors:rX /srv/reports      # new files created later
getfacl /srv/reports
ls -ld /srv/reports                                # note the + at the end of the mode
sudo setfacl -b /srv/reports                       # remove all ACL entries again
```
@choose Groups or ACLs
Plain groups | the audience is stable and used in many places | one-off access to a single path
ACLs | you need an exception for a specific person or folder | you can solve it with a group; ACLs are harder to audit
@end
