---
title: Application core and the catalog service
minutes: 55
objectives:
  - Build the shared service skeleton with config, logging, health and metrics
  - Write the catalog service with an atomic stock reservation
  - Understand the 12-factor choices that make the service easy to operate
---
The Shop services share one skeleton. Each service is a small FastAPI app of fewer than 150 lines. The code below is complete; copy it into `services/catalog/app/` to follow along. Python 3.12 is assumed.

@concept Service skeleton and dependencies
@plain
Every service has the same shape: a settings object read from environment variables, a database engine, health endpoints, a metrics endpoint and a JSON log line per request.
@problem
Services that each invent their own config, health checks and logging are painful to deploy, probe and monitor.
@does
- Configuration comes only from environment variables (12-factor), so the same image runs in every environment.
- `/healthz` says the process is alive. `/readyz` says it can reach its dependencies. Kubernetes probes use them.
- `/metrics` exposes Prometheus counters and histograms.
- Pinned dependencies make builds repeatable.
@diagram layers
caption: What each service contains
layers:
  - {label: "HTTP layer", nodes: ["Routes|business endpoints|app", "Health|healthz and readyz|ok", "Metrics|prometheus client|info"]}
  - {label: "Core", nodes: ["Settings|environment variables|plain", "Logging|JSON to stdout|plain"]}
  - {label: "Data", nodes: ["SQLAlchemy engine|Postgres or SQLite in tests|cp"]}
@h requirements.txt
```text title="services/catalog/requirements.txt" nocheck
fastapi==0.115.*
uvicorn[standard]==0.32.*
sqlalchemy==2.0.*
psycopg[binary]==3.2.*
prometheus-client==0.21.*
httpx==0.27.*
pytest==8.3.*
```
Check the current releases and pin exact versions with a lock file (pip-tools or uv) in your own repository.
@end

@concept Settings from the environment
@plain
A small class that reads every setting from environment variables with safe defaults for local work.
@problem
Hard-coded database URLs and secrets force a rebuild per environment and leak into Git.
@does
- Uses a frozen dataclass, so settings cannot change at runtime.
- `DATABASE_URL` defaults to in-memory SQLite, which makes unit tests need no database.
- Secrets arrive as env vars from a Kubernetes Secret (see the Kustomize files), never from the image.
@diagram flow
caption: One image, many environments
nodes:
  - "Image|same bytes everywhere|app"
  - "Env vars|from ConfigMap and Secret|info"
  - "Settings object|read at start|plain"
  - "Behaviour|per environment|ok"
@h config.py
```python title="services/catalog/app/config.py"
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    service_name: str = os.getenv("SERVICE_NAME", "catalog")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")


settings = Settings()
```
@end

@concept Structured JSON logging
@plain
Each log line is one JSON object with a timestamp, level, message and request fields.
@problem
Free text logs cannot be filtered by field in Loki or Elasticsearch, and multi-line stack traces break log shippers.
@does
- A tiny formatter writes JSON to stdout; the container runtime and the log agent collect it (see the ELK folder).
- A middleware logs method, path, status and duration for every request.
- Never log card numbers, UPI IDs in full or tokens.
@diagram flow
caption: Log path
nodes:
  - "App|JSON to stdout|app"
  - "Container runtime|node log file|plain"
  - "Agent|Promtail or Fluent Bit|info"
  - "Loki or Elasticsearch|search|ok"
@h logs.py
```python title="services/catalog/app/logs.py"
import json
import logging
import sys
import time


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "msg": record.getMessage(),
            "logger": record.name,
        }
        extra = getattr(record, "fields", None)
        if extra:
            data.update(extra)
        return json.dumps(data)


def setup(level: str = "INFO") -> logging.Logger:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    return logging.getLogger("shop")
```
@end

@concept Database model and engine
@plain
One table, `products`, with integer price in paise and an integer stock count.
@problem
Floating point money produces rounding errors, and unconstrained stock can go negative.
@does
- Price is stored as an integer number of paise (Rs 499.00 is 49900).
- A `CHECK (stock >= 0)` constraint is a last line of defence against overselling.
- SQLAlchemy 2 typed models keep the code short; migrations in production use Alembic (not shown, keep SQL migrations in the repo).
@diagram flow
caption: Data in the catalog database
nodes:
  - "products|sku, name, price_paise, stock|cp"
  - "Index|unique on sku|info"
  - "Constraint|stock never negative|ok"
