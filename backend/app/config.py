from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.frontend_origin.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
