"""检索、问答流程与日志。路由层只做参数校验和依赖注入，流程在这里。

流程（计划第 7 节）：嵌入问题 -> 一条 SQL 检索 -> 证据门槛 -> 演示摘录或云端生成 -> 返回前重新确认引用可见性 -> 写日志。
"""

import logging
import re
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.embeddings import (
    EmbeddingModelError,
    EmbedderProvider,
    chunk_config_id,
    embedding_model_id,
)
from app.errors import AppError
from app.llm_client import (
    AUTH_FAILED,
    BAD_RESPONSE,
    QUOTA_EXHAUSTED,
    RATE_LIMITED,
    TIMEOUT,
    UNAVAILABLE,
    LlmClient,
    LlmError,
)
from app.models import Course, QaLog, Resource, ResourceChunk
from app.qa_prompt import PROMPT_VERSION, build_messages, validate_model_output

log = logging.getLogger(__name__)

INSUFFICIENT_ANSWER = "已发布资料中未找到足够依据"
DEMO_MAX_CITATIONS = 3
EXCERPT_MAX_CHARS = 200
LOCATOR_UNITS = {"pdf_page": "页", "docx_paragraph": "段", "txt_line": "行"}
_CITE_IN_TEXT = re.compile(r"\[(\d+)\]")

# 云端错误分类 -> (HTTP 状态, 错误码)；日志状态与错误码同名
LLM_ERRORS = {
    AUTH_FAILED: (503, "llm_auth_failed", "云端模型服务认证失败"),
    QUOTA_EXHAUSTED: (503, "llm_quota_exhausted", "云端模型服务额度不足"),
    RATE_LIMITED: (503, "llm_rate_limited", "云端模型服务请求过多，请稍后重试"),
    UNAVAILABLE: (503, "llm_unavailable", "云端模型服务暂不可用"),
    TIMEOUT: (504, "llm_timeout", "云端模型响应超时"),
    BAD_RESPONSE: (502, "llm_invalid_output", "云端模型返回的内容无法使用"),
}
LOGGED_ERROR_CODES = frozenset(code for _, code, _ in LLM_ERRORS.values())


@dataclass
class Hit:
    chunk_id: uuid.UUID
    resource_id: uuid.UUID
    rank: int
    similarity: float
    content: str
    locator: dict
    title: str
    course_name: str


@dataclass
class Draft:
    """一次问答的日志草稿，流程中逐步填充，结束时写入 qa_logs。"""

    question: str
    course_id: uuid.UUID | None
    settings: Settings
    started: float = field(default_factory=time.perf_counter)
    status: str = "internal_error"
    answer: str | None = None
    retrieved: list[dict] = field(default_factory=list)
    cited_chunk_ids: list[str] = field(default_factory=list)
    retrieval_ms: float | None = None
    generation_ms: float | None = None
    usage: dict | None = None

    def model_config_record(self) -> dict:
        s = self.settings
        cloud = s.qa_mode == "cloud"
        record = {
            "qa_mode": s.qa_mode,
            "provider": s.llm_provider if cloud else None,
            "model": s.llm_model.strip() if cloud else None,
            "embedding_model": embedding_model_id(s),
            "chunk_config": chunk_config_id(s),
            "top_k": s.retrieval_top_k,
            "min_similarity": s.retrieval_min_similarity,
            "prompt_version": PROMPT_VERSION if cloud else None,
        }
        if self.usage:
            record["usage"] = self.usage
        return record

    def timings(self) -> dict:
        return {
            "retrieval_ms": self.retrieval_ms,
            "generation_ms": self.generation_ms,
            "total_ms": ms_since(self.started),
        }


def ms_since(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)


def format_locator(locator: dict) -> str:
    unit = LOCATOR_UNITS.get(locator.get("type"), "")
    start, end = locator.get("start"), locator.get("end")
    span = f"{start}" if start == end else f"{start}–{end}"
    return f"第 {span} {unit}".strip()


def make_excerpt(content: str) -> str:
    text = content.strip()
    return text if len(text) <= EXCERPT_MAX_CHARS else text[:EXCERPT_MAX_CHARS].rstrip() + "…"


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------

