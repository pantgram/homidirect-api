"""remove zone_type, listing_status and available from listings

Revision ID: b4e8f2a1c7d9
Revises: c3f8a1d6e2b4
Create Date: 2026-10-12 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'b4e8f2a1c7d9'
down_revision: Union[str, None] = 'c3f8a1d6e2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ZONE_TYPE_VALUES = ('Residential', 'Agricultural', 'Commercial', 'Industrial', 'Regeneration')
LISTING_STATUS_VALUES = ('Renovated', 'Luxurious', 'Under construction', 'Neoclassical')


def upgrade() -> None:
    op.drop_index('listings_available_featured_idx', table_name='listings')
    op.drop_index('listings_available_idx', table_name='listings')
    op.drop_column('listings', 'available')
    op.drop_column('listings', 'listing_status')
    op.drop_column('listings', 'zone_type')
    op.execute("DROP TYPE IF EXISTS listing_status")
    op.execute("DROP TYPE IF EXISTS zone_type")


def downgrade() -> None:
    op.execute(
        "CREATE TYPE zone_type AS ENUM "
        "('Residential', 'Agricultural', 'Commercial', 'Industrial', 'Regeneration')"
    )
    op.execute(
        "CREATE TYPE listing_status AS ENUM "
        "('Renovated', 'Luxurious', 'Under construction', 'Neoclassical')"
    )
    op.add_column(
        'listings',
        sa.Column(
            'zone_type',
            sa.Enum(*ZONE_TYPE_VALUES, name='zone_type', create_type=False),
            server_default='Residential',
            nullable=False,
        ),
    )
    op.add_column(
        'listings',
        sa.Column(
            'listing_status',
            sa.Enum(*LISTING_STATUS_VALUES, name='listing_status', create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        'listings',
        sa.Column('available', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    )
    op.create_index('listings_available_idx', 'listings', ['available'], unique=False)
    op.create_index('listings_available_featured_idx', 'listings', ['available', 'is_featured'], unique=False)
