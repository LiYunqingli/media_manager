"""日志配置。

- 控制台 + 文件双输出
- 文件按大小轮转
- 统一 logger 名称 ``media_manager``，子模块用 ``logging.getLogger("media_manager.xxx")``
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings

_CONFIGURED = False
_FMT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _ColorFormatter(logging.Formatter):
    """控制台带颜色的格式化器（Windows 10+ / *nix 均可用）。"""

    COLORS = {
        "DEBUG": "\033[36m",
        "INFO": "\033[32m",
        "WARNING": "\033[33m",
        "ERROR": "\033[31m",
        "CRITICAL": "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        color = self.COLORS.get(record.levelname)
        return f"{color}{text}{self.RESET}" if color else text


def setup_logging() -> logging.Logger:
    """初始化日志系统，可重复调用（幂等）。"""
    global _CONFIGURED

    root = logging.getLogger("media_manager")
    if _CONFIGURED:
        return root

    settings = get_settings()
    level_name = str(settings.get("log.level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)
    root.setLevel(level)
    root.propagate = False

    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    if bool(settings.get("log.console", True)):
        stream = logging.StreamHandler(sys.stdout)
        stream.setLevel(level)
        stream.setFormatter(_ColorFormatter(_FMT, datefmt=_DATEFMT))
        root.addHandler(stream)

    if bool(settings.get("log.file", True)):
        try:
            settings.log_dir.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                settings.log_dir / str(settings.get("log.file_name", "backend.log")),
                maxBytes=int(settings.get("log.max_bytes", 10 * 1024 * 1024)),
                backupCount=int(settings.get("log.backup_count", 5)),
                encoding="utf-8",
            )
            file_handler.setLevel(level)
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:  # 磁盘不可写时降级为仅控制台
            root.warning("无法写入日志文件，已降级为仅控制台输出: %s", exc)

    # uvicorn 的日志接入同一套 handler，避免双份格式
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True

    _CONFIGURED = True
    root.info("日志系统已初始化，级别=%s，配置文件=%s", level_name, settings.source)
    return root


def get_logger(name: str = "") -> logging.Logger:
    """获取子 logger。"""
    return logging.getLogger(f"media_manager.{name}" if name else "media_manager")
