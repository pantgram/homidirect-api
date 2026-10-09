import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import logger
from app.models.user import User
from app.utils.errors import ConflictError


async def sync_user(
    db: AsyncSession,
    supabase_user_id: uuid.UUID,
    email: str,
    first_name: str,
    last_name: str,
    role: str,
) -> User:
    """Create the app profile row for an authenticated Supabase user, or update
    the existing one. Idempotent; safe to call after every signup/login."""
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
            first_name=first_name,
            last_name=last_name,
            role=role,
        )
        db.add(user)
    else:
        user.first_name = first_name
        user.last_name = last_name
        user.role = role
        if user.email != email:
            user.email = email

    await db.flush()
    await db.refresh(user)
    logger.info("Profile synced for user %s", user.id)
    return user
