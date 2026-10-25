# ruff: noqa: E402
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

# Provide deterministic settings before any app module is imported.
# Environment variables take priority over the .env file in pydantic-settings.
_TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "CLERK_SECRET_KEY": "sk_test_dummy_secret_key",
    "CLERK_JWT_KEY": "",
    "CLERK_AUTHORIZED_PARTIES": "",
    "CLERK_WEBHOOK_SECRET": "",
    "NODE_ENV": "test",
    "R2_ACCOUNT_ID": "test-account",
    "R2_ACCESS_KEY_ID": "test-key",
    "R2_SECRET_ACCESS_KEY": "test-secret",
    "R2_BUCKET_NAME": "test-bucket",
    "R2_PUBLIC_URL": "http://localhost:9000/test-bucket",
    "SMTP_HOST": "localhost",
    "SMTP_PORT": "1025",
    "SMTP_USER": "",
    "SMTP_PASS": "",
}
for _key, _value in _TEST_ENV.items():
    os.environ.setdefault(_key, _value)

import httpx
import jwt as pyjwt
import pytest
from clerk_backend_api import ClerkBaseError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import DefaultClause
from sqlalchemy.sql.elements import TextClause

import app.models  # noqa: F401  (register all models on Base.metadata)
from app.config.database import Base, get_db
from app.config.limiter import limiter
from app.main import app
from app.models.listing import Listing
from app.models.user import User
from app.schemas.listing import MAX_YEAR_BUILT, MIN_YEAR_BUILT

# --- Make the Postgres-flavoured metadata compatible with the SQLite test DB ---

# date_built has a Postgres-only server default (EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER)
Listing.__table__.c.date_built.server_default = DefaultClause(text("CAST(strftime('%Y', 'now') AS INTEGER)"))

# The date_built CHECK constraint uses Postgres-only EXTRACT(); rewrite its sqltext for SQLite,
# which also forbids non-deterministic functions (strftime) inside CHECK constraints. The test
# DB is ephemeral (per-test in-memory), so static bounds matching the schema constants are fine.
for _constraint in Listing.__table__.constraints:
    if getattr(_constraint, "name", None) == "date_built":
        _constraint.sqltext = text(f"date_built >= {MIN_YEAR_BUILT} AND date_built <= {MAX_YEAR_BUILT}")

# Drop Postgres-only full-text-search GIN indexes (to_tsvector expressions)
for _table in Base.metadata.tables.values():
    for _index in list(_table.indexes):
        if any(isinstance(_expr, TextClause) for _expr in _index.expressions):
            _table.indexes.discard(_index)

API = "/api/v1"

# Secret used to sign Clerk-shaped test tokens. The real Clerk verifier in
# app.dependencies.auth is replaced (see mock_clerk_auth) so no network, SDK or
# Clerk keys are needed in tests.
TEST_AUTH_SECRET = "test-clerk-auth-secret-0123456789abcdef"


# --- Clerk Auth test doubles ---


# Registry of expected Clerk Backend API profiles, keyed by clerk_user_id.
# sync_user registers the profile here; the fetch_clerk_user mock consumes it,
# mirroring the real flow where profile data comes from the Backend API call.
_clerk_user_registry: dict[str, dict] = {}


def make_test_token(sub: str, email: str, user_metadata: dict | None = None) -> str:
    """Sign a Clerk-shaped session token (sub="user_<hex>", azp, iat/exp) with
    HS256. Claims are NOT the profile source: profile data travels through the
    mocked Clerk Backend API, mirroring the real flow.
    """
    now = datetime.now(timezone.utc)
    claims = {
        "sub": sub,
        "email": email,
        "azp": "http://localhost:5173",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
    }
    if user_metadata is not None:
        claims["user_metadata"] = user_metadata
    return pyjwt.encode(claims, TEST_AUTH_SECRET, algorithm="HS256")


