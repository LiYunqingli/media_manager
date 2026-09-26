"""视频相关数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class VideoUpdateRequest(BaseModel):
    """管理端编辑视频元信息（标题 / 封面 / 分类 / 简介 / 上下架）。"""

    title: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    category_id: int | None = Field(None, ge=1)
    cover: str | None = Field(None, max_length=512, description="自定义封面地址")
    sort: int | None = Field(None, ge=-9999, le=9999)
    status: int | None = Field(None, ge=0, le=1)


class VideoQuery(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)
    category_id: int | None = None
    keyword: str = Field("", max_length=64)
    status: str = Field("", pattern=r"^(|0|1)$")
    order_by: str = Field("created_at", pattern=r"^(created_at|view_count|duration|title|id)$")


class CoverFromFrameRequest(BaseModel):
    """从视频关键帧重新抽封面。"""

    seek_seconds: float | None = Field(None, ge=0, description="抽帧时间点（秒），不传则用默认值")
