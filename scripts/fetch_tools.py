#!/usr/bin/env python3
"""外部二进制工具本地化脚本（m3u8 下载导入依赖）。

把「m3u8 链接下载导入」需要的两个命令行工具下载到 ``tools/`` 下，使功能开箱可用：

==============  ==========================================================
工具            用途
==============  ==========================================================
N_m3u8DL-RE     HLS/DASH 下载器，把 m3u8 播放列表下载为一个完整媒体文件
ffmpeg          (可选但强烈建议) 把分离的音视频轨混流成 mp4；缺失时只能得到
                未混流的中间文件，遇到 video+audio 双播放列表会失败
==============  ==========================================================

为什么单独下到 ``tools/`` 而不是让用户自己装：
- N_m3u8DL-RE 是单文件 exe，放进项目目录即可，不污染系统；
- ffmpeg 走系统安装包很容易装到没有 PATH 的位置，而本项目的探测逻辑
  （``download.ffmpeg_binary`` 留空时）会优先找 ``tools/ffmpeg/bin/``。

``tools/`` 下的二进制**不入版本库**（.gitignore 已忽略），换机器/重新克隆后
跑一次本脚本即可恢复。

用法::

    python scripts/fetch_tools.py              # 缺失才下载
    python scripts/fetch_tools.py --force      # 全部重新下载
    python scripts/fetch_tools.py --only re    # 只下 N_m3u8DL-RE
    python scripts/fetch_tools.py --only ffmpeg
    python scripts/fetch_tools.py --list       # 只列出当前状态与目标地址

版本策略：N_m3u8DL-RE 跟随 GitHub 最新 Release（通过 ``/releases/latest``
重定向解析 tag，避免调用 API 触发限流）；ffmpeg 取 gyan.dev / BtbN 的
「release 静态构建」（单个 exe，无需 DLL）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --- 路径：脚本位于 <项目根>/scripts/ 下 -------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = PROJECT_ROOT / "tools"
MANIFEST = TOOLS_DIR / "manifest.json"

RE_REPO = "nilaoda/N_m3u8DL-RE"
UA = "MediaManager-fetch-tools/1.0"

# 平台 -> (N_m3u8DL-RE 资产中的平台片段, 解压后落盘目录, 可执行文件名)
_PLATFORM_MAP: dict[tuple[str, str], tuple[str, str]] = {
    ("windows", "x86_64"): ("win-x64", "N_m3u8DL-RE/N_m3u8DL-RE.exe"),
    ("windows", "aarch64"): ("win-arm64", "N_m3u8DL-RE/N_m3u8DL-RE.exe"),
    ("linux", "x86_64"): ("linux-x64", "N_m3u8DL-RE/N_m3u8DL-RE"),
    ("linux", "aarch64"): ("linux-arm64", "N_m3u8DL-RE/N_m3u8DL-RE"),
    ("darwin", "x86_64"): ("osx-x64", "N_m3u8DL-RE/N_m3u8DL-RE"),
    ("darwin", "arm64"): ("osx-arm64", "N_m3u8DL-RE/N_m3u8DL-RE"),
}


@dataclass
class Tool:
    """一个待安装的外部工具。"""

    key: str                 # re / ffmpeg
    name: str
    target: Path             # 可执行文件的最终位置
    version: str = ""
    source: str = ""
    size: int = 0
    files: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return self.target.exists()

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "path": str(self.target.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "version": self.version,
            "source": self.source,
            "size": self.size,
            "files": self.files,
        }


def human_size(n: int | float) -> str:
    value = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


# ===========================================================================
# 下载
# ===========================================================================
def http_get(url: str, *, timeout: int = 120) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read()
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last = exc
            print(f"  ! 第 {attempt} 次下载失败: {exc}")
            time.sleep(1.5 * attempt)
    raise RuntimeError(f"下载失败: {url} ({last})")


def resolve_location(url: str, *, timeout: int = 60) -> tuple[str, str]:
    """跟随重定向，返回 ``(最终 URL, 文件名)``。不下载正文。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            final = resp.geturl()
            size = int(resp.headers.get("Content-Length") or 0)
    except urllib.error.HTTPError as exc:  # 有些站点不支持 HEAD
        if exc.code not in (403, 405, 501):
            raise
        final, size = url, 0
    except Exception:  # noqa: BLE001 - HEAD 失败就退回用原 URL
        final, size = url, 0
    name = os.path.basename(urllib.parse.urlparse(final).path) or os.path.basename(url)
    _ = size
    return final, urllib.parse.unquote(name)


# ===========================================================================
# N_m3u8DL-RE
# ===========================================================================
def latest_re_tag() -> str:
    """解析 GitHub 最新 Release 的 tag（走重定向，不调 API，避免限流）。"""
    url = f"https://github.com/{RE_REPO}/releases/latest"
    req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
            final = resp.geturl()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法解析最新版本号: {exc}") from exc
    match = re.search(r"/tag/(.+)$", final)
    if not match:
        raise RuntimeError(f"无法从 {final} 解析 tag")
    return match.group(1)


