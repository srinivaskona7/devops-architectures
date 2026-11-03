---
title: Cart and orders services
minutes: 55
objectives:
  - Store carts in Redis with an expiry and a memory fallback for tests
  - Create orders with idempotency keys and compensation on failure
  - Call other services with timeouts and test the calls without a network
---
The cart and orders services reuse `config.py`, `logs.py` and `obs.py` from the catalog service. In a real repository, move the three shared files into a small internal package (for example `libs/shopcommon`) and install it in each image; the copies keep this walkthrough short.

@concept Cart service with Redis
@plain
A cart is a Redis hash per user: field is the SKU, value is the quantity. The key expires 7 days after the last change.
@problem
Carts are temporary, read often and written often. Putting them in the orders database wastes transactions and storage on data most shoppers abandon.
@does
- Key `cart:<user>` is a hash. `HSET` changes a line, `HDEL` removes it, `EXPIRE` refreshes the 7 day TTL (604,800 seconds).
- A `MemoryStore` with the same four methods is used when `REDIS_URL` is empty, so tests and local runs need no Redis.
- The user comes from the `X-User-Id` header. In real life an auth gateway sets it after verifying a token.
@diagram flow
caption: Cart write path
nodes:
  - "PUT cart item|sku and qty|app"
  - "HSET cart:user|field sku|cp"
  - "EXPIRE 7 days|refresh TTL|info"
  - "200 with cart|ok|ok"
@h store.py
```python title="services/cart/app/store.py"
import os

TTL_SECONDS = 7 * 24 * 3600


class MemoryStore:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, str]] = {}

    def hset(self, key: str, field: str, value: str) -> None:
        self.data.setdefault(key, {})[field] = value

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.data.get(key, {}))

    def hdel(self, key: str, field: str) -> None:
        self.data.get(key, {}).pop(field, None)

    def delete(self, key: str) -> None:
        self.data.pop(key, None)

    def expire(self, key: str, seconds: int) -> None:
        return None


def make_store():
    url = os.getenv("REDIS_URL", "")
    if not url:
        return MemoryStore()
    import redis

    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=1.0)
```
@end

@concept Cart routes and tests
@plain
Four endpoints: read the cart, set a line, remove a line, clear the cart.
@problem
Clients need a tiny, predictable API, and a bug in quantity handling (negative, huge) must be rejected at the edge.
@does
- Quantity is validated 0 to 100; zero removes the line.
- Redis timeouts surface as 503 through the readiness check, not as hangs, because `socket_timeout` is set.
- Tests run on the memory store.
@diagram flow
caption: Cart routes
nodes:
  - "GET cart|read all lines|plain"
  - "PUT cart items sku|set quantity|app"
  - "DELETE cart items sku|remove line|warn"
  - "DELETE cart|clear after order|bad"
@h main.py and test
```python title="services/cart/app/main.py"
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from . import logs, obs
from .config import settings
from .store import TTL_SECONDS, make_store

logs.setup(settings.log_level)
app = FastAPI(title="cart")
obs.install(app, "cart")
store = make_store()


class Line(BaseModel):
    qty: int = Field(ge=0, le=100)


def key(user: str) -> str:
    if not user:
        raise HTTPException(401, "X-User-Id required")
    return f"cart:{user}"


def view(user: str) -> dict:
    items = {sku: int(q) for sku, q in store.hgetall(key(user)).items()}
    return {"user": user, "items": items}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(response: Response) -> dict:
    try:
        store.hgetall("cart:_probe")
    except Exception:
        response.status_code = 503
        return {"status": "redis unavailable"}
    return {"status": "ready"}


@app.get("/cart")
def get_cart(x_user_id: str = Header(default="")) -> dict:
    return view(x_user_id)


@app.put("/cart/items/{sku}")
def put_item(sku: str, line: Line, x_user_id: str = Header(default="")) -> dict:
    k = key(x_user_id)
    if line.qty == 0:
        store.hdel(k, sku)
    else:
        store.hset(k, sku, str(line.qty))
        store.expire(k, TTL_SECONDS)
    return view(x_user_id)


@app.delete("/cart/items/{sku}")
def delete_item(sku: str, x_user_id: str = Header(default="")) -> dict:
    store.hdel(key(x_user_id), sku)
    return view(x_user_id)


@app.delete("/cart")
def clear(x_user_id: str = Header(default="")) -> dict:
    store.delete(key(x_user_id))
    return view(x_user_id)
```
```python title="services/cart/tests/test_cart.py"
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
H = {"X-User-Id": "u1"}


def test_add_update_remove():
    assert client.put("/cart/items/A", json={"qty": 2}, headers=H).json()["items"] == {"A": 2}
    assert client.put("/cart/items/A", json={"qty": 5}, headers=H).json()["items"] == {"A": 5}
    assert client.put("/cart/items/A", json={"qty": 0}, headers=H).json()["items"] == {}


def test_requires_user_and_validates_qty():
    assert client.get("/cart").status_code == 401
    assert client.put("/cart/items/A", json={"qty": 1000}, headers=H).status_code == 422


def test_clear_and_isolation():
    client.put("/cart/items/B", json={"qty": 1}, headers={"X-User-Id": "u2"})
    client.delete("/cart", headers={"X-User-Id": "u2"})
    assert client.get("/cart", headers={"X-User-Id": "u2"}).json()["items"] == {}
    assert client.get("/cart", headers=H).status_code == 200
```
:::note
Add `redis==5.2.*` to the cart requirements. The tests never import it because `REDIS_URL` is empty.
:::
@end

