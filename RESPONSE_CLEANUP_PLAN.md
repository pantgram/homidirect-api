# Response Serialization Cleanup Plan — v2

**Status:** agreed · **Date:** 2026-11-02

## Goal

Keep the Pydantic `response_model` + `CamelModel` alias path as the **single** JSON serialization
mechanism. Remove the redundant layers stacked on top of it, and delete serializer code that
duplicates what the schemas already declare. One deliberate wire change (see §5).

## Background

Responses are currently produced by two overlapping mechanisms:

1. Every route declares `response_model` on a `CamelModel` subclass
   (`app/schemas/base.py`) whose `alias_generator` already emits camelCase via FastAPI's
   default serialize-by-alias behavior.
2. `CamelCaseMiddleware` (`app/middleware/camel_case.py`) then re-parses every `/api/`
   JSON body and rewrites its keys to camelCase — a no-op for anything that went through
   a `response_model`.

Additional findings from the audit:

- Three implementations of the same camelCase converter: `app/schemas/base.py`,
  `app/middleware/camel_case.py`, and an inline lambda in `PaginatedResponse.model_config`
  (`app/schemas/common.py:18`).
- Hand-rolled `.isoformat()` string conversion in response dicts even though the schemas
  declare real `datetime`/`date` fields (string → datetime → string round trip).
- The middleware rebuilds `JSONResponse` with only the status code, **dropping all original
  headers** on the success path (`camel_case.py:39`) — e.g. slowapi rate-limit headers are
  silently lost (tests disable rate limiting, so nothing catches it).
- Dead schemas: `ApiResponse` and `PaginatedResponse` in `app/schemas/common.py` are never
  imported anywhere.
- `listing_to_dict` (`app/utils/serializers.py`) hand-enumerates all 33 listing fields —
  the same fields `ListingResponse` already declares. Every new column touches three
  places (model → schema → dict) with silent drift risk if one is missed. `CamelModel`
  already sets `from_attributes=True`, so Pydantic reads ORM rows natively.

## Changes

### 1. Remove `CamelCaseMiddleware`

- `app/main.py`: delete the import (line 15) and `app.add_middleware(CamelCaseMiddleware)`
  (line 53).
- Delete `app/middleware/camel_case.py`; with only an empty `__init__.py` remaining, remove
  the whole `app/middleware/` package.

Safety audit — JSON that bypasses `response_model` today:

| Source | Body keys | Impact |
|---|---|---|
| Webhook `POST /api/v1/webhooks/clerk` | `{"received": true}` | none (single-word key) |
| Exception handlers (`app/utils/errors.py`) | `{"error", "message", "details"}` | none (single-word keys) |
| slowapi rate-limit handler | its own shape | unchanged either way |

Result: zero wire-format change from this step; the header-dropping bug is fixed as a side
effect.

### 2. Delete dead schemas

- `app/schemas/common.py`: remove `ApiResponse` and `PaginatedResponse`
  (grep-confirmed unused). Keep `Pagination`, `MessageResponse`, `HealthResponse`.
- The duplicate lambda dies with `PaginatedResponse`; `to_camel_case` in
  `app/schemas/base.py` becomes the sole converter.

### 3. Delete `listing_to_dict`, return ORM rows

`from_attributes=True` is already on `CamelModel`; no schema changes needed.

- `app/utils/serializers.py` — remove `listing_to_dict`. **Keep** `get_primary_images`
  (shared by the listing and favorites services) in that file.
- `app/api/v1/listings.py` — no more conversion calls:
  - `get_all_listings`: `return {"listings": listings}` (service returns ORM rows)
  - `get_listing`, `create_listing`, `update_listing`, `feature_listing`:
    `return {"listing": listing}`
- `app/services/listing.py` (`search_listings` ~line 211, `get_listings_by_landlord`
  ~line 253) and `app/services/favorite.py` (~line 30) — graft the image instead of
  rebuilding the row:

  ```python
  for l in results:
      l.primary_image = primary_images.get(l.id)   # transient attribute
  return {"data": results, "pagination": {...}}
  ```

  `ListingSearchResponse.primary_image` is `ListingImageBasic | None`, so `None` values
  validate; Pydantic reads the transient attribute via `from_attributes`.

- **Time slots keep their dict pattern** (see §4 rationale) — that was a deliberate
  decision, not an omission.

After this step the schema is the only field list to maintain: new column touches
model → schema (two places, down from three).

### 4. Drop remaining hand-rolled ISO formatting in response dicts

Schemas already declare `datetime`/`date`; Pydantic emits ISO strings natively, so return
raw values from:

