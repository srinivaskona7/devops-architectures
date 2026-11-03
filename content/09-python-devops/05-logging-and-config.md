---
title: Logging and configuration
minutes: 45
objectives:
  - Replace print with the logging module and choose levels well
  - Emit structured JSON logs that log systems can search
  - Read settings from environment variables and validate them with pydantic-settings
  - Keep secrets out of code and out of logs
---
A tool that runs unattended must explain what it did and must be configurable without editing code. Logging and configuration are the two habits that make a script operable.

@concept Why logging instead of print
@plain
The `logging` module writes messages with a timestamp, a level and a source name, and lets you decide later where they go and how much detail to keep.
@problem
`print` has no levels, no timestamps, no way to turn noise off, and mixes diagnostics into stdout where data should be. When a cron job fails at night, you need to know when and where.
@does
- Levels in order of severity are DEBUG, INFO, WARNING, ERROR and CRITICAL.
- Each module gets its own logger with `logging.getLogger(__name__)`.
- Handlers decide the destination (console, file, syslog) and formatters decide the layout.
- `logger.exception("msg")` inside `except` records the traceback.
@diagram flow
caption: A log record on its way out
nodes:
  - "logger.info|your code|app"
  - "Level filter|drops below threshold|info"
  - "Handler|stream or file|env"
  - "Formatter|time, level, message|env"
  - "stderr or file|destination|ok"
@h Basic setup
```python title="logging_basic.py" lab
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("opskit.scan")

log.debug("not shown at INFO")
log.info("scanning %d volumes in %s", 12, "eu-west-1")
try:
    1 / 0
except ZeroDivisionError:
    log.exception("division failed")
```
:::tip
Pass values as arguments (`log.info("x=%s", x)`) instead of building an f-string. The text is only built if the level is enabled.
:::
@check
Why use getLogger(__name__)? || Each module gets a named logger, so you can see and tune where a message came from.
@end

@concept Choosing log levels
@plain
Levels express how much attention a message deserves. A consistent choice lets operators read INFO to follow progress and ERROR to find problems.
@problem
If everything is INFO the real failure is lost; if everything is ERROR nobody trusts alerts.
@does
- DEBUG: details for developers, such as request bodies and loop counters.
- INFO: normal milestones, such as "found 3 idle volumes".
- WARNING: something unexpected that was handled, such as a retry.
- ERROR: an operation failed. CRITICAL: the program cannot continue.
- Make the level configurable by `--verbose` or `LOG_LEVEL`.
@diagram cmp
caption: What belongs on each level
cards:
  - {h: "DEBUG and INFO", kind: ok, items: ["Debug is off in production", "INFO tells the story of a run", "Include counts and ids"]}
  - {h: "WARNING", kind: warn, items: ["Handled but unusual", "Retries, fallbacks, skipped items", "Review weekly"]}
  - {h: "ERROR and CRITICAL", kind: bad, items: ["Operation failed", "Someone should look", "Alert on these"]}
@h Level from environment
```python title="Level from LOG_LEVEL" lab
import logging
import os

level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
level = getattr(logging, level_name, logging.INFO)
logging.basicConfig(level=level, format="%(levelname)s %(message)s")
logging.getLogger("demo").info("running at %s", logging.getLevelName(level))
logging.getLogger("urllib3").setLevel(logging.WARNING)   # quiet chatty libraries
```
@check
Where does a retry that later succeeds belong? || WARNING, because something unexpected happened but was handled.
@end

@concept Structured JSON logging
@plain
Structured logs write each event as a JSON object with named fields, such as `{"event": "volume_found", "volume_id": "vol-1"}`. Log platforms can then filter and count by field.
@problem
Free text lines need fragile regular expressions to search. Finding all events for one account or request in ELK, Loki or CloudWatch is slow and error prone.
@does
- A custom `logging.Formatter` that returns `json.dumps(...)` works with no extra dependency.
- Pass extra fields with `extra={"volume_id": ...}`.
- Libraries such as `structlog` add context binding; `python-json-logger` adds a ready made formatter.
- Write logs to stdout or stderr in containers and let the platform collect them.
@diagram flow
caption: From event to searchable record
nodes:
  - "log.info with extra|fields attached|app"
  - "JSON formatter|one object per line|info"
  - "Container stdout|collected by the node|env"
  - "Loki, ELK or CloudWatch|query by field|ok"
@h A small JSON formatter
```python title="json_logging.py" lab
import json
import logging
import sys
from datetime import datetime, timezone

STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None)))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        doc = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        doc.update({k: v for k, v in record.__dict__.items() if k not in STANDARD and k != "message"})
        if record.exc_info:
            doc["exception"] = self.formatException(record.exc_info)
        return json.dumps(doc, default=str)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JsonFormatter())
log = logging.getLogger("opskit")
log.addHandler(handler)
log.setLevel(logging.INFO)

log.info("volume found", extra={"volume_id": "vol-1", "size_gb": 100})
```
@check
Why log to stdout in a container? || The container runtime collects it, so no log files or rotation are needed inside the container.
@end

@concept Handlers, rotation and context
@plain
Handlers send records to places. A rotating file handler keeps log files from filling a disk. Context such as a run id can be attached to every record with a `LoggerAdapter` or a `contextvars` value.
@problem
A long running daemon that logs to one file eventually fills the disk. Lines from concurrent runs get interleaved and cannot be told apart.
@does
- `RotatingFileHandler(maxBytes, backupCount)` rolls files by size; `TimedRotatingFileHandler` by time.
- `logging.config.dictConfig` defines handlers declaratively, even from YAML.
- `LoggerAdapter` adds a fixed field to every message from one logger.
- Do not log secrets; redact tokens before writing.
@diagram layers
caption: Logging architecture
layers:
  - {label: "Your code", nodes: ["logger per module|named after the module|app"]}
  - {label: "Routing", nodes: ["root logger|level and handlers|cp", "propagation|child to parent|info"]}
  - {label: "Outputs", nodes: ["console handler|stderr|ok", "rotating file|size limited|ok", "syslog or HTTP|central collector|ext"]}
