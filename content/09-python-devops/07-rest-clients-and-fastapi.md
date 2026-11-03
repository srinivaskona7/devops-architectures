---
title: REST API clients, pagination and FastAPI
minutes: 45
objectives:
  - Wrap a REST API in a small typed client class
  - Walk every page of a paginated API with a generator
  - Respect rate limits and handle errors consistently
  - Expose a small internal service with FastAPI
---
Operations teams both consume APIs (ticketing, inventory, cloud providers) and publish small ones (a webhook receiver, a status service). This section covers both directions.

@concept A small API client class
@plain
Instead of scattering `requests.get(...)` calls, put each API behind one class with one method per operation. The rest of the code never sees URLs or headers.
@problem
When the base URL, token or error rules change, every script that built its own requests must be edited, and each one handles errors differently.
@does
- One place owns the session, timeout, authentication and base URL.
- Methods return plain dataclasses or dictionaries, not raw responses.
- A single `_request` method maps HTTP failures to your own exception types.
- Tests replace the transport, so no network is needed.
@diagram layers
caption: Where each concern lives
layers:
  - {label: "Tools", nodes: ["scan script|calls methods|app", "report script|calls methods|app"]}
  - {label: "Client class", nodes: ["list_services|domain method|ok", "get_service|domain method|ok", "_request|one place for HTTP rules|cp"]}
  - {label: "Transport", nodes: ["Session|timeouts, auth, retries|env", "REST API|remote service|ext"]}
@h A client with a fake transport
```python title="inventory_client.py" lab
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ApiError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status


@dataclass(frozen=True)
class Service:
    name: str
    owner: str


class InventoryClient:
    def __init__(self, send: Callable[[str, str], tuple[int, Any]]) -> None:
        self._send = send                      # (method, path) -> (status, json)

    def _request(self, method: str, path: str) -> Any:
        status, body = self._send(method, path)
        if status >= 400:
            raise ApiError(status, str(body))
        return body

    def get_service(self, name: str) -> Service:
        raw = self._request("GET", f"/services/{name}")
        return Service(name=raw["name"], owner=raw["owner"])


def fake_send(method: str, path: str) -> tuple[int, Any]:
    if path == "/services/web":
        return 200, {"name": "web", "owner": "platform"}
    return 404, "not found"


client = InventoryClient(fake_send)
print(client.get_service("web"))
try:
    client.get_service("nope")
except ApiError as exc:
    print("error", exc.status)
```
@check
Why return dataclasses instead of raw responses? || Callers get named fields and never depend on HTTP details.
@end

@concept Pagination styles
@plain
Large lists are returned in **pages**. The API tells you how to get the next page: a page number, an offset, a cursor token, or a `Link` header.
@problem
A script that reads only the first response silently processes 100 of 5,000 items. Reports are wrong and nobody notices.
@does
- **Page or offset**: `?page=2&per_page=100`. Simple, but items can shift while you read.
- **Cursor or token**: the response holds `next_token`; stable under changes. AWS uses this style.
- **Link header**: `Link: <url>; rel="next"`; GitHub uses this. `requests` parses it into `resp.links`.
- Stop when there is no next marker, not when a page looks short.
@diagram cmp
caption: Three common styles
cards:
  - {h: "Offset or page", kind: info, items: ["page and per_page", "Easy to jump", "Can skip or repeat on changes"]}
  - {h: "Cursor token", kind: ok, items: ["next_token in the body", "Stable while reading", "Only forward"]}
  - {h: "Link header", kind: app, items: ["rel next URL in header", "Follow until absent", "requests resp.links"]}
@h Generators hide the paging
```python title="paginate.py" lab
from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Callable


def paginate_cursor(fetch: Callable[[str | None], dict[str, Any]]) -> Iterator[dict[str, Any]]:
    token: str | None = None
    while True:
        page = fetch(token)
        yield from page["items"]
        token = page.get("next_token")
        if not token:
            return


DATA = list(range(1, 8))


def fake_fetch(token: str | None) -> dict[str, Any]:
    start = int(token or 0)
    chunk = DATA[start:start + 3]
    nxt = str(start + 3) if start + 3 < len(DATA) else None
    return {"items": [{"id": i} for i in chunk], "next_token": nxt}


print([row["id"] for row in paginate_cursor(fake_fetch)])
```
@check
Why use a generator for pagination? || Callers loop over items as if there was one list, and memory holds only one page at a time.
@end

@concept Following Link headers and rate limits
@plain
Many APIs limit how fast you may call them and say so in headers such as `Retry-After`, `X-RateLimit-Remaining` and `X-RateLimit-Reset`. A polite client reads them.
@problem
Ignoring limits earns HTTP 429 responses or a temporary ban, which stops your whole automation.
@does
- On 429, wait for `Retry-After` seconds (or use exponential backoff if absent) and try again.
- Slow down before the limit when `X-RateLimit-Remaining` approaches zero.
- Fetch only what you need with filters and `fields` options; request bigger pages where allowed.
- Cache results that change slowly.
@diagram seq
caption: Waiting out a rate limit
actors: ["Client|polite|app", "API|rate limited|ext"]
steps:
  - "0>1: GET page 7 | req"
  - "1>0: 429 Retry-After 20 | bad"
  - "note 0..0: sleep 20 seconds"
  - "0>1: GET page 7 again | req"
  - "1>0: 200 with Link next | resp"