@h db.py
```python title="services/catalog/app/db.py"
from sqlalchemy import CheckConstraint, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (CheckConstraint("stock >= 0", name="stock_non_negative"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    price_paise: Mapped[int] = mapped_column(Integer)
    stock: Mapped[int] = mapped_column(Integer, default=0)


def make_engine(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    return create_engine(url, pool_size=5, max_overflow=5, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(engine, expire_on_commit=False)
```
@end

@concept Metrics and request middleware
@plain
One middleware times every request, counts it by route and status, and writes the JSON log line.
@problem
Without request metrics there is nothing to alert on, no SLO and no dashboard (see the Monitoring folder).
@does
- `http_requests_total{service,method,path,status}` is a counter. `http_request_duration_seconds` is a histogram.
- The path label uses the route template such as `/products/{sku}`, never the raw URL. Raw URLs with IDs would create unlimited label values and overload Prometheus (cardinality).
- The same file is copied into every service.
@diagram seq
caption: What the middleware does per request
actors: ["Client|caller|ext", "Middleware|obs.py|app", "Route|handler|app", "Prometheus|scrapes metrics|cp"]
steps:
  - "0>1: request | req"
  - "1>2: call handler | req"
  - "2>1: response | resp"
  - "note 1..1: count, time, log"
  - "1>0: response | resp"
  - "3>1: GET metrics | req"
@h obs.py
```python title="services/catalog/app/obs.py"
import logging
import time

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQS = Counter("http_requests_total", "HTTP requests", ["service", "method", "path", "status"])
LAT = Histogram("http_request_duration_seconds", "HTTP latency", ["service", "path"])
log = logging.getLogger("shop")


def install(app: FastAPI, service: str) -> None:
    @app.middleware("http")
    async def observe(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        took = time.perf_counter() - start
        route = request.scope.get("route")
        path = route.path if route else "unmatched"
        REQS.labels(service, request.method, path, str(response.status_code)).inc()
        LAT.labels(service, path).observe(took)
        log.info("request", extra={"fields": {
            "service": service, "method": request.method, "path": path,
            "status": response.status_code, "ms": round(took * 1000, 1)}})
        return response

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
```
@end

@concept Catalog routes and atomic stock reservation
@plain
Endpoints to create, list and read products, and to reserve or release stock.
@problem
Two shoppers buying the last item at the same moment must not both succeed. A read-then-write in Python has a race.
@does
- Reservation is one SQL statement: `UPDATE products SET stock = stock - :qty WHERE sku = :sku AND stock >= :qty`. The database applies it atomically; zero rows changed means not enough stock.
- Returns 404 for an unknown SKU and 409 for insufficient stock.
- Release adds the quantity back when a payment fails.
- `/readyz` runs `SELECT 1`; `/healthz` does not touch the database, so a database outage does not restart every pod.
@diagram flow
caption: Reserve is one atomic statement
nodes:
  - "POST reserve|sku and qty|app"
  - "UPDATE ... WHERE stock >= qty|one statement|cp"
  - "1 row changed|reserved, 200|ok"
  - "0 rows changed|409 conflict|bad"
