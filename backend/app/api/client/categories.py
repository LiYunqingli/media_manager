"""用户端：分类。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, Visibility
from app.core.response import ok, paginated
from app.services import category_service, video_service

router = APIRouter(prefix="/categories", tags=["用户端-分类"])


@router.get("", summary="可见分类列表")
def list_categories(user: CurrentUser, visibility: Visibility) -> dict:
    return ok(category_service.list_for_client(visibility))


@router.get("/{category_id}", summary="分类详情（含该分类下的视频）")
def category_detail(
    category_id: int,
    user: CurrentUser,
    visibility: Visibility,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "created_at",
) -> dict:
    category = category_service.get_visible_category(category_id, visibility)
    items, total = video_service.client_list(
        {
            "category_id": category_id,
            "page": page,
            "page_size": page_size,
            "order_by": order_by,
        },
        visibility,
    )
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    return paginated(items, total, page, page_size, {"category": category})
