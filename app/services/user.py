from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.logging_config import logger
from app.models.user import User
from app.utils.errors import NotFoundError


async def get_user_by_id(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(User.id, User.first_name, User.last_name, User.email, User.role, User.created_at)
        .where(User.id == user_id)
    )
    row = result.first()
    if row is None:
        raise NotFoundError("User not found")
    return row


async def delete_user(db: AsyncSession, user_id: int):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    clerk_user_id = user.clerk_user_id
    await db.delete(user)
    logger.info("User %s deleted", user_id)
    return clerk_user_id
