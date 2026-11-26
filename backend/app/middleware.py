import uuid

from fastapi import Request
from fastapi.responses import Response

from app.common import request_id_var
from app.errors import error_response

API_PREFIX = "/api/v1/"
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


async def request_context(request: Request, call_next) -> Response:
    """为每个请求分配 request_id，并对 /api/v1 下的修改类请求校验 Origin。"""
    request_id = uuid.uuid4().hex
    token = request_id_var.set(request_id)
    try:
        if request.method in UNSAFE_METHODS and request.url.path.startswith(API_PREFIX):
            origin = request.headers.get("origin")
            if origin is None or origin not in request.app.state.settings.allowed_origins:
                return error_response(403, "origin_mismatch", "请求来源与前端地址不一致", request_id)
        response = await call_next(request)
    finally:
        request_id_var.reset(token)
    response.headers["X-Request-ID"] = request_id
    return response