def install_re(*, force: bool) -> Tool:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("amd64", "x64"):
        machine = "x86_64"
    if machine in ("arm64", "aarch64"):
        machine = "arm64" if system == "darwin" else "aarch64"

    key = (system, machine)
    if key not in _PLATFORM_MAP:
        raise RuntimeError(f"暂无 {system}/{machine} 的预编译包，请手动下载后放到 tools/N_m3u8DL-RE/")
    asset_part, rel_exe = _PLATFORM_MAP[key]
    exe = TOOLS_DIR / rel_exe

    tag = latest_re_tag()
    tool = Tool(key="re", name="N_m3u8DL-RE", target=exe, version=tag)

    if exe.exists() and not force:
        tool.version = existing_re_version(exe) or tag
        print(f"  ✓ N_m3u8DL-RE 已存在（{tool.version}），跳过下载")
        tool.size = exe.stat().st_size
        return tool

    # 资产名形如 N_m3u8DL-RE_v0.6.0-beta_win-x64_20260629.zip，日期后缀会变，
    # 因此从 releases 展开页里正则取，而不是拼死一个文件名。
    listing = f"https://github.com/{RE_REPO}/releases/expanded_assets/{tag}"
    try:
        html = http_get(listing, timeout=60).decode("utf-8", "ignore")
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"无法获取发行版文件列表: {exc}") from exc
    pattern = re.compile(rf"/{RE_REPO}/releases/download/{re.escape(tag)}/([^\"]+{re.escape(asset_part)}[^\"]*)")
    names = sorted(set(pattern.findall(html)))
    if not names:
        raise RuntimeError(f"在 {tag} 中未找到 {asset_part} 对应的资产")
    asset = names[-1]
    url = f"https://github.com/{RE_REPO}/releases/download/{tag}/{urllib.parse.quote(asset)}"

    print(f"  ↓ {asset}")
    data = http_get(url, timeout=300)
    tool.source = url
    tool.size = len(data)

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = TOOLS_DIR / "_re.zip"
    tmp_zip.write_bytes(data)
    with zipfile.ZipFile(tmp_zip) as zf:
        members = [n for n in zf.namelist() if not n.endswith("/")]
        zf.extractall(TOOLS_DIR / "N_m3u8DL-RE")
    tmp_zip.unlink(missing_ok=True)
    tool.files = members

    if not exe.exists():
        raise RuntimeError(f"解压后未找到可执行文件: {exe}（压缩包内容: {members}）")
    if system != "windows":
        exe.chmod(exe.stat().st_mode | 0o755)
    print(f"  ✓ N_m3u8DL-RE {tag} -> {exe.relative_to(PROJECT_ROOT)}")
    tool.version = existing_re_version(exe) or tag
    return tool


def existing_re_version(exe: Path) -> str:
    try:
        out = subprocess.run(
            [str(exe), "--version"], capture_output=True, text=True, timeout=20
        )
        return (out.stdout or out.stderr).strip().splitlines()[0][:64]
    except Exception:  # noqa: BLE001
        return ""


# ===========================================================================
# ffmpeg
# ===========================================================================
def ffmpeg_url() -> tuple[str, str]:
    """返回 ``(下载 URL, 目标可执行文件名)``。"""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        # gyan.dev 的 release essentials 构建：单个 exe，体积适中，含 muxer/demuxer 全家桶
        return "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip", "ffmpeg.exe"
    if system == "linux":
        arch = "linuxarm64" if machine in ("aarch64", "arm64") else "linux64"
        ver = "ffmpeg-master-latest-" + arch + "-gpl"
        return f"https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/{ver}.zip", "ffmpeg"
    raise RuntimeError(
        "macOS 请用 `brew install ffmpeg` 安装后，把路径写入 config.yaml 的 download.ffmpeg_binary"
    )


def install_ffmpeg(*, force: bool) -> Tool:
    bin_name = "ffmpeg.exe" if platform.system().lower() == "windows" else "ffmpeg"
    target = TOOLS_DIR / "ffmpeg" / "bin" / bin_name
    tool = Tool(key="ffmpeg", name="ffmpeg", target=target)

    if target.exists() and not force:
        tool.version = ffmpeg_version(target)
        print(f"  ✓ ffmpeg 已存在（{tool.version}），跳过下载")
        tool.size = target.stat().st_size
        return tool

    url, _ = ffmpeg_url()
    final, fname = resolve_location(url)
    print(f"  ↓ {fname}（约 100MB+，首次较慢）")
    data = http_get(final, timeout=1800)
    tool.source = final
    tool.size = len(data)

    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    tmp_zip = TOOLS_DIR / "_ffmpeg.zip"
    tmp_zip.write_bytes(data)
    # 压缩包内是多层目录（ffmpeg-x.y/bin/ffmpeg.exe），只挑出需要的可执行文件，
    # 避免把 doc/、presets/ 等几十 MB 无关内容一起落盘。
    wanted = {"ffmpeg" + (".exe" if bin_name.endswith(".exe") else ""),
              "ffprobe" + (".exe" if bin_name.endswith(".exe") else "")}
    bin_dir = target.parent
    bin_dir.mkdir(parents=True, exist_ok=True)
    picked: list[str] = []
    with zipfile.ZipFile(tmp_zip) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = os.path.basename(info.filename)
            if base not in wanted:
                continue
            with zf.open(info) as src, (bin_dir / base).open("wb") as dst:
                shutil.copyfileobj(src, dst)
            picked.append(base)
    tmp_zip.unlink(missing_ok=True)

    if not target.exists():
        raise RuntimeError(f"压缩包内未找到 {bin_name}（已挑出: {picked}）")
    if os.name != "nt":
        for name in picked:
            p = bin_dir / name
            p.chmod(p.stat().st_mode | 0o755)
    tool.files = picked
    tool.version = ffmpeg_version(target)
    print(f"  ✓ ffmpeg {tool.version} -> {target.relative_to(PROJECT_ROOT)}")
    return tool


