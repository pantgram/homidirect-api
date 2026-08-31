from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.dependencies.auth import get_current_user, verify_user_ownership
from app.models.user import User
from app.schemas.user import (
    UpdateUserRequest,
    UserDetailResponse,
    UserWithRoleResponse,
)
from app.services import user as user_service

router = APIRouter(prefix="/users", tags=["Users"])


@router.get("/me", response_model=UserWithRoleResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "first_name": current_user.first_name,
        "last_name": current_user.last_name,
        "email": current_user.email,
        "role": current_user.role,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/{user_id}", response_model=UserDetailResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    verify_user_ownership(user_id, current_user)
    row = await user_service.get_user_by_id(db, user_id)
    return {"user": {
        "id": row.id,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "email": row.email,
        "role": row.role,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }}


@router.patch("/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: int,
    body: UpdateUserRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await user_service.get_user_by_id(db, user_id)
    verify_user_ownership(user_id, current_user)
    data = body.model_dump(exclude_none=True)
    user = await user_service.update_user(db, user_id, data)
    return {"user": {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }}


@router.delete("/{user_id}", status_code=204)
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await user_service.get_user_by_id(db, user_id)
    verify_user_ownership(user_id, current_user)
    await user_service.delete_user(db, user_id)
