---
title: Testing with pytest, mocks and moto
minutes: 55
objectives:
  - Write fast pytest tests with fixtures and parametrisation
  - Replace slow or dangerous dependencies with fakes and mocks
  - Test boto3 code with moto without touching AWS
  - Find edge cases with property based tests
---
Operations code deletes and changes real things, so it deserves tests more than most. The goal is fast tests that never touch a real account, cluster or network.

@concept pytest basics
@plain
`pytest` finds files named `test_*.py` and runs functions named `test_*`. A plain `assert` is all you need; on failure pytest shows the values on both sides.
@problem
Without tests, every change to a cleanup script is a gamble. Heavy test frameworks with a lot of ceremony discourage people from writing tests at all.
@does
- `pytest -q` runs everything; `-k name` selects by name; `-x` stops at the first failure; `-vv` shows details.
- `pytest.raises(ValueError, match="invalid")` asserts an exception.
- `pytest.approx` compares floats.
- Tests live in `tests/` and import your installed package.
@diagram flow
caption: What pytest does
nodes:
  - "Collect|test_*.py files|info"
  - "Run each test|isolated|app"
  - "assert rewriting|shows both sides|env"
  - "Report|pass, fail, time|ok"
@h A first test file
```python title="test_basics.py"
import pytest


def parse_size(text: str) -> int:
    units = {"K": 1024, "M": 1024**2, "G": 1024**3}
    text = text.strip().upper()
    if not text:
        raise ValueError("invalid size")
    if text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(text)


def test_plain_number():
    assert parse_size("100") == 100


def test_gigabytes():
    assert parse_size("2G") == 2 * 1024**3


def test_empty_is_rejected():
    with pytest.raises(ValueError, match="invalid"):
        parse_size("")
```
```bash title="Running the tests" nocheck
uv run pytest -q
uv run pytest -k gigabytes -vv
```
@check
Which construct asserts that an exception is raised? || pytest.raises used as a context manager.
@end

@concept Parametrised tests
@plain
`@pytest.mark.parametrize` runs one test body with many inputs and expected outputs. Each case is reported separately.
@problem
Copying the same test ten times with different numbers is noisy. A loop inside one test stops at the first failure and hides which case broke.
@does
- `@pytest.mark.parametrize("text,expected", [("1K", 1024), ("1M", 1048576)])`.
- `ids=[...]` gives readable names; `pytest.param(..., marks=pytest.mark.xfail)` marks a known failure.
- Stack several decorators to get all combinations.
- Ideal for tables of edge cases: empty, huge, unicode, negative.
@diagram flow
caption: One body, many cases
nodes:
  - "Test function|one body|app"
  - "Table of inputs|text and expected|info"
  - "One result per row|independent|ok"
@h Example
```python title="test_param.py"
import pytest


def parse_size(text: str) -> int:
    units = {"K": 1024, "M": 1024**2, "G": 1024**3}
    text = text.strip().upper()
    if text and text[-1] in units:
        return int(float(text[:-1]) * units[text[-1]])
    return int(text)


@pytest.mark.parametrize(
    "text,expected",
    [("100", 100), ("1K", 1024), ("1.5M", 1572864), (" 2g ", 2 * 1024**3)],
    ids=["plain", "kilo", "fractional", "spaces and case"],
)
def test_parse_size(text, expected):
    assert parse_size(text) == expected


@pytest.mark.parametrize("bad", ["", "abc", "1X"])
def test_bad_input(bad):
    with pytest.raises(ValueError):
        parse_size(bad)
```
@check
Why use parametrize instead of a loop? || Each case is reported separately, so one failure does not hide the others.
@end

@concept Fixtures
@plain
A **fixture** is a function that prepares something a test needs (a temp folder, a fake client, a sample file) and hands it in when the test names it as a parameter. Cleanup can follow a `yield`.
@problem
Setup code copied into every test drifts and slows tests. Shared global state makes tests depend on each other.
@does
- `@pytest.fixture` marks a setup function; tests request it by parameter name.
- Built in: `tmp_path` (unique temp folder), `monkeypatch` (temporary changes), `capsys` and `caplog` (captured output and logs).
- `scope="session"` or `"module"` reuses expensive setup; the default is per test.
- Shared fixtures go in `conftest.py`.
@diagram seq
caption: Fixture lifecycle
actors: ["pytest|runner|app", "Fixture|setup and cleanup|env", "Test|uses the value|ok"]
steps:
  - "0>1: run setup | req"
  - "1>2: value passed in | resp"
  - "2>2: assertions | req"
  - "0>1: run code after yield | req"
