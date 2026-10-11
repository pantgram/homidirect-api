"""remove featured_listing_purchases table and featured_purchase_status enum

Revision ID: a9d3f6b1e4c8
Revises: b4e8f2a1c7d9
Create Date: 2026-10-12 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'a9d3f6b1e4c8'
down_revision: Union[str, None] = 'b4e8f2a1c7d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FEATURED_PURCHASE_STATUS_VALUES = ('PENDING', 'COMPLETED', 'FAILED', 'REFUNDED')


def upgrade() -> None:
    op.drop_index('featured_purchases_status_idx', table_name='featured_listing_purchases')
    op.drop_index('featured_purchases_listing_id_idx', table_name='featured_listing_purchases')
    op.drop_index('featured_purchases_expires_at_idx', table_name='featured_listing_purchases')
    op.drop_table('featured_listing_purchases')
    op.execute("DROP TYPE IF EXISTS featured_purchase_status")


def downgrade() -> None:
    op.execute(
        "CREATE TYPE featured_purchase_status AS ENUM "
        "('PENDING', 'COMPLETED', 'FAILED', 'REFUNDED')"
    )
    op.create_table(
        'featured_listing_purchases',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('listing_id', sa.Integer(), nullable=False),
        sa.Column('purchased_by', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('currency', sa.String(length=3), server_default='EUR', nullable=False),
        sa.Column('status', sa.Enum(*FEATURED_PURCHASE_STATUS_VALUES, name='featured_purchase_status', create_type=False), server_default='PENDING', nullable=False),
        sa.Column('starts_at', sa.TIMESTAMP(), nullable=False),
        sa.Column('expires_at', sa.TIMESTAMP(), nullable=False),
        sa.Column('payment_reference', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['listing_id'], ['listings.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['purchased_by'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('featured_purchases_expires_at_idx', 'featured_listing_purchases', ['expires_at'], unique=False)
    op.create_index('featured_purchases_listing_id_idx', 'featured_listing_purchases', ['listing_id'], unique=False)
    op.create_index('featured_purchases_status_idx', 'featured_listing_purchases', ['status'], unique=False)
