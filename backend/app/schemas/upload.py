"""分片上传相关数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class UploadInitRequest(BaseModel):
    """初始化上传会话（第 1 步：分配）。"""

    file_name: str = Field(..., min_length=1, max_length=255)
    file_size: int = Field(..., ge=0, description="文件总字节数")
    file_hash: str = Field("", max_length=64, description="整文件 MD5/SHA，用于秒传与校验")
    chunk_size: int = Field(0, ge=0, description="期望分片大小，0 表示用服务端配置")
    category_id: int = Field(0, ge=0, description="预选分类，可后续再改")
    title: str = Field("", max_length=255)
    description: str = Field("")


class UploadMergeRequest(BaseModel):
    """触发合并（第 3 步）。"""

    category_id: int = Field(..., ge=1, description="最终归属分类")
    title: str = Field("", max_length=255, description="视频标题，留空则用文件名")
    description: str = Field("")
    cover: str = Field("", max_length=512, description="管理员自定义封面，留空则自动抽帧")
    sort: int = Field(0, ge=-9999, le=9999)


class UploadProgress(BaseModel):
    """上传进度快照（HTTP 轮询与 WebSocket 推送共用同一结构）。"""

    upload_id: str
    stage: str = Field(..., description="init/uploading/merging/probing/covering/finished/failed")
    stage_text: str = ""
    percent: float = 0
    total_size: int = 0
    total_chunks: int = 0
    uploaded_chunks: int = 0
    merged_bytes: int = 0
    speed: int = 0
    message: str = ""
    error: str = ""
    video_id: int = 0
    uploaded_indexes: list[int] = Field(default_factory=list)
