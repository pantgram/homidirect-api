"""slot-only bookings

Revision ID: c190c9732040
Revises: a9d3f6b1e4c8
Create Date: 2026-10-13 22:05:50.238710
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c190c9732040"
down_revision: Union[str, None] = "a9d3f6b1e4c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Data cleanup is deliberate (user decision): delete legacy free-form bookings instead of
    # failing, then dedupe slot collisions (the old check-then-act race produced duplicates).
    # Both must run before SET NOT NULL and the unique index.
    op.execute("DELETE FROM bookings WHERE availability_slot_id IS NULL")
    op.execute(
        "DELETE FROM bookings "
        "WHERE availability_slot_id IS NOT NULL "
        "AND id NOT IN ("
        "  SELECT MIN(id) FROM bookings WHERE availability_slot_id IS NOT NULL GROUP BY availability_slot_id"
        ")"
    )
    op.alter_column("bookings", "availability_slot_id", existing_type=sa.INTEGER(), nullable=False)
    op.drop_constraint(op.f("bookings_availability_slot_id_fkey"), "bookings", type_="foreignkey")
    op.create_foreign_key(
        op.f("bookings_availability_slot_id_fkey"),
        "bookings",
        "availability_slots",
        ["availability_slot_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("uq_bookings_availability_slot_id", "bookings", ["availability_slot_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_bookings_availability_slot_id", table_name="bookings")
    op.drop_constraint(op.f("bookings_availability_slot_id_fkey"), "bookings", type_="foreignkey")
    op.create_foreign_key(
        op.f("bookings_availability_slot_id_fkey"),
        "bookings",
        "availability_slots",
        ["availability_slot_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("bookings", "availability_slot_id", existing_type=sa.INTEGER(), nullable=True)
    # ### end Alembic commands ###
