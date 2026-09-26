"""管理端：分片上传 + 各类文件上传。

分片上传三个接口的调用顺序::

    1. POST /upload/init                  -> 拿到 upload_id / chunk_size / total_chunks
    2. POST /upload/chunk  (重复 N 次)     -> 逐片上传，每次回传整体进度
    3. POST /upload/{id}/merge            -> 后台合并，转去轮询 /progress 或订阅 WebSocket
    4. GET  /upload/{id}/progress         -> 轮询进度（也可用 WS /ws/admin/upload/{id}）
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile

from app.api.deps import CurrentAdmin
from app.core.config import get_settings
from app.core.errors import BizError, ErrorCode
from app.core.logger import get_logger
from app.core.response import ok
from app.repositories import upload_repo
from app.schemas.upload import UploadInitRequest, UploadMergeRequest
from app.services import upload_service
from app.utils import files as file_utils
from app.utils.presenter import present_upload

logger = get_logger("api.upload")
router = APIRouter(prefix="/upload", tags=["管理端-上传"])

# 单次分片请求上限（略大于 chunk_size，给 multipart 留余量）
_MAX_CHUNK_BYTES = 128 * 1024 * 1024


@router.post("/init", summary="① 初始化分片上传（分配任务）")
def init_upload(payload: UploadInitRequest, admin: CurrentAdmin) -> dict:
    return ok(upload_service.init_upload(admin, payload.model_dump()))


@router.post("/chunk", summary="② 上传单个分片")
async def upload_chunk(
    admin: CurrentAdmin,
    upload_id: Annotated[str, Form(max_length=40)],
    index: Annotated[int, Form(ge=0)],
    file: Annotated[UploadFile, File()],
    chunk_hash: Annotated[str | None, Form()] = None,
) -> dict:
    """接收一个分片。重复上传同一 index 会覆盖，天然支持断点续传。"""
    content = await file.read()
    if len(content) > _MAX_CHUNK_BYTES:
        raise BizError(ErrorCode.UPLOAD_CHUNK_INVALID, "单个分片超出大小限制")
    if chunk_hash:
        import hashlib

        actual = hashlib.md5(content).hexdigest()
        if actual != chunk_hash.lower():
            raise BizError(ErrorCode.UPLOAD_CHUNK_INVALID, f"分片 {index} 校验失败，请重传")
    return ok(upload_service.save_chunk(admin, upload_id, index, content))


@router.get("/{upload_id}/progress", summary="③ 查询上传进度")
def progress(
    upload_id: str,
    admin: CurrentAdmin,
    with_indexes: Annotated[bool, Query(description="是否返回已上传的分片序号列表")] = False,
) -> dict:
    return ok(upload_service.get_progress(admin, upload_id, with_indexes=with_indexes))


@router.post("/{upload_id}/merge", summary="④ 触发合并（异步，之后监听进度）")
def merge(upload_id: str, payload: UploadMergeRequest, admin: CurrentAdmin) -> dict:
    return ok(upload_service.start_merge(admin, upload_id, payload.model_dump()))


@router.delete("/{upload_id}", summary="取消上传并清理分片")
def cancel(upload_id: str, admin: CurrentAdmin) -> dict:
    upload_service.cancel_upload(admin, upload_id)
    return ok(msg="已取消")


@router.get("/sessions/list", summary="最近的上传会话（含中断可续传的）")
def sessions(
    admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict:
    rows = upload_repo.list_recent(int(admin["id"]), limit=limit)
    return ok([present_upload(r) for r in rows])


@router.post("/sessions/cleanup", summary="清理超时未完成的上传会话")
def cleanup(_: CurrentAdmin) -> dict:
    count = upload_service.cleanup_expired()
    return ok({"cleaned": count}, msg=f"已清理 {count} 个过期会话")


@router.post("/image", summary="上传图片（封面 / 头像 / 分类图）")
async def upload_image(
    admin: CurrentAdmin,
    file: Annotated[UploadFile, File()],
    kind: Annotated[str, Form(pattern=r"^(cover|avatar|category)$")] = "cover",
) -> dict:
    """图片直传（无需分片），返回可直接使用的相对路径与访问 URL。"""
    settings = get_settings()
    allow = settings.get("storage.allow_image_ext", [])
    name = file_utils.safe_filename(file.filename or "image")
    if not file_utils.check_ext(name, allow):
        raise BizError(ErrorCode.UNSUPPORTED_FILE_TYPE, f"不支持的图片格式: {file_utils.ext_of(name)}")

    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise BizError(ErrorCode.FILE_TOO_LARGE, "图片不能超过 20MB")

    dir_key = {"cover": "cover_dir", "avatar": "avatar_dir", "category": "cover_dir"}[kind]
    base = settings.storage_dir(dir_key)
    sub = file_utils.dated_subdir(by_day=False)
    stored = file_utils.generate_stored_name(name, prefix=f"{kind}_")
    target = base / sub / stored
    file_utils.ensure_dir(target.parent)
    with target.open("wb") as fp:
        fp.write(content)

    relative = target.resolve().relative_to(settings.storage_root.resolve()).as_posix()
    from app.utils.presenter import build_media_url

    logger.info("上传图片 %s (%s, %s)", relative, kind, file_utils.human_size(len(content)))
    return ok(
        {
            "path": relative,
            "url": build_media_url(relative),
            "name": name,
            "size": len(content),
            "size_text": file_utils.human_size(len(content)),
        }
    )
