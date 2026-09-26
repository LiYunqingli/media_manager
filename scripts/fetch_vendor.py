#!/usr/bin/env python3
"""前端第三方库本地化脚本。

把页面依赖的 Vue / Element Plus / Vant 及其样式、语言包、图标全部下载到
``frontend/static/vendor/``，使系统在**完全离线**环境下也能正常运行
（前端页面只引用 ``/static/vendor/...``，不依赖任何 CDN）。

用法::

    python scripts/fetch_vendor.py            # 缺失才下载
    python scripts/fetch_vendor.py --force    # 全部重新下载
    python scripts/fetch_vendor.py --list     # 只列出清单，不下载
    python scripts/fetch_vendor.py --only vant.min.js vue.global.prod.js

下载来源按顺序尝试：npmmirror（国内快）→ unpkg → jsDelivr。
下载完成后写入 ``vendor/manifest.json``，记录版本、来源、大小与 SHA-256。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# --- 路径：脚本位于 <项目根>/scripts/ 下 -------------------------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENDOR_DIR = PROJECT_ROOT / "frontend" / "static" / "vendor"
MANIFEST = VENDOR_DIR / "manifest.json"

# --- 版本锁定（与页面实际使用保持一致，升级时改这里）------------------------- #
VUE_VERSION = "3.4.38"
EP_VERSION = "2.7.8"
EP_ICONS_VERSION = "2.3.1"
VANT_VERSION = "4.9.10"

# --- CDN 前缀（按顺序回退）--------------------------------------------------- #
CDN_PREFIXES = [
    "https://registry.npmmirror.com/{pkg}/{ver}/files/{path}",
    "https://unpkg.com/{pkg}@{ver}/{path}",
    "https://cdn.jsdelivr.net/npm/{pkg}@{ver}/{path}",
]


@dataclass
class Asset:
    """一个待下载文件。"""

    name: str                       # 落地文件名
    pkg: str                        # npm 包名
    version: str                    # 版本号
    path: str                       # 包内路径
    marker: str = ""                # 完整性标记（下载后应包含此字符串）
    size_hint: int = 0              # 预期大小（仅提示，非强制）

    def urls(self) -> list[str]:
        return [
            prefix.format(pkg=self.pkg, ver=self.version, path=self.path)
            for prefix in CDN_PREFIXES
        ]


ASSETS: list[Asset] = [
    Asset(
        name="vue.global.prod.js",
        pkg="vue",
        version=VUE_VERSION,
        path="dist/vue.global.prod.js",
        marker="vue v" + VUE_VERSION,
        size_hint=146_843,
    ),
    Asset(
        name="element-plus.min.js",
        pkg="element-plus",
        version=EP_VERSION,
        path="dist/index.full.min.js",
        marker="Element Plus v" + EP_VERSION,
        size_hint=961_022,
    ),
    Asset(
        name="element-plus.css",
        pkg="element-plus",
        version=EP_VERSION,
        path="dist/index.css",
        marker=".el-button",
        size_hint=321_076,
    ),
    Asset(
        name="element-plus-dark.css",
        pkg="element-plus",
        version=EP_VERSION,
        path="theme-chalk/dark/css-vars.css",
        marker="html.dark",
        size_hint=2_919,
    ),
    Asset(
        name="element-plus-zh-cn.min.js",
        pkg="element-plus",
        version=EP_VERSION,
        path="dist/locale/zh-cn.min.js",
        marker="Element Plus v" + EP_VERSION,
        size_hint=3_441,
    ),
    Asset(
        name="element-plus-icons.js",
        pkg="@element-plus/icons-vue",
        version=EP_ICONS_VERSION,
        path="dist/index.iife.min.js",
        marker="Element Plus Icons Vue v" + EP_ICONS_VERSION,
        size_hint=209_913,
    ),
    Asset(
        name="vant.min.js",
        pkg="vant",
        version=VANT_VERSION,
        path="lib/vant.min.js",
        marker=VANT_VERSION,
        size_hint=245_371,
    ),
    Asset(
        name="vant.css",
        pkg="vant",
        version=VANT_VERSION,
        path="lib/index.css",
        marker=":root",
        size_hint=199_285,
    ),
]


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, timeout: int = 60) -> bytes:
    """下载单个 URL，返回字节内容。"""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "MediaManager-fetch-vendor/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return resp.read()


def fetch_asset(asset: Asset) -> tuple[bytes, str]:
    """按 CDN 顺序尝试，返回 (内容, 成功的 URL)。"""
    errors: list[str] = []
    for url in asset.urls():
        try:
            data = download(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            errors.append(f"  ✗ {url}\n      {exc}")
            continue

        if not data:
            errors.append(f"  ✗ {url}\n      返回内容为空")
            continue

        # 完整性校验：标记字符串必须出现
        if asset.marker:
            try:
                text = data.decode("utf-8", "ignore")
            except Exception:  # pragma: no cover
                text = ""
            if asset.marker not in text:
                errors.append(f"  ✗ {url}\n      内容校验失败（未找到标记 {asset.marker!r}）")
                continue

        return data, url

    raise RuntimeError(
        f"下载 {asset.name} 失败，已尝试 {len(asset.urls())} 个来源：\n" + "\n".join(errors)
    )


def install(asset: Asset, *, force: bool) -> dict:
    """下载并写入一个文件，返回 manifest 条目。"""
    target = VENDOR_DIR / asset.name

    if target.exists() and not force:
        data = target.read_bytes()
        print(f"  跳过  {asset.name:<28} 已存在（{human_size(len(data))}）")
        return {
            "name": asset.name,
            "version": asset.version,
            "package": asset.pkg,
            "source": "local",
            "size": len(data),
            "sha256": sha256_of(data),
        }

    t0 = time.time()
    data, url = fetch_asset(asset)
    target.write_bytes(data)
    cost = time.time() - t0

    print(
        f"  下载  {asset.name:<28} {human_size(len(data)):<10} "
        f"({cost:.1f}s)  ← {url.split('/')[2]}"
    )
    return {
        "name": asset.name,
        "version": asset.version,
        "package": asset.pkg,
        "path": asset.path,
        "source": url,
        "size": len(data),
        "sha256": sha256_of(data),
    }


def write_manifest(entries: list[dict]) -> None:
    MANIFEST.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                "assets": entries,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="下载前端第三方库到 frontend/static/vendor/")
    parser.add_argument("--force", action="store_true", help="已存在也重新下载")
    parser.add_argument("--list", action="store_true", help="只列出清单")
    parser.add_argument("--only", nargs="+", metavar="NAME", help="只处理指定文件（按落地文件名）")
    args = parser.parse_args()

    assets = ASSETS
    if args.only:
        wanted = set(args.only)
        assets = [a for a in ASSETS if a.name in wanted]
        missing = wanted - {a.name for a in assets}
        if missing:
            print(f"未知文件名: {', '.join(sorted(missing))}", file=sys.stderr)
            return 2

    if args.list:
        print(f"vendor 目录: {VENDOR_DIR}")
        print(f"{'文件':<30}{'版本':<12}{'包'}")
        for a in assets:
            print(f"{a.name:<30}{a.version:<12}{a.pkg}")
        return 0

    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    print(f"vendor 目录: {VENDOR_DIR}\n")

    entries: list[dict] = []
    failed: list[str] = []
    for asset in assets:
        try:
            entries.append(install(asset, force=args.force))
        except RuntimeError as exc:
            print(f"  失败  {asset.name}\n{exc}", file=sys.stderr)
            failed.append(asset.name)

    if entries:
        write_manifest(entries)
        print(f"\n已写入 manifest: {MANIFEST}")

    if failed:
        print(f"\n有 {len(failed)} 个文件下载失败: {', '.join(failed)}", file=sys.stderr)
        print("请检查网络，或手动下载后放入 vendor 目录。", file=sys.stderr)
        return 1

    print("\n全部就绪。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
