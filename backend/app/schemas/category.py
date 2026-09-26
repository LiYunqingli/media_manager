"""分类相关数据模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    description: str = Field("", max_length=255)
    cover: str = Field("", max_length=512)
    sort: int = Field(0, ge=-9999, le=9999)
    status: int = Field(1, ge=0, le=1)


class CategoryUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    description: str | None = Field(None, max_length=255)
    cover: str | None = Field(None, max_length=512)
    sort: int | None = Field(None, ge=-9999, le=9999)
    status: int | None = Field(None, ge=0, le=1)


class CategorySortRequest(BaseModel):
    """拖拽排序：按数组顺序重写 sort 值。"""

    ids: list[int] = Field(default_factory=list)
