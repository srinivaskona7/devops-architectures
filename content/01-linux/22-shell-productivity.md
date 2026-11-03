---
title: Shell productivity
minutes: 45
objectives:
  - Keep sessions alive and organised with tmux
  - Edit quickly with essential vim commands
  - Write safe find and xargs recipes
  - Use regular expressions with grep, sed and awk correctly
---
Speed at the terminal is a daily advantage during incidents. These tools are on nearly every server, including minimal ones where nothing else is installed.

@concept tmux sessions, windows and panes
@plain
**tmux** keeps terminal sessions running on the server after you disconnect. Inside one session you can have several windows and split panes.
@problem
An SSH drop kills a long job, and during an incident you want logs, a shell and a dashboard side by side.
@does
- Default prefix is Ctrl-b. `tmux new -s fix` starts a named session; `tmux attach -t fix` returns to it.
- Prefix then `d` detaches, `c` new window, `%` split vertically, `"` split horizontally, arrows move, `[` enters scroll and copy mode, `z` zooms a pane.
- `tmux ls` lists sessions. Pair on an incident by attaching two users to the same session.
@diagram layers
caption: tmux hierarchy
layers:
  - {label: "Server", nodes: ["tmux server|survives your SSH disconnect|cp"]}
  - {label: "Session", nodes: ["fix|named, attachable|app"]}
  - {label: "Windows and panes", nodes: ["Window 1: logs|tail -f|env", "Window 2: shell|commands|env"]}
@h Start
```bash title="A repeatable incident layout" lab
tmux new-session -d -s fix -n logs 'journalctl -f'
tmux split-window -h -t fix:logs 'watch -n 2 uptime'
tmux new-window -t fix -n shell
tmux ls
# attach with: tmux attach -t fix   (detach with Ctrl-b d)
tmux kill-session -t fix
```
@check
What happens to a tmux session when SSH disconnects? || It keeps running on the server and you can reattach.
@end

@concept vim survival and speed
@plain
`vi` or `vim` exists on every server. It has **modes**: normal mode for commands, insert mode for typing, command-line mode for save and quit.
@problem
Not knowing how to exit vim is a joke; being unable to edit a config quickly on a broken machine is a real cost.
@does
- `i` insert, `Esc` back to normal. `:w` write, `:q` quit, `:wq` both, `:q!` quit without saving.
- Move: `h j k l`, `w`/`b` by word, `0`/`$` line start and end, `gg`/`G` file start and end, `/text` search, `n` next.
- Edit: `dd` delete line, `yy` copy, `p` paste, `u` undo, `.` repeat, `ciw` change word, `:%s/old/new/g` replace everywhere.
- `:set number` shows line numbers; `:e!` reload discarding changes; `sudo` problem: `:w !sudo tee %`.
@diagram flow
caption: Modes of vim
nodes:
  - "Normal|commands, default|ok"
  - "Insert|type text, press i|app"
  - "Command line|colon commands|info"
  - "Visual|select text, press v|plain"
@h Practise
```bash title="Create a file and edit it without a mouse" lab
printf 'port=80\nhost=old\nport=80\n' > /tmp/v.conf
vim -es -c '%s/old/new/g' -c 'wq' /tmp/v.conf      # scripted edit using ex mode
cat /tmp/v.conf
vimtutor    # a 30 minute interactive lesson, worth doing once
```
@check
How do you quit without saving? || Press Esc, then :q! and Enter.
@end

@concept find recipes
@plain
`find` walks directories and tests each file by name, type, size, age, owner or permission, then optionally acts on it.
@problem
Cleaning logs, finding large files or locating files with the wrong permissions across thousands of directories by hand is impractical.
@does
- Tests: `-name`, `-iname`, `-type f|d|l`, `-size +100M`, `-mtime +7` (older than 7 days), `-mmin -30`, `-user`, `-perm`.
- Actions: `-print`, `-delete`, `-exec cmd {} \;` (one run per file), `-exec cmd {} +` (batches), `-print0` for safe names.
- Prune what you do not want to descend into with `-path /proc -prune`.
- Always run with `-print` first, then add `-delete`.
@diagram flow
caption: Safe cleaning workflow
numbered: true
nodes:
  - "Describe|tests only, -print|info"
  - "Review|count and sample|warn"
  - "Act|-delete or -exec|app"
  - "Verify|df -h, find again|ok"
