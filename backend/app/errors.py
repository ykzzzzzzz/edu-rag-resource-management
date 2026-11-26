import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common import request_id_var

UNIQUE_VIOLATION = "23505"


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthenticated",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
}
_HTTP_MESSAGES = {
    400: "请求无效",
    401: "请先登录",
    403: "无权限执行该操作",
    404: "接口或资源不存在",
    405: "请求方法不被允许",
    409: "请求与当前状态冲突",
    422: "请求参数不合法",
}


def error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={"X-Request-ID": request_id},
    )


def raise_for_unique_violation(exc: IntegrityError, code: str, message: str) -> None:
    """唯一约束冲突转为 409，其他完整性错误原样抛出。"""
    if getattr(exc.orig, "sqlstate", None) == UNIQUE_VIOLATION:
        raise AppError(409, code, message) from exc
    raise exc


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status_code, exc.code, exc.message, request_id_var.get())

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return error_response(
            exc.status_code,
            _HTTP_CODES.get(exc.status_code, "http_error"),
            _HTTP_MESSAGES.get(exc.status_code, "请求失败"),
            request_id_var.get(),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(422, "validation_error", "请求参数不合法", request_id_var.get())

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # 未捕获异常由最外层中间件处理，此时请求 ID 上下文可能缺失，需要补一个
        request_id = request_id_var.get()
        if request_id == "-":
            request_id = uuid.uuid4().hex
        return error_response(500, "internal_error", "服务器内部错误", request_id)
