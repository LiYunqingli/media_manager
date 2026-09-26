"""视频表 SQL。

可见性过滤核心（由调用方传入原始 ID 列表，本层只负责拼 SQL）：

.. code-block:: sql

    -- 可见 = 分类在可见集合内 或 视频被单独放行
    ( v.category_id IN (<可见分类>) OR v.id IN (<视频放行>) )
    AND v.category_id NOT IN (<分类黑名单>)
    AND v.id NOT IN (<视频黑名单>)

当 ``category_ids is None`` 时表示「不受分类限制」（通常是管理员），
此时第一个括号整体省略。
"""
from __future__ import annotations

from typing import Any

from app.db import session as db
from app.repositories._sql import in_clause, placeholders

# 列表查询通用字段（附带分类名）
_LIST_COLUMNS = """
    v.id, v.category_id, v.title, v.description, v.cover, v.path,
    v.original_name, v.duration, v.size, v.width, v.height, v.bitrate, v.mime,
    v.cover_source, v.view_count, v.favorite_count, v.sort, v.status,
    v.created_at, v.updated_at,
    c.name AS category_name
"""


def _visibility(
    *,
    category_ids: list[int] | None,
    deny_category_ids: list[int],
    video_allow_ids: list[int],
    video_deny_ids: list[int],
) -> tuple[str, list[Any]]:
    """构造可见性 SQL 片段与参数。"""
    sql_parts: list[str] = []
    params: list[Any] = []

    if category_ids is not None:
        cat_sql, cat_params = in_clause(category_ids)
        allow_sql, allow_params = in_clause(video_allow_ids)
        sql_parts.append(f"(v.category_id IN {cat_sql} OR v.id IN {allow_sql})")
        params.extend(cat_params)
        params.extend(allow_params)

    deny_cat_sql, deny_cat_params = _not_in(deny_category_ids, "v.category_id")
    sql_parts.append(deny_cat_sql)
    params.extend(deny_cat_params)

    deny_video_sql, deny_video_params = _not_in(video_deny_ids, "v.id")
    sql_parts.append(deny_video_sql)
    params.extend(deny_video_params)

    return " AND ".join(sql_parts), params


def _not_in(values: list[int], column: str) -> tuple[str, list[int]]:
    """NOT IN 片段；空集合返回恒真条件（避免 NOT IN (NULL) 排除全部行）。"""
    if not values:
        return "1=1", []
    return f"{column} NOT IN ({placeholders(len(values))})", list(values)


# --------------------------------------------------------------------------- #
# 单条
# --------------------------------------------------------------------------- #
def find_by_id(video_id: int) -> dict[str, Any] | None:
    return db.query_one(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id WHERE v.id = %s",
        (video_id,),
    )


def find_by_ids(video_ids: list[int]) -> list[dict[str, Any]]:
    if not video_ids:
        return []
    rows = db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"WHERE v.id IN ({placeholders(len(video_ids))})",
        tuple(video_ids),
    )
    # 保持传入顺序
    order = {vid: idx for idx, vid in enumerate(video_ids)}
    return sorted(rows, key=lambda r: order.get(int(r["id"]), 999999))


def find_by_name_size(original_name: str, size: int) -> dict[str, Any] | None:
    """按「原始文件名 + 字节数」查找同一条记录（目录批量导入时判重用）。

    不读文件内容，因此可用于大目录的快速去重；比 ``find_by_hash`` 便宜得多，
    也更宽松（同名同大小基本等同于同一文件）。
    """
    return db.query_one(
        """
        SELECT id, title, path, size, created_at
        FROM video
        WHERE original_name = %s AND size = %s
        ORDER BY id DESC LIMIT 1
        """,
        (original_name, int(size)),
    )


def find_by_hash(file_hash: str) -> dict[str, Any] | None:
    """按文件 hash 查重（秒传）。hash 存在 upload_session 里，这里做联合查询。"""
    return db.query_one(
        """
        SELECT v.id, v.title, v.path, v.size
        FROM upload_session u
        JOIN video v ON v.id = u.video_id
        WHERE u.file_hash = %s AND u.stage = 'finished' AND u.video_id > 0
        LIMIT 1
        """,
        (file_hash,),
    )


