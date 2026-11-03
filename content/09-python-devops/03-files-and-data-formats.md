---
title: Files, paths and data formats
minutes: 45
objectives:
  - Handle paths and files with pathlib instead of string joining
  - Write files atomically so readers never see half a file
  - Read and write JSON, YAML, TOML and CSV safely
  - Choose the right format for configuration and for reports
---
Operations work is mostly reading something, deciding, and writing something. These concepts cover the standard library tools for files and the four formats you meet every day.

@concept pathlib basics
@plain
`pathlib.Path` represents a file path as an object. You join with `/`, ask questions with methods, and the same code works on Linux, macOS and Windows.
@problem
Gluing paths with string concatenation breaks on missing or doubled slashes, and `os.path.join` chains are hard to read. Mistakes here delete or overwrite the wrong files.
@does
- `Path("/etc") / "hosts"` joins; `.name`, `.stem`, `.suffix`, `.parent` take paths apart.
- `.exists()`, `.is_file()`, `.is_dir()` test; `.stat().st_size` gives size and `.st_mtime` the modified time.
- `.glob("*.log")` and `.rglob("*.log")` find files; `.resolve()` makes the path absolute and follows links.
- `Path.home()` and `Path.cwd()` give well known starting points.
@diagram flow
caption: Taking a path apart and rebuilding it
nodes:
  - "/var/log/app/web.log.1|the path|plain"
  - "parent|/var/log/app|info"
  - "name|web.log.1|info"
  - "with_suffix|new path object|ok"
@h Try it
```python title="pathlib tour" lab
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as d:
    root = Path(d)
    (root / "app").mkdir()
    (root / "app" / "web.log").write_text("one\ntwo\n")
    (root / "app" / "db.log").write_text("x\n")
    for p in sorted(root.rglob("*.log")):
        print(p.relative_to(root), p.stat().st_size, "bytes", p.suffix)
    print((root / "app" / "web.log").with_suffix(".txt").name)
```
@check
Why use `/` on Path objects instead of f-strings? || It handles separators for you and keeps the value a Path with useful methods.
@end

@concept Reading and writing files safely
@plain
Open files with a `with` block so they are always closed, and say the encoding explicitly. For large files, read line by line rather than loading everything.
@problem
Forgotten close calls leak file handles. Default encodings differ between hosts, so a script that works on a laptop fails on a server with a different locale. Reading a 5 GB log into memory crashes the job.
@does
- `path.read_text(encoding="utf-8")` and `write_text` suit small files.
- `with path.open() as f: for line in f:` streams one line at a time.
- `errors="replace"` stops one bad byte from killing a log run.
- Use `mode="x"` to create a file only if it does not exist yet.
@diagram cmp
caption: Small file versus large file
cards:
  - {h: "Small config file", kind: ok, items: ["read_text then parse", "Whole content in memory", "Simple and clear"]}
  - {h: "Large log file", kind: info, items: ["Iterate line by line", "Constant memory", "Count or filter as you go"]}
@h Streaming a log
```python title="Count error lines without loading the file" lab
from pathlib import Path
import tempfile

with tempfile.TemporaryDirectory() as d:
    log = Path(d) / "app.log"
    log.write_text("ok\nERROR disk full\nok\nERROR timeout\n", encoding="utf-8")
    errors = 0
    with log.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.startswith("ERROR"):
                errors += 1
    print("errors:", errors)
```
@check
What does errors="replace" do? || Undecodable bytes become a replacement character instead of raising an exception.
@end

@concept Atomic writes and temporary files
@plain
An **atomic write** writes the new content to a temporary file in the same folder and then renames it over the target. A rename is a single step, so readers see either the old file or the new one, never half of it.
@problem
If a script crashes or the disk fills while writing a config or state file directly, the file is left truncated, and the next run or another program reads garbage.
@does
- `tempfile.NamedTemporaryFile(dir=target.parent, delete=False)` makes a temp file on the same filesystem.
- `os.fsync` asks the OS to flush data to disk before the rename.
- `os.replace(tmp, target)` swaps atomically on the same filesystem, on Linux and Windows.
@diagram seq
caption: Atomic replace of a state file
actors: ["Writer|your script|app", "Temp file|same folder|env", "Target|state.json|ok"]
steps:
  - "0>1: write full content | req"
  - "0>1: flush and fsync | req"
  - "0>2: os.replace(temp, target) | resp"
  - "note 2..2: readers never see half"
@h Helper
```python title="atomic_write.py" lab
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


with tempfile.TemporaryDirectory() as d:
    p = Path(d) / "state.json"
    atomic_write_text(p, '{"version": 1}')
    atomic_write_text(p, '{"version": 2}')
    print(p.read_text())
```
@check
Why must the temp file be in the same folder? || A rename is only atomic inside one filesystem; moving across filesystems becomes a copy.
@end

@concept JSON
@plain
JSON is text made of objects, arrays, strings, numbers, booleans and null. It is what almost every API and cloud CLI returns, and Python's `json` module reads and writes it.
@problem
You need a format that programs written in any language can exchange, and that survives being stored and shipped.
@does
- `json.loads(text)` and `json.dumps(obj)` work with strings; `json.load(f)` and `json.dump(obj, f)` with files.
- `indent=2` and `sort_keys=True` give stable, diff friendly output.
- Dates and sets are not JSON types; pass `default=str` or convert them yourself.
- JSON Lines (one object per line) suits logs and streams.
@diagram flow
caption: Round trip between Python and JSON
nodes:
  - "dict and list|Python objects|app"
  - "json.dumps|text|info"
  - "File or API|storage and network|ext"
  - "json.loads|back to objects|ok"
