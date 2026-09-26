"""媒体处理服务：元数据探测 + 关键帧抽封面。

三套后端，按可用性自动降级（可用 ``media.backend`` 强制指定）：

============  ============================================  ==============================
后端           能力                                          依赖
============  ============================================  ==============================
``av``        PyAV：探测最准，可直接编码 JPEG 抽帧            ``av``（可配合 Pillow/numpy）
``cv2``       OpenCV：探测 + 抽帧（写 JPEG 最省事）           ``opencv-python``
``builtin``   纯 Python 解析 MP4 的 moov/mvhd/tkhd，仅时长/ 无（标准库即可）
              分辨率，**不能抽帧**
============  ============================================  ==============================

抽帧优先级：``cv2`` → ``av + Pillow`` → ``av 内置 MJPEG 编码``。
探测优先级：``av`` → ``cv2`` → ``builtin``。

所有第三方导入都是**惰性**的，缺库不会导致进程启动失败，只会在调用时降级。
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger

logger = get_logger("media")

_MIME_MAP = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".mov": "video/quicktime",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".avi": "video/x-msvideo",
    ".flv": "video/x-flv",
    ".ts": "video/mp2t",
    ".wmv": "video/x-ms-wmv",
}


def guess_mime(filename: str) -> str:
    return _MIME_MAP.get(Path(filename).suffix.lower(), "application/octet-stream")


def available_backends() -> dict[str, bool]:
    """返回各后端可用性，供管理端「系统信息」展示与排障。"""
    result = {"av": False, "cv2": False, "PIL": False, "numpy": False, "builtin": True}
    for name in ("av", "cv2", "PIL", "numpy"):
        try:
            __import__(name)
            result[name] = True
        except Exception:  # noqa: BLE001
            result[name] = False
    return result


# ===========================================================================
# 探测
# ===========================================================================
def probe(path: str | Path) -> dict[str, Any]:
    """探测视频元信息。

    :return: ``{duration, width, height, bitrate, fps, has_video, backend}``
             探测失败返回全 0 的结构，不抛异常（不阻塞上传入库）。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise BizError(ErrorCode.FILE_NOT_FOUND, f"文件不存在: {file_path}")

    forced = str(get_settings().get("media.backend", "auto")).lower()
    order = {
        "av": ["av"],
        "cv2": ["cv2"],
        "builtin": ["builtin"],
    }.get(forced, ["av", "cv2", "builtin"])

    empty = {
        "duration": 0.0, "width": 0, "height": 0, "bitrate": 0,
        "fps": 0.0, "has_video": False, "backend": "",
    }
    for backend in order:
        try:
            if backend == "av":
                info = _probe_av(file_path)
            elif backend == "cv2":
                info = _probe_cv2(file_path)
            else:
                info = _probe_builtin(file_path)
            if info and (info.get("duration") or info.get("width")):
                info["backend"] = backend
                logger.info(
                    "探测成功 [%s] %s -> %.2fs %dx%d",
                    backend, file_path.name, info["duration"], info["width"], info["height"],
                )
                return {**empty, **info}
        except Exception as exc:  # noqa: BLE001
            logger.warning("探测后端 %s 失败: %s", backend, exc)
    logger.warning("全部探测后端均失败: %s", file_path)
    return empty


def _probe_av(path: Path) -> dict[str, Any]:
    import av  # 惰性导入

    with av.open(str(path)) as container:
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        video_stream = container.streams.video[0] if container.streams.video else None
        width = height = 0
        fps = 0.0
        if video_stream is not None:
            ctx = video_stream.codec_context
            width = int(ctx.width or 0)
            height = int(ctx.height or 0)
            rate = video_stream.average_rate or video_stream.base_rate
            fps = float(rate) if rate else 0.0
            # 容器时长缺失时用帧数 / 帧率兜底
            if not duration and video_stream.frames and fps:
                duration = float(video_stream.frames) / fps
        bitrate = int(container.bit_rate or 0)
        return {
            "duration": round(duration, 3),
            "width": width,
            "height": height,
            "bitrate": bitrate,
            "fps": round(fps, 3),
            "has_video": video_stream is not None,
        }


def _probe_cv2(path: Path) -> dict[str, Any]:
    import cv2  # 惰性导入

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError("OpenCV 无法打开该文件")
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        duration = frames / fps if fps > 0 else 0.0
        # 部分封装 OpenCV 读不到帧数，退化为「读到结尾计时」
        if duration <= 0:
            count = 0
            while count < 100000:
                ok, _ = cap.read()
                if not ok:
                    break
                count += 1
            duration = count / fps if fps > 0 else 0.0
        bitrate = int(path.stat().st_size * 8 / duration) if duration > 0 else 0
        return {
            "duration": round(duration, 3),
            "width": width,
            "height": height,
            "bitrate": bitrate,
            "fps": round(fps, 3),
            "has_video": width > 0,
        }
    finally:
        cap.release()


