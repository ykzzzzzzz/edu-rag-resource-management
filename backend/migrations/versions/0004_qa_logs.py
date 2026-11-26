"""Store anonymous question-answering logs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_qa_logs"
down_revision = "0003_resource_chunks"
branch_labels = None
depends_on = None

STATUSES = (
    "answered",
    "insufficient_evidence",
    "llm_invalid_output",
    "llm_auth_failed",
    "llm_quota_exhausted",
    "llm_rate_limited",
    "llm_unavailable",
    "llm_timeout",
    "internal_error",
)


def upgrade() -> None:
    op.create_table(
        "qa_logs",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=True),
        sa.Column("question", sa.String(500), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("retrieved", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("cited_chunk_ids", JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("timings", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("model_config", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_qa_logs"),
        sa.ForeignKeyConstraint(
            ["course_id"], ["courses.id"], name="fk_qa_logs_course_id_courses", ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in STATUSES) + ")", name="ck_qa_logs_status"
        ),
        sa.CheckConstraint("char_length(btrim(question)) > 0", name="ck_qa_logs_question_not_blank"),
        sa.CheckConstraint("jsonb_typeof(retrieved) = 'array'", name="ck_qa_logs_retrieved_array"),
        sa.CheckConstraint("jsonb_typeof(cited_chunk_ids) = 'array'", name="ck_qa_logs_cited_chunk_ids_array"),
        sa.CheckConstraint("jsonb_typeof(timings) = 'object'", name="ck_qa_logs_timings_object"),
        sa.CheckConstraint("jsonb_typeof(model_config) = 'object'", name="ck_qa_logs_model_config_object"),
    )
    op.create_index("ix_qa_logs_created_at", "qa_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_qa_logs_created_at", table_name="qa_logs")
    op.drop_table("qa_logs")
