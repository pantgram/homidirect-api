"""remove Google auth columns from users

Google OAuth login is removed; email/password auth remains.
Drops users.google_id, users.auth_provider, and the auth_provider enum type.

Revision ID: 0006
Revises: d41c6499bca5
Create Date: 2026-09-27
"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "d41c6499bca5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


auth_provider_enum = postgresql.ENUM("EMAIL", "GOOGLE", name="auth_provider", create_type=False)


def upgrade() -> None:
    op.drop_constraint("users_google_id_key", "users", type_="unique")
    op.drop_column("users", "google_id")
    op.drop_column("users", "auth_provider")
    op.execute("DROP TYPE IF EXISTS auth_provider")


def downgrade() -> None:
    auth_provider_enum.create(op.get_bind(), checkfirst=True)
    op.add_column("users", sa.Column("google_id", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column("auth_provider", auth_provider_enum, server_default="EMAIL", nullable=False),
    )
    op.create_unique_constraint("users_google_id_key", "users", ["google_id"])
