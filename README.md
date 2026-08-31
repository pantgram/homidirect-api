# HomiDirect API

REST API for the HomiDirect real estate platform — property listings, visit bookings, listing verification, favorites, and geocoding, with Greek/English bilingual listing content.

Built with **FastAPI**, **SQLAlchemy 2.0 (async)**, and **PostgreSQL**. Packaged with [uv](https://docs.astral.sh/uv/), Dockerized, and covered by an async pytest suite.

## Features

- **Authentication** — email/password registration and login, JWT access (15 min) & refresh tokens (7 days) with revocation via `token_version`, password reset flow, Google OAuth 2.0
- **Users** — profile management, roles (`LANDLORD` / `TENANT` / `BOTH` / `ADMIN`), status handling (banned/suspended users blocked)
- **Listings** — full CRUD, paginated search with filters and sorting, stats, distinct cities, featured listings, bilingual (el/en) content, Postgres full-text search (English + Greek)
- **Listing images** — multipart uploads to Cloudflare R2 with magic-byte content validation and size limits
- **Verification** — ownership document uploads (utility bill, title deed, etc.), verification history, admin review queue (approve/reject with notes)
- **Favorites** — add/remove/check favorite listings, paginated favorites feed
- **Bookings** — visit booking between tenants and landlords, status lifecycle (pending → confirmed/declined/cancelled) with notification emails, linked to availability slots
- **Availability slots** — bookable time windows per listing with overlap checks
- **Geocoding** — Geoapify-powered search, address autocomplete, and reverse geocoding with a DB cache layer
- **Cross-cutting** — camelCase JSON responses (middleware + Pydantic aliases), consistent error format, slowapi rate limiting on auth endpoints, CORS

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) + Alembic migrations |
| Database | PostgreSQL (asyncpg); SQLite (aiosqlite) in tests |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | python-jose (JWT), passlib/bcrypt, Google OAuth |
| Storage | Cloudflare R2 (boto3) |
| Email | aiosmtplib |
| Geocoding | Geoapify |
| Tooling | uv, ruff, pytest + pytest-asyncio |

## Getting Started

### Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL (or a connection string to one)
- Cloudflare R2, SMTP, Google OAuth, and Geoapify credentials for full functionality

### Installation

```bash
# Clone
git clone <repository-url>
cd homidirect-api

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# edit .env with your values
```

### Running

```bash
# Development
uv run uvicorn app.main:app --reload --port 5000

# Docker
docker build -t homidirect-api .
docker run -p 5000:5000 --env-file .env homidirect-api
```

The API is served at `http://localhost:5000/api/v1`, with interactive docs (Swagger UI) at `/docs` and ReDoc at `/redoc`.

### Database Migrations

```bash
uv run alembic upgrade head      # apply all migrations
uv run alembic revision --autogenerate -m "description"
```

Migrations run against `DATABASE_URL` from your `.env` (async engine).

### Testing

Tests run against an in-memory SQLite database with email, R2 storage, and rate limiting mocked — no external services required.

```bash
uv run pytest
```

### Linting

```bash
uv run ruff check .
uv run ruff format .
```

## API Overview

All routes are prefixed with `/api/v1`. Authenticated routes expect `Authorization: Bearer <access_token>`.

| Domain | Endpoints |
|---|---|
| Health | `GET /health` |
| Auth | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/forgot-password`, `POST /auth/reset-password` |
| Google Auth | `GET /auth/google/`, `GET /auth/google/callback`, `POST /auth/google/exchange` |
| Users | `GET /users/me`, `GET /users/{id}`, `PATCH /users/{id}`, `DELETE /users/{id}` |
| Listings | `GET /listings`, `GET /listings/search`, `GET /listings/stats`, `GET /listings/cities`, `GET /listings/my-listings`, `GET/POST /listings`, `GET/PATCH/DELETE /listings/{id}`, `POST /listings/{id}/contact` |
| Listing Images | `GET/POST /listings/{id}/images`, `DELETE /listings/{id}/images/{image_id}` |
| Verification | `GET /listings/{id}/verification`, `GET /listings/{id}/verification/documents`, `GET /listings/{id}/verification/history`, `POST /listings/{id}/verification/documents`, `DELETE /listings/{id}/verification/documents/{document_id}` |
| Admin Verification | `GET /admin/verifications/pending`, `POST /admin/verifications/{id}/verification/review` |
| Favorites | `GET /favorites`, `GET /favorites/ids`, `GET /favorites/{id}/check`, `POST/DELETE /favorites/{id}` |
| Bookings | `GET/POST /bookings`, `GET/PATCH/DELETE /bookings/{id}`, `GET /bookings/listing/{id}` |
| Availability Slots | `GET/POST /availability-slots`, `GET /availability-slots/listing/{id}`, `GET /availability-slots/listing/{id}/available`, `GET/PATCH/DELETE /availability-slots/{id}` |
| Geocoding | `GET /geocoding/search`, `GET /geocoding/address-search`, `GET /geocoding/reverse` |

Full request/response schemas are available in the OpenAPI docs at `/docs`.

## Project Structure

```
├── alembic/              # Async Alembic migrations
├── app/
│   ├── api/v1/           # Route handlers (one module per domain)
│   ├── config/           # Settings, database engine, rate limiter
│   ├── dependencies/     # Auth dependencies (JWT, RBAC, ownership checks)
│   ├── middleware/       # camelCase response middleware
│   ├── models/           # SQLAlchemy models and enums
│   ├── schemas/          # Pydantic schemas (CamelModel base)
│   ├── services/         # Business logic (one module per domain)
│   ├── tests/            # Pytest suite (SQLite, mocked externals)
│   └── utils/            # Errors, hashing, R2 storage, email, validation
├── Dockerfile
├── alembic.ini
├── pyproject.toml
└── uv.lock
```

## Environment Variables

See [.env.example](.env.example) for all variables:

| Variable | Purpose |
|---|---|
| `PORT` | Server port (default 5000) |
| `DATABASE_URL` | PostgreSQL connection string (required) |
| `JWT_SECRET` | JWT signing secret (required) |
| `NODE_ENV` | Environment name |
| `R2_*` | Cloudflare R2 credentials, bucket, public URL |
| `SMTP_*`, `EMAIL_FROM` | Outbound email (default Zoho) |
| `GOOGLE_CLIENT_ID/SECRET/CALLBACK_URL` | Google OAuth app |
| `GEOAPIFY_API_KEY` | Geoapify geocoding |

## License

Distributed under the [GPL-3.0 License](LICENSE).
