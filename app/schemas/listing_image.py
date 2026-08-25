from datetime import datetime

from app.schemas.base import CamelModel


class ListingImageResponse(CamelModel):
    id: int
    url: str
    listing_id: int | None
    created_at: datetime


class ListingImagesResponse(CamelModel):
    images: list[ListingImageResponse]


class ListingImageDetailResponse(CamelModel):
    image: ListingImageResponse
