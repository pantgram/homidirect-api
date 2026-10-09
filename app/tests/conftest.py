# ruff: noqa: E402
import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

# Provide deterministic settings before any app module is imported.
# Environment variables take priority over the .env file in pydantic-settings.
_TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "SUPABASE_URL": "https://test-project.supabase.co",
    "SUPABASE_JWT_SECRET": "",
    "SUPABASE_SERVICE_ROLE_KEY": "test-service-role-key",
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

import jwt as pyjwt
import pytest
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

# --- Make the Postgres-flavoured metadata compatible with the SQLite test DB ---

# date_built has a Postgres-only server default (EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER)
Listing.__table__.c.date_built.server_default = DefaultClause(text("CAST(strftime('%Y', 'now') AS INTEGER)"))

# Drop Postgres-only full-text-search GIN indexes (to_tsvector expressions)
for _table in Base.metadata.tables.values():
    for _index in list(_table.indexes):
        if any(isinstance(_expr, TextClause) for _expr in _index.expressions):
            _table.indexes.discard(_index)

API = "/api/v1"

# Secret used to sign Supabase-shaped test tokens. The real JWKS verifier in
# app.dependencies.auth is replaced (see mock_supabase_auth) so no network or
# Supabase keys are needed in tests.
TEST_AUTH_SECRET = "test-supabase-auth-secret-0123456789abcdef"


# --- Supabase Auth test doubles ---


def make_test_token(sub: str, email: str, role: str = "authenticated") -> str:
    now = datetime.now(timezone.utc)
    return pyjwt.encode(
        {
            "sub": sub,
            "email": email,
            "role": role,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
        },
        TEST_AUTH_SECRET,
        algorithm="HS256",
    )


def _fake_verify_supabase_jwt(token: str) -> dict:
    from app.utils.errors import UnauthorizedError

    try:
        payload = pyjwt.decode(token, TEST_AUTH_SECRET, algorithms=["HS256"])
    except pyjwt.PyJWTError:
        raise UnauthorizedError("Unauthorized")
    if payload.get("role") != "authenticated":
        raise UnauthorizedError("Unauthorized")
    return payload


@pytest.fixture(autouse=True)
def mock_supabase_auth(monkeypatch):
    monkeypatch.setattr("app.dependencies.auth.verify_supabase_jwt", _fake_verify_supabase_jwt)


# --- Helpers (plain functions, usable from any test module) ---


async def sync_user(
    client: AsyncClient,
    email: str = "user@example.com",
    role: str = "TENANT",
    first_name: str = "Test",
    last_name: str = "User",
    sub: str | None = None,
) -> dict:
    """Create the profile row for a Supabase-authenticated user (POST /auth/sync)
    and return {"user", "token", "sub", "email"}."""
    sub = sub or str(uuid.uuid4())
    token = make_test_token(sub, email)
    response = await client.post(
        f"{API}/auth/sync",
        json={"firstName": first_name, "lastName": last_name, "role": role},
        headers={"Authorization": f"Bearer {token}"},
    )
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
        supabase_user_id=uuid.uuid4(),
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
    token = make_test_token(str(user.supabase_user_id), user.email)
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


def slot_payload(listing_id: int, hours_from_now: float = 24, duration_hours: float = 1) -> dict:
    start = datetime.now(timezone.utc) + timedelta(hours=hours_from_now)
    end = start + timedelta(hours=duration_hours)
    return {"listingId": listing_id, "startTime": start.isoformat(), "endTime": end.isoformat()}


# --- Fixtures ---


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture(autouse=True)
def mock_external_services(monkeypatch):
    """Replace outbound e-mail, R2 storage and Supabase admin calls with mocks."""
    from app.api.v1 import listings as listings_api
    from app.services import booking as booking_service
    from app.services import verification as verification_service
    from app.utils import storage as storage_utils
    from app.utils import supabase_admin

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
    }

    monkeypatch.setattr(supabase_admin, "delete_auth_user", mocks["delete_auth_user"])
    monkeypatch.setattr(listings_api, "send_contact_owner_email", mocks["contact_owner"])
    monkeypatch.setattr(booking_service, "send_booking_created_email", mocks["booking_created"])
    monkeypatch.setattr(booking_service, "send_booking_confirmed_email", mocks["booking_confirmed"])
    monkeypatch.setattr(booking_service, "send_booking_declined_email", mocks["booking_declined"])
    monkeypatch.setattr(booking_service, "send_booking_cancelled_email", mocks["booking_cancelled"])
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
        dbapi_connection.create_function(
            "NOW", 0, lambda: datetime.now(timezone.utc).isoformat(sep=" ")
        )
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
