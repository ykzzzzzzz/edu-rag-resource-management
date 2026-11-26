"""提示词与校验规则必须和 scripts/spike_llm.py 的 spike-v2 保持一致；嵌入器与配置的单元测试。"""

import importlib.util
import json
import re
from pathlib import Path

import numpy as np
import pytest

from app import embeddings, qa_prompt
from app.config import Settings
from app.embeddings import QueryEmbedder, chunk_config_id, embedding_model_id

SPIKE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "spike_llm.py"


@pytest.fixture(scope="module")
def spike():
    spec = importlib.util.spec_from_file_location("spike_llm_under_test", SPIKE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHUNKS = [
    {"n": 1, "source": "《数据库原理》讲义", "locator": "第 3 页", "text": "事务是逻辑工作单元。"},
    {"n": 2, "source": "课程要求", "locator": "第 1–2 行", "text": "期末笔试占 50%。\n平时占 50%。"},
]


def test_system_prompt_is_identical_to_spike_v2(spike):
    assert qa_prompt.PROMPT_VERSION == "spike-v2"
    assert qa_prompt.SYSTEM_PROMPT == spike.PROMPT_VERSIONS["spike-v2"]


def test_messages_are_identical_to_spike_v2(spike):
    question = {"question": "事务的隔离性指什么？", "chunks": CHUNKS}
    assert qa_prompt.build_messages(question["question"], CHUNKS) == spike.build_messages(question, "spike-v2")


@pytest.mark.parametrize("provider", ["bailian", "deepseek"])
def test_request_body_is_identical_to_spike(spike, provider):
    messages = qa_prompt.build_messages("问题", CHUNKS)
    assert qa_prompt.build_request_body(provider, "m", messages) == spike.build_request_body(provider, "m", messages, 0.1)
    assert (qa_prompt.MAX_TOKENS, qa_prompt.TEMPERATURE) == (spike.MAX_TOKENS, 0.1)


def test_validation_matches_spike_for_a_range_of_outputs(spike):
    def j(**kw):
        return json.dumps(kw, ensure_ascii=False)

    outputs = [
        j(status="answered", answer="好[1]", citation_numbers=[1]),
        j(status="answered", answer="好[1][2]", citation_numbers=[1, 2]),
        j(status="answered", answer="好[1]", citation_numbers=[1, 2]),
        j(status="answered", answer="好[3]", citation_numbers=[3]),
        j(status="answered", answer="", citation_numbers=[1]),
        j(status="answered", answer="无标注", citation_numbers=[]),
        j(status="insufficient_evidence", answer="没有依据", citation_numbers=[]),
        j(status="insufficient_evidence", answer="没有依据[1]", citation_numbers=[1]),
        j(status="other", answer="x[1]", citation_numbers=[1]),
        j(status="answered", answer=1, citation_numbers=[1]),
        j(status="answered", answer="好[1]", citation_numbers=["1"]),
        j(status="answered", answer="好[1]", citation_numbers=[True]),
        j(status="answered", answer="好[1]"),
        "[]", "不是 JSON", "", None, 5,
    ]
    for raw in outputs:
        assert qa_prompt.validate_model_output(raw, {1, 2}) == spike.validate_model_output(raw, {1, 2}), raw


def test_client_error_classification_is_consistent_with_spike(spike):
    """HTTP 状态码到类别的映射：401 鉴权、402 余额、429 限流、其余 5xx 不可用，与脚本同一口径。"""
    from app import llm_client

    expectations = {401: "auth_failed", 402: "insufficient_balance", 429: "rate_limited", 500: "service_unavailable"}
    backend = {401: llm_client.AUTH_FAILED, 402: llm_client.QUOTA_EXHAUSTED, 429: llm_client.RATE_LIMITED,
               500: llm_client.UNAVAILABLE}
    import urllib.error

    for status, spike_category in expectations.items():
        error = urllib.error.HTTPError("https://x", status, "", {}, None)
        assert spike.classify_error(error)[0] == spike_category
        assert llm_client.classify_http_status(status, "") == backend[status]


# ---------------------------------------------------------------- 嵌入配置

def test_embedding_identifiers_match_what_the_index_worker_writes():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x/y")
    assert embedding_model_id(settings) == "BAAI/bge-small-zh-v1.5@7999e1d3359715c523056ef9478215996d62a620"
    assert chunk_config_id(settings) == "v1:350:50"
    changed = Settings(_env_file=None, database_url="postgresql+psycopg://x/y", chunk_size=200, chunk_overlap=30)
    assert chunk_config_id(changed) == "v1:200:30"


def test_index_worker_uses_the_shared_identifiers():
    source = (Path(embeddings.__file__).parent / "index_worker.py").read_text(encoding="utf-8")
    assert "embedding_model_id(settings)" in source and "chunk_config_id(settings)" in source
    assert "load_sentence_transformer(settings)" in source
    assert 'f"v1:' not in source


def test_default_query_instruction_is_the_official_bge_retrieval_instruction():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x/y")
    assert settings.embedding_query_instruction == "为这个句子生成表示以用于检索相关文章："
    assert settings.retrieval_top_k == 5 and settings.qa_rate_limit_per_minute == 10


def test_api_key_is_never_shown_in_settings_repr_or_dump():
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x/y", llm_api_key="sk-very-secret")
    assert "sk-very-secret" not in repr(settings) and "sk-very-secret" not in str(settings)
    assert settings.llm_api_key.get_secret_value() == "sk-very-secret"


class CharTokenizer:
    def __call__(self, text, **kwargs):
        spans = [m.span() for m in re.finditer(r"\S", text)]
        return {"input_ids": list(range(len(spans))), "offset_mapping": spans}

    def num_special_tokens_to_add(self, pair):
        return 2


class RecordingModel:
    tokenizer = CharTokenizer()
    max_seq_length = 20

    def __init__(self):
        self.encoded: list[str] = []

    def encode(self, texts, **kwargs):
        self.encoded.extend(texts)
        assert kwargs["normalize_embeddings"] is True
        return np.ones((len(texts), 512), dtype=np.float32) / np.sqrt(512)


def test_query_embedder_prefixes_instruction_and_counts_it_in_the_length_budget():
    model = RecordingModel()
    embedder = QueryEmbedder(model, "指令：")
    vector = embedder.embed("短问题")
    assert model.encoded == ["指令：短问题"] and len(vector) == 512
    embedder.embed("很长很长很长很长很长很长很长很长很长很长很长很长")
    # 预算 = 20 - 2 个特殊标记 = 18 个 token，其中指令占 3 个
    assert len(model.encoded[1]) == 18 and model.encoded[1].startswith("指令：")


def test_query_embedder_rejects_wrong_dimensions():
    class Wrong(RecordingModel):
        def encode(self, texts, **kwargs):
            return np.ones((len(texts), 8), dtype=np.float32)

    with pytest.raises(embeddings.EmbeddingModelError):
        QueryEmbedder(Wrong(), "").embed("问题")


def test_background_provider_reports_loading_then_failed_without_touching_network(monkeypatch):
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x/y")

    def fail(_settings):
        raise embeddings.EmbeddingModelError("无法加载本地嵌入模型，请检查缓存目录和版本")

    monkeypatch.setattr(embeddings, "load_sentence_transformer", fail)
    provider = embeddings.BackgroundEmbedderProvider(settings)
    assert provider.state == "loading" and provider.get() is None
    provider.start()
    provider._thread.join(5)
    assert provider.state == "failed" and provider.get() is None


def test_background_provider_becomes_ready_when_model_loads(monkeypatch):
    settings = Settings(_env_file=None, database_url="postgresql+psycopg://x/y")
    monkeypatch.setattr(embeddings, "load_sentence_transformer", lambda _settings: RecordingModel())
    provider = embeddings.BackgroundEmbedderProvider(settings)
    provider.start()
    provider._thread.join(5)
    assert provider.state == "ready" and provider.get() is not None
    provider.start()  # 重复启动不会再开线程
