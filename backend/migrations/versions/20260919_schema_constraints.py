"""normalize timestamp nullability and missing query log index

Revision ID: 20260919_schema_constraints
Revises: 20260919_schema_alignment
Create Date: 2026-09-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op


revision: str = "20260919_schema_constraints"
down_revision: Union[str, Sequence[str], None] = "20260919_schema_alignment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TIMESTAMP_COLUMNS = {
    "chunks": ("created_at",),
    "conversations": ("created_at", "updated_at"),
    "documents": ("created_at", "updated_at"),
    "folders": ("created_at", "updated_at"),
    "knowledge_bases": ("created_at", "updated_at"),
    "messages": ("created_at",),
    "query_logs": ("created_at",),
    # A user who has never logged in legitimately has no timestamp.
    "users": ("created_at", "updated_at"),
}


def _set_timestamp_nullability(nullable: bool) -> None:
    for table, columns in _TIMESTAMP_COLUMNS.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(),
                existing_nullable=not nullable,
                nullable=nullable,
            )


def upgrade() -> None:
    _set_timestamp_nullability(False)

    if context.is_offline_mode():
        op.create_index(
            "ix_query_logs_created_at",
            "query_logs",
            ["created_at"],
            unique=False,
        )
        return

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        from sqlalchemy import inspect

        index_names = {
            index["name"] for index in inspect(bind).get_indexes("query_logs")
        }
        if "ix_query_logs_created_at" not in index_names:
            op.create_index(
                "ix_query_logs_created_at",
                "query_logs",
                ["created_at"],
                unique=False,
            )
    else:
        op.create_index(
            "ix_query_logs_created_at",
            "query_logs",
            ["created_at"],
            unique=False,
        )


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_index("ix_query_logs_created_at", table_name="query_logs")
        _set_timestamp_nullability(True)
        return

    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        from sqlalchemy import inspect

        index_names = {
            index["name"] for index in inspect(bind).get_indexes("query_logs")
        }
        if "ix_query_logs_created_at" in index_names:
            op.drop_index("ix_query_logs_created_at", table_name="query_logs")
    else:
        op.drop_index("ix_query_logs_created_at", table_name="query_logs")

    _set_timestamp_nullability(True)
