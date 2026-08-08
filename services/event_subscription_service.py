"""出站事件订阅 repository + service。

subscribe / unsubscribe / list_subscriptions + notify（发 webhook + HMAC 验签）。

设计参见 当前文档分析.md §3.13。

notify 逻辑：事件发生时查匹配订阅（event_type 精确匹配 or event_type='all'），
对每个订阅用 httpx POST 推送 payload 到 callback_url，header 含 X-Signature（HMAC-SHA256）。
失败不阻塞主流程（异步 + 记日志）。
"""
import hashlib
import hmac
import json
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select

from infrastructure.database.models.event_subscription import EventSubscription
from infrastructure.database.repositories.base_repository import BaseRepository
from infrastructure.database.sessions import get_config_session


class EventSubscriptionRepository(BaseRepository[EventSubscription, dict[str, Any]]):
    """事件订阅 repository。"""
    _session_factory = get_config_session
    _model_class = EventSubscription
    _pk_name = 'pr_key_id'

    def _entity_to_dict(self, entity: EventSubscription, session) -> dict[str, Any]:
        return {
            'pr_key_id': entity.pr_key_id,
            'subscription_id': entity.subscription_id,
            'name': entity.name,
            'event_type': entity.event_type,
            'callback_url': entity.callback_url,
            'secret': entity.secret,
            'workspace_id': entity.workspace_id,
            'enabled': entity.enabled,
            'create_time': str(entity.create_time) if entity.create_time else None,
            'update_time': str(entity.update_time) if entity.update_time else None,
        }

    def list_all(self, workspace_id: int | None = None) -> list[dict[str, Any]]:
        """列出所有启用订阅（可选 workspace 过滤）。"""
        try:
            with self._get_session() as session:
                stmt = select(EventSubscription).where(EventSubscription.enabled == "1")
                if workspace_id is not None:
                    stmt = stmt.where(EventSubscription.workspace_id == workspace_id)
                stmt = stmt.order_by(EventSubscription.pr_key_id.desc())
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"EventSubscriptionRepository.list_all: {e}", exc_info=True)
            return []

    def delete_by_subscription_id(self, subscription_id: str) -> bool:
        """按 subscription_id 删除订阅。"""
        try:
            with self._get_session() as session:
                stmt = select(EventSubscription).where(EventSubscription.subscription_id == subscription_id)
                entity = session.scalar(stmt)
                if entity:
                    session.delete(entity)
                    session.commit()
                    return True
            return False
        except Exception as e:
            logger.error(f"EventSubscriptionRepository.delete_by_subscription_id ({subscription_id}): {e}", exc_info=True)
            return False

    def list_by_event_type(self, event_type: str, workspace_id: int | None = None) -> list[dict[str, Any]]:
        """查匹配订阅（event_type 精确匹配 or 'all'），可选 workspace 过滤。"""
        try:
            with self._get_session() as session:
                stmt = (
                    select(EventSubscription)
                    .where(EventSubscription.enabled == "1")
                    .where(EventSubscription.event_type.in_([event_type, "all"]))
                )
                if workspace_id is not None:
                    stmt = stmt.where(EventSubscription.workspace_id == workspace_id)
                entities = session.scalars(stmt).all()
                return [self._entity_to_dict(e, session) for e in entities]
        except Exception as e:
            logger.error(f"EventSubscriptionRepository.list_by_event_type ({event_type}): {e}", exc_info=True)
            return []


class EventSubscriptionService:
    """出站事件订阅服务。"""

    _table_ensured = False

    def _ensure_table(self):
        """确保 tb_event_subscription 表存在（幂等）。"""
        if EventSubscriptionService._table_ensured:
            return
        try:
            from infrastructure.database.base import Base
            from infrastructure.database.engines import get_config_engine
            from infrastructure.database.models.event_subscription import EventSubscription
            Base.metadata.create_all(
                get_config_engine(),
                tables=[EventSubscription.__table__],
                checkfirst=True,
            )
            EventSubscriptionService._table_ensured = True
        except Exception as e:
            logger.warning(f"[EventSubscription] _ensure_table failed (non-fatal): {e}")

    def subscribe(self, name: str, event_type: str, callback_url: str,
                  secret: str = "", workspace_id: int | None = None) -> dict | None:
        """创建订阅。"""
        self._ensure_table()
        try:
            from utils.id_generator import generate_uuid
            repo = EventSubscriptionRepository()
            entity = repo.create(
                subscription_id=f"SUB_{generate_uuid()[:16]}",
                name=name,
                event_type=event_type,
                callback_url=callback_url,
                secret=secret,
                workspace_id=workspace_id,
                enabled="1",
            )
            return repo._entity_to_dict(entity, None) if entity else None
        except Exception as e:
            logger.error(f"[EventSubscription] subscribe failed: {e}", exc_info=True)
            return None

    def unsubscribe(self, subscription_id: str) -> bool:
        """取消订阅（删除）。"""
        self._ensure_table()
        try:
            return EventSubscriptionRepository().delete_by_subscription_id(subscription_id)
        except Exception as e:
            logger.error(f"[EventSubscription] unsubscribe failed: {e}", exc_info=True)
            return False

    def list_subscriptions(self, workspace_id: int | None = None) -> list[dict]:
        """列出订阅。"""
        self._ensure_table()
        try:
            return EventSubscriptionRepository().list_all(workspace_id)
        except Exception as e:
            logger.error(f"[EventSubscription] list_subscriptions failed: {e}", exc_info=True)
            return []

    async def notify(self, event_type: str, payload: dict, workspace_id: int | None = None) -> int:
        """通知订阅者：查匹配订阅 + 发 webhook。

        Args:
            event_type: 事件类型（dispatch_completed/dispatch_failed/...）
            payload: 推送的数据
            workspace_id: workspace 过滤

        Returns:
            成功推送的订阅数
        """
        self._ensure_table()
        subs = EventSubscriptionRepository().list_by_event_type(event_type, workspace_id)
        if not subs:
            return 0
        success = 0
        body = json.dumps({"event_type": event_type, "payload": payload}, ensure_ascii=False, default=str)
        for sub in subs:
            try:
                headers = {"Content-Type": "application/json"}
                # HMAC-SHA256 验签
                if sub.get("secret"):
                    sig = hmac.new(
                        sub["secret"].encode("utf-8"),
                        body.encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest()
                    headers["X-Signature"] = sig
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.post(sub["callback_url"], content=body, headers=headers)
                    if resp.status_code < 400:
                        success += 1
                        logger.info(f"[EventSubscription] notify {sub['name']} ({event_type}): {resp.status_code}")
                    else:
                        logger.warning(f"[EventSubscription] notify {sub['name']} failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"[EventSubscription] notify {sub.get('name','')} error (non-fatal): {e}")
        return success
