import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.models.listing_image import ListingImage
from app.utils.errors import ConflictError, ForbiddenError, NotFoundError
from app.utils.storage import delete_from_r2, get_key_from_url, upload_to_r2


async def get_images_by_listing_id(db: AsyncSession, listing_id: int):
    result = await db.execute(select(ListingImage).where(ListingImage.listing_id == listing_id))
    return result.scalars().all()


async def get_image_by_id(db: AsyncSession, image_id: int):
    result = await db.execute(select(ListingImage).where(ListingImage.id == image_id))
    return result.scalar_one_or_none()


async def _get_image_count(db: AsyncSession, listing_id: int) -> int:
    result = await db.execute(select(func.count()).select_from(ListingImage).where(ListingImage.listing_id == listing_id))
    return result.scalar() or 0


async def upload_listing_image(db: AsyncSession, listing_id: int, file_bytes: bytes, filename: str, mimetype: str):
    count = await _get_image_count(db, listing_id)
    if count >= settings.max_images_per_listing:
        raise ConflictError(f"Maximum of {settings.max_images_per_listing} images per listing reached")

    sanitized = "".join(c if c.isalnum() or c in ".-" else "_" for c in filename)
    key = f"listings/{listing_id}/{int(time.time() * 1000)}-{sanitized}"
    url = upload_to_r2(key, file_bytes, mimetype)

    img = ListingImage(url=url, listing_id=listing_id)
    db.add(img)
    await db.flush()
    await db.refresh(img)
    return img


async def delete_image(db: AsyncSession, image_id: int, listing_id: int) -> bool:
    img = await get_image_by_id(db, image_id)
    if not img:
        raise NotFoundError("Image not found")

    if img.listing_id != listing_id:
        raise ForbiddenError("Image does not belong on this listing")
    delete_from_r2(get_key_from_url(img.url))
    await db.delete(img)
    return True


async def delete_images_by_listing_id(db: AsyncSession, listing_id: int) -> int:
    images = await get_images_by_listing_id(db, listing_id)
    for img in images:
        delete_from_r2(get_key_from_url(img.url))
    for img in images:
        await db.delete(img)
    return len(images)
