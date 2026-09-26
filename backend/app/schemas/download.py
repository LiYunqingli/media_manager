"""m3u8 链接下载导入相关数据模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DownloadCreateRequest(BaseModel):
    """创建下载任务。

    最小可用入参只有 ``url`` + ``title`` + ``cover_url``，其余都能走配置兜底
    （分类取 ``download.default_category_id``），方便浏览器插件一句话投递任务。
    """

    url: str = Field(..., min_length=8, max_length=2000, description="m3u8/mpd 播放列表地址")
    title: str = Field("", max_length=255, description="视频名称，留空则回退到链接末段文件名")
    cover_url: str = Field("", max_length=1024, description="远程封面图片地址，留空则自动抽帧")
    category_id: int = Field(0, ge=0, description="目标分类；0 表示用配置的默认分类")
    description: str = Field("", max_length=2000)
    sort: int = Field(0, ge=-9999, le=9999)
    headers: dict[str, str] | None = Field(
        default=None,
        description="附加请求头（如 Cookie / Referer / User-Agent），下载器会原样带上",
    )
    force: bool = Field(False, description="同一链接已成功下载过时是否仍重新下载")


class DownloadTaskOut(BaseModel):
    """任务快照（与 :func:`app.utils.presenter.present_download` 一一对应）。"""

    task_id: str
    stage: str = "queued"
    stage_text: str = ""
    percent: float = 0
    message: str = ""
    error: str = ""
    video_id: int = 0


class DownloadListOut(BaseModel):
    """任务列表。"""

    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    stats: dict[str, Any] = Field(default_factory=dict)
