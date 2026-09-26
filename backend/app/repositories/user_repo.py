"""用户表 SQL。"""
from __future__ import annotations

from typing import Any

from app.db import session as db
from app.repositories._sql import placeholders

# 查询时统一裁剪掉密码字段，避免误返回给前端
_SAFE_COLUMNS = (
    "id, username, nickname, avatar, email, phone, role, status, remark, "
    "last_login_at, last_login_ip, created_at, updated_at"
)


def find_by_username(username: str, *, with_password: bool = False) -> dict[str, Any] | None:
    cols = f"{_SAFE_COLUMNS}, password" if with_password else _SAFE_COLUMNS
    return db.query_one(f"SELECT {cols} FROM sys_user WHERE username = %s", (username,))


def find_by_id(user_id: int, *, with_password: bool = False) -> dict[str, Any] | None:
    cols = f"{_SAFE_COLUMNS}, password" if with_password else _SAFE_COLUMNS
    return db.query_one(f"SELECT {cols} FROM sys_user WHERE id = %s", (user_id,))


def find_many_by_ids(user_ids: list[int]) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    rows = db.query_all(
        f"SELECT {_SAFE_COLUMNS} FROM sys_user "
        f"WHERE id IN ({placeholders(len(user_ids))})",
        tuple(user_ids),
    )
    return rows


def list_users(
    *,
    page: int,
    page_size: int,
    keyword: str = "",
    role: str = "",
    status: str = "",
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: list[Any] = []

    if keyword:
        where.append("(username LIKE %s OR nickname LIKE %s OR remark LIKE %s)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    if role:
        where.append("role = %s")
        params.append(role)
    if status in ("0", "1"):
        where.append("status = %s")
        params.append(int(status))

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    total = db.count(f"SELECT COUNT(*) AS c FROM sys_user {clause}", tuple(params) or None)

    rows = db.query_all(
        f"SELECT {_SAFE_COLUMNS} FROM sys_user {clause} "
        f"ORDER BY id ASC LIMIT %s OFFSET %s",
        (*params, page_size, (page - 1) * page_size),
    )
    return rows, total


def create(
    *,
    username: str,
    password: str,
    nickname: str = "",
    role: str = "user",
    status: int = 1,
    email: str = "",
    phone: str = "",
    remark: str = "",
) -> int:
    return db.execute_return_id(
        "INSERT INTO sys_user (username, password, nickname, role, status, email, phone, remark) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (username, password, nickname, role, status, email, phone, remark),
    )


_ALLOWED_UPDATE_FIELDS = {"nickname", "avatar", "email", "phone", "role", "status", "remark"}


def update(user_id: int, fields: dict[str, Any]) -> int:
    """按白名单字段更新，禁止通过该接口改密码。"""
    data = {k: v for k, v in fields.items() if k in _ALLOWED_UPDATE_FIELDS and v is not None}
    if not data:
        return 0
    assignments = ", ".join(f"{k} = %s" for k in data)
    return db.execute(
        f"UPDATE sys_user SET {assignments} WHERE id = %s",
        (*data.values(), user_id),
    )


def update_password(user_id: int, password_hash: str) -> int:
    return db.execute(
        "UPDATE sys_user SET password = %s WHERE id = %s", (password_hash, user_id)
    )


def delete(user_id: int) -> int:
    return db.execute("DELETE FROM sys_user WHERE id = %s", (user_id,))


def touch_login(user_id: int, ip: str = "") -> int:
    return db.execute(
        "UPDATE sys_user SET last_login_at = NOW(), last_login_ip = %s WHERE id = %s",
        (ip, user_id),
    )


def count_by_role(role: str) -> int:
    return db.count("SELECT COUNT(*) AS c FROM sys_user WHERE role = %s", (role,))
