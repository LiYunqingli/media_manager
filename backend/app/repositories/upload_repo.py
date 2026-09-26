"""分片上传会话与分片记录 SQL。"""
from __future__ import annotations

from typing import Any

from app.db import session as db

_ALLOWED = {
    "category_id", "title", "stage", "merged_bytes", "percent",
    "speed", "message", "error", "video_id", "file_hash",
}


def create_session(
    *,
    upload_id: str,
    user_id: int,
    file_name: str,
    total_size: int,
    chunk_size: int,
    total_chunks: int,
    file_hash: str = "",
    category_id: int = 0,
    title: str = "",
) -> None:
    db.execute(
        """
        INSERT INTO upload_session
            (upload_id, user_id, file_name, file_hash, category_id, title,
             total_size, chunk_size, total_chunks, stage, percent, message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'init', 0, '已分配上传任务')
        """,
        (
            upload_id, user_id, file_name, file_hash, category_id, title,
            total_size, chunk_size, total_chunks,
        ),
    )


def get(upload_id: str) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM upload_session WHERE upload_id = %s", (upload_id,))


def update(upload_id: str, fields: dict[str, Any]) -> int:
    data = {k: v for k, v in fields.items() if k in _ALLOWED and v is not None}
    if not data:
        return 0
    assignments = ", ".join(f"{k} = %s" for k in data)
    return db.execute(
        f"UPDATE upload_session SET {assignments} WHERE upload_id = %s",
        (*data.values(), upload_id),
    )


def add_chunk(upload_id: str, chunk_index: int, size: int) -> int:
    """记录一个已成功落盘的分片（幂等：重复上报同一分片不报错）。"""
    return db.execute(
        "INSERT IGNORE INTO upload_chunk (upload_id, chunk_index, size) VALUES (%s, %s, %s)",
        (upload_id, chunk_index, size),
    )


def sync_uploaded_count(upload_id: str) -> int:
    """以 upload_chunk 为准回写已上传分片数，返回最新值。"""
    db.execute(
        """
        UPDATE upload_session u
        SET u.uploaded_chunks = (
            SELECT COUNT(*) FROM upload_chunk c WHERE c.upload_id = u.upload_id
        )
        WHERE u.upload_id = %s
        """,
        (upload_id,),
    )
    value = db.query_value(
        "SELECT uploaded_chunks FROM upload_session WHERE upload_id = %s", (upload_id,), default=0
    )
    return int(value or 0)


def list_chunk_indexes(upload_id: str) -> list[int]:
    rows = db.query_all(
        "SELECT chunk_index FROM upload_chunk WHERE upload_id = %s ORDER BY chunk_index ASC",
        (upload_id,),
    )
    return [int(r["chunk_index"]) for r in rows]


def count_chunks(upload_id: str) -> int:
    return db.count("SELECT COUNT(*) AS c FROM upload_chunk WHERE upload_id = %s", (upload_id,))


def clear_chunks(upload_id: str) -> int:
    return db.execute("DELETE FROM upload_chunk WHERE upload_id = %s", (upload_id,))


def delete_session(upload_id: str) -> None:
    with db.transaction() as cur:
        cur.execute("DELETE FROM upload_chunk WHERE upload_id = %s", (upload_id,))
        cur.execute("DELETE FROM upload_session WHERE upload_id = %s", (upload_id,))


def list_recent(
    user_id: int, *, limit: int = 20
) -> list[dict[str, Any]]:
    return db.query_all(
        """
        SELECT * FROM upload_session WHERE user_id = %s
        ORDER BY created_at DESC LIMIT %s
        """,
        (user_id, limit),
    )


def list_unfinished() -> list[dict[str, Any]]:
    return db.query_all(
        "SELECT * FROM upload_session WHERE stage NOT IN ('finished', 'failed')"
    )


def list_unfinished_before(hours: int) -> list[dict[str, Any]]:
    return db.query_all(
        """
        SELECT * FROM upload_session
        WHERE stage NOT IN ('finished', 'failed')
          AND updated_at < DATE_SUB(NOW(), INTERVAL %s HOUR)
        """,
        (int(hours),),
    )


def stats() -> dict[str, Any]:
    row = db.query_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN stage = 'finished' THEN 1 ELSE 0 END) AS finished,
            SUM(CASE WHEN stage = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN stage NOT IN ('finished','failed') THEN 1 ELSE 0 END) AS running
        FROM upload_session
        """
    ) or {}
    return {
        "total": int(row.get("total") or 0),
        "finished": int(row.get("finished") or 0),
        "failed": int(row.get("failed") or 0),
        "running": int(row.get("running") or 0),
    }
