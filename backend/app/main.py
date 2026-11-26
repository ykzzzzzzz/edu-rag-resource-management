from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api import api_router
from app.config import Settings, get_settings
from app.db import make_engine
from app.errors import register_error_handlers
from app.middleware import request_context


def create_app(settings: Settings | None = None) -> FastAPI:
    """创建应用实例。启动方式：uvicorn app.main:create_app --factory"""
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)

    app = FastAPI(title="RAG 教育机构资源管理系统 API", version="0.1.0")
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = sessionmaker(bind=engine, expire_on_commit=False)

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
