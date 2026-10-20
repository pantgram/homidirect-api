"""supabase auth migration

Link users to Supabase Auth via supabase_user_id and drop columns now owned by
Supabase Auth (password, reset-token tracking, token revocation, email_verified).

Revision ID: c3f8a1d6e2b4
Revises: 95c2c6236605
Create Date: 2026-09-29 00:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = 'c3f8a1d6e2b4'
down_revision: Union[str, None] = '95c2c6236605'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('supabase_user_id', postgresql.UUID(as_uuid=True), nullable=False))
    op.create_index('ix_users_supabase_user_id', 'users', ['supabase_user_id'], unique=True)
    op.drop_column('users', 'password')
    op.drop_column('users', 'email_verified')
    op.drop_column('users', 'password_reset_token')
    op.drop_column('users', 'password_reset_expires')
    op.drop_column('users', 'token_version')


def downgrade() -> None:
    op.add_column('users', sa.Column('token_version', sa.Integer(), server_default='0', nullable=False))
    op.add_column('users', sa.Column('password_reset_expires', sa.TIMESTAMP(timezone=True), nullable=True))
    op.add_column('users', sa.Column('password_reset_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('users', sa.Column('password', sa.Text(), nullable=True))
    op.drop_index('ix_users_supabase_user_id', table_name='users')
    op.drop_column('users', 'supabase_user_id')
