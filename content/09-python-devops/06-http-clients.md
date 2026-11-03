---
title: HTTP clients with requests and httpx
minutes: 45
objectives:
  - Call HTTP APIs with timeouts, sessions and clear error handling
  - Add retries with backoff to safe requests
  - Choose between requests and httpx and use async httpx for fan out
  - Authenticate to APIs without leaking credentials
---
Nearly every platform you operate exposes an HTTP API. Writing a reliable client means more than calling `get`: timeouts, retries, sessions and error handling decide whether your tool survives a bad network day.
@concept The request and response cycle
@plain
An HTTP call sends a method (GET, POST, PUT, PATCH, DELETE), a URL, headers and an optional body, and receives a status code, headers and a body.
@problem
Treating an API call as "it either works or throws" hides the real outcomes: 4xx means you made a mistake, 5xx means the server failed, and a network error means you do not know what happened.
@does
- 2xx success, 3xx redirect, 4xx client error (401 unauthenticated, 403 forbidden, 404 missing, 429 rate limited), 5xx server error.
- GET, PUT and DELETE are meant to be idempotent; POST usually is not.
- Always parse the body according to `Content-Type`, and read error bodies; they usually explain the failure.
@diagram seq
caption: One request and its possible outcomes
actors: ["Client|your tool|app", "API|service|ext"]
steps:
  - "0>1: GET /v1/items | req"
  - "1>0: 200 JSON body | resp"
  - "0>1: GET /v1/items?bad | req"
  - "1>0: 400 error message | bad"
  - "note 0..1: 429 and 5xx may be retried"
@h Status classes in code
```python title="Classify outcomes" lab
def classify(status: int) -> str:
    if 200 <= status < 300:
        return "ok"
    if status in (408, 425, 429) or status >= 500:
        return "retry"
    if status in (401, 403):
        return "auth problem"
    return "client error, do not retry"


for code in (200, 404, 429, 503, 401):
    print(code, classify(code))
```
@check
Which statuses are normally worth retrying? || 408, 429 and 5xx, because the request may succeed later; most other 4xx will fail the same way again.
@end

@concept requests basics and timeouts
@plain
`requests` is the long standing, simple HTTP library. The most important rule: **always pass a timeout**, because by default requests waits forever.
@problem
A server that accepts a connection and never answers blocks your script indefinitely. In a scheduled job this means missed runs and stuck processes.
@does
- `requests.get(url, params={...}, headers={...}, timeout=(3.05, 10))` sets connect and read timeouts.
- `resp.raise_for_status()` turns 4xx and 5xx into `requests.HTTPError`.
- `resp.json()` parses the body; `resp.text` and `resp.content` give text and bytes.
- `json=payload` sends JSON and sets the header for you.
@diagram flow
caption: A careful call
numbered: true
nodes:
  - "Build request|url, params, headers|app"
  - "Send with timeout|connect and read|info"
  - "raise_for_status|fail on 4xx and 5xx|warn"
  - "resp.json|use the data|ok"
@h Example
```python title="requests with a timeout" nocheck
import requests


def get_json(url: str, **params: str) -> dict:
    resp = requests.get(url, params=params, timeout=(3.05, 10), headers={"Accept": "application/json"})
    resp.raise_for_status()
    return resp.json()


try:
    data = get_json("https://api.example.com/v1/services", team="platform")
except requests.Timeout:
    print("timed out")
except requests.HTTPError as exc:
    print("http error", exc.response.status_code, exc.response.text[:200])
except requests.ConnectionError:
    print("cannot connect")
```
@check
What happens if you omit timeout in requests? || The call can wait forever, because there is no default timeout.
@end

@concept Sessions and connection reuse
@plain
A `requests.Session` keeps connections open between calls and shares headers, authentication and cookies. It is faster and shorter to write than separate calls.
@problem
Each bare `requests.get` opens a new TCP and TLS connection. Calling an API a thousand times that way is slow and strains the server.
@does
- `session.headers.update({...})` sets headers once.
- `session.auth`, `session.verify` and `session.proxies` apply to every call.
- Use `with requests.Session() as s:` so connections close.
- A session has no global timeout; wrap calls or subclass to inject one.
@diagram cmp
caption: Bare calls versus a session
cards:
  - {h: "Bare requests.get", kind: warn, items: ["New connection each time", "Repeat headers everywhere", "Slow for many calls"]}
  - {h: "Session", kind: ok, items: ["Connection pool reused", "Headers and auth set once", "Cookies kept"]}
