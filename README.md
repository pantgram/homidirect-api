# HomiDirect API

REST API for the HomiDirect real estate platform — property listings, visit bookings, listing verification, favorites, and geocoding, with Greek/English bilingual listing content.

Built with **FastAPI**, **SQLAlchemy 2.0 (async)**, and **PostgreSQL**. Packaged with [uv](https://docs.astral.sh/uv/), Dockerized, and covered by an async pytest suite.

## Features

- **Authentication** — Supabase Auth: clients sign up / sign in / refresh / reset passwords directly with Supabase; the API verifies Supabase JWTs (JWKS, asymmetric signing keys) and maps each auth user to an app profile row
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
| Auth | Supabase Auth + PyJWT (`pyjwt[crypto]`) verification via JWKS |
| Storage | Cloudflare R2 (boto3) |
| Email | aiosmtplib |
| Geocoding | Geoapify |
| Tooling | uv, ruff, pytest + pytest-asyncio |

## Getting Started

### Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL (or a connection string to one)
- Cloudflare R2, SMTP, and Geoapify credentials for full functionality

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
| Auth | `POST /auth/sync` |
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
│   ├── dependencies/     # Auth dependencies (Supabase JWT verification, RBAC, ownership checks)
│   ├── middleware/       # camelCase response middleware
│   ├── models/           # SQLAlchemy models and enums
│   ├── schemas/          # Pydantic schemas (CamelModel base)
│   ├── services/         # Business logic (one module per domain)
│   ├── tests/            # Pytest suite (SQLite, mocked externals)
│   └── utils/            # Errors, R2 storage, Supabase admin client, email, validation
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
| `SUPABASE_URL` | Supabase project URL, e.g. `https://<ref>.supabase.co` (required) |
| `SUPABASE_JWT_SECRET` | Legacy HS256 JWT secret — only for projects not using asymmetric signing keys (optional) |
| `SUPABASE_SERVICE_ROLE_KEY` | Server-only key for Supabase Admin API (auth user deletion on account delete; optional) |
| `NODE_ENV` | Environment name |
| `R2_*` | Cloudflare R2 credentials, bucket, public URL |
| `SMTP_*`, `EMAIL_FROM` | Outbound email for booking/verification notifications (default Zoho) |
| `GEOAPIFY_API_KEY` | Geoapify geocoding |

## Authentication

Auth is delegated to **Supabase Auth**. The API never handles passwords, token
issuance, refresh, or password reset — all of that is done client-side with
[supabase-js](https://supabase.com/docs/reference/javascript/introduction).

### Flow

1. **Sign up** (client): `supabase.auth.signUp({ email, password })` — Supabase
   creates the `auth.users` row and sends the confirmation email.
2. **Create the app profile** (client, after email confirmation):
   `POST /api/v1/auth/sync` with `Authorization: Bearer <access_token>` and body
   `{ firstName, lastName, role }`. Roles are limited to `LANDLORD` / `TENANT` /
   `BOTH` — `ADMIN` is rejected. The endpoint is idempotent and upserts the
   profile, so it is safe to call again after profile changes.
3. **Call the API** (client): send the Supabase access token as
   `Authorization: Bearer <access_token>`. The API verifies it against the
   project's JWKS endpoint, resolves the user via `users.supabase_user_id`
   (the JWT `sub`), and enforces app-level status checks (banned/suspended).
   supabase-js refreshes the token automatically.
4. **Password reset / email change / logout**: all via supabase-js
   (`resetPasswordForEmail`, `updateUser`, `signOut`). Nothing to call on the API.

```js
import { createClient } from "@supabase/supabase-js";

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

// sign up
await supabase.auth.signUp({ email, password });

// after confirmation: create/update the API profile
const { data } = await supabase.auth.getSession();
await fetch(`${API_URL}/api/v1/auth/sync`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${data.session.access_token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ firstName: "Ada", lastName: "Lovelace", role: "TENANT" }),
});

// authenticated API call
await fetch(`${API_URL}/api/v1/users/me`, {
  headers: { Authorization: `Bearer ${(await supabase.auth.getSession()).data.session.access_token}` },
});
```

### Supabase dashboard checklist

- **Auth → URL Configuration**: set Site URL and redirect URLs to your frontend.
- **Auth → Emails**: configure custom SMTP (Settings → Auth → SMTP); the
  built-in email provider is rate-limited and dev-only. Point the confirmation
  and password-reset templates at your frontend routes.
- **Auth → Sign In / Providers**: keep "Confirm email" enabled (the API assumes
  a confirmed email for profile sync).
- **JWT keys** (Settings → API): use the default asymmetric signing keys — the
  API fetches `SUPABASE_URL/auth/v1/.well-known/jwks.json` and needs no shared
  secret. Only set `SUPABASE_JWT_SECRET` for legacy HS256 projects.
- **API keys**: `SUPABASE_SERVICE_ROLE_KEY` is optional; when set, deleting an
  account via the API also deletes the Supabase auth user.

### Notes

- `users.id` (integer) remains the identity referenced by all other tables;
  `users.supabase_user_id` maps it to the Supabase auth UUID.
- No RLS: the API is the sole database client.
- Server-side revocation is gone by design — access tokens are short-lived and
  status checks (`BANNED`/`SUSPENDED`) are enforced per request.

## License

Distributed under the [GPL-3.0 License](LICENSE).
