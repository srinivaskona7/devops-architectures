---
title: Packaging, project layout and typing
minutes: 45
objectives:
  - Lay out an operations project so it is importable, testable and installable
  - Build a wheel and expose commands through entry points
  - Add type hints and check them with mypy
  - Model structured data with dataclasses, TypedDict and Protocol
---
A script that grows beyond one file needs a shape. This section turns loose scripts into a small package and adds types so mistakes are found before they reach production.

@concept Modules and the src layout
@plain
A **module** is one `.py` file; a **package** is a folder of modules with an `__init__.py`. The **src layout** puts the package under `src/` so tests import the installed code, not whatever sits in the current folder.
@problem
Scripts that import each other by relative file position work on your laptop and break in cron, in CI or in a container, because the working directory differs.
@does
- Keeps code in `src/opskit/`, tests in `tests/`, and configuration in `pyproject.toml`.
- `pip install -e .` makes `import opskit` work anywhere in that environment.
- `if __name__ == "__main__":` lets a file act as both a library and a script.
@diagram layers
caption: A small project on disk
layers:
  - {label: "Repository root", nodes: ["pyproject.toml|metadata and tools|cp", "uv.lock|exact versions|info", "README.md|how to use|plain"]}
  - {label: "src/opskit", nodes: ["__init__.py|marks the package|app", "cli.py|argument parsing|app", "aws.py|cloud calls|app", "report.py|formatting|app"]}
  - {label: "tests", nodes: ["test_report.py|pure logic tests|ok", "conftest.py|shared fixtures|ok"]}
@h A minimal module
```python title="src/opskit/report.py"
"""Format simple tables for terminals."""
from __future__ import annotations


def render_table(rows: list[dict[str, object]], columns: list[str]) -> str:
    widths = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in columns} if rows else {c: len(c) for c in columns}
    head = "  ".join(c.ljust(widths[c]) for c in columns)
    lines = [head, "  ".join("-" * widths[c] for c in columns)]
    for r in rows:
        lines.append("  ".join(str(r.get(c, "")).ljust(widths[c]) for c in columns))
    return "\n".join(lines)


if __name__ == "__main__":
    print(render_table([{"name": "web-1", "state": "running"}], ["name", "state"]))
```
@check
Why use a src layout? || It forces tests and tools to import the installed package, which catches missing files and wrong imports early.
@end

@concept Building a wheel
@plain
A **wheel** is a ready to install archive of your package. Building one turns your code into something `pip` or `uv` can install anywhere without running your build scripts.
@problem
Copying a folder to a server leaves out dependency declarations and entry points, and gives no version you can roll back to.
@does
- `python -m build` (or `uv build`) produces `dist/opskit-0.1.0-py3-none-any.whl` and a source archive.
- The wheel carries metadata, so `pip install dist/*.whl` also installs the declared dependencies.
- Upload to a private index (Artifactory, CodeArtifact, devpi) so teammates and servers can install by version.
@diagram flow
caption: From source to an installed tool
numbered: true
nodes:
  - "Source|src and pyproject.toml|app"
  - "Build|python -m build|info"
  - "Wheel|versioned archive in dist|env"
  - "Index|private package index|ext"
  - "Install|pip or pipx on a host|ok"
@h Commands
```bash title="Build and test the wheel locally"
python -m pip install build
python -m build                          # creates dist/
python -m venv /tmp/wheel-test
/tmp/wheel-test/bin/python -m pip install dist/*.whl
/tmp/wheel-test/bin/opskit --help        # the entry point exists
python -m twine upload --repository-url "$INDEX_URL" dist/*   # publish to your index
```
:::tip
Always install the built wheel into a clean environment and run it once. That test catches files missing from the package.
:::
@check
What does the wheel give you that a copied folder does not? || A version number, declared dependencies and entry points, installable with one command.
@end

