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

import contextlib
import os
import struct
import threading
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger

logger = get_logger("media")

# 串行化 fd 2 的重定向窗口，避免并发抽帧时句柄恢复错乱
_cv2_lock = threading.Lock()


@contextlib.contextmanager
def _cv2_quiet():
    """屏蔽 OpenCV 底层 FFmpeg 写入 fd 2 的解码噪音。

    随机 seek 抽帧时 FFmpeg 从最近关键帧起解码，B 帧参考帧尚未解出，会刷出大量::

        [h264 @ 0000...] co located POCs unavailable
        [h264 @ 0000...] mmco: unref short failure

    这类噪音不影响抽帧结果（调用处已校验 ``ok`` 与输出文件大小），却会淹没真实日志。

    ``OPENCV_FFMPEG_LOGLEVEL`` 只在**进程启动前**由父进程注入才生效：实测运行时改
    ``os.environ``、``os.putenv``、乃至 kernel32 ``SetEnvironmentVariableW`` 写进程
    环境块**均无效**（OpenCV 在加载期已固定日志级别），因此改为在 fd 层临时重定向。
    本项目 logger 输出走 stdout / 文件句柄，不受影响。
    """
    with _cv2_lock:
        try:
            saved = os.dup(2)
        except OSError:  # 无 fd 2 的环境（如 pythonw）直接放行
            yield
            return
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, 2)
            yield
        finally:
            os.dup2(saved, 2)
            os.close(devnull)
            os.close(saved)

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


# 扩展名 -> 可接受的真实容器（一个容器常对应多个扩展名）
CONTAINERS_BY_EXT: dict[str, set[str]] = {
    ".mp4": {"mp4", "mov"},
    ".m4v": {"mp4", "mov"},
    ".mov": {"mov", "mp4"},
    ".mkv": {"mkv", "webm"},
    ".webm": {"webm", "mkv"},
    ".flv": {"flv"},
    ".avi": {"avi"},
    ".ts": {"mpegts"},
    ".wmv": {"asf"},
}


def detect_container(path: str | Path, *, sample: int = 4096) -> str:
    """按魔数嗅探**真实容器格式**，不信任扩展名。

    动机：把 ``.ts`` / ``.flv`` / ``.mkv`` 直接改名成 ``.mp4`` 的上游文件很常见
    （尤其来自流媒体下载/录制工具）。这类文件字节完整、FFmpeg 嗅探后也能正常解码
    （所以探测元信息、抽封面都不会报错），但**系统播放器与浏览器按扩展名解析时
    会直接判定「文件已损坏」**，极易被误判为上传或合并出了问题。

    :return: ``mp4`` / ``mov`` / ``mkv`` / ``webm`` / ``flv`` / ``avi`` / ``asf``
             / ``mpegts`` / ``unknown``
    """
    try:
        with Path(path).open("rb") as fp:
            head = fp.read(sample)
    except OSError:
        return "unknown"
    if len(head) < 377:
        return "unknown"

    if head[4:8] == b"ftyp":
        # major_brand 为 qt 时属 QuickTime 容器
        return "mov" if head[8:12] == b"qt  " else "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3":  # EBML
        return "webm" if b"webm" in head else "mkv"
    if head[:3] == b"FLV":
        return "flv"
    if head[8:12] == b"AVI ":
        return "avi"
    if head[:4] == b"\x30\x26\xb2\x75":  # ASF GUID 前缀
        return "asf"
    # MPEG-TS：0x47 为同步字节，每 188 字节出现一次
    if head[0] == 0x47 and head[188] == 0x47 and head[376] == 0x47:
        return "mpegts"
    return "unknown"


# 扩展名 -> 转封装时使用的 FFmpeg 输出格式名
FORMAT_BY_EXT: dict[str, str] = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mov",
    ".mkv": "matroska",
    ".webm": "webm",
    ".ts": "mpegts",
    ".flv": "flv",
    ".avi": "avi",
    ".wmv": "asf",
}


