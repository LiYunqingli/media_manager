"""观看历史与播放会话 SQL。

「观看次数」规则：单次播放会话（segment_id）累计观看达到阈值（默认 10 秒）记 1 次，
每个会话只记一次，避免刷新页面刷播放量。
"""
from __future__ import annotations

from typing import Any

from app.db import session as db


# --------------------------------------------------------------------------- #
# 观看历史
# --------------------------------------------------------------------------- #
def upsert_progress(
    *,
    user_id: int,
    video_id: int,
    last_position: float,
    duration: float,
    progress: float,
    watch_seconds: float,
    finished: int,
    segment_id: str,
) -> int:
    """写入/更新观看进度。watch_seconds 为累加值，其余字段覆盖。"""
    return db.execute(
        """
        INSERT INTO watch_history
            (user_id, video_id, last_position, duration, progress,
             watch_seconds, finished, segment_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            last_position = VALUES(last_position),
            duration      = VALUES(duration),
            progress      = VALUES(progress),
            watch_seconds = watch_seconds + VALUES(watch_seconds),
            finished      = GREATEST(finished, VALUES(finished)),
            segment_id    = VALUES(segment_id)
        """,
        (
            user_id, video_id, last_position, duration, progress,
            watch_seconds, finished, segment_id,
        ),
    )


def get(user_id: int, video_id: int) -> dict[str, Any] | None:
    return db.query_one(
        "SELECT * FROM watch_history WHERE user_id = %s AND video_id = %s",
        (user_id, video_id),
    )


def list_by_user(*, user_id: int, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    total = db.count("SELECT COUNT(*) AS c FROM watch_history WHERE user_id = %s", (user_id,))
    rows = db.query_all(
        """
        SELECT h.id AS history_id, h.last_position, h.duration, h.progress,
               h.watch_seconds, h.finished, h.updated_at AS watched_at,
               v.id, v.category_id, v.title, v.cover, v.path, v.status,
               v.view_count, c.name AS category_name
        FROM watch_history h
        JOIN video v ON v.id = h.video_id
        LEFT JOIN category c ON c.id = v.category_id
        WHERE h.user_id = %s
        ORDER BY h.updated_at DESC
        LIMIT %s OFFSET %s
        """,
        (user_id, page_size, (page - 1) * page_size),
    )
    return rows, total


def list_continue_watching(
    user_id: int, *, limit: int = 12, min_seconds: float = 3.0
) -> list[dict[str, Any]]:
    """「继续观看」：有进度、未看完、观看超过 min_seconds 的最近记录。"""
    return db.query_all(
        """
        SELECT h.last_position, h.duration, h.progress, h.updated_at AS watched_at,
               v.id, v.category_id, v.title, v.cover, v.duration AS video_duration,
               c.name AS category_name
        FROM watch_history h
        JOIN video v ON v.id = h.video_id
        LEFT JOIN category c ON c.id = v.category_id
        WHERE h.user_id = %s AND h.finished = 0 AND h.watch_seconds >= %s
          AND v.status = 1
        ORDER BY h.updated_at DESC
        LIMIT %s
        """,
        (user_id, min_seconds, limit),
    )


def delete(user_id: int, video_id: int) -> int:
    return db.execute(
        "DELETE FROM watch_history WHERE user_id = %s AND video_id = %s", (user_id, video_id)
    )


def clear(user_id: int) -> int:
    return db.execute("DELETE FROM watch_history WHERE user_id = %s", (user_id,))


def count_by_user(user_id: int) -> int:
    return db.count("SELECT COUNT(*) AS c FROM watch_history WHERE user_id = %s", (user_id,))


def delete_by_video(video_id: int) -> int:
    return db.execute("DELETE FROM watch_history WHERE video_id = %s", (video_id,))


# --------------------------------------------------------------------------- #
# 播放会话（观看次数统计）
# --------------------------------------------------------------------------- #
def ensure_session(
    *,
    segment_id: str,
    user_id: int,
    video_id: int,
    ip: str = "",
    user_agent: str = "",
) -> None:
    db.execute(
        """
        INSERT INTO view_session (segment_id, user_id, video_id, watch_seconds, ip, user_agent)
        VALUES (%s, %s, %s, 0, %s, %s)
        ON DUPLICATE KEY UPDATE updated_at = NOW()
        """,
        (segment_id, user_id, video_id, ip[:64], user_agent[:255]),
    )


def add_session_seconds(segment_id: str, seconds: float) -> None:
    db.execute(
        """
        UPDATE view_session SET watch_seconds = watch_seconds + %s
        WHERE segment_id = %s
        """,
        (seconds, segment_id),
    )


def get_session(segment_id: str) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM view_session WHERE segment_id = %s", (segment_id,))


def mark_session_counted(segment_id: str) -> int:
    """原子置位：仅当尚未计数时成功，返回受影响行数（1=本次计数生效）。"""
    return db.execute(
        "UPDATE view_session SET counted = 1 WHERE segment_id = %s AND counted = 0",
        (segment_id,),
    )


def video_view_total(video_id: int) -> int:
    value = db.query_value("SELECT view_count FROM video WHERE id = %s", (video_id,), default=0)
    return int(value or 0)


def user_watch_seconds(user_id: int) -> float:
    value = db.query_value(
        "SELECT COALESCE(SUM(watch_seconds), 0) AS s FROM watch_history WHERE user_id = %s",
        (user_id,),
        default=0,
    )
    return float(value or 0)
