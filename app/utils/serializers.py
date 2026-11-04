from sqlalchemy import asc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.listing_image import ListingImage


async def get_primary_images(db: AsyncSession, listing_ids: list[int]) -> dict:
    if not listing_ids:
        return {}
    result = await db.execute(
        select(ListingImage).where(ListingImage.listing_id.in_(listing_ids)).order_by(asc(ListingImage.created_at))
    )
    images = result.scalars().all()
    img_map = {}
    for img in images:
        if img.listing_id and img.listing_id not in img_map:
            img_map[img.listing_id] = {
                "id": img.id,
                "url": img.url,
                "listing_id": img.listing_id,
                "created_at": img.created_at,
            }
    return img_map
