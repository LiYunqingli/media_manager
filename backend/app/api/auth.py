"""公共认证路由：用户端与管理端共用（通过 require_admin 区分入口）。

管理端登录请走 ``POST /api/admin/auth/login``，该入口会额外校验角色。
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ClientIP, CurrentUser
from app.core.response import ok
from app.schemas.auth import ChangePasswordRequest, LoginRequest, ProfileUpdateRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login", summary="登录（用户端/管理端通用）")
def login(payload: LoginRequest, ip: ClientIP) -> dict:
    return ok(auth_service.login(payload.username, payload.password, ip=ip))


@router.get("/me", summary="获取当前登录用户")
def me(user: CurrentUser) -> dict:
    return ok(auth_service.profile_of(user))


@router.put("/profile", summary="修改个人资料")
def update_profile(payload: ProfileUpdateRequest, user: CurrentUser) -> dict:
    return ok(auth_service.update_profile(user, payload.model_dump(exclude_unset=True)))


@router.put("/password", summary="修改密码")
def change_password(payload: ChangePasswordRequest, user: CurrentUser) -> dict:
    auth_service.change_password(user, payload.old_password, payload.new_password)
    return ok(msg="密码修改成功，请重新登录")
