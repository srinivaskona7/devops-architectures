---
title: Payments, the mock UPI gateway and the web frontend
minutes: 60
objectives:
  - Model a UPI collect payment with idempotency and signed webhooks
  - Build a mock gateway that can succeed, fail or answer late
  - Serve a plain HTML frontend through nginx that proxies the services
---
Payments is the service that earns the most attention from security and on-call. UPI (Unified Payments Interface) lets a customer approve a payment from a bank app using a virtual payment address (VPA) such as `asha@okbank`. In a real launch you integrate a licensed payment provider; the rules for collect requests change over time, so check the current provider and NPCI documentation. Here a mock gateway stands in so every failure mode can be rehearsed.

@concept Payment states and the UPI flow
@plain
A payment starts as `PENDING` and ends as `SUCCESS` or `FAILURE`. UPI is asynchronous by nature: the customer must approve on their phone, which can take seconds or never happen.
@problem
Treating a payment as a single synchronous call loses money: a timeout does not mean the customer did not pay.
@does
- Payments writes its own row first, then calls the gateway with the payment id as the reference.
- A gateway timeout leaves the payment `PENDING`; the signed webhook or a reconciliation job later settles it.
- One payment per order (unique `order_id`), so a retry returns the same payment.
- Amounts are integer paise. The VPA is stored but masked in logs.
@diagram flow
caption: Payment state machine
nodes:
  - "PENDING|row written first|warn"
  - "Gateway collect|customer approves|ext"
  - "SUCCESS|order paid|ok"
  - "FAILURE|stock released|bad"
@end

@concept Payments data model and settings
@plain
One table keyed by order, plus settings for the gateway address and the webhook secret.
@problem
Without a unique order key a double click or client retry charges the customer twice.
@does
- `order_id` is unique, so the database refuses a second payment for the same order.
- `GATEWAY_URL`, `WEBHOOK_SECRET` and `ORDERS_URL` come from the environment; the secret comes from a Kubernetes Secret.
- `gateway_ref` stores the provider's reference for reconciliation.
@diagram layers
caption: Payments storage
layers:
  - {label: "payments table", nodes: ["id|primary key|cp", "order_id|unique|ok", "amount_paise|integer|plain", "vpa|masked in logs|warn", "status|PENDING SUCCESS FAILURE|info"]}
@h db.py and config.py
```python title="services/payments/app/db.py"
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    amount_paise: Mapped[int] = mapped_column(Integer)
    vpa: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    gateway_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)


def make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
```
```python title="services/payments/app/config.py"
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    service_name: str = os.getenv("SERVICE_NAME", "payments")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    gateway_url: str = os.getenv("GATEWAY_URL", "http://upi-mock:8000")
    orders_url: str = os.getenv("ORDERS_URL", "http://orders:8000")
    webhook_secret: str = os.getenv("WEBHOOK_SECRET", "dev-only-secret")
    call_timeout: float = float(os.getenv("CALL_TIMEOUT_SECONDS", "3"))


settings = Settings()
```
@end

@concept Signed webhooks
@plain
The gateway sends the final result to us by an HTTP call. It signs the body with a shared secret so we know it is genuine.
@problem
A webhook URL is public to the internet. Anyone could post "SUCCESS" and get free goods.
@does
- Signature is HMAC-SHA256 of the raw request body, hex encoded, sent in `X-Signature`.
- We compute our own and compare with `hmac.compare_digest`, which takes constant time and prevents timing attacks.
- Reject with 401 if it differs. The secret is rotated by changing the Kubernetes Secret and restarting; providers usually support two active secrets during rotation.
- The webhook handler is idempotent: a repeated event for a settled payment changes nothing.
@diagram seq
caption: Late result by webhook
actors: ["Gateway|UPI provider|ext", "payments|webhook endpoint|app", "orders|internal API|app"]
steps:
  - "0>1: POST webhook with X-Signature | tls"
  - "note 1..1: verify HMAC on raw body"
  - "1>1: update payment row | req"
  - "1>2: payment-result | req"
  - "2>1: 200 | resp"
  - "1>0: 200 | resp"
@h security.py
```python title="services/payments/app/security.py"
import hashlib
import hmac


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify(secret: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign(secret, body), signature or "")
```
@end

@concept The gateway client and the payments routes
@plain
Payments calls the gateway with a timeout and maps every outcome to a payment status.
@problem
A hung gateway call would hold a worker and make checkout slow for everyone.
@does
- Timeout or network error leaves the payment `PENDING` and returns it; the order stays pending too.
- A repeated `POST /payments` for the same order returns the stored row without calling the gateway again.
- After a webhook, payments tells orders the final result (best effort; reconciliation catches failures).
- Logs use `mask(vpa)` so only the first two characters appear.
@diagram flow
caption: Collect request outcomes
nodes:
  - "POST payments|from orders|app"
  - "Row exists?|return stored|info"
  - "Gateway answers|SUCCESS or FAILURE|ok"
  - "Gateway times out|stay PENDING|warn"
