"""分类表 SQL。"""
from __future__ import annotations

from typing import Any

from app.db import session as db

_COLS = "id, name, description, cover, sort, status, created_at, updated_at"


def list_all(
    *,
    only_enabled: bool = False,
    allowed_ids: list[int] | None = None,
    deny_video_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """列出分类，附带视频数量与「默认封面」。

    :param only_enabled: 只返回 status=1
    :param allowed_ids: 限定 ID 集合（None = 不限制；空列表 = 返回空）
    :param deny_video_ids: 视频黑名单。分类自身没设封面时，默认封面取自该分类下
        最热的一条视频；这里把用户被禁看的那几条排除掉，避免用一张不该看到的
        图当分类封面。
    """
    where: list[str] = []
    params: list[Any] = []
    sub_params: list[Any] = []

    if only_enabled:
        where.append("c.status = 1")
    if allowed_ids is not None:
        if not allowed_ids:
            return []
        where.append(f"c.id IN ({','.join(['%s'] * len(allowed_ids))})")
        params.extend(allowed_ids)

    deny_clause = ""
    if deny_video_ids:
        deny_clause = f"AND v.id NOT IN ({','.join(['%s'] * len(deny_video_ids))})"
        sub_params.extend(deny_video_ids)

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    # 注意参数顺序：默认封面的子查询出现在 SELECT 里（在 WHERE 之前），
    # 所以它的占位符参数必须排在前面。
    sql = f"""
        SELECT c.id, c.name, c.description, c.cover, c.sort, c.status,
               c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM video v WHERE v.category_id = c.id AND v.status = 1) AS video_count,
               (SELECT v.cover FROM video v
                 WHERE v.category_id = c.id AND v.status = 1 AND v.cover <> ''
                   {deny_clause}
                 ORDER BY v.view_count DESC, v.created_at DESC, v.id DESC
                 LIMIT 1) AS default_cover
        FROM category c
        {clause}
        ORDER BY c.sort ASC, c.id ASC
    """
    return db.query_all(sql, tuple(sub_params + params) or None)


def list_with_total_videos() -> list[dict[str, Any]]:
    """管理端列表：统计全量视频数（含下架）。"""
    return db.query_all(
        """
        SELECT c.id, c.name, c.description, c.cover, c.sort, c.status,
               c.created_at, c.updated_at,
               (SELECT COUNT(*) FROM video v WHERE v.category_id = c.id) AS video_count
        FROM category c
        ORDER BY c.sort ASC, c.id ASC
        """
    )


def find_by_id(category_id: int) -> dict[str, Any] | None:
    return db.query_one(f"SELECT {_COLS} FROM category WHERE id = %s", (category_id,))


def find_by_name(name: str, *, exclude_id: int = 0) -> dict[str, Any] | None:
    return db.query_one(
        f"SELECT {_COLS} FROM category WHERE name = %s AND id <> %s", (name, exclude_id)
    )


def create(*, name: str, description: str = "", cover: str = "", sort: int = 0, status: int = 1) -> int:
    return db.execute_return_id(
        "INSERT INTO category (name, description, cover, sort, status) VALUES (%s, %s, %s, %s, %s)",
        (name, description, cover, sort, status),
    )


_ALLOWED = {"name", "description", "cover", "sort", "status"}


def update(category_id: int, fields: dict[str, Any]) -> int:
    data = {k: v for k, v in fields.items() if k in _ALLOWED and v is not None}
    if not data:
        return 0
    assignments = ", ".join(f"{k} = %s" for k in data)
    return db.execute(
        f"UPDATE category SET {assignments} WHERE id = %s", (*data.values(), category_id)
    )


def update_sort(pairs: list[tuple[int, int]]) -> None:
    """批量写排序值：``[(category_id, sort), ...]`` 在同一事务内完成。"""
    with db.transaction() as cur:
        for category_id, sort in pairs:
            cur.execute("UPDATE category SET sort = %s WHERE id = %s", (sort, category_id))


def delete(category_id: int) -> int:
    return db.execute("DELETE FROM category WHERE id = %s", (category_id,))


def video_count(category_id: int) -> int:
    return db.count("SELECT COUNT(*) AS c FROM video WHERE category_id = %s", (category_id,))


def max_sort() -> int:
    value = db.query_value("SELECT COALESCE(MAX(sort), 0) AS m FROM category", default=0)
    return int(value or 0)