@h Example
```python title="Rotation and a run id" lab
import logging
import tempfile
import uuid
from logging.handlers import RotatingFileHandler
from pathlib import Path

d = Path(tempfile.mkdtemp())
handler = RotatingFileHandler(d / "tool.log", maxBytes=200, backupCount=2)
handler.setFormatter(logging.Formatter("%(asctime)s %(run_id)s %(message)s"))
base = logging.getLogger("rotdemo")
base.setLevel(logging.INFO)
base.addHandler(handler)

log = logging.LoggerAdapter(base, {"run_id": uuid.uuid4().hex[:8]})
for i in range(10):
    log.info("processing item %d", i)
print(sorted(p.name for p in d.iterdir()))
```
@check
What does backupCount control? || How many rotated files are kept before the oldest is deleted.
@end

@concept Configuration from environment variables
@plain
Configuration is anything that changes between environments: region, endpoints, thresholds, secrets. The twelve-factor approach reads it from **environment variables** so the same code runs in dev and in production.
@problem
Hard coded values force code edits and releases for every change, and committed secrets end up in Git history.
@does
- `os.environ["NAME"]` fails loudly when missing; `os.environ.get("NAME", default)` supplies a default.
- Values are always strings; convert booleans and numbers explicitly.
- Kubernetes injects variables from ConfigMaps and Secrets; systemd uses `EnvironmentFile=`.
- Command line options override environment, which overrides defaults.
@diagram flow
caption: Order of precedence
nodes:
  - "Defaults|in code|plain"
  - "Config file|optional|info"
  - "Environment|per deployment|env"
  - "CLI flags|per run|ok"
@h Example
```python title="env config by hand" lab
import os


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


os.environ["OPSKIT_DRY_RUN"] = "true"       # normally set by the platform
region = os.environ.get("AWS_REGION", "eu-west-1")
dry_run = env_bool("OPSKIT_DRY_RUN", True)
days = int(os.environ.get("OPSKIT_DAYS", "14"))
print(region, dry_run, days)
```
@check
Why convert booleans explicitly? || Every environment variable is a string, and the string "false" is truthy in Python.
@end

@concept Validated settings with pydantic-settings
@plain
`pydantic-settings` reads environment variables (and `.env` files) into a typed class and validates them at start up, so a bad value stops the program with a clear message.
@problem
Hand written parsing scatters conversions across the code, and a typo like `OPSKIT_DAYS=ten` only fails halfway through a run.
@does
- Subclass `BaseSettings`; fields get types, defaults and constraints.
- `env_prefix="OPSKIT_"` maps `OPSKIT_DAYS` to `days`.
- `SecretStr` hides values in logs and repr output.
- Failure raises `ValidationError` listing every wrong field at once.
@diagram flow
caption: Settings are validated before work starts
nodes:
  - "Environment and .env|raw strings|plain"
  - "BaseSettings|parse and validate|info"
  - "Settings object|typed fields|app"
  - "Fail fast|clear error list|bad"
@h Example
```python title="settings.py" nocheck
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OPSKIT_", env_file=".env", extra="ignore")

    region: str = "eu-west-1"
    days: int = Field(14, ge=1, le=365)
    dry_run: bool = True
    slack_webhook: SecretStr | None = None


settings = Settings()          # OPSKIT_DAYS=30 OPSKIT_DRY_RUN=false python tool.py
print(settings.days, settings.dry_run)
if settings.slack_webhook:
    url = settings.slack_webhook.get_secret_value()
```
:::warn
Add `.env` to `.gitignore`. In production use real environment variables from the platform's secret store, not files in the image.
:::
@check
What does SecretStr protect against? || Accidentally printing or logging the secret, because its repr is masked.
@end

@concept Secrets and redaction
@plain
Secrets are tokens, passwords and keys. They must come from a secret store at run time and must never appear in code, command lines, or logs.
@problem
Tokens pasted into scripts leak through Git, through `ps` output on shared hosts, and through debug logs of HTTP requests.
@does
- Prefer workload identity (IAM roles, Kubernetes service accounts) over long lived keys.
- Otherwise read from environment variables, mounted files, AWS Secrets Manager or Vault.
- Never pass secrets as command line arguments; other users can see them.
- Add a logging filter that masks known patterns before records are written.
@diagram cmp
caption: Where a secret may live
cards:
  - {h: "Never", kind: bad, items: ["Source code and Git history", "Command line arguments", "Log messages"]}
  - {h: "Acceptable", kind: warn, items: ["Environment variable from a secret store", "Mounted file with strict permissions"]}
  - {h: "Best", kind: ok, items: ["Workload identity with short lived tokens", "Secret fetched at run time"]}
@h A redaction filter
```python title="redact.py" lab
import logging
import re

PATTERN = re.compile(r"(?i)(token|password|secret)(=|: ?)([^\s,]+)")


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = PATTERN.sub(lambda m: f"{m.group(1)}{m.group(2)}***", str(record.msg))
        return True


handler = logging.StreamHandler()
handler.addFilter(RedactFilter())
log = logging.getLogger("redact")
log.addHandler(handler)
log.setLevel(logging.INFO)
log.info("calling api token=abc123 user=bob")
```
@check
Why is a command line argument a poor place for a secret? || Other users on the host can read it from the process list, and shell history may store it.
@end