@h gateway.py and main.py
```python title="services/payments/app/gateway.py"
import httpx

from .config import settings


def collect(ref: str, amount_paise: int, vpa: str) -> dict:
    """Ask the gateway to send a collect request. Returns {'status': ...}."""
    try:
        with httpx.Client(timeout=settings.call_timeout) as c:
            r = c.post(f"{settings.gateway_url}/collect", json={
                "ref": ref, "amount_paise": amount_paise, "vpa": vpa,
                "callback_url": "http://payments:8000/webhooks/upi"})
        if r.status_code >= 500:
            return {"status": "PENDING"}
        return r.json()
    except httpx.HTTPError:
        return {"status": "PENDING"}


def notify_orders(order_id: int, status: str) -> None:
    try:
        with httpx.Client(timeout=settings.call_timeout) as c:
            c.post(f"{settings.orders_url}/internal/orders/{order_id}/payment-result",
                   json={"status": status})
    except httpx.HTTPError:
        pass  # reconciliation job repairs it
```
```python title="services/payments/app/main.py"
import json
import logging

from fastapi import FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from . import gateway, logs, obs, security
from .config import settings
from .db import Base, Payment, SessionLocal, engine

logs.setup(settings.log_level)
Base.metadata.create_all(engine)
app = FastAPI(title="payments")
obs.install(app, "payments")
log = logging.getLogger("shop")


class NewPayment(BaseModel):
    order_id: int = Field(gt=0)
    amount_paise: int = Field(gt=0, le=10_000_000)
    vpa: str = Field(pattern=r"^[\w.\-]{2,64}@[A-Za-z]{2,32}$")


def mask(vpa: str) -> str:
    return vpa[:2] + "***@" + vpa.split("@")[-1]


def to_dict(p: Payment) -> dict:
    return {"id": p.id, "order_id": p.order_id, "amount_paise": p.amount_paise, "status": p.status}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        response.status_code = 503
        return {"status": "database unavailable"}
    return {"status": "ready"}


@app.post("/payments")
def create_payment(body: NewPayment) -> dict:
    with SessionLocal.begin() as s:
        existing = s.scalar(select(Payment).where(Payment.order_id == body.order_id))
        if existing:
            return to_dict(existing)
        p = Payment(order_id=body.order_id, amount_paise=body.amount_paise, vpa=body.vpa)
        s.add(p)
        s.flush()
        pid = p.id
    log.info("collect", extra={"fields": {"order_id": body.order_id, "vpa": mask(body.vpa)}})
    result = gateway.collect(f"pay-{pid}", body.amount_paise, body.vpa)
    status = result.get("status", "PENDING")
    with SessionLocal.begin() as s:
        p = s.get(Payment, pid)
        if status in ("SUCCESS", "FAILURE"):
            p.status = status
        p.gateway_ref = f"pay-{pid}"
        return to_dict(p)


@app.post("/webhooks/upi")
async def upi_webhook(request: Request) -> dict:
    raw = await request.body()
    if not security.verify(settings.webhook_secret, raw, request.headers.get("X-Signature", "")):
        raise HTTPException(401, "bad signature")
    event = json.loads(raw)
    ref, status = event.get("ref", ""), event.get("status")
    if status not in ("SUCCESS", "FAILURE") or not ref.startswith("pay-"):
        raise HTTPException(422, "bad event")
    with SessionLocal.begin() as s:
        p = s.get(Payment, int(ref[4:]))
        if not p:
            raise HTTPException(404, "unknown payment")
        if p.status != "PENDING":
            return to_dict(p)
        p.status = status
        order_id, out = p.order_id, to_dict(p)
    gateway.notify_orders(order_id, status)
    return out
```
@end

@concept Payments tests including signature checks
@plain
Tests prove the idempotency, the timeout behaviour and the webhook signature rules.
@problem
Payment bugs are discovered by customers unless tests describe the money rules first.
@does
- A fake gateway returns SUCCESS, FAILURE or PENDING.
- A second call for the same order must not call the gateway again.
- A webhook with a wrong signature gets 401 and does not change the row.
- A valid webhook settles a pending payment and calls `notify_orders` once.
@diagram flow
caption: What the suite protects
nodes:
  - "No double charge|unique order|ok"
  - "Late result handled|webhook|info"
  - "Forged webhook refused|HMAC|bad"
  - "Timeout stays pending|no false failure|warn"
