---
title: Environments, pip, uv and lockfiles
minutes: 45
objectives:
  - Explain why every project needs its own isolated environment
  - Create and use environments with venv, pip and uv
  - Describe a project in pyproject.toml and pin it with a lockfile
  - Install command line tools with pipx without polluting projects
---
Python is the glue language of operations. Before any script is worth writing, you need a repeatable way to say which Python and which libraries it runs on. This section covers that foundation.

@concept Why isolated environments
@plain
An environment is a private folder holding one Python interpreter link and the libraries for exactly one project. Two projects can then use different versions of the same library without fighting.
@problem
If every script installs into the system Python, one upgrade of `requests` for tool A breaks tool B. Operating system tools such as `dnf` and `apt` also depend on the system Python, so a careless `pip install` can damage the machine.
@does
- Keeps each project's dependencies separate from the system and from other projects.
- Makes a script reproducible, because the same environment can be rebuilt on a laptop, in CI and in a container.
- Lets you delete and recreate an environment at any time, because it holds no data of its own.
@diagram cmp
caption: One global Python versus one environment per project
cards:
  - {h: "Global install", kind: bad, items: ["All projects share versions", "Can break OS tools", "Hard to reproduce elsewhere"]}
  - {h: "Environment per project", kind: ok, items: ["Own versions for each tool", "Safe to delete and rebuild", "Same recipe in CI and containers"]}
@h See which Python you are using
```python title="whoami.py" lab
import sys

print("interpreter:", sys.executable)
print("prefix     :", sys.prefix)
print("base prefix:", sys.base_prefix)
print("in a venv  :", sys.prefix != sys.base_prefix)
```
:::tip
Run `python -c "import sys; print(sys.prefix)"` before installing anything. If it prints a system path you are about to change the global Python.
:::
@check
Why is deleting an environment safe? || It contains only installed packages, which can be recreated from pyproject.toml or a lockfile.
@end

@concept venv, the built in tool
@plain
`python -m venv` creates an environment folder, usually `.venv`, using the standard library only. Activating it puts its `bin` directory first on your `PATH`.
@problem
You need isolation on a server or in a container where you cannot install extra tools first.
@does
- Creates `.venv/bin/python` and a private `site-packages` folder.
- `source .venv/bin/activate` is optional. Calling `.venv/bin/python` directly works the same and is clearer in scripts and cron.
- Never commit `.venv`; add it to `.gitignore`.
@diagram flow
caption: Creating and using a venv
numbered: true
nodes:
  - "python -m venv .venv|creates the folder|app"
  - "activate or call .venv/bin/python|picks the private interpreter|info"
  - "pip install|goes into .venv only|env"
  - "Run the tool|sees only its own libraries|ok"
@h Commands
```bash title="venv from scratch" lab
python3 -m venv /tmp/demo-venv            # create
/tmp/demo-venv/bin/python -m pip --version   # call it without activating
/tmp/demo-venv/bin/python -m pip install --quiet rich
/tmp/demo-venv/bin/python -c "import rich; print(rich.__file__)"
rm -rf /tmp/demo-venv                     # safe to throw away
```
@check
Why prefer .venv/bin/python over activating in cron or systemd? || There is no shell session to activate in, and the explicit path cannot pick up the wrong interpreter.
@end

@concept pip essentials
@plain
`pip` downloads packages from an index such as PyPI and installs them into the current environment. Always run it as `python -m pip` so it is tied to the interpreter you mean.
@problem
Running a bare `pip` may belong to a different Python than the `python` you use, and you install into the wrong place.
@does
- `pip install name`, `pip install "name>=2,<3"`, `pip install -r requirements.txt`.
- `pip list`, `pip show name`, `pip freeze` show what is installed.
- `pip check` reports broken dependency combinations.
- `pip install -e .` installs your own project in editable mode while developing.
@diagram flow
caption: What pip does on an install
nodes:
  - "Resolve|find versions that fit all rules|info"
  - "Download|wheel or source archive|env"
  - "Build if needed|only for source archives|warn"
  - "Install|copy into site-packages|ok"
@h Everyday use
```bash title="pip commands" lab
python3 -m venv /tmp/pipdemo
/tmp/pipdemo/bin/python -m pip install --quiet "requests>=2.31,<3"
/tmp/pipdemo/bin/python -m pip list --format=freeze | head -5
/tmp/pipdemo/bin/python -m pip show requests | head -3
/tmp/pipdemo/bin/python -m pip check
rm -rf /tmp/pipdemo
```
:::warn
Avoid `sudo pip install`. If pip says the environment is externally managed, create a venv or use pipx instead of forcing it with `--break-system-packages`.
:::
@check
What does pip check do? || It verifies that installed packages have compatible dependencies and reports conflicts.
@end

@concept pyproject.toml, the project description
@plain
`pyproject.toml` is one file that names your project, its Python version, its dependencies and the tools that build and check it. Every modern tool reads it.
@problem
Older projects scattered this across `setup.py`, `setup.cfg`, `requirements.txt` and tool specific files, and executing `setup.py` to learn dependencies was unsafe and slow.
@does
- `[project]` holds name, version, `requires-python` and `dependencies`.
- `[project.optional-dependencies]` or `[dependency-groups]` hold extras such as test tools.
- `[project.scripts]` creates command line entry points.
- `[build-system]` says which backend builds the package; `[tool.*]` tables configure ruff, mypy and pytest.
@diagram layers
caption: Sections of a pyproject.toml
layers:
  - {label: "Identity", nodes: ["name and version|who it is|app", "requires-python|which interpreters|info"]}
  - {label: "Dependencies", nodes: ["dependencies|needed at run time|env", "dependency groups|dev and test only|env"]}
  - {label: "Tooling", nodes: ["build-system|how to build|cp", "tool.ruff and tool.mypy|settings|cp", "project.scripts|CLI commands|ok"]}
