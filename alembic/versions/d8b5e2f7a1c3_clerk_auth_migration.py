"""clerk auth migration

Clean break from Supabase Auth to Clerk: users.supabase_user_id (UUID) is
dropped and replaced by users.clerk_user_id (String(255), unique). Dev-only
data, nothing to copy.

Revision ID: d8b5e2f7a1c3
Revises: e7d1f4a9b3c2
Create Date: 2026-10-25 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "d8b5e2f7a1c3"
down_revision: Union[str, None] = "e7d1f4a9b3c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_users_supabase_user_id", table_name="users")
    op.drop_column("users", "supabase_user_id")
    op.add_column("users", sa.Column("clerk_user_id", sa.String(length=255), nullable=False))
    op.create_index(op.f("ix_users_clerk_user_id"), "users", ["clerk_user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_clerk_user_id"), table_name="users")
    op.drop_column("users", "clerk_user_id")
    op.add_column("users", sa.Column("supabase_user_id", postgresql.UUID(as_uuid=True), nullable=False))
    op.create_index("ix_users_supabase_user_id", "users", ["supabase_user_id"], unique=True)
