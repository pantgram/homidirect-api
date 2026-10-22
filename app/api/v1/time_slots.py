from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.config.logging_config import logger
from app.dependencies.auth import (
    get_current_user,
    get_optional_user,
    require_role,
    verify_listing_ownership,
    verify_time_slot_ownership,
)
from app.models.user import User
from app.schemas.time_slot import (
    ClaimSlotRequest,
    CreateSlotRequest,
    PatchSlotRequest,
    ProposeSlotRequest,
    TimeSlotDetailResponse,
    TimeSlotsListResponse,
)
from app.services import listing as listing_service
from app.services import time_slot as time_slot_service
from app.services.time_slot import SLOT_DURATION

router = APIRouter(prefix="/time-slots", tags=["Time Slots"])


def _format_slot(s, include_private: bool) -> dict:
    """One serializer, viewer-dependent: public shape for OPEN rows, participant shape
    (candidate + meet link) once claimed."""
    data = {
        "id": s.id,
        "status": s.status,
        "listing_id": s.listing_id,
        "landlord_id": s.listing.landlord_id,
        "start_time": s.start_time.isoformat(),
        "end_time": (s.start_time + SLOT_DURATION).isoformat(),
        "type": s.type,
        "created_at": s.created_at.isoformat(),
        "is_booked": s.status != "OPEN",
    }
    if include_private:
        data["candidate_id"] = s.candidate_id
        data["meet_link"] = s.meet_link
        data["landlord_created"] = s.landlord_created
    return data


# NOTE: static paths ("/me") must be registered before "/{slot_id}" or FastAPI would
# try to parse "me" as a slot id.


@router.get("/me", response_model=TimeSlotsListResponse)
async def get_my_time_slots(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    slots = await time_slot_service.get_bookings_by_user(db, current_user.id)
    return {"time_slots": [_format_slot(s, include_private=True) for s in slots]}


@router.get("/listing/{listing_id}/available", response_model=TimeSlotsListResponse)
async def get_available_slots(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    await listing_service.get_public_listing(db, listing_id, current_user)
    slots = await time_slot_service.get_available_slots(db, listing_id)
    return {"time_slots": [_format_slot(s, include_private=False) for s in slots]}


@router.get("/listing/{listing_id}", response_model=TimeSlotsListResponse)
async def get_slots_by_listing(listing_id: int, db: AsyncSession = Depends(get_db)):
    slots = await time_slot_service.get_slots_by_listing(db, listing_id)
    return {"time_slots": [_format_slot(s, include_private=False) for s in slots]}


@router.get("/listing/{listing_id}/bookings", response_model=TimeSlotsListResponse)
async def get_listing_bookings(
    listing_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await verify_listing_ownership(listing_id, db, current_user)
    slots = await time_slot_service.get_bookings_by_listing(db, listing_id)
    return {"time_slots": [_format_slot(s, include_private=True) for s in slots]}


@router.post("", status_code=201, response_model=TimeSlotDetailResponse)
async def create_slot(
    body: CreateSlotRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("LANDLORD", "BOTH", "ADMIN")),
):
    data = body.model_dump(exclude_none=True)
    slot = await time_slot_service.create_slot(db, data, current_user)
    logger.info("Slot %s created for listing %s by user %s", slot.id, body.listing_id, current_user.id)
    return {"time_slot": _format_slot(slot, include_private=slot.status != "OPEN")}


@router.post("/propose", status_code=201, response_model=TimeSlotDetailResponse)
async def propose_slot(
    body: ProposeSlotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = body.model_dump(exclude_none=True)
    slot = await time_slot_service.propose(db, data, current_user, background_tasks)
    logger.info("Time slot %s proposed for listing %s by user %s", slot.id, slot.listing_id, current_user.id)
    return {"time_slot": _format_slot(slot, include_private=True)}


@router.post("/{slot_id}/claim", status_code=201, response_model=TimeSlotDetailResponse)
async def claim_slot(
    slot_id: int,
    body: ClaimSlotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    data = body.model_dump(exclude_none=True)
    slot = await time_slot_service.claim(db, slot_id, data, current_user, background_tasks)
    logger.info("Time slot %s claimed for listing %s by user %s", slot.id, slot.listing_id, current_user.id)
    return {"time_slot": _format_slot(slot, include_private=True)}


@router.get("/{slot_id}", response_model=TimeSlotDetailResponse)
async def get_time_slot(
    slot_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_user),
):
    slot = await time_slot_service.get_slot_by_id(db, slot_id)
    if slot.status != "OPEN":
        # Claimed/proposed windows are visible only to their participants.
        await verify_time_slot_ownership(slot_id, db, current_user)
    return {"time_slot": _format_slot(slot, include_private=slot.status != "OPEN")}


@router.patch("/{slot_id}", response_model=TimeSlotDetailResponse)
async def update_time_slot(
    slot_id: int,
    body: PatchSlotRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await verify_time_slot_ownership(slot_id, db, current_user)
    data = body.model_dump(exclude_none=True)
    slot = await time_slot_service.update_time_slot(db, slot_id, data, current_user, background_tasks)
    logger.info("Time slot %s updated by user %s", slot_id, current_user.id)
    return {"time_slot": _format_slot(slot, include_private=slot.status != "OPEN")}


@router.delete("/{slot_id}", status_code=204)
async def delete_time_slot(
    slot_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await verify_time_slot_ownership(slot_id, db, current_user)
    await time_slot_service.delete_time_slot(db, slot_id, current_user, background_tasks)
    logger.info("Time slot %s deleted by user %s", slot_id, current_user.id)