@h Recipes
```bash title="Common find tasks" lab
mkdir -p /tmp/ft && cd /tmp/ft && for i in 1 2 3; do echo x > "log $i.old"; done; touch -d '10 days ago' *.old
find /tmp/ft -type f -name '*.old' -mtime +7 -print              # review first
find /tmp/ft -type f -name '*.old' -mtime +7 -delete             # then delete
find /var/log -xdev -type f -size +50M -exec ls -lh {} + 2>/dev/null | head
find /etc -maxdepth 2 -type f -perm -o+w 2>/dev/null | head       # world writable files
```
:::danger
Put `-delete` last. Because tests are evaluated in order, `find . -delete -name x` deletes everything.
:::
@end

@concept xargs and safe pipelines
@plain
`xargs` takes lines from input and turns them into arguments for another command, in batches or in parallel.
@problem
Piping filenames with spaces or newlines into `rm` or `cp` breaks, and running 5000 commands one at a time is slow.
@does
- Use null separators: `find ... -print0 | xargs -0 cmd`.
- `-n 1` one argument per run, `-P 4` four at once, `-I{}` placeholder, `-r` (GNU) skips running on empty input.
- On macOS (BSD) some GNU options differ; check `man xargs`.
- For complex jobs, a `while read -r` loop or GNU `parallel` is clearer.
@diagram flow
caption: Find to xargs
nodes:
  - "find -print0|null separated names|app"
  - "xargs -0 -P 4|batches and parallel|cp"
  - "command|runs per batch|ok"
@h Recipes
```bash title="Parallel and safe" lab
cd /tmp/ft && printf 'a\n' > 'with space.txt'; printf 'b\n' > plain.txt
find . -name '*.txt' -print0 | xargs -0 wc -c
printf '%s\n' 1 2 3 4 | xargs -n 1 -P 2 sh -c 'echo "job $0"; sleep 1'
grep -rl 'ERROR' /var/log 2>/dev/null | head -3 | xargs -r ls -l
printf 'host1\nhost2\n' | xargs -I{} echo ssh {} uptime        # dry run: echo the command first
```
@check
Why use -print0 with -0? || Names with spaces or newlines stay intact instead of being split.
@end

@concept Regular expressions
@plain
A **regular expression** (regex) describes a text pattern. It lets you search, validate and replace without listing every possibility.
@problem
Finding all IPs, error lines or timestamps in 10 GB of logs needs a pattern language, and the differences between tools are a frequent source of bugs.
@does
- Basics: `.` any character, `*` zero or more, `+` one or more, `?` optional, `^` start, `$` end, `[abc]` set, `[0-9]` range, `(a|b)` alternatives, `\b` word boundary (GNU).
- Flavours: basic (grep default), extended (`grep -E`, `sed -E`, awk) and Perl-style (`grep -P` on GNU). macOS grep has no `-P`.
- Greedy quantifiers match as much as possible; test on sample data.
- Anchoring and escaping the dot (`\.`) avoids false matches like `1x2x3x4`.
@diagram cmp
caption: Which flavour to use
cards:
  - {h: "grep (basic)", kind: plain, items: ["Need backslashes for + ? |", "Default"]}
  - {h: "grep -E / sed -E / awk", kind: ok, items: ["Extended syntax", "Portable and readable"]}
  - {h: "grep -P", kind: info, items: ["Perl style, lookaheads, \\d", "GNU only"]}
