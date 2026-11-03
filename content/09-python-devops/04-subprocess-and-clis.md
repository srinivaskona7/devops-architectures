---
title: Subprocess and command line tools
minutes: 45
objectives:
  - Run external commands safely without shell injection
  - Handle timeouts, exit codes and streamed output
  - Build command line tools with argparse, click and typer
  - Use exit codes and output streams the way shells expect
---
Operations tools call other programs and are called by people, cron and pipelines. Both directions need care: how you run commands, and how your own command accepts input and reports results.

@concept Running commands with subprocess.run
@plain
`subprocess.run` starts another program, waits for it, and returns an object with the exit code and, if you ask, the captured output.
@problem
Older ways such as `os.system` give you no output, no clean error handling and invite shell injection. Scripts must know whether `kubectl` or `git` actually succeeded.
@does
- Pass the command as a **list**: `["git", "status", "--short"]`.
- `capture_output=True, text=True` returns stdout and stderr as strings.
- `check=True` raises `CalledProcessError` on a non zero exit.
- `result.returncode`, `.stdout` and `.stderr` hold the outcome.
@diagram seq
caption: What run does for you
actors: ["Your script|Python|app", "Child|external program|env"]
steps:
  - "0>1: start with argument list | req"
  - "note 1..1: runs and prints"
  - "1>0: exit code, stdout, stderr | resp"
  - "note 0..0: check or inspect result"
@h Example
```python title="run a command and use the result" lab
import subprocess
import sys

res = subprocess.run(
    [sys.executable, "-c", "print('hello'); import sys; sys.exit(3)"],
    capture_output=True,
    text=True,
)
print("code:", res.returncode, "out:", res.stdout.strip())

try:
    subprocess.run([sys.executable, "-c", "raise SystemExit(2)"], check=True)
except subprocess.CalledProcessError as exc:
    print("failed with", exc.returncode)
```
@check
What does check=True do? || It raises CalledProcessError when the exit code is not zero.
@end

@concept Avoiding shell injection
@plain
A **shell** interprets characters such as `;`, `|`, `$()` and backticks. If untrusted text reaches a shell command line, it can run extra commands. Passing a list of arguments with no shell avoids the whole problem.
@problem
`subprocess.run(f"ping {host}", shell=True)` with `host = "x; rm -rf /"` runs two commands. Hostnames, branch names, and ticket titles all come from outside your control.
@does
- Default to `shell=False` with a list of arguments, so each item reaches the program as is.
- When you must build a shell string, quote parts with `shlex.quote`.
- Use `--` before user supplied values so they are not read as options.
- Validate input against an allow list or pattern first.
@diagram cmp
caption: Two ways to run the same command
cards:
  - {h: "String with shell=True", kind: bad, items: ["Shell parses user text", "Semicolons run extra commands", "Quoting is easy to get wrong"]}
  - {h: "List with shell=False", kind: ok, items: ["Arguments passed untouched", "No parsing, no injection", "Clearer to read"]}
@h Safe pattern
```python title="Validated and list based" lab
import re
import shlex
import subprocess
import sys

HOST_RE = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


def check_host(host: str) -> list[str]:
    if not HOST_RE.fullmatch(host):
        raise ValueError(f"invalid host: {host!r}")
    # list form: the value is one argument, never shell syntax
    return [sys.executable, "-c", "import sys; print('would ping', sys.argv[1])", host]


print(subprocess.run(check_host("example.com"), capture_output=True, text=True).stdout.strip())
try:
    check_host("x; rm -rf /")
except ValueError as e:
    print("rejected:", e)
print(shlex.quote("a b; c"))
```
:::danger
Never build shell commands from user, ticket or API data with f-strings and `shell=True`. That pattern is a code execution vulnerability.
:::
@check
How do you pass a hostname safely? || Validate it, then pass it as one item of an argument list with shell=False.
@end