def retrieve(db: Session, settings: Settings, vector: list[float], course_id: uuid.UUID | None) -> list[Hit]:
    """一条 SQL 完成全部限定。返回 Top-K（尚未应用相似度门槛），按排名升序。"""
    distance = ResourceChunk.embedding.cosine_distance(vector).label("distance")
    stmt = (
        select(
            ResourceChunk.id,
            ResourceChunk.resource_id,
            distance,
            ResourceChunk.content,
            ResourceChunk.locator,
            Resource.title,
            Course.name,
        )
        .join(Resource, Resource.id == ResourceChunk.resource_id)
        .join(Course, Course.id == Resource.course_id)
        .where(
            Resource.review_status == "published",
            Resource.index_status == "ready",
            ResourceChunk.embedding_model == embedding_model_id(settings),
            ResourceChunk.chunk_config == chunk_config_id(settings),
        )
        .order_by(distance, ResourceChunk.id)
        .limit(settings.retrieval_top_k)
    )
    if course_id is not None:
        stmt = stmt.where(Resource.course_id == course_id)
    return [
        Hit(
            chunk_id=row[0],
            resource_id=row[1],
            rank=rank,
            similarity=round(1.0 - float(row[2]), 6),
            content=row[3],
            locator=row[4],
            title=row[5],
            course_name=row[6],
        )
        for rank, row in enumerate(db.execute(stmt).all(), start=1)
    ]


