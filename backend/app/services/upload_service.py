"""分片上传服务。

流程
----
::

    ① /init      分配任务      -> 生成 upload_id、分片大小、总分片数（可秒传）
    ② /chunk     分片上传      -> 前端把文件切成 N 片逐片 POST，每片落盘 + 记库
    ③ /merge     触发合并      -> 后台线程按序拼接为一个完整文件（实时写合并进度）
    ④ 内部       探测元信息    -> 时长/分辨率/码率
    ⑤ 内部       生成封面      -> 优先手动封面，否则抽关键帧
    ⑥ /progress  查询进度      -> 轮询或 WebSocket 推送同一份快照

进度分段（整体 0-100）
------------------------
============  =========  =========================================
阶段          区间        计算方式
============  =========  =========================================
init          0          仅分配，尚无传输
uploading     0 - 70     已上传分片数 / 总分片数
merging       70 - 90    已合并字节 / 总字节
probing       90 - 95    解析元信息
covering      95 - 100   抽帧生成封面
finished      100        全部完成
============  =========  =========================================

所有进度都持久化在 ``upload_session`` 表，因此**刷新页面、重启进程都不会丢**。
"""
from __future__ import annotations

import contextlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.repositories import upload_repo, video_repo
from app.services import media_service
from app.utils import files as file_utils
from app.utils.presenter import present_upload

logger = get_logger("upload")

# 各阶段的整体进度区间
STAGE_RANGE: dict[str, tuple[float, float]] = {
    "init": (0.0, 0.0),
    "uploading": (0.0, 70.0),
    "merging": (70.0, 90.0),
    "probing": (90.0, 95.0),
    "covering": (95.0, 100.0),
    "finished": (100.0, 100.0),
    "failed": (0.0, 100.0),
}

_MERGE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="merge")
_RUNNING: set[str] = set()
_RUNNING_LOCK = threading.Lock()
_SPEED_CACHE: dict[str, tuple[float, int]] = {}  # upload_id -> (timestamp, bytes)


# ===========================================================================
# 路径辅助
# ===========================================================================
def chunk_dir(upload_id: str) -> Path:
    """分片存放目录：``storage/chunks/<upload_id>/``。"""
    return get_settings().storage_dir("chunk_dir") / upload_id


def chunk_file(upload_id: str, index: int) -> Path:
    return chunk_dir(upload_id) / f"{index:08d}.part"


def _rel(path: Path, root: Path) -> str:
    """转成相对 storage 根目录的 POSIX 风格路径（入库用）。"""
    return path.resolve().relative_to(root.resolve()).as_posix()