@concept Timeouts, errors and streaming output
@plain
Commands can hang or print a lot. Set a timeout so your tool cannot wait forever, and stream output line by line when the program runs for a long time.
@problem
A hung `kubectl` or `ssh` stalls a pipeline until someone notices. Capturing a huge output into memory is also wasteful.
@does
- `timeout=30` raises `TimeoutExpired` and kills the child.
- `Popen` with `stdout=PIPE` lets you read lines as they arrive.
- Always handle a missing program: `FileNotFoundError` means the executable is not installed.
- Pass `env={**os.environ, "KEY": "value"}` to change the environment without losing `PATH`.
@diagram flow
caption: A defensive command wrapper
nodes:
  - "Validate input|before starting|info"
  - "run with timeout|bounded wait|app"
  - "Exit code|0 or not|env"
  - "Parse output|only on success|ok"
@h Wrapper
```python title="run_cmd.py" lab
from __future__ import annotations

import subprocess
import sys


def run_cmd(args: list[str], timeout: float = 30.0) -> str:
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=True)
    except FileNotFoundError:
        raise RuntimeError(f"{args[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{args[0]} timed out after {timeout}s") from None
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{args[0]} failed ({exc.returncode}): {exc.stderr.strip()}") from None
    return res.stdout


print(run_cmd([sys.executable, "-c", "print('fine')"]).strip())
try:
    run_cmd([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5)
except RuntimeError as e:
    print(e)

proc = subprocess.Popen([sys.executable, "-c", "print('a'); print('b')"], stdout=subprocess.PIPE, text=True)
assert proc.stdout is not None
for line in proc.stdout:
    print("streamed:", line.strip())
proc.wait()
```
@check
Which exception means the program is not installed? || FileNotFoundError.
@end

@concept Exit codes and standard streams
@plain
Every program ends with an **exit code**: 0 means success, anything else means failure. It prints results to **stdout** and diagnostics to **stderr**, so pipelines can separate them.
@problem
A script that prints "error" but exits 0 makes CI green on a failure. A script that mixes logs into stdout breaks `| jq` and other consumers.
@does
- Exit 0 on success; use 1 for a generic failure and 2 for bad usage (argparse does this).
- Use distinct codes for distinct outcomes when callers act on them, for example 3 for "findings present".
- Write data to stdout, messages to stderr (`print(..., file=sys.stderr)` or logging).
- Raise `SystemExit(code)` from `main`, not scattered `sys.exit` deep in helpers.
@diagram flow
caption: Streams in a pipeline
nodes:
  - "Your tool|reads args|app"
  - "stdout|data for the next program|ok"
  - "stderr|messages for humans|warn"
  - "Exit code|decision for CI|info"
@h Pattern
```python title="Clear contract" lab
import sys

EXIT_OK, EXIT_FINDINGS, EXIT_ERROR = 0, 3, 1


def main() -> int:
    findings = ["vol-1", "vol-2"]
    print("checking...", file=sys.stderr)
    for f in findings:
        print(f)                       # stdout is the data
    return EXIT_FINDINGS if findings else EXIT_OK


if __name__ == "__main__":
    code = main()
    print("exit code would be", code, file=sys.stderr)
```
@check
Where should progress messages go? || stderr, so stdout stays clean for piping.
@end

@concept argparse, the standard library CLI
@plain
`argparse` turns `sys.argv` into named, typed options, generates `--help`, and rejects bad usage with exit code 2.
@problem
Hand parsing arguments gives inconsistent flags, no help text, and silent mistakes such as ignoring a misspelled option.
@does
- `add_argument("--region", default="eu-west-1")` for options; positional arguments without dashes.
- `type=int`, `choices=[...]`, `required=True`, `action="store_true"` and `nargs="+"` shape input.
- `add_subparsers` builds commands like `tool list` and `tool delete`.
- `parse_args(argv)` accepts a list, which makes the CLI easy to test.
@diagram flow
caption: From a command line to a namespace
nodes:
  - "opskit scan --days 14 --dry-run|raw arguments|plain"
  - "ArgumentParser|rules and help|info"
  - "Namespace|days=14 dry_run=True|app"
  - "Your function|does the work|ok"
