from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config.logging_config import logger
from app.models.listing import Listing
from app.models.time_slot import TimeSlot
from app.models.user import User
from app.utils.email import (
    send_booking_cancelled_email,
    send_booking_confirmed_email,
    send_booking_created_email,
    send_booking_declined_email,
)
from app.utils.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError

# Every slot is exactly 30 minutes long; the end time is derived, never stored.
SLOT_DURATION = timedelta(minutes=30)

# Terminal states never persist as rows: DECLINED/CANCELLED on a landlord-created slot
# reset it to OPEN (the window becomes available again) and delete candidate-proposed rows.
VALID_TRANSITIONS = {
    "OPEN": [],
    "PENDING": ["CONFIRMED", "DECLINED", "CANCELLED"],
    "CONFIRMED": ["CANCELLED"],
    "DECLINED": [],
    "CANCELLED": [],
}


def _validate_meet_link(slot_type: str, meet_link: str | None) -> None:
    # A meeting link only makes sense on a REMOTE slot.
    if meet_link and slot_type == "ON_SITE":
        raise ValidationError("ON_SITE slots cannot have a meeting link")


def _ensure_utc(dt: datetime) -> datetime:
    # SQLite (tests) returns naive datetimes for TIMESTAMP columns; treat those as UTC.
    # Postgres (asyncpg) returns timezone-aware ones.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _full_name(user: User) -> str:
    return f"{user.first_name} {user.last_name}"


def _ensure_owner(slot: TimeSlot, current_user) -> None:
    # The landlord is resolved through the listing — time_slots has no landlord_id column.
    if current_user.role != "ADMIN" and slot.listing.landlord_id != current_user.id:
        raise ForbiddenError("You do not own this slot")


async def _load_slot(db: AsyncSession, slot_id: int) -> TimeSlot:
    result = await db.execute(select(TimeSlot).options(joinedload(TimeSlot.listing)).where(TimeSlot.id == slot_id))
    slot = result.scalar_one_or_none()
    if not slot:
        raise NotFoundError("Time slot not found")
    return slot


# --- Availability: landlord-authored windows ---


async def create_slot(db: AsyncSession, data: dict, current_user):
    listing_r = await db.execute(select(Listing).where(Listing.id == data["listing_id"]))
    listing = listing_r.scalar_one_or_none()
    if not listing:
        raise NotFoundError("Listing not found")
    if current_user.role != "ADMIN" and listing.landlord_id != current_user.id:
        raise ForbiddenError("You do not own this listing")

    _validate_meet_link(data["type"], data.get("meet_link"))

    # OPEN + landlord_created are the model defaults: a fresh slot is pure availability.
    slot = TimeSlot(
        listing_id=listing.id,
        start_time=data["start_time"],
        type=data["type"],
        meet_link=data.get("meet_link"),
    )
    db.add(slot)
    await db.flush()
    await db.refresh(slot)
    slot.listing = listing
    logger.info("Slot %s created for listing %s", slot.id, data["listing_id"])
    return slot


async def get_slots_by_listing(db: AsyncSession, listing_id: int):
    result = await db.execute(
        select(TimeSlot)
        .options(joinedload(TimeSlot.listing))
        .where(TimeSlot.listing_id == listing_id)
        .order_by(TimeSlot.start_time)
    )
    return result.scalars().all()


async def get_available_slots(db: AsyncSession, listing_id: int):
    # Available = landlord-authored (OPEN) and in the future; claimed or proposed windows
    # are not bookable.
    result = await db.execute(
        select(TimeSlot)
        .options(joinedload(TimeSlot.listing))
        .where(
            TimeSlot.listing_id == listing_id,
            TimeSlot.status == "OPEN",
            TimeSlot.start_time >= datetime.now(timezone.utc),
        )
        .order_by(TimeSlot.start_time)
    )
    return result.scalars().all()


async def get_slot_by_id(db: AsyncSession, slot_id: int):
    result = await db.execute(select(TimeSlot).options(joinedload(TimeSlot.listing)).where(TimeSlot.id == slot_id))
    slot = result.scalar_one_or_none()
    if not slot:
        raise NotFoundError("Time slot not found")
    return slot


async def update_slot(db: AsyncSession, slot: TimeSlot, data: dict, current_user) -> TimeSlot:
    """Landlord fields (start_time, type). Ownership is re-checked here because the
    router's slot ownership check also admits the claiming candidate."""
    _ensure_owner(slot, current_user)

    new_type = data.get("type")
    if new_type and new_type != slot.type:
        # The meeting type is locked as soon as someone claims or proposes the window.
        if slot.status != "OPEN":
            raise ConflictError("Cannot change the type of a claimed slot")
        slot.type = new_type
        if new_type == "ON_SITE":
            slot.meet_link = None

    if "start_time" in data:
        # Rescheduling is safe on any status.
        slot.start_time = data["start_time"]

    await db.flush()
    logger.info("Slot %s updated", slot.id)
    return slot


# --- Bookings: claimed/proposed windows ---


