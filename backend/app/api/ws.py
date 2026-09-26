"""WebSocket：分片上传进度实时推送。

为什么用 WebSocket：合并大文件时进度变化密集，轮询会浪费请求；
但轮询接口依然保留（``GET /api/admin/upload/{id}/progress``），
两者读取的是**同一份** ``upload_session`` 快照，前端可任选其一或互为兜底。

连接方式::

    ws://host/ws/admin/upload/<upload_id>?token=<jwt>

服务端在阶段变为 ``finished`` / ``failed`` 后推送最后一帧并主动关闭。
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.errors import BizError
from app.core.logger import get_logger
from app.services import auth_service, upload_service

logger = get_logger("ws")
router = APIRouter()

# 推送间隔（秒），与 upload.progress_interval_ms 保持一致的下限
_MIN_INTERVAL = 0.2
_MAX_INTERVAL = 2.0


@router.websocket("/ws/admin/upload/{upload_id}")
async def upload_progress_ws(websocket: WebSocket, upload_id: str) -> None:
    token = websocket.query_params.get("token") or ""
    try:
        auth_service.authenticate_token(token, require_admin=True)
    except BizError as exc:
        await websocket.close(code=4401, reason=exc.message)
        return

    await websocket.accept()
    logger.debug("WebSocket 连接建立: %s", upload_id)

    interval = _MIN_INTERVAL
    last_payload: str | None = None
    idle_ticks = 0

    try:
        while True:
            snapshot = upload_service.snapshot(upload_id)
            if snapshot is None:
                await websocket.send_text(
                    json.dumps({"code": 4005, "msg": "上传会话不存在或已过期", "data": None},
                               ensure_ascii=False)
                )
                break

            payload = json.dumps({"code": 0, "msg": "ok", "data": snapshot}, ensure_ascii=False)
            if payload != last_payload:
                await websocket.send_text(payload)
                last_payload = payload
                idle_ticks = 0
                # 有变化时加快推送，稳定后放慢，降低无效查询
                interval = _MIN_INTERVAL
            else:
                idle_ticks += 1
                interval = min(_MAX_INTERVAL, _MIN_INTERVAL * (1 + idle_ticks * 0.5))

            stage = snapshot.get("stage")
            if stage in ("finished", "failed"):
                logger.debug("WebSocket 结束（阶段=%s）: %s", stage, upload_id)
                break

            await asyncio.sleep(interval)

        try:
            await websocket.close()
        except RuntimeError:
            pass
    except WebSocketDisconnect:
        logger.debug("WebSocket 客户端断开: %s", upload_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("WebSocket 异常 %s: %s", upload_id, exc)
        try:
            await websocket.close(code=1011)
        except RuntimeError:
            pass