@h Link following
```python title="github_style_links.py" nocheck
import time

import requests


def iter_items(session: requests.Session, url: str):
    while url:
        resp = session.get(url, timeout=15)
        if resp.status_code == 429:
            time.sleep(int(resp.headers.get("Retry-After", "10")))
            continue                              # same URL again
        resp.raise_for_status()
        yield from resp.json()
        url = resp.links.get("next", {}).get("url")   # absent on the last page


s = requests.Session()
s.headers["Accept"] = "application/vnd.github+json"
for repo in iter_items(s, "https://api.github.com/orgs/example/repos?per_page=100"):
    print(repo["full_name"])
```
@check
What does the loop use to know it reached the last page? || The next link is missing from resp.links.
@end

@concept Idempotency keys for writes
@plain
An **idempotency key** is a unique value you send with a POST so the server can recognise a repeated request and return the original result instead of creating a second copy.
@problem
If a POST times out, you cannot know whether it was applied. Retrying may create a duplicate ticket, payment or server.
@does
- Generate one key per logical operation (`uuid.uuid4()`) and reuse it on every retry.
- Send it in a header such as `Idempotency-Key` when the API supports it.
- Without support, search first (GET by a unique name) and create only if missing.
@diagram seq
caption: A safe retry of a POST
actors: ["Client|key abc-123|app", "API|dedupes by key|ext"]
steps:
  - "0>1: POST create with key | req"
  - "note 1..1: created, but reply is lost"
  - "0>1: POST again, same key | req"
  - "1>0: original result returned | resp"
@h Example
```python title="idempotency_key.py" lab
import uuid

CREATED: dict[str, dict] = {}


def api_create(key: str, payload: dict) -> dict:
    if key in CREATED:                      # server side dedupe
        return CREATED[key]
    CREATED[key] = {"id": len(CREATED) + 1, **payload}
    return CREATED[key]


key = str(uuid.uuid4())
first = api_create(key, {"title": "disk alert"})
retry = api_create(key, {"title": "disk alert"})        # same key after a timeout
print(first == retry, len(CREATED))
```
@check
When must the key change? || For each new logical operation; reuse the same key only for retries of the same operation.
@end

@concept FastAPI for small internal services
@plain
FastAPI is a Python web framework where you write typed functions and get routing, input validation, JSON output and interactive documentation automatically.
@problem
Operations teams often need a tiny service: a webhook receiver, a deploy status page, an internal lookup. Building one with raw `http.server` means hand parsing and no validation.
@does
- `@app.get("/health")` and `@app.post("/events")` bind functions to routes.
- Pydantic models validate request bodies; wrong input becomes a 422 response with details.
- Docs appear at `/docs` (Swagger UI) and `/openapi.json` with no extra work.
- Run with `uvicorn module:app`; test with `TestClient`.
@diagram flow
caption: A request through FastAPI
nodes:
  - "HTTP request|JSON body|ext"
  - "Validation|pydantic model|info"
  - "Your function|business logic|app"
  - "Response model|serialised JSON|ok"
@h A webhook receiver
```python title="app.py" nocheck
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Deploy events")
EVENTS: list[dict] = []


class DeployEvent(BaseModel):
    service: str = Field(min_length=1, max_length=64)
    version: str
    environment: str = Field(pattern="^(dev|staging|prod)$")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/events", status_code=201)
def add_event(event: DeployEvent, x_token: str | None = Header(default=None)) -> dict:
    if x_token != "expected-token-from-env":          # read from settings in real code
        raise HTTPException(status_code=401, detail="bad token")
    record = {**event.model_dump(), "at": datetime.now(timezone.utc).isoformat()}
    EVENTS.append(record)
    return record


@app.get("/events")
def list_events(service: str | None = None) -> list[dict]:
    return [e for e in EVENTS if service in (None, e["service"])]
```
```bash title="Run and call it" nocheck
uvicorn app:app --host 0.0.0.0 --port 8080
curl -s -X POST localhost:8080/events -H 'x-token: expected-token-from-env' \
  -H 'content-type: application/json' \
  -d '{"service":"web","version":"1.4.2","environment":"prod"}'
```
@check
What does FastAPI return for a body that fails validation? || A 422 response listing which fields were wrong.
@end

@concept Making a FastAPI service production ready
@plain
A service in Kubernetes needs health endpoints, graceful shutdown, structured logs and tests. These are small additions in FastAPI.
@problem
Without health endpoints Kubernetes cannot tell when to send traffic or restart; without tests every change is a risk.
@does
- `/healthz` (liveness: process is up) and `/readyz` (readiness: dependencies are reachable) endpoints.
- `lifespan` handlers open and close connections at start and stop.
- Dependencies (`Depends`) inject settings, clients and authentication, and can be overridden in tests.
- Run several uvicorn workers or several pods, not shared in memory state.
@diagram flow
caption: Pieces around the app
nodes:
  - "Container|uvicorn on port 8080|env"
  - "Probes|/healthz and /readyz|info"
  - "App|routes and dependencies|app"
  - "Metrics|/metrics for Prometheus|ok"
@h Testing without a server
```python title="test_app.py" nocheck
from fastapi.testclient import TestClient

from app import app

client = TestClient(app)


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_rejects_bad_environment():
    r = client.post("/events", json={"service": "web", "version": "1", "environment": "moon"},
                    headers={"x-token": "expected-token-from-env"})
    assert r.status_code == 422
```
:::tip
Keep state outside the process (a database or object store). Two pods of the same service must give the same answers.
:::
@check
What is the difference between liveness and readiness? || Liveness says restart me if I am stuck; readiness says do not send me traffic until my dependencies work.
@end
