from datetime import datetime

from app.schemas.base import CamelModel


class AvailabilitySlotResponse(CamelModel):
    id: int
    listing_id: int
    landlord_id: int
    start_time: datetime
    end_time: datetime
    is_booked: bool
    created_at: datetime


class CreateAvailabilitySlotRequest(CamelModel):
    listing_id: int
    start_time: datetime


class UpdateAvailabilitySlotRequest(CamelModel):
    start_time: datetime | None = None
    is_booked: bool | None = None


class SlotDetailResponse(CamelModel):
    slot: AvailabilitySlotResponse


class SlotsListResponse(CamelModel):
    slots: list[AvailabilitySlotResponse]