# --------------------------------------------------------------------------- #
# 纯 Python MP4 解析（兜底：不依赖任何第三方库）
# --------------------------------------------------------------------------- #
def _probe_builtin(path: Path) -> dict[str, Any]:
    """解析 MP4/MOV 的 moov 盒子，读取 mvhd（时长）与 tkhd（分辨率）。"""
    size = path.stat().st_size
    with path.open("rb") as fp:
        result: dict[str, Any] = {
            "duration": 0.0, "width": 0, "height": 0,
            "bitrate": 0, "fps": 0.0, "has_video": False,
        }
        timescale = 0
        duration = 0
        video_track = None

        def walk(start: int, end: int, depth: int = 0) -> None:
            nonlocal timescale, duration, video_track
            if depth > 4:
                return
            pos = start
            while pos + 8 <= end:
                fp.seek(pos)
                header = fp.read(8)
                if len(header) < 8:
                    return
                box_size, box_type = struct.unpack(">I4s", header)
                header_size = 8
                if box_size == 1:
                    ext = fp.read(8)
                    if len(ext) < 8:
                        return
                    box_size = struct.unpack(">Q", ext)[0]
                    header_size = 16
                elif box_size == 0:
                    box_size = end - pos
                if box_size < header_size:
                    return
                box_type = box_type.decode("latin-1", "ignore")
                body_start = pos + header_size
                body_end = min(pos + box_size, end)

                if box_type in ("moov", "trak", "mdia", "minf", "stbl"):
                    walk(body_start, body_end, depth + 1)
                elif box_type == "mvhd":
                    timescale, duration = _parse_mvhd(fp, body_start, box_size)
                elif box_type == "tkhd":
                    wh = _parse_tkhd(fp, body_start, box_size)
                    if wh and (wh[0] > 0 and wh[1] > 0):
                        video_track = wh
                elif box_type == "mdhd":
                    ts = _parse_mdhd_timescale(fp, body_start, box_size)
                    if ts and timescale == 0:
                        timescale = ts
                pos += box_size

        walk(0, size)

        if timescale > 0 and duration > 0:
            result["duration"] = round(duration / timescale, 3)
        if video_track:
            result["width"], result["height"] = video_track
            result["has_video"] = True
        if result["duration"] > 0:
            result["bitrate"] = int(size * 8 / result["duration"])
        return result


def _parse_mvhd(fp, offset: int, box_size: int) -> tuple[int, int]:
    fp.seek(offset + 4)  # version(1) + flags(3)
    version_byte = fp.read(4)
    if len(version_byte) < 4:
        return 0, 0
    version = version_byte[0]
    if version == 1:
        data = fp.read(8 + 8 + 4)  # creation, modification(8), timescale(4)
        if len(data) < 20:
            return 0, 0
        timescale = struct.unpack(">I", data[16:20])[0]
        duration = struct.unpack(">Q", fp.read(8))[0]
    else:
        data = fp.read(4 + 4 + 4)
        if len(data) < 12:
            return 0, 0
        timescale = struct.unpack(">I", data[8:12])[0]
        duration = struct.unpack(">I", fp.read(4))[0]
    return int(timescale), int(duration)


def _parse_tkhd(fp, offset: int, box_size: int) -> tuple[int, int] | None:
    fp.seek(offset)
    head = fp.read(4)
    if len(head) < 4:
        return None
    version = head[0]
    skip = 8 + 8 if version == 1 else 4 + 4  # creation + modification
    fp.seek(offset + 4 + skip)
    rest = fp.read(8 + 8 + 2 + 2 + 2 + 2 + 36 + 4 + 4)
    if len(rest) < (8 + 8 + 2 + 2 + 2 + 2 + 36 + 8):
        return None
    # 跳过 track_id(4)+reserved(4)+duration(4/8)+reserved(8)+layer(2)+alt(2)+volume(2)+reserved(2)+matrix(36)
    base = len(rest) - 8
    width = struct.unpack(">I", rest[base : base + 4])[0] >> 16
    height = struct.unpack(">I", rest[base + 4 : base + 8])[0] >> 16
    return int(width), int(height)


def _parse_mdhd_timescale(fp, offset: int, box_size: int) -> int | None:
    head = fp.read(4)
    if len(head) < 4:
        return None
    version = head[0]
    skip = 8 + 8 if version == 1 else 4 + 4
    fp.seek(offset + 4 + skip)
    data = fp.read(4)
    if len(data) < 4:
        return None
    return int(struct.unpack(">I", data)[0])


