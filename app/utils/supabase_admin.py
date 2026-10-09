import uuid

import httpx

from app.config.logging_config import logger
from app.config.settings import settings


async def delete_auth_user(supabase_user_id: uuid.UUID) -> bool:
    """Delete the Supabase Auth user via the Admin API.

    No-op (with a warning) when SUPABASE_SERVICE_ROLE_KEY is not configured,
    so the API keeps working in environments without admin credentials.
    """
    if not settings.supabase_service_role_key:
        logger.warning(
            "SUPABASE_SERVICE_ROLE_KEY not configured; skipping Supabase auth user deletion for %s",
            supabase_user_id,
        )
        return False
    url = f"{settings.supabase_url}/auth/v1/admin/users/{supabase_user_id}"
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.delete(url, headers=headers, timeout=10.0)
    except httpx.HTTPError:
        logger.exception("Failed to reach Supabase Auth API while deleting user %s", supabase_user_id)
        return False
    if response.status_code >= 400:
        logger.error(
            "Supabase Auth API returned %s while deleting user %s: %s",
            response.status_code,
            supabase_user_id,
            response.text,
        )
        return False
    return True
