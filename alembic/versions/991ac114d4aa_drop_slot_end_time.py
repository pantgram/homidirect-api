"""drop slot end_time

Revision ID: 991ac114d4aa
Revises: c190c9732040
Create Date: 2026-10-17 18:57:16.874864
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "991ac114d4aa"
down_revision: Union[str, None] = "c190c9732040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Data cleanup is deliberate (user decision): slots are now fixed 30-minute windows defined
    # by start_time alone; the stored end_time values are dropped, not migrated.
    op.drop_column("availability_slots", "end_time")


def downgrade() -> None:
    # end_time is no longer derived from data: the server_default is an approximation so the
    # NOT NULL constraint can be re-added to a non-empty table, not a restoration of real values.
    op.add_column(
        "availability_slots",
        sa.Column("end_time", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )
