"""用户可见性规则 SQL（分类白/黑名单 + 视频白/黑名单）。"""
from __future__ import annotations

from typing import Any

from app.db import session as db
from app.repositories._sql import placeholders


def get_category_rules(user_id: int) -> list[dict[str, Any]]:
    return db.query_all(
        "SELECT category_id, allow FROM user_category_rule WHERE user_id = %s",
        (user_id,),
    )


def get_video_rules(user_id: int) -> list[dict[str, Any]]:
    return db.query_all(
        "SELECT video_id, allow FROM user_video_rule WHERE user_id = %s",
        (user_id,),
    )


def get_category_rules_map(user_id: int, category_id: int) -> dict[str, Any] | None:
    return db.query_one(
        "SELECT * FROM user_category_rule WHERE user_id = %s AND category_id = %s",
        (user_id, category_id),
    )


def get_video_rules_map(user_id: int, video_id: int) -> dict[str, Any] | None:
    return db.query_one(
        "SELECT * FROM user_video_rule WHERE user_id = %s AND video_id = %s",
        (user_id, video_id),
    )


def replace_rules(
    user_id: int,
    *,
    allow_category_ids: list[int],
    deny_category_ids: list[int],
    video_allow_ids: list[int],
    video_deny_ids: list[int],
) -> None:
    """整体覆盖式保存（先清空再写入，同一事务）。"""
    with db.transaction() as cur:
        cur.execute("DELETE FROM user_category_rule WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_video_rule WHERE user_id = %s", (user_id,))

        rows = [(user_id, cid, 1) for cid in allow_category_ids]
        rows += [(user_id, cid, 0) for cid in deny_category_ids]
        if rows:
            cur.executemany(
                "INSERT INTO user_category_rule (user_id, category_id, allow) VALUES (%s, %s, %s)",
                rows,
            )

        rows = [(user_id, vid, 1) for vid in video_allow_ids]
        rows += [(user_id, vid, 0) for vid in video_deny_ids]
        if rows:
            cur.executemany(
                "INSERT INTO user_video_rule (user_id, video_id, allow) VALUES (%s, %s, %s)",
                rows,
            )


def clear_user_rules(user_id: int) -> None:
    with db.transaction() as cur:
        cur.execute("DELETE FROM user_category_rule WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM user_video_rule WHERE user_id = %s", (user_id,))


def count_bound_users(category_id: int) -> int:
    return db.count(
        "SELECT COUNT(*) AS c FROM user_category_rule WHERE category_id = %s AND allow = 1",
        (category_id,),
    )


def users_with_category_allow(category_id: int) -> list[int]:
    rows = db.query_all(
        "SELECT user_id FROM user_category_rule WHERE category_id = %s AND allow = 1",
        (category_id,),
    )
    return [int(r["user_id"]) for r in rows]


def batch_video_rule_summary(video_ids: list[int]) -> dict[int, dict[str, int]]:
    """统计一批视频被多少用户加入黑/白名单，用于管理端展示。"""
    if not video_ids:
        return {}
    sql = f"""
        SELECT video_id,
               SUM(CASE WHEN allow = 0 THEN 1 ELSE 0 END) AS deny_count,
               SUM(CASE WHEN allow = 1 THEN 1 ELSE 0 END) AS allow_count
        FROM user_video_rule
        WHERE video_id IN ({placeholders(len(video_ids))})
        GROUP BY video_id
    """
    rows = db.query_all(sql, tuple(video_ids))
    return {
        int(r["video_id"]): {"deny": int(r["deny_count"] or 0), "allow": int(r["allow_count"] or 0)}
        for r in rows
    }