@concept Entry points and console scripts
@plain
An **entry point** maps a command name to a Python function. After installation, typing `opskit` runs that function, with no `python path/to/file.py` needed.
@problem
Operators should not need to know where a script lives or which interpreter it needs. A shebang pointing at a laptop path fails on every other machine.
@does
- `[project.scripts] opskit = "opskit.cli:main"` creates an executable in the environment's `bin` directory.
- The function should return an integer exit code; the generated wrapper passes it to `sys.exit`.
- `python -m opskit` works too if you add a `__main__.py`.
@diagram flow
caption: How a command name reaches your code
nodes:
  - "opskit|typed in the shell|plain"
  - "bin/opskit|generated wrapper|env"
  - "opskit.cli:main|your function|app"
  - "Exit code|returned to the shell|ok"
@h Wiring it
```python title="src/opskit/cli.py"
from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in {"-h", "--help"}:
        print("usage: opskit <command>")
        return 0
    print(f"unknown command: {args[0]}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```
```python title="src/opskit/__main__.py"
from opskit.cli import main

raise SystemExit(main())
```
@check
What should main return? || An integer exit code, 0 for success, so shells and CI can detect failure.
@end

@concept Installing as a command
@plain
Publish the package to a private index, or install straight from Git, and users get a real command on their `PATH` through the entry point you declared.
@problem
"Clone the repo, make a venv, run python scripts/x.py" is a barrier, and every copy drifts from the others.
@does
- `pipx install opskit` (or `uv tool install opskit`) gives one isolated environment per tool and the `opskit` command.
- `pipx install git+https://git.example.com/ops/opskit@v1.2.0` pins a Git tag.
- `opskit --version` should print the installed version from package metadata (`importlib.metadata.version`).
- Tag releases; upgrade deliberately with `pipx upgrade opskit`.
@diagram flow
caption: From repository to every laptop
nodes:
  - "Git tag v1.2.0|release point|plain"
  - "CI builds wheel|tests pass first|app"
  - "Private index|Artifactory or CodeArtifact|ext"
  - "pipx install|one command per user|ok"
@h Version from metadata
```python title="version.py" lab
from importlib.metadata import PackageNotFoundError, version


def tool_version(name: str = "opskit") -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "0+unknown"      # running from a source checkout


print(tool_version("pip"), tool_version("not-installed-xyz"))
```
@check
Where should --version read the number from? || Package metadata, so it always matches the installed release.
@end

@concept Type hints, the basics
@plain
A **type hint** states what kind of value a variable, argument or return is, for example `str`, `int` or `list[str]`. Python ignores hints at run time; tools read them.
@problem
In a long ops script a function that sometimes returns `None` and sometimes a string causes a crash at 3 a.m. when the rare path is hit. Hints make that visible when you edit.
@does
- `def f(x: int, name: str | None = None) -> list[str]:` documents inputs and outputs.
- Builtin generics (`list[str]`, `dict[str, int]`) work from Python 3.9, and `X | None` from 3.10.
- Editors use hints for completion and warnings; mypy checks them across the project.
@diagram cmp
caption: The same function without and with hints
cards:
  - {h: "No hints", kind: warn, items: ["Reader must guess types", "None surprises appear at run time", "Refactors are risky"]}
  - {h: "With hints", kind: ok, items: ["Contract visible in the signature", "Editor and mypy flag misuse", "Refactors are checked"]}
@h Example
```python title="Hints in a real helper" lab
from __future__ import annotations


def parse_size(text: str) -> int:
    """Turn '10G', '512M' or '100' into bytes."""
    units = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
    text = text.strip().upper()
    if text and text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(text)


def first_match(names: list[str], prefix: str) -> str | None:
    for n in names:
        if n.startswith(prefix):
            return n
    return None


print(parse_size("10G"), parse_size("512M"), first_match(["db-1", "web-1"], "web"))
```
@check
Does Python enforce hints at run time? || No; they are checked by tools such as mypy and used by editors.
@end

@concept Checking with mypy
@plain
`mypy` reads your hints and reports places where the code contradicts them, without running the code.
@problem
Tests only cover paths you thought of. Types catch whole classes of bugs, such as passing `None` into a function that needs a string, for every path.
@does
- `mypy src` reports errors with file and line.
- `strict = true` in `[tool.mypy]` turns on the stricter checks; start with it on new code.
- Libraries without hints need stubs such as `types-requests` and `types-PyYAML`, or an ignore for that module only.
- Run it in CI beside tests and ruff so regressions fail the build.
@diagram flow
caption: Where mypy sits in the pipeline
nodes:
  - "Edit|write code with hints|app"
  - "ruff|style and simple bugs|info"
  - "mypy|type contradictions|env"
  - "pytest|behaviour|env"
  - "Merge|all green|ok"