@concept Orders data model
@plain
Two tables: `orders` (one row per order) and `order_items` (the lines with the price at purchase time).
@problem
If an order stored only SKUs, a later price change would rewrite history and break accounting.
@does
- `orders.idem_key` is unique. A client that retries a failed network call with the same key gets the original order back instead of a duplicate.
- `status` is one of `pending`, `paid`, `failed`, `cancelled`.
- Totals and prices are integer paise.
@diagram layers
caption: Orders schema
layers:
  - {label: "orders", nodes: ["id|primary key|cp", "user_id|who|plain", "status|pending, paid, failed|warn", "total_paise|integer|plain", "idem_key|unique|ok"]}
  - {label: "order_items", nodes: ["order_id|foreign key|cp", "sku|product|plain", "qty|1 to 100|plain", "price_paise|at purchase|ok"]}
@h db.py and config.py
```python title="services/orders/app/db.py"
from sqlalchemy import ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    total_paise: Mapped[int] = mapped_column(Integer)
    idem_key: Mapped[str | None] = mapped_column(String(80), unique=True, nullable=True)
    items: Mapped[list["OrderItem"]] = relationship(back_populates="order", cascade="all")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    sku: Mapped[str] = mapped_column(String(40))
    qty: Mapped[int] = mapped_column(Integer)
    price_paise: Mapped[int] = mapped_column(Integer)
    order: Mapped[Order] = relationship(back_populates="items")


def make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
```
```python title="services/orders/app/config.py"
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    service_name: str = os.getenv("SERVICE_NAME", "orders")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    catalog_url: str = os.getenv("CATALOG_URL", "http://catalog:8000")
    payments_url: str = os.getenv("PAYMENTS_URL", "http://payments:8000")
    call_timeout: float = float(os.getenv("CALL_TIMEOUT_SECONDS", "3"))


settings = Settings()
```
@end

@concept Service clients with timeouts
@plain
Small functions wrap the HTTP calls to catalog and payments. Each has a timeout and turns failures into one clear exception.
@problem
A call without a timeout can hang a worker forever. A slow dependency then takes down the caller too (cascading failure).
@does
- A shared `httpx.Client` timeout of 3 seconds (`CALL_TIMEOUT_SECONDS`).
- `Upstream` is raised for network errors and 5xx answers, so the route returns 502 and compensates.
- Keeping calls in one module lets tests replace them without any network.
@diagram flow
caption: Failure is contained at the client
nodes:
  - "Route|orders|app"
  - "clients.py|3 second timeout|info"
  - "Dependency slow|catalog or payments|bad"
  - "502 and release stock|compensation|warn"
@h clients.py
```python title="services/orders/app/clients.py"
import httpx

from .config import settings


class Upstream(Exception):
    pass


class OutOfStock(Exception):
    pass


def _client() -> httpx.Client:
    return httpx.Client(timeout=settings.call_timeout)


def get_product(sku: str) -> dict | None:
    try:
        with _client() as c:
            r = c.get(f"{settings.catalog_url}/products/{sku}")
    except httpx.HTTPError as e:
        raise Upstream(str(e)) from e
    if r.status_code == 404:
        return None
    if r.status_code >= 500:
        raise Upstream(f"catalog {r.status_code}")
    return r.json()


def reserve(sku: str, qty: int) -> None:
    try:
        with _client() as c:
            r = c.post(f"{settings.catalog_url}/products/{sku}/reserve", json={"qty": qty})
    except httpx.HTTPError as e:
        raise Upstream(str(e)) from e
    if r.status_code == 409:
        raise OutOfStock(sku)
    if r.status_code >= 400:
        raise Upstream(f"catalog {r.status_code}")


def release(sku: str, qty: int) -> None:
    try:
        with _client() as c:
            c.post(f"{settings.catalog_url}/products/{sku}/release", json={"qty": qty})
    except httpx.HTTPError:
        pass  # best effort; a reconciliation job repairs leftovers


def collect(order_id: int, amount_paise: int, vpa: str) -> dict:
    try:
        with _client() as c:
            r = c.post(f"{settings.payments_url}/payments",
                       json={"order_id": order_id, "amount_paise": amount_paise, "vpa": vpa})
    except httpx.HTTPError as e:
        raise Upstream(str(e)) from e
    if r.status_code >= 500:
        raise Upstream(f"payments {r.status_code}")
    return r.json()
```
@end