def load_visible_chunks(db: Session, chunk_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    """重新读取仍然可见（资源 published 且 ready）的片段。引用的全部文字都从这里取，不用模型输出。"""
    if not chunk_ids:
        return {}
    stmt = (
        select(
            ResourceChunk.id,
            ResourceChunk.resource_id,
            ResourceChunk.content,
            ResourceChunk.locator,
            Resource.title,
            Course.name,
        )
        .join(Resource, Resource.id == ResourceChunk.resource_id)
        .join(Course, Course.id == Resource.course_id)
        .where(
            ResourceChunk.id.in_(chunk_ids),
            Resource.review_status == "published",
            Resource.index_status == "ready",
        )
    )
    return {
        row[0]: {"resource_id": row[1], "content": row[2], "locator": row[3], "title": row[4], "course_name": row[5]}
        for row in db.execute(stmt).all()
    }


def citation_payload(number: int, chunk_id: uuid.UUID, row: dict) -> dict:
    return {
        "number": number,
        "resource_id": str(row["resource_id"]),
        "chunk_id": str(chunk_id),
        "title": row["title"],
        "course_name": row["course_name"],
        "locator": {k: row["locator"][k] for k in ("type", "start", "end")},
        "excerpt": make_excerpt(row["content"]),
    }


def demo_answer(citations: list[dict]) -> str:
    """服务端拼成的纯文本。摘录里原有的 [n] 改成全角括号，避免被当成引用标记。"""
    lines = ["以下是已发布资料中与问题最相关的原文摘录："]
    for item in citations:
        excerpt = _CITE_IN_TEXT.sub(lambda m: f"［{m.group(1)}］", item["excerpt"])
        lines.append(f"{excerpt}[{item['number']}]")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 流程
# ---------------------------------------------------------------------------

def _insufficient(draft: Draft, mode: str) -> dict:
    draft.status = "insufficient_evidence"
    draft.answer = INSUFFICIENT_ANSWER
    draft.cited_chunk_ids = []
    return {"status": "insufficient_evidence", "mode": mode, "answer": INSUFFICIENT_ANSWER, "citations": []}


def _generate(draft: Draft, settings: Settings, question: str, qualified: list[Hit], transport) -> dict | None:
    """云端生成。返回已校验的输出，模型自己判定证据不足时返回 None。不合法时抛出 AppError。"""
    client = LlmClient(settings, transport=transport)
    if not client.configured:
        raise AppError(503, "llm_unavailable", "云端模型未配置，请联系管理员")
    chunks = [
        {"n": n, "source": hit.title, "locator": format_locator(hit.locator), "text": hit.content}
        for n, hit in enumerate(qualified, start=1)
    ]
    started = time.perf_counter()
    try:
        content, usage = client.chat(build_messages(question, chunks))
    except LlmError as exc:
        status, code, message = LLM_ERRORS[exc.kind]
        raise AppError(status, code, message) from None
    finally:
        draft.generation_ms = ms_since(started)
    draft.usage = usage
    checked = validate_model_output(content, set(range(1, len(qualified) + 1)))
    if not checked["structure_ok"]:
        raise AppError(502, "llm_invalid_output", "云端模型返回的内容无法使用")
    if checked["status"] == "insufficient_evidence":
        return None
    return checked


def _pipeline(
    draft: Draft,
    db: Session,
    settings: Settings,
    provider: EmbedderProvider,
    question: str,
    course_id: uuid.UUID | None,
    transport,
) -> dict:
    mode = settings.qa_mode
    embedder = provider.get()
    if embedder is None:
        # 加载仍在进行的情况已在路由层以 retrieval_warming_up 拒绝；走到这里说明加载失败
        raise AppError(503, "retrieval_unavailable", "检索模型加载失败，请联系管理员")

    started = time.perf_counter()
    try:
        vector = embedder.embed(question)
    except EmbeddingModelError:
        raise AppError(500, "internal_error", "服务器内部错误") from None
    hits = retrieve(db, settings, vector, course_id)
    draft.retrieval_ms = ms_since(started)
    draft.retrieved = [
        {"chunk_id": str(h.chunk_id), "resource_id": str(h.resource_id), "rank": h.rank, "similarity": h.similarity}
        for h in hits
    ]
    db.rollback()  # 结束只读事务，调用云端期间不占用数据库连接

    qualified = [h for h in hits if h.similarity >= settings.retrieval_min_similarity]
    if not qualified:
        return _insufficient(draft, mode)

    if mode == "demo":
        chosen = qualified[:DEMO_MAX_CITATIONS]
        rows = load_visible_chunks(db, [h.chunk_id for h in chosen])
        db.rollback()
        survivors = [h for h in chosen if h.chunk_id in rows]
        citations = [citation_payload(n, h.chunk_id, rows[h.chunk_id]) for n, h in enumerate(survivors, start=1)]
        if not citations:
            return _insufficient(draft, mode)
        answer = demo_answer(citations)
    else:
        checked = _generate(draft, settings, question, qualified, transport)
        if checked is None:
            return _insufficient(draft, mode)
        numbers = sorted(set(checked["citation_numbers"]))
        rows = load_visible_chunks(db, [qualified[n - 1].chunk_id for n in numbers])
        db.rollback()
        citations = [
            citation_payload(n, qualified[n - 1].chunk_id, rows[qualified[n - 1].chunk_id])
            for n in numbers
            if qualified[n - 1].chunk_id in rows
        ]
        if not citations:
            return _insufficient(draft, mode)
        answer = checked["answer"]

    draft.status = "answered"
    draft.answer = answer
    draft.cited_chunk_ids = [c["chunk_id"] for c in citations]
    return {"status": "answered", "mode": mode, "answer": answer, "citations": citations}


def write_log(session_factory: sessionmaker, draft: Draft) -> None:
    """写日志失败只记应用日志，不影响响应。日志不含用户标识，也不含完整提示词。"""
    try:
        with session_factory.begin() as db:
            db.add(
                QaLog(
                    course_id=draft.course_id,
                    question=draft.question,
                    status=draft.status,
                    answer=draft.answer,
                    retrieved=draft.retrieved,
                    cited_chunk_ids=draft.cited_chunk_ids,
                    timings=draft.timings(),
                    llm_config=draft.model_config_record(),
                )
            )
    except Exception as exc:
        log.warning("问答日志写入失败 (%s)", type(exc).__name__)


def ask(
    *,
    db: Session,
    session_factory: sessionmaker,
    settings: Settings,
    provider: EmbedderProvider,
    transport,
    question: str,
    course_id: uuid.UUID | None,
) -> dict:
    draft = Draft(question=question, course_id=course_id, settings=settings)
    try:
        return _pipeline(draft, db, settings, provider, question, course_id, transport)
    except AppError as exc:
        draft.status = exc.code if exc.code in LOGGED_ERROR_CODES else "internal_error"
        raise
    except Exception:
        draft.status = "internal_error"
        raise
    finally:
        write_log(session_factory, draft)
