from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = REPO_ROOT / ".env"


class Settings(BaseSettings):
    """运行配置，读取仓库根目录的 .env 与同名环境变量。环境变量优先。"""

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    database_url: str
    qa_mode: Literal["demo", "cloud"] = "demo"
    # 逗号分隔的前端源，用于校验修改类请求的 Origin
    frontend_origin: str = "http://localhost:5173,http://127.0.0.1:5173"
    session_ttl_hours: int = Field(default=8, ge=1, le=168)
    session_cookie_secure: bool = False
    # 资源原件的存放目录（不在任何静态路径下），默认仓库根下 data/local/uploads
    resource_storage_dir: Path = REPO_ROOT / "data" / "local" / "uploads"
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, ge=1)
    hf_home: Path | None = None
    embedding_model: str = Field(default="BAAI/bge-small-zh-v1.5", min_length=1, max_length=150)
    embedding_revision: str = Field(default="7999e1d3359715c523056ef9478215996d62a620", pattern=r"^[0-9a-f]{40}$")
    chunk_size: int = Field(default=350, ge=2, le=500)
    chunk_overlap: int = Field(default=50, ge=0, le=499)
    index_timeout_seconds: float = Field(default=300, gt=0)
    index_poll_seconds: float = Field(default=2, gt=0)
    max_pdf_pages: int = Field(default=200, ge=1)
    max_docx_unpacked_bytes: int = Field(default=64 * 1024 * 1024, ge=1)
    # 问答与检索。相似度门槛是 M4 的临时默认值，M5 用验证集调参后再确定
    embedding_query_instruction: str = Field(default="为这个句子生成表示以用于检索相关文章：", max_length=100)
    retrieval_top_k: int = Field(default=5, ge=1, le=20)
    retrieval_min_similarity: float = Field(default=0.40, ge=-1, le=1)
    qa_rate_limit_per_minute: int = Field(default=10, ge=1)
    # 云端生成。API 密钥用 SecretStr 保存，不进入日志、错误信息和索引子进程
    llm_provider: Literal["bailian", "deepseek"] = "bailian"
    llm_base_url: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_model: str = ""
    llm_timeout_seconds: float = Field(default=45, gt=0, le=600)

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origin.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