async def claim(db: AsyncSession, slot_id: int, data: dict, current_user, background_tasks: BackgroundTasks):
    slot = await _load_slot(db, slot_id)
    listing = slot.listing

    if listing.publication_status != "ACTIVE":
        raise NotFoundError("Listing not found")
    if listing.landlord_id == current_user.id:
        raise ConflictError("Cannot book your own listing")
    if slot.status != "OPEN":
        raise ConflictError("Time slot is already booked")
    if _ensure_utc(slot.start_time) < datetime.now(timezone.utc):
        raise ValidationError("Cannot book a slot in the past")
    _validate_meet_link(slot.type, data.get("meet_link"))

    # Atomic claim: the conditional UPDATE is race-safe by construction. A concurrent
    # request that claimed the slot first makes our rowcount 0, which surfaces as 409 —
    # no row lock, unique index or IntegrityError retry needed.
    claim_result = await db.execute(
        update(TimeSlot)
        .where(TimeSlot.id == slot.id, TimeSlot.status == "OPEN")
        .values(status="PENDING", candidate_id=current_user.id, meet_link=data.get("meet_link"))
        .execution_options(synchronize_session=False)
    )
    if claim_result.rowcount == 0:
        raise ConflictError("Time slot is already booked")
    # Mirror the claimed values onto the in-session instance so the router can format
    # the response without re-selecting.
    slot.status = "PENDING"
    slot.candidate_id = current_user.id
    slot.meet_link = data.get("meet_link")

    try:
        landlord_r = await db.execute(select(User).where(User.id == listing.landlord_id))
        landlord = landlord_r.scalar_one_or_none()
        if landlord:
            background_tasks.add_task(
                send_booking_created_email,
                landlord.email,
                _full_name(landlord),
                _full_name(current_user),
                listing.title_el,
                listing.id,
                slot.start_time.isoformat(),
                slot.id,
            )
    except Exception:
        logger.warning("Failed to queue booking created email for slot %s", slot.id, exc_info=True)

    return slot


async def propose(db: AsyncSession, data: dict, current_user, background_tasks: BackgroundTasks):
    listing_result = await db.execute(
        select(Listing).where(Listing.id == data["listing_id"], Listing.publication_status == "ACTIVE")
    )
    listing = listing_result.scalar_one_or_none()
    if not listing:
        raise NotFoundError("Listing not found")

    if listing.landlord_id == current_user.id:
        raise ConflictError("Cannot propose a time on your own listing")

    _validate_meet_link(data["type"], data.get("meet_link"))
    if _ensure_utc(data["start_time"]) < datetime.now(timezone.utc):
        raise ValidationError("Cannot propose a time in the past")

    duplicate = await db.execute(
        select(TimeSlot.id).where(TimeSlot.listing_id == listing.id, TimeSlot.start_time == data["start_time"])
    )
    if duplicate.first():
        raise ConflictError("A slot already exists at this time")

    slot = TimeSlot(
        listing_id=listing.id,
        start_time=data["start_time"],
        status="PENDING",
        candidate_id=current_user.id,
        landlord_created=False,
        type=data["type"],
        meet_link=data.get("meet_link"),
    )
    db.add(slot)
    await db.flush()
    await db.refresh(slot)
    slot.listing = listing

    try:
        landlord_r = await db.execute(select(User).where(User.id == listing.landlord_id))
        landlord = landlord_r.scalar_one_or_none()
        if landlord:
            background_tasks.add_task(
                send_booking_created_email,
                landlord.email,
                _full_name(landlord),
                _full_name(current_user),
                listing.title_el,
                listing.id,
                slot.start_time.isoformat(),
                slot.id,
            )
    except Exception:
        logger.warning("Failed to queue booking created email for slot %s", slot.id, exc_info=True)

    return slot


async def _release(db: AsyncSession, slot: TimeSlot, background_tasks: BackgroundTasks, actor, reason: str) -> None:
    """DECLINED/CANCELLED cleanup. A landlord-created window returns to OPEN availability
    (candidate + meet link cleared); a candidate-proposed row never was real availability,
    so it is deleted outright."""
    tenant_r = await db.execute(select(User).where(User.id == slot.candidate_id))
    landlord_r = await db.execute(select(User).where(User.id == slot.listing.landlord_id))
    tenant = tenant_r.scalar_one_or_none()
    landlord = landlord_r.scalar_one_or_none()
    start_iso = slot.start_time.isoformat()
    title = slot.listing.title_el

    if slot.landlord_created:
        slot.status = "OPEN"
        slot.candidate_id = None
        slot.meet_link = None
    else:
        # Keep the requested status on the response even though the row is going away.
        slot.status = reason
        await db.delete(slot)
    await db.flush()

    try:
        if not (tenant and landlord):
            return
        if reason == "DECLINED":
            background_tasks.add_task(
                send_booking_declined_email,
                tenant.email,
                _full_name(tenant),
                _full_name(landlord),
                title,
                start_iso,
            )
        elif actor.id == tenant.id:
            background_tasks.add_task(
                send_booking_cancelled_email,
                landlord.email,
                _full_name(landlord),
                _full_name(tenant),
                title,
                start_iso,
            )
        else:
            background_tasks.add_task(
                send_booking_cancelled_email,
                tenant.email,
                _full_name(tenant),
                _full_name(landlord),
                title,
                start_iso,
            )
    except Exception:
        logger.warning("Failed to queue booking release email for slot %s", slot.id, exc_info=True)


