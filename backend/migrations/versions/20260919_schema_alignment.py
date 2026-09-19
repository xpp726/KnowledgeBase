"""align the initial schema with the current MySQL models

Revision ID: 20260919_schema_alignment
Revises: f0b1c75457c2
Create Date: 2026-09-19

The original initial migration predates the users/folders tables, the
conversation ownership fields, and the DATETIME/LONGTEXT schema conversion.
This migration makes a fresh ``alembic upgrade head`` produce the same schema
used by the current application.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql


revision: str = "20260919_schema_alignment"
down_revision: Union[str, Sequence[str], None] = "f0b1c75457c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _convert_epoch_column(table: str, column: str) -> None:
    """Convert legacy UNIX seconds before changing the column type."""
    op.execute(
        sa.text(
            f"UPDATE {table} SET {column} = FROM_UNIXTIME({column}) "
            f"WHERE {column} IS NOT NULL AND {column} > 0"
        )
    )


def _alter_datetime(table: str, column: str) -> None:
    _convert_epoch_column(table, column)
    op.alter_column(
        table,
        column,
        existing_type=sa.Float(),
        type_=sa.DateTime(),
        existing_nullable=False,
    )


def upgrade() -> None:
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
    op.create_index("ix_folders_kb_id", "folders", ["kb_id"], unique=False)
    op.create_index("ix_folders_parent_id", "folders", ["parent_id"], unique=False)
    op.create_index(
        "uq_folders_kb_parent_name",
        "folders",
        ["kb_id", "parent_id", "name"],
        unique=True,
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(255), nullable=False),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.add_column(
        "conversations",
        sa.Column("mode", sa.String(255), nullable=False, server_default="kb"),
    )
    op.add_column(
        "conversations",
        sa.Column("user_id", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index("ix_conversations_mode", "conversations", ["mode"], unique=False)
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)
    op.alter_column("conversations", "mode", server_default=None)
    op.alter_column("conversations", "user_id", server_default=None)

    op.add_column(
        "query_logs",
        sa.Column("mode", sa.String(255), nullable=False, server_default="kb"),
    )
    op.add_column(
        "query_logs",
        sa.Column("user_id", sa.String(255), nullable=False, server_default=""),
    )
    op.create_index("ix_query_logs_user_id", "query_logs", ["user_id"], unique=False)
    op.alter_column("query_logs", "mode", server_default=None)
    op.alter_column("query_logs", "user_id", server_default=None)

    op.add_column("documents", sa.Column("folder_id", sa.String(255), nullable=True))
    op.create_index("ix_documents_folder_id", "documents", ["folder_id"], unique=False)
    op.create_index(
        "ix_documents_folder_filename",
        "documents",
        ["folder_id", "file_name"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_documents_folder_id",
        "documents",
        "folders",
        ["folder_id"],
        ["folder_id"],
        ondelete="SET NULL",
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
            _alter_datetime(table, column)

    op.alter_column(
        "chunks",
        "text",
        existing_type=sa.String(255),
        type_=mysql.LONGTEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "documents",
        "error",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "knowledge_bases",
        "description",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "messages",
        "content",
        existing_type=sa.String(255),
        type_=mysql.LONGTEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "messages",
        "refs_json",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "query_logs",
        "question",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    op.alter_column(
        "query_logs",
        "answer",
        existing_type=sa.String(255),
        type_=mysql.LONGTEXT(),
        existing_nullable=False,
    )
    op.alter_column(
        "query_logs",
        "refs_json",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )


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
