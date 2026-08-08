"""人工审核 registry — dispatch_id → asyncio.Queue（spec §5.1）。

plan_executor pause 时 register + await queue.get()；
POST /api/plan/review 时 put 唤醒。
"""
import asyncio
from typing import Optional, Dict, Any
from loguru import logger


class ReviewRegistry:
    """dispatch_id → asyncio.Queue 的审核等待注册表（类级共享）。"""

    _queues: Dict[str, asyncio.Queue] = {}

    @classmethod
    def register(cls, dispatch_id: str) -> asyncio.Queue:
        """注册 dispatch_id，返回新 queue（maxsize=1）。"""
        q = asyncio.Queue(maxsize=1)
        cls._queues[dispatch_id] = q
        return q

    @classmethod
    def get(cls, dispatch_id: str) -> Optional[asyncio.Queue]:
        """获取已注册的 queue（未注册返回 None）。"""
        return cls._queues.get(dispatch_id)

    @classmethod
    def put(cls, dispatch_id: str, result: Dict[str, Any]) -> bool:
        """提交审核结果，唤醒 plan_executor。未注册返回 False。"""
        q = cls._queues.get(dispatch_id)
        if q is None:
            logger.warning(f"[ReviewRegistry] dispatch {dispatch_id} 未注册")
            return False
        q.put_nowait(result)
        return True

    @classmethod
    async def await_review(cls, dispatch_id: str, timeout: float = 300) -> Optional[Dict[str, Any]]:
        """plan_executor pause 时调用，阻塞等待审核结果。超时返回 reject。

        无论成功/超时/异常，finally 都清理 dispatch_id，防 queue 永久残留（#13）。
        """
        q = cls._queues.get(dispatch_id)
        if q is None:
            logger.warning(f"[ReviewRegistry] {dispatch_id} 未注册，返回 reject")
            return {"action": "reject", "reason": "not_registered"}
        try:
            result = await asyncio.wait_for(q.get(), timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"[ReviewRegistry] {dispatch_id} 审核超时({timeout}s)，按 reject 处理")
            return {"action": "reject", "reason": "timeout"}
        finally:
            cls.remove(dispatch_id)

    @classmethod
    def remove(cls, dispatch_id: str) -> None:
        """清理已完成的 dispatch_id。"""
        cls._queues.pop(dispatch_id, None)
