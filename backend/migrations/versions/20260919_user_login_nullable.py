"""allow users who have never logged in to keep a NULL login timestamp

Revision ID: 20260919_user_login_nullable
Revises: 20260919_schema_constraints
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "20260919_user_login_nullable"
down_revision: Union[str, Sequence[str], None] = "20260919_schema_constraints"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "last_login_at",
        existing_type=sa.DateTime(),
        existing_nullable=False,
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET last_login_at = NOW() "
            "WHERE last_login_at IS NULL"
        )
    )
    op.alter_column(
        "users",
        "last_login_at",
        existing_type=sa.DateTime(),
        existing_nullable=True,
        nullable=False,
    )
