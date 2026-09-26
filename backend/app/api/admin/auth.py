"""管理端认证。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import ClientIP, CurrentAdmin
from app.core.response import ok
from app.schemas.auth import LoginRequest
from app.services import auth_service

router = APIRouter(prefix="/auth", tags=["管理端-认证"])


@router.post("/login", summary="管理端登录（仅管理员）")
def login(payload: LoginRequest, ip: ClientIP) -> dict:
    return ok(auth_service.login(payload.username, payload.password, ip=ip, require_admin=True))


@router.get("/me", summary="当前管理员信息")
def me(user: CurrentAdmin) -> dict:
    return ok(auth_service.profile_of(user))
