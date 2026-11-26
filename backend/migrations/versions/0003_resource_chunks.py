"""Store document fragments, source locations and versioned vectors."""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB

revision = "0003_resource_chunks"
down_revision = "0002_resources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "resource_chunks",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("resource_id", sa.Uuid(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("locator", JSONB(), nullable=False),
        sa.Column("embedding", Vector(512), nullable=False),
        sa.Column("embedding_model", sa.String(200), nullable=False),
        sa.Column("chunk_config", sa.String(100), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_resource_chunks"),
        sa.ForeignKeyConstraint(
            ["resource_id"], ["resources.id"], name="fk_resource_chunks_resource_id_resources", ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "resource_id", "embedding_model", "chunk_config", "chunk_index",
            name="uq_resource_chunks_configuration_position",
        ),
        sa.CheckConstraint("chunk_index >= 0", name="ck_resource_chunks_position"),
    )


def downgrade() -> None:
    op.drop_table("resource_chunks")