async def update_booking(
    db: AsyncSession, slot: TimeSlot, data: dict, current_user, background_tasks: BackgroundTasks
) -> tuple[TimeSlot, bool]:
    """Booking transition (status, meet_link). Returns (slot, row_deleted): a released
    candidate-proposed row is deleted and only kept around to format the response."""
    listing = slot.listing

    new_status = data.get("status")
    if new_status:
        if new_status in ("CONFIRMED", "DECLINED") and listing.landlord_id != current_user.id:
            raise ConflictError("Only landlord can confirm or decline bookings")
        allowed = VALID_TRANSITIONS.get(slot.status, [])
        if new_status not in allowed:
            raise ConflictError(f"Cannot transition booking from {slot.status} to {new_status}")

    if new_status in ("DECLINED", "CANCELLED"):
        await _release(db, slot, background_tasks, current_user, reason=new_status)
        return slot, not slot.landlord_created

    _validate_meet_link(slot.type, data.get("meet_link"))

    for key, value in data.items():
        if value is not None:
            setattr(slot, key, value)
    await db.flush()

    if slot.status == "CONFIRMED":
        try:
            tenant_r = await db.execute(select(User).where(User.id == slot.candidate_id))
            landlord_r = await db.execute(select(User).where(User.id == listing.landlord_id))
            tenant = tenant_r.scalar_one_or_none()
            landlord = landlord_r.scalar_one_or_none()
            if tenant and landlord:
                background_tasks.add_task(
                    send_booking_confirmed_email,
                    tenant.email,
                    _full_name(tenant),
                    _full_name(landlord),
                    listing.title_el,
                    slot.start_time.isoformat(),
                    slot.meet_link,
                )
        except Exception:
            logger.warning("Failed to queue booking status email for slot %s", slot.id, exc_info=True)

    return slot, False


async def delete_booking(db: AsyncSession, slot: TimeSlot, current_user, background_tasks: BackgroundTasks) -> bool:
    await _release(db, slot, background_tasks, current_user, reason="CANCELLED")
    logger.info("Booking %s deleted", slot.id)
    return True


async def get_bookings_by_user(db: AsyncSession, user_id: int):
    # OPEN rows are pure availability, not bookings: they only appear here once claimed
    # (or proposed), which is also how landlords discover pending proposals.
    result = await db.execute(
        select(TimeSlot)
        .options(joinedload(TimeSlot.listing))
        .join(TimeSlot.listing)
        .where(
            or_(TimeSlot.candidate_id == user_id, Listing.landlord_id == user_id),
            TimeSlot.status != "OPEN",
        )
        .order_by(TimeSlot.start_time)
    )
    return result.scalars().all()


async def get_bookings_by_listing(db: AsyncSession, listing_id: int):
    result = await db.execute(
        select(TimeSlot)
        .options(joinedload(TimeSlot.listing))
        .where(TimeSlot.listing_id == listing_id, TimeSlot.status != "OPEN")
        .order_by(TimeSlot.start_time)
    )
    return result.scalars().all()


async def get_booking_by_id(db: AsyncSession, slot_id: int):
    return await _load_slot(db, slot_id)


# --- Dispatchers for the unified PATCH / DELETE endpoints ---


async def update_time_slot(db: AsyncSession, slot_id: int, data: dict, current_user, background_tasks: BackgroundTasks):
    """PATCH dispatcher. Branches on the requested fields — landlord fields
    (start_time, type) vs booking transition (status, meet_link). Validation lives in
    the service; the request schema accepts all four fields."""
    slot = await _load_slot(db, slot_id)
    row_deleted = False

    if "status" in data or "meet_link" in data:
        slot, row_deleted = await update_booking(db, slot, data, current_user, background_tasks)
    if ("start_time" in data or "type" in data) and not row_deleted:
        slot = await update_slot(db, slot, data, current_user)
    return slot


async def delete_time_slot(db: AsyncSession, slot_id: int, current_user, background_tasks: BackgroundTasks) -> bool:
    """DELETE dispatcher. An OPEN window is pure availability and is hard-deleted by its
    owner; claimed/proposed windows are released instead of silently destroying a booking."""
    slot = await _load_slot(db, slot_id)
    if slot.status == "OPEN":
        _ensure_owner(slot, current_user)
        await db.delete(slot)
        logger.info("Slot %s deleted", slot_id)
        return True

    await delete_booking(db, slot, current_user, background_tasks)
    logger.info("Time slot %s released", slot_id)
    return True
