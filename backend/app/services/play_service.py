"""播放行为服务：观看进度、续播位置、观看次数。

观看次数规则
------------
- 前端每次进入播放页生成一个 ``segment_id``（uuid），视为一次「播放会话」；
- 会话内累计观看时长达到阈值（``business.view_count_threshold_seconds``，默认 10 秒）
  才计入 ``video.view_count``，且**同一会话只计一次**；
- 判定用 ``UPDATE ... WHERE counted = 0`` 的原子置位，避免并发重复计数；
- 拖动进度条跳着看不算：只有 ``delta``（真实播放增量）才累加，
  并且单次上报的 ``delta`` 会被服务端夹到合理范围（见 schema 的 le=600）。
"""
from __future__ import annotations

from typing import Any

from app.core.config import get_settings
from app.core.logger import get_logger
from app.repositories import favorite_repo, history_repo, video_repo
from app.services import permission_service
from app.utils.presenter import present_history

logger = get_logger("play")


def get_play_info(video_id: int, user: dict[str, Any], visibility: permission_service.Visibility) -> dict[str, Any]:
    """进入播放页前拉取：续播位置、是否收藏、播放次数等。"""
    row = permission_service.get_visible_video(video_id, visibility)
    user_id = int(user["id"])
    history = history_repo.get(user_id, video_id)
    settings = get_settings()

    return {
        "video_id": video_id,
        "play_url": f"/media/{(row.get('path') or '').lstrip('/')}",
        "duration": float(row.get("duration") or 0),
        "view_count": int(row.get("view_count") or 0),
        "favorited": favorite_repo.exists(user_id, video_id),
        "favorite_count": int(row.get("favorite_count") or 0),
        "last_position": float(history.get("last_position") or 0) if history else 0.0,
        "progress": round(float(history.get("progress") or 0), 2) if history else 0.0,
        "watch_seconds": round(float(history.get("watch_seconds") or 0), 1) if history else 0.0,
        "finished": int(history.get("finished") or 0) if history else 0,
        "count_threshold": settings.view_threshold_seconds,
        "heartbeat_interval": int(settings.get("business.heartbeat_interval_seconds", 5)),
    }


def report_progress(
    video_id: int,
    user: dict[str, Any],
    visibility: permission_service.Visibility,
    payload: dict[str, Any],
    *,
    ip: str = "",
    user_agent: str = "",
) -> dict[str, Any]:
    """上报播放心跳，返回最新播放次数 / 是否已计数。"""
    row = permission_service.get_visible_video(video_id, visibility)
    user_id = int(user["id"])
    segment_id = str(payload["segment_id"]).strip()

    settings = get_settings()
    threshold = settings.view_threshold_seconds
    finished_percent = float(settings.get("business.finished_percent", 95))

    position = max(0.0, float(payload.get("position") or 0))
    duration = max(0.0, float(payload.get("duration") or 0)) or float(row.get("duration") or 0)
    delta = max(0.0, float(payload.get("delta") or 0))
    # 单次上报增量夹紧，防止伪造超大值
    delta = min(delta, 600.0)

    # 进度百分比
    if duration > 0:
        progress = min(100.0, max(0.0, position / duration * 100))
    else:
        progress = 0.0
    finished = 1 if (duration > 0 and progress >= finished_percent) else 0
    if finished and position < duration:
        # 自动连播在结尾会停在 duration 附近，回写为完整进度
        position = max(position, duration)

    # ---- 1) 会话累计 + 观看次数判定 ----
    history_repo.ensure_session(
        segment_id=segment_id,
        user_id=user_id,
        video_id=video_id,
        ip=ip,
        user_agent=user_agent,
    )
    if delta > 0:
        history_repo.add_session_seconds(segment_id, delta)

    session = history_repo.get_session(segment_id) or {}
    counted_now = False
    if int(session.get("counted") or 0) == 0 and float(session.get("watch_seconds") or 0) >= threshold:
        if history_repo.mark_session_counted(segment_id) == 1:
            video_repo.increment_view(video_id)
            counted_now = True
            logger.info("视频 #%s 播放次数 +1（会话 %s 累计 %.1fs）", video_id, segment_id, session.get("watch_seconds"))

    # ---- 2) 观看历史（续播位置）----
    history_repo.upsert_progress(
        user_id=user_id,
        video_id=video_id,
        last_position=position,
        duration=duration,
        progress=progress,
        watch_seconds=delta,
        finished=finished,
        segment_id=segment_id,
    )

    view_count = history_repo.video_view_total(video_id)
    return {
        "video_id": video_id,
        "view_count": view_count,
        "counted": counted_now,
        "session_seconds": round(float(session.get("watch_seconds") or 0) + delta, 1),
        "threshold": threshold,
        "progress": round(progress, 2),
        "finished": finished,
        "saved_position": round(position, 2),
    }


# ===========================================================================
# 收藏
# ===========================================================================
def toggle_favorite(
    video_id: int, user: dict[str, Any], visibility: permission_service.Visibility
) -> dict[str, Any]:
    """收藏/取消收藏（幂等开关）。"""
    row = permission_service.get_visible_video(video_id, visibility)
    user_id = int(user["id"])

    if favorite_repo.exists(user_id, video_id):
        favorite_repo.remove(user_id, video_id)
        video_repo.adjust_favorite(video_id, -1)
        favorited = False
    else:
        favorite_repo.add(user_id, video_id)
        video_repo.adjust_favorite(video_id, 1)
        favorited = True

    count = favorite_repo.count_by_video(video_id)
    logger.info("用户 #%s %s 视频 #%s（当前收藏数 %s）", user_id, "收藏" if favorited else "取消收藏", video_id, count)
    return {"favorited": favorited, "favorite_count": count, "video_id": video_id}


def set_favorite(
    video_id: int, user: dict[str, Any], visibility: permission_service.Visibility, favorited: bool
) -> dict[str, Any]:
    """显式设置收藏状态（避免前端状态不同步时反复切换）。"""
    permission_service.get_visible_video(video_id, visibility)
    user_id = int(user["id"])
    current = favorite_repo.exists(user_id, video_id)
    if current != favorited:
        if favorited:
            favorite_repo.add(user_id, video_id)
            video_repo.adjust_favorite(video_id, 1)
        else:
            favorite_repo.remove(user_id, video_id)
            video_repo.adjust_favorite(video_id, -1)
    return {
        "favorited": favorited,
        "favorite_count": favorite_repo.count_by_video(video_id),
        "video_id": video_id,
    }


def list_favorites(user: dict[str, Any], *, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    from app.utils.presenter import present_favorite

    rows, total = favorite_repo.list_by_user(user_id=int(user["id"]), page=page, page_size=page_size)
    return [present_favorite(r) for r in rows], total


# ===========================================================================
# 历史
# ===========================================================================
def list_history(user: dict[str, Any], *, page: int, page_size: int) -> tuple[list[dict[str, Any]], int]:
    rows, total = history_repo.list_by_user(user_id=int(user["id"]), page=page, page_size=page_size)
    return [present_history(r) for r in rows], total


def delete_history(video_id: int, user: dict[str, Any]) -> None:
    history_repo.delete(int(user["id"]), video_id)


def clear_history(user: dict[str, Any]) -> None:
    history_repo.clear(int(user["id"]))
