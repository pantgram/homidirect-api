from datetime import datetime
from typing import Literal

from app.schemas.base import CamelModel


class TimeSlotResponse(CamelModel):
    """Unified slot shape. The participant fields (candidate_id, meet_link,
    landlord_created) are None in the public view of an OPEN slot."""

    id: int
    status: str
    listing_id: int
    landlord_id: int
    start_time: datetime
    end_time: datetime
    type: str
    created_at: datetime
    is_booked: bool
    candidate_id: int | None = None
    meet_link: str | None = None
    landlord_created: bool | None = None


class CreateSlotRequest(CamelModel):
    listing_id: int
    start_time: datetime
    type: Literal["REMOTE", "ON_SITE"]
    meet_link: str | None = None


class ClaimSlotRequest(CamelModel):
    meet_link: str | None = None


class ProposeSlotRequest(CamelModel):
    listing_id: int
    start_time: datetime
    type: Literal["REMOTE", "ON_SITE"]
    meet_link: str | None = None


class PatchSlotRequest(CamelModel):
    # Accepts both landlord fields and booking transition fields; the branching and
    # validation happen in the service layer.
    start_time: datetime | None = None
    type: Literal["REMOTE", "ON_SITE"] | None = None
    status: str | None = None
    meet_link: str | None = None


class TimeSlotDetailResponse(CamelModel):
    time_slot: TimeSlotResponse


class TimeSlotsListResponse(CamelModel):
    time_slots: list[TimeSlotResponse]