@h A session with a default timeout
```python title="session_client.py" nocheck
import requests


class ApiClient(requests.Session):
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.default_timeout = timeout
        self.headers.update({"Authorization": f"Bearer {token}", "Accept": "application/json"})

    def request(self, method, url, **kwargs):  # type: ignore[override]
        kwargs.setdefault("timeout", self.default_timeout)
        return super().request(method, f"{self.base_url}/{url.lstrip('/')}", **kwargs)


with ApiClient("https://api.example.com", token="from-env") as api:
    print(api.get("/v1/health").status_code)
```
@check
Why is a session faster? || It reuses open connections, avoiding repeated TCP and TLS setup.
@end

@concept Retries with backoff in requests
@plain
A **retry** tries a failed call again. **Backoff** waits longer between tries, with a little random **jitter**, so many clients do not hammer a recovering server at the same moment.
@problem
Networks drop packets and services return 502 or 429 for a few seconds. A script without retries fails on a blip; a script with instant retries makes outages worse.
@does
- Mount `HTTPAdapter(max_retries=Retry(...))` on a session; `Retry` comes from `urllib3.util.retry`.
- `status_forcelist=[429, 500, 502, 503, 504]` chooses what to retry.
- `backoff_factor=0.5` waits roughly 0.5, 1, 2, 4 seconds and `respect_retry_after_header` honours the server's hint.
- Only retry methods that are safe to repeat, set with `allowed_methods`.
@diagram seq
caption: Backoff after transient failures
actors: ["Client|session with Retry|app", "API|recovering|ext"]
steps:
  - "0>1: request | req"
  - "1>0: 503 | bad"
  - "note 0..0: wait 0.5 s plus jitter"
  - "0>1: retry | req"
  - "1>0: 503 | bad"
  - "note 0..0: wait 1 s plus jitter"
  - "0>1: retry | req"
  - "1>0: 200 | resp"
@h Configuring Retry
```python title="retry_session.py" nocheck
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def make_session() -> requests.Session:
    retry = Retry(
        total=5,
        connect=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS"}),
        respect_retry_after_header=True,
    )
    s = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


resp = make_session().get("https://api.example.com/v1/items", timeout=10)
```
:::warn
POST is left out on purpose. Retrying a POST that created something can create it twice unless the API supports an idempotency key.
:::
@check
Why add jitter? || Random spread stops many clients from retrying at the same instant and overloading the server.
@end

@concept httpx, a modern client
@plain
`httpx` has an API very close to requests and adds HTTP/2 support, strict timeouts by default, type hints, and both synchronous and asynchronous clients.
@problem
requests cannot do async I/O, so calling 200 endpoints one after another is slow, and threads add complexity.
@does
- `httpx.Client(timeout=10.0, base_url=...)` is the equivalent of a session.
- Default timeout is 5 seconds; set `httpx.Timeout(10.0, connect=3.0)` to control parts.
- `httpx.HTTPTransport(retries=3)` retries only connection failures; for status retries use tenacity.
- `httpx.MockTransport` makes tests easy without a network.
@diagram cmp
caption: requests versus httpx
cards:
  - {h: "requests", kind: info, items: ["Very common, simple", "Sync only", "Timeout must be set by you"]}
  - {h: "httpx", kind: ok, items: ["Sync and async clients", "Default timeout of 5 seconds", "HTTP/2 optional, MockTransport for tests"]}
