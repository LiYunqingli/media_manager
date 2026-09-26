"""用户管理服务（仅管理端使用）。

业务规则：
- 系统不开放注册，账号只能由管理员创建；
- 不允许删除自己；
- 不允许删除/禁用最后一个可用的管理员，避免把自己锁在门外。
"""
from __future__ import annotations

from typing import Any

from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.core.security import hash_password
from app.repositories import favorite_repo, history_repo, user_repo
from app.services import permission_service
from app.utils.presenter import present_user

logger = get_logger("user")


def list_users(
    *,
    page: int,
    page_size: int,
    keyword: str = "",
    role: str = "",
    status: str = "",
    with_rules: bool = False,
) -> tuple[list[dict[str, Any]], int]:
    rows, total = user_repo.list_users(
        page=page, page_size=page_size, keyword=keyword, role=role, status=status
    )
    items = []
    for row in rows:
        rules = permission_service.load_rules(int(row["id"])) if with_rules else None
        items.append(present_user(row, with_rules=rules))
    return items, total


def get_user(user_id: int) -> dict[str, Any]:
    row = user_repo.find_by_id(user_id)
    if not row:
        raise BizError(ErrorCode.USER_NOT_FOUND)
    rules = permission_service.load_rules(user_id)
    data = present_user(row, with_rules=rules)
    data["stats"] = {
        "favorite_count": favorite_repo.count_by_user(user_id),
        "history_count": history_repo.count_by_user(user_id),
        "watch_seconds": round(history_repo.user_watch_seconds(user_id), 1),
    }
    # 白名单为空时，实际可见范围 = 全部启用分类，这里回显真实结果便于核对
    data["visible_category_ids"] = (
        None
        if row.get("role") == "admin"
        else permission_service.compute_visible_category_ids(user_id)
    )
    return data


def create_user(payload: dict[str, Any]) -> dict[str, Any]:
    username = (payload.get("username") or "").strip()
    if user_repo.find_by_username(username):
        raise BizError(ErrorCode.ACCOUNT_EXISTS, f"账号已存在: {username}")

    user_id = user_repo.create(
        username=username,
        password=hash_password(payload.get("password") or ""),
        nickname=payload.get("nickname") or username,
        role=payload.get("role") or "user",
        status=int(payload.get("status", 1)),
        email=payload.get("email") or "",
        phone=payload.get("phone") or "",
        remark=payload.get("remark") or "",
    )

    allow_categories = payload.get("allow_category_ids") or []
    if allow_categories:
        permission_service.save_rules(
            user_id,
            {
                "allow_category_ids": allow_categories,
                "deny_category_ids": [],
                "video_allow_ids": [],
                "video_deny_ids": [],
            },
        )
    logger.info("创建用户 #%s %s", user_id, username)
    return get_user(user_id)


def update_user(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = user_repo.find_by_id(user_id)
    if not row:
        raise BizError(ErrorCode.USER_NOT_FOUND)

    fields = {
        k: payload[k]
        for k in ("nickname", "avatar", "email", "phone", "remark", "role", "status")
        if payload.get(k) is not None
    }
    # 防止把最后一个管理员降级或禁用
    if row.get("role") == "admin":
        demoting = fields.get("role") == "user"
        disabling = int(fields.get("status", 1)) == 0
        if demoting or disabling:
            _assert_not_last_admin(user_id, action="降级或禁用")

    if fields:
        user_repo.update(user_id, fields)
        logger.info("更新用户 #%s: %s", user_id, list(fields.keys()))
    return get_user(user_id)


def delete_user(user_id: int, *, operator_id: int) -> None:
    row = user_repo.find_by_id(user_id)
    if not row:
        raise BizError(ErrorCode.USER_NOT_FOUND)
    if user_id == operator_id:
        raise BizError(ErrorCode.FORBIDDEN, "不能删除当前登录账号")
    if row.get("role") == "admin":
        _assert_not_last_admin(user_id, action="删除")

    permission_service.cleanup_user(user_id)
    favorite_repo.delete_by_user(user_id)
    history_repo.clear(user_id)
    user_repo.delete(user_id)
    logger.info("删除用户 #%s %s", user_id, row.get("username"))


def reset_password(user_id: int, new_password: str) -> None:
    if not user_repo.find_by_id(user_id):
        raise BizError(ErrorCode.USER_NOT_FOUND)
    if len(new_password or "") < 6:
        raise BizError(ErrorCode.PARAM_ERROR, "密码至少 6 位")
    user_repo.update_password(user_id, hash_password(new_password))
    logger.info("重置用户 #%s 密码", user_id)


def set_status(user_id: int, status: int) -> None:
    row = user_repo.find_by_id(user_id)
    if not row:
        raise BizError(ErrorCode.USER_NOT_FOUND)
    if row.get("role") == "admin" and status == 0:
        _assert_not_last_admin(user_id, action="禁用")
    user_repo.update(user_id, {"status": 1 if status else 0})


def set_rules(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    if not user_repo.find_by_id(user_id):
        raise BizError(ErrorCode.USER_NOT_FOUND)
    permission_service.save_rules(user_id, payload)
    return get_user(user_id)


def _assert_not_last_admin(user_id: int, *, action: str) -> None:
    from app.db import session as db

    remaining = db.count(
        "SELECT COUNT(*) AS c FROM sys_user WHERE role = 'admin' AND status = 1 AND id <> %s",
        (user_id,),
    )
    if remaining <= 0:
        raise BizError(ErrorCode.FORBIDDEN, f"系统至少需要保留一个启用的管理员，无法{action}")
