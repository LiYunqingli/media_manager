"""认证服务：登录、令牌校验、密码与资料管理。"""
from __future__ import annotations

from typing import Any

from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.repositories import user_repo
from app.utils.presenter import present_user

logger = get_logger("auth")


def login(
    username: str,
    password: str,
    *,
    ip: str = "",
    require_admin: bool = False,
) -> dict[str, Any]:
    """账号密码登录，返回令牌与用户信息。"""
    username = (username or "").strip()
    row = user_repo.find_by_username(username, with_password=True)
    if not row or not verify_password(password, row.get("password") or ""):
        logger.warning("登录失败 username=%s ip=%s", username, ip)
        raise BizError(ErrorCode.BAD_CREDENTIALS)
    if int(row.get("status") or 0) != 1:
        raise BizError(ErrorCode.ACCOUNT_DISABLED, "账号已被禁用，请联系管理员")
    if require_admin and row.get("role") != "admin":
        raise BizError(ErrorCode.FORBIDDEN, "该账号不是管理员，无法登录管理端")

    token, expires_in = create_access_token(
        {
            "sub": int(row["id"]),
            "username": row["username"],
            "role": row["role"],
        }
    )
    user_repo.touch_login(int(row["id"]), ip)
    logger.info("登录成功 #%s %s (%s) ip=%s", row["id"], row["username"], row["role"], ip)

    row.pop("password", None)
    row["last_login_at"] = None  # 由前端重新拉取，避免时区歧义
    return {
        "token": token,
        "token_type": "Bearer",
        "expires_in": expires_in,
        "user": present_user(row),
    }


def authenticate_token(token: str, *, require_admin: bool = False) -> dict[str, Any]:
    """校验令牌并返回最新用户信息（每次都查库，保证禁用/改权限即时生效）。"""
    payload = decode_access_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise BizError(ErrorCode.TOKEN_INVALID, "令牌缺少用户标识")

    row = user_repo.find_by_id(int(user_id))
    if not row:
        raise BizError(ErrorCode.USER_NOT_FOUND, "用户不存在或已被删除")
    if int(row.get("status") or 0) != 1:
        raise BizError(ErrorCode.ACCOUNT_DISABLED)
    if require_admin and row.get("role") != "admin":
        raise BizError(ErrorCode.FORBIDDEN, "需要管理员权限")
    return row


def change_password(user: dict[str, Any], old_password: str, new_password: str) -> None:
    """用户自助改密。"""
    row = user_repo.find_by_id(int(user["id"]), with_password=True)
    if not row or not verify_password(old_password, row.get("password") or ""):
        raise BizError(ErrorCode.OLD_PASSWORD_WRONG)
    if len(new_password) < 6:
        raise BizError(ErrorCode.PARAM_ERROR, "新密码至少 6 位")
    if old_password == new_password:
        raise BizError(ErrorCode.PARAM_ERROR, "新密码不能与原密码相同")
    user_repo.update_password(int(user["id"]), hash_password(new_password))
    logger.info("用户 #%s 修改了密码", user["id"])


def update_profile(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """更新个人资料。"""
    fields = {
        k: payload[k]
        for k in ("nickname", "avatar", "email", "phone")
        if payload.get(k) is not None
    }
    if fields:
        user_repo.update(int(user["id"]), fields)
    row = user_repo.find_by_id(int(user["id"])) or {}
    return present_user(row)


def profile_of(user: dict[str, Any]) -> dict[str, Any]:
    """当前用户完整资料（含统计）。"""
    from app.repositories import favorite_repo, history_repo

    user_id = int(user["id"])
    row = user_repo.find_by_id(user_id) or user
    data = present_user(row)
    data["stats"] = {
        "favorite_count": favorite_repo.count_by_user(user_id),
        "history_count": history_repo.count_by_user(user_id),
        "watch_seconds": round(history_repo.user_watch_seconds(user_id), 1),
    }
    return data