@concept Creating an order with idempotency and compensation
@plain
The order route checks prices, reserves stock, saves a pending order, asks payments to collect, and then marks the order paid, failed or pending.
@problem
Several services are involved and there is no distributed transaction. If payment fails after stock was reserved, stock must be given back, and a retried request must not create a second order.
@does
- Same `Idempotency-Key` returns the existing order (HTTP 200).
- Reservations made so far are released if a later step fails (compensation, a simple saga).
- Payment answers: `SUCCESS` gives status paid, `FAILURE` gives failed and releases stock, `PENDING` leaves the order pending until the webhook arrives.
- Payments calls `POST /internal/orders/{id}/payment-result` to finish pending orders.
@diagram seq
caption: Failure path with compensation
actors: ["Client|caller|ext", "orders|service|app", "catalog|stock|app", "payments|collect|app"]
steps:
  - "0>1: POST /orders | req"
  - "1>2: reserve | req"
  - "2>1: ok | resp"
  - "1>3: collect | req"
  - "3>1: FAILURE | bad"
  - "1>2: release stock | req"
  - "1>0: 402 payment failed | bad"
@h main.py
```python title="services/orders/app/main.py"
from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from . import clients, logs, obs
from .config import settings
from .db import Base, Order, OrderItem, SessionLocal, engine

logs.setup(settings.log_level)
Base.metadata.create_all(engine)
app = FastAPI(title="orders")
obs.install(app, "orders")


class Line(BaseModel):
    sku: str
    qty: int = Field(gt=0, le=100)


class NewOrder(BaseModel):
    items: list[Line] = Field(min_length=1, max_length=50)
    vpa: str = Field(pattern=r"^[\w.\-]{2,64}@[A-Za-z]{2,32}$")


class PaymentResult(BaseModel):
    status: str


def to_dict(o: Order) -> dict:
    return {"id": o.id, "status": o.status, "total_paise": o.total_paise,
            "items": [{"sku": i.sku, "qty": i.qty, "price_paise": i.price_paise} for i in o.items]}


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


@app.post("/orders", status_code=201)
def create_order(body: NewOrder, response: Response, x_user_id: str = Header(default=""),
                 idempotency_key: str | None = Header(default=None)) -> dict:
    if not x_user_id:
        raise HTTPException(401, "X-User-Id required")
    if idempotency_key:
        with SessionLocal() as s:
            existing = s.scalar(select(Order).where(Order.idem_key == idempotency_key))
            if existing:
                response.status_code = 200
                return to_dict(existing)

    priced, reserved = [], []
    try:
        for line in body.items:
            product = clients.get_product(line.sku)
            if product is None:
                raise HTTPException(404, f"unknown sku {line.sku}")
            clients.reserve(line.sku, line.qty)
            reserved.append(line)
            priced.append((line, product["price_paise"]))
    except clients.OutOfStock as e:
        _release(reserved)
        raise HTTPException(409, f"out of stock {e}") from e
    except clients.Upstream as e:
        _release(reserved)
        raise HTTPException(502, "catalog unavailable") from e
    except HTTPException:
        _release(reserved)
        raise

    total = sum(line.qty * price for line, price in priced)
    with SessionLocal.begin() as s:
        order = Order(user_id=x_user_id, status="pending", total_paise=total, idem_key=idempotency_key)
        order.items = [OrderItem(sku=l.sku, qty=l.qty, price_paise=p) for l, p in priced]
        s.add(order)
        s.flush()
        order_id = order.id

    try:
        result = clients.collect(order_id, total, body.vpa)
    except clients.Upstream as e:
        _finish(order_id, "failed", reserved)
        raise HTTPException(502, "payments unavailable") from e

    status = result.get("status")
    if status == "SUCCESS":
        _finish(order_id, "paid", [])
    elif status == "FAILURE":
        _finish(order_id, "failed", reserved)
        raise HTTPException(402, "payment failed")
    with SessionLocal() as s:
        return to_dict(s.get(Order, order_id))


@app.get("/orders/{order_id}")
def get_order(order_id: int, x_user_id: str = Header(default="")) -> dict:
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if not o or o.user_id != x_user_id:
            raise HTTPException(404, "order not found")
        return to_dict(o)


@app.post("/internal/orders/{order_id}/payment-result")
def payment_result(order_id: int, body: PaymentResult) -> dict:
    with SessionLocal() as s:
        o = s.get(Order, order_id)
        if not o:
            raise HTTPException(404, "order not found")
        if o.status != "pending":
            return to_dict(o)
        lines = [Line(sku=i.sku, qty=i.qty) for i in o.items]
    if body.status == "SUCCESS":
        _finish(order_id, "paid", [])
    else:
        _finish(order_id, "failed", lines)
    with SessionLocal() as s:
        return to_dict(s.get(Order, order_id))


def _release(lines) -> None:
    for line in lines:
        clients.release(line.sku, line.qty)


def _finish(order_id: int, status: str, to_release) -> None:
    with SessionLocal.begin() as s:
        s.get(Order, order_id).status = status
    _release(to_release)
```
@end