@h Example
```python title="test_fixtures.py"
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"version": 1}))
    return p


def bump(path: Path) -> int:
    data = json.loads(path.read_text())
    data["version"] += 1
    path.write_text(json.dumps(data))
    return data["version"]


def test_bump(state_file):
    assert bump(state_file) == 2
    assert json.loads(state_file.read_text())["version"] == 2


def test_env(monkeypatch):
    monkeypatch.setenv("OPSKIT_DAYS", "30")
    assert os.environ["OPSKIT_DAYS"] == "30"


@pytest.fixture
def fake_clock():
    value = {"now": 1000.0}
    yield value                      # test runs here
    value.clear()                    # cleanup after the test
```
@check
Where does cleanup code go in a fixture? || After the yield statement.
@end

@concept Fakes, stubs and unittest.mock
@plain
A **fake** is a simple working replacement (an in-memory list instead of a database). A **mock** records how it was called so a test can check the calls. Python's `unittest.mock` provides `Mock`, `MagicMock` and `patch`.
@problem
Tests must not call real clouds: they are slow, cost money, need credentials and can delete real things.
@does
- `Mock(return_value=...)` and `side_effect=[...]` or an exception script the replacement's behaviour.
- `mock.assert_called_once_with(...)` checks calls; `mock.call_args_list` lists them.
- `patch("module.name")` replaces a name where it is **used**, not where it is defined.
- Prefer fakes and dependency injection when logic is complex; mock only the edge.
@diagram cmp
caption: Which replacement to use
cards:
  - {h: "Fake", kind: ok, items: ["Small working version", "Tests state and results", "Survives refactors"]}
  - {h: "Mock", kind: info, items: ["Records calls", "Checks interactions", "Breaks if code is restructured"]}
  - {h: "Real service", kind: bad, items: ["Slow and costly", "Needs credentials", "Can change real data"]}
@h Example
```python title="test_mock.py" lab
from unittest.mock import Mock


def stop_idle(ec2, instance_ids, apply):
    if not instance_ids:
        return 0
    ec2.stop_instances(InstanceIds=instance_ids, DryRun=not apply)
    return len(instance_ids)


ec2 = Mock()
assert stop_idle(ec2, ["i-1", "i-2"], apply=False) == 2
ec2.stop_instances.assert_called_once_with(InstanceIds=["i-1", "i-2"], DryRun=True)

failing = Mock(side_effect=[ConnectionError("blip"), "ok"])
try:
    failing()
except ConnectionError:
    pass
print(failing(), failing.call_count)
```
:::warn
Patch the name in the module that imports it. If `tool.py` does `from boto3 import client`, patch `tool.client`, not `boto3.client`.
:::
@check
What is the difference between a fake and a mock? || A fake works like the real thing in a simple way; a mock records calls so you can assert on them.
@end

@concept moto, a fake AWS
@plain
`moto` implements many AWS services in memory. With its `mock_aws` decorator, boto3 calls inside the test go to moto instead of the internet, and behave much like the real service.
@problem
Mocks of boto3 return whatever you script, so tests pass even when the real call would have failed on a wrong parameter. You want realistic behaviour without an account.
@does
- `from moto import mock_aws` (moto 5 and later) wraps a test or works as a context manager.
- Set fake credentials in the environment so nothing real is ever used.
- Create the state you need with real boto3 calls (buckets, volumes), run your code, assert on the result.
- Coverage differs by service; check moto's docs for the calls you use.
@diagram flow
caption: moto intercepts boto3
nodes:
  - "Test|arranges state with boto3|app"
  - "Your code|normal boto3 calls|app"
  - "moto mock_aws|in memory AWS|env"
  - "Assertions|on returned data|ok"
