"""管理端：m3u8 链接下载导入。

与 ``upload.py``（分片上传）并列的第二条入库入口：不传文件，只传链接，
由服务端调 N_m3u8DL-RE 下载后按同一套逻辑入库。

调用顺序::

    1. POST   /download/m3u8                     -> 建任务，拿到 task_id
    2. GET    /download/tasks/{task_id}          -> 轮询进度（也可用 /
       GET    /download/tasks                    列表页一次拉全部）
    3. GET    /download/tools                    -> 工具链是否就绪（前端首屏提示用）
    4. POST   /download/tasks/{id}/cancel|retry  -> 取消 / 重试
    5. DELETE /download/tasks/{id}               -> 删除记录（不动已入库的视频）

鉴权
----
下列接口的依赖是 :data:`app.api.deps.DownloadOperator`，即
**管理员 JWT** 或 **``X-API-Token`` 接口令牌** 二选一。
后者专供浏览器插件：在 config.yaml 里设 ``download.api_token`` 后，插件只需::

    POST /api/admin/download/m3u8
    X-API-Token: <你的令牌>
    Content-Type: application/json

    {"url": "...index.m3u8", "title": "视频名称", "cover_url": "https://.../p.jpg"}
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import DownloadOperator
from app.core.logger import get_logger
from app.core.response import ok
from app.schemas.download import DownloadCreateRequest
from app.services import download_service

logger = get_logger("api.download")
router = APIRouter(prefix="/download", tags=["管理端-m3u8下载"])


@router.post("/m3u8", summary="① 新建 m3u8 下载导入任务")
def create(payload: DownloadCreateRequest, user: DownloadOperator) -> dict:
    """投递一个下载任务，立即返回任务快照（下载在后台进行）。"""
    data = download_service.create_task(
        user, payload.model_dump(), source="api" if _is_api_token_call(user) else "admin"
    )
    return ok(data, msg="该链接已下载过，已复用既有任务" if data.get("deduped") else "已加入下载队列")


@router.get("/tools", summary="工具链状态（N_m3u8DL-RE / ffmpeg 是否就绪）")
def tools(_: DownloadOperator) -> dict:
    return ok(download_service.tool_status())


@router.get("/tasks", summary="② 任务列表（含统计；前端据此轮询）")
def list_tasks(
    user: DownloadOperator,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
    stage: Annotated[str | None, Query(description="按阶段过滤")] = None,
    mine: Annotated[bool, Query(description="true=只看自己投递的")] = True,
) -> dict:
    return ok(download_service.list_tasks(user, limit=limit, offset=offset, stage=stage, mine=mine))


@router.get("/tasks/{task_id}", summary="③ 单个任务进度")
def detail(task_id: str, user: DownloadOperator) -> dict:
    return ok(download_service.get_progress(user, task_id))


@router.post("/tasks/{task_id}/cancel", summary="④ 取消任务")
def cancel(task_id: str, user: DownloadOperator) -> dict:
    return ok(download_service.cancel_task(user, task_id), msg="已取消")


@router.post("/tasks/{task_id}/retry", summary="⑤ 重试任务")
def retry(task_id: str, user: DownloadOperator) -> dict:
    return ok(download_service.retry_task(user, task_id), msg="已重新入队")


@router.delete("/tasks/{task_id}", summary="删除任务记录（已入库的视频不受影响）")
def remove(task_id: str, user: DownloadOperator) -> dict:
    download_service.delete_task(user, task_id)
    return ok(msg="已删除")


@router.post("/tasks/cleanup", summary="清理 7 天前的失败/取消任务")
def cleanup(_: DownloadOperator) -> dict:
    count = download_service.cleanup_expired(7)
    return ok({"cleaned": count}, msg=f"已清理 {count} 条")


def _is_api_token_call(user: dict) -> bool:
    """用 X-API-Token 调用时任务的归属用户是「系统管理员」，用它区分来源。

    这里只需要一个是否来自插件的标记，不必回读请求头，故用标记字段判断。
    """
    return bool(user.get("_via_api_token"))
