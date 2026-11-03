---
title: Idempotency, retries and concurrency
minutes: 55
objectives:
  - Design automation so that running it twice is safe
  - Retry transient failures with exponential backoff and jitter using tenacity
  - Choose between threads, asyncio and processes for a job
  - Bound parallelism and collect errors from concurrent work
---
Automation runs unattended, fails halfway and gets restarted. Three habits make that survivable: operations that can safely repeat, retries that are polite, and concurrency that is bounded.

@concept Idempotency
@plain
An operation is **idempotent** if doing it twice leaves the same result as doing it once. "Ensure the bucket exists" is idempotent; "create a bucket" is not, because the second call fails.
@problem
Jobs are interrupted, retried by schedulers and re-run by humans. Non idempotent scripts create duplicates, send double notifications or crash on the second run.
@does
- Describe the **desired state** ("tag X must be Y") and make changes only if the current state differs.
- Check first, then act; treat "already exists" or "already gone" as success.
- Use deterministic names and keys instead of random ones.
- Record progress in the system itself (a tag, a marker object) rather than in memory.
@diagram flow
caption: Ensure, do not just create
nodes:
  - "Read current state|describe or get|info"
  - "Compare with desired|differs?|app"
  - "Change only the difference|patch or create|env"
  - "Same result on rerun|no changes|ok"
@h Ensure helpers
```python title="ensure.py" lab
from __future__ import annotations


def ensure_tags(current: dict[str, str], desired: dict[str, str]) -> dict[str, str]:
    """Return only the tags that must be written."""
    return {k: v for k, v in desired.items() if current.get(k) != v}


current = {"Owner": "platform"}
desired = {"Owner": "platform", "Env": "prod", "CostCenter": "1234"}
todo = ensure_tags(current, desired)
print("first run writes:", todo)
current.update(todo)
print("second run writes:", ensure_tags(current, desired))
```
@check
Is DELETE idempotent? || The end state is the same after repeats; a second delete may return 404, which your code should treat as success.
@end

@concept Retry design rules
@plain
Retry only failures that may go away: timeouts, throttling, 5xx. Never retry failures that will repeat: bad credentials, validation errors, not found. Limit attempts and total time.
@problem
Blind retries hide bugs, multiply load on a struggling service, and make a failing job run for hours.
@does
- **Exponential backoff** doubles the wait each time (1, 2, 4, 8 seconds up to a cap).
- **Jitter** adds randomness so many clients spread out.
- A **deadline** or attempt limit bounds total time; after it, fail clearly.
- Only retry idempotent operations, or use idempotency keys.
@diagram cmp
caption: What to retry
cards:
  - {h: "Retry", kind: ok, items: ["Connection reset and timeouts", "429 and 503", "AWS throttling codes"]}
  - {h: "Do not retry", kind: bad, items: ["401 and 403", "400 and 422 validation", "404 on a required object"]}
  - {h: "Be careful", kind: warn, items: ["POST without idempotency key", "Operations with side effects", "Very long operations"]}
@h Hand written backoff
```python title="backoff.py" lab
import random
import time


def retry(fn, attempts=5, base=0.1, cap=2.0, retry_on=(ConnectionError, TimeoutError)):
    for i in range(1, attempts + 1):
        try:
            return fn()
        except retry_on as exc:
            if i == attempts:
                raise
            delay = min(cap, base * 2 ** (i - 1)) * random.uniform(0.5, 1.0)
            print(f"attempt {i} failed ({exc}); sleeping {delay:.2f}s")
            time.sleep(delay)


calls = {"n": 0}


def flaky():
    calls["n"] += 1
    if calls["n"] < 3:
        raise ConnectionError("blip")
    return "ok"


print(retry(flaky))
```
@check
Why add jitter? || It spreads out retries from many clients so they do not all hit the service together.
@end

@concept tenacity decorators
@plain
`tenacity` is a library that wraps a function with retry rules written declaratively: when to stop, how long to wait, which exceptions to retry, and what to log.
@problem
Hand written loops get edge cases wrong: no cap, no jitter, retrying the wrong exception, losing the original error.
@does
- `@retry(stop=stop_after_attempt(5) | stop_after_delay(60), wait=wait_exponential_jitter(initial=1, max=30), retry=retry_if_exception_type(...), reraise=True)`.
- `before_sleep_log(logger, logging.WARNING)` records each retry.
- `Retrying(...)` as an iterator retries a block of code instead of a function.
- Works with `async def` functions as well.
@diagram flow
caption: Tenacity decision per failure
nodes:
  - "Call raises|exception|bad"
  - "retry predicate|is it retryable?|info"
  - "stop condition|attempts or time|warn"
  - "wait strategy|backoff and jitter|env"
  - "Try again or reraise|final error kept|ok"
