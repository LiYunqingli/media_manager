"""管理端：用户管理 + 可见性权限配置。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin, PageParams
from app.core.response import ok, paginated
from app.repositories import video_repo
from app.schemas.user import (
    AdminResetPasswordRequest,
    UserCreateRequest,
    UserRulesRequest,
    UserUpdateRequest,
)
from app.services import user_service
from app.utils.presenter import present_video

router = APIRouter(prefix="/users", tags=["管理端-用户"])


@router.get("", summary="用户列表")
def list_users(
    _: CurrentAdmin,
    params: PageParams,
    keyword: Annotated[str, Query(max_length=64)] = "",
    role: Annotated[str, Query(pattern=r"^(|admin|user)$")] = "",
    status: Annotated[str, Query(pattern=r"^(|0|1)$")] = "",
    with_rules: Annotated[bool, Query(description="是否附带权限规则")] = False,
) -> dict:
    items, total = user_service.list_users(
        page=params["page"],
        page_size=params["page_size"],
        keyword=keyword,
        role=role,
        status=status,
        with_rules=with_rules,
    )
    return paginated(items, total, params["page"], params["page_size"])


@router.post("", summary="创建用户（系统不开放注册）")
def create_user(payload: UserCreateRequest, _: CurrentAdmin) -> dict:
    return ok(user_service.create_user(payload.model_dump()))


@router.get("/{user_id}", summary="用户详情（含权限规则与统计）")
def get_user(user_id: int, _: CurrentAdmin) -> dict:
    return ok(user_service.get_user(user_id))


@router.put("/{user_id}", summary="更新用户基础信息")
def update_user(user_id: int, payload: UserUpdateRequest, _: CurrentAdmin) -> dict:
    return ok(user_service.update_user(user_id, payload.model_dump(exclude_unset=True)))


@router.delete("/{user_id}", summary="删除用户")
def delete_user(user_id: int, admin: CurrentAdmin) -> dict:
    user_service.delete_user(user_id, operator_id=int(admin["id"]))
    return ok(msg="用户已删除")


@router.put("/{user_id}/password", summary="重置用户密码")
def reset_password(user_id: int, payload: AdminResetPasswordRequest, _: CurrentAdmin) -> dict:
    user_service.reset_password(user_id, payload.new_password)
    return ok(msg="密码已重置")


@router.put("/{user_id}/status", summary="启用/禁用用户")
def set_status(user_id: int, status: Annotated[int, Query(ge=0, le=1)], _: CurrentAdmin) -> dict:
    user_service.set_status(user_id, int(status))
    return ok(msg="状态已更新")


# --------------------------------------------------------------------------- #
# 可见性规则
# --------------------------------------------------------------------------- #
@router.get("/{user_id}/permissions", summary="读取用户的可见性规则")
def get_permissions(user_id: int, _: CurrentAdmin) -> dict:
    return ok(user_service.get_user(user_id))


@router.put("/{user_id}/permissions", summary="保存用户的可见性规则（覆盖式）")
def save_permissions(user_id: int, payload: UserRulesRequest, _: CurrentAdmin) -> dict:
    return ok(user_service.set_rules(user_id, payload.model_dump()))


@router.get("/{user_id}/permissions/videos", summary="挑选视频用于黑/白名单")
def pick_videos(
    user_id: int,
    _: CurrentAdmin,
    params: PageParams,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    keyword: Annotated[str, Query(max_length=64)] = "",
) -> dict:
    """返回视频列表并标注该用户当前对每个视频的规则状态，便于前端勾选。"""
    from app.services import permission_service

    rows, total = video_repo.list_page(
        page=params["page"],
        page_size=params["page_size"],
        category_id=category_id,
        keyword=keyword,
        order_by="id",
        order_desc=False,
    )
    rules = permission_service.load_rules(user_id)
    deny = set(rules["video_deny_ids"])
    allow = set(rules["video_allow_ids"])

    items = []
    for row in rows:
        item = present_video(row)
        vid = int(row["id"])
        item["rule"] = 0 if vid in deny else (1 if vid in allow else -1)
        items.append(item)
    return paginated(items, total, params["page"], params["page_size"])
