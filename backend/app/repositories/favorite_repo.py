"""收藏表 SQL。"""
from __future__ import annotations

from typing import Any

from app.db import session as db


def add(user_id: int, video_id: int) -> int:
    """幂等收藏：已存在时不报错、返回 0。"""
    return db.execute(
        "INSERT IGNORE INTO favorite (user_id, video_id) VALUES (%s, %s)",
        (user_id, video_id),
    )


def remove(user_id: int, video_id: int) -> int:
    return db.execute(
        "DELETE FROM favorite WHERE user_id = %s AND video_id = %s", (user_id, video_id)
    )


def exists(user_id: int, video_id: int) -> bool:
    return db.exists(
        "SELECT 1 FROM favorite WHERE user_id = %s AND video_id = %s LIMIT 1",
        (user_id, video_id),
    )


def count_by_user(user_id: int) -> int:
    return db.count("SELECT COUNT(*) AS c FROM favorite WHERE user_id = %s", (user_id,))


def count_by_video(video_id: int) -> int:
    return db.count("SELECT COUNT(*) AS c FROM favorite WHERE video_id = %s", (video_id,))


def list_by_user(*, user_id: int, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    total = count_by_user(user_id)
    rows = db.query_all(
        """
        SELECT f.id AS favorite_id, f.created_at AS favorited_at,
               v.id, v.category_id, v.title, v.description, v.cover, v.path,
               v.duration, v.size, v.view_count, v.favorite_count, v.status,
               v.created_at, c.name AS category_name
        FROM favorite f
        JOIN video v ON v.id = f.video_id
        LEFT JOIN category c ON c.id = v.category_id
        WHERE f.user_id = %s
        ORDER BY f.id DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, page_size, (page - 1) * page_size),
    )
    return rows, total


def video_ids_by_user(user_id: int, limit: int = 500) -> list[int]:
    rows = db.query_all(
        "SELECT video_id FROM favorite WHERE user_id = %s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )
    return [int(r["video_id"]) for r in rows]


def delete_by_video(video_id: int) -> int:
    """删除视频时联动清理收藏。"""
    return db.execute("DELETE FROM favorite WHERE video_id = %s", (video_id,))


def delete_by_user(user_id: int) -> int:
    """删除用户时联动清理收藏。"""
    return db.execute("DELETE FROM favorite WHERE user_id = %s", (user_id,))