# ===========================================================================
# 封面抽帧
# ===========================================================================
def extract_cover(
    video_path: str | Path,
    output_path: str | Path,
    *,
    seek_seconds: float | None = None,
) -> tuple[bool, str]:
    """从视频抽取关键帧并写为 JPEG。

    :return: ``(是否成功, 使用的后端名)``
    """
    src = Path(video_path)
    dst = Path(output_path)
    dst.parent.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    seeks: list[float] = []
    base_seek = float(
        seek_seconds if seek_seconds is not None else settings.get("media.cover_seek_seconds", 3.0)
    )
    seeks.append(max(0.0, base_seek))
    for fallback in settings.get("media.cover_fallback_seeks", [1.0, 0.0]) or []:
        seeks.append(max(0.0, float(fallback)))

    for backend in ("cv2", "av"):
        for seek in seeks:
            try:
                if backend == "cv2":
                    ok = _cover_cv2(src, dst, seek)
                else:
                    ok = _cover_av(src, dst, seek, allow_pillow=True)
                if ok and dst.exists() and dst.stat().st_size > 0:
                    return True, backend
            except Exception as exc:  # noqa: BLE001
                logger.debug("抽帧失败 [%s @%.1fs]: %s", backend, seek, exc)

    # 最后再试一次纯 av 的 MJPEG 编码（不需要 Pillow）
    try:
        if _cover_av(src, dst, seeks[0], allow_pillow=False) and dst.exists():
            return True, "av-mjpeg"
    except Exception as exc:  # noqa: BLE001
        logger.warning("全部抽帧方案失败: %s", exc)

    return False, ""


def _cover_cv2(src: Path, dst: Path, seek: float) -> bool:
    import cv2  # 惰性导入

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return False
    try:
        if seek > 0:
            cap.set(cv2.CAP_PROP_POS_MSEC, seek * 1000)
        ok, frame = cap.read()
        if not ok or frame is None:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = cap.read()
        if not ok or frame is None:
            return False
        frame = _resize_cv2(frame)
        quality = int(get_settings().get("media.cover_quality", 3))
        return bool(cv2.imwrite(str(dst), frame, [int(cv2.IMWRITE_JPEG_QUALITY), max(1, 100 - quality * 3)]))
    finally:
        cap.release()


def _resize_cv2(frame):
    import cv2

    max_w = int(get_settings().get("media.cover_max_width", 1280))
    max_h = int(get_settings().get("media.cover_max_height", 720))
    h, w = frame.shape[:2]
    if w <= max_w and h <= max_h:
        return frame
    scale = min(max_w / w, max_h / h)
    return cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def _cover_av(src: Path, dst: Path, seek: float, *, allow_pillow: bool) -> bool:
    """PyAV 抽帧。

    ``allow_pillow=True`` 时优先用 ``frame.to_image()``（需 Pillow），
    否则用 PyAV 自带的 MJPEG 编码器直接写出 JPEG（无额外依赖）。
    """
    import av  # 惰性导入

    with av.open(str(src)) as container:
        if not container.streams.video:
            return False
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"

        target = int(seek * av.time_base)
        if target > 0:
            try:
                container.seek(target, backward=True, any_frame=False)
            except Exception:  # noqa: BLE001 - 某些容器不支持 seek，从头解码
                container.seek(0)

        frame = None
        for decoded in container.decode(stream):
            frame = decoded
            break
        if frame is None:
            return False

        if allow_pillow:
            try:
                image = frame.to_image()
                image = _resize_pil(image)
                image.save(str(dst), format="JPEG", quality=int(get_settings().get("media.cover_quality", 3)), optimize=True)
                return True
            except Exception:  # noqa: BLE001 - 缺 Pillow 时落到 MJPEG 编码
                pass

        return _encode_jpeg_av(frame, dst)


def _resize_pil(image):
    max_w = int(get_settings().get("media.cover_max_width", 1280))
    max_h = int(get_settings().get("media.cover_max_height", 720))
    w, h = image.size
    if w <= max_w and h <= max_h:
        return image
    scale = min(max_w / w, max_h / h)
    return image.resize((max(1, int(w * scale)), max(1, int(h * scale))))


def _encode_jpeg_av(frame, dst: Path) -> bool:
    """用 PyAV 的 mjpeg 编码器把单帧写成 JPEG，无需 Pillow。"""
    import av

    container = av.open(str(dst), mode="w", format="image2")
    try:
        stream = container.add_stream("mjpeg", rate=1)
        stream.width = frame.width
        stream.height = frame.height
        stream.pix_fmt = "yuvj420p"
        for packet in stream.encode(frame):
            container.mux(packet)
        for packet in stream.encode(None):
            container.mux(packet)
    finally:
        container.close()
    return dst.exists() and dst.stat().st_size > 0


def can_extract_cover() -> bool:
    """是否存在可用的抽帧后端。"""
    backends = available_backends()
    return bool(backends["cv2"] or backends["av"])
