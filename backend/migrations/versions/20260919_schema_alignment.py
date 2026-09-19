"""align the initial schema with the current MySQL models

Revision ID: 20260919_schema_alignment
Revises: f0b1c75457c2
Create Date: 2026-09-19

The original initial migration predates the users/folders tables, the
conversation ownership fields, and the DATETIME/LONGTEXT schema conversion.
This migration is deliberately inspection-driven because older application
versions could have created part of the schema with ``create_all`` before
Alembic was introduced.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import context, op
from sqlalchemy.dialects import mysql


revision: str = "20260919_schema_alignment"
down_revision: Union[str, Sequence[str], None] = "f0b1c75457c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _inspector():
    if context.is_offline_mode():
        return None
    from sqlalchemy import inspect

    return inspect(op.get_bind())


def _has_table(table: str) -> bool:
    inspector = _inspector()
    # Offline SQL generation must follow the fresh-schema path because the
    # database cannot be inspected there.
    return inspector is not None and inspector.has_table(table)


def _columns(table: str) -> dict[str, dict]:
    inspector = _inspector()
    if inspector is None or not inspector.has_table(table):
        return {}
    return {column["name"]: column for column in inspector.get_columns(table)}


def _index_names(table: str) -> set[str]:
    inspector = _inspector()
    if inspector is None or not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def _foreign_key_names(table: str) -> set[str]:
    inspector = _inspector()
    if inspector is None or not inspector.has_table(table):
        return set()
    return {
        foreign_key["name"]
        for foreign_key in inspector.get_foreign_keys(table)
        if foreign_key.get("name")
    }


def _ensure_index(
    name: str, table: str, columns: list[str], *, unique: bool = False
) -> None:
    if name not in _index_names(table):
        op.create_index(name, table, columns, unique=unique)


def _ensure_column(
    table: str,
    column: sa.Column,
    *,
    server_default: str | None = None,
) -> None:
    if column.name in _columns(table):
        return
    if server_default is not None:
        column.server_default = server_default
    op.add_column(table, column)
    if server_default is not None:
        op.alter_column(table, column.name, server_default=None)


def _convert_epoch_column(table: str, column: str, *, nullable: bool) -> None:
    """Convert legacy UNIX seconds before changing a numeric column to DATETIME."""
    replacement = "NULL" if nullable else "NOW()"
    op.execute(
        sa.text(
            f"UPDATE {table} SET {column} = {replacement} "
            f"WHERE {column} IS NULL OR {column} <= 0"
        )
    )
    op.execute(
        sa.text(
            f"UPDATE {table} SET {column} = FROM_UNIXTIME({column}) "
            f"WHERE {column} IS NOT NULL AND {column} > 0"
        )
    )


def _normalize_datetime(table: str, column: str, *, nullable: bool) -> None:
    info = _columns(table).get(column)
    if info is None:
        return

    existing_type = info["type"]
    existing_nullable = bool(info.get("nullable", True))
    is_datetime = isinstance(existing_type, sa.DateTime)

    if not is_datetime:
        # A legacy numeric column must temporarily allow NULL so a sentinel
        # value such as last_login_at=0 can be normalized before the type change.
        if not existing_nullable:
            op.alter_column(
                table,
                column,
                existing_type=existing_type,
                existing_nullable=False,
                nullable=True,
            )
        _convert_epoch_column(table, column, nullable=nullable)
        op.alter_column(
            table,
            column,
            existing_type=existing_type,
            type_=sa.DateTime(),
            existing_nullable=True,
            nullable=nullable,
        )
        return

    if not nullable:
        # Existing nullable rows cannot be made NOT NULL without a value.
        op.execute(
            sa.text(
                f"UPDATE {table} SET {column} = NOW() "
                f"WHERE {column} IS NULL"
            )
        )
    if existing_nullable != nullable:
        op.alter_column(
            table,
            column,
            existing_type=existing_type,
            existing_nullable=existing_nullable,
            nullable=nullable,
        )


def _alter_text_columns() -> None:
    text_changes = (
        ("chunks", "text", sa.String(255), mysql.LONGTEXT()),
        ("documents", "error", sa.String(255), sa.Text()),
        ("knowledge_bases", "description", sa.String(255), sa.Text()),
        ("messages", "content", sa.String(255), mysql.LONGTEXT()),
        ("messages", "refs_json", sa.String(255), sa.Text()),
        ("query_logs", "question", sa.String(255), sa.Text()),
        ("query_logs", "answer", sa.String(255), mysql.LONGTEXT()),
        ("query_logs", "refs_json", sa.String(255), sa.Text()),
    )
    for table, column, existing_type, target_type in text_changes:
        if column in _columns(table):
            op.alter_column(
                table,
                column,
                existing_type=existing_type,
                type_=target_type,
                existing_nullable=False,
            )


def upgrade() -> None:
    if not _has_table("folders"):
        op.create_table(
            "folders",
            sa.Column("folder_id", sa.String(255), nullable=False),
            sa.Column("kb_id", sa.String(255), nullable=False),
            sa.Column("parent_id", sa.String(255), nullable=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("depth", sa.Integer(), nullable=False),
            sa.Column("is_system", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("folder_id"),
        )
    _ensure_index("ix_folders_kb_id", "folders", ["kb_id"])
    _ensure_index("ix_folders_parent_id", "folders", ["parent_id"])
    _ensure_index(
        "uq_folders_kb_parent_name",
        "folders",
        ["kb_id", "parent_id", "name"],
        unique=True,
    )

    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(255), nullable=False),
            sa.Column("username", sa.String(255), nullable=False),
            sa.Column("display_name", sa.String(255), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(255), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
    _ensure_index("ix_users_username", "users", ["username"], unique=True)

    _ensure_column(
        "conversations",
        sa.Column("mode", sa.String(255), nullable=False),
        server_default="kb",
    )
    _ensure_column(
        "conversations",
        sa.Column("user_id", sa.String(255), nullable=False),
        server_default="",
    )
    _ensure_index("ix_conversations_mode", "conversations", ["mode"])
    _ensure_index("ix_conversations_user_id", "conversations", ["user_id"])

    _ensure_column(
        "query_logs",
        sa.Column("mode", sa.String(255), nullable=False),
        server_default="kb",
    )
    _ensure_column(
        "query_logs",
        sa.Column("user_id", sa.String(255), nullable=False),
        server_default="",
    )
    _ensure_index("ix_query_logs_user_id", "query_logs", ["user_id"])

    _ensure_column("documents", sa.Column("folder_id", sa.String(255), nullable=True))
    _ensure_index("ix_documents_folder_id", "documents", ["folder_id"])
    _ensure_index(
        "ix_documents_folder_filename",
        "documents",
        ["folder_id", "file_name"],
    )
    if "fk_documents_folder_id" not in _foreign_key_names("documents"):
        op.create_foreign_key(
            "fk_documents_folder_id",
            "documents",
            "folders",
            ["folder_id"],
            ["folder_id"],
            ondelete="SET NULL",
        )

    timestamp_columns = {
        "chunks": (("created_at", False),),
        "conversations": (("created_at", False), ("updated_at", False)),
        "documents": (("created_at", False), ("updated_at", False)),
        "folders": (("created_at", False), ("updated_at", False)),
        "knowledge_bases": (("created_at", False), ("updated_at", False)),
        "messages": (("created_at", False),),
        "query_logs": (("created_at", False),),
        "users": (
            ("last_login_at", True),
            ("created_at", False),
            ("updated_at", False),
        ),
    }
    for table, columns in timestamp_columns.items():
        for column, nullable in columns:
            _normalize_datetime(table, column, nullable=nullable)

    _alter_text_columns()


def downgrade() -> None:
    op.alter_column(
        "query_logs", "refs_json", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "query_logs", "answer", existing_type=mysql.LONGTEXT(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "query_logs", "question", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "messages", "refs_json", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "messages", "content", existing_type=mysql.LONGTEXT(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "knowledge_bases", "description", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "documents", "error", existing_type=sa.Text(), type_=sa.String(255), existing_nullable=False
    )
    op.alter_column(
        "chunks", "text", existing_type=mysql.LONGTEXT(), type_=sa.String(255), existing_nullable=False
    )

    for table, columns in {
        "chunks": ("created_at",),
        "conversations": ("created_at", "updated_at"),
        "documents": ("created_at", "updated_at"),
        "knowledge_bases": ("created_at", "updated_at"),
        "messages": ("created_at",),
        "query_logs": ("created_at",),
    }.items():
        for column in columns:
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(),
                type_=sa.Float(),
                existing_nullable=False,
            )

    op.drop_constraint("fk_documents_folder_id", "documents", type_="foreignkey")
    op.drop_index("ix_documents_folder_filename", table_name="documents")
    op.drop_index("ix_documents_folder_id", table_name="documents")
    op.drop_column("documents", "folder_id")

    op.drop_index("ix_query_logs_user_id", table_name="query_logs")
    op.drop_column("query_logs", "user_id")
    op.drop_column("query_logs", "mode")
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_index("ix_conversations_mode", table_name="conversations")
    op.drop_column("conversations", "user_id")
    op.drop_column("conversations", "mode")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    op.drop_index("uq_folders_kb_parent_name", table_name="folders")
    op.drop_index("ix_folders_parent_id", table_name="folders")
    op.drop_index("ix_folders_kb_id", table_name="folders")
    op.drop_table("folders")
