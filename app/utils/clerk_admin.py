import httpx
from clerk_backend_api import Clerk, ClerkBaseError

from app.config.logging_config import logger
from app.config.settings import settings

_client: Clerk | None = None


def _get_client() -> Clerk:
    global _client
    if _client is None:
        _client = Clerk(bearer_auth=settings.clerk_secret_key)
    return _client


async def fetch_clerk_user(clerk_user_id: str) -> dict:
    """Fetch profile data for a Clerk user via the Backend API.

    Returns ``{"email", "first_name", "last_name"}``; the primary email is
    resolved from ``primary_email_address_id`` against ``email_addresses[]``.
    Propagates ClerkBaseError (has .status_code) to the caller.
    """
    clerk_user = await _get_client().users.get_async(user_id=clerk_user_id)
    email = None
    for address in clerk_user.email_addresses or []:
        if address.id == clerk_user.primary_email_address_id:
            email = address.email_address
            break
    if email is None and clerk_user.email_addresses:
        email = clerk_user.email_addresses[0].email_address
    return {
        "email": email,
        "first_name": clerk_user.first_name,
        "last_name": clerk_user.last_name,
    }


async def delete_auth_user(clerk_user_id: str) -> bool:
    """Delete the Clerk user via the Backend API.

    No-op (with a warning) when CLERK_SECRET_KEY is not configured, so the API
    keeps working in environments without admin credentials.
    """
    if not settings.clerk_secret_key:
        logger.warning(
            "CLERK_SECRET_KEY not configured; skipping Clerk auth user deletion for %s",
            clerk_user_id,
        )
        return False
    try:
        await _get_client().users.delete_async(user_id=clerk_user_id)
    except ClerkBaseError as exc:
        logger.error(
            "Clerk Backend API returned %s while deleting user %s: %s",
            exc.status_code,
            clerk_user_id,
            exc,
        )
        return False
    except httpx.HTTPError:
        logger.exception("Failed to reach Clerk Backend API while deleting user %s", clerk_user_id)
        return False
    return True
