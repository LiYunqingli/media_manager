"""用户端：首页聚合。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, Visibility
from app.core.response import ok
from app.services import video_service

router = APIRouter(tags=["用户端-首页"])


@router.get("/home", summary="首页聚合数据（轮播/热门/最新/继续观看/分类板块）")
def home(user: CurrentUser, visibility: Visibility) -> dict:
    return ok(video_service.client_home(visibility, user))


@router.get("/search", summary="搜索视频")
def search(
    user: CurrentUser,
    visibility: Visibility,
    keyword: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    from app.core.response import paginated

    items, total = video_service.client_search(
        {"keyword": keyword, "page": page, "page_size": page_size}, visibility
    )
    return paginated(items, total, max(1, page), max(1, min(page_size, 100)), {"keyword": keyword})