@h Configuration and a caught bug
```toml title="pyproject.toml tool settings"
[tool.mypy]
python_version = "3.11"
strict = true
files = ["src"]

[[tool.mypy.overrides]]
module = ["boto3.*", "botocore.*"]
ignore_missing_imports = true
```
```python title="mypy would reject this"
def find_owner(tags: dict[str, str]) -> str:
    return tags.get("owner")   # error: returns "str | None", declared "str"


def find_owner_fixed(tags: dict[str, str]) -> str:
    return tags.get("owner", "unknown")
```
@check
What is the bug in find_owner? || dict.get can return None, but the declared return type is str.
@end

@concept Dataclasses and TypedDict for structured data
@plain
A **dataclass** is a small class that just holds named fields. A **TypedDict** describes the shape of a plain dictionary, such as a JSON object from an API.
@problem
Passing raw dictionaries around means typos in keys (`"intance_id"`) only fail when that line runs, and nobody knows what keys exist.
@does
- `@dataclass(frozen=True)` gives an immutable record with `__init__`, `__repr__` and equality for free.
- `asdict()` converts it back to a dictionary for JSON output.
- `TypedDict` documents API payloads without changing them; mypy checks the keys.
@diagram cmp
caption: Choosing a shape for data
cards:
  - {h: "dict", kind: warn, items: ["Any key at any time", "Typos found late", "Good for quick scripts"]}
  - {h: "TypedDict", kind: info, items: ["Describes JSON from outside", "No run time checking", "Keys checked by mypy"]}
  - {h: "dataclass", kind: ok, items: ["Your own records", "Methods and defaults", "Easy to test and print"]}
@h Example
```python title="A volume record" lab
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import TypedDict


class ApiVolume(TypedDict):
    VolumeId: str
    Size: int
    State: str


@dataclass(frozen=True)
class Volume:
    id: str
    size_gb: int
    state: str
    tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_api(cls, raw: ApiVolume) -> "Volume":
        return cls(id=raw["VolumeId"], size_gb=raw["Size"], state=raw["State"])

    @property
    def idle(self) -> bool:
        return self.state == "available"


v = Volume.from_api({"VolumeId": "vol-1", "Size": 100, "State": "available"})
print(v.idle, json.dumps(asdict(v)))
```
@check
Why make a dataclass frozen? || Immutable records cannot be changed by accident and can be used as dictionary keys or set members.
@end

@concept Protocol and dependency injection
@plain
A **Protocol** describes the methods an object must have, without requiring inheritance. Your function says "give me anything with `list_volumes()`", and tests pass a fake.
@problem
Code that creates its own boto3 client inside every function cannot be tested without AWS or heavy mocking.
@does
- Define a small `Protocol` for the capability you need.
- Pass the real client in production and a stub in tests.
- mypy checks that the stub has the right methods.
@diagram flow
caption: One function, two implementations
nodes:
  - "find_idle(source)|needs list_volumes|app"
  - "Protocol|the contract|info"
  - "AwsSource|real boto3|ext"
  - "FakeSource|list in a test|ok"
@h Example
```python title="Testable by design" lab
from __future__ import annotations

from typing import Protocol


class VolumeSource(Protocol):
    def list_volumes(self) -> list[dict[str, object]]: ...


def idle_ids(source: VolumeSource) -> list[str]:
    return [str(v["id"]) for v in source.list_volumes() if v["state"] == "available"]


class FakeSource:
    def list_volumes(self) -> list[dict[str, object]]:
        return [{"id": "vol-1", "state": "available"}, {"id": "vol-2", "state": "in-use"}]


assert idle_ids(FakeSource()) == ["vol-1"]
print("ok")
```
@check
What does a Protocol save you in tests? || You can pass any simple fake with the right methods instead of patching boto3.
@end