@h A realistic file
```toml title="pyproject.toml"
[project]
name = "opskit"
version = "0.1.0"
description = "Small operations tools"
requires-python = ">=3.11"
dependencies = [
  "boto3>=1.34",
  "requests>=2.31",
  "pyyaml>=6",
]

[project.scripts]
opskit = "opskit.cli:main"

[dependency-groups]
dev = ["pytest>=8", "mypy>=1.10", "ruff>=0.5", "moto[s3,ec2]>=5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.ruff]
line-length = 100

[tool.pytest.ini_options]
testpaths = ["tests"]
```
```python title="Read it with the standard library" lab
import tomllib

doc = tomllib.loads("""
[project]
name = "opskit"
dependencies = ["requests>=2.31"]
""")
print(doc["project"]["name"], doc["project"]["dependencies"])
```
@check
Which table creates the opskit command? || [project.scripts], mapping a command name to module:function.
@end

@concept uv, a fast project manager
@plain
`uv` is a single program that creates environments, installs packages, manages Python versions and writes lockfiles. It does the work of pip, venv, pip-tools and pyenv, and is much faster.
@problem
Resolving and installing with pip can take minutes in CI, and juggling several tools for versions, environments and locking is easy to get wrong.
@does
- `uv venv` and `uv pip install` are drop in replacements for venv and pip.
- `uv init`, `uv add`, `uv remove` edit pyproject.toml and the lock for you.
- `uv run cmd` runs a command inside the project environment, creating it first when needed.
- `uv python install 3.12` downloads a managed interpreter.
@diagram flow
caption: The uv project workflow
numbered: true
nodes:
  - "uv init|creates pyproject.toml|app"
  - "uv add boto3|edits file and uv.lock|info"
  - "uv sync|builds .venv from the lock|env"
  - "uv run pytest|runs inside the project|ok"
@h Commands
```bash title="uv project in five commands"
uv init opskit && cd opskit
uv add boto3 requests            # runtime dependencies
uv add --dev pytest mypy ruff    # development group
uv sync                          # create .venv exactly as locked
uv run pytest -q                 # run without activating
uv python install 3.12           # fetch an interpreter if missing
uv pip install -r requirements.txt   # pip compatible mode
```
@choose Picking a tool
uv | new projects and CI where speed and one tool matter | the host policy allows only the standard library
pip with venv | minimal servers and base images | you also want locking and Python version management
Poetry or PDM | the team already uses them | you are starting fresh and want fewer moving parts
@check
Which uv command runs a program in the project environment without activating it? || uv run.
@end

@concept Lockfiles and reproducible installs
@plain
`pyproject.toml` says what versions are acceptable. A **lockfile** records the exact versions, and ideally hashes, that were chosen, so every machine installs the same thing.
@problem
Without a lock, "requests>=2" installs a different version next month. A tool that worked on Friday fails on Monday because a transitive dependency changed, or worse, a malicious release is pulled in silently.
@does
- `uv lock` writes `uv.lock`; `uv sync --locked` fails if the lock is out of date, which suits CI.
- `pip-compile --generate-hashes` (from pip-tools) writes a `requirements.txt` with hashes; `pip install --require-hashes -r` verifies each file.
- Commit the lock for applications and tools. Libraries usually commit only ranges.
@diagram seq
caption: Locking once, installing many times
actors: ["Developer|laptop|app", "Index|PyPI or mirror|ext", "CI|build job|env"]
steps:
  - "0>1: resolve ranges | req"
  - "1>0: exact versions and hashes | resp"
  - "note 0..0: commit uv.lock"
  - "2>1: download exact files | req"
  - "1>2: files must match hashes | tls"
@h Installing from a lock
```bash title="Strict installs in CI"
uv lock --check                      # fail if the lock does not match pyproject.toml
uv sync --locked --no-dev            # exact production set

# plain pip route
pip-compile --generate-hashes -o requirements.txt pyproject.toml
python -m pip install --require-hashes -r requirements.txt
```
:::note
Upgrade deliberately with `uv lock --upgrade-package boto3` or a scheduled Dependabot or Renovate pull request, not by accident at build time.
:::
@check
Why do hashes add security? || An installer rejects any file whose hash differs from the recorded one, so a swapped or tampered package fails.
@end

@concept pipx and uv tool, installing command line tools
@plain
`pipx` installs a Python command line application into its own private environment and puts the command on your `PATH`. `uv tool install` does the same.
@problem
Tools such as `ruff`, `awscli`, `pre-commit` or `httpie` are not libraries of your project. Installing them into a project pollutes its dependencies; installing globally risks conflicts.
@does
- `pipx install name` makes one isolated venv per tool.
- `pipx run name` runs a tool once without keeping it.
- `pipx inject tool extra` adds a plugin library into that tool's environment.
- `pipx upgrade-all` refreshes everything; `pipx ensurepath` fixes `PATH`.
@diagram layers
caption: Tools isolated from each other and from projects
layers:
  - {label: "Your PATH", nodes: ["ruff|command|ok", "pre-commit|command|ok", "opskit|command|ok"]}
  - {label: "Private environments", nodes: ["ruff venv|own libraries|env", "pre-commit venv|own libraries|env", "opskit venv|own libraries|env"]}
@h Commands
```bash title="Installing tools"
python3 -m pip install --user pipx
pipx ensurepath
pipx install ruff
pipx install "git+https://github.com/example/opskit.git"   # your own tool from git
pipx run cowsay hello                                      # one-off, nothing kept
uv tool install ruff                                       # the uv equivalent
pipx list
```
@check
When would you choose pipx run? || To try a tool once or run it in a script without leaving it installed.
@end
