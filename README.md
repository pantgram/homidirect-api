# HomiDirect API

REST API for the HomiDirect real estate platform — property listings, visit bookings via time slots, listing verification, and favorites, with Greek/English bilingual listing content.

Built with **FastAPI**, **SQLAlchemy 2.0 (async)**, and **PostgreSQL**. Packaged with [uv](https://docs.astral.sh/uv/), Dockerized, and covered by an async pytest suite.

## Features

- **Authentication** — Clerk: clients sign up / sign in with Clerk's frontend SDKs; the API verifies Clerk session tokens (`Authorization: Bearer <session_token>`) and maps each Clerk user to an app profile row
- **Users** — profile management and roles (`LANDLORD` / `TENANT` / `BOTH` / `ADMIN`); banned/suspended users are blocked per request
- **Listings** — full CRUD, paginated search with filters and sorting, stats, distinct cities, bilingual (el/en) content, Postgres full-text search (English + Greek), admin-managed featured windows
- **Listing images** — multipart uploads to Cloudflare R2 with magic-byte content validation and size limits
- **Verification** — ownership document uploads (utility bill, title deed, etc.), verification history, admin review queue (approve/reject with notes)
- **Favorites** — add/remove/check favorite listings, paginated favorites feed
- **Time slots** — bookings are claimed 30-minute viewing windows (`REMOTE` or `ON_SITE`) with a status lifecycle (`OPEN` → `PENDING` → `CONFIRMED` / `DECLINED` / `CANCELLED`) and notification emails
- **Webhooks** — Svix-signed Clerk lifecycle events (`user.created` / `user.updated` / `user.deleted`) keep profiles in sync, fail-closed
- **Cross-cutting** — camelCase JSON responses (middleware + Pydantic aliases), consistent error format, slowapi rate limiting on `/auth/sync`, CORS

## Tech Stack

| Layer | Choice |
|---|---|
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) + Alembic migrations |
| Database | PostgreSQL (asyncpg); SQLite (aiosqlite) in tests |
| Validation | Pydantic v2 + pydantic-settings |
| Auth | Clerk (`clerk-backend-api` SDK) + Svix webhook signatures |
| Storage | Cloudflare R2 (boto3) |
| Email | aiosmtplib |
| Tooling | uv, ruff, pytest + pytest-asyncio |

## Getting Started

### Prerequisites

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/)
- PostgreSQL (or a connection string to one)
- Cloudflare R2, Clerk, and SMTP credentials for full functionality

### Installation

```bash
# Clone
git clone <repository-url>
cd homidirect-api

# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# edit .env with your values (note: R2_ACCOUNT_ID is required but
# missing from .env.example — add it)
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

Tests run against an in-memory SQLite database with email, R2 storage, Clerk Backend API, webhook signatures, and rate limiting mocked — no external services required.

```bash
uv run pytest
```

### Linting

```bash
uv run ruff check .
uv run ruff format .
```

## API Overview

All routes are prefixed with `/api/v1`. Authenticated routes expect `Authorization: Bearer <clerk_session_token>`.

| Domain | Endpoints |
|---|---|
| Health | `GET /health` |
| Auth | `POST /auth/sync` (rate-limited 10/min) |
| Users | `GET /users/me`, `GET /users/{id}`, `DELETE /users/{id}` |
| Listings | `GET /listings`, `GET /listings/search`, `GET /listings/stats`, `GET /listings/cities`, `GET /listings/my-listings`, `POST /listings`, `GET/PATCH/DELETE /listings/{id}`, `POST /listings/{id}/contact`, `POST/DELETE /listings/{id}/feature` (admin) |
| Listing Images | `GET/POST /listings/{id}/images`, `DELETE /listings/{id}/images/{image_id}` |
| Verification | `GET /listings/{id}/verification`, `GET /listings/{id}/verification/documents`, `POST /listings/{id}/verification/documents`, `DELETE /listings/{id}/verification/documents/{document_id}`, `GET /listings/{id}/verification/history` |
| Admin Verification | `GET /admin/verifications/pending`, `POST /admin/verifications/{id}/verification/review` |
| Favorites | `GET /favorites`, `GET /favorites/ids`, `GET /favorites/{id}/check`, `POST/DELETE /favorites/{id}` |
| Time Slots | `GET /time-slots/me`, `GET /time-slots/listing/{id}`, `GET /time-slots/listing/{id}/available`, `GET /time-slots/listing/{id}/bookings`, `POST /time-slots`, `POST /time-slots/propose`, `POST /time-slots/{id}/claim`, `GET/PATCH/DELETE /time-slots/{id}` |
| Webhooks | `POST /webhooks/clerk` (Svix-signed) |

Full request/response schemas are available in the OpenAPI docs at `/docs`.

### Time slots & bookings

A booking is just a claimed slot: `OPEN` rows are landlord-authored availability (`POST /time-slots`), while proposed/claimed rows carry a candidate tenant (`POST /time-slots/propose`, `POST /time-slots/{id}/claim`). Claiming moves the slot to `PENDING`; the landlord then confirms or declines (`PATCH`), and either side can cancel — which frees the slot. Slots are fixed 30-minute windows (`startTime` only) and are typed `REMOTE` (with meet link) or `ON_SITE`. Rescheduling is not supported — cancel and rebook.

## Project Structure

```
├── alembic/              # Async Alembic migrations
├── app/
│   ├── api/v1/           # Route handlers (one module per domain)
│   ├── config/           # Settings, database engine, rate limiter, logging
│   ├── dependencies/     # Auth dependencies (Clerk token verification, RBAC, ownership checks)
│   ├── middleware/       # camelCase response middleware
│   ├── models/           # SQLAlchemy models and enums
│   ├── schemas/          # Pydantic schemas (CamelModel base)
│   ├── services/         # Business logic (one module per domain)
│   ├── tests/            # Pytest suite (SQLite, mocked externals)
│   └── utils/            # Errors, R2 storage, Clerk admin client, email, file validation
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
└── uv.lock
```

## Environment Variables

See [.env.example](.env.example) for all variables:

| Variable | Purpose |
|---|---|
| `PORT` | Server port (default 5000) |
| `DATABASE_URL` | PostgreSQL connection string (required) |
| `CLERK_SECRET_KEY` | Clerk server API key `sk_...` — used for token verification (JWKS fallback) and the Clerk Backend API (required) |
| `CLERK_JWT_KEY` | Optional PEM public key — verifies tokens locally without network calls; leave empty for JWKS (auto rotation) |
| `CLERK_AUTHORIZED_PARTIES` | Comma-separated `azp` allowlist (frontend origins); strongly recommended against replay/CSRF |
| `CLERK_WEBHOOK_SECRET` | Svix signing secret (`whsec_...`) for the webhook endpoint; empty ⇒ webhooks are rejected |
| `NODE_ENV` | Environment name (`echo`-mode SQL logging when `development`) |
| `FRONTEND_URL` | Allowed CORS origin (default `http://localhost:8080`) |
| `LOG_FILE` / `LOG_LEVEL` | File logging (the default path is machine-specific — parent dirs are not created) |
| `R2_*` | Cloudflare R2 account, credentials, bucket, public URL (`R2_ACCOUNT_ID` is required but missing from `.env.example`) |
| `SMTP_*`, `EMAIL_FROM` | Outbound email for booking/verification notifications (default Zoho) |