@h Example
```python title="tenacity_example.py" nocheck
import logging

import requests
from tenacity import (before_sleep_log, retry, retry_if_exception_type,
                      stop_after_attempt, stop_after_delay, wait_exponential_jitter)

log = logging.getLogger("opskit")


class Transient(Exception):
    pass


@retry(
    retry=retry_if_exception_type((Transient, requests.ConnectionError, requests.Timeout)),
    stop=stop_after_attempt(6) | stop_after_delay(60),
    wait=wait_exponential_jitter(initial=1, max=20),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def fetch_status(url: str) -> dict:
    r = requests.get(url, timeout=5)
    if r.status_code in (429, 502, 503, 504):
        raise Transient(f"status {r.status_code}")
    r.raise_for_status()
    return r.json()
```
:::tip
`reraise=True` raises your original exception after the last attempt instead of tenacity's `RetryError`, which keeps error handling simpler.
:::
@check
What does reraise=True change? || The last original exception is raised instead of a RetryError wrapper.
@end

@concept Timeouts, deadlines and circuit breakers
@plain
A timeout bounds one call. A **deadline** bounds a whole operation including retries. A **circuit breaker** stops calling a dependency that keeps failing, giving it time to recover.
@problem
Retries multiplied by timeouts can make a job last far longer than anyone expects. Hammering a dead service keeps it dead.
@does
- Set connect and read timeouts on every network call.
- Compute `deadline = time.monotonic() + budget` and pass the remaining time to each attempt.
- A breaker has three states: closed (normal), open (fail fast), half open (try one request).
- Fail fast and report which dependency is unhealthy.
@diagram flow
caption: Circuit breaker states
nodes:
  - "Closed|calls pass|ok"
  - "Failures reach limit|count in window|warn"
  - "Open|calls fail at once|bad"
  - "Half open|one trial call|info"
@h A tiny breaker
```python title="breaker.py" lab
import time


class Breaker:
    def __init__(self, limit=3, reset_after=0.2):
        self.limit, self.reset_after = limit, reset_after
        self.failures, self.opened_at = 0, None

    def call(self, fn):
        if self.opened_at and time.monotonic() - self.opened_at < self.reset_after:
            raise RuntimeError("circuit open")
        try:
            result = fn()
        except Exception:
            self.failures += 1
            if self.failures >= self.limit:
                self.opened_at = time.monotonic()
            raise
        self.failures, self.opened_at = 0, None
        return result


def bad():
    raise OSError("down")


b = Breaker()
for _ in range(4):
    try:
        b.call(bad)
    except Exception as e:
        print(type(e).__name__, e)
time.sleep(0.25)
print(b.call(lambda: "recovered"))
```
@check
Why use time.monotonic for deadlines? || It never goes backwards when the system clock changes.
@end

@concept Threads for I/O bound work
@plain
A **thread** runs code at the same time as other threads inside one process. Python threads cannot run Python code truly in parallel (the GIL), but they overlap well while waiting on network or disk.
@problem
Calling an API for 500 resources one by one wastes minutes waiting for replies.
@does
- Good for boto3, HTTP and file I/O; not for pure computation.
- `ThreadPoolExecutor(max_workers=10)` provides a pool with a bound.
- boto3 clients are thread safe; sessions are not shared across threads (create one per thread).
- Limit workers to what the remote service tolerates.
@diagram flow
caption: A pool bounds parallel work
nodes:
  - "Work items|500 regions or ids|plain"
  - "Pool of 10 workers|bounded|app"
  - "Each waits on I/O|network replies|info"
  - "Results|as they finish|ok"
@h concurrent.futures
```python title="threads.py" lab
import time
from concurrent.futures import ThreadPoolExecutor, as_completed


def probe(name: str) -> tuple[str, float]:
    start = time.perf_counter()
    time.sleep(0.2)                       # stands for a network call
    return name, time.perf_counter() - start


names = [f"host-{i}" for i in range(20)]
start = time.perf_counter()
results, errors = [], []
with ThreadPoolExecutor(max_workers=10) as pool:
    futures = {pool.submit(probe, n): n for n in names}
    for fut in as_completed(futures):
        try:
            results.append(fut.result())
        except Exception as exc:          # one failure must not hide the others
            errors.append((futures[fut], exc))
print(len(results), "ok,", len(errors), "failed in", round(time.perf_counter() - start, 1), "s")
```
@check
Why not share one boto3 Session between threads? || Sessions are not thread safe; create one per thread, while clients are safe to share.
@end

