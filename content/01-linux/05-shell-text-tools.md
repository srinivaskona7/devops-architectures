---
title: Shell, pipes and text tools
minutes: 45
objectives:
  - Explain standard input, output and error and combine commands with pipes
  - Search and transform text with grep, sed, awk, cut, sort and uniq
  - Process JSON and run work in parallel with jq and xargs
---
Linux tools are small and do one thing. The shell lets you connect them, so a one-line pipeline can answer a question that would take a program in another environment. Most log analysis, incident triage and CI scripting is exactly this skill.

@concept Standard streams and redirection
@plain
Every program starts with three channels: **standard input** (0) where it reads, **standard output** (1) where it writes results, and **standard error** (2) where it writes problems. The shell can point each one at a file or at another program.
@problem
If results and errors were mixed, you could not save the data without the noise, or see the errors while saving the data. Separate channels let you route each independently.
@does
- `>` writes output to a file (replacing it), `>>` appends, `<` reads from a file.
- `2>` redirects errors, `2>&1` sends errors to wherever output goes, `&>` redirects both.
- `/dev/null` discards anything written to it.
- A pipe `|` connects one program's output to the next program's input without a temporary file.
@diagram flow
caption: Three streams around a program
nodes:
  - "stdin (0)|keyboard, file or pipe|info"
  - "Program|reads, works, writes|app"
  - "stdout (1)|results|ok"
  - "stderr (2)|errors and warnings|bad"
@h Redirection in practice
```bash title="Routing the three streams" lab
ls /nonexistent /tmp > out.txt 2> err.txt      # results to one file, errors to another
ls /nonexistent /tmp > both.txt 2>&1           # both into one file (order matters: 2>&1 comes last)
ls /nonexistent 2>/dev/null                    # hide errors
echo "line" >> app.log                         # append
sort < out.txt | head -3                       # read from a file, pipe the result on
```
@check
What does `cmd > file 2>&1` do compared to `cmd 2>&1 > file`? || The first sends both streams to the file. The second points errors at the terminal first and only then redirects output, so errors stay on the screen.
@end

@concept Pipes and exit codes
@plain
A pipeline runs all its programs at once, each feeding the next. Every command also finishes with an **exit code**: 0 means success and any other number means a failure.
@problem
You need to know whether a long chain worked. By default only the *last* command's code is reported, so a failure early in a pipeline can be hidden.
@does
- `$?` holds the last exit code. `&&` runs the next command only on success, `||` only on failure.
- `set -o pipefail` makes a pipeline fail if *any* stage fails.
- Conventions: 0 success, 1 general error, 2 misuse, 126 not executable, 127 not found, 130 interrupted by Ctrl-C, 143 killed by SIGTERM (128 + 15).
@diagram seq
caption: A pipeline with and without pipefail
actors: ["Stage 1|false|bad", "Stage 2|true|ok", "Shell|reports|cp"]
steps:
  - "0>1: data flows | req"
  - "1>2: exit 0 | resp"
  - "0>2: exit 1 | bad"
  - "note 0..2: default: reports 0 (only the last stage)"
  - "note 0..2: with pipefail: reports 1"
@h Proving it
```bash title="Exit codes" lab
true;  echo "true -> $?"
false; echo "false -> $?"
grep -q zzz /etc/hostname; echo "no match -> $?"        # grep returns 1 when nothing matches
bash -c 'false | true; echo "default: $?"'
bash -c 'set -o pipefail; false | true; echo "pipefail: $?"'
mkdir -p /tmp/work && cd /tmp/work && echo "ran in $(pwd)"   # && stops the chain if mkdir fails
```
:::tip
Start every non-trivial script with `set -euo pipefail`: exit on error, treat unset variables as errors, and fail a pipeline when any part fails.
:::
@end

@concept Searching with grep
@plain
`grep` prints the lines that match a pattern. It is the quickest way to find the needle in a log haystack.
@problem
Logs and configuration files have thousands of lines and you rarely want most of them. You need to ask "show me only the lines that mention this error".
@does
- `-i` ignores case, `-v` inverts (lines that do *not* match), `-c` counts, `-n` shows line numbers, `-r` recurses into folders.
- `-A 3 -B 3` shows context lines after and before a match.
- `-E` enables extended regular expressions (alternation with `|`, `+`, `?`, `{n}`).
- `-o` prints only the matching part, useful for extracting values.
@diagram flow
caption: grep is a filter
nodes:
  - "All lines|10,000|plain"
  - "grep -i error|only matching lines|info"
  - "grep -v health|drop noise|warn"
  - "Signal|the lines that matter|ok"
@h Examples
```bash title="grep recipes"
grep -in 'connection refused' /var/log/app.log          # case-insensitive with line numbers
grep -E 'HTTP/1\.1" 5[0-9]{2}' access.log | head        # every 5xx response
grep -c ' 502 ' access.log                              # how many 502s
grep -B2 -A2 'OutOfMemory' app.log                      # two lines of context each side
grep -oE '[0-9]{1,3}(\.[0-9]{1,3}){3}' access.log | sort -u   # extract unique IP addresses
```
@end

