"""文件与路径工具。

安全要点：
- :func:`safe_filename` 清洗上传文件名，杜绝 ``../`` 目录穿越；
- :func:`safe_join` 保证拼接结果不越出根目录。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime
from pathlib import Path
from typing import Iterator

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_MULTI_SPACE = re.compile(r"\s+")


def normalize_name(name: str, *, max_length: int = 120) -> str:
    """归一化文件名（保留中文）。"""
    name = unicodedata.normalize("NFKC", name or "")
    name = _ILLEGAL.sub("_", name)
    name = _MULTI_SPACE.sub(" ", name).strip(" .")
    if len(name) > max_length:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: max_length - len(ext) - 1] + dot + ext) if dot else name[:max_length]
    return name or "unnamed"


def safe_filename(filename: str) -> str:
    """取文件名部分并清洗，防止目录穿越。"""
    base = os.path.basename((filename or "").replace("\\", "/"))
    return normalize_name(base)


def ext_of(filename: str) -> str:
    """返回小写扩展名，含点号；无扩展名返回空串。"""
    return Path(filename or "").suffix.lower()


def check_ext(filename: str, allow: list[str]) -> bool:
    return ext_of(filename) in {e.lower() for e in allow}


def safe_join(root: Path, *parts: str) -> Path:
    """安全拼接路径，确保结果位于 root 之内。"""
    root = root.resolve()
    target = root.joinpath(*parts).resolve()
    if root != target and root not in target.parents:
        raise ValueError(f"路径越界: {target}")
    return target


def generate_stored_name(original: str, *, prefix: str = "") -> str:
    """生成磁盘存储名：``<prefix><时间戳>_<短uuid><扩展名>``。"""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    short = uuid.uuid4().hex[:8]
    ext = ext_of(original) or ".bin"
    return f"{prefix}{stamp}_{short}{ext}"


def dated_subdir(*, by_day: bool = True) -> str:
    """按年月（或年月日）分目录，避免单目录文件过多。"""
    now = datetime.now()
    return now.strftime("%Y/%m/%d") if by_day else now.strftime("%Y/%m")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def remove_file(path: Path, *, missing_ok: bool = True) -> bool:
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        if not missing_ok:
            raise
        return False
    except OSError:
        return False


def remove_dir(path: Path) -> bool:
    try:
        shutil.rmtree(path, ignore_errors=True)
        return True
    except OSError:
        return False


def hash_file(path: Path, *, algorithm: str = "sha256", chunk_size: int = 1024 * 1024) -> str:
    """计算文件摘要。"""
    digest = hashlib.new(algorithm)
    with path.open("rb") as fp:
        while True:
            block = fp.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def iter_file_chunks(path: Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """按块读取文件，用于合并时统计进度。"""
    with path.open("rb") as fp:
        while True:
            block = fp.read(chunk_size)
            if not block:
                break
            yield block


def human_size(size: int | float) -> str:
    """把字节数格式化成人读形式。"""
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.2f} TB"


def format_duration(seconds: float | int) -> str:
    """秒 -> ``HH:MM:SS`` / ``MM:SS``。"""
    total = int(seconds or 0)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def is_relative_to(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
