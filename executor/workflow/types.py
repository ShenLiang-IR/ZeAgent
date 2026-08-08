from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    Optional,
    Union,
)
from uuid import uuid4
from loguru import logger
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


@dataclass
class TaskResultEnvelope:
    """L2 结构化任务结果（前向兼容，opt-in，不强制迁移 str 契约）。

    当前 results 通道仍以 str 为主；消费者经 result_to_text / is_error_result
    同时兼容 str 与 envelope。未来需要结构化工件/错误细分时可用 envelope。
    """
    status: TaskStatus = TaskStatus.COMPLETED
    output: str = ""
    artifacts: list = field(default_factory=list)
    error: str = ""


def result_to_text(result: Any) -> str:
    """把 result（str 或 TaskResultEnvelope）归一为文本（_build_input/截断用）。"""
    if isinstance(result, TaskResultEnvelope):
        if result.status == TaskStatus.FAILED:
            return f"error: {result.error}" if result.error else "error: unknown"
        return result.output or ""
    if isinstance(result, str):
        return result
    return str(result) if result is not None else ""


def is_error_result(result: Any) -> bool:
    """判断 task result 是否表示失败。

    兼容 str（'error:' 前缀）与 TaskResultEnvelope（status==FAILED）。
    """
    if isinstance(result, TaskResultEnvelope):
        return result.status == TaskStatus.FAILED
    return isinstance(result, str) and result.startswith("error:")
class ExecutionEventType(str, Enum):
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_TIMEOUT = "task_timeout"
    PROGRESS_UPDATE = "progress_update"
    CONTENT_CHUNK = "content_chunk"
    ERROR = "error"
@dataclass
class ExecutionEvent:
    type: ExecutionEventType
    data: Any
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    def __repr__(self) -> str:
        return f"ExecutionEvent(type={self.type.value}, data={self.data!r})"
@dataclass
class Task:
    id: str
    target: Union[str, Callable]
    payload: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 300.0
    retry_count: int = 0
    max_retries: int = 0
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    _status: TaskStatus = field(default=TaskStatus.PENDING, init=False, repr=False)
    _result: Any = field(default=None, init=False, repr=False)
    _exception: Optional[Exception] = field(default=None, init=False, repr=False)
    @property
    def status(self) -> TaskStatus:
        return self._status
    @status.setter
    def status(self, value: TaskStatus):
        self._status = value
    @property
    def result(self) -> Any:
        return self._result
    @result.setter
    def result(self, value: Any):
        self._result = value
        self._status = TaskStatus.COMPLETED
    @property
    def exception(self) -> Optional[Exception]:
        return self._exception
    @exception.setter
    def exception(self, value: Exception):
        self._exception = value
        self._status = TaskStatus.FAILED
    def can_retry(self) -> bool:
        return self._status == TaskStatus.FAILED and self.retry_count < self.max_retries
    def increment_retry(self):
        self.retry_count += 1
    @classmethod
    def create(
        cls,
        target: Union[str, Callable],
        payload: Dict[str, Any],
        **kwargs
    ) -> "Task":
        return cls(
            id=str(uuid4()),
            target=target,
            payload=payload,
            **kwargs
        )
@dataclass
class TaskHandle:
    task_id: str
    future: asyncio.Future
    _event_queue: asyncio.Queue
    _task: Optional[Task] = field(default=None, init=False, repr=False)
    async def result(self) -> Any:
        return await self.future
    async def stream_events(
        self
    ) -> AsyncGenerator[ExecutionEvent, None]:
        while True:
            event = await self._event_queue.get()
            if event is None:
                break
            yield event
    @property
    def status(self) -> TaskStatus:
        if self.future.done():
            if self.future.exception():
                return TaskStatus.FAILED
            return TaskStatus.COMPLETED
        return TaskStatus.RUNNING
    @property
    def is_done(self) -> bool:
        return self.future.done()
    def cancel(self) -> bool:
        result = self.future.cancel()
        if not result and not self.future.done():
            logger.warning(
                f"[TaskHandle] 任务 {self.task_id} 无法取消（已开始，future 不会真正中断）"
            )
        return result
    def add_done_callback(self, callback: Callable, *args: Any) -> None:
        self.future.add_done_callback(callback, *args)
    def __await__(self):
        return self.future.__await__()
    def __repr__(self) -> str:
        return f"TaskHandle(id={self.task_id}, status={self.status.value})"