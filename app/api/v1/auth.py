import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.limiter import limiter
from app.config.logging_config import logger
from app.dependencies import auth as auth_deps
from app.schemas.user import UserDetailResponse
from app.services import auth as auth_service
from app.utils.errors import UnauthorizedError

router = APIRouter(prefix="", tags=["Auth"])


@router.post("/sync", response_model=UserDetailResponse)
@limiter.limit("10/minute")
async def sync_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    credentials=Depends(auth_deps.security_scheme),
):
    """Create or update the app profile row for the authenticated Supabase user.

    Single write path for profile data: Supabase auth.users is the source of
    truth, this endpoint only mirrors it. The frontend calls this after
    supabase-js signUp **and** after every `supabase.auth.updateUser`
    (names or email change). Idempotent.

    Profile claims are read from the token's ``user_metadata`` — keys are
    snake_case (``first_name``, ``last_name``), matching what signUp writes.
    """
    if credentials is None:
        raise UnauthorizedError("Unauthorized")
    claims = auth_deps.verify_supabase_jwt(credentials.credentials)
    sub = claims.get("sub")
    email = claims.get("email")
    metadata = claims.get("user_metadata", {})
    if not sub or not email:
        raise UnauthorizedError("Unauthorized")
    try:
        supabase_user_id = uuid.UUID(sub)
    except (ValueError, AttributeError):
        raise UnauthorizedError("Unauthorized")

    user = await auth_service.sync_user(
        db, supabase_user_id, email, metadata.get("first_name"), metadata.get("last_name"), metadata.get("role")
    )
    logger.info("Profile synced for user %s", user.id)
    return {"user": {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "role": user.role,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }}
