from fastapi import APIRouter

from . import (
    auth,
    favorites,
    health,
    listing_images,
    listings,
    time_slots,
    users,
    verification,
    webhooks,
)

router = APIRouter(prefix="/v1")

router.include_router(auth.router, prefix="/auth")
router.include_router(users.router)
router.include_router(listings.router)
router.include_router(listing_images.router)
router.include_router(time_slots.router)
router.include_router(verification.router)
router.include_router(verification.admin_router)
router.include_router(favorites.router)
router.include_router(health.router)
router.include_router(webhooks.router)
