"""分类服务。"""
from __future__ import annotations

from typing import Any

from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.repositories import category_repo
from app.services import permission_service
from app.utils.presenter import present_categories, present_category

logger = get_logger("category")


def list_for_admin() -> list[dict[str, Any]]:
    """管理端：全部分类（含隐藏分类与全量视频数）。"""
    return present_categories(category_repo.list_with_total_videos())


def list_for_client(visibility: permission_service.Visibility) -> list[dict[str, Any]]:
    """用户端：仅返回可见且启用的分类。"""
    if visibility.is_admin:
        rows = category_repo.list_all(only_enabled=True)
    else:
        allowed = visibility.category_ids or []
        if visibility.deny_category_ids:
            allowed = [c for c in allowed if c not in visibility.deny_category_ids]
        rows = category_repo.list_all(only_enabled=True, allowed_ids=allowed)
    return present_categories(rows)


def get_category(category_id: int) -> dict[str, Any]:
    row = category_repo.find_by_id(category_id)
    if not row:
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND)
    return present_category(row)


def get_visible_category(category_id: int, visibility: permission_service.Visibility) -> dict[str, Any]:
    row = category_repo.find_by_id(category_id)
    if not row:
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND)
    permission_service.assert_category_visible(visibility, category_id)
    if int(row.get("status") or 0) != 1 and not visibility.is_admin:
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND, "分类不存在或已下架")
    return present_category(row)


def create_category(payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    if not name:
        raise BizError(ErrorCode.PARAM_ERROR, "分类名称不能为空")
    if category_repo.find_by_name(name):
        raise BizError(ErrorCode.CATEGORY_NAME_EXISTS, f"分类已存在: {name}")

    sort = payload.get("sort")
    if sort is None:
        sort = category_repo.max_sort() + 10

    category_id = category_repo.create(
        name=name,
        description=payload.get("description") or "",
        cover=payload.get("cover") or "",
        sort=int(sort),
        status=int(payload.get("status", 1)),
    )
    logger.info("创建分类 #%s %s", category_id, name)
    return get_category(category_id)


def update_category(category_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    current = category_repo.find_by_id(category_id)
    if not current:
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND)

    name = payload.get("name")
    if name is not None:
        name = str(name).strip()
        if not name:
            raise BizError(ErrorCode.PARAM_ERROR, "分类名称不能为空")
        dup = category_repo.find_by_name(name, exclude_id=category_id)
        if dup:
            raise BizError(ErrorCode.CATEGORY_NAME_EXISTS, f"分类已存在: {name}")

    fields = {
        k: payload[k]
        for k in ("name", "description", "cover", "sort", "status")
        if payload.get(k) is not None
    }
    if fields:
        category_repo.update(category_id, fields)
        logger.info("更新分类 #%s: %s", category_id, list(fields.keys()))
    return get_category(category_id)


def delete_category(category_id: int, *, force: bool = False) -> None:
    if not category_repo.find_by_id(category_id):
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND)

    total = category_repo.video_count(category_id)
    if total > 0 and not force:
        raise BizError(
            ErrorCode.CATEGORY_NOT_EMPTY,
            f"该分类下还有 {total} 个视频，请先移走或删除（或使用 force 强制删除）",
        )
    if total > 0:
        # 强制删除时把视频一并标记为下架，避免出现「分类不存在」的孤儿数据
        from app.db import session as db

        db.execute("UPDATE video SET status = 0 WHERE category_id = %s", (category_id,))

    permission_service.cleanup_category_rule(category_id)
    category_repo.delete(category_id)
    logger.info("删除分类 #%s（force=%s）", category_id, force)


def reorder(ids: list[int]) -> list[dict[str, Any]]:
    """按传入顺序重写排序值，步长 10。"""
    if not ids:
        raise BizError(ErrorCode.PARAM_ERROR, "排序列表不能为空")
    pairs = [(int(cid), (index + 1) * 10) for index, cid in enumerate(ids)]
    category_repo.update_sort(pairs)
    return list_for_admin()
