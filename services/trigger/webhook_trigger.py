"""WebhookTrigger：Webhook 事件驱动触发器。

设计参见 docs/specs/2026-07-19-trigger-registry-design.md §6.3。

要点：
- 验签 HMAC-SHA256（GitHub/Stripe 通行风格，hmac.compare_digest 防时序攻击）
- IP 白名单（可选）
- timestamp 防重放（5 分钟窗口）
- verify 接受裸参数（body/headers/client_ip），便于纯函数测试；
  路由层从 Request 提取后调 verify
- start/stop 空实现：路由在 FastAPI 层注册，无需后台任务
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import time
from typing import Any

from fastapi import HTTPException
from loguru import logger

from .base import ITrigger


class WebhookTrigger(ITrigger):
    """Webhook 触发器：入站事件 → 验签 → 调度。"""

    async def start(self) -> None:
        """空实现：路由在 FastAPI app 层注册，无需启动后台任务。"""
        logger.info(f"[WebhookTrigger] {self.trigger_id} ready (routes registered at app layer)")

    async def stop(self) -> None:
        """空实现。"""
        pass

    async def verify(
        self,
        body: bytes,
        headers: dict[str, str],
        client_ip: str,
    ) -> dict[str, Any]:
        """校验签名 + IP 白名单 + timestamp 防重放。

        Args:
            body: 请求体原始字节（用于 HMAC 计算）
            headers: 请求头（含 X-Webhook-Signature, X-Webhook-Timestamp）
            client_ip: 客户端 IP

        Returns:
            event dict: {payload, headers, client_ip} 传给 handle
        Raises:
            HTTPException: 401（签名/timestamp 失败）/ 403（IP 不允许）
        """
        # 1. IP 白名单校验（可选）
        allowed = self.config.get("allowed_ips", [])
        if allowed:
            try:
                ip = ipaddress.ip_address(client_ip)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"invalid client_ip: {client_ip}")
            ok = False
            for cidr in allowed:
                try:
                    if ip in ipaddress.ip_network(cidr, strict=False):
                        ok = True
                        break
                except ValueError:
                    continue
            if not ok:
                raise HTTPException(status_code=403, detail="IP not allowed")

        # 2. HMAC-SHA256 验签
        raw_secret = self.config.get("secret", "")
        if not raw_secret:
            raise HTTPException(status_code=500, detail="webhook trigger config missing 'secret'")
        # 通过 secret_store 自动解密：支持 enc: 前缀密文存储（设计参见 secret-encryption-design.md）
        # 无 enc: 前缀视为明文直接返回（向下兼容）
        from utils.crypto.secret_store import decrypt_secret
        secret = decrypt_secret(raw_secret)
        sig = headers.get("X-Webhook-Signature", "")
        if not sig:
            raise HTTPException(status_code=401, detail="missing X-Webhook-Signature")
        expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise HTTPException(status_code=401, detail="Invalid signature")

        # 3. timestamp 防重放（5 分钟窗口）
        ts_str = headers.get("X-Webhook-Timestamp")
        if ts_str:
            try:
                ts = int(ts_str)
                if abs(int(time.time()) - ts) > 300:
                    raise HTTPException(status_code=401, detail="Timestamp out of range (replay suspected)")
            except ValueError:
                raise HTTPException(status_code=401, detail="invalid X-Webhook-Timestamp")

        # 4. 解析 payload
        import json
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = body.decode("utf-8", errors="replace")

        return {
            "payload": payload,
            "headers": dict(headers),
            "client_ip": client_ip,
        }
