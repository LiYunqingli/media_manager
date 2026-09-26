"""m3u8 链接下载导入服务（基于外部工具 N_m3u8DL-RE）。

与分片上传的关系
----------------
两条链路**共用同一段入库逻辑**（:func:`app.services.ingest_service.ingest_file`）：

::

    分片上传:  切分片 -> 传输 -> 拼接 -> ┐
                                        ├─> 容器校验/转封装 -> 探测 -> 封面 -> 写 video 表
    m3u8 下载: 链接 -> N_m3u8DL-RE ->  ┘
                      （下载 + 可选混流）

因此「下载导入」出来的视频在数据库里与上传的没有任何区别。

进度模型
--------
``download_task`` 持久化全部状态，前端轮询或刷新页面都不会丢：

=============  =========  ===============================================
阶段           区间        计算方式
=============  =========  ===============================================
queued         0          已入队，等待并发额度
downloading    0 - 80     分片进度（N_已下载/N_总数）
muxing         80 - 88    N_m3u8DL-RE / ffmpeg 混流
ingesting      88 - 90    容器校验、必要时转封装
probing        90 - 95    解析元信息
covering       95 - 100   生成封面
finished       100        完成
=============  =========  ===============================================

进度从哪来
----------
N_m3u8DL-RE 在 stdout **不是终端**时，会把进度条反复重写在**同一行**且不带任何
换行符（实测：整段进度输出首尾相连、连 ``\\r`` 都没有）。所以**不能按行读**，
只能用「累积缓冲区 + 在尾部反复正则取最后一次匹配」的方式解析——见 :func:`_pump`。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.config import PROJECT_ROOT, get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.repositories import category_repo, download_repo, upload_repo
from app.services import ingest_service
from app.utils import files as file_utils
from app.utils.presenter import present_download

logger = get_logger("download")

# 各阶段的整体进度区间
STAGE_RANGE: dict[str, tuple[float, float]] = {
    "queued": (0.0, 0.0),
    "downloading": (0.0, 80.0),
    "muxing": (80.0, 88.0),
    "ingesting": (88.0, 90.0),
    "probing": (90.0, 95.0),
    "covering": (95.0, 100.0),
    "finished": (100.0, 100.0),
    "failed": (0.0, 100.0),
    "cancelled": (0.0, 0.0),
}

# 入库阶段回调 -> 下载任务阶段
_INGEST_STAGE_MAP = {
    "remuxing": "ingesting",
    "probing": "probing",
    "covering": "covering",
}

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MediaManager/1.0"

# --- 输出解析用的正则（在缓冲区尾部取最后一次匹配） ------------------------- #
# N_m3u8DL-RE 会**每条轨道画一条进度条**（Vid / Aud / Sub ...），同一个窗口里
# 交替出现。所以不能简单地「取最后一个匹配」——那会读到落后的那条音轨。
# 正确做法是按轨道标签切分，各取最新值，再对多轨取最小值（全部轨道都下完才算完）。
# ⚠️ 标签前面**不能**加 ``\b``：进度段之间没有任何分隔符，上一条进度条的数字会紧贴
# 下一条的标签（``…100.00%Vid 1280x720…``），而 ``0`` 与 ``V`` 都是单词字符，
# ``\bVid`` 会直接匹配失败（实测踩过：整个下载阶段解析不出任何百分比）。
# 用「后面不是字母」来排除 Audio / Subtitle 这类干扰词即可。
_RE_BAR_START = re.compile(r"(Vid|Aud|Sub)(?![A-Za-z])")
_RE_PERCENT = re.compile(r"([\d.]+)%")
_RE_SEGMENT = re.compile(r"(\d+)\s*/\s*(\d+)\s+[\d.]+%")
_RE_SIZE_PAIR = re.compile(r"([\d.]+\s*[KMGT]?i?B)\s*/\s*([\d.]+\s*[KMGT]?i?B)", re.I)
_RE_SPEED = re.compile(r"(-?[\d.]+\s*[KMGT]?i?B)ps", re.I)
_RE_ETA = re.compile(r"(\d{2}:\d{2}:\d{2}|--:--:--)(?![\d.])")
_RE_SIZE = re.compile(r"([\d.]+)\s*([KMGT]?)(i?)B", re.I)
_RE_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")

_MEDIA_EXTS = {".mp4", ".mkv", ".mov", ".m4v", ".ts", ".webm", ".flv", ".avi", ".wmv",
               ".m4a", ".aac", ".mp3", ".opus", ".wav", ".m2ts"}
_IMAGE_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", ".jpg"),
    (b"\x89PNG\r\n\x1a\n", ".png"),
    (b"GIF87a", ".gif"),
    (b"GIF89a", ".gif"),
    (b"BM", ".bmp"),
)
_UNITS = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}

# 运行态登记表：task_id -> Popen（用于取消/看门狗）
_LOCK = threading.Lock()
_RUNNING: dict[str, subprocess.Popen] = {}
_CANCEL: set[str] = set()
_EXECUTOR = ThreadPoolExecutor(max_workers=8, thread_name_prefix="m3u8")
_SEMAPHORE: threading.Semaphore | None = None
_SEM_SIZE = 0


# ===========================================================================
# 工具探测
# ===========================================================================
def resolve_binary() -> Path | None:
    """N_m3u8DL-RE 可执行文件；未安装返回 None。"""
    settings = get_settings()
    raw = str(settings.get("download.binary", "") or "").strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path if path.exists() else None


def resolve_ffmpeg() -> Path | None:
    """ffmpeg 可执行文件。顺序：配置项 -> tools/ffmpeg/bin -> PATH。"""
    settings = get_settings()
    raw = str(settings.get("download.ffmpeg_binary", "") or "").strip()
    if raw:
        path = Path(raw)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        if path.exists():
            return path
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    bundled = PROJECT_ROOT / "tools" / "ffmpeg" / "bin" / exe
    if bundled.exists():
        return bundled
    which = shutil.which("ffmpeg")
    return Path(which) if which else None


def tool_status() -> dict[str, Any]:
    """工具链就绪情况（供前端提示与排障接口使用）。"""
    binary = resolve_binary()
    ffmpeg = resolve_ffmpeg()
    settings = get_settings()
    return {
        "enabled": bool(settings.get("download.enabled", True)),
        "binary": str(binary) if binary else "",
        "binary_ready": binary is not None,
        "ffmpeg": str(ffmpeg) if ffmpeg else "",
        "ffmpeg_ready": ffmpeg is not None,
        "binary_expected": str(settings.get("download.binary", "")),
        "hint": "" if binary else "请执行 python scripts/fetch_tools.py 下载 N_m3u8DL-RE",
        "api_token_enabled": bool(str(settings.get("download.api_token", "") or "").strip()),
        "default_category_id": int(settings.get("download.default_category_id", 0) or 0),
        "max_concurrent": _max_concurrent(),
        "active": _active_count(),
    }


def _max_concurrent() -> int:
    return max(1, int(get_settings().get("download.max_concurrent", 2) or 2))


def _semaphore() -> threading.Semaphore:
    """按配置的并发数创建信号量（配置进程内不变，创建一次即可）。"""
    global _SEMAPHORE, _SEM_SIZE
    size = _max_concurrent()
    with _LOCK:
        if _SEMAPHORE is None or _SEM_SIZE != size:
            _SEMAPHORE = threading.Semaphore(size)
            _SEM_SIZE = size
        return _SEMAPHORE


def _active_count() -> int:
    with _LOCK:
        return len(_RUNNING)


# ===========================================================================
# 路径
# ===========================================================================
def _stage_percent(stage: str, ratio: float) -> float:
    """把阶段内进度比例映射到整体百分比（与 upload_service 同一套算法）。"""
    low, high = STAGE_RANGE.get(stage, (0.0, 100.0))
    ratio = max(0.0, min(1.0, float(ratio or 0)))
    return round(low + (high - low) * ratio, 2)


def staging_dir(task_id: str) -> Path:
    """下载暂存目录：``storage/tmp/m3u8/<task_id>/``。"""
    return get_settings().storage_dir("tmp_dir") / "m3u8" / task_id


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(get_settings().storage_root.resolve()).as_posix()
    except ValueError:
        return ""


# ===========================================================================
# 创建任务
# ===========================================================================
def create_task(user: dict[str, Any], payload: dict[str, Any], *, source: str = "admin") -> dict[str, Any]:
    """建任务并入队。返回首个进度快照。

    :param payload: ``url`` / ``title`` / ``cover_url`` / ``category_id`` /
                    ``description`` / ``sort`` / ``headers`` / ``force``
    :raises BizError: 功能关闭、工具缺失、参数非法、分类不存在
    """
    settings = get_settings()
    if not bool(settings.get("download.enabled", True)):
        raise BizError(ErrorCode.DOWNLOAD_DISABLED)

    url = _normalize_url(payload.get("url"))
    header_map = _normalize_headers(payload.get("headers"))
    title = str(payload.get("title") or "").strip()[:255] or _title_from_url(url)
    cover_url = str(payload.get("cover_url") or "").strip()[:1024]
    if cover_url and not cover_url.lower().startswith(("http://", "https://")):
        raise BizError(ErrorCode.PARAM_ERROR, "封面地址必须是 http/https 链接")

    category_id = int(payload.get("category_id") or 0) or int(
        settings.get("download.default_category_id", 0) or 0
    )
    if category_id <= 0:
        raise BizError(ErrorCode.PARAM_ERROR, "请选择视频分类（或配置 download.default_category_id）")
    if not category_repo.find_by_id(category_id):
        raise BizError(ErrorCode.CATEGORY_NOT_FOUND)

    # 同一链接已成功下载过就直接复用，避免插件反复推送同一页面时重复下载
    if not payload.get("force"):
        existing = download_repo.find_by_url(url, finished_only=True)
        if existing:
            logger.info("命中下载判重: %s -> task %s", url, existing["task_id"])
            data = present_download(existing)
            data["deduped"] = True
            return data

    binary = resolve_binary()
    if binary is None:
        raise BizError(
            ErrorCode.DOWNLOAD_TOOL_MISSING,
            "未找到 N_m3u8DL-RE 可执行文件，请先执行 python scripts/fetch_tools.py",
        )

    task_id = uuid.uuid4().hex
    download_repo.create(
        task_id=task_id,
        user_id=int(user["id"]),
        url=url,
        title=title,
        cover_url=cover_url,
        category_id=category_id,
        description=str(payload.get("description") or ""),
        sort=int(payload.get("sort") or 0),
        headers=json.dumps(header_map, ensure_ascii=False) if header_map else "",
        source=source[:24],
    )
    _EXECUTOR.submit(_run_task, task_id)

    row = download_repo.get(task_id) or {}
    data = present_download(row)
    data["deduped"] = False
    logger.info("新建下载任务 %s: %s (%s)", task_id, title, url)
    return data


def _normalize_url(raw: Any) -> str:
    url = str(raw or "").strip()
    if not url:
        raise BizError(ErrorCode.PARAM_ERROR, "m3u8 链接不能为空")
    if len(url) > 2000:
        raise BizError(ErrorCode.PARAM_ERROR, "链接过长")
    low = url.lower()
    if not low.startswith(("http://", "https://")):
        # 明确拒绝 file:// 之类会把服务器变成任意文件读取器的协议
        raise BizError(ErrorCode.PARAM_ERROR, "仅支持 http/https 链接")
    return url


def _normalize_headers(raw: Any) -> dict[str, str]:
    """请求头归一化：接受 dict 或 ``"Key: Value\\nKey2: Value"`` 文本。"""
    if not raw:
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw = parsed
        else:
            result: dict[str, str] = {}
            for line in text.splitlines():
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key, value = key.strip(), value.strip()
                if key:
                    result[key] = value
            return result
    if not isinstance(raw, dict):
        return {}
    result = {}
    for key, value in raw.items():
        key = str(key).strip()
        if not key or value is None:
            continue
        # 换行会破坏 -H 参数，直接压平
        result[key[:64]] = str(value).replace("\r", " ").replace("\n", " ").strip()[:1024]
    return result


def _title_from_url(url: str) -> str:
    """链接里没有标题时兜底取末段文件名。"""
    path = urllib.parse.urlparse(url).path
    stem = Path(path).stem if path else ""
    return (stem or f"m3u8_{time.strftime('%Y%m%d%H%M%S')}")[:255]


# ===========================================================================
# 执行
# ===========================================================================
def _build_command(binary: Path, task: dict[str, Any], staging: Path, save_name: str) -> list[str]:
    settings = get_settings()
    cmd: list[str] = [
        str(binary),
        task["url"],
        "--save-dir", str(staging),
        "--save-name", save_name,
        "--tmp-dir", str(_tmp_dir(staging)),
        "--thread-count", str(int(settings.get("download.threads", 8) or 8)),
        "--download-retry-count", str(int(settings.get("download.download_retry", 3) or 3)),
        "--ui-language", "en-US",
        "--log-file-path", str(staging / "re.log"),
        "--disable-update-check",
        # 输出被重定向时进度条会挤在同一行，但至少让我们能拿到实时百分比
        "--force-ansi-console",
        "--no-ansi-color",
    ]
    if bool(settings.get("download.auto_select", True)):
        cmd.append("--auto-select")

    ffmpeg = resolve_ffmpeg()
    if ffmpeg:
        cmd += ["--ffmpeg-binary-path", str(ffmpeg)]

    mux = str(settings.get("download.mux_format", "mp4") or "").strip()
    if mux and ffmpeg:
        # 分离音视频轨（HLS 最常见形态）必须靠 ffmpeg 混流；没装 ffmpeg 时降级为
        # 不混流：此时多半只能拿到视频轨，入库的容器校验会给出明确提示。
        cmd += ["-M", f"format={mux}"]
    elif mux and not ffmpeg:
        logger.warning("未检测到 ffmpeg，本次不做混流（分离音视频流会失败）")

    headers = _parse_headers(task.get("headers"))
    for key, value in headers.items():
        cmd += ["-H", f"{key}: {value}"]

    for extra in settings.get("download.extra_args", []) or []:
        if isinstance(extra, str) and extra:
            cmd.append(extra)
    return cmd


def _tmp_dir(staging: Path) -> Path:
    """N_m3u8DL-RE 的分片临时目录（下载完成后它自己会清理）。"""
    return staging / "_tmp"


def _parse_headers(raw: Any) -> dict[str, str]:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _run_task(task_id: str) -> None:
    """后台任务主体：占并发额度 -> 下载 -> 找产物 -> 入库。"""
    sem = _semaphore()
    sem.acquire()
    started = time.time()
    staging = staging_dir(task_id)
    try:
        task = download_repo.get(task_id)
        if not task:
            return
        if _is_cancelled(task_id):
            download_repo.update(task_id, {"stage": "cancelled", "message": "已取消"})
            return

        settings = get_settings()
        binary = resolve_binary()
        if binary is None:
            raise BizError(ErrorCode.DOWNLOAD_TOOL_MISSING, "N_m3u8DL-RE 不可用")

        file_utils.ensure_dir(staging)
        save_name = "download"
        download_repo.update(
            task_id,
            {
                "staging_dir": _rel(staging),
                "message": "正在下载分片",
            },
        )
        download_repo.mark_started(task_id)

        cmd = _build_command(binary, task, staging, save_name)
        logger.info("m3u8 下载启动 %s: %s", task_id, task["url"])
        logger.debug("命令: %s", " ".join(cmd))

        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
            "bufsize": 0,
            "cwd": str(PROJECT_ROOT),
        }
        if os.name == "nt":
            # 不加这个标志会弹出一个黑色控制台窗口（服务端跑在后台时很碍事）
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        else:
            # 独立进程组：取消任务时能一次性干掉 RE 及其拉起的 ffmpeg
            popen_kwargs["start_new_session"] = True

        proc = subprocess.Popen(cmd, **popen_kwargs)  # noqa: S603
        with _LOCK:
            _RUNNING[task_id] = proc
        _pump(task_id, proc, staging, started, settings)
        returncode = proc.wait()

        if _is_cancelled(task_id):
            download_repo.update(
                task_id, {"stage": "cancelled", "message": "已取消", "speed": 0, "eta": 0}
            )
            logger.info("下载任务已取消 %s", task_id)
            return

        if returncode != 0:
            raise BizError(
                ErrorCode.DOWNLOAD_FAILED,
                f"N_m3u8DL-RE 退出码 {returncode}：{_failure_hint(staging) or _tail(staging)}"[:480],
            )

        media = _pick_output(staging, save_name)
        if media is None:
            raise BizError(
                ErrorCode.DOWNLOAD_FAILED,
                f"未找到下载产物：{_tail(staging) or '目录内没有媒体文件'}",
            )
        if _is_cancelled(task_id):
            download_repo.update(task_id, {"stage": "cancelled", "message": "已取消"})
            return

        _finalize(task_id, task, media, staging, started, settings)

    except BizError as exc:
        logger.error("下载任务失败 %s: %s", task_id, exc.message)
        download_repo.update(
            task_id,
            {"stage": "failed", "error": exc.message, "message": "任务失败",
             "speed": 0, "eta": 0, "elapsed": round(time.time() - started, 2)},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("下载任务异常 %s: %s", task_id, exc)
        download_repo.update(
            task_id,
            {"stage": "failed", "error": f"{type(exc).__name__}: {exc}"[:480],
             "message": "任务异常", "speed": 0, "eta": 0,
             "elapsed": round(time.time() - started, 2)},
        )
    finally:
        with _LOCK:
            _RUNNING.pop(task_id, None)
            _CANCEL.discard(task_id)
            sem_to_release = _SEMAPHORE
        # 先归还并发额度再清理目录：清理失败（磁盘占用、权限、杀软锁文件）绝不能
        # 把下载流水线堵死，否则后续任务会永远排队。
        if sem_to_release is not None:
            sem_to_release.release()
        _safe_remove_dir(staging)


def _safe_remove_dir(path: Path) -> None:
    """删除目录，任何失败都只记日志。

    暂存目录里是下载中间产物，留着不影响正确性；而清理动作处在 finally / 请求
    处理路径上，一旦向上抛就会污染任务结果或直接 500。
    """
    try:
        file_utils.remove_dir(path)
    except BaseException as exc:  # noqa: BLE001 - 清理失败绝不冒泡
        logger.warning("清理暂存目录失败 %s: %s", path, exc)


def _finalize(
    task_id: str,
    task: dict[str, Any],
    media: Path,
    staging: Path,
    started: float,
    settings: Any,
) -> None:
    """把下载产物搬进 storage/videos 并走 ingest 入库。"""
    video_root = settings.storage_dir("video_dir")
    sub = file_utils.dated_subdir(by_day=False)
    title = str(task.get("title") or media.stem)

    # 原始文件名要带**下载产物的真实扩展名**，不能用链接的扩展名：链接必然是
    # ``xxx.m3u8``，直接拿来当文件名会让落盘文件叫 ``xxx.m3u8``，MIME 推断、
    # 播放器识别、容器校验全部错位（实测过）。所以只借链接的「名字」，换它的「后缀」。
    name_from_url = Path(urllib.parse.urlparse(str(task.get("url") or "")).path).name
    stem = Path(file_utils.safe_filename(name_from_url)).stem if name_from_url else ""
    original_name = f"{stem or file_utils.safe_filename(title)}{media.suffix.lower()}"

    stored = file_utils.generate_stored_name(original_name)
    target_dir = video_root / sub
    file_utils.ensure_dir(target_dir)
    dest = target_dir / stored

    shutil.move(str(media), str(dest))
    logger.info("m3u8 下载完成 %s -> %s (%s)", task_id, dest.name, file_utils.human_size(file_utils.file_size(dest)))

    # 内容摘要要在**入库前**算：容器不符时会被就地转封装，落盘体积随之改变
    # （与 import_videos.py 同一套判重思路）。
    file_hash = ""
    if bool(settings.get("download.record_hash", True)):
        try:
            file_hash = file_utils.hash_file(dest)
        except OSError as exc:
            logger.warning("计算下载文件摘要失败: %s", exc)

    # 封面：优先用接口给的远程封面（cover_source=1 = 手动封面）
    cover_rel = ""
    cover_url = str(task.get("cover_url") or "").strip()
    if cover_url:
        download_repo.update(task_id, {"message": "正在下载封面"})
        cover_rel = _fetch_cover(cover_url, int(settings.get("download.cover_max_bytes", 0) or 0))
        if not cover_rel:
            logger.warning("远程封面下载失败，改用自动抽帧: %s", cover_url)

    def _on_stage(stage: str, ratio: float, message: str) -> None:
        mapped = _INGEST_STAGE_MAP.get(stage, "ingesting")
        fields: dict[str, Any] = {"stage": mapped, "percent": _stage_percent(mapped, ratio)}
        if message:
            fields["message"] = message
        download_repo.update(task_id, fields)

    outcome = ingest_service.ingest_file(
        dest,
        category_id=int(task.get("category_id") or 0),
        title=title,
        original_name=original_name,
        description=str(task.get("description") or ""),
        sort=int(task.get("sort") or 0),
        manual_cover=cover_rel,
        on_stage=_on_stage,
    )

    message = f"完成，耗时 {time.time() - started:.1f}s"
    if outcome.notes:
        message += "｜注意：" + "；".join(outcome.notes)
    if cover_rel:
        message += "｜已使用远程封面"

    download_repo.update(
        task_id,
        {
            "file_path": _rel(dest),
            "cover": cover_rel or outcome.cover,
            "elapsed": round(time.time() - started, 2),
            "speed": 0,
            "eta": 0,
            "message": message,
        },
    )
    download_repo.mark_finished(task_id, video_id=outcome.video_id)

    # 写一条 finished 的上传台账：网页端再上传同一文件可命中秒传（与 CLI 导入一致）
    if file_hash:
        _record_session(task, outcome, original_name, file_hash)

    logger.info("m3u8 任务入库完成 %s -> video#%d (%s)", task_id, outcome.video_id, title)


def _record_session(
    task: dict[str, Any],
    result: ingest_service.IngestResult,
    original_name: str,
    file_hash: str,
) -> None:
    settings = get_settings()
    try:
        upload_id = uuid.uuid4().hex
        upload_repo.create_session(
            upload_id=upload_id,
            user_id=int(task.get("user_id") or 0),
            file_name=original_name,
            total_size=result.size,
            chunk_size=settings.chunk_size,
            total_chunks=1,
            file_hash=file_hash,
            category_id=int(task.get("category_id") or 0),
            title=str(task.get("title") or ""),
        )
        upload_repo.update(
            upload_id,
            {
                "stage": "finished",
                "percent": 100,
                "video_id": result.video_id,
                "merged_bytes": result.size,
                "message": "由 m3u8 链接下载导入",
            },
        )
    except Exception as exc:  # noqa: BLE001 - 台账失败不影响入库结果
        logger.warning("写入下载台账失败: %s", exc)


# ===========================================================================
# 输出解析
# ===========================================================================
class _BarSnapshot:
    """一次解析的结果（多轨进度条的汇总）。"""

    __slots__ = ("percent", "done_bytes", "total_bytes", "speed", "eta", "segments")

    def __init__(self) -> None:
        self.percent: float | None = None
        self.done_bytes = 0
        self.total_bytes = 0
        self.speed = 0
        self.eta = 0
        self.segments = ""


def _parse_bars(window: str) -> _BarSnapshot:
    """从输出尾部窗口解析出多轨进度汇总。

    窗口里每条轨道的最新一次渲染形如::

        Vid 1280x720 | 5150 Kbps ------------------------ 3/6 50.00% 726.33KB/2.13MB 422.33KBps 00:00:01
        Aud audio                ------------------------ 7/7 100.00% 414.19KB - 00:00:00

    按 ``Vid`` / ``Aud`` / ``Sub`` 标签切块，每块取**最后一个**百分比（该轨道最新状态），
    再对全部轨道取 ``max``。

    为什么是 max 而不是 min：多轨是**串行**下载的（实测：视频 46 片下完才轮到音频），
    没轮到的那条会长时间停在 ``0/100 0.00%`` 的占位状态。取 min 会让进度条从头到尾
    钉在 0%，取 max 则始终跟随当前在下的那条轨道，且因为每条轨道的百分比只增不减，
    ``max`` 天然单调不回退。下载阶段封顶 80%（:data:`STAGE_RANGE`），所以「视频先下完、
    音频还在下」时也只是停在 80% 等着进入混流阶段。
    """
    snap = _BarSnapshot()
    marks = list(_RE_BAR_START.finditer(window))
    chunks: dict[str, str] = {}
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(window)
        chunk = window[mark.start():end]
        if _last(_RE_PERCENT, chunk) is None:
            # 形如 "INFO : Vid 1280x720 | ... | 6 Segments" 的日志行，不是进度渲染
            continue
        chunks[mark.group(1)] = chunk  # 同名轨道以最后一次渲染为准

    percents: list[float] = []
    speeds: list[int] = []
    etas: list[int] = []
    for chunk in chunks.values():
        pct = _last(_RE_PERCENT, chunk)
        if pct:
            percents.append(min(100.0, float(pct.group(1))))
        pair = _last(_RE_SIZE_PAIR, chunk)
        if pair:
            snap.done_bytes += _parse_size(pair.group(1))
            snap.total_bytes += _parse_size(pair.group(2))
        spd = _last(_RE_SPEED, chunk)
        if spd:
            speeds.append(max(0, _parse_size(spd.group(1).replace("-", ""))))
        eta_match = _last(_RE_ETA, chunk)
        if eta_match and eta_match.group(1) != "--:--:--":
            etas.append(_hms_to_seconds(eta_match.group(1)))

    if percents:
        snap.percent = max(percents)
    # 片数进度取自「进度最靠前的那条轨道」，展示上更直观
    if snap.percent is not None:
        for chunk in chunks.values():
            pct = _last(_RE_PERCENT, chunk)
            if pct and float(pct.group(1)) >= snap.percent:
                seg = _last(_RE_SEGMENT, chunk)
                if seg:
                    snap.segments = f"{seg.group(1)}/{seg.group(2)}"
                break
    snap.speed = max(speeds) if speeds else 0
    snap.eta = max(etas) if etas else 0
    return snap


def _pump(task_id: str, proc: subprocess.Popen, staging: Path, started: float, settings: Any) -> None:
    """持续读取子进程输出并更新进度（详见模块 docstring 的「进度从哪来」）。"""
    if proc.stdout is None:  # pragma: no cover - Popen 已保证有 stdout
        return
    timeout = float(settings.get("download.timeout_seconds", 7200) or 0)
    buf = ""
    phase = "downloading"
    last_db = 0.0
    last_data = time.time()
    snap = _BarSnapshot()
    percent = 0.0
    segments = ""

    while True:
        try:
            chunk = proc.stdout.read(4096)
        except (OSError, ValueError):
            break
        if not chunk:
            break
        if isinstance(chunk, str):  # 保险：万一被包成文本流
            chunk = chunk.encode("utf-8", "replace")
        text = _RE_ANSI.sub("", chunk.decode("utf-8", "replace"))
        buf = (buf + text)[-65536:]
        window = buf[-8192:]
        now = time.time()
        last_data = now

        parsed = _parse_bars(window)
        if parsed.percent is not None:
            percent = parsed.percent
        if parsed.done_bytes or parsed.total_bytes:
            snap.done_bytes = parsed.done_bytes
            snap.total_bytes = parsed.total_bytes
        if parsed.speed:
            snap.speed = parsed.speed
        if parsed.eta:
            snap.eta = parsed.eta
        if parsed.segments:
            segments = parsed.segments

        if "Binary merging" in window or "Muxing to" in window or "Rename to" in window:
            phase = "muxing"

        if now - last_db >= 0.4:
            last_db = now
            download_repo.update(
                task_id,
                {
                    "stage": phase,
                    "percent": _stage_percent(phase, percent / 100.0),
                    "done_bytes": snap.done_bytes,
                    "total_bytes": snap.total_bytes,
                    "speed": snap.speed if phase == "downloading" else 0,
                    "eta": snap.eta if phase == "downloading" else 0,
                    "message": _progress_message(phase, segments, snap.done_bytes),
                },
            )

        # 看门狗①：长时间没有任何输出，用暂存目录体积证明「还活着」
        if now - last_data > 30 and now - last_db > 15:
            last_db = now
            grown = _dir_size(_tmp_dir(staging)) or _dir_size(staging)
            download_repo.update(
                task_id,
                {
                    "stage": phase,
                    "done_bytes": grown or snap.done_bytes,
                    "message": f"已落盘 {file_utils.human_size(grown or snap.done_bytes)}…",
                },
            )

        # 看门狗②：总运行时长超限，强制结束（防止对流媒体/挂死连接无限等待）
        if timeout and now - started > timeout:
            logger.error("下载任务超时 %s（>%.0fs）", task_id, timeout)
            download_repo.update(
                task_id,
                {"message": f"超过最长运行时间 {int(timeout)}s，已强制结束"},
            )
            _request_cancel(task_id)
            break

    # 收尾：把最后一次已知进度写一份，避免最后 0.4s 内的变化丢了
    download_repo.update(
        task_id,
        {
            "stage": phase,
            "percent": _stage_percent(phase, percent / 100.0),
            "done_bytes": snap.done_bytes or _dir_size(staging),
            "total_bytes": snap.total_bytes,
            "speed": 0,
            "eta": 0,
            "log_tail": _safe_tail(buf),
        },
    )


def _last(pattern: re.Pattern[str], text: str) -> re.Match[str] | None:
    found = None
    for found in pattern.finditer(text):
        pass
    return found


def _parse_size(text: str) -> int:
    match = _RE_SIZE.match(text.strip())
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).upper()
    return int(value * _UNITS.get(unit, 1))


def _hms_to_seconds(text: str) -> int:
    try:
        hours, minutes, seconds = (int(part) for part in text.split(":"))
    except ValueError:
        return 0
    return hours * 3600 + minutes * 60 + seconds


def _progress_message(phase: str, segments: str, done: int) -> str:
    if phase == "muxing":
        return "正在混流封装"
    if segments:
        return f"下载中 {segments} 片"
    if done:
        return f"已下载 {file_utils.human_size(done)}"
    return "正在下载分片"


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _tail(staging: Path, *, limit: int = 400) -> str:
    """失败原因：优先取 RE 自己的日志文件末尾。"""
    log = staging / "re.log"
    if not log.exists():
        return ""
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return " / ".join(lines[-3:])[:limit]


def _failure_hint(staging: Path) -> str:
    text = _tail(staging, limit=800)
    if not text:
        return ""
    low = text.lower()
    if "403" in low or "forbidden" in low:
        return "服务器返回 403（可能需要 Cookie/Referer 请求头）"
    if "404" in low:
        return "地址返回 404（链接可能已失效）"
    if "connection" in low or "timeout" in low:
        return "网络连接失败或超时"
    if "ffmpeg" in low:
        return "ffmpeg 调用失败（检查 tools/ffmpeg 是否完整）"
    return text


def _safe_tail(buf: str, *, limit: int = 2000) -> str:
    """截取缓冲区尾部，去掉控制字符，避免日志/数据库出现乱码。"""
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else " " for ch in buf)
    cleaned = _RE_ANSI.sub("", cleaned)
    return cleaned[-limit:]


def _pick_output(staging: Path, save_name: str) -> Path | None:
    """挑出真正的媒体产物。

    目录里还会有 ``_tmp``（分片）、``download.json``（meta）、``re.log``，
    一律按「扩展名属于媒体 + 体积最大」筛掉。
    """
    best: Path | None = None
    best_size = -1
    for item in staging.iterdir():
        if not item.is_file():
            continue
        if item.suffix.lower() not in _MEDIA_EXTS:
            continue
        size = file_utils.file_size(item)
        if size > best_size:
            best, best_size = item, size
    if best is None:
        # 兜底：不带扩展名的产物也认（极少数站点）
        for item in staging.iterdir():
            if item.is_file() and item.name.startswith(save_name + ".") and item.suffix.lower() not in {
                ".json", ".log", ".txt"
            }:
                if file_utils.file_size(item) > best_size:
                    best, best_size = item, file_utils.file_size(item)
    return best


# ===========================================================================
# 封面
# ===========================================================================
def _fetch_cover(url: str, max_bytes: int) -> str:
    """下载远程封面并落盘，返回相对 storage 的路径；失败返回空串。"""
    settings = get_settings()
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            data = resp.read((max_bytes or 40 * 1024 * 1024) + 1)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        logger.warning("封面下载失败 %s: %s", url, exc)
        return ""

    if max_bytes and len(data) > max_bytes:
        logger.warning("封面超过体积上限，已忽略: %s", url)
        return ""
    if len(data) < 64:
        logger.warning("封面内容过小，已忽略: %s", url)
        return ""

    # 用魔数判断真实格式，而不是相信 URL 后缀（封面地址经常没有扩展名）
    ext = ""
    for magic, guess in _IMAGE_MAGIC:
        if data.startswith(magic):
            ext = guess
            break
    if not ext and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        ext = ".webp"
    if not ext:
        logger.warning("封面不是可识别的图片格式，已忽略: %s", url)
        return ""

    cover_dir = settings.storage_dir("cover_dir")
    target = cover_dir / file_utils.dated_subdir(by_day=False) / file_utils.generate_stored_name(
        f"cover{ext}", prefix="dl_"
    )
    file_utils.ensure_dir(target.parent)
    target.write_bytes(data)
    logger.info("远程封面已保存 %s (%s)", target.name, file_utils.human_size(len(data)))
    return _rel(target)


# ===========================================================================
# 取消 / 重试 / 删除
# ===========================================================================
def _is_cancelled(task_id: str) -> bool:
    with _LOCK:
        return task_id in _CANCEL


def _request_cancel(task_id: str) -> bool:
    """标记取消并结束进程（含子进程树）。"""
    with _LOCK:
        _CANCEL.add(task_id)
        proc = _RUNNING.get(task_id)
    if proc is None:
        return False
    _kill_tree(proc)
    return True


def _kill_tree(proc: subprocess.Popen) -> None:
    """结束进程树。N_m3u8DL-RE 会拉起 ffmpeg，只杀父进程会留下孤儿。"""
    if proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(  # noqa: S603,S607
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=15,
            )
        else:
            os.killpg(os.getpgid(proc.pid), 15)  # noqa: S603
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001 - 兜底强杀
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def cancel_task(user: dict[str, Any], task_id: str) -> dict[str, Any]:
    """取消任务：运行中则结束进程，排队中直接出队。"""
    task = get_task(user, task_id)
    if task["stage"] in ("finished", "failed", "cancelled"):
        return present_download(task)
    killed = _request_cancel(task_id)
    download_repo.update(
        task_id,
        {
            "stage": "cancelled",
            "message": "已取消" if killed else "已取消（未开始）",
            "speed": 0,
            "eta": 0,
        },
    )
    logger.info("取消下载任务 %s", task_id)
    row = download_repo.get(task_id) or {}
    return present_download(row)


def retry_task(user: dict[str, Any], task_id: str) -> dict[str, Any]:
    """重试：清理暂存目录后按原参数重新排队。"""
    task = get_task(user, task_id)
    if task["stage"] not in ("failed", "cancelled", "finished"):
        raise BizError(ErrorCode.DOWNLOAD_BUSY, "任务正在运行，无法重试")
    if resolve_binary() is None:
        raise BizError(
            ErrorCode.DOWNLOAD_TOOL_MISSING,
            "未找到 N_m3u8DL-RE 可执行文件，请先执行 python scripts/fetch_tools.py",
        )
    _safe_remove_dir(staging_dir(task_id))
    with _LOCK:
        _CANCEL.discard(task_id)
    download_repo.reset_for_retry(task_id)
    _EXECUTOR.submit(_run_task, task_id)
    row = download_repo.get(task_id) or {}
    logger.info("重试下载任务 %s", task_id)
    return present_download(row)


def delete_task(user: dict[str, Any], task_id: str) -> None:
    """删除记录（视频本身不动）。运行中的任务必须先取消。"""
    task = get_task(user, task_id)
    if task["stage"] in download_repo.ACTIVE_STAGES:
        raise BizError(ErrorCode.DOWNLOAD_BUSY, "任务正在运行，请先取消")
    _safe_remove_dir(staging_dir(task_id))
    download_repo.delete(task_id)


# ===========================================================================
# 查询
# ===========================================================================
def get_task(user: dict[str, Any], task_id: str) -> dict[str, Any]:
    row = download_repo.get(task_id)
    if not row:
        raise BizError(ErrorCode.DOWNLOAD_NOT_FOUND)
    if int(row["user_id"]) != int(user["id"]) and user.get("role") != "admin":
        raise BizError(ErrorCode.FORBIDDEN, "无权查看他人的下载任务")
    return row


def get_progress(user: dict[str, Any], task_id: str) -> dict[str, Any]:
    return present_download(get_task(user, task_id))


def list_tasks(
    user: dict[str, Any],
    *,
    limit: int = 30,
    offset: int = 0,
    stage: str | None = None,
    mine: bool = True,
) -> dict[str, Any]:
    """任务列表。管理员默认只看自己的，``mine=False`` 看全部。"""
    user_id = int(user["id"]) if (user.get("role") != "admin" or mine) else None
    rows = download_repo.list_tasks(user_id=user_id, stage=stage, limit=limit, offset=offset)
    return {
        "items": [present_download(r) for r in rows],
        "total": download_repo.count_tasks(user_id=user_id, stage=stage),
        "stats": download_repo.stats(),
    }


def mark_interrupted() -> int:
    """启动时把上次进程留下的「运行中」任务判为中断。

    否则它们会永远停在 downloading，前端会一直以为还在跑。
    """
    rows = download_repo.list_active()
    for row in rows:
        download_repo.mark_interrupted(row["task_id"])
    if rows:
        logger.warning("已把 %d 个上次未完成的 m3u8 下载任务标记为中断", len(rows))
    return len(rows)


def cleanup_expired(days: int = 7) -> int:
    """清理超过 N 天的失败/取消任务（连带暂存目录）。"""
    from app.db import session as db

    rows = db.query_all(
        """
        SELECT task_id FROM download_task
        WHERE stage IN ('failed', 'cancelled') AND updated_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        """,
        (int(days),),
    )
    for row in rows:
        _safe_remove_dir(staging_dir(row["task_id"]))
        download_repo.delete(row["task_id"])
    return len(rows)
