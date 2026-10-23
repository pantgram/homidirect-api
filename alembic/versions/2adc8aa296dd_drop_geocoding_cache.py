"""drop geocoding_cache

Revision ID: 2adc8aa296dd
Revises: b2f9d4c8e1a7
Create Date: 2026-10-22 22:00:55.946941
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "2adc8aa296dd"
down_revision: Union[str, None] = "b2f9d4c8e1a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # indexes geocoding_cache_hash_idx / geocoding_cache_expires_idx drop with the table
    op.drop_table("geocoding_cache")


def downgrade() -> None:
    # same definition as the initial schema (95c2c6236605) for reversibility
    op.create_table(
        "geocoding_cache",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("query_hash", sa.String(length=64), nullable=False),
        sa.Column("query_text", sa.String(length=500), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("lang", sa.String(length=2), nullable=True),
        sa.Column("results", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_hash"),
    )
    op.create_index("geocoding_cache_expires_idx", "geocoding_cache", ["expires_at"], unique=False)
    op.create_index("geocoding_cache_hash_idx", "geocoding_cache", ["query_hash"], unique=False)
