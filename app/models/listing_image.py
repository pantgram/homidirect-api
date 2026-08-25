from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base

if TYPE_CHECKING:
    from app.models.listing import Listing


class ListingImage(Base):
    __tablename__ = "listing_images"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(sa.String(500), nullable=False)
    listing_id: Mapped[int | None] = mapped_column(sa.Integer, sa.ForeignKey("listings.id", ondelete="CASCADE"))
    created_at: Mapped[sa.DateTime] = mapped_column(sa.TIMESTAMP, nullable=False, server_default=sa.func.now())

    listing: Mapped["Listing | None"] = relationship("Listing", back_populates="images")
