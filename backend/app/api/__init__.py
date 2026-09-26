"""API 路由聚合。"""
from fastapi import APIRouter

from app.api import auth
from app.api.admin import admin_router
from app.api.client import client_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(admin_router)
api_router.include_router(client_router)


@api_router.get("/health", tags=["系统"], summary="健康检查")
def health() -> dict:
    from app.core.response import ok
    from app.db import session as db

    db_version = "unknown"
    try:
        row = db.query_one("SELECT VERSION() AS v")
        db_version = row["v"] if row else "unknown"
    except Exception as exc:  # noqa: BLE001
        db_version = f"error: {exc}"

    return ok({"status": "ok", "mysql": db_version})


@api_router.get("/info", tags=["系统"], summary="接口信息与入口地址")
def info() -> dict:
    from app.core.config import get_settings
    from app.core.response import ok

    settings = get_settings()
    return ok(
        {
            "name": settings.get("app.name"),
            "version": settings.get("app.version"),
            "docs": "/docs",
            "admin": "/admin/",
            "web": "/",
            "default_site": settings.get("app.default_site"),
        }
    )


__all__ = ["api_router"]
