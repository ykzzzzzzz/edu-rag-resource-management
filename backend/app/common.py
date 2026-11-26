from contextvars import ContextVar
from datetime import datetime, timezone

# 当前请求的 ID，由中间件设置，错误响应体中使用
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
