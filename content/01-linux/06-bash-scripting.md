---
title: Bash scripting
minutes: 50
objectives:
  - Write scripts with variables, tests, loops and functions
  - Make scripts safe with quoting, strict mode, traps and temporary files
  - Parse arguments, validate input and return meaningful exit codes
---
A shell script is the glue of operations work: deploy hooks, backups, health checks and CI steps. The difference between a script that works on your laptop and one you can trust at 3 a.m. is a handful of habits covered here.

@concept Variables, quoting and expansion
@plain
A variable stores text. The shell replaces `$name` with its value *before* running the command, and it splits unquoted values on spaces. Quoting controls that splitting.
@problem
Unquoted variables are the number one source of shell bugs. A file called `my report.txt` becomes two arguments, and an empty variable makes `rm -rf $dir/` become `rm -rf /`.
@does
- Assign without spaces: `name=value`. Read with `"$name"`. Always double-quote expansions.
- Single quotes keep text literal. Double quotes allow `$var` and `$(command)`.
- `${var:-default}` supplies a default, `${var:?message}` aborts if unset, `${var%.txt}` strips a suffix, `${#var}` gives the length.
- Arrays hold lists safely: `files=(a.txt "b c.txt")`, expanded with `"${files[@]}"`.
@diagram flow
caption: What the shell does to a line before running it
numbered: true
nodes:
  - "You type|rm $dir/*.log|plain"
  - "Expand|variables, commands, globs|info"
  - "Split|on spaces unless quoted|warn"
  - "Run|program gets final arguments|ok"
@h Quoting in practice
```bash title="Quoting rules" lab
f="my report.txt"
touch "$f"
ls $f 2>&1 | head -2          # unquoted: two arguments, so two errors
ls "$f"                       # quoted: one argument, works
name=${1:-world}              # default value when no argument is given
echo "hello, ${name}"
echo 'single quotes: $name stays literal'
files=(one.txt "two words.txt")
printf '%s\n' "${files[@]}"   # each element stays intact
echo "${f%.txt}"              # strip the suffix
```
:::warn
Never write `rm -rf $dir/*` with an unchecked variable. Use `rm -rf "${dir:?dir is empty}"/*` so the script stops if `dir` is unset or empty.
:::
@check
Why quote "$var" almost everywhere? || Unquoted values are split on whitespace and expanded as globs, which breaks on spaces and can match unintended files.
@end

@concept Tests and conditionals
@plain
`if` runs a command and branches on its exit code. `[[ ... ]]` is the bash test for strings, numbers and files.
@problem
Scripts must check that inputs exist and that previous steps worked before they do anything destructive.
@does
- File tests: `-f` regular file, `-d` directory, `-r` readable, `-x` executable, `-s` non-empty, `-e` exists.
- String tests: `-z` empty, `-n` non-empty, `==` equal, `=~` regex match.
- Numeric tests use `-eq -ne -lt -gt -le -ge` inside `[[ ]]`, or `(( a > b ))`.
- Combine with `&&`, `||` and `!`. `case` matches one value against several patterns.
@diagram flow
caption: A guard clause pattern keeps scripts flat and readable
nodes:
  - "Check input|file exists? arg set?|info"
  - "Fail early|message to stderr, exit 2|bad"
  - "Do the work|only reached when valid|ok"
@h Conditionals
```bash title="if, case and guards" lab
file=/etc/hostname
if [[ -r "$file" ]]; then echo "readable"; else echo "missing" >&2; fi
count=7
(( count > 5 )) && echo "more than five"
read -r env <<< "prod"
case "$env" in
  dev|test) echo "safe to experiment" ;;
  prod)     echo "extra care" ;;
  *)        echo "unknown environment" >&2; exit 2 ;;
esac
[[ "$env" =~ ^(dev|test|prod)$ ]] && echo "valid environment"
```
@end

@concept Loops and reading input
@plain
Loops repeat work: over a list of items, over lines of a file, or until a condition is met.
@problem
Operations tasks are repetitive: check ten hosts, process every file, retry until a service is up.
@does
- `for x in a b c; do ...; done` and `for f in *.log; do ...; done` for lists and globs.
- `while read -r line; do ...; done < file` reads a file line by line without word-splitting.
- `until command; do sleep 2; done` waits for success.
- `break` and `continue` control flow. Never parse `ls` output; use globs or `find -print0`.
@diagram flow
caption: A retry loop with a limit
numbered: true
nodes:
  - "Try the command|curl the health URL|app"
  - "Success?|exit code 0|info"
  - "Wait|sleep, increase the delay|warn"
  - "Give up|after N attempts|bad"
@h Examples
```bash title="Loops" lab
for host in web1 web2 db1; do printf 'checking %s\n' "$host"; done
for f in /etc/*.conf; do [[ -f "$f" ]] && echo "$f"; done | head -3
printf 'a 1\nb 2\n' | while read -r key value; do echo "$key=$value"; done
attempt=0
until [[ $attempt -ge 3 ]]; do
  attempt=$((attempt + 1)); echo "attempt $attempt"
  true && break
  sleep 1
done
```
@check
Why use read -r? || Without -r, backslashes are interpreted and mangle the input.
@end

