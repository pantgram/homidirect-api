from fastapi import APIRouter

from . import (
    auth,
    availability_slots,
    bookings,
    favorites,
    geocoding,
    google_auth,
    health,
    listing_images,
    listings,
    users,
    verification,
)

router = APIRouter(prefix="/v1")

router.include_router(google_auth.router)
router.include_router(auth.router, prefix="/auth")
router.include_router(users.router)
router.include_router(listings.router)
router.include_router(listing_images.router)
router.include_router(bookings.router)
router.include_router(availability_slots.router)
router.include_router(verification.router)
router.include_router(verification.admin_router)
router.include_router(geocoding.router)
router.include_router(favorites.router)
router.include_router(health.router)
