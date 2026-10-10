"""用户端：分类。"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, Visibility
from app.core.response import ok, paginated
from app.services import category_service, video_service

router = APIRouter(prefix="/categories", tags=["用户端-分类"])


@router.get("", summary="可见分类列表")
def list_categories(
    user: CurrentUser, visibility: Visibility, with_all: bool = False
) -> dict:
    """可见分类列表。

    ``with_all=1`` 时在首位追加「完整视频」虚拟分类（id=0，所有分类合并），
    供分类总览页、顶栏分类下拉、分类页切换标签条使用。
    """
    return ok(category_service.list_for_client(visibility, with_all=with_all))


@router.get("/{category_id}", summary="分类详情（含该分类下的视频）")
def category_detail(
    category_id: int,
    user: CurrentUser,
    visibility: Visibility,
    page: int = 1,
    page_size: int = 20,
    order_by: str = "created_at",
) -> dict:
    if category_id == category_service.ALL_CATEGORY_ID:
        # 「完整视频」：不校验分类可见性（本来就不存在这个分类），
        # 视频范围完全交给 client_list 的可见性过滤。
        category = category_service.build_all_category(visibility)
    else:
        category = category_service.get_visible_category(category_id, visibility)

    items, total = video_service.client_list(
        {
            # 0 / None 都表示「不限分类」，查询层不需要为聚合视图开分支
            "category_id": category_id or None,
            "page": page,
            "page_size": page_size,
            "order_by": order_by,
        },
        visibility,
    )
    page = max(1, page)
    page_size = max(1, min(page_size, 100))
    return paginated(items, total, page, page_size, {"category": category})
