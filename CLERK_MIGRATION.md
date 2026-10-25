# Migration plan: Supabase Auth → Clerk

Status: **approved, not yet implemented.** This document is the implementation
contract for replacing Supabase Auth with Clerk as the identity provider.

Supabase is used **only** for auth in this codebase (storage is R2, email is
SMTP), so this migration touches no other subsystem.

---

## 1. Locked decisions

| # | Decision |
|---|----------|
| 1 | **Token verification: SDK `authenticate_request()`** (the canonical Clerk Python pattern). FastAPI `Request` passed directly; `accepts_token=["session_token"]` explicit (the SDK default is `['any']`), `authorized_parties` as the `azp` allowlist, `jwt_key` PEM when configured (networkless) with JWKS fallback. Supabase's `role=authenticated` check and the HS256 legacy branch are deleted. |
| 2 | **Lifecycle ownership:** `POST /auth/sync` is the **only profile-creation path** (role travels in the request body, webhooks can't know it). Webhooks own **updates** (`user.updated`) and **deletes** (`user.deleted`). Webhook `user.created` is a **safety-net upsert only** (TENANT default); sync immediately applies the real role. |
| 3 | **Backend API calls: `clerk-backend-api` SDK** (pinned version), wrapped in `app/utils/clerk_admin.py`. `fetch_clerk_user` (used by sync) and `delete_auth_user` (account deletion). Async SDK methods (`get_async`/`delete_async`). |
| 4 | **Webhook signatures: `svix` package** — fail-closed (400 on bad signature). The SDK has no webhook verification. |
| 5 | **Data: clean break** — dev-only, no real users. `users.supabase_user_id UUID` is dropped and replaced by `clerk_user_id String(255)` (unique, indexed). No Supabase→Clerk user import script. |
| 6 | **RBAC stays DB-only** — `users.role` + existing `require_role` / `require_admin` / `verify_*_ownership` helpers are untouched. Roles are deliberately **not** mirrored to Clerk `publicMetadata`; no Clerk Organizations. Revisit only if landlord teams/agencies become a requirement. `ADMIN` remains non-self-assignable. |
| 7 | **New dependencies:** `clerk-backend-api` (pinned), `svix`. `pyjwt[crypto]` moves from main deps to the dev group (still used by conftest to sign fake test tokens). |
| 8 | **Settings:** remove `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`; add `CLERK_SECRET_KEY` (required — verification and Backend API both need it), `CLERK_JWT_KEY` (optional PEM, networkless verification), `CLERK_AUTHORIZED_PARTIES` (comma-separated, optional but strongly recommended), `CLERK_WEBHOOK_SECRET` (optional). No `CLERK_ISSUER` — keys are pasted from the dashboard, no issuer-domain reasoning. |

The `Authorization: Bearer <token>` wire contract is unchanged — Clerk's
frontend SDK `getToken()` also returns a JWT — so the frontend→API contract
(other than token issuer) is preserved.

---

## 2. Architecture after migration

- **Verification** (`app/dependencies/auth.py`): a thin wrapper
  `authenticate_clerk_request(request: Request) -> dict` around the SDK:
  - `authenticate_request(request, AuthenticateRequestOptions(secret_key=...,
    jwt_key=settings.clerk_jwt_key or None, authorized_parties=<parsed list>,
    accepts_token=["session_token"]))` — the SDK accepts FastAPI/Starlette
    `Request` directly (it reads `Authorization: Bearer` itself, with a
    `__session` cookie fallback); the `HTTPBearer` dependency is dropped.
  - `jwt_key` (PEM public key from the dashboard) → local, networkless
    verification; omitted → JWKS fallback fetched per `kid` and cached
    (~5 min, auto key rotation).
  - `state.is_signed_in` false → `UnauthorizedError(state.reason.name)`;
    success → return `state.payload`.
  - `sub` is used as-is (string like `user_2abc...`); **no UUID parsing**.
- **Identity lookup**: `User.clerk_user_id` replaces `supabase_user_id` in
  `get_current_user` / `get_optional_user`. Banned/suspended handling,
  `get_optional_user` semantics, RBAC and ownership helpers unchanged.
- **`POST /auth/sync`**: verify token → `sub` → `clerk_admin.fetch_clerk_user(sub)`
  (Backend API `GET /v1/users/{id}` via SDK; resolve primary email via
  `primary_email_address_id` against `email_addresses[]`) → existing
  `sync_user()` logic (param type `uuid.UUID` → `str`). Still rate-limited
  (10/min), still idempotent, still the only creation path, role allowlist
  excludes `ADMIN`.
- **Webhooks** (`app/api/v1/webhooks.py`, new): `POST /api/v1/webhooks/clerk`
  - Svix signature verification against `CLERK_WEBHOOK_SECRET`; **fail-closed**
    → 400 on missing/invalid `svix-*` headers. No rate-limit decorator, no auth
    dependency.
  - `user.created` → upsert profile (TENANT default; role comes from sync right
    after). Unknown user upserts are fine; email collision → log + 200 (never
    4xx, Clerk retries non-2xx).
  - `user.updated` → update names/email on the matching row (role untouched);
    unknown `clerk_user_id` → log + 200.
  - `user.deleted` → delete local row via the existing `user_service.delete_user`
    logic; idempotent (already-gone → 200). This makes the existing
    `DELETE /users/{id}` flow safe: it deletes locally, calls Clerk, and the
    resulting webhook is a no-op.
  - All other event types → 200 ignore.
  - Handlers are idempotent (Clerk redelivers).
- **Account deletion**: `app/utils/clerk_admin.py` (replaces `supabase_admin.py`)
  - Module-lazy `Clerk(bearer_auth=settings.clerk_secret_key)` singleton,
    constructed once and reused across requests (async SDK client).
  - `fetch_clerk_user(clerk_user_id) -> dict` — SDK `users.get_async`, returns
    `{email, first_name, last_name}`.
  - `delete_auth_user(clerk_user_id) -> bool` — SDK `users.delete_async`;
    errors via `ClerkBaseError` (has `.status_code`); keeps the
    warn-and-no-op-when-key-missing behavior.
- **Unchanged**: `require_role` / `require_admin` / `verify_user_ownership` /
  `verify_listing_ownership` / `verify_time_slot_ownership`, `users.status`
  banned/suspended checks, rate limiting, camelCase error envelope, `get_db`
  auto-commit (webhook handler commits at request end automatically).

---

## 3. File-by-file changes

| File | Change |
|---|---|
| `pyproject.toml` | + `clerk-backend-api` (pinned), + `svix`; move `pyjwt[crypto]` from main deps to the dev group |
| `.env.example` | Remove `SUPABASE_*`; add `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`, `CLERK_AUTHORIZED_PARTIES`, `CLERK_WEBHOOK_SECRET` |
| `app/config/settings.py` | Same removals/additions; `clerk_authorized_parties` stored comma-separated, parsed to `list[str]` (never pass the raw string to `AuthenticateRequestOptions` — it becomes one list element and every request fails with `TOKEN_INVALID_AUTHORIZED_PARTIES`) |
| `app/models/user.py` | `supabase_user_id UUID` → `clerk_user_id: sa.String(255)`, unique + indexed |
| `alembic/versions/` | New migration: drop `users.supabase_user_id` (+ its index), add `users.clerk_user_id` + unique index. Clean break, no data copy. |
| `app/dependencies/auth.py` | `verify_supabase_jwt` + `HTTPBearer` → `authenticate_clerk_request(request)` SDK wrapper (§2); drop `_extract_supabase_user_id` and the `PyJWKClient` singleton; `get_current_user` / `get_optional_user` take `request: Request` and look up by `clerk_user_id` |
| `app/utils/clerk_admin.py` (new; deletes `supabase_admin.py`) | SDK wrappers per §2 |
| `app/services/auth.py` | `sync_user(db, clerk_user_id: str, ...)`: type change only; logic intact |
| `app/api/v1/auth.py` | Sync flow: wrapper → `sub` → `fetch_clerk_user` → `sync_user`; `security_scheme` dependency replaced by the raw `Request`; docstring updated (Clerk, not supabase-js) |
| `app/api/v1/users.py` | Rename only (`clerk_user_id`, `clerk_admin.delete_auth_user`) |
| `app/services/user.py` | Rename only |
| `app/api/v1/webhooks.py` (new) | Clerk webhook endpoint per §2 |
| `app/api/v1/__init__.py` | Register webhooks router |
| `app/main.py` | Add `Webhooks` to `openapi_tags` |
| `app/schemas/user.py` | Update the `VALID_ROLES` comment (Supabase metadata → Clerk sync body) |
| `app/tests/conftest.py` | See §4 |
| `app/tests/test_auth.py` | Renames: unknown-Clerk-user test, ADMIN-in-claims-ignored test; drop `role=authenticated`-shaped assertions |
| `app/tests/test_users.py` | Rename the auth-user-deleted test |
| `app/tests/test_webhooks.py` (new) | See §4 |
| `AGENTS.md` | Rewrite the auth paragraph for Clerk; add design note: *"Roles are app-level, stored in `users.role`, deliberately not mirrored to Clerk publicMetadata — revisit only if landlord teams/agencies become a requirement."* |

---

## 4. Test strategy (`app/tests/`)

`conftest.py`:

- `_TEST_ENV`: replace `SUPABASE_*` with `CLERK_SECRET_KEY`, `CLERK_JWT_KEY`
  (empty), `CLERK_AUTHORIZED_PARTIES`, `CLERK_WEBHOOK_SECRET`.
- `make_test_token(sub, email, ...)`: Clerk-shaped claims —
  `sub="user_<hex>"`, `azp`, `iat`/`exp`. The Supabase `role="authenticated"`
  claim is gone.
- `mock_supabase_auth` → `mock_clerk_auth`: monkeypatch the wrapper
  `app.dependencies.auth.authenticate_clerk_request` with an HS256 fake that
  decodes the bearer token with `TEST_AUTH_SECRET` and returns its claims
  (same approach as today; no network, no SDK in tests).
- `sync_user` helper: registers expected profile data in a registry consumed by
  the `fetch_clerk_user` mock (names now come from the mocked Backend API call,
  mirroring the real flow), then POSTs to `/auth/sync` as before.
- `create_db_user` / `auth_headers_for`: string `clerk_user_id=f"user_{uuid4().hex}"`.
- `mock_external_services` gains (patched inside consuming modules, per the
  existing convention):
  - `clerk_admin.fetch_clerk_user` (registry-backed)
  - `clerk_admin.delete_auth_user` (AsyncMock, replaces the Supabase one)
  - webhook signature verification function inside `app.api.v1.webhooks` (no-op
    so tests can POST raw payloads)

New `test_webhooks.py` coverage: invalid signature → 400; `user.created`
upserts (TENANT default); `user.updated` updates names/email and never the
role; `user.deleted` removes the row and is idempotent (repeat/unknown → 200);
unknown event type → 200.

`test_auth.py` / `test_users.py`: mechanical renames plus the existing
"ADMIN in claims/metadata is ignored" test adapted to the sync body.

---

## 5. Sequencing

1. **Foundation** — deps (`clerk-backend-api` pinned, `svix`), settings,
   model column change + Alembic migration, `.env.example`, conftest env.
2. **Identity swap** — `clerk_admin.py` (delete `supabase_admin.py`),
   the `authenticate_clerk_request` wrapper, repo-wide `supabase_user_id` →
   `clerk_user_id` renames (services, routers, tests).
3. **Sync rewrite** — `/auth/sync` via `fetch_clerk_user`.
4. **Webhooks** — `webhooks.py` + registration + `test_webhooks.py`.
5. **Green + docs** — full suite (`uv run pytest`), `uv run ruff check . &&
   uv run ruff format .`, AGENTS.md rewrite.

---

## 6. Cutover / operational notes

- Dashboard keys to collect: `CLERK_SECRET_KEY` (`sk_test_`/`sk_live_`),
  optionally the JWT public key (PEM) for networkless verification, and the
  webhook signing secret (`whsec_...`). If `CLERK_JWT_KEY` is left empty,
  verification falls back to JWKS (auto key rotation, ~5 min cache); if set,
  PEM rotation is manual.
- One manual Clerk dashboard step: register the webhook endpoint
  (`POST {API_BASE}/api/v1/webhooks/clerk`, events `user.created`,
  `user.updated`, `user.deleted`) and copy the signing secret into
  `CLERK_WEBHOOK_SECRET`.
- Deployment env files need the new `CLERK_*` values; old `SUPABASE_*` vars
  become inert (pydantic `extra="ignore"`).
- Frontend (separate repo): swap supabase-js for Clerk components; keep calling
  `POST /auth/sync` with `role` in the body after sign-up and after profile
  updates (sync stays the creation path; updates also arrive via webhook).
- Supabase project can be retired once the frontend is cut over.

## 7. Known trade-offs accepted

- Four must-remembers, all centralized in the wrapper: (1) pass
  `accepts_token=["session_token"]` explicitly — the Python SDK defaults to
  `['any']`, which would also accept API keys and M2M tokens on every endpoint;
  (2) configure `authorized_parties` — per Clerk's docs, omitting it can open
  replay/CSRF vectors; (3) `CLERK_JWT_KEY` (PEM) means manual key rotation,
  while the JWKS fallback rotates automatically; (4) the pinned SDK version
  runs on every request, so upgrades deserve a test run.
- Backend API availability becomes a dependency of `/auth/sync` (it fetches the
  profile). Acceptable: sync is infrequent and rate-limited; without
  `CLERK_SECRET_KEY` configured the endpoint fails loudly rather than silently
  creating empty profiles.
