# ruff: noqa: E402
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

# Provide deterministic settings before any app module is imported.
# Environment variables take priority over the .env file in pydantic-settings.
_TEST_ENV = {
    "DATABASE_URL": "postgresql+asyncpg://test:test@localhost:5432/test",
    "JWT_SECRET": "test-jwt-secret",
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
from app.dependencies.auth import create_access_token
from app.main import app
from app.models.listing import Listing
from app.models.user import User
from app.utils.hash import hash_password

# --- Make the Postgres-flavoured metadata compatible with the SQLite test DB ---

# date_built has a Postgres-only server default (EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER)
Listing.__table__.c.date_built.server_default = DefaultClause(text("CAST(strftime('%Y', 'now') AS INTEGER)"))

# Drop Postgres-only full-text-search GIN indexes (to_tsvector expressions)
for _table in Base.metadata.tables.values():
    for _index in list(_table.indexes):
        if any(isinstance(_expr, TextClause) for _expr in _index.expressions):
            _table.indexes.discard(_index)

API = "/api/v1"

VALID_PASSWORD = "Password123"


# --- Helpers (plain functions, usable from any test module) ---


async def register_user(
    client: AsyncClient,
    email: str = "user@example.com",
    password: str = VALID_PASSWORD,
    role: str = "TENANT",
    first_name: str = "Test",
    last_name: str = "User",
) -> dict:
    response = await client.post(
        f"{API}/auth/register",
        json={
            "firstName": first_name,
            "lastName": last_name,
            "email": email,
            "password": password,
            "role": role,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def login_user(client: AsyncClient, email: str, password: str) -> dict:
    response = await client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


async def create_db_user(
    session,
    email: str = "admin@example.com",
    password: str = VALID_PASSWORD,
    role: str = "ADMIN",
    status: str = "ACTIVE",
) -> User:
    user = User(
        email=email,
        password=hash_password(password),
        first_name="Db",
        last_name="User",
        role=role,
        status=status,
        auth_provider="EMAIL",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


def auth_headers_for(user: User, token_version: int = 0) -> dict:
    token = create_access_token(
        {"id": user.id, "email": user.email, "role": user.role, "token_version": token_version}
    )
    return {"Authorization": f"Bearer {token}"}


def headers_from_tokens(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['accessToken']}"}


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
    """Replace outbound e-mail and R2 storage calls with mocks."""
    from app.api.v1 import listings as listings_api
    from app.services import auth as auth_service
    from app.services import booking as booking_service
    from app.services import verification as verification_service
    from app.utils import storage as storage_utils

    mocks = {
        "password_reset": AsyncMock(),
        "contact_owner": AsyncMock(),
        "booking_created": AsyncMock(),
        "booking_confirmed": AsyncMock(),
        "booking_declined": AsyncMock(),
        "booking_cancelled": AsyncMock(),
        "upload_to_r2": MagicMock(side_effect=lambda key, data, mime: f"http://localhost:9000/test-bucket/{key}"),
        "delete_from_r2": MagicMock(),
        "copy_in_r2": MagicMock(side_effect=lambda old, new: f"http://localhost:9000/test-bucket/{new}"),
    }

    monkeypatch.setattr(auth_service, "send_password_reset_email", mocks["password_reset"])
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
    data = await register_user(client, email="landlord@example.com", role="LANDLORD")
    return data


@pytest.fixture
async def landlord_headers(landlord):
    return headers_from_tokens(landlord["token"])


@pytest.fixture
async def tenant(client):
    data = await register_user(client, email="tenant@example.com", role="TENANT")
    return data


@pytest.fixture
async def tenant_headers(tenant):
    return headers_from_tokens(tenant["token"])


@pytest.fixture
async def listing(client, landlord_headers):
    return await create_listing(client, landlord_headers)


@pytest.fixture
async def admin(session):
    return await create_db_user(session, email="admin@example.com", role="ADMIN")


@pytest.fixture
def admin_headers(admin):
    return auth_headers_for(admin)
