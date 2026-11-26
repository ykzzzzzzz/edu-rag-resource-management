"""创建资源表与审核记录表

Revision ID: 0002_resources
Revises: 0001_auth_courses
Create Date: 2026-11-26
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_resources"
down_revision: Union[str, None] = "0001_auth_courses"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resources",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("review_status", sa.String(16), server_default=sa.text("'draft'"), nullable=False),
        sa.Column("index_status", sa.String(16), server_default=sa.text("'not_indexed'"), nullable=False),
        sa.Column("index_error", sa.String(500), nullable=True),
        sa.Column("index_attempt_id", sa.Uuid(), nullable=True),
        sa.Column("index_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_resources"),
        sa.UniqueConstraint("storage_key", name="uq_resources_storage_key"),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name="fk_resources_owner_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], name="fk_resources_course_id_courses", ondelete="RESTRICT"
        ),
        sa.CheckConstraint(
            "review_status IN ('draft', 'pending', 'published', 'rejected', 'archived')",
            name="ck_resources_review_status",
        ),
        sa.CheckConstraint(
            "index_status IN ('not_indexed', 'queued', 'processing', 'ready', 'failed')",
            name="ck_resources_index_status",
        ),
        sa.CheckConstraint("char_length(btrim(title)) > 0", name="ck_resources_title_not_blank"),
        sa.CheckConstraint("size_bytes > 0", name="ck_resources_size_bytes_positive"),
        sa.CheckConstraint("storage_key ~ '^[0-9a-f]{32}$'", name="ck_resources_storage_key_format"),
        sa.CheckConstraint(
            "mime_type IN ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain')",
            name="ck_resources_mime_type",
        ),
        sa.CheckConstraint(
            "(review_status IN ('published', 'archived')) = (published_at IS NOT NULL)",
            name="ck_resources_published_at_consistent",
        ),
        sa.CheckConstraint(
            "review_status IN ('published', 'archived') OR index_status = 'not_indexed'",
            name="ck_resources_unpublished_not_indexed",
        ),
    )
    op.create_index("ix_resources_owner_id", "resources", ["owner_id"])
    op.create_index("ix_resources_course_id", "resources", ["course_id"])
    op.create_index("ix_resources_review_status", "resources", ["review_status"])
    op.create_index("ix_resources_index_status", "resources", ["index_status"])

    op.create_table(
        "resource_reviews",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("reviewer_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_resource_reviews"),
        sa.ForeignKeyConstraint(
            ["resource_id"],
            ["resources.id"],
            name="fk_resource_reviews_resource_id_resources",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_id"], ["users.id"], name="fk_resource_reviews_reviewer_id_users", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("action IN ('approve', 'reject', 'archive')", name="ck_resource_reviews_action"),
        sa.CheckConstraint(
            "action <> 'reject' OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="ck_resource_reviews_reject_needs_reason",
        ),
    )
    op.create_index("ix_resource_reviews_resource_id", "resource_reviews", ["resource_id"])


def downgrade() -> None:
    op.drop_index("ix_resource_reviews_resource_id", table_name="resource_reviews")
    op.drop_table("resource_reviews")
    op.drop_index("ix_resources_index_status", table_name="resources")
    op.drop_index("ix_resources_review_status", table_name="resources")
    op.drop_index("ix_resources_course_id", table_name="resources")
    op.drop_index("ix_resources_owner_id", table_name="resources")
    op.drop_table("resources")