@h test_payments.py
```python title="services/payments/tests/test_payments.py"
import json

import pytest
from fastapi.testclient import TestClient

from app import gateway, security
from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture
def fake(monkeypatch):
    state = {"status": "SUCCESS", "calls": 0, "notified": []}

    def collect(ref, amount, vpa):
        state["calls"] += 1
        return {"status": state["status"]}

    monkeypatch.setattr(gateway, "collect", collect)
    monkeypatch.setattr(gateway, "notify_orders", lambda oid, st: state["notified"].append((oid, st)))
    return state


def pay(order_id, vpa="asha@okbank"):
    return client.post("/payments", json={"order_id": order_id, "amount_paise": 50000, "vpa": vpa})


def test_success(fake):
    assert pay(1).json()["status"] == "SUCCESS"


def test_same_order_does_not_call_gateway_twice(fake):
    first = pay(2).json()
    second = pay(2).json()
    assert first["id"] == second["id"] and fake["calls"] == 1


def test_pending_then_valid_webhook(fake):
    fake["status"] = "PENDING"
    p = pay(3).json()
    assert p["status"] == "PENDING"
    body = json.dumps({"ref": f"pay-{p['id']}", "status": "SUCCESS"}).encode()
    sig = security.sign(settings.webhook_secret, body)
    r = client.post("/webhooks/upi", content=body, headers={"X-Signature": sig})
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"
    assert fake["notified"] == [(3, "SUCCESS")]


def test_forged_webhook_rejected(fake):
    fake["status"] = "PENDING"
    p = pay(4).json()
    body = json.dumps({"ref": f"pay-{p['id']}", "status": "SUCCESS"}).encode()
    r = client.post("/webhooks/upi", content=body, headers={"X-Signature": "00"})
    assert r.status_code == 401 and fake["notified"] == []


def test_invalid_vpa_and_amount(fake):
    assert pay(5, vpa="bad").status_code == 422
    r = client.post("/payments", json={"order_id": 6, "amount_paise": 0, "vpa": "a1@okbank"})
    assert r.status_code == 422
```
@end

@concept The mock UPI gateway
@plain
A tiny service that behaves like a payment provider: the VPA suffix chooses the outcome, so every case can be tested on demand.
@problem
You cannot test failure and late-result handling against a real bank, and you must never send test traffic to production providers.
@does
- `name@okbank` succeeds at once. `name@okfail` fails. `name@okslow` answers `PENDING` and sends a signed webhook after two seconds.
- Runs in dev and staging only; production points `GATEWAY_URL` at the real provider (a different secret and URL, set in the prod overlay).
- Shares the webhook signing function so the full path is exercised.
@diagram cmp
caption: VPA suffix decides the result
cards:
  - {h: "okbank", kind: ok, items: ["Immediate SUCCESS", "Normal path"]}
  - {h: "okfail", kind: bad, items: ["Immediate FAILURE", "Tests stock release"]}
  - {h: "okslow", kind: warn, items: ["PENDING at once", "Signed webhook after 2 seconds", "Tests the late path"]}
@h upi-mock
```python title="upi-mock/app/main.py"
import asyncio
import hashlib
import hmac
import json
import os

import httpx
from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

SECRET = os.getenv("WEBHOOK_SECRET", "dev-only-secret")
DELAY = float(os.getenv("SLOW_DELAY_SECONDS", "2"))
app = FastAPI(title="upi-mock")


class Collect(BaseModel):
    ref: str
    amount_paise: int
    vpa: str
    callback_url: str


async def send_webhook(url: str, ref: str, status: str) -> None:
    await asyncio.sleep(DELAY)
    body = json.dumps({"ref": ref, "status": status}).encode()
    sig = hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.post(url, content=body, headers={"X-Signature": sig})
    except httpx.HTTPError:
        pass


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.post("/collect")
def collect(req: Collect, tasks: BackgroundTasks) -> dict:
    suffix = req.vpa.split("@")[-1].lower()
    if suffix == "okfail":
        return {"ref": req.ref, "status": "FAILURE"}
    if suffix == "okslow":
        tasks.add_task(send_webhook, req.callback_url, req.ref, "SUCCESS")
        return {"ref": req.ref, "status": "PENDING"}
    return {"ref": req.ref, "status": "SUCCESS"}
```
```python title="upi-mock/tests/test_mock.py"
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def collect(vpa):
    return client.post("/collect", json={"ref": "pay-1", "amount_paise": 100, "vpa": vpa,
                                         "callback_url": "http://127.0.0.1:9/none"}).json()["status"]


def test_outcomes():
    assert collect("a@okbank") == "SUCCESS"
    assert collect("a@okfail") == "FAILURE"
    assert collect("a@okslow") == "PENDING"
```
@end

