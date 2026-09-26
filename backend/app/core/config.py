"""全局配置加载器。

职责：
1. 定位并读取 ``config/config.yaml``；
2. 支持 ``${ENV_NAME:default}`` 占位符，运行时用环境变量替换；
3. 提供点号路径访问：``settings.get("database.host")``；
4. 解析并缓存所有路径（保证跨工作目录启动也能找到文件）。

配置只在进程内加载一次（lru_cache），修改配置需重启服务。
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

# backend/app/core/config.py -> 项目根目录
PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
BACKEND_DIR: Path = PROJECT_ROOT / "backend"
DEFAULT_CONFIG_PATH: Path = PROJECT_ROOT / "config" / "config.yaml"

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


class ConfigError(RuntimeError):
    """配置缺失或格式错误。"""


def _resolve_env_placeholder(value: str) -> str:
    """把 ``${NAME:default}`` 替换为环境变量值，未设置则用 default。"""

    def _sub(match: re.Match[str]) -> str:
        name, default = match.group(1), match.group(2)
        return os.environ.get(name, default if default is not None else "")

    return _ENV_PATTERN.sub(_sub, value)


def _walk(node: Any) -> Any:
    """递归处理 dict / list / str 中的占位符。"""
    if isinstance(node, dict):
        return {k: _walk(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(v) for v in node]
    if isinstance(node, str):
        return _resolve_env_placeholder(node)
    return node


class Settings:
    """配置访问门面。"""

    def __init__(self, raw: dict[str, Any], source: Path) -> None:
        self._raw = raw
        self.source = source

    # ---------------------------------------------------------------- 基础访问
    @property
    def raw(self) -> dict[str, Any]:
        return self._raw

    def get(self, path: str, default: Any = None) -> Any:
        """按 ``a.b.c`` 路径读取配置，任一层缺失即返回 default。"""
        node: Any = self._raw
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> dict[str, Any]:
        value = self.get(name, {})
        if not isinstance(value, dict):
            raise ConfigError(f"配置节 {name} 必须是字典，实际为 {type(value).__name__}")
        return value

    def require(self, path: str) -> Any:
        value = self.get(path, None)
        if value is None or value == "":
            raise ConfigError(f"缺少必填配置项: {path}")
        return value

    # ---------------------------------------------------------------- 路径解析
    @staticmethod
    def resolve_path(value: str | os.PathLike[str]) -> Path:
        """相对路径一律相对【项目根目录】解析，避免受当前工作目录影响。"""
        p = Path(str(value)).expanduser()
        return p if p.is_absolute() else (PROJECT_ROOT / p).resolve()

    # ------------------------------------------------------------ 常用快捷属性
    @property
    def storage_root(self) -> Path:
        return self.resolve_path(self.get("storage.root", "./storage"))

    def storage_dir(self, key: str) -> Path:
        """取存储子目录，例如 storage_dir('video_dir') -> <root>/videos。"""
        name = self.get(f"storage.{key}", key)
        return self.storage_root / str(name)

    @property
    def log_dir(self) -> Path:
        return self.storage_root / str(self.get("storage.log_dir", "logs"))

    @property
    def chunk_size(self) -> int:
        return int(self.get("upload.chunk_size", 5 * 1024 * 1024))

    @property
    def view_threshold_seconds(self) -> float:
        return float(self.get("business.view_count_threshold_seconds", 10))

    @property
    def page_size(self) -> int:
        return int(self.get("business.page_size", 20))

    def ensure_dirs(self) -> None:
        """创建全部必需目录。"""
        for key in (
            "video_dir",
            "cover_dir",
            "avatar_dir",
            "chunk_dir",
            "tmp_dir",
            "log_dir",
        ):
            self.storage_dir(key).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def load_config() -> Settings:
    """加载并缓存配置。"""
    custom = os.environ.get("MM_CONFIG")
    path = Path(custom).resolve() if custom else DEFAULT_CONFIG_PATH
    if not path.exists():
        raise ConfigError(
            f"未找到配置文件: {path}\n"
            f"请确认 config/config.yaml 存在，或用环境变量 MM_CONFIG 指定路径。"
        )
    with path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"配置文件根节点必须是字典: {path}")
    return Settings(_walk(raw), path)


def get_settings() -> Settings:
    """供 FastAPI 依赖注入使用的入口。"""
    return load_config()
