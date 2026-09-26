"""管理端：视频管理。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin, PageParams
from app.core.response import ok, paginated
from app.schemas.video import CoverFromFrameRequest, VideoUpdateRequest
from app.services import video_service

router = APIRouter(prefix="/videos", tags=["管理端-视频"])


@router.get("", summary="视频列表")
def list_videos(
    _: CurrentAdmin,
    params: PageParams,
    category_id: Annotated[int | None, Query(ge=1)] = None,
    keyword: Annotated[str, Query(max_length=64)] = "",
    status: Annotated[str, Query(pattern=r"^(|0|1)$")] = "",
    order_by: Annotated[str, Query(pattern=r"^(created_at|view_count|duration|title|id)$")] = "created_at",
) -> dict:
    items, total = video_service.admin_list(
        {
            "page": params["page"],
            "page_size": params["page_size"],
            "category_id": category_id,
            "keyword": keyword,
            "status": status,
            "order_by": order_by,
        }
    )
    return paginated(items, total, params["page"], params["page_size"])


@router.get("/{video_id}", summary="视频详情")
def get_video(video_id: int, _: CurrentAdmin) -> dict:
    return ok(video_service.admin_detail(video_id))


@router.put("/{video_id}", summary="编辑视频（标题/简介/分类/封面/排序/上下架）")
def update_video(video_id: int, payload: VideoUpdateRequest, _: CurrentAdmin) -> dict:
    return ok(video_service.update_video(video_id, payload.model_dump(exclude_unset=True)))


@router.delete("/{video_id}", summary="删除视频")
def delete_video(
    video_id: int,
    _: CurrentAdmin,
    remove_file: Annotated[bool, Query(description="是否同时删除磁盘文件")] = False,
) -> dict:
    video_service.delete_video(video_id, remove_file=remove_file)
    return ok(msg="视频已删除")


@router.post("/{video_id}/cover/from-frame", summary="从关键帧重新生成封面")
def cover_from_frame(video_id: int, payload: CoverFromFrameRequest, _: CurrentAdmin) -> dict:
    return ok(video_service.regenerate_cover(video_id, payload.seek_seconds))


@router.put("/{video_id}/cover", summary="设置自定义封面（传已上传图片的相对路径）")
def set_cover(
    video_id: int,
    cover: Annotated[str, Query(max_length=512, description="封面相对路径，如 covers/2026/09/x.jpg")],
    _: CurrentAdmin,
) -> dict:
    return ok(video_service.set_cover(video_id, cover))


@router.post("/{video_id}/refresh-meta", summary="重新探测时长/分辨率")
def refresh_meta(video_id: int, _: CurrentAdmin) -> dict:
    return ok(video_service.refresh_meta(video_id))
