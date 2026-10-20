import uuid
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base
from app.models.enums import user_role_enum, user_status_enum

if TYPE_CHECKING:
    from app.models.interested_listing import InterestedListing
    from app.models.listing import Listing


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    supabase_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    role: Mapped[str] = mapped_column(user_role_enum, nullable=False)
    status: Mapped[str] = mapped_column(user_status_enum, nullable=False, server_default="ACTIVE")
    email: Mapped[str] = mapped_column(sa.String(255), nullable=False, unique=True)
    created_at: Mapped[sa.DateTime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now())
    updated_at: Mapped[sa.DateTime] = mapped_column(sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now())

    listings: Mapped[list["Listing"]] = relationship("Listing", foreign_keys="[Listing.landlord_id]", back_populates="landlord")
    verified_listings: Mapped[list["Listing"]] = relationship("Listing", foreign_keys="[Listing.verified_by]", back_populates="verified_by_user")
    interested_listings: Mapped[list["InterestedListing"]] = relationship("InterestedListing", back_populates="user")
