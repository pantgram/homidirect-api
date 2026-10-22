from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base
from app.models.enums import slot_status_enum, slot_type_enum

if TYPE_CHECKING:
    from app.models.listing import Listing
    from app.models.user import User


class TimeSlot(Base):
    """A 30-minute viewing window. A booking is just a claimed slot: OPEN rows are
    landlord-authored availability, claimed/proposed rows carry a candidate."""

    __tablename__ = "time_slots"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    listing_id: Mapped[int] = mapped_column(
        sa.Integer, sa.ForeignKey("listings.id", ondelete="CASCADE"), nullable=False
    )
    start_time: Mapped[sa.DateTime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(slot_status_enum, nullable=False, server_default="OPEN")
    candidate_id: Mapped[int | None] = mapped_column(
        sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    landlord_created: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, server_default=sa.true())
    type: Mapped[str] = mapped_column(slot_type_enum, nullable=False)
    meet_link: Mapped[str | None] = mapped_column(sa.String(255))
    created_at: Mapped[sa.DateTime] = mapped_column(
        sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()
    )

    listing: Mapped["Listing"] = relationship("Listing", back_populates="time_slots")
    candidate: Mapped["User | None"] = relationship("User", foreign_keys=[candidate_id])

    __table_args__ = (
        sa.Index("time_slots_listing_id_idx", "listing_id"),
        sa.Index("time_slots_start_time_idx", "start_time"),
        sa.Index("time_slots_status_idx", "status"),
        sa.Index("time_slots_candidate_id_idx", "candidate_id"),
    )
