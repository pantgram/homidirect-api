"""add date_built check constraint

Revision ID: 4a9db007b3e8
Revises: 991ac114d4aa
Create Date: 2026-10-18 13:39:18.187796
"""

from typing import Sequence, Union

from alembic import op

revision: str = "4a9db007b3e8"
down_revision: Union[str, None] = "991ac114d4aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safe for existing data: rows hold the current year (server default) or sane input.
    op.create_check_constraint(
        "date_built",
        "listings",
        "date_built >= 1800 AND date_built <= EXTRACT(YEAR FROM CURRENT_DATE)::INTEGER",
    )


def downgrade() -> None:
    op.drop_constraint("date_built", "listings", type_="check")
