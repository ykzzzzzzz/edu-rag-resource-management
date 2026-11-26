from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api import api_router
from app.config import Settings, get_settings
from app.db import make_engine
from app.embeddings import BackgroundEmbedderProvider, EmbedderProvider
from app.errors import register_error_handlers
from app.middleware import request_context
from app.rate_limit import SlidingWindowLimiter


def create_app(
    settings: Settings | None = None,
    *,
    embedder_provider: EmbedderProvider | None = None,
    llm_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    """创建应用实例。启动方式：uvicorn app.main:create_app --factory

    embedder_provider 与 llm_transport 供测试注入确定性替身；生产环境留空，
    API 在启动时于后台线程预加载查询嵌入模型，云端调用走真实 HTTP。
    """
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    provider = embedder_provider or BackgroundEmbedderProvider(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        provider.start()
        yield

    app = FastAPI(title="RAG 教育机构资源管理系统 API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    app.state.embedder_provider = provider
    app.state.llm_transport = llm_transport
    app.state.qa_rate_limiter = SlidingWindowLimiter(settings.qa_rate_limit_per_minute)

    register_error_handlers(app)
    app.middleware("http")(request_context)
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/healthz", tags=["system"])
    def healthz(request: Request) -> JSONResponse:
        try:
            with request.app.state.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"status": "unavailable", "database": "unavailable"})
        return JSONResponse(content={"status": "ok", "database": "ok"})

    return app
