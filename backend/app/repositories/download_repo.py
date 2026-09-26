"""m3u8 下载导入任务 SQL。

表 ``download_task`` 承载「链接 -> 下载 -> 入库」的全过程状态，字段语义与
``upload_session`` 对齐（stage / percent / message / error / video_id），
前端因此可以复用同一套进度展示组件与轮询逻辑。
"""
from __future__ import annotations

from typing import Any

from app.db import session as db

# UPDATE 白名单。
# ⚠️ 这里漏字段的后果和 video_repo._ALLOWED 一样：update() 会静默过滤掉，
# 过滤后为空直接 return 0 —— 不抛错、不生效。新增需要回写的字段务必同步加。
_ALLOWED = {
    "source",
    "headers",
    "title",
    "cover_url",
    "category_id",
    "description",
    "sort",
    "stage",
    "percent",
    "total_bytes",
    "done_bytes",
    "speed",
    "eta",
    "staging_dir",
    "file_path",
    "cover",
    "video_id",
    "message",
    "error",
    "log_tail",
    "elapsed",
}

# 运行中的阶段（进程重启后需要判为中断）
ACTIVE_STAGES = ("queued", "downloading", "muxing", "ingesting", "probing", "covering")


def create(
    *,
    task_id: str,
    user_id: int,
    url: str,
    title: str = "",
    cover_url: str = "",
    category_id: int = 0,
    description: str = "",
    sort: int = 0,
    headers: str = "",
    source: str = "admin",
) -> None:
    db.execute(
        """
        INSERT INTO download_task
            (task_id, user_id, source, url, headers, title, cover_url,
             category_id, description, sort, stage, message)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'queued', '已加入下载队列')
        """,
        (
            task_id, user_id, source, url, headers, title, cover_url,
            category_id, description, sort,
        ),
    )


def get(task_id: str) -> dict[str, Any] | None:
    return db.query_one("SELECT * FROM download_task WHERE task_id = %s", (task_id,))


def update(task_id: str, fields: dict[str, Any]) -> int:
    data = {k: v for k, v in fields.items() if k in _ALLOWED and v is not None}
    if not data:
        return 0
    assignments = ", ".join(f"{k} = %s" for k in data)
    return db.execute(
        f"UPDATE download_task SET {assignments} WHERE task_id = %s",
        (*data.values(), task_id),
    )


def mark_started(task_id: str) -> int:
    return db.execute(
        "UPDATE download_task SET stage = 'downloading', started_at = NOW(), "
        "message = '正在下载分片' WHERE task_id = %s",
        (task_id,),
    )


def mark_finished(task_id: str, *, video_id: int = 0) -> int:
    return db.execute(
        "UPDATE download_task SET stage = 'finished', percent = 100, speed = 0, eta = 0, "
        "video_id = %s, finished_at = NOW() WHERE task_id = %s",
        (int(video_id), task_id),
    )


def reset_for_retry(task_id: str) -> int:
    """把任务打回排队状态，便于原 ID 重试。"""
    return db.execute(
        """
        UPDATE download_task
        SET stage = 'queued', percent = 0, done_bytes = 0, speed = 0, eta = 0,
            error = '', message = '重新排队', video_id = 0,
            started_at = NULL, finished_at = NULL, elapsed = 0
        WHERE task_id = %s
        """,
        (task_id,),
    )


def delete(task_id: str) -> int:
    return db.execute("DELETE FROM download_task WHERE task_id = %s", (task_id,))


def list_tasks(
    *,
    user_id: int | None = None,
    stage: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if user_id:
        where.append("user_id = %s")
        params.append(int(user_id))
    if stage:
        where.append("stage = %s")
        params.append(stage)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    params.extend([int(limit), int(offset)])
    return db.query_all(
        f"SELECT * FROM download_task {clause} ORDER BY created_at DESC LIMIT %s OFFSET %s",
        tuple(params),
    )


def count_tasks(*, user_id: int | None = None, stage: str | None = None) -> int:
    where: list[str] = []
    params: list[Any] = []
    if user_id:
        where.append("user_id = %s")
        params.append(int(user_id))
    if stage:
        where.append("stage = %s")
        params.append(stage)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    return db.count(f"SELECT COUNT(*) AS c FROM download_task {clause}", tuple(params))


def find_by_url(url: str, *, finished_only: bool = True) -> dict[str, Any] | None:
    """按链接找已有任务（判重：同一链接不必重复下载）。"""
    if finished_only:
        return db.query_one(
            "SELECT * FROM download_task WHERE url = %s AND stage = 'finished' "
            "ORDER BY created_at DESC LIMIT 1",
            (url,),
        )
    return db.query_one(
        "SELECT * FROM download_task WHERE url = %s ORDER BY created_at DESC LIMIT 1",
        (url,),
    )


def list_active() -> list[dict[str, Any]]:
    """仍在运行中的任务（进程重启时用来标记中断）。"""
    marks = ",".join(["%s"] * len(ACTIVE_STAGES))
    return db.query_all(
        f"SELECT * FROM download_task WHERE stage IN ({marks})", tuple(ACTIVE_STAGES)
    )


def mark_interrupted(task_id: str) -> int:
    return db.execute(
        "UPDATE download_task SET stage = 'failed', message = '服务重启，任务中断', "
        "error = '服务进程重启导致任务中断，请重试', finished_at = NOW() "
        "WHERE task_id = %s",
        (task_id,),
    )


def stats() -> dict[str, Any]:
    row = db.query_one(
        """
        SELECT
            COUNT(*) AS total,
            SUM(CASE WHEN stage = 'finished' THEN 1 ELSE 0 END) AS finished,
            SUM(CASE WHEN stage = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN stage IN ('queued','downloading','muxing','ingesting','probing','covering')
                     THEN 1 ELSE 0 END) AS running
        FROM download_task
        """
    ) or {}
    return {
        "total": int(row.get("total") or 0),
        "finished": int(row.get("finished") or 0),
        "failed": int(row.get("failed") or 0),
        "running": int(row.get("running") or 0),
    }
