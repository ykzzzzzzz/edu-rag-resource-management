"""问答相关测试的共用辅助：可控向量的假嵌入器、云端 HTTP 替身、片段与日志的直接读写。

所有查询向量取 512 维的第 0 个坐标轴 e0。要让某个片段与查询的余弦相似度恰为 s，
片段向量取 (s, sqrt(1 - s^2), 0, ...)，见 axis_vector。
"""

import json
import math
import uuid

import httpx
from pydantic import SecretStr
from sqlalchemy import select

from app.embeddings import chunk_config_id, embedding_model_id
from app.models import QaLog, Resource, ResourceChunk
from tests.resource_helpers import API, make_in_state, update_resource_row

DIMENSIONS = 512
QUERY_VECTOR = [1.0] + [0.0] * (DIMENSIONS - 1)

LLM_BASE_URL = "https://llm.test/v1"
LLM_API_KEY = "sk-test-secret-0123456789"
LLM_MODEL = "qwen-flash-2025-07-28"


def axis_vector(similarity: float, axis: int = 1) -> list[float]:
    vector = [0.0] * DIMENSIONS
    vector[0] = similarity
    vector[axis] = math.sqrt(max(0.0, 1.0 - similarity * similarity))
    return vector


class FakeEmbedder:
    """确定性的查询嵌入器。默认所有问题都映射到 e0；可按问题文字指定其他向量。"""

    def __init__(self):
        self.calls: list[str] = []
        self.vectors: dict[str, list[float]] = {}

    def embed(self, question: str) -> list[float]:
        self.calls.append(question)
        return list(self.vectors.get(question, QUERY_VECTOR))


class NoNetwork(httpx.BaseTransport):
    """默认的云端传输层：任何请求都说明测试漏掉了替身，直接失败。"""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        raise AssertionError("测试不应发起任何外部 HTTP 请求")


class FakeLlm(httpx.BaseTransport):
    """记录请求并按设定返回的云端替身。"""

    def __init__(self, handler=None):
        self.requests: list[httpx.Request] = []
        self.handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def body(self, index: int = 0) -> dict:
        return json.loads(self.requests[index].content)


def llm_content_response(content, usage=None) -> httpx.Response:
    payload = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        payload["usage"] = usage
    return httpx.Response(200, json=payload)


def model_json(status="answered", answer="答案[1]", citation_numbers=(1,)) -> str:
    return json.dumps(
        {"status": status, "answer": answer, "citation_numbers": list(citation_numbers)}, ensure_ascii=False
    )


def cloud_settings(**overrides) -> dict:
    values = {
        "qa_mode": "cloud",
        "llm_provider": "bailian",
        "llm_base_url": LLM_BASE_URL,
        "llm_api_key": SecretStr(LLM_API_KEY),
        "llm_model": LLM_MODEL,
    }
    values.update(overrides)
    return values


def current_model(settings) -> str:
    return embedding_model_id(settings)


def current_config(settings) -> str:
    return chunk_config_id(settings)


def add_chunk(
    factory,
    settings,
    resource_id,
    content,
    similarity: float,
    *,
    chunk_index: int = 0,
    locator: dict | None = None,
    chunk_id: uuid.UUID | None = None,
    embedding_model: str | None = None,
    chunk_config: str | None = None,
    vector: list[float] | None = None,
) -> str:
    """直接写入一个片段，其向量与默认查询向量的余弦相似度为 similarity。"""
    with factory() as db:
        chunk = ResourceChunk(
            id=chunk_id or uuid.uuid4(),
            resource_id=uuid.UUID(str(resource_id)),
            chunk_index=chunk_index,
            content=content,
            locator=locator or {"type": "txt_line", "start": 1, "end": 2},
            embedding=vector if vector is not None else axis_vector(similarity),
            embedding_model=embedding_model or current_model(settings),
            chunk_config=chunk_config or current_config(settings),
        )
        db.add(chunk)
        db.commit()
        return str(chunk.id)


def ready_resource(actors, factory, course_id, *, title="事务讲义", filename="note.txt") -> str:
    """通过真实接口发布资源，并把索引状态直接置为 ready（不运行索引进程）。"""
    rid = make_in_state(actors, course_id, "published", title=title, filename=filename)
    update_resource_row(factory, rid, index_status="ready")
    return rid


def ask(client, question="事务的隔离性是什么？", course_id=None):
    body = {"question": question}
    if course_id is not None:
        body["course_id"] = str(course_id)
    return client.post(f"{API}/qa/ask", json=body)


def all_logs(factory) -> list[QaLog]:
    with factory() as db:
        return list(db.execute(select(QaLog).order_by(QaLog.created_at, QaLog.id)).scalars())


def resource_row(factory, rid) -> Resource:
    with factory() as db:
        return db.get(Resource, uuid.UUID(str(rid)))
