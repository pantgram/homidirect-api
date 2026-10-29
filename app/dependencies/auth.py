from clerk_backend_api import AuthenticateRequestOptions, authenticate_request
from fastapi import Depends, Request, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config.database import get_db
from app.config.logging_config import logger
from app.config.settings import settings
from app.models.listing import Listing
from app.models.user import User
from app.utils.errors import ForbiddenError, NotFoundError, UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False, description="Clerk session token")

def authenticate_clerk_request(request: Request) -> dict:
    """Verify the Clerk session token on the request and return its claims.

    Thin wrapper around the clerk-backend-api SDK, which reads the
    ``Authorization: Bearer`` header itself (with a ``__session`` cookie
    fallback). ``jwt_key`` (PEM from the dashboard) enables networkless local
    verification; omitted, the SDK falls back to JWKS (auto key rotation,
    ~5 min cache). ``authorized_parties`` is the ``azp`` allowlist — per
    Clerk's docs, omitting it can open replay/CSRF vectors.
    """
    state = authenticate_request(
        request,
        AuthenticateRequestOptions(
            secret_key=settings.clerk_secret_key,
            jwt_key=settings.clerk_jwt_key or None,
            authorized_parties=settings.clerk_authorized_parties_list or None,
            accepts_token=["session_token"],
        ),
    )
    logger.info("Clerk token verification state: %s", state)
    if not state.is_signed_in:
        reason = state.reason.name if state.reason is not None else state.status.name
        logger.warning("Clerk token verification failed: %s", reason)
        raise UnauthorizedError("Unauthorized")
    return state.payload


async def get_current_user(request: Request, _: HTTPAuthorizationCredentials | None = Security(bearer_scheme),db: AsyncSession = Depends(get_db)) -> User:
    payload = authenticate_clerk_request(request)
    clerk_user_id = payload.get("sub")
    if not clerk_user_id:
        raise UnauthorizedError("Unauthorized")

    result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        # Valid Clerk token but no local profile row yet. get_current_user
        # never auto-creates: POST /auth/sync is the only creation entry point.
        raise UnauthorizedError("Unauthorized")
    if user.status in ("BANNED", "SUSPENDED"):
        raise ForbiddenError(f"Account is {user.status.lower()}")
    return user


async def get_optional_user(request: Request, db: AsyncSession = Depends(get_db)) -> User | None:
    try:
        payload = authenticate_clerk_request(request)
        clerk_user_id = payload.get("sub")
        if not clerk_user_id:
            return None
        result = await db.execute(select(User).where(User.clerk_user_id == clerk_user_id))
        user = result.scalar_one_or_none()
    except UnauthorizedError:
        return None
    if user and user.status in ("BANNED", "SUSPENDED"):
        return None
    return user


def require_role(*roles: str):
    async def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == "ADMIN":
            return current_user
        if current_user.role not in roles:
            raise ForbiddenError("Insufficient permissions")
        return current_user

    return _check


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "ADMIN":
        raise ForbiddenError("Admin access required")
    return current_user


def verify_user_ownership(user_id: int, current_user: User) -> User:
    if current_user.role == "ADMIN":
        return current_user
    if current_user.id != user_id:
        raise NotFoundError("User not found")
    return current_user


async def verify_listing_ownership(listing_id: int, db: AsyncSession, current_user: User) -> User:
    if current_user.role == "ADMIN":
        return current_user

    result = await db.execute(select(Listing.landlord_id).where(Listing.id == listing_id))
    row = result.first()
    if not row:
        raise NotFoundError("Listing not found")
    if row[0] != current_user.id:
        raise ForbiddenError("You do not own this listing")
    return current_user


async def verify_time_slot_ownership(slot_id: int, db: AsyncSession, current_user: User | None) -> User:
    """Verify the viewer may act on a time slot: the listing's landlord, the claiming
    candidate, or an admin. Accepts an anonymous viewer (None) so public routes can
    reuse the check; outsiders get a 404, never a 403."""
    from app.models.time_slot import TimeSlot

    result = await db.execute(select(TimeSlot).options(joinedload(TimeSlot.listing)).where(TimeSlot.id == slot_id))
    slot = result.scalar_one_or_none()
    if current_user is not None and current_user.role == "ADMIN":
        return current_user
    # An OPEN row has no candidate; it still "belongs" to the listing's landlord so the
    # owner can act on it.
    if (
        (not slot)
        or current_user is None
        or (slot.candidate_id != current_user.id and slot.listing.landlord_id != current_user.id)
    ):
        raise NotFoundError("Time slot not found")
    return current_user
