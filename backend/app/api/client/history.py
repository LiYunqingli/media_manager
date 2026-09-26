"""用户端：观看历史。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser
from app.core.response import ok, paginated
from app.services import play_service

router = APIRouter(prefix="/history", tags=["用户端-历史"])


@router.get("", summary="观看历史")
def list_history(
    user: CurrentUser,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    items, total = play_service.list_history(user, page=page, page_size=page_size)
    return paginated(items, total, page, page_size)


@router.delete("/{video_id}", summary="删除单条历史")
def delete_history(video_id: int, user: CurrentUser) -> dict:
    play_service.delete_history(video_id, user)
    return ok(msg="已删除")


@router.delete("", summary="清空全部历史")
def clear_history(user: CurrentUser) -> dict:
    play_service.clear_history(user)
    return ok(msg="已清空")