@h Subcommands
```python title="argparse with subcommands" lab
from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opskit", description="Small ops tools")
    sub = p.add_subparsers(dest="cmd", required=True)
    scan = sub.add_parser("scan", help="find idle resources")
    scan.add_argument("--days", type=int, default=14)
    scan.add_argument("--region", action="append", default=[])
    scan.add_argument("--dry-run", action="store_true")
    sub.add_parser("version", help="print version")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    ns = build_parser().parse_args(argv)
    if ns.cmd == "scan":
        print(f"scan days={ns.days} regions={ns.region or ['default']} dry={ns.dry_run}")
    else:
        print("0.1.0")
    return 0


print(main(["scan", "--days", "30", "--region", "eu-west-1", "--dry-run"]))
```
@check
Why pass argv explicitly to parse_args? || It makes the parser testable without touching sys.argv.
@end

@concept click, decorators for CLIs
@plain
`click` is a third party library where you decorate a function to declare options. It adds colour, prompts, environment variable defaults and nested command groups with little code.
@problem
Large argparse programs become long blocks of parser setup, separate from the function that uses the values.
@does
- `@click.command()` and `@click.option("--days", default=14, show_default=True)` define the interface next to the function.
- `envvar="OPSKIT_REGION"` lets an option read from the environment.
- `@click.group()` creates a tool with subcommands.
- `click.testing.CliRunner` runs commands in tests.
@diagram layers
caption: Pieces of a click tool
layers:
  - {label: "Declaration", nodes: ["group|top level command|cp", "command|one action|app", "option|flag with type and default|info"]}
  - {label: "Run time", nodes: ["Context|shared state|env", "echo|output to stdout or stderr|ok"]}
@h Example
```python title="click group" nocheck
import click


@click.group()
@click.option("--region", envvar="OPSKIT_REGION", default="eu-west-1", show_default=True)
@click.pass_context
def cli(ctx: click.Context, region: str) -> None:
    """Small ops tools."""
    ctx.obj = {"region": region}


@cli.command()
@click.option("--days", type=click.IntRange(min=1), default=14, show_default=True)
@click.option("--dry-run/--apply", default=True)
@click.pass_context
def scan(ctx: click.Context, days: int, dry_run: bool) -> None:
    """Find idle resources older than DAYS."""
    click.echo(f"region={ctx.obj['region']} days={days} dry_run={dry_run}")
    if not dry_run:
        click.echo("applying changes", err=True)


if __name__ == "__main__":
    cli()
```
@check
How does click read a default from the environment? || Give the option an envvar name, for example envvar="OPSKIT_REGION".
@end

@concept typer, type hints as the interface
@plain
`typer` builds on click and reads your function's type hints to create the options. A parameter with a default becomes an option; one without becomes an argument.
@problem
Even click requires repeating names and types in decorators. Typer removes that repetition for modern, typed code.
@does
- `typer.Typer()` is the app; `@app.command()` adds a command.
- `Annotated[int, typer.Option(help="Age")]` adds help text and constraints.
- Enums become choices, `Path` parameters are validated, and bool defaults produce `--flag/--no-flag`.
- Run it with `app()` or through a `[project.scripts]` entry point.
@diagram flow
caption: Typer derives the CLI from the signature
nodes:
  - "def scan(days: int = 14)|typed function|app"
  - "Typer|reads hints|info"
  - "--days INTEGER|option and help|env"
  - "Validated call|wrong types rejected|ok"
@h Example
```python title="typer app" nocheck
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(help="Small ops tools", no_args_is_help=True)


class Fmt(str, Enum):
    table = "table"
    json = "json"


@app.command()
def scan(
    days: Annotated[int, typer.Option(min=1, help="Minimum age in days")] = 14,
    fmt: Annotated[Fmt, typer.Option(help="Output format")] = Fmt.table,
    out: Annotated[Path | None, typer.Option(help="Write to a file")] = None,
) -> None:
    """Find idle resources."""
    typer.echo(f"days={days} fmt={fmt.value} out={out}")


if __name__ == "__main__":
    app()
```
@choose Picking a CLI library
argparse | no extra dependency, small tools, zipapps | you need many nested commands with rich help
click | larger tools with groups, prompts and plugins | you want the shortest typed code
typer | typed codebases that already use hints | you must avoid third party packages
@check
What decides whether a typer parameter is an option or an argument? || A default value makes it an option; no default makes it a required argument.
@end
