"""用户端路由。所有接口都要求已登录（系统暂不开放注册与游客浏览）。"""
from fastapi import APIRouter

from app.api.client import categories, favorites, history, home, profile, videos

client_router = APIRouter(prefix="/client")

client_router.include_router(home.router)
client_router.include_router(categories.router)
client_router.include_router(videos.router)
client_router.include_router(favorites.router)
client_router.include_router(history.router)
client_router.include_router(profile.router)

__all__ = ["client_router"]