# --------------------------------------------------------------------------- #
# 列表
# --------------------------------------------------------------------------- #
def list_page(
    *,
    page: int,
    page_size: int,
    category_id: int | None = None,
    keyword: str = "",
    status: str = "",
    order_by: str = "created_at",
    order_desc: bool = True,
    category_ids: list[int] | None = None,
    deny_category_ids: list[int] | None = None,
    video_allow_ids: list[int] | None = None,
    video_deny_ids: list[int] | None = None,
    exclude_ids: list[int] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """通用分页查询，同时返回总数。"""
    order_map = {
        "created_at": "v.created_at",
        "view_count": "v.view_count",
        "duration": "v.duration",
        "title": "v.title",
        "id": "v.id",
    }
    order_column = order_map.get(order_by, "v.created_at")
    direction = "DESC" if order_desc else "ASC"

    where: list[str] = []
    params: list[Any] = []

    if category_id:
        where.append("v.category_id = %s")
        params.append(category_id)
    if keyword:
        where.append("(v.title LIKE %s OR v.description LIKE %s)")
        like = f"%{keyword}%"
        params.extend([like, like])
    if status in ("0", "1"):
        where.append("v.status = %s")
        params.append(int(status))
    if exclude_ids:
        where.append(f"v.id NOT IN ({placeholders(len(exclude_ids))})")
        params.extend(exclude_ids)

    vis_sql, vis_params = _visibility(
        category_ids=category_ids,
        deny_category_ids=deny_category_ids or [],
        video_allow_ids=video_allow_ids or [],
        video_deny_ids=video_deny_ids or [],
    )
    where.append(f"({vis_sql})")
    params.extend(vis_params)

    clause = f"WHERE {' AND '.join(where)}"
    total = db.count(
        f"SELECT COUNT(*) AS c FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id {clause}",
        tuple(params),
    )
    rows = db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"{clause} ORDER BY v.sort DESC, {order_column} {direction}, v.id DESC "
        f"LIMIT %s OFFSET %s",
        (*params, page_size, (page - 1) * page_size),
    )
    return rows, total


def related(
    video_id: int,
    category_id: int,
    *,
    limit: int = 8,
    category_ids: list[int] | None = None,
    deny_category_ids: list[int] | None = None,
    video_allow_ids: list[int] | None = None,
    video_deny_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """相关推荐：同分类优先，不足时用「播放量高的其他视频」补齐。"""
    vis_sql, vis_params = _visibility(
        category_ids=category_ids,
        deny_category_ids=deny_category_ids or [],
        video_allow_ids=video_allow_ids or [],
        video_deny_ids=video_deny_ids or [],
    )

    same_category = db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"WHERE v.id <> %s AND v.category_id = %s AND v.status = 1 AND ({vis_sql}) "
        f"ORDER BY v.sort DESC, v.view_count DESC, v.id DESC LIMIT %s",
        (video_id, category_id, *vis_params, limit),
    )
    if len(same_category) >= limit:
        return same_category

    exclude = [video_id] + [int(r["id"]) for r in same_category]
    fill = db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"WHERE v.category_id <> %s AND v.status = 1 "
        f"  AND v.id NOT IN ({placeholders(len(exclude))}) AND ({vis_sql}) "
        f"ORDER BY v.view_count DESC, v.id DESC LIMIT %s",
        (category_id, *exclude, *vis_params, limit - len(same_category)),
    )
    return same_category + fill


def list_by_category(
    category_id: int,
    *,
    limit: int = 12,
    offset: int = 0,
    category_ids: list[int] | None = None,
    deny_category_ids: list[int] | None = None,
    video_allow_ids: list[int] | None = None,
    video_deny_ids: list[int] | None = None,
    order_by: str = "view_count",
) -> list[dict[str, Any]]:
    """按分类取视频（首页板块 / 继续观看补位用）。"""
    order_map = {"view_count": "v.view_count", "created_at": "v.created_at", "sort": "v.sort"}
    order_column = order_map.get(order_by, "v.view_count")
    vis_sql, vis_params = _visibility(
        category_ids=category_ids,
        deny_category_ids=deny_category_ids or [],
        video_allow_ids=video_allow_ids or [],
        video_deny_ids=video_deny_ids or [],
    )
    return db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"WHERE v.category_id = %s AND v.status = 1 AND ({vis_sql}) "
        f"ORDER BY v.sort DESC, {order_column} DESC, v.id DESC LIMIT %s OFFSET %s",
        (category_id, *vis_params, limit, offset),
    )


def list_hot(
    *,
    limit: int = 12,
    category_ids: list[int] | None = None,
    deny_category_ids: list[int] | None = None,
    video_allow_ids: list[int] | None = None,
    video_deny_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """热门视频（按播放次数）。"""
    vis_sql, vis_params = _visibility(
        category_ids=category_ids,
        deny_category_ids=deny_category_ids or [],
        video_allow_ids=video_allow_ids or [],
        video_deny_ids=video_deny_ids or [],
    )
    return db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"WHERE v.status = 1 AND ({vis_sql}) "
        f"ORDER BY v.view_count DESC, v.id DESC LIMIT %s",
        (*vis_params, limit),
    )


