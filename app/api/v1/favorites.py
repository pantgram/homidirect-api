from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.logging_config import logger
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.listing import PaginatedListingSearchPublicResponse
from app.schemas.user import (
    AddFavoriteResponse,
    CheckFavoriteResponse,
    FavoriteIdsResponse,
    RemoveFavoriteResponse,
)
from app.services.favorite import (get_favorites, get_favorite_ids, check_favorite, add_favorite, remove_favorite) 

router = APIRouter(prefix="/favorites", tags=["Favorites"])


@router.get("/", response_model=PaginatedListingSearchPublicResponse)
async def get_favorites(
    page: int = 1, limit: int = 15,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_favorites(db, current_user.id, page, limit)


@router.get("/ids", response_model=FavoriteIdsResponse)
async def get_favorite_ids(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ids = await get_favorite_ids(db, current_user.id)
    return {"favorite_ids": ids}


@router.get("/{listing_id}/check", response_model=CheckFavoriteResponse)
async def check_favorite(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    is_fav = await check_favorite(db, current_user.id, listing_id)
    return {"is_favorited": is_fav}


@router.post("/{listing_id}", response_model=AddFavoriteResponse)
async def add_favorite(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    added = await add_favorite(db, current_user.id, listing_id)
    logger.info("Listing %s favorited by user %s (added=%s)", listing_id, current_user.id, added)
    return {"success": True, "added": added, "message": "Favorite added" if added else "Already favorited"}


@router.delete("/{listing_id}", response_model=RemoveFavoriteResponse)
async def remove_favorite(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await remove_favorite(db, current_user.id, listing_id)
    logger.info("Listing %s removed from favorites by user %s", listing_id, current_user.id)
    return {"removed": True}
