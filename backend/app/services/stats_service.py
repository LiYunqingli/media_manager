"""统计服务（管理端仪表盘）。"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.db import session as db
from app.repositories import category_repo, upload_repo, user_repo, video_repo
from app.services import media_service
from app.utils.files import human_size


def overview() -> dict[str, Any]:
    """仪表盘总览。"""
    settings = get_settings()
    total_videos = video_repo.count_all()
    total_duration = video_repo.sum_duration()
    total_size = video_repo.sum_size()

    today_views = db.count(
        "SELECT COUNT(*) AS c FROM view_session "
        "WHERE counted = 1 AND created_at >= CURDATE()"
    )
    today_users = db.count(
        "SELECT COUNT(*) AS c FROM sys_user WHERE DATE(created_at) = CURDATE()"
    )
    active_users = db.count(
        "SELECT COUNT(DISTINCT user_id) AS c FROM watch_history "
        "WHERE updated_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)"
    )

    return {
        "video": {
            "total": total_videos,
            "online": video_repo.count_by_status(1),
            "offline": video_repo.count_by_status(0),
            "duration_seconds": round(total_duration, 1),
            "duration_text": _duration_text(total_duration),
            "size": total_size,
            "size_text": human_size(total_size),
        },
        "user": {
            "total": db.count("SELECT COUNT(*) AS c FROM sys_user"),
            "admin": user_repo.count_by_role("admin"),
            "normal": user_repo.count_by_role("user"),
            "active_7d": active_users,
            "new_today": today_users,
        },
        "category": {
            "total": len(category_repo.list_with_total_videos()),
            "items": video_repo.count_by_category(),
        },
        "play": {
            "total": _total_view_count(),
            "today": today_views,
            "favorite": db.count("SELECT COUNT(*) AS c FROM favorite"),
            "history": db.count("SELECT COUNT(*) AS c FROM watch_history"),
        },
        "upload": upload_repo.stats(),
        "system": {
            "media_backend": media_service.available_backends(),
            "chunk_size": settings.chunk_size,
            "storage_root": str(settings.storage_root),
            "pool": _pool_stats(),
        },
    }


def trend(days: int = 14) -> dict[str, Any]:
    """近 N 天播放趋势（按有效播放会话统计）。"""
    days = max(1, min(int(days or 14), 90))
    rows = db.query_all(
        """
        SELECT DATE(created_at) AS day,
               COUNT(*) AS views,
               COUNT(DISTINCT user_id) AS users
        FROM view_session
        WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        GROUP BY DATE(created_at)
        ORDER BY day ASC
        """,
        (days,),
    )
    return {
        "days": days,
        "items": [
            {
                "day": r["day"].strftime("%Y-%m-%d") if r.get("day") else "",
                "views": int(r.get("views") or 0),
                "users": int(r.get("users") or 0),
            }
            for r in rows
        ],
    }


def top_videos(limit: int = 10) -> list[dict[str, Any]]:
    rows = video_repo.list_page(page=1, page_size=min(limit, 50), order_by="view_count")[0]
    return [
        {
            "id": int(r["id"]),
            "title": r["title"],
            "category_name": r.get("category_name") or "",
            "view_count": int(r.get("view_count") or 0),
        }
        for r in rows
    ]


def _total_view_count() -> int:
    value = db.query_value("SELECT COALESCE(SUM(view_count), 0) AS s FROM video", default=0)
    return int(value or 0)


def _pool_stats() -> dict[str, Any]:
    from app.db.pool import get_pool

    try:
        return get_pool().stats()
    except Exception:  # noqa: BLE001
        return {}


def _duration_text(seconds: float) -> str:
    total = int(seconds or 0)
    hours, remainder = divmod(total, 3600)
    minutes, _ = divmod(remainder, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分"
    return f"{minutes} 分钟"