@h Example
```python title="test_idle_volumes.py" nocheck
import boto3
import pytest
from moto import mock_aws


@pytest.fixture(autouse=True)
def aws_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")


def idle_volume_ids(ec2) -> list[str]:
    out = []
    for page in ec2.get_paginator("describe_volumes").paginate(
            Filters=[{"Name": "status", "Values": ["available"]}]):
        out += [v["VolumeId"] for v in page["Volumes"]]
    return out


@mock_aws
def test_finds_unattached_volume():
    ec2 = boto3.client("ec2")
    vol = ec2.create_volume(AvailabilityZone="eu-west-1a", Size=10)
    assert idle_volume_ids(ec2) == [vol["VolumeId"]]


@mock_aws
def test_s3_upload_roundtrip():
    s3 = boto3.client("s3", region_name="eu-west-1")
    s3.create_bucket(Bucket="b", CreateBucketConfiguration={"LocationConstraint": "eu-west-1"})
    s3.put_object(Bucket="b", Key="k", Body=b"hello")
    assert s3.get_object(Bucket="b", Key="k")["Body"].read() == b"hello"
```
@check
Why set fake credentials in the test environment? || So that a configuration mistake can never reach a real account.
@end

@concept Testing the CLI, HTTP and time
@plain
Command line tools, HTTP calls and clocks are three common sources of flaky tests. Each has a standard answer: call `main(argv)` directly, replace the transport, and inject the current time.
@problem
Tests that shell out, call real URLs or depend on `datetime.now()` fail randomly and at midnight.
@does
- Call `main(["scan", "--days", "7"])` and use `capsys` to read the output; check the returned exit code.
- `httpx.MockTransport` or the `responses` library replaces the network.
- Pass `now` as a parameter with a default, so tests supply a fixed value.
- Use `caplog` to assert that a warning was logged.
@diagram flow
caption: Removing sources of flakiness
nodes:
  - "Arguments|main(argv)|app"
  - "Network|mock transport|info"
  - "Clock|now passed in|env"
  - "Deterministic test|same result every run|ok"
@h Example
```python title="test_cli_and_time.py"
from datetime import datetime, timedelta, timezone


def is_stale(last_seen: datetime, days: int, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now - last_seen > timedelta(days=days)


def main(argv: list[str]) -> int:
    print("stale" if is_stale(datetime(2026, 1, 1, tzinfo=timezone.utc), int(argv[0]),
                              now=datetime(2026, 3, 1, tzinfo=timezone.utc)) else "fresh")
    return 0


def test_is_stale_uses_injected_clock():
    now = datetime(2026, 1, 10, tzinfo=timezone.utc)
    assert is_stale(datetime(2026, 1, 1, tzinfo=timezone.utc), 5, now=now)
    assert not is_stale(datetime(2026, 1, 8, tzinfo=timezone.utc), 5, now=now)


def test_main_prints(capsys):
    assert main(["30"]) == 0
    assert capsys.readouterr().out.strip() == "stale"
```
@check
How do you make a time dependent function testable? || Accept the current time as a parameter and pass a fixed value in tests.
@end

@concept Property based tests with Hypothesis
@plain
Instead of writing examples, you state a **property** that must always hold ("parsing a formatted size returns the original number") and Hypothesis generates hundreds of inputs, including nasty ones, and shrinks any failure to a minimal case.
@problem
Hand written examples only cover what you imagined. Parsers, formatters and path handling fail on inputs nobody thought of.
@does
- `@given(st.integers(min_value=0, max_value=10**12))` generates test data.
- Typical properties: round trip (encode then decode), idempotence (applying twice equals once), invariants (output is sorted, never negative).
- Failing cases are saved so the next run replays them.
- Keep properties fast and pure.
@diagram flow
caption: Hypothesis loop
nodes:
  - "Strategy|describes inputs|info"
  - "Generate 100 cases|random and edge values|app"
  - "Property holds?|assert|env"
  - "Shrink failure|smallest counterexample|bad"
@h Example
```python title="test_properties.py" nocheck
from hypothesis import given, strategies as st


def format_bytes(n: int) -> str:
    return f"{n}B"


def parse_bytes(s: str) -> int:
    return int(s.removesuffix("B"))


@given(st.integers(min_value=0, max_value=10**15))
def test_roundtrip(n):
    assert parse_bytes(format_bytes(n)) == n


def normalise(tags: dict[str, str]) -> dict[str, str]:
    return {k.strip().lower(): v.strip() for k, v in tags.items()}


@given(st.dictionaries(st.text(), st.text()))
def test_normalise_is_idempotent(tags):
    once = normalise(tags)
    assert normalise(once) == once
```
@check
What does a round trip property check? || That encoding then decoding returns the original value.
@end