@concept The HTML frontend
@plain
One static page with a few lines of JavaScript: list products, add to cart, pay with a VPA. No build step, no framework.
@problem
Learners need to see the whole system work in a browser, but a React build chain would add a second topic to every pipeline file.
@does
- `fetch` calls go to the same origin under `/api/<service>/`; nginx forwards them, so there is no CORS to configure.
- A random `X-User-Id` is kept in `localStorage` as a stand-in for real login.
- `Idempotency-Key` is generated once per checkout click, so a retry cannot double-order.
- The page has no inline secrets and loads no third-party scripts, which keeps the content security policy simple.
@diagram flow
caption: Browser to services
nodes:
  - "index.html|static file|app"
  - "fetch api catalog|same origin|info"
  - "nginx|prefix routing|cp"
  - "Service|ClusterIP|ok"
@h web/index.html
```html title="web/index.html" nocheck
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>The Shop</title>
</head>
<body>
  <h1>The Shop</h1>
  <ul id="products"></ul>
  <h2>Cart</h2>
  <pre id="cart">empty</pre>
  <input id="vpa" placeholder="you@okbank">
  <button id="pay">Pay with UPI</button>
  <p id="result"></p>
  <script>
    const uid = localStorage.uid || (localStorage.uid = "u" + Math.random().toString(36).slice(2, 10));
    const h = { "X-User-Id": uid, "Content-Type": "application/json" };
    const api = (p, o = {}) => fetch("/api/" + p, { headers: h, ...o }).then(r => r.json());

    async function refresh() {
      const cart = await api("cart/cart");
      document.getElementById("cart").textContent = JSON.stringify(cart.items, null, 1);
    }
    async function load() {
      const items = await api("catalog/products");
      const ul = document.getElementById("products");
      for (const p of items) {
        const li = document.createElement("li");
        li.textContent = p.name + " Rs " + (p.price_paise / 100).toFixed(2) + " ";
        const b = document.createElement("button");
        b.textContent = "Add";
        b.onclick = async () => { await api("cart/cart/items/" + p.sku, { method: "PUT", body: JSON.stringify({ qty: 1 }) }); refresh(); };
        li.appendChild(b);
        ul.appendChild(li);
      }
      refresh();
    }
    document.getElementById("pay").onclick = async () => {
      const cart = await api("cart/cart");
      const items = Object.entries(cart.items).map(([sku, qty]) => ({ sku, qty }));
      const r = await fetch("/api/orders/orders", { method: "POST",
        headers: { ...h, "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ items, vpa: document.getElementById("vpa").value }) });
      document.getElementById("result").textContent = r.status + " " + JSON.stringify(await r.json());
      if (r.ok) await api("cart/cart", { method: "DELETE" });
      refresh();
    };
    load();
  </script>
</body>
</html>
```
@end

@concept nginx configuration for the web tier
@plain
nginx serves the static files and forwards `/api/<service>/` to the matching Kubernetes Service, removing the prefix.
@problem
The browser must talk to one origin. Exposing four services directly would need four load balancers and CORS rules.
@does
- `proxy_pass http://catalog:8000/;` with the trailing slash strips `/api/catalog/`.
- `/healthz` on the web tier returns 200 for probes.
- `server_tokens off` hides the version. Security headers are added once here.
- Runs as the unprivileged nginx image listening on 8080 (ports below 1024 need root).
- A regex `location` blocks `/internal` and `/metrics` paths at the edge.
@diagram flow
caption: Prefix routing
nodes:
  - "/|static files|plain"
  - "/api/catalog/|to catalog 8000|app"
  - "/api/cart/|to cart 8000|app"
  - "/api/orders/|to orders 8000|app"
@h web/nginx.conf
```nginx title="web/nginx.conf" nocheck
server {
  listen 8080;
  server_tokens off;
  root /usr/share/nginx/html;
  index index.html;

  add_header X-Content-Type-Options nosniff always;
  add_header X-Frame-Options DENY always;
  add_header Referrer-Policy no-referrer always;

  location = /healthz { return 200 "ok"; }

  # never expose internal or metrics paths at the edge
  location ~ ^/api/[a-z]+/(internal|metrics) { return 404; }

  location /api/catalog/ { proxy_pass http://catalog:8000/; proxy_read_timeout 5s; }
  location /api/cart/    { proxy_pass http://cart:8000/;    proxy_read_timeout 5s; }
  location /api/orders/  { proxy_pass http://orders:8000/;  proxy_read_timeout 10s; }

  location / { try_files $uri /index.html; }
}
```
:::note
The regex location returns 404 for `/internal/` and `/metrics` paths. The `/webhooks/upi` path of payments is not routed here; in production it needs its own public Ingress path, and NetworkPolicy limits who may reach the internal endpoints.
:::
@end