@h Patterns
```bash title="Extract IPs and failed logins" lab
printf '10.0.0.5 GET /a 200\n10.0.0.7 GET /b 500\n1x2x3x4 bad\n' > /tmp/a.log
grep -Eo '\b([0-9]{1,3}\.){3}[0-9]{1,3}\b' /tmp/a.log          # dots escaped, so 1x2x3x4 is skipped
grep -E ' (4|5)[0-9]{2}$' /tmp/a.log                           # 4xx and 5xx lines
sed -E 's/^([0-9.]+) .* ([0-9]{3})$/\1 -> \2/' /tmp/a.log
awk '$NF ~ /^5[0-9][0-9]$/ {c++} END {print c+0, "server errors"}' /tmp/a.log
```
```python title="Same idea in Python" lab
import re
line = "2026-10-31T14:05:49Z ERROR payment failed id=4711"
m = re.search(r"^(\S+) (ERROR|WARN) (.*) id=(\d+)$", line)
print(m.groups())     # ('2026-10-31T14:05:49Z', 'ERROR', 'payment failed', '4711')
```
@end

@concept History, shortcuts and shell habits
@plain
The shell remembers commands and offers editing shortcuts that save thousands of keystrokes.
@problem
Retyping long commands invites typos, and some typos are destructive.
@does
- Ctrl-r searches history; `!!` repeats the last command (use `sudo !!`); `!$` is the last argument.
- Ctrl-a / Ctrl-e jump to line start and end, Ctrl-w deletes a word, Ctrl-u clears to the start, Ctrl-l clears the screen.
- Aliases and functions in `~/.bashrc` or `~/.zshrc`; keep `set -o pipefail` in scripts, not in the interactive shell.
- `HISTCONTROL=ignoreboth` and a leading space keep secrets out of history, but better not to type secrets on the command line.
@diagram flow
caption: Typical fast cycle
nodes:
  - "Ctrl-r|find an old command|info"
  - "Edit line|Ctrl-a, Alt-b, Ctrl-w|app"
  - "Dry run first|echo or --dry-run|warn"
  - "Run|and verify|ok"
@h Setup
```bash title="Helpful aliases and functions" nocheck
alias k=kubectl
alias kgp='kubectl get pods -o wide'
alias ll='ls -lah'
kns() { kubectl config set-context --current --namespace="$1"; }
export HISTCONTROL=ignoreboth HISTSIZE=50000
source <(kubectl completion bash) 2>/dev/null
complete -o default -F __start_kubectl k 2>/dev/null
```
@check
What does sudo !! do? || Re-runs the previous command with sudo.
@end

@concept Text pipelines for operations
@plain
Combining `grep`, `sort`, `uniq`, `cut`, `awk` and `jq` answers most log questions in one line.
@problem
Opening a log in an editor does not scale and offers no aggregation.
@does
- Count and rank: `sort | uniq -c | sort -rn | head`.
- Field work: `awk '{print $1}'`, `cut -d' ' -f1`, `column -t` for tables.
- JSON logs: `jq -r '.level + " " + .msg'`.
- Time range filters: lexical comparison works for ISO timestamps.
- `tail -f file | grep --line-buffered pattern` keeps streaming when piping into another command.
@diagram flow
caption: Top talkers pipeline
nodes:
  - "access.log|raw lines|plain"
  - "awk print $1|client IP|app"
  - "sort then uniq -c|count|info"
  - "sort -rn then head|ranked list|ok"
@h Examples
```bash title="Rank clients and slow requests" lab
printf '1.1.1.1 - 200 0.12\n2.2.2.2 - 500 2.40\n1.1.1.1 - 200 0.30\n' > /tmp/acc.log
awk '{print $1}' /tmp/acc.log | sort | uniq -c | sort -rn | head
awk '$4 > 1.0 {print $1, $3, $4}' /tmp/acc.log
printf '{"level":"error","msg":"db timeout"}\n{"level":"info","msg":"ok"}\n' | jq -r 'select(.level=="error") | .msg'
```
:::tip
Build pipelines one stage at a time and look at the output after each pipe. Save good ones as shell functions.
:::
@end
