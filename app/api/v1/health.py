from datetime import datetime, timezone

from fastapi import APIRouter

from app.config.logging_config import logger
from app.schemas.common import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])

@router.get("", response_model=HealthResponse)
async def health_check():
    logger.debug("Health check requested")
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}
