"""FastAPI 依赖注入。

令牌获取顺序：``Authorization: Bearer <token>`` → 查询参数 ``?token=``
（后者用于 ``<video>`` 标签、WebSocket 这类无法自定义请求头的场景）。
"""
from __future__ import annotations

from typing import Any, Annotated

from fastapi import Depends, Header, Query, Request

from app.core.errors import BizError, ErrorCode
from app.services import auth_service, permission_service


def client_ip(request: Request) -> str:
    """取客户端真实 IP（兼容反向代理）。"""
    forwarded = request.headers.get("x-forwarded-for") or ""
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()[:64]
    return (request.client.host if request.client else "")[:64]


def user_agent(request: Request) -> str:
    return (request.headers.get("user-agent") or "")[:255]


def extract_token(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query(description="备选令牌，供 video/WebSocket 使用")] = None,
) -> str:
    """从请求中提取令牌。"""
    if authorization:
        scheme, _, param = authorization.partition(" ")
        if scheme.lower() == "bearer" and param.strip():
            return param.strip()
        # 容错：直接传裸 token
        if not param and scheme:
            return scheme.strip()
    if token:
        return token.strip()
    # 管理端的长连接 / 静态资源场景只能走 query
    raise BizError(ErrorCode.UNAUTHORIZED, "请先登录")


def get_current_user(
    request: Request,
    token_value: Annotated[str, Depends(extract_token)],
) -> dict[str, Any]:
    """任意登录用户。"""
    return auth_service.authenticate_token(token_value)


def get_current_admin(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    """管理员。"""
    if user.get("role") != "admin":
        raise BizError(ErrorCode.FORBIDDEN, "需要管理员权限")
    return user


def get_visibility(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> permission_service.Visibility:
    """当前用户的可见范围。"""
    return permission_service.get_visibility(user)


# 类型别名，供各 router 直接使用
CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
CurrentAdmin = Annotated[dict[str, Any], Depends(get_current_admin)]
Visibility = Annotated[permission_service.Visibility, Depends(get_visibility)]
ClientIP = Annotated[str, Depends(client_ip)]
UserAgent = Annotated[str, Depends(user_agent)]


def page_params(
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 20,
) -> dict[str, int]:
    return {"page": page, "page_size": page_size}


PageParams = Annotated[dict[str, int], Depends(page_params)]