- `app/utils/serializers.py` — `get_primary_images` (`created_at`)
- `app/api/v1/users.py:26,40`
- `app/api/v1/auth.py:59`
- `app/api/v1/listing_images.py:30,53`
- `app/api/v1/verification.py:37,49`
- `app/api/v1/time_slots.py:37-40` — in `_format_slot`:
  - `"start_time": s.start_time`
  - `"end_time": s.start_time + SLOT_DURATION` (computed — this is why time slots keep
    the dict)
  - `"created_at": s.created_at`
- `app/services/verification.py:24,36,52,168`

### Why time slots keep `_format_slot` (and listings don't keep `listing_to_dict`)

`_format_slot` (`app/api/v1/time_slots.py:29-47`) contains real logic, not field copying:

1. `end_time` is computed (`start_time + SLOT_DURATION`, no column)
2. `is_booked` is derived (`status != "OPEN"`)
3. `landlord_id` crosses a relationship (`s.listing.landlord_id`)
4. A viewer-dependent privacy filter — `include_private` gates
   `candidate_id`/`meet_link`/`landlord_created`, hiding participant data from the public
   view of an OPEN slot. That is authorization logic; a schema cannot know who is viewing.

The relationship access is safe: every service query uses
`joinedload(TimeSlot.listing)` (service lines 57, 95, 107, 119, 372, 386), so nothing
lazy-loads in async context.

**Explicitly out of scope (keep `.isoformat()`):**

- `app/services/time_slot.py:194,249,266,352` — ISO strings feed **email background
  tasks**, not response models.
- `app/api/v1/health.py` — generates its own timestamp (`HealthResponse.timestamp: str`);
  no double conversion involved.
- Test helpers that *send* ISO strings in request bodies.

### 5. Accepted wire change: `Z` suffix on production Postgres

Verified behavior difference:

```
naive isoformat : 2026-11-02T10:00:00      → pydantic: identical
date  isoformat : 2026-11-02               → pydantic: identical
UTC-aware        2026-11-02T10:00:00+00:00 → pydantic: 2026-11-02T10:00:00Z   ← differs
```

- Affected columns use `TIMESTAMP(timezone=True)` (`listings`, `users`, `time_slots`,
  `listing_images`, verification models). On **Postgres (production)**, asyncpg returns
  tz-aware datetimes, so `created_at`/`updated_at`/`verified_at`/`featured_until`/
  `start_time`/`end_time` etc. will emit `...Z` instead of `...+00:00`.
- On **SQLite (tests)** values come back naive → test output stays byte-identical, so the
  suite will NOT flag this change. It is deliberate.
- `Z` and `+00:00` are semantically identical ISO 8601; any JS client parses both.
- Caveat for non-JS consumers on Python < 3.11: `datetime.fromisoformat()` does not parse
  `Z` — they would need `.replace("Z", "+00:00")`. Check external consumers if any exist
  outside this repo.

### 6. Verification

- `app/tests/test_middleware.py` stays as-is: it becomes a camelCase **contract test** —
  all four assertions must pass via alias serialization alone, proving the middleware was
  redundant. (Optionally rename to `test_response_conventions.py`.)
- Time-slot tests parse responses with `datetime.fromisoformat(body["startTime"])` — keep
  working: SQLite values are naive and Pydantic emits the same naive ISO format.
- `grep -r listing_to_dict app/` must return nothing.
- Run the full suite and lint:

  ```bash
  uv run pytest
  uv run ruff check . && uv run ruff format .
  ```

## Documented caveats for the implementer

- The transient `primary_image` is a plain Python attribute on the SQLAlchemy instance —
  not mapped, not persisted, invisible to Alembic.
- If a relationship field ever lands on a listing/favorite schema (e.g. `landlord`),
  `from_attributes` will try to read it and hit `MissingGreenlet` in async context.
  Convention: eagerly load (`joinedload`/`selectinload`) before returning rows — the time
  slot service already does this everywhere.
- With the middleware gone, a future route added **without** `response_model` that returns
  snake_case dicts would leak snake_case keys to clients. Mitigation: convention (every
  route declares `response_model`, as all do today) plus the camelCase contract tests.

## Outcomes

- One serialization path: typed response models.
- One camelCase converter.
- No string → datetime → string round trip for dates.
- `listing_to_dict` and its 33-field duplication deleted; two-place field maintenance.
- Response headers (rate-limit, etc.) no longer dropped.
- Slightly faster: no per-response body buffering/re-parse, and `BaseHTTPMiddleware`
  overhead removed.
- One documented wire change (`Z` suffix) on production Postgres only.
