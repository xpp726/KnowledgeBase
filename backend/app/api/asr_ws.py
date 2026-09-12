"""ASR 语音输入 WebSocket 代理。

KB 前端统一走本端点（/api/asr/ws?token=...），后端校验 JWT 后
将连接双向转发到 ASR 后端的实时识别 WebSocket（asr_ws_url，见 config）。

协议透传：客户端 ⇄ ASR 之间 text(JSON) / binary(PCM16) 原样转发，
ASR 协议（start / partial / final / stop / session_end / error）由前端
按 ASR 项目约定处理，本代理不解析内容。
"""

from __future__ import annotations

import asyncio
import logging

import websockets
from fastapi import APIRouter, WebSocket

from app.config import get_settings
from app.services.auth import decode_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/asr", tags=["asr"])


@router.websocket("/ws")
async def asr_proxy(ws: WebSocket) -> None:
    """校验 token 后，把本连接转发到 ASR 后端实时识别端点。

    先 accept 再校验：uvicorn 会把 accept 前的 close 渲染成 HTTP 403，
    先 accept 可让客户端拿到 4401/4403 等 WebSocket close 码。
    """
    await ws.accept()
    settings = get_settings()
    token = ws.query_params.get("token", "")
    if not token or not decode_token(token):
        await ws.close(code=4401, reason="未登录或登录已过期")
        return

    # 先建立到 ASR 后端的连接；不可达时给客户端可识别的 error 后关闭
    try:
        asr = await websockets.connect(settings.asr_ws_url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ASR WebSocket 连接失败: %s", exc)
        await ws.send_text(
            '{"type":"error","message":"语音服务不可用，请确认 ASR 后端已启动"}'
        )
        await ws.close(code=4403, reason="asr unavailable")
        return

    logger.info("ASR 语音代理会话建立（user=%s）", _token_user(token))

    async def client_to_asr() -> None:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                return
            if msg.get("bytes") is not None:
                await asr.send(msg["bytes"])
            elif msg.get("text") is not None:
                await asr.send(msg["text"])

    async def asr_to_client() -> None:
        while True:
            data = await asr.recv()
            if isinstance(data, bytes):
                await ws.send_bytes(data)
            else:
                await ws.send_text(data)

    try:
        await asyncio.gather(client_to_asr(), asr_to_client())
    except Exception as exc:  # noqa: BLE001
        logger.info("ASR 语音代理会话结束: %s", exc)
    finally:
        await asr.close()
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


def _token_user(token: str) -> str:
    payload = decode_token(token) or {}
    return str(payload.get("username", "?"))
