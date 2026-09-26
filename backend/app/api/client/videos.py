"""用户端：视频浏览、播放信息与播放心跳。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import ClientIP, CurrentUser, UserAgent, Visibility
from app.core.response import ok, paginated
from app.schemas.play import PlayReportRequest
from app.services import play_service, video_service

router = APIRouter(prefix="/videos", tags=["用户端-视频"])


@router.get("", summary="视频列表（可按分类/关键词筛选）")
def list_videos(
    user: CurrentUser,
    visibility: Visibility,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    keyword: Annotated[str, Query(max_length=64)] = "",
    order_by: Annotated[str, Query(pattern=r"^(created_at|view_count|duration|title|id)$")] = "created_at",
) -> dict:
    items, total = video_service.client_list(
        {
            "page": page,
            "page_size": page_size,
            "category_id": category_id,
            "keyword": keyword,
            "order_by": order_by,
        },
        visibility,
    )
    return paginated(items, total, page, page_size)


@router.get("/{video_id}", summary="视频详情（含相关推荐）")
def video_detail(video_id: int, user: CurrentUser, visibility: Visibility) -> dict:
    return ok(video_service.client_detail(video_id, user, visibility))


@router.get("/{video_id}/related", summary="更多相关视频")
def related(
    video_id: int,
    user: CurrentUser,
    visibility: Visibility,
    limit: Annotated[int, Query(ge=1, le=30)] = 8,
) -> dict:
    return ok(video_service.client_related(video_id, visibility, limit=limit))


@router.get("/{video_id}/play-info", summary="播放前信息（续播位置/收藏/播放次数）")
def play_info(video_id: int, user: CurrentUser, visibility: Visibility) -> dict:
    return ok(play_service.get_play_info(video_id, user, visibility))


@router.post("/{video_id}/play-report", summary="播放心跳上报（进度 + 观看次数统计）")
def play_report(
    video_id: int,
    payload: PlayReportRequest,
    user: CurrentUser,
    visibility: Visibility,
    ip: ClientIP,
    ua: UserAgent,
) -> dict:
    return ok(
        play_service.report_progress(
            video_id, user, visibility, payload.model_dump(), ip=ip, user_agent=ua
        )
    )
