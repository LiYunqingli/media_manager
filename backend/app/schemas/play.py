"""播放行为相关数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PlayReportRequest(BaseModel):
    """播放心跳上报。

    前端每次心跳（默认 5 秒）或暂停/退出时上报一次。

    - ``segment_id``：前端每次进入播放页生成的会话 ID（uuid），用于「观看次数」去重；
    - ``position``：当前播放位置（秒），用于续播；
    - ``duration``：视频总时长（秒），0 表示未知；
    - ``delta``：**本次上报**新增的观看秒数，服务端累加用于判断是否满 10 秒。
    """

    segment_id: str = Field(..., min_length=8, max_length=40)
    position: float = Field(0, ge=0)
    duration: float = Field(0, ge=0)
    delta: float = Field(0, ge=0, le=600, description="单次上报最多 600 秒，防刷")


class FavoriteToggleResponse(BaseModel):
    favorited: bool
    favorite_count: int