@concept asyncio
@plain
`asyncio` runs many tasks on one thread. A task gives up control at each `await`, so while one waits for a reply others progress. It scales to thousands of concurrent waits.
@problem
Threads cost memory and need locks; thousands of them are impractical. Some libraries (httpx, aiobotocore, asyncpg) are written for async.
@does
- `async def` defines a coroutine; `await` pauses it; `asyncio.run(main())` starts the loop.
- `asyncio.gather` runs many together; `asyncio.TaskGroup` (Python 3.11) cancels siblings on failure.
- `asyncio.timeout(5)` bounds a block; `Semaphore` bounds parallelism.
- Never call blocking functions such as `time.sleep` or `requests.get` inside a coroutine; use `asyncio.to_thread` for those.
@diagram seq
caption: One thread, many waits
actors: ["Event loop|one thread|app", "Task A|waiting|env", "Task B|waiting|env"]
steps:
  - "0>1: start A, A awaits | req"
  - "0>2: start B, B awaits | req"
  - "1>0: A reply ready | resp"
  - "2>0: B reply ready | resp"
@h Example
```python title="async_tasks.py" lab
import asyncio


async def probe(name: str, delay: float, sem: asyncio.Semaphore) -> str:
    async with sem:
        await asyncio.sleep(delay)
        if name == "bad":
            raise RuntimeError("boom")
        return name


async def main() -> None:
    sem = asyncio.Semaphore(3)
    names = ["a", "b", "bad", "c"]
    results = await asyncio.gather(*(probe(n, 0.1, sem) for n in names), return_exceptions=True)
    for n, r in zip(names, results):
        print(n, "->", repr(r))
    async with asyncio.timeout(1):
        print(await asyncio.to_thread(sum, range(1000)))


asyncio.run(main())
```
@check
What does return_exceptions=True do in gather? || Failures come back as values in the result list instead of cancelling the whole gather.
@end

@concept Processes for CPU bound work
@plain
For heavy computation such as parsing gigabytes of logs, use separate processes. Each has its own interpreter and GIL, so work truly runs in parallel on several cores.
@problem
Threads do not speed up CPU work in Python. A single process parsing a 20 GB log uses one core while seven idle.
@does
- `ProcessPoolExecutor(max_workers=os.cpu_count())` has the same API as the thread pool.
- Arguments and results are pickled, so pass small items (file names, chunk offsets) and return summaries.
- Guard the entry with `if __name__ == "__main__":` because child processes import the module.
- Python 3.13 has an experimental free threaded build; do not rely on it yet.
@diagram cmp
caption: Picking a concurrency model
cards:
  - {h: "Threads", kind: ok, items: ["I/O bound with blocking libraries", "boto3 and requests", "Simple to add"]}
  - {h: "asyncio", kind: info, items: ["Thousands of waits", "Needs async libraries", "Single thread, no locks"]}
  - {h: "Processes", kind: app, items: ["CPU bound parsing", "Uses all cores", "Data is pickled between processes"]}
@h Example
```python title="processes.py" lab
import os
from concurrent.futures import ProcessPoolExecutor


def count_errors(chunk: list[str]) -> int:
    return sum(1 for line in chunk if "ERROR" in line)


if __name__ == "__main__":
    lines = ["ok", "ERROR a", "ok", "ERROR b"] * 50000
    chunks = [lines[i:i + 50000] for i in range(0, len(lines), 50000)]
    with ProcessPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        print(sum(pool.map(count_errors, chunks)))
```
@check
Why do processes help CPU work while threads do not? || Each process has its own GIL, so Python code runs on several cores at once.
@end

@concept Rate limiting and shared state safely
@plain
When many workers call one service, you need a shared limit. When they update shared data, you need a lock or, better, no shared mutable data at all.
@problem
Ten threads each retrying aggressively exceed an API limit together. Two threads appending to one list or counter can lose updates.
@does
- A `Semaphore` caps simultaneous calls; a token bucket caps calls per second.
- `queue.Queue` passes work between threads safely; `threading.Lock` guards counters.
- Prefer returning results from workers and combining them in the main thread.
- Log with thread names or task ids to follow events.
@diagram flow
caption: Producer and workers with a queue
nodes:
  - "Producer|puts items|app"
  - "Queue|thread safe|info"
  - "Workers|take and process|env"
  - "Main thread|combines results|ok"
@h Token bucket
```python title="rate_limit.py" lab
import threading
import time


class RateLimiter:
    def __init__(self, per_second: float) -> None:
        self.interval = 1.0 / per_second
        self.lock = threading.Lock()
        self.next_time = time.monotonic()

    def wait(self) -> None:
        with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_time - now)
            self.next_time = max(now, self.next_time) + self.interval
        if delay:
            time.sleep(delay)


rl = RateLimiter(per_second=50)
start = time.monotonic()
for _ in range(10):
    rl.wait()
print(f"10 calls took {time.monotonic() - start:.2f}s")
```
@check
Why return results instead of sharing a list? || It avoids locks and lost updates; the main thread merges the results.
@end