## Authentication

Auth is delegated to **Clerk**. The API never handles passwords, token issuance, or sessions — all of that is done client-side with [Clerk's frontend SDKs](https://clerk.com/docs/quickstarts).

### Flow

1. **Sign up / sign in** (client, Clerk SDK): Clerk issues a session token.
2. **Create the app profile** (client, after sign-in): `POST /api/v1/auth/sync` with `Authorization: Bearer <session_token>` and body `{ "role": "LANDLORD" | "TENANT" }` (or `null`). The endpoint is idempotent — call it after signup/login and after every profile change. Profile data (email, names) is fetched server-side from the Clerk Backend API; only the role travels in the body. `BOTH` and `ADMIN` can never be self-assigned.
3. **Call the API** (client): send the Clerk session token as `Authorization: Bearer <session_token>`. The API verifies it (optional local PEM key, JWKS fallback), resolves the user via `users.clerk_user_id` (the JWT `sub`), and enforces app-level status checks (`BANNED`/`SUSPENDED` → 403).
4. **Profile updates**: owned by the Clerk webhook (`user.updated` refreshes names/email; the role is untouched). **Account deletion**: `DELETE /users/{id}` removes the local row and the Clerk auth user (Backend API); the subsequent `user.deleted` webhook is a no-op.

```js
// after Clerk signIn/signUp
const token = await window.Clerk.session.getToken();

// create/update the API profile
await fetch(`${API_URL}/api/v1/auth/sync`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({ role: "LANDLORD" }),
});

// authenticated API call (refresh the token — it is short-lived)
await fetch(`${API_URL}/api/v1/users/me`, {
  headers: { Authorization: `Bearer ${await window.Clerk.session.getToken()}` },
});
```

### Clerk dashboard checklist

- **API Keys**: copy the server secret into `CLERK_SECRET_KEY`. Optionally export the public key (PEM) into `CLERK_JWT_KEY` for networkless verification — key rotation is then manual.
- **Webhooks**: register `POST https://<api-host>/api/v1/webhooks/clerk` for `user.created`, `user.updated`, `user.deleted` and copy the Svix signing secret into `CLERK_WEBHOOK_SECRET`. Handlers are idempotent (Clerk redelivers) and always answer 200 on success; invalid signatures are rejected with 400 so Clerk retries.
- **Authorized parties**: set `CLERK_AUTHORIZED_PARTIES` to your frontend origins (comma-separated) — omitting it can open replay/CSRF vectors.

### Notes

- `users.id` (integer) remains the identity referenced by all other tables; `users.clerk_user_id` maps it to the Clerk user id (`sub`).
- No RLS: the API is the sole database client.
- Server-side revocation is gone by design — session tokens are short-lived and status checks (`BANNED`/`SUSPENDED`) are enforced per request.
- Roles are app-level, stored in `users.role`, and deliberately not mirrored to Clerk public metadata.

## License

Distributed under the [GPL-3.0 License](LICENSE).
