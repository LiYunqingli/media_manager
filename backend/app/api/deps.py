"""FastAPI 依赖注入。

令牌获取顺序：``Authorization: Bearer <token>`` → 查询参数 ``?token=``
（后者用于 ``<video>`` 标签、WebSocket 这类无法自定义请求头的场景）。
"""
from __future__ import annotations

import secrets
from typing import Any, Annotated

from fastapi import Depends, Header, Query, Request

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.repositories import user_repo
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


def get_download_operator(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query(description="备选令牌")] = None,
    x_api_token: Annotated[str | None, Header(alias="X-API-Token")] = None,
) -> dict[str, Any]:
    """m3u8 下载接口的操作者身份，两条通道二选一：

    1. **接口令牌**：请求头 ``X-API-Token`` 与配置项 ``download.api_token`` 完全一致
       （常量时间比较）。这是给浏览器插件/脚本用的免登录通道 —— 插件里让用户扫码登录
       管理端不现实，配置一个令牌最省事。
    2. **管理员 JWT**：``Authorization: Bearer <token>``，与其它管理端接口一致。

    接口令牌调用时任务归属到 ``download.api_user_id``（0 = 库中第一个可用管理员），
    因为 ``download_task.user_id`` 是非空外键语义，必须有归属人。
    """
    settings = get_settings()
    expected = str(settings.get("download.api_token", "") or "").strip()
    if expected and x_api_token and secrets.compare_digest(x_api_token.strip(), expected):
        uid = int(settings.get("download.api_user_id", 0) or 0)
        user = user_repo.find_by_id(uid) if uid else None
        user = user or user_repo.find_first_admin()
        if not user:
            raise BizError(ErrorCode.FORBIDDEN, "库中没有可用管理员，无法归属下载任务")
        if int(user.get("status") or 0) != 1:
            raise BizError(ErrorCode.ACCOUNT_DISABLED)
        # 打一个来源标记：下载任务表要区分「管理端页面投递」与「插件/脚本投递」
        return {**user, "_via_api_token": True}
    # 回落到常规管理员校验。这两个函数在 FastAPI 里是 Depends 包装过的普通函数，
    # 手工调用必须**逐层传参**（get_current_admin 只收 user），不能直接透传 token。
    token_value = extract_token(request, authorization, token)
    return get_current_admin(get_current_user(request, token_value))


# 类型别名，供各 router 直接使用
CurrentUser = Annotated[dict[str, Any], Depends(get_current_user)]
CurrentAdmin = Annotated[dict[str, Any], Depends(get_current_admin)]
DownloadOperator = Annotated[dict[str, Any], Depends(get_download_operator)]
Visibility = Annotated[permission_service.Visibility, Depends(get_visibility)]
ClientIP = Annotated[str, Depends(client_ip)]
UserAgent = Annotated[str, Depends(user_agent)]


def page_params(
    page: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数")] = 20,
) -> dict[str, int]:
    return {"page": page, "page_size": page_size}


PageParams = Annotated[dict[str, int], Depends(page_params)]
