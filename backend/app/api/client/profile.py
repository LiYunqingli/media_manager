"""用户端：个人中心。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser
from app.core.response import ok
from app.schemas.auth import ChangePasswordRequest, ProfileUpdateRequest
from app.services import auth_service

router = APIRouter(prefix="/profile", tags=["用户端-个人中心"])


@router.get("", summary="个人资料与统计")
def profile(user: CurrentUser) -> dict:
    return ok(auth_service.profile_of(user))


@router.put("", summary="修改资料")
def update_profile(payload: ProfileUpdateRequest, user: CurrentUser) -> dict:
    return ok(auth_service.update_profile(user, payload.model_dump(exclude_unset=True)))


@router.put("/password", summary="修改密码")
def change_password(payload: ChangePasswordRequest, user: CurrentUser) -> dict:
    auth_service.change_password(user, payload.old_password, payload.new_password)
    return ok(msg="密码修改成功，请重新登录")