@h Sync client and a test transport
```python title="httpx with MockTransport" nocheck
import httpx


def handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/v1/items":
        return httpx.Response(200, json={"items": [1, 2, 3]})
    return httpx.Response(404, json={"error": "not found"})


transport = httpx.MockTransport(handler)
with httpx.Client(transport=transport, base_url="https://api.example.com", timeout=10.0) as client:
    r = client.get("/v1/items")
    r.raise_for_status()
    print(r.json())

real = httpx.Client(timeout=httpx.Timeout(10.0, connect=3.0), transport=httpx.HTTPTransport(retries=2))
```
@choose Picking a client
requests | scripts already using it and simple sync flows | you need async or HTTP/2
httpx | new code, async fan out, easy tests | the environment forbids extra dependencies
urllib.request | zero dependency scripts and zipapps | you need sessions, retries or comfort
@check
What does HTTPTransport(retries=n) retry? || Only connection establishment failures, not HTTP error statuses.
@end

@concept Async fan out with httpx.AsyncClient
@plain
With **asyncio**, one thread starts many requests and handles whichever answers first. This is ideal for checking hundreds of URLs or APIs where each call mostly waits for the network.
@problem
Checking 300 health endpoints serially at 200 ms each takes a minute; the same checks in parallel take about a second.
@does
- `async with httpx.AsyncClient() as client:` shares a connection pool.
- `asyncio.gather(*tasks)` runs calls concurrently.
- Use an `asyncio.Semaphore(n)` to cap parallel requests so you do not overload yourself or the target.
- Handle errors per task with `return_exceptions=True` or a try block.
@diagram flow
caption: Concurrent checks with a limit
nodes:
  - "List of URLs|300 endpoints|plain"
  - "Semaphore 20|at most 20 in flight|warn"
  - "AsyncClient|shared pool|app"
  - "gather|collect results|info"
  - "Report|status and latency|ok"
@h Example
```python title="health_sweep.py" nocheck
import asyncio
import time

import httpx


async def check(client: httpx.AsyncClient, sem: asyncio.Semaphore, url: str) -> dict:
    async with sem:
        start = time.perf_counter()
        try:
            r = await client.get(url)
            return {"url": url, "status": r.status_code, "ms": round((time.perf_counter() - start) * 1000)}
        except httpx.HTTPError as exc:
            return {"url": url, "status": None, "error": type(exc).__name__}


async def sweep(urls: list[str], limit: int = 20) -> list[dict]:
    sem = asyncio.Semaphore(limit)
    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        return await asyncio.gather(*(check(client, sem, u) for u in urls))


if __name__ == "__main__":
    results = asyncio.run(sweep(["https://example.com", "https://example.org"]))
    for row in results:
        print(row)
```
@check
Why use a Semaphore? || It limits how many requests run at once so you do not exhaust sockets or overload the target.
@end

@concept Authentication, TLS and proxies
@plain
APIs need to know who you are: a bearer token, basic credentials, an API key header, or a client certificate. TLS verification proves you reached the right server.
@problem
Disabling certificate checks (`verify=False`) to silence an error removes the protection against impersonation, and tokens placed in URLs end up in logs.
@does
- Send tokens in the `Authorization` header, never in the query string.
- `verify="/path/ca-bundle.pem"` trusts a private CA properly; `cert=("client.pem", "client.key")` presents a client certificate.
- Both libraries honour `HTTPS_PROXY`, `NO_PROXY` and `REQUESTS_CA_BUNDLE` or `SSL_CERT_FILE` from the environment.
- Refresh short lived OAuth tokens before they expire and retry once on 401.
@diagram layers
caption: Layers of a trusted API call
layers:
  - {label: "Transport", nodes: ["TLS verify|server identity checked|ok", "Private CA bundle|trusts internal CA|info"]}
  - {label: "Identity", nodes: ["Bearer token|header|app", "Client certificate|mutual TLS|app"]}
  - {label: "Policy", nodes: ["Timeouts|bounded waits|env", "Retries|only safe calls|env"]}
@h Safe patterns
```python title="Private CA and token from the environment" nocheck
import os

import requests

session = requests.Session()
session.headers["Authorization"] = f"Bearer {os.environ['API_TOKEN']}"
session.verify = os.environ.get("CA_BUNDLE", True)     # path to a PEM file or True

resp = session.get("https://internal.example.com/api/v1/me", timeout=10)
print(resp.status_code)
# Wrong: requests.get(url, verify=False)  -> disables certificate checking
```
@check
How do you trust an internal certificate authority correctly? || Point verify (or SSL_CERT_FILE) at the CA bundle instead of disabling verification.
@end
