from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def update_user(db: AsyncSession, user_id: int, data: dict):
   

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")

    for key, value in data.items():
        if value is not None:
            setattr(user, key, value)
    user.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user_id: int) -> bool:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise NotFoundError("User not found")
    await db.delete(user)
    return True
