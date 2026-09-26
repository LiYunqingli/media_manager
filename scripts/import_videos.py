#!/usr/bin/env python3
"""服务端批量导入：把指定目录下的视频登记进系统（跳过分片上传）。

给**服务器运维/管理员**用：视频文件已经在服务器磁盘上（移动硬盘拷进来、rsync 同步、
爬虫落盘等），不需要走浏览器分片上传，直接搬进 ``storage`` 并入库。

处理链路与网页分片上传完全一致，只是省掉了「切分片 → 逐片传输 → 拼接」三步::

    扫描目录 -> 判重 -> 搬运(copy/move/link) -> 容器校验/自动转封装
             -> 探测元信息 -> 生成封面 -> 写入 video 表

后四步复用 ``app.services.ingest_service.ingest_file``，因此两条入口的入库结果
（含 TS 容器自动转封装、封面抽帧参数、MIME 推断）**不会有任何差异**。

用法::

    # 先干跑看看会导入什么（不落盘、不写库）
    python scripts/import_videos.py D:/待导入 -r --category-name 电影 --dry-run

    # 正式导入：递归、复制进库、保留源文件
    python scripts/import_videos.py D:/待导入 -r --category-name 电影

    # 按子目录名自动建分类，并移动源文件（导入后源目录就空了）
    python scripts/import_videos.py D:/剧集 --category-from-subdir --mode move

    #    # 只需快速灌数据、不在意判重精度时关掉摘要计算
    #    python scripts/import_videos.py D:/待导入 --category-id 10 --no-hash

退出码：0 = 全部成功（含跳过），1 = 存在失败项，2 = 参数/环境错误。

判重
----
默认对每个源文件算一次 SHA-256（读源文件，与是否转封装无关），据此查重并写入
``upload_session``，两个好处：① 容器被自动转封装后体积变了也能准确识别重复；
② 网页端再上传同一文件会命中秒传。不想要这两点时用 ``--no-hash``。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

# --- 让脚本能直接 import 后端包（backend/ 加入 sys.path） -------------------- #
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402
from app.core.errors import BizError  # noqa: E402
from app.repositories import category_repo, upload_repo, video_repo  # noqa: E402
from app.services import ingest_service, media_service  # noqa: E402
from app.utils import files as file_utils  # noqa: E402

_print_lock = threading.Lock()


def emit(text: str = "") -> None:
    """线程安全的行输出（并发导入时避免日志交错）。"""
    with _print_lock:
        print(text, flush=True)


# ===========================================================================
# 分类解析
# ===========================================================================
class CategoryResolver:
    """把「分类名 / 子目录名」解析成 category_id，必要时自动创建分类。"""

    def __init__(self, default_id: int | None) -> None:
        self.default_id = default_id
        self._cache: dict[str, int] = {}
        self._lock = threading.Lock()

    def resolve(self, name: str | None) -> int:
        if not name:
            if self.default_id is None:
                raise RuntimeError("未指定默认分类（--category-id / --category-name）")
            return self.default_id

        with self._lock:
            if name in self._cache:
                return self._cache[name]
            row = category_repo.find_by_name(name)
            if row:
                cid = int(row["id"])
            else:
                cid = category_repo.create(name=name, sort=category_repo.max_sort() + 10)
                emit(f"  + 新建分类 #{cid} {name}")
            self._cache[name] = cid
            return cid


# ===========================================================================
# 单个文件的处理结果
# ===========================================================================
@dataclass
class Outcome:
    path: Path
    status: str                 # imported / skipped / failed
    video_id: int = 0
    detail: str = ""
    notes: list[str] = field(default_factory=list)
    size: int = 0
    duration: float = 0.0
    width: int = 0
    height: int = 0
    category: str = ""
    elapsed: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": str(self.path),
            "status": self.status,
            "video_id": self.video_id,
            "detail": self.detail,
            "notes": self.notes,
            "size": self.size,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "category": self.category,
            "elapsed": round(self.elapsed, 2),
        }


# ===========================================================================
# 路径扫描
# ===========================================================================
class ScanError(Exception):
    """扫描阶段的参数/路径错误（调用方直接映射为退出码 2）。"""


def collect_targets(
    paths: Iterable[Path],
    *,
    recursive: bool,
    exts: set[str],
    include_hidden: bool,
    limit: int,
) -> list[tuple[Path, Path]]:
    """把传入路径展开成 ``[(文件绝对路径, 所属搜索根目录)]``（已去重、已排序）。

    每一项可以是**目录**（按 ``recursive`` 展开）或**单个文件**（直接采纳，
    不受 ``recursive`` 影响）。单文件情况下「搜索根」取其父目录，于是
    ``--category-from-subdir`` 对它恒等于「无子目录分类」，落到默认分类
    —— 单个文件本来就谈不上按子目录归类。
    """
    seen: set[Path] = set()
    targets: list[tuple[Path, Path]] = []

    for root in paths:
        # ---- 显式指定的单个文件：直接采纳（不做隐藏文件过滤，后缀仍校验） ----
        if root.is_file():
            if root.suffix.lower() not in exts:
                raise ScanError(
                    f"不是支持的视频扩展名: {root.name}"
                    f"（允许 {', '.join(sorted(exts))}，可用 --ext 放宽）"
                )
            resolved = root.resolve()
            if resolved not in seen:
                seen.add(resolved)
                targets.append((resolved, resolved.parent))
                if limit and len(targets) >= limit:
                    return targets
            continue

        if not root.exists():
            raise ScanError(f"路径不存在: {root}")
        if not root.is_dir():
            raise ScanError(f"既不是文件也不是目录: {root}")

        walker = root.rglob("*") if recursive else root.glob("*")
        for item in sorted(walker, key=lambda p: str(p).lower()):
            if not item.is_file():
                continue
            if item.suffix.lower() not in exts:
                continue
            # macOS 的 ._xxx / .DS_Store 之类的元数据文件，默认跳过
            if not include_hidden and item.name.startswith("."):
                continue
            resolved = item.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            targets.append((resolved, root.resolve()))
            if limit and len(targets) >= limit:
                return targets
    return targets


def subdir_category(file_path: Path, root: Path) -> str | None:
    """取「相对搜索根的第一级目录名」作为分类名；文件直接在根下则返回 None。"""
    try:
        rel = file_path.relative_to(root)
    except ValueError:
        return None
    return rel.parts[0] if len(rel.parts) > 1 else None


# ===========================================================================
# 搬运
# ===========================================================================
def stage_file(src: Path, dest: Path, mode: str) -> str:
    """把源文件放到 ``dest``。返回实际操作（copy / move / hardlink）。

    ``move`` 也先复制：只有在整条入库链路都成功之后才删除源文件（见 main 的收尾逻辑），
    避免「文件已移走但入库失败」这种最难收拾的状态。
    """
    if mode == "link":
        try:
            os.link(src, dest)
            return "hardlink"
        except OSError as exc:
            # 跨盘 / 文件系统不支持硬链接 / 无权限 -> 静默退回复制
            emit(f"  ! 硬链接不可用（{exc.strerror or exc}），改为复制")
    shutil.copy2(src, dest)
    return "move-src-pending" if mode == "move" else "copy"


# ===========================================================================
# 单文件流程
# ===========================================================================
def process_one(
    file_path: Path,
    root: Path,
    args: argparse.Namespace,
    resolver: CategoryResolver,
) -> Outcome:
    started = time.time()
    outcome = Outcome(path=file_path, status="failed")
    settings = get_settings()
    storage_root = settings.storage_root

    original_name = file_utils.safe_filename(file_path.name)
    size = file_utils.file_size(file_path)
    outcome.size = size

    # ---------------- 内容摘要（判重 + 网页秒传用） ----------------
    # 为什么要算：容器不符的文件入库时会被**自动转封装**，落盘体积与源文件不再相等
    # （实测 18.8MB 的 TS -> 17.4MB 的 MP4），仅靠「同名同大小」判重会失效、导致
    # 同一批文件被反复导入。摘要读的是源文件，不受转封装影响，是唯一可靠的判重键。
    file_hash = ""
    if args.hash:
        try:
            file_hash = file_utils.hash_file(file_path)
        except OSError as exc:
            emit(f"  ! 计算文件摘要失败（将退化为按名称+大小判重）: {exc}")

    # ---------------- 分类 ----------------
    try:
        cid = resolver.resolve(
            subdir_category(file_path, root) if args.category_from_subdir else None
        )
    except Exception as exc:  # noqa: BLE001
        outcome.detail = f"分类解析失败: {exc}"
        outcome.elapsed = time.time() - started
        return outcome
    cat_row = category_repo.find_by_id(cid)
    outcome.category = str(cat_row["name"]) if cat_row else str(cid)

    # ---------------- 判重 ----------------
    # 优先按内容摘要（精确，且能识别「转封装后体积变了」的同名文件）；
    # 未算摘要时退化为「原始文件名 + 字节数」。
    if not args.force:
        dup = video_repo.find_by_hash(file_hash) if file_hash else None
        reason = "内容一致"
        if not dup:
            dup = ingest_service.find_duplicate(original_name, size)
            reason = "同名同大小"
        if dup:
            outcome.status = "skipped"
            outcome.video_id = int(dup["id"])
            outcome.detail = f"已存在 video#{dup['id']}（{reason}）"
            outcome.elapsed = time.time() - started
            return outcome

    # ---------------- 定位目标路径 ----------------
    already_inside = file_utils.is_relative_to(file_path, storage_root)
    created: Path | None = None  # 由本脚本创建的落盘文件（失败时要清理）

    if already_inside:
        dest = file_path
    else:
        video_dir = settings.storage_dir("video_dir")
        sub = file_utils.dated_subdir(by_day=False)
        dest = video_dir / sub / file_utils.generate_stored_name(original_name)
        file_utils.ensure_dir(dest.parent)
        try:
            stage_file(file_path, dest, args.mode)
        except OSError as exc:
            outcome.detail = f"搬运文件失败: {exc}"
            outcome.elapsed = time.time() - started
            return outcome
        created = dest

    title = original_name if args.title_from == "filename" else Path(original_name).stem

    # ---------------- 入库（容器校验/转封装 -> 探测 -> 封面 -> 写表） ----------------
    try:
        result = ingest_service.ingest_file(
            dest,
            category_id=cid,
            title=title,
            original_name=original_name,
            description=args.description,
            sort=args.sort,
        )
    except (BizError, OSError, ValueError) as exc:
        if created is not None:
            file_utils.remove_file(created)  # 回滚：不留孤儿文件
        outcome.detail = f"入库失败: {getattr(exc, 'message', exc)}"
        outcome.elapsed = time.time() - started
        return outcome
    except Exception as exc:  # noqa: BLE001
        if created is not None:
            file_utils.remove_file(created)
        outcome.detail = f"入库异常: {type(exc).__name__}: {exc}"
        outcome.elapsed = time.time() - started
        return outcome

    # ---------------- 成功收尾 ----------------
    outcome.status = "imported"
    outcome.video_id = result.video_id
    outcome.size = result.size
    outcome.duration = result.duration
    outcome.width = result.width
    outcome.height = result.height
    outcome.notes = list(result.notes)
    outcome.detail = "导入成功"

    if args.mode == "move" and not already_inside:
        file_utils.remove_file(file_path)  # 入库成功后才删源，失败时源文件还在

    if args.hash and file_hash:
        _record_session(args, cid, title, result, original_name, file_hash)

    outcome.elapsed = time.time() - started
    return outcome


def _record_session(
    args: argparse.Namespace,
    category_id: int,
    title: str,
    result: ingest_service.IngestResult,
    original_name: str,
    file_hash: str,
) -> None:
    """写一条 finished 的上传会话，落库 ``file_hash``。

    这不是「历史包袱」：网页端 ``init_upload`` 的秒传逻辑完全依赖
    ``upload_session.file_hash``，没有这条记录，导入过的文件在网页端再传一次
    仍会从头分片上传。副作用是该记录会出现在管理端「最近上传会话」列表里。
    """
    import uuid

    settings = get_settings()
    try:
        upload_id = uuid.uuid4().hex
        upload_repo.create_session(
            upload_id=upload_id,
            user_id=int(args.user_id),
            file_name=original_name,
            total_size=result.size,
            chunk_size=settings.chunk_size,
            total_chunks=1,
            file_hash=file_hash,
            category_id=category_id,
            title=title,
        )
        upload_repo.update(
            upload_id,
            {
                "stage": "finished",
                "percent": 100,
                "video_id": result.video_id,
                "merged_bytes": result.size,
                "message": "由服务端 CLI 导入",
            },
        )
    except Exception as exc:  # noqa: BLE001 - 台账写入失败不影响导入结果
        emit(f"  ! 写入导入台账失败: {exc}")


def _default_admin_id() -> int:
    from app.db import session as db

    value = db.query_value("SELECT id FROM sys_user WHERE role = 'admin' ORDER BY id LIMIT 1")
    if value is None:
        raise RuntimeError("库中没有管理员账号，无法归属导入记录；请显式指定 --user-id")
    return int(value)


# ===========================================================================
# CLI
# ===========================================================================
def normalize_ext(raw: Iterable[str]) -> set[str]:
    result = set()
    for ext in raw:
        ext = ext.strip().lower()
        if not ext:
            continue
        result.add(ext if ext.startswith(".") else f".{ext}")
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="import_videos.py",
        description="把指定目录（或单个文件）下的视频批量导入 MediaManager（跳过分片上传）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python scripts/import_videos.py D:/待导入 --category-name 电影 --dry-run\n"
            "  python scripts/import_videos.py D:/待导入 -r --category-name 电影\n"
            "  python scripts/import_videos.py D:/剧集 --category-from-subdir --mode move\n"
            "  python scripts/import_videos.py E:/珠江.mp4 --category-id 10\n"
        ),
    )
    parser.add_argument(
        "paths", nargs="+", metavar="路径", help="待导入的目录或单个视频文件（可多个）"
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="递归子目录")

    group = parser.add_argument_group("分类")
    group.add_argument("--category-id", type=int, default=None, help="目标分类 ID")
    group.add_argument("--category-name", default=None, help="目标分类名（不存在则自动创建）")
    group.add_argument(
        "--category-from-subdir",
        action="store_true",
        help="按「一级子目录名」自动建分类；直属于根的文件落到 --category-id/--category-name",
    )

    group = parser.add_argument_group("搬运")
    group.add_argument(
        "--mode",
        choices=("copy", "move", "link"),
        default="copy",
        help="copy=复制进库保留源(默认) / move=入库成功后删源 / link=同盘硬链接(零拷贝)",
    )
    group.add_argument("--sort", type=int, default=0, help="排序值，越大越靠前")

    group = parser.add_argument_group("过滤")
    group.add_argument("--ext", nargs="+", default=None, help="限定扩展名，如 --ext .mp4 .mkv（默认取 config）")
    group.add_argument("--limit", type=int, default=0, help="最多处理 N 个文件（0=不限）")
    group.add_argument("--include-hidden", action="store_true", help="包含 . 开头的文件")
    group.add_argument("--force", action="store_true", help="同名同大小已存在时也重新导入")

    group = parser.add_argument_group("行为")
    group.add_argument("--dry-run", action="store_true", help="只列出将要导入的文件，不落盘不写库")
    group.add_argument("--jobs", type=int, default=1, help="并发处理数（默认 1；抽帧受全局锁限制，建议不超过 4）")
    group.add_argument("--title-from", choices=("stem", "filename"), default="stem", help="标题来源")
    group.add_argument("--description", default="", help="统一写入的视频简介")
    group.add_argument(
        "--no-hash",
        dest="hash",
        action="store_false",
        help="跳过内容摘要计算：不写导入台账，判重退化为「同名同大小」（大目录导入更快）",
    )
    parser.set_defaults(hash=True)
    group.add_argument("--user-id", type=int, default=None, help="写台账时归属的用户（默认取首个管理员）")
    group.add_argument("-v", "--verbose", action="store_true", help="打印后端 DEBUG 日志")
    group.add_argument("--json", dest="json_out", action="store_true", help="以 JSON 输出结果摘要")
    return parser.parse_args(argv)


def resolve_default_category(args: argparse.Namespace) -> int | None:
    """解析默认分类：``--category-id`` 直接采用；``--category-name`` 不存在则创建。"""
    if args.category_id:
        return int(args.category_id)
    if args.category_name:
        row = category_repo.find_by_name(args.category_name)
        if row:
            return int(row["id"])
        cid = category_repo.create(name=args.category_name, sort=category_repo.max_sort() + 10)
        emit(f"  + 新建分类 #{cid} {args.category_name}")
        return cid
    return None


def format_line(index: int, total: int, outcome: Outcome) -> str:
    tag = {"imported": "OK  ", "skipped": "跳过", "failed": "失败"}[outcome.status]
    head = f"[{index}/{total}] {tag} {outcome.path.name}"
    if outcome.status == "imported":
        info = [
            f"video#{outcome.video_id}",
            outcome.category,
            f"{outcome.width}x{outcome.height}",
            file_utils.format_duration(outcome.duration),
            file_utils.human_size(outcome.size),
            f"{outcome.elapsed:.1f}s",
        ]
        return f"{head}  -> " + " | ".join(info) + (
            "\n" + "\n".join(f"        ! {n}" for n in outcome.notes) if outcome.notes else ""
        )
    if outcome.status == "skipped":
        return f"{head}  -> {outcome.detail}"
    return f"{head}  -> ⚠️ {outcome.detail}"


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台编码兜底：无法编码的字符替换而不是抛 UnicodeEncodeError
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(errors="replace")

    args = parse_args(argv)
    args.jobs = max(1, min(int(args.jobs or 1), 8))

    if args.verbose:
        import logging

        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
    else:
        import logging

        logging.basicConfig(level=logging.WARNING, format="%(levelname)s | %(message)s")

    settings = get_settings()
    if not args.json_out:
        emit(f"storage  : {settings.storage_root}")
        emit(f"database : {settings.get('database.host')}:{settings.get('database.port')}"
             f"/{settings.get('database.name')}")
        emit(f"config   : {settings.source}")

    settings.ensure_dirs()

    paths = [Path(p).expanduser().resolve() for p in args.paths]
    exts = normalize_ext(args.ext) if args.ext else {
        e.lower() for e in (settings.get("storage.allow_video_ext", []) or [])
    }
    if not exts:
        emit("⚠️ 未配置允许的视频扩展名（storage.allow_video_ext），请用 --ext 指定")
        return 2

    # ---- 分类参数尽早校验：避免「扫完整个目录才发现参数错」 ----
    # 这里只做只读检查；--category-name 指向的分类若不存在，留到正式导入时创建
    # （--dry-run 承诺「不落盘不写库」，不该顺手建出分类）。
    if args.category_id and args.category_name:
        emit("⚠️ --category-id 与 --category-name 只能给一个")
        return 2
    if args.category_from_subdir and not (args.category_id or args.category_name):
        emit("⚠️ --category-from-subdir 时，直属根目录的文件需要默认分类，"
             "请同时给 --category-id 或 --category-name")
        return 2
    if args.category_id and not category_repo.find_by_id(args.category_id):
        emit(f"⚠️ 分类不存在: #{args.category_id}")
        return 2

    video_backends = media_service.available_backends()
    if not (video_backends.get("av") or video_backends.get("cv2")):
        emit("⚠️ 未安装 av / opencv-python，元信息探测与封面抽帧会大幅降级（建议安装）")

    try:
        targets = collect_targets(
            paths,
            recursive=args.recursive,
            exts=exts,
            include_hidden=args.include_hidden,
            limit=args.limit,
        )
    except ScanError as exc:
        emit(f"⚠️ {exc}")
        return 2

    mode_text = {"copy": "复制", "move": "移动", "link": "硬链接"}[args.mode]
    if not args.json_out:
        emit(f"扫描     : {', '.join(str(p) for p in paths)}"
             f"（递归={args.recursive}, 扩展名={','.join(sorted(exts))}）")
        emit(f"搬运方式 : {mode_text}  并发={args.jobs}\n")

    if not targets:
        emit("没有找到可导入的视频文件。")
        return 0

    emit(f"找到 {len(targets)} 个视频文件。")

    if args.dry_run:
        for index, (path, root) in enumerate(targets, 1):
            size = file_utils.file_size(path)
            if args.category_from_subdir:
                cat = subdir_category(path, root) or "(默认分类)"
            elif args.category_name:
                cat = args.category_name
            elif args.category_id:
                cat = f"#{args.category_id}"
            else:
                cat = "(未指定)"
            # 顺带嗅探真实容器：与扩展名不符的文件导入时会被自动转封装，值得提前知道
            container = media_service.detect_container(path)
            allowed = media_service.CONTAINERS_BY_EXT.get(path.suffix.lower())
            warn = ""
            if container != "unknown" and allowed and container not in allowed:
                warn = f"  ⚠️ 实为 {container.upper()} 容器，导入时将自动转封装"
            emit(
                f"[{index}/{len(targets)}] {file_utils.human_size(size):>10}  "
                f"{cat:<12} {container:<8} {path.name}{warn}"
            )
        emit("\n（--dry-run：以上文件未被导入）")
        if not (args.category_id or args.category_name or args.category_from_subdir):
            emit("⚠️ 未指定分类：正式导入需要 --category-id 或 --category-name"
                 "（或 --category-from-subdir 按子目录自动建分类）")
        return 0

    # ---- 正式导入必须有分类 ----
    # 与其让每个文件各失败一次（最后还配一句「已入库」的误导提示），不如开跑前一次说清。
    # --dry-run 不写库，允许不给分类（上方分类列会显示「未指定」）。
    if not (args.category_id or args.category_name):
        emit("⚠️ 未指定分类：请用 --category-id N 或 --category-name 名称"
             "（想按子目录自动建分类则加 --category-from-subdir）")
        return 2

    try:
        default_cid = resolve_default_category(args)
    except SystemExit as exc:
        emit(f"⚠️ {exc}")
        return 2

    if args.hash and not args.user_id:
        # 导入台账需要一个归属用户（upload_session.user_id 非空）
        try:
            args.user_id = _default_admin_id()
        except RuntimeError as exc:
            emit(f"⚠️ {exc}")
            return 2

    resolver = CategoryResolver(default_cid)
    total = len(targets)
    counter = {"done": 0}
    counter_lock = threading.Lock()

    def worker(item: tuple[Path, Path]) -> Outcome:
        path, root = item
        try:
            outcome = process_one(path, root, args, resolver)
        except Exception as exc:  # noqa: BLE001 - 单文件异常不该终止整批
            outcome = Outcome(path=path, status="failed", detail=f"{type(exc).__name__}: {exc}")
        with counter_lock:
            counter["done"] += 1
            index = counter["done"]
        if not args.json_out:
            emit(format_line(index, total, outcome))
        return outcome

    started = time.time()
    if args.jobs == 1:
        results = [worker(item) for item in targets]
    else:
        with ThreadPoolExecutor(max_workers=args.jobs, thread_name_prefix="import") as pool:
            results = list(pool.map(worker, targets))

    imported = [r for r in results if r.status == "imported"]
    skipped = [r for r in results if r.status == "skipped"]
    failed = [r for r in results if r.status == "failed"]
    elapsed = time.time() - started

    if args.json_out:
        print(json.dumps(
            {
                "total": total,
                "imported": len(imported),
                "skipped": len(skipped),
                "failed": len(failed),
                "elapsed": round(elapsed, 2),
                "items": [r.to_dict() for r in results],
            },
            ensure_ascii=False,
            indent=2,
        ))
    else:
        emit("")
        emit("=" * 68)
        emit(f"完成：成功 {len(imported)} | 跳过 {len(skipped)} | 失败 {len(failed)}"
             f"（共 {total} 个，耗时 {elapsed:.1f}s）")
        emitted_bytes = sum(r.size for r in imported)
        if imported:
            emit(f"入库体积：{file_utils.human_size(emitted_bytes)}")
        if failed:
            emit("\n⚠️ 失败清单：")
            for r in failed:
                emit(f"  - {r.path}：{r.detail}")
        emit("=" * 68)
        # 提示必须跟着实际结果走：全失败时说「已入库」是在骗人。
        if not imported:
            if failed:
                emit("提示：没有任何视频入库，请按上方失败原因修正后重跑。")
            else:
                emit("提示：这些视频此前都已导入过，未新增记录。")
        elif failed:
            emit(f"提示：{len(imported)} 个已入库（另有 {len(failed)} 个失败，见上方清单），"
                 "管理端刷新即可看到成功的部分。")
        else:
            emit(f"提示：{len(imported)} 个视频已入库，管理端刷新即可看到。")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
