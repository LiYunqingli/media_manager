"""通用数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PageQuery(BaseModel):
    """分页查询参数。"""

    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=1, le=100, description="每页条数，最大 100")


class IdsRequest(BaseModel):
    """批量 ID 操作。"""

    ids: list[int] = Field(default_factory=list, description="ID 列表")
