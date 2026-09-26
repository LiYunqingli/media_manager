"""统一响应体与全局异常处理。

响应格式（前后端唯一契约）：

成功::

    {"code": 0, "msg": "ok", "data": {...}}

失败::

    {"code": 2004, "msg": "用户名或密码错误", "data": null}

分页数据统一放在 ``data`` 内::

    {"code": 0, "msg": "ok",
     "data": {"list": [...], "total": 128, "page": 1, "page_size": 20, "pages": 7}}
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errors import BizError, ErrorCode, http_status_for

logger = logging.getLogger("media_manager")

# 业务层直接返回该类型即可交给 FastAPI 序列化
ResponseBody = dict[str, Any]


def ok(data: Any = None, msg: str = "ok") -> ResponseBody:
    """构造成功响应体。"""
    return {"code": int(ErrorCode.OK), "msg": msg, "data": data}


def fail(code: ErrorCode | int, msg: str | None = None, data: Any = None) -> ResponseBody:
    """构造失败响应体。"""
    from app.core.errors import _default_message  # 局部导入避免循环

    return {"code": int(code), "msg": msg or _default_message(int(code)), "data": data}


def paginated(
    items: list[Any],
    total: int,
    page: int,
    page_size: int,
    extra: dict[str, Any] | None = None,
) -> ResponseBody:
    """构造分页响应体。"""
    pages = (total + page_size - 1) // page_size if page_size > 0 else 0
    data: dict[str, Any] = {
        "list": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }
    if extra:
        data.update(extra)
    return ok(data)


def _json(code: int, msg: str, http_status: int, data: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=http_status,
        content={"code": int(code), "msg": msg, "data": data},
    )


def register_exception_handlers(app: FastAPI) -> None:
    """挂载全局异常处理器，保证任何异常都返回统一响应体。"""
    from app.core.config import load_config

    expose = bool(load_config().get("dev.expose_traceback", False))

    @app.exception_handler(BizError)
    async def _biz_error(_: Request, exc: BizError) -> JSONResponse:
        return _json(exc.code, exc.message, exc.http_status, exc.data)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()) if x not in ("body", "query", "path"))
            details.append({"field": loc or "body", "message": err.get("msg", "")})
        msg = "；".join(f"{d['field']}: {d['message']}" for d in details) or "参数校验失败"
        return _json(int(ErrorCode.PARAM_ERROR), msg, 400, details)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        # 把 404/405 等标准 HTTP 异常也包装成业务响应体
        mapping = {
            status.HTTP_401_UNAUTHORIZED: ErrorCode.UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN: ErrorCode.FORBIDDEN,
            status.HTTP_404_NOT_FOUND: ErrorCode.NOT_FOUND,
            status.HTTP_405_METHOD_NOT_ALLOWED: ErrorCode.INVALID_REQUEST,
        }
        code = mapping.get(exc.status_code, ErrorCode.INVALID_REQUEST)
        msg = str(exc.detail) if exc.detail else _default_of(code)
        return _json(int(code), msg, exc.status_code)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 %s %s: %s", request.method, request.url.path, exc)
        msg = f"服务器内部错误: {exc}" if expose else "服务器内部错误"
        return _json(int(ErrorCode.INTERNAL_ERROR), msg, 500)


def _default_of(code: ErrorCode) -> str:
    from app.core.errors import _default_message

    return _default_message(int(code))


__all__ = ["ok", "fail", "paginated", "register_exception_handlers", "http_status_for"]
