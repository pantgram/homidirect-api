import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from app.config.database import get_db
from app.config.logging_config import logger
from app.config.settings import settings
from app.models.user import User
from app.services import auth as auth_service
from app.services import user as user_service
from app.utils.errors import ConflictError, ValidationError

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

# Matches the first_name/last_name column limit on users.
_MAX_NAME_LENGTH = 100


def verify_webhook(payload: bytes, headers: dict) -> dict:
    """Verify the Svix signature of a Clerk webhook delivery and return the
    decoded event. Fail-closed: any missing/invalid ``svix-*`` header raises,
    and the endpoint answers 400 (Clerk only retries non-2xx).

    The signature must be checked before the payload is trusted, so this is a
    plain function (patchable in tests), not a FastAPI dependency.
    """
    if not settings.clerk_webhook_secret:
        logger.warning("CLERK_WEBHOOK_SECRET not configured; rejecting webhook delivery")
        raise WebhookVerificationError
    Webhook(settings.clerk_webhook_secret).verify(payload, headers)
    return json.loads(payload)


def _primary_email(data: dict) -> str | None:
    """Resolve the primary email from a Clerk user object payload, mirroring
    app/utils/clerk_admin.fetch_clerk_user."""
    email_addresses = data.get("email_addresses") or []
    primary_id = data.get("primary_email_address_id")
    for address in email_addresses:
        if address.get("id") == primary_id:
            return address.get("email_address")
    if email_addresses:
        return email_addresses[0].get("email_address")
    return None


def _clean_name(value: str | None) -> str:
    return (value or "").strip()[:_MAX_NAME_LENGTH]


@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive Clerk user lifecycle events.

    Profile creation stays owned by POST /auth/sync (only it knows the desired
    role): ``user.created`` is a safety-net upsert with the TENANT default, and
    sync applies the real role immediately after. ``user.updated`` refreshes
    names/email (role untouched). ``user.deleted`` removes the local row,
    making the DELETE /users/{id} flow (local delete + Clerk delete → webhook
    no-op) safe. Handlers are idempotent — Clerk redelivers — and every event
    is answered 200; unknown event types are ignored.
    """
    payload = await request.body()
    logger.info("Webhook received: %s bytes", len(payload))
    try:
        event = verify_webhook(payload, dict(request.headers))
    except WebhookVerificationError:
        logger.error("Webhook rejected: invalid or missing Svix signature")
        raise ValidationError("Invalid webhook signature")

    event_type = event.get("type")
    data = event.get("data") or {}
    clerk_user_id = data.get("id")

    if not event_type or not clerk_user_id:
        logger.warning("Webhook ignored: missing type or data.id")
        return {"received": True}

    if event_type == "user.created":
        # Safety-net upsert only; role=None → TENANT on create, stored role kept
        # on update. The real role arrives via /auth/sync right after signup.
        email = _primary_email(data)
        if not email:
            logger.info("Webhook user.created skipped: no resolvable email for clerk user %s", clerk_user_id)
            return {"received": True}
        try:
            await auth_service.sync_user(
                db,
                clerk_user_id,
                email,
                _clean_name(data.get("first_name")),
                _clean_name(data.get("last_name")),
                role=None,
            )
            logger.info("Webhook user.created upserted profile for clerk user %s", clerk_user_id)
        except ConflictError:
            logger.warning("Webhook user.created skipped: email already registered for clerk user %s", clerk_user_id)

    elif event_type == "user.updated":
        result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
        user = result.scalar_one_or_none()
        if user is None:
            logger.info("Webhook user.updated for unknown clerk user %s; ignoring", clerk_user_id)
        else:
            first_name = _clean_name(data.get("first_name"))
            last_name = _clean_name(data.get("last_name"))
            if first_name:
                user.first_name = first_name
            if last_name:
                user.last_name = last_name
            email = _primary_email(data)
            if email:
                user.email = email
            await db.flush()
            logger.info("Webhook user.updated refreshed profile for user %s", user.id)

    elif event_type == "user.deleted":
        result = await db.execute(select(User.id).where(User.clerk_user_id == clerk_user_id))
        row = result.first()
        if row is None:
            logger.info("Webhook user.deleted for unknown clerk user %s; ignoring", clerk_user_id)
        else:
            await user_service.delete_user(db, row[0])
            logger.info("Webhook user.deleted removed local row for clerk user %s", clerk_user_id)

    else:
        logger.info("Webhook event %s ignored", event_type)

    return {"ok": True}
