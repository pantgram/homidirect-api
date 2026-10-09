import uuid

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.logging_config import logger
from app.config.settings import settings
from app.models.listing import Listing
from app.models.user import User
from app.utils.errors import ForbiddenError, NotFoundError, UnauthorizedError
from app.services import auth as auth_service

security_scheme = HTTPBearer(auto_error=False)

_jwk_client: PyJWKClient | None = None


def _get_jwk_client() -> PyJWKClient:
    global _jwk_client
    if _jwk_client is None:
        _jwk_client = PyJWKClient(
            f"{settings.supabase_url}/auth/v1/.well-known/jwks.json",
            cache_keys=True,
            lifespan=600,
        )
    return _jwk_client


def verify_supabase_jwt(token: str) -> dict:
    """Verify a Supabase Auth access token and return its claims.

    Uses the project's JWKS endpoint (asymmetric signing keys) by default, or the
    legacy HS256 shared secret when SUPABASE_JWT_SECRET is configured.
    """
    issuer = f"{settings.supabase_url.rstrip('/')}/auth/v1"
    logger.info("Verifying JWT with token: %s", token)
    try:
        if settings.supabase_jwt_secret:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                issuer=issuer,
                audience=audience,
            )
        else:
            signing_key = _get_jwk_client().get_signing_key_from_jwt(token)
            audience = "authenticated"
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[signing_key.algorithm_name],
                issuer=issuer,
                audience=audience,
            )
    except jwt.PyJWTError as exc:
        logger.warning("JWT verification failed: %s: %s", type(exc).__name__, exc)
        raise UnauthorizedError("Unauthorized") from exc
    if payload.get("role") != "authenticated":
        logger.warning("JWT role is not authenticated: %s", payload.get("role"))
        raise UnauthorizedError("Unauthorized")
    return payload


def _extract_supabase_user_id(payload: dict) -> uuid.UUID | None:
    sub = payload.get("sub")
    if not sub:
        return None
    try:
        return uuid.UUID(sub)
    except (ValueError, AttributeError):
        return None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Unauthorized")
    payload = verify_supabase_jwt(credentials.credentials)
    logger.info("JWT payload: %s", payload)
    supabase_user_id = _extract_supabase_user_id(payload)
    if supabase_user_id is None:
        raise UnauthorizedError("Unauthorized")

    result = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
    user = result.scalar_one_or_none()
    if user is None:
        metadata = payload.get("user_metadata", {})
        user = await auth_service.sync_user(db, supabase_user_id, payload.get("email"), metadata.get("first_name"), metadata.get("last_name"), metadata.get("role"))
    if user.status in ("BANNED", "SUSPENDED"):
        raise ForbiddenError(f"Account is {user.status.lower()}")
    return user


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if credentials is None:
        return None
    try:
        payload = verify_supabase_jwt(credentials.credentials)
        supabase_user_id = _extract_supabase_user_id(payload)
        if supabase_user_id is None:
            return None
        result = await db.execute(select(User).where(User.supabase_user_id == supabase_user_id))
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


async def verify_booking_ownership(booking_id: int, db: AsyncSession, current_user: User) -> User:
    from app.models.booking import Booking
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if current_user.role == "ADMIN":
        return current_user
    if (not booking) or (booking.candidate_id != current_user.id and booking.landlord_id != current_user.id):
        raise NotFoundError("Booking not found")
    return current_user
