from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.settings import settings
from app.dependencies.auth import require_role, verify_listing_ownership
from app.models.user import User
from app.schemas.listing_image import ListingImageDetailResponse, ListingImagesResponse
from app.services import listing_image as img_service
from app.utils.file_validation import validate_image

router = APIRouter(prefix="/listings", tags=["Listing Images"])


@router.get("/{listing_id}/images", response_model=ListingImagesResponse)
async def get_images(listing_id: int, db: AsyncSession = Depends(get_db)):
    images = await img_service.get_images_by_listing_id(db, listing_id)
    return {"images": [
        {
            "id": i.id,
            "url": i.url,
            "listing_id": i.listing_id,
            "upload_session_id": i.upload_session_id,
            "created_at": i.created_at.isoformat(),
        }
        for i in images
    ]}


@router.post("/{listing_id}/images", status_code=201, response_model=ListingImageDetailResponse)
async def upload_image(
    listing_id: int,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("LANDLORD", "BOTH")),
):
    await verify_listing_ownership(listing_id, db, current_user)
    file_bytes = await file.read()
    detected_type = validate_image(file_bytes, file.filename or "image", file.content_type, settings.max_file_size)

    img = await img_service.upload_listing_image(db, listing_id, file_bytes, file.filename or "image", detected_type)
    return {"image": {
        "id": img.id,
        "url": img.url,
        "listing_id": img.listing_id,
        "upload_session_id": img.upload_session_id,
        "created_at": img.created_at.isoformat(),
    }}


@router.delete("/{listing_id}/images/{image_id}", status_code=204)
async def delete_image(
    listing_id: int,
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("LANDLORD", "BOTH")),
):
    await verify_listing_ownership(listing_id, db, current_user)
    await img_service.delete_image(db, image_id)
