"""管理端：分类管理。"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentAdmin
from app.core.response import ok
from app.schemas.category import CategoryCreateRequest, CategorySortRequest, CategoryUpdateRequest
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["管理端-分类"])


@router.get("", summary="分类列表（含隐藏分类）")
def list_categories(_: CurrentAdmin) -> dict:
    return ok(category_service.list_for_admin())


@router.post("", summary="新增分类")
def create_category(payload: CategoryCreateRequest, _: CurrentAdmin) -> dict:
    return ok(category_service.create_category(payload.model_dump()))


@router.get("/{category_id}", summary="分类详情")
def get_category(category_id: int, _: CurrentAdmin) -> dict:
    return ok(category_service.get_category(category_id))


@router.put("/{category_id}", summary="修改分类（名称/封面/描述/排序/状态）")
def update_category(category_id: int, payload: CategoryUpdateRequest, _: CurrentAdmin) -> dict:
    return ok(category_service.update_category(category_id, payload.model_dump(exclude_unset=True)))


@router.delete("/{category_id}", summary="删除分类")
def delete_category(
    category_id: int,
    _: CurrentAdmin,
    force: Annotated[bool, Query(description="分类下有视频时是否强制删除（视频一并下架）")] = False,
) -> dict:
    category_service.delete_category(category_id, force=force)
    return ok(msg="分类已删除")


@router.put("/sort/update", summary="批量调整排序（按数组顺序）")
def reorder(payload: CategorySortRequest, _: CurrentAdmin) -> dict:
    return ok(category_service.reorder(payload.ids))