@h Example
```python title="JSON and JSON Lines" lab
import json
from datetime import datetime, timezone

record = {"id": "i-123", "seen": datetime(2026, 1, 5, tzinfo=timezone.utc), "tags": ["web", "prod"]}
text = json.dumps(record, indent=2, sort_keys=True, default=str)
print(text)
print(json.loads(text)["tags"])

lines = [json.dumps({"n": i}) for i in range(3)]
print("\n".join(lines))
print([json.loads(l)["n"] for l in lines])
```
@check
Why use JSON Lines for big outputs? || Each line is a complete record, so you can stream, append and parse without loading the whole document.
@end

@concept YAML, always with safe_load
@plain
YAML is a human friendly format used by Kubernetes, Ansible, Helm and CI systems. PyYAML reads it, but only the safe functions should be used on files you do not fully control.
@problem
`yaml.load` without a safe loader can construct arbitrary Python objects, which lets a crafted file run code. Kubernetes manifests also contain many documents in one file.
@does
- `yaml.safe_load(text)` returns plain dicts, lists and scalars.
- `yaml.safe_load_all(text)` yields each `---` separated document.
- `yaml.safe_dump(obj, sort_keys=False)` writes YAML and keeps your key order.
- Beware the Norway problem: with YAML 1.1 rules `no` can be read as `False`. Quote strings such as country codes.
@diagram cmp
caption: Loader choices
cards:
  - {h: "yaml.safe_load", kind: ok, items: ["Plain data types only", "Use for every input", "Multi-document via safe_load_all"]}
  - {h: "yaml.load with FullLoader or none", kind: bad, items: ["Can build arbitrary objects", "Never on untrusted files", "Avoid in tools"]}
@h Reading manifests
```python title="Count kinds in a multi-document manifest" lab
import yaml
from collections import Counter

text = """
apiVersion: v1
kind: Namespace
metadata: {name: demo}
---
apiVersion: apps/v1
kind: Deployment
metadata: {name: web, namespace: demo}
spec: {replicas: 2}
---
apiVersion: v1
kind: Service
metadata: {name: web, namespace: demo}
"""
docs = [d for d in yaml.safe_load_all(text) if d]
print(Counter(d["kind"] for d in docs))
print(yaml.safe_dump(docs[1], sort_keys=False))
```
:::warn
YAML round trips lose comments. If you must edit a file and keep comments, use `ruamel.yaml`, not PyYAML.
:::
@check
Which function reads a file with several --- documents? || yaml.safe_load_all.
@end

@concept TOML for configuration
@plain
TOML is a simple configuration format with sections and typed values. Python 3.11 can read it with the built in `tomllib`; writing needs a third party package such as `tomli-w`.
@problem
INI files have no types or lists, YAML has surprising rules, and JSON has no comments. Tool configuration needs something readable and strict.
@does
- `tomllib.load(f)` needs a file opened in binary mode (`"rb"`); `tomllib.loads(text)` takes text.
- Gives you real integers, booleans, lists and dates.
- It is the format of `pyproject.toml`, so your tool config can live in the same file under `[tool.yourtool]`.
@diagram flow
caption: Config from file to typed values
nodes:
  - "tool.toml|text with comments|plain"
  - "tomllib.loads|parser|info"
  - "dict|typed values|app"
  - "dataclass|validated settings|ok"
@h Example
```python title="Reading TOML into a dataclass" lab
import tomllib
from dataclasses import dataclass

TEXT = """
# thresholds for the volume checker
[checker]
min_age_days = 14
regions = ["eu-west-1", "us-east-1"]
dry_run = true
"""


@dataclass
class Checker:
    min_age_days: int
    regions: list[str]
    dry_run: bool = True


cfg = Checker(**tomllib.loads(TEXT)["checker"])
print(cfg)
```
@check
Why does tomllib.load need a binary file? || The parser decodes UTF-8 itself, so the file must be opened with "rb".
@end

@concept CSV for reports
@plain
CSV is rows of values separated by commas. The `csv` module handles quoting, so a comma or newline inside a value does not break the file. Spreadsheets and finance teams open it directly.
@problem
Building lines by hand with `",".join(...)` corrupts rows when a value contains a comma, a quote or a line break.
@does
- `csv.DictReader` yields each row as a dict keyed by the header.
- `csv.DictWriter` writes dicts with a fixed column order.
- Open files with `newline=""` so line endings are not mangled.
- All values come back as strings; convert numbers yourself.
@diagram flow
caption: Producing a report file
nodes:
  - "Collect|list of dicts|app"
  - "DictWriter|quoting handled|info"
  - "report.csv|opens in a spreadsheet|ok"
@h Write and read back
```python title="csv round trip" lab
import csv
import io

rows = [
    {"volume": "vol-1", "size_gb": 100, "owner": "team, platform"},
    {"volume": "vol-2", "size_gb": 50, "owner": "unknown"},
]
buf = io.StringIO(newline="")
w = csv.DictWriter(buf, fieldnames=["volume", "size_gb", "owner"])
w.writeheader()
w.writerows(rows)
print(buf.getvalue())

buf.seek(0)
total = sum(int(r["size_gb"]) for r in csv.DictReader(buf))
print("total GB:", total)
```
@choose Format choice
JSON | machine to machine data and API payloads | people must edit it by hand and want comments
YAML | Kubernetes, CI and files people edit often | the input is untrusted and you cannot use safe_load
TOML | tool configuration with typed values | you need deeply nested data
CSV | flat tables for spreadsheets | records are nested or contain mixed types
@check
Why open CSV files with newline=""? || So the csv module controls line endings and embedded newlines are kept intact.
@end
