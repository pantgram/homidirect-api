# AGENTS.md — HomiDirect API

FastAPI + SQLAlchemy 2.0 (async) + PostgreSQL REST API. Package manager is **uv** (always `uv run ...`, never plain `python`/`pytest`).

## Commands

```bash
uv sync                                              # install deps (dev group included)
uv run pytest                                        # full suite (~5s, no external services)
uv run pytest app/tests/test_listings.py -k name     # focused test
uv run ruff check . && uv run ruff format .          # lint (line length 120; rules E,F,I,N,W)
uv run uvicorn app.main:app --reload --port 5000     # dev server (docs at /docs)
uv run alembic upgrade head                          # apply migrations
uv run alembic revision --autogenerate -m "..."      # generate migration
```

No CI, no pre-commit. Work happens on the `develop` branch.

## Environment gotchas

- `app/config/settings.py` loads `.env` from **`../.env`** — the parent of the current working directory, not the repo root. Environment variables take priority over the file, so exporting vars is the reliable way to configure a run.
- Required settings with no default: `DATABASE_URL`, `SUPABASE_URL`, `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET_NAME`, `R2_PUBLIC_URL`. Note `.env.example` is **missing `R2_ACCOUNT_ID`** even though the app requires it.
- Alembic and the app both import `settings` at module load, so any command touching `app.*` fails without those vars set.
- `LOG_FILE` defaults to a hardcoded `/home/pantgram/Documents/logs/...` path and `FileHandler` does not create parent dirs — if `import app.main` dies with `FileNotFoundError`, set `LOG_FILE`.
- `settings.async_database_url` strips PG-only query params (`sslmode`, ...) from `DATABASE_URL` for asyncpg; use it, not `database_url`, for engines.

## Architecture

- Layering: `app/api/v1/` (routers) → `app/services/` (business logic, one module per domain) → `app/models/` (SQLAlchemy) and `app/schemas/` (Pydantic).
- Adding a domain requires touching: new router in `app/api/v1/`, registration in `app/api/v1/__init__.py` (everything mounts under `/api/v1`), tag in `openapi_tags` in `app/main.py`, and model import in `app/models/__init__.py` (needed for Alembic autogenerate and test `create_all`).
- Sessions auto-commit: `get_db` in `app/config/database.py` commits at request end and rolls back on exception. Services/routers never call `db.commit()`.
- Errors: raise `AppError` subclasses from `app/utils/errors.py` (`NotFoundError`, `ConflictError`, ...). Handlers emit `{"error", "message"}`; unhandled exceptions are masked as a generic 500 (logged).
- JSON is camelCase on the wire: every schema extends `CamelModel` (`app/schemas/base.py` — snake_case attributes, camelCase aliases, `populate_by_name=True`); `CamelCaseMiddleware` converts responses too.
- Auth is delegated to Supabase: JWTs verified via JWKS in `app/dependencies/auth.py`. `get_current_user` never auto-creates profiles — an unknown `sub` is a 401 `Unauthorized`; `POST /auth/sync` is the only profile-creation path. That endpoint takes a `SyncUser` body: names (`first_name`, `last_name`) come from the token's `user_metadata` (snake_case keys), while `role` comes from the body (`"LANDLORD" | "TENANT"`, or `null`/omitted → `TENANT` on create, stored role kept on update; `BOTH`/`ADMIN` can never be self-assigned). RBAC with `require_role`/`require_admin`, ownership with the `verify_*_ownership` helpers in the same file; `ADMIN` bypasses all role/ownership checks.

## Testing (`app/tests/`)

- `conftest.py` injects fake env vars **before** importing the app, using `os.environ.setdefault` — real exported env vars leak into tests.
- Postgres → SQLite compatibility is patched in conftest: SQLite server default **and** rewritten CHECK constraint for `Listing.date_built`, full-text GIN `TextClause` indexes dropped from metadata. If you add Postgres-only constructs to models, update conftest or the suite breaks.
- Autouse fixtures disable rate limiting and mock email/R2/Supabase-admin. Mocks patch the name **inside the consuming module** (e.g. `verification_service.upload_to_r2`, since services do `from app.utils.storage import upload_to_r2`) — wire new external calls into `mock_external_services` in conftest.
- JWT verification is replaced with HS256 test tokens (`role=authenticated`). Use the helpers/fixtures: `make_test_token`, `sync_user`, `create_db_user`, `auth_headers_for`, `create_listing`, `landlord`/`tenant`/`admin` (+`*_headers`).

## Alembic

- `alembic/env.py` excludes `listings_search_el_idx` / `listings_search_en_idx` from autogenerate (they are full-text GIN indexes created manually in migrations). Add similar PG-only indexes to `include_object` or autogenerate will emit drops for them.