@h main.py
```python title="services/catalog/app/main.py"
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, text, update

from . import logs, obs
from .config import settings
from .db import Base, Product, SessionLocal, engine

logs.setup(settings.log_level)
Base.metadata.create_all(engine)
app = FastAPI(title="catalog")
obs.install(app, settings.service_name)


class ProductIn(BaseModel):
    sku: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)
    price_paise: int = Field(gt=0)
    stock: int = Field(ge=0, default=0)


class Qty(BaseModel):
    qty: int = Field(gt=0, le=100)


def as_dict(p: Product) -> dict:
    return {"sku": p.sku, "name": p.name, "price_paise": p.price_paise, "stock": p.stock}


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


@app.post("/products", status_code=201)
def create_product(body: ProductIn) -> dict:
    with SessionLocal.begin() as s:
        if s.scalar(select(Product).where(Product.sku == body.sku)):
            raise HTTPException(409, "sku exists")
        p = Product(**body.model_dump())
        s.add(p)
        s.flush()
        return as_dict(p)


@app.get("/products")
def list_products(q: str = "", limit: int = 50) -> list[dict]:
    stmt = select(Product).order_by(Product.sku).limit(min(limit, 100))
    if q:
        stmt = stmt.where(Product.name.ilike(f"%{q}%"))
    with SessionLocal() as s:
        return [as_dict(p) for p in s.scalars(stmt)]


@app.get("/products/{sku}")
def get_product(sku: str) -> dict:
    with SessionLocal() as s:
        p = s.scalar(select(Product).where(Product.sku == sku))
        if not p:
            raise HTTPException(404, "unknown sku")
        return as_dict(p)


@app.post("/products/{sku}/reserve")
def reserve(sku: str, body: Qty) -> dict:
    with SessionLocal.begin() as s:
        if not s.scalar(select(Product.id).where(Product.sku == sku)):
            raise HTTPException(404, "unknown sku")
        changed = s.execute(
            update(Product)
            .where(Product.sku == sku, Product.stock >= body.qty)
            .values(stock=Product.stock - body.qty)
        ).rowcount
        if changed == 0:
            raise HTTPException(409, "insufficient stock")
    return {"sku": sku, "reserved": body.qty}


@app.post("/products/{sku}/release")
def release(sku: str, body: Qty) -> dict:
    with SessionLocal.begin() as s:
        changed = s.execute(
            update(Product).where(Product.sku == sku).values(stock=Product.stock + body.qty)
        ).rowcount
        if changed == 0:
            raise HTTPException(404, "unknown sku")
    return {"sku": sku, "released": body.qty}
```
@end

@concept Catalog tests with pytest
@plain
Fast tests that run against in-memory SQLite through FastAPI's test client. No containers needed.
@problem
If tests need a running database, developers skip them and CI becomes slow and flaky.
@does
- `pytest.ini` puts the service folder on the import path.
- Tests cover create, duplicate, search, successful reserve, over-reserve and release.
- The same suite runs in CI before the image is built (see the pipeline files).
- An integration test against real Postgres runs in Compose and in staging (smoke tests).
@diagram flow
caption: Test pyramid for one service
nodes:
  - "Unit and API tests|SQLite, seconds|ok"
  - "Integration|Compose with Postgres|info"
  - "Smoke|staging after deploy|warn"
  - "Load|k6 before release|app"
@h Tests
```ini title="services/catalog/pytest.ini" nocheck
[pytest]
pythonpath = .
testpaths = tests
```
```python title="services/catalog/tests/test_catalog.py"
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def make(sku="TSHIRT", stock=5):
    return client.post("/products", json={"sku": sku, "name": "Cotton T-shirt",
                                          "price_paise": 49900, "stock": stock})


def test_create_and_get():
    assert make("A1").status_code == 201
    r = client.get("/products/A1")
    assert r.status_code == 200 and r.json()["price_paise"] == 49900


def test_duplicate_sku_conflicts():
    make("A2")
    assert make("A2").status_code == 409


def test_search_by_name():
    make("A3")
    names = [p["sku"] for p in client.get("/products", params={"q": "cotton"}).json()]
    assert "A3" in names


def test_reserve_then_oversell_is_rejected():
    make("A4", stock=5)
    assert client.post("/products/A4/reserve", json={"qty": 3}).status_code == 200
    assert client.post("/products/A4/reserve", json={"qty": 3}).status_code == 409
    assert client.get("/products/A4").json()["stock"] == 2


def test_release_restores_stock():
    make("A5", stock=1)
    client.post("/products/A5/reserve", json={"qty": 1})
    client.post("/products/A5/release", json={"qty": 1})
    assert client.get("/products/A5").json()["stock"] == 1


def test_health_and_metrics():
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").status_code == 200
    assert b"http_requests_total" in client.get("/metrics").content
```
```bash title="Run them" lab
cd services/catalog && python -m pytest -q
```
:::tip
Create `services/catalog/app/__init__.py` as an empty file so `app` is a package.
:::
@end
