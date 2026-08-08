"""审批 WebSocket 实时通知。

连接：ws://host/ws/approvals?token=<jwt_token>
协议：
  → 审批通过/拒绝：{"type":"approval_result","agent_id":"...","agent_name":"...","status":"approved|rejected"}
  → 新提交审批：{"type":"new_submission","agent_id":"...","agent_name":"...","submitter":"..."}
  → 刷新代办数：{"type":"refresh_todo","count":N}

多 worker 支持：有 REDIS_URL 时通过 Redis pub/sub 跨 worker 广播；
无 Redis 时仅本进程直推（本地开发兼容）。
"""

import json
import os
from typing import Dict, Set
from fastapi import WebSocket, WebSocketDisconnect, Query
from loguru import logger


# Redis pub/sub channel
_WS_CHANNEL = "ws:approvals"


def _get_redis():
    """获取 Redis 连接，无 REDIS_URL 时返回 None。"""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        import redis
        return redis.from_url(redis_url, decode_responses=True)
    except ImportError:
        logger.warning("[WS] redis-py not installed, falling back to in-process only")
        return None
    except Exception as e:
        logger.warning(f"[WS] Redis connection failed: {e}")
        return None


class ConnectionManager:
    """管理 WebSocket 连接，按 user_id 索引。

    多 worker 模式：
    - 本进程连接的 WS 直接推送
    - 同时 publish 到 Redis channel，其他 worker 的 _redis_subscriber 收到后推给它们的连接
    """

    def __init__(self):
        # user_id → set of WebSocket connections
        self._connections: Dict[str, Set[WebSocket]] = {}
        # user_id → is_admin
        self._admins: Set[str] = set()
        self._redis = _get_redis()

    async def connect(self, ws: WebSocket, user_id: str, is_admin: bool):
        await ws.accept()
        self._connections.setdefault(user_id, set()).add(ws)
        if is_admin:
            self._admins.add(user_id)
        logger.info(f"[WS] {user_id} connected (admin={is_admin}), total users={len(self._connections)}")

    def disconnect(self, ws: WebSocket, user_id: str):
        if user_id in self._connections:
            self._connections[user_id].discard(ws)
            if not self._connections[user_id]:
                del self._connections[user_id]
        if user_id in self._admins and user_id not in self._connections:
            self._admins.discard(user_id)

    async def _local_send_to_user(self, user_id: str, msg: str):
        """本进程直推给指定用户。"""
        dead = set()
        for ws in self._connections.get(user_id, set()):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws, user_id)

    async def _local_broadcast_admins(self, msg: str):
        """本进程直推给所有 admin。"""
        for uid in list(self._admins):
            await self._local_send_to_user(uid, msg)

    async def send_to_user(self, user_id: str, data: dict):
        """推送给指定用户（跨 worker）。"""
        msg = json.dumps(data, ensure_ascii=False)
        await self._local_send_to_user(user_id, msg)
        if self._redis:
            try:
                self._redis.publish(_WS_CHANNEL, json.dumps({
                    "target": "user", "user_id": str(user_id), "msg": msg
                }))
            except Exception:
                pass  # Redis 故障不影响本进程直推

    async def broadcast_to_admins(self, data: dict):
        """推送给所有 admin（跨 worker）。"""
        msg = json.dumps(data, ensure_ascii=False)
        await self._local_broadcast_admins(msg)
        if self._redis:
            try:
                self._redis.publish(_WS_CHANNEL, json.dumps({
                    "target": "admins", "msg": msg
                }))
            except Exception:
                pass

    def get_admin_count(self) -> int:
        return len(self._admins)


# 全局单例
manager = ConnectionManager()


async def _redis_subscriber():
    """Redis 订阅协程：收到跨 worker 消息后本进程直推。

    在 FastAPI lifespan startup 中启动。
    """
    if not manager._redis:
        return
    try:
        pubsub = manager._redis.pubsub()
        pubsub.subscribe(_WS_CHANNEL)
        logger.info(f"[WS] Redis subscriber started on channel '{_WS_CHANNEL}'")
        for raw in pubsub.listen():
            if raw.get("type") != "message":
                continue
            try:
                data = json.loads(raw["data"])
                msg = data["msg"]
                if data.get("target") == "user":
                    await manager._local_send_to_user(data["user_id"], msg)
                elif data.get("target") == "admins":
                    await manager._local_broadcast_admins(msg)
            except Exception:
                pass
    except Exception as e:
        logger.error(f"[WS] Redis subscriber error: {e}")


# ── WebSocket 端点 ──

async def ws_approvals_endpoint(websocket: WebSocket, token: str = Query("")):
    """审批 WebSocket 入口。query 参数 token 鉴权。"""
    user_id = "anonymous"
    is_admin = False
    try:
        from services.auth_service import AuthService
        payload = AuthService().verify_token(token) if token else {}
        user_id = str(payload.get("user_id") or "anonymous")
        roles = payload.get("roles", [])
        is_admin = "admin" in roles
    except Exception as e:
        logger.warning(f"[WS] token decode failed: {e}")
        await websocket.close(code=4001, reason="auth failed")
        return

    await manager.connect(websocket, user_id, is_admin)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug(f"[WS] {user_id} error: {e}")
    finally:
        manager.disconnect(websocket, user_id)
        logger.info(f"[WS] {user_id} disconnected")


# ── 外部调用函数（供 approval 路由使用）──

async def notify_approval_result(creator_id: str, agent_id: str, agent_name: str, status: str, reason: str = ""):
    """审批通过/拒绝 → 通知提交人。"""
    msg = {
        "type": "approval_result",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "status": status,
    }
    if reason:
        msg["reason"] = reason
    await manager.send_to_user(str(creator_id), msg)


async def notify_new_submission(agent_id: str, agent_name: str, submitter: str):
    """新提交审批 → 通知所有在线 admin。"""
    await manager.broadcast_to_admins({
        "type": "new_submission",
        "agent_id": agent_id,
        "agent_name": agent_name,
        "submitter": submitter,
    })


async def notify_todo_count(user_id: str, count: int):
    """刷新代办计数。"""
    await manager.send_to_user(str(user_id), {
        "type": "refresh_todo",
        "count": count,
    })
