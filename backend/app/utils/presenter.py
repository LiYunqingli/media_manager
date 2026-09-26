"""数据出参转换（DB 行 -> 前端可见结构）。

集中一处做字段裁剪与衍生字段拼装，保证所有接口返回结构一致：
- 统一补充 ``*_url`` 媒体地址；
- 统一补充 ``duration_text`` / ``size_text`` 便于前端直接展示；
- 屏蔽 ``path`` 之外的无用字段（如内部 hash）。
"""
from __future__ import annotations

from typing import Any

from app.utils.files import format_duration, human_size

# 静态资源挂载前缀，见 app/main.py
MEDIA_PREFIX = "/media"
# 无封面时的占位图（放在 frontend/static/img 下由前端处理，这里返回空串）
DEFAULT_COVER = ""


def build_media_url(rel_path: str | None) -> str:
    """把存储相对路径转成可访问 URL。

    ``videos/2026/09/x.mp4`` -> ``/media/videos/2026/09/x.mp4``
    """
    clean = (rel_path or "").strip().replace("\\", "/").lstrip("/")
    if not clean:
        return ""
    if clean.startswith(("http://", "https://", "/media/", "data:")):
        return clean
    return f"{MEDIA_PREFIX}/{clean}"


# --------------------------------------------------------------------------- #
# 视频
# --------------------------------------------------------------------------- #
def present_video(row: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """视频出参。detail=True 时附带 path/play_url 等播放字段。"""
    cover = row.get("cover") or ""
    duration = float(row.get("duration") or 0)
    data: dict[str, Any] = {
        "id": int(row.get("id") or 0),
        "category_id": int(row.get("category_id") or 0),
        "category_name": row.get("category_name") or "",
        "title": row.get("title") or "",
        "cover": cover,
        "cover_url": build_media_url(cover) or DEFAULT_COVER,
        "duration": duration,
        "duration_text": format_duration(duration),
        "view_count": int(row.get("view_count") or 0),
        "favorite_count": int(row.get("favorite_count") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if detail:
        size = int(row.get("size") or 0)
        data.update(
            {
                "description": row.get("description") or "",
                "path": row.get("path") or "",
                "play_url": build_media_url(row.get("path") or ""),
                "original_name": row.get("original_name") or "",
                "size": size,
                "size_text": human_size(size),
                "width": int(row.get("width") or 0),
                "height": int(row.get("height") or 0),
                "bitrate": int(row.get("bitrate") or 0),
                "mime": row.get("mime") or "",
                "cover_source": int(row.get("cover_source") or 0),
                "sort": int(row.get("sort") or 0),
                "status": int(row.get("status") or 0),
            }
        )
    else:
        data["status"] = int(row.get("status") or 0)
    return data


def present_videos(rows: list[dict[str, Any]], *, detail: bool = False) -> list[dict[str, Any]]:
    return [present_video(r, detail=detail) for r in rows]


# --------------------------------------------------------------------------- #
# 分类
# --------------------------------------------------------------------------- #
def present_category(row: dict[str, Any]) -> dict[str, Any]:
    cover = row.get("cover") or ""
    return {
        "id": int(row.get("id") or 0),
        "name": row.get("name") or "",
        "description": row.get("description") or "",
        "cover": cover,
        "cover_url": build_media_url(cover),
        "sort": int(row.get("sort") or 0),
        "status": int(row.get("status") or 0),
        "video_count": int(row.get("video_count") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def present_categories(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [present_category(r) for r in rows]


# --------------------------------------------------------------------------- #
# 用户
# --------------------------------------------------------------------------- #
def present_user(row: dict[str, Any], *, with_rules: dict[str, Any] | None = None) -> dict[str, Any]:
    avatar = row.get("avatar") or ""
    data: dict[str, Any] = {
        "id": int(row.get("id") or 0),
        "username": row.get("username") or "",
        "nickname": row.get("nickname") or "",
        "avatar": avatar,
        "avatar_url": build_media_url(avatar),
        "email": row.get("email") or "",
        "phone": row.get("phone") or "",
        "role": row.get("role") or "user",
        "status": int(row.get("status") or 0),
        "remark": row.get("remark") or "",
        "last_login_at": row.get("last_login_at"),
        "last_login_ip": row.get("last_login_ip") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    if with_rules is not None:
        data["rules"] = with_rules
    return data


# --------------------------------------------------------------------------- #
# 历史 / 收藏
# --------------------------------------------------------------------------- #
def present_history(row: dict[str, Any]) -> dict[str, Any]:
    cover = row.get("cover") or ""
    duration = float(row.get("duration") or row.get("video_duration") or 0)
    last_position = float(row.get("last_position") or 0)
    return {
        "video_id": int(row.get("id") or row.get("video_id") or 0),
        "title": row.get("title") or "",
        "cover": cover,
        "cover_url": build_media_url(cover),
        "category_id": int(row.get("category_id") or 0),
        "category_name": row.get("category_name") or "",
        "duration": duration,
        "duration_text": format_duration(duration),
        "last_position": last_position,
        "last_position_text": format_duration(last_position),
        "progress": round(float(row.get("progress") or 0), 2),
        "watch_seconds": round(float(row.get("watch_seconds") or 0), 1),
        "finished": int(row.get("finished") or 0),
        "view_count": int(row.get("view_count") or 0),
        "watched_at": row.get("watched_at"),
    }


def present_favorite(row: dict[str, Any]) -> dict[str, Any]:
    cover = row.get("cover") or ""
    duration = float(row.get("duration") or 0)
    return {
        "video_id": int(row.get("id") or 0),
        "title": row.get("title") or "",
        "cover": cover,
        "cover_url": build_media_url(cover),
        "category_id": int(row.get("category_id") or 0),
        "category_name": row.get("category_name") or "",
        "duration": duration,
        "duration_text": format_duration(duration),
        "view_count": int(row.get("view_count") or 0),
        "favorited_at": row.get("favorited_at"),
    }


# --------------------------------------------------------------------------- #
# 上传进度
# --------------------------------------------------------------------------- #
STAGE_TEXT = {
    "init": "已分配上传任务",
    "uploading": "分片上传中",
    "merging": "分片合并中",
    "probing": "解析视频信息",
    "covering": "生成视频封面",
    "finished": "处理完成",
    "failed": "处理失败",
}


def present_upload(row: dict[str, Any], *, uploaded_indexes: list[int] | None = None) -> dict[str, Any]:
    stage = row.get("stage") or "init"
    return {
        "upload_id": row.get("upload_id") or "",
        "file_name": row.get("file_name") or "",
        "stage": stage,
        "stage_text": STAGE_TEXT.get(stage, stage),
        "percent": round(float(row.get("percent") or 0), 2),
        "total_size": int(row.get("total_size") or 0),
        "total_size_text": human_size(row.get("total_size") or 0),
        "chunk_size": int(row.get("chunk_size") or 0),
        "total_chunks": int(row.get("total_chunks") or 0),
        "uploaded_chunks": int(row.get("uploaded_chunks") or 0),
        "merged_bytes": int(row.get("merged_bytes") or 0),
        "merged_percent": round(
            (float(row.get("merged_bytes") or 0) / float(row.get("total_size") or 1)) * 100, 2
        ),
        "speed": int(row.get("speed") or 0),
        "speed_text": f"{human_size(row.get('speed') or 0)}/s",
        "message": row.get("message") or "",
        "error": row.get("error") or "",
        "video_id": int(row.get("video_id") or 0),
        "title": row.get("title") or "",
        "category_id": int(row.get("category_id") or 0),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "uploaded_indexes": uploaded_indexes or [],
    }


# --------------------------------------------------------------------------- #
# m3u8 下载任务
# --------------------------------------------------------------------------- #
DOWNLOAD_STAGE_TEXT = {
    "queued": "排队中",
    "downloading": "下载中",
    "muxing": "混流封装",
    "ingesting": "处理文件",
    "probing": "解析信息",
    "covering": "生成封面",
    "finished": "已完成",
    "failed": "失败",
    "cancelled": "已取消",
}


def present_download(row: dict[str, Any]) -> dict[str, Any]:
    """m3u8 下载任务出参（前端进度卡与插件回调共用）。"""
    stage = row.get("stage") or "queued"
    cover = row.get("cover") or ""
    eta = int(row.get("eta") or 0)
    return {
        "task_id": row.get("task_id") or "",
        "source": row.get("source") or "admin",
        "url": row.get("url") or "",
        "title": row.get("title") or "",
        "cover_url": row.get("cover_url") or "",
        "cover": cover,
        "cover_preview": build_media_url(cover),
        "category_id": int(row.get("category_id") or 0),
        "description": row.get("description") or "",
        "sort": int(row.get("sort") or 0),
        "stage": stage,
        "stage_text": DOWNLOAD_STAGE_TEXT.get(stage, stage),
        "percent": round(float(row.get("percent") or 0), 2),
        "total_bytes": int(row.get("total_bytes") or 0),
        "total_bytes_text": human_size(row.get("total_bytes") or 0),
        "done_bytes": int(row.get("done_bytes") or 0),
        "done_bytes_text": human_size(row.get("done_bytes") or 0),
        "speed": int(row.get("speed") or 0),
        "speed_text": f"{human_size(row.get('speed') or 0)}/s",
        "eta": eta,
        "eta_text": format_duration(eta) if eta else "",
        "video_id": int(row.get("video_id") or 0),
        "file_path": row.get("file_path") or "",
        "message": row.get("message") or "",
        "error": row.get("error") or "",
        "log_tail": row.get("log_tail") or "",
        "elapsed": round(float(row.get("elapsed") or 0), 2),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
        "updated_at": row.get("updated_at"),
    }