def container_of_ext(ext: str) -> str:
    """扩展名 -> 期望容器名（用于比对 ``detect_container`` 的结果）。

    ``.mp4`` 的合法容器有 ``mp4`` / ``mov`` 两个（见 ``CONTAINERS_BY_EXT``），
    但「期望值」应为最标准的那个，故用本表而非集合排序。
    """
    key = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
    return _PRIMARY_CONTAINER.get(key, "")


_PRIMARY_CONTAINER: dict[str, str] = {
    ".mp4": "mp4",
    ".m4v": "mp4",
    ".mov": "mov",
    ".mkv": "mkv",
    ".webm": "webm",
    ".ts": "mpegts",
    ".flv": "flv",
    ".avi": "avi",
    ".wmv": "asf",
}


# ===========================================================================
# 转封装（stream copy，不重编码）
# ===========================================================================
def remux_to_container(
    src: str | Path,
    ext: str,
    *,
    out_path: str | Path | None = None,
) -> tuple[bool, str]:
    """把视频**无损转封装**为目标扩展名对应的容器（仅改封装，不重编码）。

    为什么需要它：上游文件把 ``.ts`` / ``.mkv`` 改名成 ``.mp4`` 很常见，字节完整、
    FFmpeg 也能解码，但 Windows 播放器/浏览器按扩展名解析会直接报「文件已损坏」。
    合并阶段是**按字节原样拼接**、不负责转封装，所以这类文件必须在入库前处理掉，
    否则用户拿到的就是打不开的「坏文件」。

    :param ext: 目标扩展名（如 ``.mp4``），决定输出容器
    :param out_path: 输出路径；默认与源文件同目录、后缀为 ``.remux<ext>``
    :return: ``(是否成功, 说明)``；失败时输出文件会被清理，调用方应保留原文件
    """
    import av  # 惰性导入

    source = Path(src)
    suffix = ext.lower() if ext.startswith(".") else f".{ext.lower()}"
    fmt = FORMAT_BY_EXT.get(suffix)
    if not fmt:
        return False, f"不支持的目标容器: {suffix}"
    if not source.exists():
        return False, f"源文件不存在: {source}"

    dst = Path(out_path) if out_path else source.with_name(f"{source.stem}.remux{suffix}")

    # MP4/MOV 把 moov 前置：否则浏览器要等整个文件下载完才能开播（HTTP 渐进播放必需）
    options = {"movflags": "+faststart"} if fmt in ("mp4", "mov") else {}

    try:
        with av.open(str(source)) as inp, av.open(
            str(dst), "w", format=fmt, options=options
        ) as out:
            mapped: dict[int, Any] = {}
            for stream in inp.streams:
                if stream.type not in ("video", "audio"):
                    continue
                mapped[stream.index] = _add_mirror_stream(out, stream)
            if not mapped:
                raise RuntimeError("源文件不含可用的音视频流")

            for packet in inp.demux():
                if packet.dts is None:  # 刷尾的空包，mux 时丢弃
                    continue
                target_stream = mapped.get(packet.stream.index)
                if target_stream is None:
                    continue
                packet.stream = target_stream
                out.mux(packet)
    except Exception as exc:  # noqa: BLE001 - 转封装失败交由调用方降级处理
        with contextlib.suppress(OSError):
            dst.unlink()
        return False, f"{type(exc).__name__}: {exc}"[:200]

    expected = CONTAINERS_BY_EXT.get(suffix, set())
    actual = detect_container(dst)
    if expected and actual != "unknown" and actual not in expected:
        with contextlib.suppress(OSError):
            dst.unlink()
        return False, f"转封装结果容器仍不符（期望 {sorted(expected)}，实际 {actual}）"

    return True, actual


def _add_mirror_stream(out_container, src_stream):
    """按模板添加输出流（兼容 PyAV 新旧 API）。"""
    adder = getattr(out_container, "add_stream_from_template", None)
    if adder is not None:  # PyAV >= 18
        return adder(src_stream)
    return out_container.add_stream(template=src_stream)  # PyAV <= 17


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


