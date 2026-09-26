"""管理端：数据统计与系统信息。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin
from app.core.config import get_settings
from app.core.response import ok
from app.db.pool import get_pool
from app.services import media_service, stats_service

router = APIRouter(prefix="/stats", tags=["管理端-统计"])


@router.get("/overview", summary="仪表盘总览")
def overview(_: CurrentAdmin) -> dict:
    return ok(stats_service.overview())


@router.get("/trend", summary="播放趋势")
def trend(_: CurrentAdmin, days: Annotated[int, Query(ge=1, le=90)] = 14) -> dict:
    return ok(stats_service.trend(days))


@router.get("/top-videos", summary="播放排行")
def top_videos(_: CurrentAdmin, limit: Annotated[int, Query(ge=1, le=50)] = 10) -> dict:
    return ok(stats_service.top_videos(limit))


@router.get("/system", summary="系统与运行环境信息")
def system(_: CurrentAdmin) -> dict:
    settings = get_settings()
    from app.utils.files import human_size

    storage_root = settings.storage_root
    usage = 0
    if storage_root.exists():
        for path in storage_root.rglob("*"):
            if path.is_file():
                try:
                    usage += path.stat().st_size
                except OSError:
                    continue

    try:
        pool = get_pool().stats()
    except Exception:  # noqa: BLE001
        pool = {}

    return ok(
        {
            "app": {
                "name": settings.get("app.name"),
                "version": settings.get("app.version"),
                "timezone": settings.get("app.timezone"),
            },
            "config_path": str(settings.source),
            "media_backend": media_service.available_backends(),
            "can_extract_cover": media_service.can_extract_cover(),
            "storage": {
                "root": str(storage_root),
                "usage": usage,
                "usage_text": human_size(usage),
                "chunk_size": settings.chunk_size,
                "chunk_size_text": human_size(settings.chunk_size),
            },
            "database_pool": pool,
            "business": {
                "view_threshold_seconds": settings.view_threshold_seconds,
                "page_size": settings.page_size,
                "heartbeat_interval": settings.get("business.heartbeat_interval_seconds"),
            },
            "security": {
                "token_expire_minutes": settings.get("security.token_expire_minutes"),
                "password_rounds": settings.get("security.password_rounds"),
            },
        }
    )
