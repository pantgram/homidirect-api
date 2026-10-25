from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.security import HTTPAuthorizationCredentials
from app.config.database import get_db
from app.config.limiter import limiter
from app.config.logging_config import logger
from app.dependencies import auth
from app.schemas.auth import SyncUser
from app.schemas.user import UserDetailResponse
from app.services import auth as auth_service
from app.utils import clerk_admin
from app.utils.errors import UnauthorizedError

router = APIRouter(prefix="", tags=["Auth"])


@router.post("/sync", response_model=UserDetailResponse)
@limiter.limit("10/minute")
async def sync_profile(
    request: Request,
    body: SyncUser,
    db: AsyncSession = Depends(get_db),
    credentials: HTTPAuthorizationCredentials = Depends(auth.bearer_scheme)
):
    """Create or update the app profile row for the authenticated Clerk user.

    Single write path for profile creation: POST /auth/sync is the only
    endpoint that creates a profile row. The frontend calls this after Clerk
    sign-up **and** after every profile update (names or email change).
    Idempotent.

    Profile data (email, names) is fetched from the Clerk Backend API
    (``GET /v1/users/{id}``) — the token's ``sub`` identifies the user. The
    desired role travels in the request body; omitting it (null) keeps TENANT
    on create and the stored role on update.
    """
    if credentials is None:
        raise UnauthorizedError("Unauthorized")
    claims = auth.authenticate_clerk_request(request)
    sub = claims.get("sub")
    logger.info("Sync request for Clerk user %s", sub)
    if not sub:
        raise UnauthorizedError("Unauthorized")
    clerk_profile = await clerk_admin.fetch_clerk_user(sub)
    if not clerk_profile.get("email"):
        logger.error("Clerk user %s has no resolvable email address; rejecting sync", sub)
        raise UnauthorizedError("Unauthorized")
    user = await auth_service.sync_user(
        db, sub, clerk_profile["email"], clerk_profile.get("first_name"), clerk_profile.get("last_name"), body.role
    )
    logger.info("Profile synced for user %s", user.id)
    return {
        "user": {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "email": user.email,
            "role": user.role,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
    }
