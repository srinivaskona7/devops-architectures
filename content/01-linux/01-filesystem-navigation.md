---
title: Filesystem and navigation
minutes: 35
objectives:
  - Navigate the Linux directory tree and explain what lives where
  - Find files by name, size, age and content
  - Explain hard links, symbolic links and inodes
  - Create, inspect and extract archives
---
Linux organises everything as a **tree of files** that starts at one root, written `/`. Devices, processes and settings all appear as files too, which is why a few commands go a very long way.

@concept The directory tree
@plain
There is one tree, not drive letters. Everything hangs below `/`. Standard places keep programs, settings, logs and your own files apart so that tools and people know where to look.
@problem
If every program stored its files anywhere it liked, administrators could not back up settings, clean old logs, or upgrade software without breaking something. A shared layout makes systems predictable.
@does
- Defines a standard top-level layout called the Filesystem Hierarchy Standard.
- Separates system programs, per-machine configuration, changing data and temporary files.
- Lets you mount other disks or network shares at any point in the tree.
@diagram layers
caption: The top of the Linux tree and what each part holds
layers:
  - {label: "Programs", nodes: ["/bin /usr/bin|commands everyone can run|app", "/sbin /usr/sbin|admin commands|app", "/lib /usr/lib|shared libraries|app"]}
  - {label: "Settings", nodes: ["/etc|text config files per machine|env"]}
  - {label: "Changing data", nodes: ["/var/log|logs|warn", "/var/lib|app state, databases|warn", "/home|user files|ok", "/root|root user's files|ok"]}
  - {label: "Temporary", nodes: ["/tmp|cleared on reboot|plain", "/run|runtime state, sockets|plain"]}
  - {label: "Virtual", nodes: ["/proc|kernel and process info|cp", "/sys|devices and kernel settings|cp", "/dev|device files|cp"]}
@h Where am I and what is here
Three commands answer most questions: where you are, what is here, and how big it is.
```bash title="Orientation"
pwd                      # print working directory
ls -lah                  # long listing, hidden files, human-readable sizes
cd /var/log && ls -lt | head      # newest files first
tree -L 2 /etc 2>/dev/null | head -20   # if the tree command is installed
du -sh /var/log/* | sort -h | tail -5   # the five biggest log entries
df -hT                   # free space per mounted filesystem
```
@h Paths
An **absolute path** starts with `/` and works from anywhere. A **relative path** starts from where you are: `.` is here, `..` is the parent, and `~` is your home directory.
@check
Where would you look for a service's configuration? || Under `/etc`, usually in a file or folder named after the service.
Where do container runtimes keep image layers? || Typically under `/var/lib`, for example `/var/lib/docker` or `/var/lib/containerd`.
@end

@concept Finding files
@plain
`find` walks the tree and tests each file against conditions you give it. `grep` searches inside files. `locate` searches a prebuilt index and is instant but can be out of date.
@problem
On a server with millions of files you cannot browse. You need to answer questions such as "which files changed in the last hour", "what is filling the disk", or "which config mentions this setting".
@does
- `find` filters by name, type, size, owner, age and permissions, and can run a command on each match.
- `grep -r` searches contents recursively; `-n` shows line numbers, `-i` ignores case.
- Combining them answers most investigation questions in one line.
@diagram flow
caption: A search narrows from the whole tree to the answer
numbered: true
nodes:
  - "Whole tree|millions of files|plain"
  - "find -type f|only files|info"
  - "-mtime -1|changed in a day|app"
  - "-size +100M|large ones|warn"
  - "Answer|the culprits|ok"
@h Common searches
```bash title="find and grep recipes"
find /var/log -type f -name '*.log' -mtime -1          # logs changed in the last day
find / -xdev -type f -size +500M 2>/dev/null           # big files on this filesystem only
find /etc -type f -perm -o+w                           # files anyone can write (a red flag)
find . -name '*.tmp' -type f -delete                   # delete matches (test without -delete first)
grep -rn --include='*.conf' 'listen' /etc/nginx        # which config says "listen"
grep -rIl 'password' /etc 2>/dev/null                  # files that mention password
```
:::warn
Run `find ... -delete` or `-exec rm` without the delete part first, read the list, and only then add it. There is no recycle bin.
:::
@choose find, locate or grep
find | you need conditions such as age, size, owner or permissions | you only know part of the file's content
locate | you want a fast name lookup and the index is fresh | the file was created in the last day, or you need current state
grep | you are searching inside file contents | you are looking for file names or metadata
@end

@concept Links and inodes
@plain
A file has two parts: its data and a record called an **inode** that stores size, owner, permissions and where the data lives. The name in a folder is just a pointer to an inode. A **hard link** is another name for the same inode. A **symbolic link** is a small file that holds a path.
@problem
You often need one file to appear in two places, or a stable name that points to a changing target, such as `current` pointing to the latest release folder, without copying data.
@does
- A hard link shares the inode; the data is deleted only when the last name is removed. It cannot cross filesystems or point at a directory.
- A symlink holds a path; it can cross filesystems and point at directories, but breaks if the target moves.
- `ls -li` shows inode numbers, `readlink -f` resolves a symlink to its real target.
@diagram cmp
caption: Hard link versus symbolic link
cards:
  - {h: "Hard link", kind: ok, items: ["Second name for the same inode", "Survives deleting the original name", "Same filesystem only"]}
  - {h: "Symbolic link", kind: app, items: ["A file containing a path", "Can cross filesystems, can target folders", "Dangles if the target is removed"]}
@h Try it
```bash title="Links in practice" lab
cd "$(mktemp -d)"
echo hello > original.txt
ln original.txt hard.txt          # hard link
ln -s original.txt soft.txt       # symbolic link
ls -li                            # hard.txt shares the inode number with original.txt
rm original.txt
cat hard.txt                      # still works: data survives
cat soft.txt                      # fails: the symlink now dangles
```
@check
Why is "current -> releases/2026-10-30" a symlink and not a hard link? || Directories cannot be hard linked, and the symlink target can be switched atomically to deploy or roll back.
@end

@concept Archives and compression
@plain
`tar` bundles many files into one file (an archive). A compressor such as `gzip`, `xz` or `zstd` makes it smaller. They are separate steps that `tar` can chain for you.
@problem
Copying thousands of small files is slow and loses permissions and ownership. Backups, releases and container image layers all need one portable file that keeps the metadata.
@does
- `tar -c` creates, `-x` extracts, `-t` lists, `-f` names the file, `-z` gzip, `-J` xz, `--zstd` zstd.
- Preserves permissions, owners, timestamps and symlinks.
- Streams over a pipe, so you can archive straight to another machine without a temporary file.
@diagram flow
caption: Making and moving a backup
nodes:
  - "Folder|many files|plain"
  - "tar|one archive|info"
  - "gzip or zstd|smaller|app"
  - "scp or object store|moved|env"
@h Examples
```bash title="tar recipes"
tar -czf backup-$(date +%F).tar.gz -C /var/www site       # create, gzip
tar -tzf backup-2026-10-30.tar.gz | head                  # list without extracting
tar -xzf backup-2026-10-30.tar.gz -C /tmp/restore         # extract to a folder
tar -cf - /etc | ssh backup@host 'cat > etc.tar'          # stream over SSH, no temp file
sha256sum backup-2026-10-30.tar.gz                        # checksum to verify later
```
@choose Picking a compressor
gzip | you want the most compatible format and quick speed | you need the smallest size
xz | size matters more than time, such as releases | you compress often or need speed
zstd | you want fast and well compressed, modern default | the receiving system is very old
@end
