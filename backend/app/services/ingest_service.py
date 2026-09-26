"""本地视频文件入库服务（分片上传 + 服务端批量导入 共用）。

职责单一：把「**已经在磁盘上的完整视频文件**」登记进系统。

::

    ① 容器校验   -> 真实容器与扩展名不符时无损转封装（stream copy，秒级）
    ② 元信息探测 -> 时长 / 分辨率 / 码率
    ③ 生成封面   -> 手动封面优先，否则抽关键帧
    ④ 写入 video 表

之所以单独成模块，是因为有**两条入口**需要同一段逻辑：

- 分片上传：``upload_service._merge_worker`` 把分片拼成一个完整文件之后；
- 服务端导入：``scripts/import_videos.py`` 把指定目录下的文件搬进 storage 之后。

两条链路若各写一份，改探测/封面参数时必然漂移（历史上「TS 转封装」就只加在了上传侧）。
因此这里统一实现，上传侧通过 ``on_stage`` 回调继续更新 ``upload_session`` 进度。

本模块**不碰分片、不碰 upload_session**，只负责「文件已就位之后」的事情。
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.repositories import video_repo
from app.services import media_service
from app.utils import files as file_utils

logger = get_logger("ingest")

# 阶段回调：``(stage, ratio, message)``
#   stage   -> remuxing / probing / covering
#   ratio   -> 该阶段内的完成比例 0~1（调用方自行映射到整体百分比）
#   message -> 给前端展示的文案，空串表示「只更新进度、不改文案」
StageHook = Callable[[str, float, str], None]


@dataclass
class IngestResult:
    """入库结果。"""

    video_id: int
    path: str                    # 相对 storage 根目录的路径（入库值）
    abs_path: Path               # 绝对路径
    size: int                    # 最终落盘字节数（转封装后会变）
    cover: str = ""              # 相对 storage 根目录的封面路径
    duration: float = 0.0
    width: int = 0
    height: int = 0
    bitrate: int = 0
    remuxed: bool = False        # 是否发生过容器转封装
    notes: list[str] = field(default_factory=list)  # 需要回显给使用者的提示


def _rel(path: Path, root: Path) -> str:
    """转成相对 storage 根目录的 POSIX 风格路径（入库用）。"""
    return path.resolve().relative_to(root.resolve()).as_posix()


def _notify(hook: StageHook | None, stage: str, ratio: float, message: str = "") -> None:
    if hook is None:
        return
    try:
        hook(stage, ratio, message)
    except Exception as exc:  # noqa: BLE001 - 进度上报失败不该中断入库
        logger.warning("进度回调失败 %s: %s", stage, exc)


# ===========================================================================
# 容器转封装
# ===========================================================================
def remux_in_place(path: Path, ext: str) -> bool:
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


# ===========================================================================
# 入库主流程
# ===========================================================================
def ingest_file(
    dest: str | Path,
    *,
    category_id: int,
    title: str,
    original_name: str,
    description: str = "",
    sort: int = 0,
    manual_cover: str = "",
    on_stage: StageHook | None = None,
) -> IngestResult:
    """把一个**已落在 storage 内**的完整视频文件登记入库。

    :param dest: 文件的最终位置（必须在 ``storage.root`` 之内）
    :param original_name: 原始文件名（入库到 ``original_name``，并据此推断 MIME）
    :param manual_cover: 手动封面（相对 storage 根的路径），空则自动抽帧
    :param on_stage: 阶段回调，见 :data:`StageHook`
    :raises BizError: 文件不存在 / 不在 storage 内 / 分类缺失
    """
    settings = get_settings()
    path = Path(dest)
    if not path.exists():
        raise BizError(ErrorCode.FILE_NOT_FOUND, f"文件不存在: {path}")
    if not file_utils.is_relative_to(path, settings.storage_root):
        raise BizError(
            ErrorCode.PARAM_ERROR,
            f"文件必须位于 storage 根目录内（{settings.storage_root}）: {path}",
        )

    suffix = path.suffix.lower()
    actual_size = file_utils.file_size(path)
    notes: list[str] = []

    # ---------------- ① 容器校验 / 自动转封装 ----------------
    # 扩展名不可信：把 .ts / .flv / .mkv 改名成 .mp4 的上游文件很常见。这类文件
    # 字节完整、FFmpeg 也能解码，但系统播放器按扩展名解析会报「文件已损坏」，
    # 容易被误判成上传/合并出错。检测到不匹配就**自动转封装**（stream copy，
    # 无损、秒级），失败才退回提示文案。
    remuxed = False
    actual_container = media_service.detect_container(path)
    allowed = media_service.CONTAINERS_BY_EXT.get(suffix)
    if actual_container != "unknown" and allowed and actual_container not in allowed:
        logger.warning(
            "容器与扩展名不符 %s: 实际=%s 扩展名=%s", path.name, actual_container, suffix
        )
        if bool(settings.get("media.auto_remux", True)):
            _notify(
                on_stage, "remuxing", 1.0,
                f"检测到 {actual_container.upper()} 容器，正在转封装为 {suffix.upper()}…",
            )
            remuxed = remux_in_place(path, suffix)

        if remuxed:
            actual_size = file_utils.file_size(path)
            notes.append(f"原文件实为 {actual_container.upper()} 容器，已自动转封装为 {suffix.upper()}")
            logger.info(
                "已自动转封装 %s: %s -> %s (%s)",
                path.name, actual_container, suffix, file_utils.human_size(actual_size),
            )
        else:
            note = (
                f"文件实际是 {actual_container.upper()} 容器，与扩展名 {suffix} 不符，"
                "系统播放器可能提示文件损坏（建议用 VLC/PotPlayer 打开，或转封装为 MP4）"
            )
            notes.append(note)

    # ---------------- ② 探测元信息 ----------------
    _notify(on_stage, "probing", 0.3, "解析视频信息")
    info = media_service.probe(path)
    _notify(on_stage, "probing", 1.0)
    if float(info.get("duration") or 0) <= 0:
        # probe() 失败时返回全 0 结构，不阻塞入库，但要让使用者知道
        notes.append("元信息探测失败（时长/分辨率记为 0），可在管理端对视频执行「重新探测」")
        logger.warning("元信息探测失败: %s", path.name)

    # ---------------- ③ 生成封面 ----------------
    _notify(on_stage, "covering", 0.2, "生成视频封面")
    cover_rel = ""
    cover_source = 0
    manual = (manual_cover or "").strip()
    if manual:
        cover_rel = manual.lstrip("/")
        cover_source = 1
    else:
        cover_dir = settings.storage_dir("cover_dir")
        cover_path = cover_dir / file_utils.dated_subdir(by_day=False) / f"{path.stem}.jpg"
        ok, backend = media_service.extract_cover(path, cover_path)
        if ok:
            cover_rel = _rel(cover_path, settings.storage_root)
            cover_source = 0
            logger.info("封面已生成 [%s] %s", backend, cover_path.name)
        else:
            logger.warning("封面生成失败（前端将显示占位图）: %s", path.stem)

    # ---------------- ④ 入库 ----------------
    video_id = video_repo.create(
        category_id=int(category_id),
        title=str(title)[:255],
        description=description or "",
        cover=cover_rel,
        path=_rel(path, settings.storage_root),
        original_name=original_name,
        duration=float(info.get("duration") or 0),
        size=actual_size,
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        bitrate=int(info.get("bitrate") or 0),
        mime=media_service.guess_mime(original_name or path.name),
        cover_source=cover_source,
        sort=int(sort or 0),
        status=1,
    )

    result = IngestResult(
        video_id=video_id,
        path=_rel(path, settings.storage_root),
        abs_path=path,
        size=actual_size,
        cover=cover_rel,
        duration=float(info.get("duration") or 0),
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        bitrate=int(info.get("bitrate") or 0),
        remuxed=remuxed,
        notes=notes,
    )
    logger.info(
        "入库完成 video#%d %s (%s, %dx%d, %.1fs)",
        video_id, title, file_utils.human_size(actual_size),
        result.width, result.height, result.duration,
    )
    return result


def find_duplicate(original_name: str, size: int) -> dict[str, Any] | None:
    """按「原始文件名 + 字节数」查已入库的同名同大小视频（导入去重用）。"""
    return video_repo.find_by_name_size(original_name, int(size))