def _fake_authenticate_clerk_request(request) -> dict:
    from app.utils.errors import UnauthorizedError

    bearer = request.headers.get("Authorization")
    if not bearer or not bearer.startswith("Bearer "):
        raise UnauthorizedError("Unauthorized")
    token = bearer.removeprefix("Bearer ")
    try:
        payload = pyjwt.decode(token, TEST_AUTH_SECRET, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        raise UnauthorizedError("Unauthorized")
    return payload


@pytest.fixture(autouse=True)
def mock_clerk_auth(monkeypatch):
    monkeypatch.setattr("app.dependencies.auth.authenticate_clerk_request", _fake_authenticate_clerk_request)


# --- Helpers (plain functions, usable from any test module) ---


async def sync_user(
    client: AsyncClient,
    email: str = "user@example.com",
    role: str = "TENANT",
    first_name: str = "Test",
    last_name: str = "User",
    sub: str | None = None,
) -> dict:
    """Create the profile row for a Clerk-authenticated user (POST /auth/sync)
    and return {"user", "token", "sub", "email"}.

    Names travel through the mocked Clerk Backend API (fetch_clerk_user),
    exactly like the real flow; the desired role travels in the JSON body.
    """
    sub = sub or f"user_{uuid.uuid4().hex}"
    _clerk_user_registry[sub] = {"email": email, "first_name": first_name, "last_name": last_name}
    token = make_test_token(sub, email)
    response = await client.post(f"{API}/auth/sync", json={"role": role}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    return {"user": response.json()["user"], "token": token, "sub": sub, "email": email}


async def create_db_user(
    session,
    email: str = "admin@example.com",
    role: str = "ADMIN",
    status: str = "ACTIVE",
) -> User:
    user = User(
        email=email,
        clerk_user_id=f"user_{uuid.uuid4().hex}",
        first_name="Db",
        last_name="User",
        role=role,
        status=status,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def auth_headers_for(user: User) -> dict:
    token = make_test_token(user.clerk_user_id, user.email)
    return {"Authorization": f"Bearer {token}"}


def headers_from_tokens(sync_data: dict) -> dict:
    return {"Authorization": f"Bearer {sync_data['token']}"}


def listing_payload(**overrides) -> dict:
    payload = {
        "price": 850.0,
        "city": "Athens",
        "postalCode": "10431",
        "propertyType": "apartment",
        "area": 75.0,
        "bedrooms": 2,
        "bathrooms": 1,
        "floor": "2nd",
        "levels": 1,
        "kitchens": 1,
        "dateBuilt": 2015,
        "dateAvailable": "2026-10-01",
        "country": "Greece",
        "titleEl": "Ωραίο διαμέρισμα",
        "titleEn": "Nice apartment",
        "descriptionEl": "Φωτεινό διαμέρισμα στο κέντρο",
        "landlordId": 0,
        "landlordPhone": "+306900000000",
        "publicationStatus": "ACTIVE",
    }
    payload.update(overrides)
    return payload


async def create_listing(client: AsyncClient, headers: dict, **overrides) -> dict:
    response = await client.post(f"{API}/listings/", json=listing_payload(**overrides), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["listing"]


def slot_payload(listing_id: int, hours_from_now: float = 24, type: str = "REMOTE", **extra) -> dict:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    payload = {"listingId": listing_id, "startTime": start.isoformat(), "type": type}
    payload.update(extra)
    return payload


# --- Fixtures ---


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture(autouse=True)
def mock_external_services(monkeypatch):
    """Replace outbound e-mail, R2 storage, Clerk Backend API and webhook
    signature verification calls with mocks."""
    from app.api.v1 import listings as listings_api
    from app.api.v1 import webhooks as webhooks_api
    from app.services import time_slot as time_slot_service
    from app.services import verification as verification_service
    from app.utils import clerk_admin
    from app.utils import storage as storage_utils

    async def _fake_fetch_clerk_user(clerk_user_id: str) -> dict:
        # Registry-backed: sync_user registers expected profile data before
        # POSTing, mirroring the real Backend API round-trip.
        profile = _clerk_user_registry.get(clerk_user_id)
        if profile is None:
            raise ClerkBaseError("Not Found", raw_response=httpx.Response(404))
        return dict(profile)

    mocks = {
        "delete_auth_user": AsyncMock(return_value=True),
        "contact_owner": AsyncMock(),
        "booking_created": AsyncMock(),
        "booking_confirmed": AsyncMock(),
        "booking_declined": AsyncMock(),
        "booking_cancelled": AsyncMock(),
        "upload_to_r2": MagicMock(side_effect=lambda key, data, mime: f"http://localhost:9000/test-bucket/{key}"),
        "delete_from_r2": MagicMock(),
        "copy_in_r2": MagicMock(side_effect=lambda old, new: f"http://localhost:9000/test-bucket/{new}"),
        "verify_webhook": MagicMock(side_effect=lambda payload, headers: json.loads(payload)),
    }

    monkeypatch.setattr(clerk_admin, "fetch_clerk_user", _fake_fetch_clerk_user)
    monkeypatch.setattr(clerk_admin, "delete_auth_user", mocks["delete_auth_user"])
    monkeypatch.setattr(webhooks_api, "verify_webhook", mocks["verify_webhook"])
    monkeypatch.setattr(listings_api, "send_contact_owner_email", mocks["contact_owner"])
    monkeypatch.setattr(time_slot_service, "send_booking_created_email", mocks["booking_created"])
    monkeypatch.setattr(time_slot_service, "send_booking_confirmed_email", mocks["booking_confirmed"])
    monkeypatch.setattr(time_slot_service, "send_booking_declined_email", mocks["booking_declined"])
    monkeypatch.setattr(time_slot_service, "send_booking_cancelled_email", mocks["booking_cancelled"])
    monkeypatch.setattr(verification_service, "upload_to_r2", mocks["upload_to_r2"])
    monkeypatch.setattr(verification_service, "delete_from_r2", mocks["delete_from_r2"])
    monkeypatch.setattr(storage_utils, "upload_to_r2", mocks["upload_to_r2"])
    monkeypatch.setattr(storage_utils, "delete_from_r2", mocks["delete_from_r2"])
    monkeypatch.setattr(storage_utils, "copy_in_r2", mocks["copy_in_r2"])
    return mocks


@pytest.fixture
async def db_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _configure_sqlite(dbapi_connection, _):
        dbapi_connection.create_function("NOW", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" "))
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(db_engine):
    return async_sessionmaker(db_engine, expire_on_commit=False)


@pytest.fixture
async def session(session_factory):
    async with session_factory() as db:
        yield db


@pytest.fixture
async def client(session_factory):
    async def override_get_db():
        async with session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    class _NoReraiseASGI:
        """Starlette's ServerErrorMiddleware re-raises the exception after sending the
        500 response; httpx.ASGITransport would surface it in the test. Swallow it so
        tests can assert on the masked 500 response (response is already sent)."""

        def __init__(self, asgi_app):
            self._asgi_app = asgi_app

        async def __call__(self, scope, receive, send):
            try:
                await self._asgi_app(scope, receive, send)
            except Exception:
                pass

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=_NoReraiseASGI(app))
    async with AsyncClient(transport=transport, base_url="http://testserver") as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
async def landlord(client):
    return await sync_user(client, email="landlord@example.com", role="LANDLORD")


@pytest.fixture
async def landlord_headers(landlord):
    return headers_from_tokens(landlord)


@pytest.fixture
async def tenant(client):
    return await sync_user(client, email="tenant@example.com", role="TENANT")


@pytest.fixture
async def tenant_headers(tenant):
    return headers_from_tokens(tenant)


@pytest.fixture
async def listing(client, landlord_headers):
    return await create_listing(client, landlord_headers)


@pytest.fixture
async def admin(session):
    return await create_db_user(session, email="admin@example.com", role="ADMIN")


@pytest.fixture
def admin_headers(admin):
    return auth_headers_for(admin)
