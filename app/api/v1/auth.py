import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.limiter import limiter
from app.config.logging_config import logger
from app.dependencies import auth as auth_deps
from app.schemas.auth import SyncProfileRequest
from app.schemas.user import UserDetailResponse
from app.services import auth as auth_service
from app.utils.errors import UnauthorizedError

router = APIRouter(prefix="", tags=["Auth"])


@router.post("/sync", response_model=UserDetailResponse)
@limiter.limit("10/minute")
async def sync_profile(
    request: Request,
    body: SyncProfileRequest,
    db: AsyncSession = Depends(get_db),
    credentials=Depends(auth_deps.security_scheme),
):
    """Create or update the app profile row for the authenticated Supabase user.

    Call this after supabase-js signUp (once the user is confirmed). Idempotent.
    """
    if credentials is None:
        raise UnauthorizedError("Unauthorized")
    claims = auth_deps.verify_supabase_jwt(credentials.credentials)
    sub = claims.get("sub")
    email = claims.get("email")
    if not sub or not email:
        raise UnauthorizedError("Unauthorized")
    try:
        supabase_user_id = uuid.UUID(sub)
    except (ValueError, AttributeError):
        raise UnauthorizedError("Unauthorized")

    user = await auth_service.sync_user(db, supabase_user_id, email, body.first_name, body.last_name, body.role)
    logger.info("Profile synced for user %s", user.id)
    return {"user": {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }}
