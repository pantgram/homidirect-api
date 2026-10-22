"""unify bookings and availability_slots into time_slots

Revision ID: b2f9d4c8e1a7
Revises: 4a9db007b3e8
Create Date: 2026-10-21 10:00:00.000000

A booking becomes just a claimed slot: one `time_slots` table where OPEN rows are
landlord-authored availability and claimed/proposed rows carry a candidate. Data is
merged preserving the availability slot ids; the `landlord_id` denormalization and the
`uq_bookings_availability_slot_id` unique index disappear with the old tables.

The downgrade is LOSSY by design: rows released in the unified model (a cancelled or
declined landlord-created booking reset to OPEN) come back as plain availability with
no booking row, and candidate-proposed rows have no old-world counterpart at all.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b2f9d4c8e1a7"
down_revision: Union[str, None] = "4a9db007b3e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enum types are created manually because the models declare create_type=False.


    op.create_table(
        "time_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "OPEN",
                "PENDING",
                "CONFIRMED",
                "DECLINED",
                "CANCELLED",
                name="slot_status",
                create_type=False,
            ),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column("candidate_id", sa.Integer(), nullable=True),
        sa.Column("landlord_created", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "type",
            sa.Enum("REMOTE", "ON_SITE", name="slot_type", create_type=False),
            nullable=False,
        ),
        sa.Column("meet_link", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("time_slots_candidate_id_idx", "time_slots", ["candidate_id"], unique=False)
    op.create_index("time_slots_listing_id_idx", "time_slots", ["listing_id"], unique=False)
    op.create_index("time_slots_start_time_idx", "time_slots", ["start_time"], unique=False)
    op.create_index("time_slots_status_idx", "time_slots", ["status"], unique=False)

    # Merge rows keeping the slot ids. Each availability slot holds at most one booking
    # (guaranteed by the old uq_bookings_availability_slot_id unique index), so the LEFT
    # JOIN cannot fan out. Claimed windows (PENDING/CONFIRMED) keep status, candidate and
    # meet link; terminal bookings (CANCELLED/DECLINED) and unbooked slots become plain
    # OPEN availability. type is inferred from the meet link.
    op.execute(
        """
        INSERT INTO time_slots
            (id, listing_id, start_time, status, candidate_id, landlord_created, type, meet_link, created_at)
        SELECT
            s.id,
            s.listing_id,
            s.start_time,
            CASE
                WHEN b.id IS NOT NULL AND b.status IN ('PENDING', 'CONFIRMED')
                    THEN b.status::text::slot_status
                ELSE 'OPEN'::slot_status
            END,
            CASE
                WHEN b.id IS NOT NULL AND b.status IN ('PENDING', 'CONFIRMED') THEN b.candidate_id
                ELSE NULL
            END,
            TRUE,
            CASE WHEN b.meet_link IS NOT NULL THEN 'REMOTE'::slot_type ELSE 'ON_SITE'::slot_type END,
            CASE
                WHEN b.id IS NOT NULL AND b.status IN ('PENDING', 'CONFIRMED') THEN b.meet_link
                ELSE NULL
            END,
            s.created_at
        FROM availability_slots s
        LEFT JOIN bookings b ON b.availability_slot_id = s.id
        """
    )

    op.drop_index("uq_bookings_availability_slot_id", table_name="bookings")
    op.drop_index("bookings_availability_slot_id_idx", table_name="bookings")
    op.drop_index("bookings_candidate_id_idx", table_name="bookings")
    op.drop_index("bookings_landlord_id_idx", table_name="bookings")
    op.drop_index("bookings_listing_id_idx", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("availability_slots_is_booked_idx", table_name="availability_slots")
    op.drop_index("availability_slots_landlord_id_idx", table_name="availability_slots")
    op.drop_index("availability_slots_listing_id_idx", table_name="availability_slots")
    op.drop_index("availability_slots_start_time_idx", table_name="availability_slots")
    op.drop_table("availability_slots")
    op.execute("DROP TYPE booking_status")


def downgrade() -> None:
    # Lossy: see module docstring.
    op.execute("CREATE TYPE booking_status AS ENUM ('PENDING', 'CONFIRMED', 'DECLINED', 'CANCELLED')")

    op.create_table(
        "availability_slots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("is_booked", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["landlord_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("availability_slots_is_booked_idx", "availability_slots", ["is_booked"], unique=False)
    op.create_index("availability_slots_landlord_id_idx", "availability_slots", ["landlord_id"], unique=False)
    op.create_index("availability_slots_listing_id_idx", "availability_slots", ["listing_id"], unique=False)
    op.create_index("availability_slots_start_time_idx", "availability_slots", ["start_time"], unique=False)

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "CONFIRMED",
                "DECLINED",
                "CANCELLED",
                name="booking_status",
                create_type=False,
            ),
            server_default="PENDING",
            nullable=True,
        ),
        sa.Column("scheduled_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("meet_link", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("landlord_id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("availability_slot_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["availability_slot_id"], ["availability_slots.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["landlord_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["listing_id"], ["listings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("bookings_availability_slot_id_idx", "bookings", ["availability_slot_id"], unique=False)
    op.create_index("bookings_candidate_id_idx", "bookings", ["candidate_id"], unique=False)
    op.create_index("bookings_landlord_id_idx", "bookings", ["landlord_id"], unique=False)
    op.create_index("bookings_listing_id_idx", "bookings", ["listing_id"], unique=False)
    op.create_index("uq_bookings_availability_slot_id", "bookings", ["availability_slot_id"], unique=True)

    # Split the unified rows back out. availability_slots keeps the slot ids (landlord_id
    # resolved through the listing, as the unified table no longer stores it); only
    # still-claimed rows (PENDING/CONFIRMED) reappear as bookings, reusing their slot id.
    op.execute(
        """
        INSERT INTO availability_slots (id, listing_id, landlord_id, start_time, is_booked, created_at)
        SELECT ts.id, ts.listing_id, l.landlord_id, ts.start_time, (ts.status <> 'OPEN'), ts.created_at
        FROM time_slots ts
        JOIN listings l ON l.id = ts.listing_id
        """
    )
    op.execute(
        """
        INSERT INTO bookings
            (id, status, scheduled_at, meet_link, created_at,
             candidate_id, landlord_id, listing_id, availability_slot_id)
        SELECT ts.id, ts.status::text::booking_status, ts.start_time, ts.meet_link, ts.created_at,
               ts.candidate_id, l.landlord_id, ts.listing_id, ts.id
        FROM time_slots ts
        JOIN listings l ON l.id = ts.listing_id
        WHERE ts.status IN ('PENDING', 'CONFIRMED')
        """
    )

    op.drop_table("time_slots")
    op.execute("DROP TYPE slot_status")
    op.execute("DROP TYPE slot_type")