# ===========================================================================
# ① 初始化
# ===========================================================================
def init_upload(user: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """创建上传会话。若整文件 hash 命中已有视频则直接秒传。"""
    settings = get_settings()
    file_name = file_utils.safe_filename(payload.get("file_name") or "")
    file_size = int(payload.get("file_size") or 0)
    file_hash = (payload.get("file_hash") or "").strip().lower()

    if not file_name:
        raise BizError(ErrorCode.PARAM_ERROR, "文件名不能为空")
    if not file_utils.check_ext(file_name, settings.get("storage.allow_video_ext", [])):
        raise BizError(ErrorCode.UNSUPPORTED_FILE_TYPE, f"不支持的视频格式: {file_utils.ext_of(file_name)}")

    max_size = int(settings.get("storage.max_file_size", 0) or 0)
    if max_size and file_size > max_size:
        raise BizError(ErrorCode.FILE_TOO_LARGE, f"文件超过上限 {file_utils.human_size(max_size)}")

    # 秒传：同一文件已入库过
    if file_hash:
        existing = video_repo.find_by_hash(file_hash)
        if existing:
            logger.info("命中秒传: %s -> video#%s", file_name, existing["id"])
            return {
                "instant": True,
                "upload_id": "",
                "video_id": int(existing["id"]),
                "chunk_size": 0,
                "total_chunks": 0,
                "total_size": int(existing.get("size") or 0),
                "message": "该文件已存在，秒传完成",
            }

    chunk_size = int(payload.get("chunk_size") or 0) or settings.chunk_size
    chunk_size = max(256 * 1024, min(chunk_size, 64 * 1024 * 1024))  # 限制 256KB ~ 64MB
    total_chunks = (file_size + chunk_size - 1) // chunk_size if file_size else 0
    if total_chunks > int(settings.get("upload.max_chunks", 20000)):
        raise BizError(ErrorCode.PARAM_ERROR, f"分片数过多（{total_chunks}），请调大分片大小")

    upload_id = uuid.uuid4().hex
    target_dir = chunk_dir(upload_id)
    file_utils.ensure_dir(target_dir)

    upload_repo.create_session(
        upload_id=upload_id,
        user_id=int(user["id"]),
        file_name=file_name,
        total_size=file_size,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        file_hash=file_hash,
        category_id=int(payload.get("category_id") or 0),
        title=(payload.get("title") or Path(file_name).stem)[:255],
    )
    logger.info(
        "分配上传任务 %s: %s, %s, %d 片 x %s",
        upload_id, file_name, file_utils.human_size(file_size),
        total_chunks, file_utils.human_size(chunk_size),
    )
    row = upload_repo.get(upload_id) or {}
    data = present_upload(row)
    data["instant"] = False
    return data


# ===========================================================================
# ② 上传分片
# ===========================================================================
def save_chunk(
    user: dict[str, Any],
    upload_id: str,
    index: int,
    content: bytes,
) -> dict[str, Any]:
    """保存一个分片。支持重复上传（覆盖），天然支持断点续传。"""
    session = _get_owned_session(user, upload_id)
    if session["stage"] in ("finished", "merging"):
        raise BizError(ErrorCode.INVALID_REQUEST, f"当前阶段({session['stage']})不接受分片")

    total_chunks = int(session["total_chunks"])
    if index < 0 or index >= total_chunks:
        raise BizError(ErrorCode.UPLOAD_CHUNK_INVALID, f"分片序号越界: {index}")
    if not content:
        raise BizError(ErrorCode.UPLOAD_CHUNK_INVALID, "分片内容为空")

    expected = int(session["chunk_size"])
    # 最后一片通常小于 chunk_size
    is_last = index == total_chunks - 1
    if not is_last and len(content) > expected:
        raise BizError(ErrorCode.UPLOAD_CHUNK_INVALID, f"分片大小超出预期（{len(content)} > {expected}）")

    target = chunk_file(upload_id, index)
    file_utils.ensure_dir(target.parent)
    tmp = target.with_suffix(".tmp")
    with tmp.open("wb") as fp:
        fp.write(content)
    tmp.replace(target)  # 原子替换，避免半截文件被合并

    inserted = upload_repo.add_chunk(upload_id, index, len(content))
    uploaded = upload_repo.sync_uploaded_count(upload_id)

    percent = _stage_percent("uploading", uploaded / total_chunks if total_chunks else 0)
    speed = _touch_speed(upload_id, uploaded * expected)
    upload_repo.update(
        upload_id,
        {
            "stage": "uploading",
            "uploaded_chunks": uploaded,
            "percent": percent,
            "speed": speed,
            "message": f"已上传 {uploaded}/{total_chunks} 片",
        },
    )
    if inserted:
        logger.debug("分片 %s #%d 落盘 (%d 字节)", upload_id, index, len(content))

    row = upload_repo.get(upload_id) or {}
    return present_upload(row, uploaded_indexes=upload_repo.list_chunk_indexes(upload_id))


# ===========================================================================
# ③ 进度
# ===========================================================================
def get_progress(user: dict[str, Any], upload_id: str, *, with_indexes: bool = False) -> dict[str, Any]:
    session = _get_owned_session(user, upload_id)
    indexes = upload_repo.list_chunk_indexes(upload_id) if with_indexes else []
    return present_upload(session, uploaded_indexes=indexes)


def snapshot(upload_id: str) -> dict[str, Any] | None:
    """供 WebSocket 推送使用的原始进度快照（不做鉴权）。"""
    row = upload_repo.get(upload_id)
    if not row:
        return None
    return present_upload(row)


# ===========================================================================
# ④ 合并
# ===========================================================================
def start_merge(user: dict[str, Any], upload_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """触发合并（异步）。立即返回当前进度，前端转去监听 merging 阶段。"""
    session = _get_owned_session(user, upload_id)
    if session["stage"] == "finished":
        return present_upload(session)

    category_id = int(payload.get("category_id") or session.get("category_id") or 0)
    if category_id <= 0:
        raise BizError(ErrorCode.PARAM_ERROR, "请选择视频分类")

    with _RUNNING_LOCK:
        if upload_id in _RUNNING:
            logger.info("合并任务已在进行中: %s", upload_id)
            return present_upload(session)
        _RUNNING.add(upload_id)

    upload_repo.update(
        upload_id,
        {
            "stage": "merging",
            "percent": _stage_percent("merging", 0),
            "message": "开始合并分片",
            "error": "",
            "category_id": category_id,
            "title": (payload.get("title") or session.get("title") or "").strip()[:255],
        },
    )
    _MERGE_EXECUTOR.submit(_merge_worker, upload_id, payload)

    row = upload_repo.get(upload_id) or {}
    return present_upload(row)


def _merge_worker(upload_id: str, payload: dict[str, Any]) -> None:
    """后台合并线程。任何异常都落到 session.error，前端可见。"""
    started = time.time()
    settings = get_settings()
    try:
        session = upload_repo.get(upload_id)
        if not session:
            return

        total_chunks = int(session["total_chunks"])
        total_size = int(session["total_size"])
        chunk_size = int(session["chunk_size"])

        if bool(settings.get("upload.verify_chunks", True)):
            uploaded = upload_repo.count_chunks(upload_id)
            if uploaded != total_chunks:
                missing = [
                    str(i) for i in range(total_chunks)
                    if not chunk_file(upload_id, i).exists()
                ][:20]
                raise BizError(
                    ErrorCode.UPLOAD_INCOMPLETE,
                    f"分片不完整（{uploaded}/{total_chunks}），缺失: {', '.join(missing)}",
                )

        # 目标文件：storage/videos/YYYY/MM/<时间戳_短uuid>.mp4
        video_root = settings.storage_dir("video_dir")
        sub = file_utils.dated_subdir(by_day=False)
        stored_name = file_utils.generate_stored_name(session["file_name"])
        target_dir = video_root / sub
        file_utils.ensure_dir(target_dir)
        target = target_dir / stored_name
        tmp_target = target.with_suffix(target.suffix + ".merging")

        written = 0
        last_report = 0.0
        with tmp_target.open("wb") as out:
            for index in range(total_chunks):
                part = chunk_file(upload_id, index)
                if not part.exists():
                    raise BizError(ErrorCode.UPLOAD_INCOMPLETE, f"分片缺失: {index}")
                with part.open("rb") as fp:
                    while True:
                        block = fp.read(1024 * 1024)
                        if not block:
                            break
                        out.write(block)
                        written += len(block)

                # 限频写库（默认 300ms 一次），避免高频 UPDATE 拖慢合并
                now = time.time()
                if now - last_report >= float(settings.get("upload.progress_interval_ms", 300)) / 1000:
                    last_report = now
                    ratio = written / total_size if total_size else 0
                    upload_repo.update(
                        upload_id,
                        {
                            "stage": "merging",
                            "merged_bytes": written,
                            "percent": _stage_percent("merging", ratio),
                            "speed": _touch_speed(upload_id, written),
                            "message": f"合并中 {file_utils.human_size(written)} / {file_utils.human_size(total_size)}",
                        },
                    )
            out.flush()

        actual_size = file_utils.file_size(tmp_target)
        if total_size and actual_size != total_size:
            raise BizError(
                ErrorCode.UPLOAD_MERGE_FAILED,
                f"合并后大小不符（期望 {total_size}，实际 {actual_size}）",
            )

        merged_path = target
        tmp_target.replace(merged_path)
        logger.info("合并完成 %s -> %s (%s)", upload_id, merged_path.name, file_utils.human_size(actual_size))

        # ---------------- 容器校验 / 自动转封装 ----------------
        # 扩展名不可信：把 .ts / .flv / .mkv 改名成 .mp4 的上游文件很常见。这类文件
        # 字节完整、FFmpeg 也能解码，但系统播放器按扩展名解析会报「文件已损坏」，
        # 容易被误判成上传/合并出错。合并是**按字节原样拼接**、不做转封装，所以这里
        # 检测到不匹配就**自动转封装**（stream copy，无损、秒级），失败才退回提示。
        container_note = ""
        actual_container = media_service.detect_container(merged_path)
        allowed = media_service.CONTAINERS_BY_EXT.get(target.suffix.lower())
        if actual_container != "unknown" and allowed and actual_container not in allowed:
            logger.warning(
                "容器与扩展名不符 %s: 实际=%s 扩展名=%s",
                merged_path.name, actual_container, target.suffix,
            )
            remuxed = False
            if bool(settings.get("media.auto_remux", True)):
                upload_repo.update(
                    upload_id,
                    {
                        "stage": "merging",
                        "percent": _stage_percent("merging", 1.0),
                        "message": f"检测到 {actual_container.upper()} 容器，正在转封装为 {target.suffix}…",
                    },
                )
                remuxed = _remux_in_place(merged_path, target.suffix)

            if remuxed:
                actual_size = file_utils.file_size(merged_path)
                container_note = (
                    f"原文件实为 {actual_container.upper()} 容器，已自动转封装为 {target.suffix.upper()}"
                )
                logger.info(
                    "已自动转封装 %s: %s -> %s (%s)",
                    merged_path.name, actual_container, target.suffix,
                    file_utils.human_size(actual_size),
                )
            else:
                container_note = (
                    f"文件实际是 {actual_container.upper()} 容器，与扩展名 {target.suffix} 不符，"
                    "系统播放器可能提示文件损坏（建议用 VLC/PotPlayer 打开，或转封装为 MP4）"
                )

        # ---------------- 探测元信息 ----------------
        upload_repo.update(
            upload_id,
            {"stage": "probing", "percent": _stage_percent("probing", 0.3), "message": "解析视频信息"},
        )
        info = media_service.probe(merged_path)
        upload_repo.update(upload_id, {"percent": _stage_percent("probing", 1.0)})

        # ---------------- 生成封面 ----------------
        upload_repo.update(
            upload_id,
            {"stage": "covering", "percent": _stage_percent("covering", 0.2), "message": "生成视频封面"},
        )
        cover_rel = ""
        cover_source = 0
        manual_cover = (payload.get("cover") or "").strip()
        if manual_cover:
            cover_rel = manual_cover.lstrip("/")
            cover_source = 1
        else:
            cover_dir = settings.storage_dir("cover_dir")
            cover_sub = file_utils.dated_subdir(by_day=False)
            cover_name = f"{target.stem}.jpg"
            cover_path = cover_dir / cover_sub / cover_name
            ok, backend = media_service.extract_cover(merged_path, cover_path)
            if ok:
                cover_rel = _rel(cover_path, settings.storage_root)
                cover_source = 0
                logger.info("封面已生成 [%s] %s", backend, cover_name)
            else:
                logger.warning("封面生成失败（前端将显示占位图）: %s", target.stem)

        # ---------------- 入库 ----------------
        relative_video = _rel(merged_path, settings.storage_root)
        title = (payload.get("title") or session.get("title") or Path(session["file_name"]).stem)[:255]
        video_id = video_repo.create(
            category_id=int(payload.get("category_id") or session.get("category_id") or 0),
            title=title,
            description=payload.get("description") or "",
            cover=cover_rel,
            path=relative_video,
            original_name=session["file_name"],
            duration=float(info.get("duration") or 0),
            size=actual_size,
            width=int(info.get("width") or 0),
            height=int(info.get("height") or 0),
            bitrate=int(info.get("bitrate") or 0),
            mime=media_service.guess_mime(session["file_name"]),
            cover_source=cover_source,
            sort=int(payload.get("sort") or 0),
            status=1,
        )

        upload_repo.update(
            upload_id,
            {
                "stage": "finished",
                "percent": 100,
                "video_id": video_id,
                "merged_bytes": actual_size,
                "speed": 0,
                "message": f"完成，耗时 {time.time() - started:.1f}s"
                + (f"｜注意：{container_note}" if container_note else ""),
            },
        )

        if bool(settings.get("upload.remove_chunks_after_merge", True)):
            _cleanup_chunks(upload_id)

        logger.info("视频入库完成 video#%d (%s)", video_id, title)

    except BizError as exc:
        logger.error("合并失败 %s: %s", upload_id, exc.message)
        upload_repo.update(upload_id, {"stage": "failed", "error": exc.message, "message": "处理失败"})
    except Exception as exc:  # noqa: BLE001
        logger.exception("合并异常 %s: %s", upload_id, exc)
        upload_repo.update(
            upload_id, {"stage": "failed", "error": str(exc)[:480], "message": "处理失败"}
        )
    finally:
        with _RUNNING_LOCK:
            _RUNNING.discard(upload_id)
        _SPEED_CACHE.pop(upload_id, None)


def _remux_in_place(path: Path, ext: str) -> bool:
    """把 ``path`` 就地转封装为 ``ext`` 对应的容器。

    先写到 ``storage/tmp`` 下的临时文件，校验容器正确后才原子替换原文件；
    任何一步失败都保持原文件不变（宁可留一个容器不符的文件，也不能把内容搞丢）。
    """
    settings = get_settings()
    tmp_dir = settings.storage_dir("tmp_dir")
    file_utils.ensure_dir(tmp_dir)
    tmp_out = tmp_dir / f"{path.stem}.remux{ext}"

    ok, detail = media_service.remux_to_container(path, ext, out_path=tmp_out)
    if not ok:
        logger.warning("转封装失败，保留原文件 %s: %s", path.name, detail)
        with contextlib.suppress(OSError):
            tmp_out.unlink()
        return False

    try:
        tmp_out.replace(path)
    except OSError as exc:
        logger.warning("转封装结果落盘失败 %s: %s", path.name, exc)
        with contextlib.suppress(OSError):
            tmp_out.unlink()
        return False
    return True


def cancel_upload(user: dict[str, Any], upload_id: str) -> None:
    """取消上传：删除会话与已落盘分片。"""
    session = _get_owned_session(user, upload_id)
    if session["stage"] == "merging":
        raise BizError(ErrorCode.INVALID_REQUEST, "正在合并中，无法取消")
    _cleanup_chunks(upload_id)
    upload_repo.delete_session(upload_id)


def cleanup_expired() -> int:
    """清理超时未完成的上传会话（可由定时任务调用）。"""
    hours = int(get_settings().get("upload.session_expire_hours", 24))
    rows = upload_repo.list_unfinished_before(hours)
    for row in rows:
        upload_id = row["upload_id"]
        _cleanup_chunks(upload_id)
        upload_repo.delete_session(upload_id)
        logger.info("清理过期上传会话: %s", upload_id)
    return len(rows)


# ===========================================================================
# 内部工具
# ===========================================================================
def _get_owned_session(user: dict[str, Any], upload_id: str) -> dict[str, Any]:
    session = upload_repo.get(upload_id)
    if not session:
        raise BizError(ErrorCode.UPLOAD_NOT_FOUND)
    if int(session["user_id"]) != int(user["id"]) and user.get("role") != "admin":
        raise BizError(ErrorCode.FORBIDDEN, "无权操作他人的上传任务")
    return session


def _stage_percent(stage: str, ratio: float) -> float:
    """把阶段内进度比例映射到整体百分比。"""
    low, high = STAGE_RANGE.get(stage, (0.0, 100.0))
    ratio = max(0.0, min(1.0, float(ratio or 0)))
    return round(low + (high - low) * ratio, 2)


def _touch_speed(upload_id: str, bytes_done: int) -> int:
    """计算瞬时速度（字节/秒），基于两次调用之间的增量。"""
    now = time.time()
    prev = _SPEED_CACHE.get(upload_id)
    _SPEED_CACHE[upload_id] = (now, bytes_done)
    if not prev:
        return 0
    prev_ts, prev_bytes = prev
    elapsed = now - prev_ts
    if elapsed <= 0.05:
        return 0
    delta = max(0, bytes_done - prev_bytes)
    return int(delta / elapsed)


def _cleanup_chunks(upload_id: str) -> None:
    file_utils.remove_dir(chunk_dir(upload_id))
    upload_repo.clear_chunks(upload_id)
