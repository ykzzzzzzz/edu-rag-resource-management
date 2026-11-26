"""嵌入模型的加载与查询向量，API 进程与索引进程共用。

加载方式固定：只读本地缓存、固定 revision、CPU、必须是快速分词器和 512 维向量。
"""

import logging
import math
import threading
from typing import Protocol

from app.config import Settings

log = logging.getLogger(__name__)
EMBEDDING_DIMENSIONS = 512


class EmbeddingModelError(Exception):
    """可以直接展示的嵌入模型错误原因。"""


def embedding_model_id(settings: Settings) -> str:
    """片段和查询共同使用的模型标识，格式与索引进程写入 resource_chunks.embedding_model 的完全一致。"""
    return f"{settings.embedding_model}@{settings.embedding_revision}"


def chunk_config_id(settings: Settings) -> str:
    """切块配置标识，格式与索引进程写入 resource_chunks.chunk_config 的完全一致。"""
    return f"v1:{settings.chunk_size}:{settings.chunk_overlap}"


def load_sentence_transformer(settings: Settings):
    from sentence_transformers import SentenceTransformer

    cache = str(settings.hf_home / "hub") if settings.hf_home else None
    try:
        model = SentenceTransformer(settings.embedding_model, revision=settings.embedding_revision,
                                    cache_folder=cache, device="cpu", local_files_only=True)
        if not model.tokenizer.is_fast or model.get_embedding_dimension() != EMBEDDING_DIMENSIONS:
            raise EmbeddingModelError("嵌入模型必须提供快速分词器和 512 维向量")
        return model
    except EmbeddingModelError:
        raise
    except Exception:
        raise EmbeddingModelError("无法加载本地嵌入模型，请检查缓存目录和版本") from None


class QueryEmbedder:
    """把问题加上检索指令后编码为单位向量。指令计入模型长度预算，超长时截掉问题的尾部。"""

    def __init__(self, model, instruction: str):
        self.model = model
        self.instruction = instruction
        self._lock = threading.Lock()  # CPU 推理串行执行，避免并发请求互相拖慢

    def _fit(self, text: str) -> str:
        tokenizer = self.model.tokenizer
        budget = self.model.max_seq_length - tokenizer.num_special_tokens_to_add(pair=False)
        offsets = tokenizer(text, add_special_tokens=False, return_offsets_mapping=True, verbose=False)["offset_mapping"]
        offsets = [(start, end) for start, end in offsets if start < end]
        if len(offsets) <= budget:
            return text
        return text[: offsets[budget - 1][1]]

    def embed(self, question: str) -> list[float]:
        text = self._fit(self.instruction + question)
        with self._lock:
            vectors = self.model.encode([text], normalize_embeddings=True, batch_size=1, show_progress_bar=False)
        if vectors.shape != (1, EMBEDDING_DIMENSIONS):
            raise EmbeddingModelError("嵌入模型返回了无效向量")
        vector = [float(x) for x in vectors[0]]
        if not all(math.isfinite(x) for x in vector):
            raise EmbeddingModelError("嵌入模型返回了无效向量")
        return vector


class EmbedderProvider(Protocol):
    state: str  # "loading" | "ready" | "failed"

    def start(self) -> None: ...

    def get(self) -> QueryEmbedder | None: ...


class BackgroundEmbedderProvider:
    """应用启动时在后台线程加载模型。加载完成前 get() 返回 None。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.state = "loading"
        self._embedder: QueryEmbedder | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            self._thread = threading.Thread(target=self._load, name="embedding-preload", daemon=True)
            self._thread.start()

    def _load(self) -> None:
        try:
            model = load_sentence_transformer(self.settings)
            self._embedder = QueryEmbedder(model, self.settings.embedding_query_instruction)
            self.state = "ready"
            log.info("查询嵌入模型已加载")
        except Exception as exc:
            self.state = "failed"
            log.error("查询嵌入模型加载失败：%s", exc if isinstance(exc, EmbeddingModelError) else type(exc).__name__)

    def get(self) -> QueryEmbedder | None:
        return self._embedder


class StaticEmbedderProvider:
    """直接持有一个现成的嵌入器，不加载任何模型。测试用确定性替身时使用。"""

    def __init__(self, embedder):
        self._embedder = embedder
        self.state = "ready" if embedder is not None else "loading"

    def start(self) -> None:
        return None

    def get(self):
        return self._embedder
