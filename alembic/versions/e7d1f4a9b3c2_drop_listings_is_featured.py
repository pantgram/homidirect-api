"""drop listings.is_featured

A listing is featured iff featured_until > NOW(); the never-written boolean
column is redundant. No backfill: nothing in the codebase ever set it.

Revision ID: e7d1f4a9b3c2
Revises: 2adc8aa296dd
Create Date: 2026-10-23 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e7d1f4a9b3c2"
down_revision: Union[str, None] = "2adc8aa296dd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("listings_is_featured_idx", table_name="listings")
    op.drop_column("listings", "is_featured")


def downgrade() -> None:
    # same definition as the initial schema (95c2c6236605) for reversibility
    op.add_column(
        "listings",
        sa.Column("is_featured", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.create_index("listings_is_featured_idx", "listings", ["is_featured"], unique=False)
