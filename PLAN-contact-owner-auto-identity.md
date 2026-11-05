# Plan: Auto-populate sender name/email in contact-owner

**Status:** agreed, not yet implemented
**Decision:** sender identity is *strictly server-derived* from the authenticated user's profile (no client overrides).

## Context

`POST /api/v1/listings/{listing_id}/contact` lets an authenticated user send an inquiry email to a
listing's landlord. Today the client supplies the sender's `name` and `email` in the request body
(`ContactOwnerRequest`), which:

- is redundant — the endpoint already requires auth, and `User` stores `first_name`, `last_name`, `email`
- lets callers spoof someone else's contact details in the email delivered to the landlord

The `User` model (`app/models/user.py`) has no phone column, so `phone` remains client-supplied.

## Changes

### 1. `app/schemas/listing.py` — slim down `ContactOwnerRequest` (line 162)

```python
class ContactOwnerRequest(CamelModel):
    phone: str | None = None
    message: str
```

- `name` and `email` are removed.
- `CamelModel` uses Pydantic's default `extra="ignore"`, so old clients still sending
  `name`/`email` get them silently discarded instead of a 422 — backward compatible.

### 2. `app/api/v1/listings.py` — derive identity from `current_user` (`contact_owner`, line 171)

```python
sender_name = f"{current_user.first_name} {current_user.last_name}".strip()
background_tasks.add_task(
    send_contact_owner_email,
    landlord.email,
    sender_name,
    current_user.email,
    body.phone or "",
    body.message,
)
```

- `send_contact_owner_email` signature is unchanged — no service/email-template edits.
- The existing behavior of silently skipping the email when the landlord row is missing
  (`if landlord:`) stays as-is.

### 3. `app/tests/test_listings.py` — update `TestContactOwner` (lines 414–444)

- All payloads drop `name`/`email`, e.g. `json={"message": "Is this available?"}`
  (including the 401 and 404 tests).
- Strengthen the main assertion: the `tenant` fixture user is `first_name="Test"`,
  `last_name="User"`, `email="tenant@example.com"`, so assert
  `args[1] == "Test User"` and `args[2] == "tenant@example.com"` — proving the email task
  receives profile data, not client input.

## Out of scope / untouched

- `app/tests/conftest.py` — the `contact_owner` mock is a generic `AsyncMock` that records args; no change.
- No DB migration (no model changes), no other callers of `ContactOwnerRequest`.
- `phone` stays in the request body (optional) since `User` has no phone field.

## Verification

```bash
uv run pytest app/tests/test_listings.py -k contact   # focused
uv run pytest                                         # full suite
uv run ruff check . && uv run ruff format .
```
