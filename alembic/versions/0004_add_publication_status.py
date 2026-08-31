"""add listings.publication_status for draft lifecycle

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-23
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    publication_status = sa.Enum("DRAFT", "ACTIVE", name="publication_status")
    publication_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "listings",
        sa.Column("publication_status", publication_status, nullable=False, server_default="ACTIVE"),
    )
    op.create_index("listings_publication_status_idx", "listings", ["publication_status"])


def downgrade() -> None:
    op.drop_index("listings_publication_status_idx", table_name="listings")
    op.drop_column("listings", "publication_status")
    sa.Enum(name="publication_status").drop(op.get_bind(), checkfirst=True)