@concept Orders tests without a network
@plain
Tests replace the functions in `clients.py` with fakes, so the whole saga runs in milliseconds.
@problem
Testing a multi-service flow with real services needs containers; that is slow and hides which step broke.
@does
- `monkeypatch` swaps `get_product`, `reserve`, `release` and `collect`.
- Covered cases: paid, payment failure with release, out of stock, pending then webhook, idempotent retry.
- Integration with the real services is tested in Docker Compose and in staging smoke tests.
@diagram flow
caption: Which test checks what
nodes:
  - "Happy path|status paid|ok"
  - "Payment fails|402 and release|bad"
  - "Out of stock|409|warn"
  - "Pending then webhook|paid later|info"
  - "Retry same key|same order id|app"
@h test_orders.py
```python title="services/orders/tests/test_orders.py"
import pytest
from fastapi.testclient import TestClient

from app import clients
from app.main import app

client = TestClient(app)
H = {"X-User-Id": "u1"}
BODY = {"items": [{"sku": "A", "qty": 2}], "vpa": "asha@okbank"}


@pytest.fixture
def fakes(monkeypatch):
    calls = {"release": [], "pay": "SUCCESS", "stock": 10}
    monkeypatch.setattr(clients, "get_product", lambda sku: {"sku": sku, "price_paise": 25000})

    def reserve(sku, qty):
        if qty > calls["stock"]:
            raise clients.OutOfStock(sku)

    monkeypatch.setattr(clients, "reserve", reserve)
    monkeypatch.setattr(clients, "release", lambda sku, qty: calls["release"].append((sku, qty)))
    monkeypatch.setattr(clients, "collect", lambda oid, amt, vpa: {"status": calls["pay"]})
    return calls


def test_paid_order_total(fakes):
    r = client.post("/orders", json=BODY, headers=H)
    assert r.status_code == 201
    assert r.json()["status"] == "paid" and r.json()["total_paise"] == 50000


def test_payment_failure_releases_stock(fakes):
    fakes["pay"] = "FAILURE"
    r = client.post("/orders", json=BODY, headers=H)
    assert r.status_code == 402 and fakes["release"] == [("A", 2)]


def test_out_of_stock(fakes):
    fakes["stock"] = 1
    assert client.post("/orders", json=BODY, headers=H).status_code == 409


def test_pending_then_webhook(fakes):
    fakes["pay"] = "PENDING"
    order = client.post("/orders", json=BODY, headers=H).json()
    assert order["status"] == "pending"
    done = client.post(f"/internal/orders/{order['id']}/payment-result", json={"status": "SUCCESS"})
    assert done.json()["status"] == "paid"


def test_idempotent_retry(fakes):
    h = {**H, "Idempotency-Key": "k-1"}
    first = client.post("/orders", json=BODY, headers=h)
    second = client.post("/orders", json=BODY, headers=h)
    assert second.status_code == 200 and second.json()["id"] == first.json()["id"]


def test_bad_vpa_rejected(fakes):
    bad = {**BODY, "vpa": "not-a-vpa"}
    assert client.post("/orders", json=bad, headers=H).status_code == 422
```
:::warn
Releasing stock is best effort. A pod killed between reserve and release leaks stock. The runbook chapter adds a reconciliation query for reservations older than 15 minutes with no matching order.
:::
@end
