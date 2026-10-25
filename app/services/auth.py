import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import logger
from app.models.user import User
from app.schemas.user import VALID_ROLES
from app.utils.errors import ConflictError

# Matches the first_name/last_name column limit on users.
_MAX_NAME_LENGTH = 100


async def sync_user(
    db: AsyncSession,
    supabase_user_id: uuid.UUID,
    email: str,
    first_name: str | None,
    last_name: str | None,
    role: str | None = None,
) -> User:
    """Create the app profile row for an authenticated Supabase user, or update
    the existing one from Supabase-owned claims. Idempotent; safe to call after
    every signup/login and after every supabase.auth.updateUser.

    Supabase is the single source of truth for email and names; the desired
    role comes from the /auth/sync request body: an allowlisted role is applied
    on create (TENANT fallback) and on update, anything else keeps the stored
    value. ADMIN can never be assigned here.
    """
    result = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
    user = result.scalar_one_or_none()

    if user is None:
        result = await db.execute(select(User.id).where(User.email == email))
        if result.scalar_one_or_none() is not None:
            logger.warning("Profile sync rejected: email already registered for supabase user %s", supabase_user_id)
            raise ConflictError("Email already registered")
        user = User(
            supabase_user_id=supabase_user_id,
            email=email,
            first_name=(first_name or "").strip()[:_MAX_NAME_LENGTH],
            last_name=(last_name or "").strip()[:_MAX_NAME_LENGTH],
            role=role if role in VALID_ROLES else "TENANT",
        )
        db.add(user)
    else:
        clean_first_name = (first_name or "").strip()[:_MAX_NAME_LENGTH]
        if clean_first_name:
            user.first_name = clean_first_name
        clean_last_name = (last_name or "").strip()[:_MAX_NAME_LENGTH]
        if clean_last_name:
            user.last_name = clean_last_name
        if role in VALID_ROLES:
            user.role = role
        if user.email != email:
            user.email = email

    await db.flush()
    await db.refresh(user)
    logger.info("Profile synced for user %s", user.id)
    return user
