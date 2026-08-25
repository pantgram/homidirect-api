"""drop listing_images.upload_session_id

The pending-session upload flow is replaced by draft listings:
images are uploaded directly to an existing (draft) listing.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-24
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM listing_images WHERE listing_id IS NULL")
    op.drop_column("listing_images", "upload_session_id")


def downgrade() -> None:
    op.add_column("listing_images", sa.Column("upload_session_id", sa.String(36), nullable=True))
