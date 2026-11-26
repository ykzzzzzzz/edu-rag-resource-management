import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import JSONB


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("role IN ('student', 'teacher', 'admin')", name="ck_users_role"),
        CheckConstraint(
            "username = lower(username) AND char_length(username) >= 3",
            name="ck_users_username_format",
        ),
        CheckConstraint("char_length(btrim(display_name)) > 0", name="ck_users_display_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AuthSession(Base):
    """登录会话。数据库只保存会话令牌的 SHA-256 哈希。"""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
        CheckConstraint("char_length(token_hash) = 64", name="ck_sessions_token_hash_length"),
        Index("ix_sessions_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    token_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE", name="fk_sessions_user_id_users")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        # 课程名大小写不敏感地唯一
        Index("uq_courses_name_lower", text("lower(name)"), unique=True),
        CheckConstraint("char_length(btrim(name)) > 0", name="ck_courses_name_not_blank"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Resource(Base):
    """教学资源。一个资源对应一个原始文件。审核状态与索引状态分别保存。"""

    __tablename__ = "resources"
    __table_args__ = (
        UniqueConstraint("storage_key", name="uq_resources_storage_key"),
        CheckConstraint(
            "review_status IN ('draft', 'pending', 'published', 'rejected', 'archived')",
            name="ck_resources_review_status",
        ),
        CheckConstraint(
            "index_status IN ('not_indexed', 'queued', 'processing', 'ready', 'failed')",
            name="ck_resources_index_status",
        ),
        CheckConstraint("char_length(btrim(title)) > 0", name="ck_resources_title_not_blank"),
        CheckConstraint("size_bytes > 0", name="ck_resources_size_bytes_positive"),
        # storage_key 同时是磁盘文件名，限定为 32 位小写十六进制，杜绝路径成分
        CheckConstraint("storage_key ~ '^[0-9a-f]{32}$'", name="ck_resources_storage_key_format"),
        CheckConstraint(
            "mime_type IN ('application/pdf', "
            "'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 'text/plain')",
            name="ck_resources_mime_type",
        ),
        # 已发布或已下架的资源一定有发布时间，其余状态一定没有
        CheckConstraint(
            "(review_status IN ('published', 'archived')) = (published_at IS NOT NULL)",
            name="ck_resources_published_at_consistent",
        ),
        # 尚未发布的资源不会进入索引流程
        CheckConstraint(
            "review_status IN ('published', 'archived') OR index_status = 'not_indexed'",
            name="ck_resources_unpublished_not_indexed",
        ),
        Index("ix_resources_owner_id", "owner_id"),
        Index("ix_resources_course_id", "course_id"),
        Index("ix_resources_review_status", "review_status"),
        Index("ix_resources_index_status", "index_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT", name="fk_resources_owner_id_users")
    )
    course_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("courses.id", ondelete="RESTRICT", name="fk_resources_course_id_courses")
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(64))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    review_status: Mapped[str] = mapped_column(String(16), default="draft", server_default=text("'draft'"))
    index_status: Mapped[str] = mapped_column(
        String(16), default="not_indexed", server_default=text("'not_indexed'")
    )
    index_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    index_attempt_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    index_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResourceReview(Base):
    """审核事件：通过、驳回、下架。提交与退回草稿不记录。"""

    __tablename__ = "resource_reviews"
    __table_args__ = (
        CheckConstraint("action IN ('approve', 'reject', 'archive')", name="ck_resource_reviews_action"),
        CheckConstraint(
            "action <> 'reject' OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)",
            name="ck_resource_reviews_reject_needs_reason",
        ),
        Index("ix_resource_reviews_resource_id", "resource_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resources.id", ondelete="CASCADE", name="fk_resource_reviews_resource_id_resources")
    )
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT", name="fk_resource_reviews_reviewer_id_users")
    )
    action: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceChunk(Base):
    __tablename__ = "resource_chunks"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "embedding_model", "chunk_config", "chunk_index",
            name="uq_resource_chunks_configuration_position",
        ),
        CheckConstraint("chunk_index >= 0", name="ck_resource_chunks_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("resources.id", ondelete="CASCADE", name="fk_resource_chunks_resource_id_resources")
    )
    chunk_index: Mapped[int]
    content: Mapped[str] = mapped_column(Text)
    locator: Mapped[dict[str, str | int]] = mapped_column(JSONB)
    embedding: Mapped[list[float]] = mapped_column(Vector(512))
    embedding_model: Mapped[str] = mapped_column(String(200))
    chunk_config: Mapped[str] = mapped_column(String(100))


QA_LOG_STATUSES = (
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


class QaLog(Base):
    """匿名问答日志。不保存用户 ID，也不保存拼接后的完整提示词。"""

    __tablename__ = "qa_logs"
    __table_args__ = (
        CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in QA_LOG_STATUSES) + ")",
            name="ck_qa_logs_status",
        ),
        CheckConstraint("char_length(btrim(question)) > 0", name="ck_qa_logs_question_not_blank"),
        CheckConstraint("jsonb_typeof(retrieved) = 'array'", name="ck_qa_logs_retrieved_array"),
        CheckConstraint("jsonb_typeof(cited_chunk_ids) = 'array'", name="ck_qa_logs_cited_chunk_ids_array"),
        CheckConstraint("jsonb_typeof(timings) = 'object'", name="ck_qa_logs_timings_object"),
        CheckConstraint("jsonb_typeof(model_config) = 'object'", name="ck_qa_logs_model_config_object"),
        Index("ix_qa_logs_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()")
    )
    course_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("courses.id", ondelete="SET NULL", name="fk_qa_logs_course_id_courses"), nullable=True
    )
    question: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(32))
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    # [{"chunk_id", "resource_id", "rank", "similarity"}]，按排名升序
    retrieved: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    cited_chunk_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    # {"retrieval_ms", "generation_ms", "total_ms"}
    timings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # 列名与计划一致；属性名避开 Pydantic 的保留名
    llm_config: Mapped[dict] = mapped_column("model_config", JSONB, default=dict, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
