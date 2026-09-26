"""用户端：收藏。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, Visibility
from app.core.response import ok, paginated
from app.services import play_service

router = APIRouter(prefix="/favorites", tags=["用户端-收藏"])


@router.get("", summary="我的收藏")
def list_favorites(
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    items, total = play_service.list_favorites(user, page=page, page_size=page_size)
    return paginated(items, total, page, page_size)


@router.post("/{video_id}", summary="收藏视频（幂等）")
def add_favorite(video_id: int, user: CurrentUser, visibility: Visibility) -> dict:
    return ok(play_service.set_favorite(video_id, user, visibility, True))


@router.delete("/{video_id}", summary="取消收藏")
def remove_favorite(video_id: int, user: CurrentUser, visibility: Visibility) -> dict:
    return ok(play_service.set_favorite(video_id, user, visibility, False))


@router.post("/{video_id}/toggle", summary="切换收藏状态")
def toggle_favorite(video_id: int, user: CurrentUser, visibility: Visibility) -> dict:
    return ok(play_service.toggle_favorite(video_id, user, visibility))