@concept Functions and structure
@plain
A function groups commands under a name. Well-structured scripts define small functions, then a `main` that calls them.
@problem
Long scripts of straight-line commands are hard to test, reuse and read.
@does
- `name() { ...; }` defines it. Arguments are `$1`, `$2`, `"$@"`. `return N` sets the exit code; output goes to stdout.
- Use `local` for variables so functions do not leak state.
- `log()` and `die()` helpers give consistent messages and exit codes.
- End the file with `main "$@"` so sourcing the file for tests does not run it.
@diagram layers
caption: Layout of a maintainable script
layers:
  - {label: "Header", nodes: ["shebang|#!/usr/bin/env bash|plain", "set -euo pipefail|strict mode|warn"]}
  - {label: "Helpers", nodes: ["log, die|consistent output|app", "usage|help text|app"]}
  - {label: "Logic", nodes: ["small functions|one job each|ok"]}
  - {label: "Entry", nodes: ["main \"$@\"|single entry point|env"]}
@h A template
```bash title="Script template" lab
#!/usr/bin/env bash
set -euo pipefail

log() { printf '%s %s\n' "$(date +%T)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

check_disk() {
  local path=$1 limit=${2:-90} used
  used=$(df --output=pcent "$path" 2>/dev/null | tail -1 | tr -dc '0-9')
  [[ -n "$used" ]] || die "cannot read $path"
  (( used < limit ))
}

main() {
  check_disk / 95 && log "disk ok" || die "disk is nearly full"
}
main "$@"
```
@end

@concept Safe scripts: strict mode, traps and temp files
@plain
Strict mode makes a script stop at the first problem. A `trap` runs cleanup code however the script ends. `mktemp` creates unpredictable temporary files.
@problem
By default bash keeps going after errors, uses unset variables as empty strings and leaves temporary files behind, which turns small mistakes into incidents.
@does
- `set -e` exits when a command fails, `set -u` errors on unset variables, `set -o pipefail` fails a pipeline if any part fails.
- `trap 'cleanup' EXIT` runs on every exit; `trap ... ERR` can report the failing line.
- `mktemp -d` makes a private directory, deleted in the trap.
- `flock` prevents two copies of a cron job running at once.
- Check scripts with `bash -n` (syntax) and `shellcheck` (bugs).
@diagram flow
caption: Cleanup always runs
nodes:
  - "Start|create temp dir, set trap|info"
  - "Work|may fail anywhere|warn"
  - "EXIT trap|removes temp dir, releases lock|ok"
@h Hardened skeleton
```bash title="Strict mode, trap, lock" lab
#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'
tmp=$(mktemp -d)
cleanup() { rm -rf "$tmp"; }
trap cleanup EXIT
trap 'echo "failed at line $LINENO" >&2' ERR
exec 9>"$tmp/lock"
flock -n 9 || { echo "already running" >&2; exit 1; }
echo "working in $tmp"
```
@choose Bash or Python
Bash | gluing commands, small file and process tasks | parsing JSON deeply, complex logic, tests
Python | structured data, APIs, retries, unit tests | a three-line pipeline
@end

@concept Arguments, options and exit codes
@plain
Real scripts take options such as `-f file` or `--dry-run`. `getopts` parses short options, and a consistent exit code tells callers what happened.
@problem
Hard-coded values make scripts single-use, and silent failures make automation unreliable.
@does
- `getopts "f:t:h" opt` reads options; `shift $((OPTIND-1))` leaves the remaining arguments.
- Validate everything before acting. Offer `--dry-run` for destructive scripts.
- Exit codes: 0 success, 1 failure, 2 usage error, 64-78 are the sysexits convention.
- Print help to stdout when asked, errors to stderr.
@diagram seq
caption: A script as a good command-line citizen
actors: ["Caller|CI or person|app", "Script|check.sh|env"]
steps:
  - "0>1: -f access.log -t 10 | req"
  - "note 1..1: validate options, read file"
  - "1>0: exit 0 or 1 | resp"
  - "1>0: usage on stderr, exit 2 | bad"
@h Tested example
This script was run against a sample log during development: with threshold 50 it exited 0, with threshold 10 it exited 1 and printed the alert, and with no arguments it exited 2.
```bash title="check.sh" lab
#!/usr/bin/env bash
set -euo pipefail
usage() { echo "usage: $0 -f LOGFILE [-t PERCENT]" >&2; exit 2; }
threshold=5
while getopts "f:t:" opt; do
  case $opt in
    f) file=$OPTARG ;;
    t) threshold=$OPTARG ;;
    *) usage ;;
  esac
done
[[ -n "${file:-}" && -r "$file" ]] || usage
total=$(wc -l <"$file" | tr -d ' ')
errors=$(awk '$9 ~ /^5/ {n++} END {print n+0}' "$file")
rate=$(awk -v e="$errors" -v t="$total" 'BEGIN {printf "%.1f", 100*e/t}')
echo "requests=$total errors=$errors rate=${rate}%"
awk -v r="$rate" -v th="$threshold" 'BEGIN {exit (r > th) ? 1 : 0}' || { echo "ALERT: above ${threshold}%" >&2; exit 1; }
```
@check
Which exit code means the caller used the script wrongly? || 2 by convention; 1 is a general runtime failure.
@end
