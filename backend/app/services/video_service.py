"""视频服务（管理端 + 用户端）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.repositories import category_repo, favorite_repo, history_repo, video_repo
from app.services import media_service, permission_service
from app.utils import files as file_utils
from app.utils.presenter import present_category, present_video, present_videos

logger = get_logger("video")


# ===========================================================================
# 管理端
# ===========================================================================
def admin_list(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    rows, total = video_repo.list_page(
        page=int(payload.get("page") or 1),
        page_size=int(payload.get("page_size") or 20),
        category_id=int(payload["category_id"]) if payload.get("category_id") else None,
        keyword=payload.get("keyword") or "",
        status=payload.get("status") or "",
        order_by=payload.get("order_by") or "created_at",
        order_desc=True,
    )
    return present_videos(rows, detail=True), total


def admin_detail(video_id: int) -> dict[str, Any]:
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)
    data = present_video(row, detail=True)
    data["favorite_count_real"] = favorite_repo.count_by_video(video_id)
    data["file_exists"] = (get_settings().storage_root / str(row["path"])).exists()
    return data


def update_video(video_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)

    category_id = payload.get("category_id")
    if category_id is not None and not category_repo.find_by_id(int(category_id)):
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND)

    title = payload.get("title")
    if title is not None:
        title = str(title).strip()
        if not title:
            raise BizError(ErrorCode.PARAM_ERROR, "视频标题不能为空")

    fields = {
        k: payload[k]
        for k in ("title", "description", "category_id", "cover", "sort", "status")
        if payload.get(k) is not None
    }
    if "cover" in fields:
        # 管理员自定义封面时标记来源，便于前端区分「自动抽帧/手动上传」
        fields["cover_source"] = 1 if fields["cover"] else 0
    if not fields:
        return admin_detail(video_id)

    video_repo.update(video_id, fields)
    logger.info("更新视频 #%s: %s", video_id, list(fields.keys()))
    return admin_detail(video_id)


def delete_video(video_id: int, *, remove_file: bool = False) -> None:
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)

    if remove_file:
        _remove_media_files(row)

    favorite_repo.delete_by_video(video_id)
    history_repo.delete_by_video(video_id)
    permission_service.cleanup_video_rule(video_id)
    video_repo.delete(video_id)
    logger.info("删除视频 #%s %s（删文件=%s）", video_id, row.get("title"), remove_file)


def regenerate_cover(video_id: int, seek_seconds: float | None = None) -> dict[str, Any]:
    """从视频关键帧重新生成封面。"""
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)

    settings = get_settings()
    source = settings.storage_root / str(row["path"])
    if not source.exists():
        raise BizError(ErrorCode.FILE_NOT_FOUND, f"视频文件不存在: {row['path']}")
    if not media_service.can_extract_cover():
        raise BizError(
            ErrorCode.MEDIA_PROBE_FAILED,
            "未安装抽帧依赖（opencv-python 或 av），无法生成封面",
        )

    cover_dir = settings.storage_dir("cover_dir")
    sub = file_utils.dated_subdir(by_day=False)
    cover_path = cover_dir / sub / f"{source.stem}.jpg"
    cover_path.parent.mkdir(parents=True, exist_ok=True)

    ok, backend = media_service.extract_cover(source, cover_path, seek_seconds=seek_seconds)
    if not ok:
        raise BizError(ErrorCode.MEDIA_PROBE_FAILED, "抽帧失败，请换个时间点重试")

    relative = cover_path.resolve().relative_to(settings.storage_root.resolve()).as_posix()
    video_repo.update(video_id, {"cover": relative, "cover_source": 0})
    logger.info("重新生成封面 video#%s (%s) [%s]", video_id, relative, backend)
    return admin_detail(video_id)


def set_cover(video_id: int, relative_cover: str) -> dict[str, Any]:
    """设置自定义封面路径。"""
    if not video_repo.find_by_id(video_id):
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)
    video_repo.update(
        video_id, {"cover": relative_cover.lstrip("/"), "cover_source": 1}
    )
    return admin_detail(video_id)


def refresh_meta(video_id: int) -> dict[str, Any]:
    """重新探测时长/分辨率（文件被替换或探测失败时补救）。"""
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)
    source = get_settings().storage_root / str(row["path"])
    if not source.exists():
        raise BizError(ErrorCode.FILE_NOT_FOUND)
    info = media_service.probe(source)
    # probe() 探测失败时返回全 0 结构。若不加判断直接回写，
    # 会把库里已有的分辨率/时长抹成 0，所以只更新探测有效的字段。
    fields: dict[str, Any] = {"size": file_utils.file_size(source)}
    if float(info.get("duration") or 0) > 0:
        fields["duration"] = float(info["duration"])
    if int(info.get("width") or 0) > 0:
        fields["width"] = int(info["width"])
    if int(info.get("height") or 0) > 0:
        fields["height"] = int(info["height"])
    if int(info.get("bitrate") or 0) > 0:
        fields["bitrate"] = int(info["bitrate"])
    video_repo.update(video_id, fields)
    return admin_detail(video_id)


def _remove_media_files(row: dict[str, Any]) -> None:
    settings = get_settings()
    for key in ("path", "cover"):
        rel = row.get(key) or ""
        if not rel:
            continue
        target = (settings.storage_root / rel).resolve()
        if file_utils.is_relative_to(target, settings.storage_root):
            file_utils.remove_file(target)


# ===========================================================================
# 用户端
# ===========================================================================
def client_list(
    payload: dict[str, Any], visibility: permission_service.Visibility
) -> tuple[list[dict[str, Any]], int]:
    category_id = int(payload["category_id"]) if payload.get("category_id") else None
    if category_id:
        permission_service.assert_category_visible(visibility, category_id)

    rows, total = video_repo.list_page(
        page=int(payload.get("page") or 1),
        page_size=int(payload.get("page_size") or 20),
        category_id=category_id,
        keyword=payload.get("keyword") or "",
        status="1",
        order_by=payload.get("order_by") or "created_at",
        **visibility.as_query_kwargs(),
    )
    return present_videos(rows), total


def client_detail(video_id: int, user: dict[str, Any], visibility: permission_service.Visibility) -> dict[str, Any]:
    row = permission_service.get_visible_video(video_id, visibility)
    if int(row.get("status") or 0) != 1 and not visibility.is_admin:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND, "视频不存在或已下架")

    data = present_video(row, detail=True)
    data["favorited"] = favorite_repo.exists(int(user["id"]), video_id)

    history = history_repo.get(int(user["id"]), video_id)
    data["history"] = (
        {
            "last_position": float(history.get("last_position") or 0),
            "progress": round(float(history.get("progress") or 0), 2),
            "watch_seconds": round(float(history.get("watch_seconds") or 0), 1),
            "finished": int(history.get("finished") or 0),
        }
        if history
        else None
    )
    data["related"] = client_related(video_id, visibility, limit=int(get_settings().get("business.related_limit", 8)))
    return data


def client_related(
    video_id: int,
    visibility: permission_service.Visibility,
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """相关推荐：同分类优先，不足自动补热门。"""
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)
    rows = video_repo.related(
        video_id,
        int(row["category_id"]),
        limit=limit,
        **visibility.as_query_kwargs(),
    )
    return present_videos(rows)


def client_home(visibility: permission_service.Visibility, user: dict[str, Any] | None = None) -> dict[str, Any]:
    """用户端首页聚合数据。

    结构::

        {
          "banners": [...],          # 轮播：最新 + 热门
          "hot": [...],              # 热门推荐
          "latest": [...],           # 最新上传
          "continue_watch": [...],   # 继续观看（登录用户）
          "sections": [              # 每个可见分类一个板块
            {"category": {...}, "videos": [...]}
          ]
        }
    """
    settings = get_settings()
    section_size = int(settings.get("business.home_section_size", 12))
    kwargs = visibility.as_query_kwargs()

    hot = present_videos(video_repo.list_hot(limit=12, **kwargs))
    latest = present_videos(video_repo.list_latest(limit=12, **kwargs))

    categories = []
    if visibility.is_admin:
        categories = category_repo.list_all(only_enabled=True)
    else:
        allowed = visibility.category_ids or []
        if visibility.deny_category_ids:
            allowed = [c for c in allowed if c not in visibility.deny_category_ids]
        categories = category_repo.list_all(only_enabled=True, allowed_ids=allowed)

    sections = []
    for category in categories:
        videos = video_repo.list_by_category(
            int(category["id"]), limit=section_size, **kwargs
        )
        if not videos:
            continue
        sections.append(
            {
                "category": present_category(category),
                "videos": present_videos(videos),
            }
        )

    continue_watch: list[dict[str, Any]] = []
    if user:
        from app.utils.presenter import present_history

        rows = history_repo.list_continue_watching(
            int(user["id"]), limit=int(settings.get("business.continue_watch_limit", 12))
        )
        continue_watch = [
            present_history(r)
            for r in rows
            if permission_service.is_video_visible(
                visibility, {"id": r["id"], "category_id": r["category_id"]}
            )
        ]

    return {
        "banners": latest[:5] or hot[:5],
        "hot": hot,
        "latest": latest,
        "continue_watch": continue_watch,
        "sections": sections,
    }


def client_search(payload: dict[str, Any], visibility: permission_service.Visibility) -> tuple[list[dict[str, Any]], int]:
    keyword = (payload.get("keyword") or "").strip()
    if not keyword:
        return [], 0
    rows, total = video_repo.list_page(
        page=int(payload.get("page") or 1),
        page_size=int(payload.get("page_size") or 20),
        keyword=keyword,
        status="1",
        order_by="view_count",
        **visibility.as_query_kwargs(),
    )
    return present_videos(rows), total


def resolve_local_path(video_id: int) -> Path:
    """取视频的本地磁盘路径（下载/转码用）。"""
    row = video_repo.find_by_id(video_id)
    if not row:
        raise BizError(ErrorCode.VIDEO_NOT_FOUND)
    path = get_settings().storage_root / str(row["path"])
    if not path.exists():
        raise BizError(ErrorCode.FILE_NOT_FOUND)
    return path