@concept Transforming with sed, cut, sort and uniq
@plain
`sed` edits a stream of text line by line. `cut` takes columns. `sort` orders lines. `uniq -c` counts neighbours that are identical, which is why it is almost always used after `sort`.
@problem
Raw data needs reshaping before it is useful: mask a password, pull one column, rank the most common values.
@does
- `sed 's/old/new/g'` substitutes; `-i` edits the file in place (use `-i.bak` to keep a backup); `-n '10,20p'` prints a range.
- `cut -d' ' -f1,7` picks fields; `tr 'a-z' 'A-Z'` maps characters.
- `sort -n` numeric, `-r` reverse, `-u` unique, `-k2` by second field. `uniq -c` prefixes a count.
- The pattern "extract, sort, count, rank" answers most "top N" questions.
@diagram flow
caption: The top-N pattern
numbered: true
nodes:
  - "Extract|awk or cut one column|info"
  - "sort|group equal values|app"
  - "uniq -c|count each group|env"
  - "sort -rn|largest first|warn"
  - "head|top N|ok"
@h Worked example on a real access log
The output below was produced by running these commands on a six-line sample log.
```bash title="Top clients, status codes and the error rate"
awk '{print $1}' access.log | sort | uniq -c | sort -rn | head -3
awk '{print $9}' access.log | sort | uniq -c | sort -k2
awk '$9 ~ /^5/ {e++} END {printf "%.1f%% (%d of %d)\n", 100*e/NR, e, NR}' access.log
sed -E 's/([0-9]+\.[0-9]+\.[0-9]+)\.[0-9]+/\1.x/' access.log      # mask the last octet
```
```text title="Output on the sample"
   3 203.0.113.5
   2 198.51.100.7
   1 203.0.113.9

   3 200
   1 304
   2 502

33.3% (2 of 6)
```
:::warn
`sed -i` rewrites the file immediately. Run it without `-i` first, or use `-i.bak`, and in version control use `git diff` to review.
:::
@end

@concept awk for columns and calculations
@plain
`awk` reads lines, splits them into fields (`$1`, `$2`, ...), and runs small programs on them. It is a tiny spreadsheet for text.
@problem
`cut` cannot do arithmetic or conditions, and writing a full script for a quick sum or filter is overkill.
@does
- A program is `pattern { action }`. With no pattern the action runs on every line; `BEGIN` and `END` run once before and after.
- Built-ins: `NR` line number, `NF` field count, `$NF` last field, `FS` field separator.
- Variables and arrays let you sum, average and group.
@diagram flow
caption: An awk program has three phases
nodes:
  - "BEGIN|runs once first|info"
  - "pattern { action }|runs per line|app"
  - "END|runs once at the end|ok"
@h Recipes
```bash title="awk in practice"
awk '{sum += $10} END {print sum/1024 " KiB served"}' access.log        # total bytes
awk '{n[$7]++} END {for (p in n) print n[p], p}' access.log | sort -rn   # hits per path
awk -F: '$3 >= 1000 {print $1}' /etc/passwd                              # human accounts (UID >= 1000)
awk 'NR==1 || /ERROR/' app.log                                           # header plus error lines
```
@choose Which tool
grep | you want whole lines that match | you need to compute or rearrange columns
sed | you want a substitution or a range of lines | you need arithmetic or grouping
awk | you need columns, conditions, sums or counts | the job needs real data structures; use a script language
cut | one simple fixed column or character range | the delimiter is irregular, such as repeated spaces
@end

@concept JSON with jq, and parallel work with xargs
@plain
Modern tools return **JSON**, which the line-oriented tools handle badly. `jq` is "awk for JSON". `xargs` turns a list of lines into arguments for another command, and can run many at once.
@problem
`kubectl`, `aws` and `docker inspect` produce JSON. Parsing it with `grep` breaks on formatting. And running one command per item in a loop is slow when items are independent.
@does
- `jq '.items[].metadata.name'` walks into the structure; `-r` prints raw strings without quotes; `select()` filters; `map()` transforms.
- `xargs -n1` runs the command once per item; `-P 4` runs four at a time; `-0` with `find -print0` handles odd file names safely.
@diagram flow
caption: From a JSON document to an action
nodes:
  - "kubectl get pods -o json|large document|ext"
  - "jq select|keep failing pods|info"
  - "jq -r name|plain list|app"
  - "xargs -P4|act on each, four at once|ok"
@h Recipes
```bash title="jq and xargs" nocheck
kubectl get pods -A -o json | jq -r '.items[] | select(.status.phase!="Running") | "\(.metadata.namespace)/\(.metadata.name)"'
aws ec2 describe-instances --query 'Reservations[].Instances[].InstanceId' --output text | tr '\t' '\n'
find . -name '*.log' -print0 | xargs -0 -P4 -n1 gzip -9          # compress logs, four at a time
docker inspect --format '{{.State.Health.Status}}' web            # built-in templates avoid jq sometimes
```
@check
Why use find -print0 with xargs -0? || File names can contain spaces or newlines; NUL separators are the only safe delimiter.
@end
