"""管理端路由。所有接口都要求管理员身份（下载接口另接受 X-API-Token，见 deps）。"""
from fastapi import APIRouter

from app.api.admin import auth, categories, download, stats, upload, users, videos

admin_router = APIRouter(prefix="/admin")

admin_router.include_router(auth.router)
admin_router.include_router(stats.router)
admin_router.include_router(users.router)
admin_router.include_router(categories.router)
admin_router.include_router(videos.router)
admin_router.include_router(upload.router)
admin_router.include_router(download.router)

__all__ = ["admin_router"]