def _av_video_rotation(container, stream) -> int:
    """读取视频流的显示旋转角（顺时针 0/90/180/270）。

    手机竖拍时通常按横屏编码，再在 ``tkhd`` 的 display matrix 里标记旋转角，
    播放器需据此把「编码尺寸」换算成「显示尺寸」。PyAV 不会自动应用该角度，
    且各版本暴露的位置不同，这里按「元信息 → 流属性 → 解一帧」依次尝试。
    """
    # 1) rotate 标签（旧版 ffmpeg 会写到流 / 容器 metadata）
    for holder in (getattr(stream, "metadata", None), getattr(container, "metadata", None)):
        if not holder:
            continue
        raw = holder.get("rotate")
        if raw is None:
            continue
        try:
            return int(float(raw)) % 360
        except (TypeError, ValueError):
            pass
    # 2) 部分版本直接挂在流对象上
    for attr in ("rotation", "rotate"):
        raw = getattr(stream, attr, None)
        if raw is None:
            continue
        try:
            return int(raw) % 360
        except (TypeError, ValueError):
            pass
    # 3) 兜底：解一帧读 frame.rotation（PyAV 18 只在这里暴露）
    try:
        for frame in container.decode(stream):
            raw = getattr(frame, "rotation", None)
            if raw is not None:
                return int(raw) % 360
            break
    except Exception:  # noqa: BLE001 - 读不到就按「不旋转」处理
        pass
    return 0


def _probe_av(path: Path) -> dict[str, Any]:
    import av  # 惰性导入

    with av.open(str(path)) as container:
        duration = float(container.duration / av.time_base) if container.duration else 0.0
        video_stream = container.streams.video[0] if container.streams.video else None
        width = height = 0
        fps = 0.0
        rotation = 0
        if video_stream is not None:
            ctx = video_stream.codec_context
            width = int(ctx.width or 0)
            height = int(ctx.height or 0)
            rate = video_stream.average_rate or video_stream.base_rate
            fps = float(rate) if rate else 0.0
            # 90 / 270 表示画面被旋转了奇数次直角 → 宽高互换才是真实显示尺寸
            rotation = _av_video_rotation(container, video_stream)
            if rotation % 180 == 90:
                width, height = height, width
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
            "rotation": rotation,
        }


def _probe_cv2(path: Path) -> dict[str, Any]:
    import cv2  # 惰性导入

    with _cv2_quiet():
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

    with _cv2_quiet():
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
            # cv2 默认开启 autorotate，取到的已是显示方向，直接缩放即可
            return _write_jpeg_cv2(_resize_cv2(frame), dst)
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


def _write_jpeg_cv2(array, dst: Path) -> bool:
    """把 BGR 数组写为 JPEG（与 ``_cover_cv2`` 使用同一套质量换算）。"""
    import cv2

    quality = int(get_settings().get("media.cover_quality", 3))
    return bool(
        cv2.imwrite(
            str(dst),
            array,
            [int(cv2.IMWRITE_JPEG_QUALITY), max(1, 100 - quality * 3)],
        )
    )


def _rotate_bgr(array, rotation: int):
    """按显示旋转角纠正 BGR 数组（``rotation`` 为顺时针角度）。"""
    import cv2

    deg = rotation % 360
    if deg == 0:
        return array
    if deg == 90:
        return cv2.rotate(array, cv2.ROTATE_90_CLOCKWISE)
    if deg == 180:
        return cv2.rotate(array, cv2.ROTATE_180)
    return cv2.rotate(array, cv2.ROTATE_90_COUNTERCLOCKWISE)


def _rotate_pil(image, rotation: int):
    """按显示旋转角纠正 PIL 图像（``rotation`` 为顺时针角度）。"""
    deg = rotation % 360
    if deg == 0:
        return image
    # PIL 的 rotate 以逆时针为正，故取负；expand 保证旋转后不被裁掉
    return image.rotate(-deg, expand=True)


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

        # PyAV 不会应用 tkhd 的旋转角，需自行纠正，否则横竖屏视频的封面会横躺
        rotation = _av_video_rotation(container, stream)

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

        if rotation % 360:
            # 需要旋转时统一走 cv2（PIL / MJPEG 两条路都不做几何变换）
            array = _resize_cv2(_rotate_bgr(frame.to_ndarray(format="bgr24"), rotation))
            return _write_jpeg_cv2(array, dst)

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
