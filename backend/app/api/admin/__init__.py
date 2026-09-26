"""管理端路由。所有接口都要求管理员身份。"""
from fastapi import APIRouter

from app.api.admin import auth, categories, stats, upload, users, videos

admin_router = APIRouter(prefix="/admin")

admin_router.include_router(auth.router)
admin_router.include_router(stats.router)
admin_router.include_router(users.router)
admin_router.include_router(categories.router)
admin_router.include_router(videos.router)
admin_router.include_router(upload.router)

__all__ = ["admin_router"]