def list_latest(
    *,
    limit: int = 12,
    category_ids: list[int] | None = None,
    deny_category_ids: list[int] | None = None,
    video_allow_ids: list[int] | None = None,
    video_deny_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    """最新上传。"""
    vis_sql, vis_params = _visibility(
        category_ids=category_ids,
        deny_category_ids=deny_category_ids or [],
        video_allow_ids=video_allow_ids or [],
        video_deny_ids=video_deny_ids or [],
    )
    return db.query_all(
        f"SELECT {_LIST_COLUMNS} FROM video v "
        f"LEFT JOIN category c ON c.id = v.category_id "
        f"WHERE v.status = 1 AND ({vis_sql}) "
        f"ORDER BY v.created_at DESC, v.id DESC LIMIT %s",
        (*vis_params, limit),
    )


def accessible_category_ids_for_user(user_id: int) -> list[int] | None:
    """便捷方法：一次性算出用户可访问的分类 ID 列表。

    规则（与 permission_service 保持一致，此处提供 SQL 侧等价实现，供首页批量拼装用）：
    - 有 allow=1 记录 -> 白名单
    - 无 allow=1 记录 -> 全部启用分类
    - 再减去 deny=0 记录
    """
    allow_rows = db.query_all(
        "SELECT category_id FROM user_category_rule WHERE user_id = %s AND allow = 1", (user_id,)
    )
    deny_rows = db.query_all(
        "SELECT category_id FROM user_category_rule WHERE user_id = %s AND allow = 0", (user_id,)
    )
    deny = {int(r["category_id"]) for r in deny_rows}

    if allow_rows:
        base = {int(r["category_id"]) for r in allow_rows}
    else:
        rows = db.query_all("SELECT id FROM category WHERE status = 1")
        base = {int(r["id"]) for r in rows}
    return sorted(base - deny)


# --------------------------------------------------------------------------- #
# 写入
# --------------------------------------------------------------------------- #
def create(
    *,
    category_id: int,
    title: str,
    path: str,
    cover: str = "",
    description: str = "",
    original_name: str = "",
    duration: float = 0,
    size: int = 0,
    width: int = 0,
    height: int = 0,
    bitrate: int = 0,
    mime: str = "",
    cover_source: int = 0,
    sort: int = 0,
    status: int = 1,
) -> int:
    return db.execute_return_id(
        """
        INSERT INTO video
            (category_id, title, description, cover, path, original_name,
             duration, size, width, height, bitrate, mime, cover_source, sort, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            category_id, title, description, cover, path, original_name,
            duration, size, width, height, bitrate, mime, cover_source, sort, status,
        ),
    )


# 允许被 UPDATE 的字段。
# 前半段是管理员可编辑字段，后半段是系统探测/统计写入的字段
# （refresh_meta 会回写 duration/width/height/bitrate/size，
#   漏掉它们会导致「重新探测分辨率」静默不生效）。
_ALLOWED = {
    "title",
    "description",
    "category_id",
    "cover",
    "cover_source",
    "sort",
    "status",
    "duration",
    "width",
    "height",
    "bitrate",
    "size",
}


def update(video_id: int, fields: dict[str, Any]) -> int:
    data = {k: v for k, v in fields.items() if k in _ALLOWED and v is not None}
    if not data:
        return 0
    assignments = ", ".join(f"{k} = %s" for k in data)
    return db.execute(f"UPDATE video SET {assignments} WHERE id = %s", (*data.values(), video_id))


def delete(video_id: int) -> int:
    return db.execute("DELETE FROM video WHERE id = %s", (video_id,))


def increment_view(video_id: int) -> int:
    return db.execute("UPDATE video SET view_count = view_count + 1 WHERE id = %s", (video_id,))


def adjust_favorite(video_id: int, delta: int) -> int:
    """调整收藏计数，且不允许为负。"""
    if delta >= 0:
        return db.execute(
            "UPDATE video SET favorite_count = favorite_count + %s WHERE id = %s", (delta, video_id)
        )
    return db.execute(
        "UPDATE video SET favorite_count = GREATEST(favorite_count + %s, 0) WHERE id = %s",
        (delta, video_id),
    )


def count_all() -> int:
    return db.count("SELECT COUNT(*) AS c FROM video")


def count_by_status(status: int) -> int:
    return db.count("SELECT COUNT(*) AS c FROM video WHERE status = %s", (status,))


def sum_duration() -> float:
    value = db.query_value("SELECT COALESCE(SUM(duration), 0) AS s FROM video", default=0)
    return float(value or 0)


def sum_size() -> int:
    value = db.query_value("SELECT COALESCE(SUM(size), 0) AS s FROM video", default=0)
    return int(value or 0)


def count_by_category() -> list[dict[str, Any]]:
    return db.query_all(
        """
        SELECT c.id AS category_id, c.name AS category_name, COUNT(v.id) AS total
        FROM category c LEFT JOIN video v ON v.category_id = c.id
        GROUP BY c.id, c.name ORDER BY c.sort ASC, c.id ASC
        """
    )