def ffmpeg_version(exe: Path) -> str:
    try:
        out = subprocess.run([str(exe), "-version"], capture_output=True, text=True, timeout=20)
        first = (out.stdout or "").splitlines()
        # "ffmpeg version 7.1 Copyright (c) ..." -> 7.1
        if first and first[0].startswith("ffmpeg version"):
            return first[0].split()[2][:32]
    except Exception:  # noqa: BLE001
        pass
    return ""


# ===========================================================================
# CLI
# ===========================================================================
def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        for block in iter(lambda: fp.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="fetch_tools.py",
        description="下载 m3u8 下载导入所需的外部工具到 tools/",
    )
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    parser.add_argument(
        "--only", choices=("re", "ffmpeg"), default=None, help="只处理其中一个工具"
    )
    parser.add_argument("--list", action="store_true", help="只检查当前状态，不下载")
    parser.add_argument("--json", dest="json_out", action="store_true", help="以 JSON 输出结果")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    system = platform.system().lower()
    bin_name = "N_m3u8DL-RE.exe" if system == "windows" else "N_m3u8DL-RE"
    ff_name = "ffmpeg.exe" if system == "windows" else "ffmpeg"

    re_exe = TOOLS_DIR / "N_m3u8DL-RE" / bin_name
    ff_exe = TOOLS_DIR / "ffmpeg" / "bin" / ff_name

    if args.list:
        print(f"项目根目录 : {PROJECT_ROOT}")
        print(f"N_m3u8DL-RE: {re_exe}  {'[已安装]' if re_exe.exists() else '[缺失]'}")
        print(f"ffmpeg     : {ff_exe}  {'[已安装]' if ff_exe.exists() else '[缺失]'}")
        try:
            url, _ = ffmpeg_url()
            print(f"ffmpeg 下载源: {resolve_location(url)[0]}")
        except Exception as exc:  # noqa: BLE001
            print(f"ffmpeg 下载源: 不可用（{exc}）")
        try:
            print(f"RE 最新版本  : {latest_re_tag()}")
        except Exception as exc:  # noqa: BLE001
            print(f"RE 最新版本  : 解析失败（{exc}）")
        return 0

    print(f"项目根目录: {PROJECT_ROOT}")
    results: list[Tool] = []
    failed = False

    if args.only != "ffmpeg":
        print("[1/2] N_m3u8DL-RE")
        try:
            results.append(install_re(force=args.force))
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ 安装失败: {exc}")
            failed = True

    if args.only != "re":
        print("[2/2] ffmpeg")
        try:
            results.append(install_ffmpeg(force=args.force))
        except Exception as exc:  # noqa: BLE001
            print(f"  ✗ 安装失败: {exc}")
            failed = True

    if results:
        old: dict = {}
        if MANIFEST.exists():
            try:
                old = json.loads(MANIFEST.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                old = {}
        merged = {t["key"]: t for t in old.get("tools", [])}
        for tool in results:
            entry = tool.to_dict()
            if tool.target.exists():
                entry["sha256"] = sha256_of(tool.target)
            merged[tool.key] = entry
        MANIFEST.write_text(
            json.dumps(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "platform": f"{platform.system().lower()}/{platform.machine().lower()}",
                    "tools": list(merged.values()),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    if args.json_out:
        print(json.dumps([t.to_dict() for t in results], ensure_ascii=False, indent=2))
    else:
        print("")
        missing_ff = not ff_exe.exists()
        if failed:
            print("⚠️ 有工具安装失败：m3u8 下载导入可能不可用，请按上方提示处理。")
        elif missing_ff:
            print("提示：ffmpeg 未就绪，遇到「音视频分离」的 HLS 会下载失败；"
                  "单轨 TS 播放列表仍可用（入库时会自动转封装为 MP4）。")
        else:
            print("完成：工具链已就绪。重启后端进程后，管理端「m3u8 链接下载」入口即可用。")
    return 1 if failed else 0


if __name__ == "__main__":
    import urllib.parse  # noqa: E402  （放在末尾避免与上面的 import 风格冲突）

    raise SystemExit(main())
